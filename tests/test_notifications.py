import hashlib
import hmac
import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient

from aigovkit import notification_delivery, notifications
from aigovkit.storage import PostgresInventory
from aigovkit.tenancy import schema_for
from main import app


def test_webhook_signature_covers_timestamp_and_exact_body():
    secret = secrets.token_hex(32)
    destination = notification_delivery.Webhook.model_validate(
        {
            "url": "https://example.invalid/endpoint",
            "signing_key": secret,
        }
    )
    payload = b'{"event":"incident.alerted"}'
    headers = notification_delivery.signed_headers(
        destination, payload, "message-id", "123"
    )
    digest = hmac.new(secret.encode(), b"v1.123." + payload, hashlib.sha256).hexdigest()
    assert headers["X-AIGovKit-Signature"] == "v1=" + digest
    assert headers["Idempotency-Key"] == "message-id"


def test_smtp_message_uses_tls_and_a_stable_minimal_envelope(monkeypatch):
    messages = []

    class SMTP:
        def __init__(self, host, port, **kwargs):
            assert host == "smtp.example.invalid" and port == 465
            assert kwargs["context"].check_hostname

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send_message(self, message):
            messages.append(message)

    monkeypatch.setattr(notification_delivery.smtplib, "SMTP_SSL", SMTP)
    destination = notification_delivery.SMTP(
        host="smtp.example.invalid",
        sender="alerts@example.invalid",
        recipient="ops@example.invalid",
    )
    event = {"id": "stable-id", "event": "incident.alerted", "priority": "urgent"}
    notification_delivery.deliver_smtp(destination, event)
    notification_delivery.deliver_smtp(destination, event)
    assert [item["Message-ID"] for item in messages] == [
        "<stable-id@example.invalid>"
    ] * 2
    assert "incident.alerted" in messages[0].get_content()


def test_notifications_are_transactional_scoped_and_retried(monkeypatch):
    dsn = os.getenv("AIGOVKIT_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Disposable PostgreSQL is required.")
    tenant, other = (f"test-{secrets.token_hex(8)}" for _ in range(2))
    members = [
        {"id": role, "role": role, "key": secrets.token_urlsafe(32)}
        for role in ("editor", "scheduler", "reader")
    ]
    outside = {"id": "editor", "role": "editor", "key": secrets.token_urlsafe(32)}
    monkeypatch.setenv(
        "AIGOVKIT_TENANTS",
        json.dumps(
            [
                {"id": tenant, "members": members},
                {"id": other, "members": [outside]},
            ]
        ),
    )
    monkeypatch.setenv("AIGOVKIT_DATABASE_URL", dsn)
    monkeypatch.setenv(
        "AIGOVKIT_NOTIFICATION_DESTINATIONS",
        json.dumps(
            {
                tenant: {
                    "smtp": {
                        "host": "smtp.example.invalid",
                        "sender": "alerts@example.invalid",
                        "recipient": "ops@example.invalid",
                    }
                },
            }
        ),
    )
    for scope in (tenant, other):
        PostgresInventory(dsn, schema_for(scope)).initialize()
    editor, scheduler, reader = [
        TestClient(app, headers={"X-API-Key": member["key"]}) for member in members
    ]
    stranger = TestClient(app, headers={"X-API-Key": outside["key"]})
    route = "/v1/notifications"
    assert (
        reader.put(route + "/settings", json={"channels": ["smtp"]}).status_code == 403
    )
    assert (
        editor.put(route + "/settings", json={"channels": ["smtp"]}).status_code == 200
    )
    assert "ops@example.invalid" not in editor.get(route + "/settings").text
    assert editor.post(route + "/run").status_code == 403
    assert (
        editor.put(
            "/v1/organisation",
            json={
                "name": "Demo",
                "sector": "Technology",
                "jurisdiction": "UK",
                "adoption_stage": "piloting",
            },
        ).status_code
        == 200
    )
    draft = editor.post(
        "/v1/policy-drafts",
        json={
            "template_id": "agent-security",
            "owner": "Security",
            "scope": "Private scope marker",
            "review_days": 90,
            "applies_to_agents": False,
        },
    ).json()
    revisions = f"/v1/policy-drafts/{draft['id']}/revisions"
    assert (
        editor.post(
            revisions,
            json={
                "expected_version": 0,
                "clause_texts": {draft["clauses"][0]["id"]: "Review fixture."},
            },
        ).status_code
        == 201
    )
    assert editor.post(revisions + "/1/submit").status_code == 200
    assert editor.post(revisions + "/1/submit").status_code == 409
    assert len(editor.get(route).json()) == 2
    assert [row["channel"] for row in reader.get(route).json()] == ["in_app"]
    assert stranger.get(route).json() == []

    calls = []

    def send(config, actor_tenant, item):
        payload = notification_delivery.packet(actor_tenant, item)
        assert set(payload) == {"schema", "id", "event", "priority", "occurred_at"}
        calls.append(payload)
        if len(calls) == 1:
            raise notification_delivery.DeliveryFailure("smtp_451", retry=True)

    monkeypatch.setattr(notifications, "deliver", send)
    assert scheduler.post(route + "/run").json()["queued"] == 1
    assert scheduler.post(route + "/run").json()["delivered"] == 0
    assert (
        next(row for row in editor.get(route).json() if row["channel"] == "smtp")[
            "last_error"
        ]
        == "smtp_451"
    )
    schema = schema_for(tenant)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            psycopg.sql.SQL("SET search_path TO {}").format(
                psycopg.sql.Identifier(schema)
            )
        )
        conn.execute(
            "UPDATE notification_outbox SET next_attempt_at=clock_timestamp() WHERE channel='smtp'"
        )
    with ThreadPoolExecutor() as workers:
        results = list(
            workers.map(lambda _: scheduler.post(route + "/run").json(), range(2))
        )
    assert sum(result["delivered"] for result in results) == 1
    assert len(calls) == 2 and calls[0] == calls[1]
    sent = next(row for row in editor.get(route).json() if row["channel"] == "smtp")
    assert sent["attempts"] == 2 and sent["state"] == "delivered"

    history_path = route + f"/{sent['event_id']}/attempts"
    history = editor.get(history_path).json()
    assert [row["state"] for row in history] == ["queued", "delivered"]
    assert reader.get(history_path).status_code == 403
    assert stranger.get(history_path).json() == []

    second = editor.post(
        "/v1/policy-drafts",
        json={
            "template_id": "agent-security",
            "owner": "Security",
            "scope": "Second fixture",
            "review_days": 90,
            "applies_to_agents": False,
        },
    ).json()
    second_path = f"/v1/policy-drafts/{second['id']}/revisions"
    assert (
        editor.post(
            second_path,
            json={
                "expected_version": 0,
                "clause_texts": {second["clauses"][0]["id"]: "Fixture two."},
            },
        ).status_code
        == 201
    )
    assert editor.post(second_path + "/1/submit").status_code == 200
    with psycopg.connect(dsn) as conn:
        conn.execute(
            psycopg.sql.SQL("SET search_path TO {}").format(
                psycopg.sql.Identifier(schema)
            )
        )
        conn.execute(
            "UPDATE notification_outbox SET attempts=4 WHERE channel='smtp' AND state='queued'"
        )

    def refuse(*_):
        raise notification_delivery.DeliveryFailure("smtp_451", retry=True)

    monkeypatch.setattr(notifications, "deliver", refuse)
    assert scheduler.post(route + "/run").json()["dead"] == 1
    assert scheduler.post(route + "/run").json()["dead"] == 0
