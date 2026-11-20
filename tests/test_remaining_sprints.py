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
        for role in ("editor", "scheduler", "reader", "reviewer", "publisher")
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
    editor, scheduler, reader, reviewer, publisher, outside = [
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

    draft = f"{learning}/course-drafts/local-course"
    content = {
        "title": "Local course",
        "lesson": "Use approved tools",
        "question": "Which tools?",
        "choices": ["Approved", "Any"],
        "correct_choice": 0,
        "expected_revision": 0,
    }
    saved = editor.put(draft, json=content)
    assert saved.status_code == 200, saved.text
    assert editor.put(draft, json=content).status_code == 409
    assert reader.get(learning + "/course-drafts").status_code == 403
    assert (
        editor.post(draft + "/publish", json={"expected_revision": 1}).status_code
        == 403
    )
    published = publisher.post(draft + "/publish", json={"expected_revision": 1})
    assert published.status_code == 200, published.text
    course_id = published.json()["id"]
    assert (
        reader.get(f"{learning}/courses/{course_id}").json()["choices"]
        == content["choices"]
    )
    assert outside.get(f"{learning}/courses/{course_id}").status_code == 404
    enrolment = editor.put(
        learning + "/enrolment-rules/team",
        json={
            "course_id": course_id,
            "role": "reader",
            "refresher_days": 30,
        },
    )
    assert enrolment.status_code == 200, enrolment.text
    run = learning + "/enrolments/run"
    first = scheduler.post(run)
    assert first.json() == {"assigned": 1}, first.text
    assert scheduler.post(run).json() == {"assigned": 0}
    assigned = reader.get(learning + "/assignments").json()[0]
    assert assigned["course_id"] == course_id
    assert (
        editor.put(
            draft, json={**content, "correct_choice": 1, "expected_revision": 1}
        ).status_code
        == 200
    )
    assert (
        publisher.post(draft + "/publish", json={"expected_revision": 2}).json()["id"]
        != course_id
    )
    quiz = f"{learning}/assignments/{assigned['id']}/answer"
    assert reader.post(quiz, json={"choice": 0}).json()["status"] == "completed"
    assert scheduler.post(run).json() == {"assigned": 0}
    with store.connect() as conn:
        conn.execute(
            """UPDATE foundation_documents SET body=jsonb_set(body,'{completed_at}',
               to_jsonb((now()-interval '31 days')::text)) WHERE kind='learning_assignment' AND id=%s""",
            (assigned["id"],),
        )
    assert scheduler.post(run).json() == {"assigned": 1}
    store.put_document(
        "register_risk",
        "due-risk",
        {
            "title": "Pilot risk",
            "treatment_owner": "editor",
            "due_date": today,
            "status": "open",
            "residual_score": 16,
        },
    )
    assert scheduler.post("/v1/reassessments/run").json() == {"created": 1}
    assert scheduler.post("/v1/reassessments/run").json() == {"created": 0}
    assert editor.get("/v1/reassessments").json()[0]["title"] == "Pilot risk"
    assert reader.get("/v1/reassessments").status_code == 403
    assert outside.get("/v1/reassessments").json() == []
    expanded = editor.post(board, json=options).json()
    assert expanded["metrics"]["high_residual_risks"] == 1
    assert expanded["evidence_sources"]["risks"] == "observed"

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
