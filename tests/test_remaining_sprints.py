import json
import os
import secrets
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from aigovkit import notifications
from aigovkit.notification_delivery import DeliveryFailure
from aigovkit.storage import PostgresInventory
from aigovkit.tenancy import schema_for
from main import app


def test_reporting_learning_and_audit_export(monkeypatch):
    dsn = os.getenv("AIGOVKIT_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Disposable PostgreSQL is required.")
    tenant, other = (f"test-{secrets.token_hex(8)}" for _ in range(2))
    members = [
        {"id": role, "role": role, "key": secrets.token_urlsafe(32)}
        for role in ("editor", "scheduler", "reader", "reviewer")
    ]
    outsider = {**members[0], "key": secrets.token_urlsafe(32)}
    monkeypatch.setenv("AIGOVKIT_DATABASE_URL", dsn)
    monkeypatch.setenv(
        "AIGOVKIT_TENANTS",
        json.dumps(
            [
                {"id": tenant, "members": members},
                {"id": other, "members": [outsider]},
            ]
        ),
    )
    monkeypatch.setenv(
        "AIGOVKIT_NOTIFICATION_DESTINATIONS",
        json.dumps(
            {
                tenant: {
                    "audit_webhook": {
                        "url": "https://audit.example.invalid/ingest",
                        "signing_key": secrets.token_hex(32),
                    }
                }
            }
        ),
    )
    store = PostgresInventory(dsn, schema_for(tenant))
    store.initialize()
    PostgresInventory(dsn, schema_for(other)).initialize()
    editor, scheduler, reader, reviewer, outside = [
        TestClient(app, headers={"X-API-Key": member["key"]})
        for member in [*members, outsider]
    ]
    today = datetime.now(UTC).date().isoformat()
    learning = "/v1/learning"
    course = reader.get(learning + "/courses").json()[0]
    assert course["id"] == "responsible-use-v1"
    assert not {"answer", "correct", "correct_choice"}.intersection(course)
    payload = {"course_id": course["id"], "learner": "reader", "due": today}
    assert reader.post(learning + "/assignments", json=payload).status_code == 403
    result = editor.post(learning + "/assignments", json=payload)
    assert result.status_code == 201, result.text
    assignment = result.json()
    assert outside.get(learning + "/assignments").json() == []
    assert scheduler.post(learning + "/run").json() == {"emitted": 1}
    assert scheduler.post(learning + "/run").json() == {"emitted": 0}
    assert reader.get("/v1/notifications").json()[0]["action"] == "learning.reminder"
    assert reviewer.get("/v1/notifications").json() == []
    answer = f"{learning}/assignments/{assignment['id']}/answer"
    assert editor.post(answer, json={"choice": 0}).status_code == 404
    assert reader.post(answer, json={"choice": 1}).json()["score"] == 0
    completed = reader.post(answer, json={"choice": 0}).json()
    assert completed["status"] == "completed"
    assert reader.post(answer, json={"choice": 1}).json() == completed

    board = "/v1/board-reports"
    options = {"start": today, "end": today}
    assert reader.get(board).status_code == 403
    result = editor.post(board, json=options)
    assert result.status_code == 201, result.text
    report = result.json()
    assert report["metrics"]["completed_training"] == 1
    assert report["coverage"]["assessments"] == "no_assessment_records"
    export = f"{board}/{report['id']}/export"
    assert outside.get(export + "/json").status_code == 404
    assert editor.get(export + "/json").json() == report
    for fmt, signature in [("csv", b"Metric,Value"), ("pdf", b"%PDF"), ("docx", b"PK")]:
        result = editor.get(f"{export}/{fmt}")
        assert result.content.startswith(signature)
    assert editor.put(board + "/schedule", json={"enabled": True}).status_code == 200
    assert scheduler.post(board + "/run").json()["created"]
    assert not scheduler.post(board + "/run").json()["created"]

    batches = []

    def transport(destination, event):
        assert destination.url == "https://audit.example.invalid/ingest"
        batches.append(event)
        if len(batches) == 1:
            raise DeliveryFailure("unavailable", retry=True)

    monkeypatch.setattr(notifications, "deliver_webhook", transport)
    exporter = "/v1/audit-exporter"
    assert editor.post(exporter + "/run").status_code == 403
    assert reader.get(exporter + "/history").status_code == 403
    assert scheduler.post(exporter + "/run").json()["state"] == "queued"
    assert scheduler.post(exporter + "/run").json()["state"] == "idle"
    assert scheduler.post("/v1/notifications/run").json()["queued"] == 1
    assert editor.get(exporter + "/history").json()[0]["last_error"] == "unavailable"
    with store.connect() as conn:
        conn.execute(
            "UPDATE notification_outbox SET next_attempt_at=clock_timestamp() "
            "WHERE action='audit_export.batch'"
        )
    assert scheduler.post("/v1/notifications/run").json()["delivered"] == 1
    assert editor.get(exporter + "/history").json()[0]["state"] == "delivered"
    assert outside.get(exporter + "/history").json() == []
    batch_path = f"{exporter}/batches/{batches[0]['batch']['batch_id']}"
    assert editor.get(batch_path + "/json").json() == batches[0]["batch"]
    assert editor.get(batch_path + "/csv").content.startswith(
        b"event_id,occurred_at,action"
    )
    assert outside.get(batch_path + "/json").status_code == 404
    assert batches[0] == batches[1]
    for event in batches[0]["batch"]["events"]:
        assert set(event) == {"event_id", "occurred_at", "action"}
