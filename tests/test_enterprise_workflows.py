import json
import os
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aigovkit.connectors import JsonInventoryConnector
from aigovkit.storage import PostgresInventory
from aigovkit.tenancy import schema_for
from main import app

SCENARIO = {
    "role": "support",
    "agent_id": "helper",
    "asset_id": "tickets",
    "action": "read",
    "department_id": "customer-support",
    "purpose": "ticket-summary",
    "policy_version": "1.1.0",
}


@pytest.fixture
def tenant(monkeypatch):
    dsn = os.getenv("AIGOVKIT_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Use disposable PostgreSQL.")
    tenant_id = f"test-{secrets.token_hex(8)}"
    members = [
        {"id": role, "role": role, "key": secrets.token_urlsafe(32)}
        for role in (
            "editor",
            "publisher",
            "gateway",
            "identity_admin",
            "reviewer",
            "auditor",
        )
    ]
    monkeypatch.setenv(
        "AIGOVKIT_TENANTS", json.dumps([{"id": tenant_id, "members": members}])
    )
    monkeypatch.setenv("AIGOVKIT_DATABASE_URL", dsn)
    store = PostgresInventory(dsn, schema_for(tenant_id))
    store.initialize()
    sample = (
        Path(__file__).resolve().parents[1] / "examples" / "department-inventory.json"
    )
    store.put(JsonInventoryConnector(sample).records())
    return {
        item["role"]: TestClient(app, headers={"X-API-Key": item["key"]})
        for item in members
    }


def test_gate_deployment_rollback_verification_and_suspend(tenant):
    editor, publisher, gateway = (
        tenant[key] for key in ("editor", "publisher", "gateway")
    )
    check = "/v1/guardrail-checks"
    assert gateway.get("/v1/inventory").status_code == 403
    assert gateway.post(check, json=SCENARIO).status_code == 403
    allow = editor.post(
        "/v1/guardrail-rules", json={"scope": SCENARIO, "decision": "allow"}
    ).json()
    deny = editor.post(
        "/v1/guardrail-rules", json={"scope": SCENARIO, "decision": "deny"}
    ).json()

    def deploy(version, operation, rule=None):
        return publisher.post(
            "/v1/guardrail-deployments",
            json={
                "agent_id": "helper",
                "operation": operation,
                "expected_version": version,
                "revision_id": rule["id"] if rule else None,
            },
        )

    assert deploy(0, "rollback", allow).status_code == 409
    assert deploy(0, "deploy", allow).status_code == 200
    assert deploy(0, "deploy", deny).status_code == 409
    assert gateway.post(check, json=SCENARIO | {"role": "unknown"}).status_code == 403
    observed = gateway.post(check, json=SCENARIO)
    assert observed.status_code == 200
    verification = publisher.post(
        "/v1/guardrail-verifications",
        json={
            "check_id": observed.json()["id"],
            "expected": "allow",
        },
    )
    assert verification.json()["matched"]

    import httpx
    from fastapi import FastAPI

    from aigovkit.gate_adapter import EnforcedRoutes

    operations = []
    protected = FastAPI()

    @protected.post("/operation")
    def operation():
        operations.append("executed")
        return {"executed": True}

    def gate(request):
        result = gateway.post(check, json=json.loads(request.content))
        return httpx.Response(result.status_code, json=result.json())

    guarded = TestClient(
        EnforcedRoutes(
            protected,
            "https://gate.example.invalid",
            gateway.headers["X-API-Key"],
            {("POST", "/operation"): SCENARIO},
            transport=httpx.MockTransport(gate),
        )
    )
    assert guarded.post("/operation").status_code == 200
    assert operations == ["executed"]
    assert deploy(1, "deploy", deny).status_code == 200
    assert guarded.post("/operation").status_code == 403
    assert operations == ["executed"]
    assert deploy(2, "rollback", allow).status_code == 200
    assert guarded.post("/operation").status_code == 200
    assert deploy(3, "suspend").status_code == 200
    assert guarded.post("/operation").status_code == 403
    assert operations == ["executed", "executed"]


def test_operational_history_monitoring_and_adaptive_readiness(tenant):
    editor = tenant["editor"]
    risk = {
        "kind": "risk",
        "title": "Excessive access",
        "system_id": "helper",
        "owner": "security",
        "likelihood": 4,
        "impact": 5,
        "control_effectiveness": 40,
        "treatment": "mitigate",
        "treatment_owner": "engineering",
        "due_date": "2027-01-01",
        "status": "open",
    }
    result = editor.put("/v1/registers/risk/test", json=risk)
    assert result.status_code == 200
    assert result.json()["residual_score"] == 12
    assert editor.put("/v1/registers/risk/test", json=risk).status_code == 409
    assert (
        editor.put(
            "/v1/registers/risk/test?expected_version=1",
            json=risk
            | {
                "control_effectiveness": 0,
            },
        ).status_code
        == 200
    )
    assert (
        editor.get("/v1/registers/risk/test/history/1").json()["residual_score"] == 12
    )
    assert editor.get("/v1/monitoring").json()["high_residual_risks"] == 1
    assert (
        editor.put(
            "/v1/organisation",
            json={
                "name": "Example",
                "sector": "Technology",
                "jurisdiction": "UK",
                "adoption_stage": "operating",
            },
        ).status_code
        == 200
    )
    path = "/v1/readiness/adaptive?handles_sensitive_data=true"
    questions = editor.get(path).json()["questions"]
    assert {"monitoring", "development", "sensitive_data"} <= questions.keys()
    result = editor.post(path, json={"answers": dict.fromkeys(questions, "partial")})
    assert result.status_code == 201
    assert result.json()["score"] == 50
    assert len(editor.get("/v1/frameworks").json()["references"]) >= 8
    mapping = {
        "kind": "framework_assessment",
        "title": "AI framework review",
        "framework_id": "nist-ai-rmf",
        "framework_version": "1.0",
        "applicability": "applicable",
        "owner": "security",
        "rationale": "Voluntary mapping.",
        "control_ids": ["CTRL-INVENTORY"],
        "reviewed_on": "2026-11-19",
    }
    assert (
        editor.put("/v1/registers/framework_assessment/rmf", json=mapping).status_code
        == 200
    )
    assert (
        editor.put(
            "/v1/registers/framework_assessment/unknown",
            json=mapping | {"framework_version": "other"},
        ).status_code
        == 422
    )


def test_directory_join_move_leave_and_access_queue(tenant, monkeypatch):
    from aigovkit import tenancy

    monkeypatch.setenv("AIGOVKIT_OIDC_ISSUER", "https://fixture.invalid/")
    monkeypatch.setattr(tenancy, "verify_access_token", lambda token, _: token)
    owner, reviewer = tenant["identity_admin"], tenant["reviewer"]
    requester = TestClient(app, headers={"Authorization": "Bearer new-subject"})
    assert requester.get("/v1/session").status_code == 403
    member = {
        "subject": "new-subject",
        "role": "reader",
        "state": "active",
        "groups": ["support"],
        "expected_version": 0,
    }
    member_path = "/v1/identity/members/new-member"
    assert owner.put(member_path, json=member).status_code == 200
    assert requester.get("/v1/session").json()["member_id"] == "new-member"
    data = {
        "simulation": SCENARIO,
        "group": "support",
        "justification": "Summarise tickets.",
    }
    requested = requester.post("/v1/access-requests", json=data)
    assert requested.status_code == 201
    access = requested.json()
    assert access["assessment"]["disposition"] == "consider_after_review"
    assert (
        reviewer.post(
            "/v1/access-decisions",
            json={
                "request_id": access["id"],
                "decision": "approved",
                "rationale": "Reviewed the scope.",
            },
        ).status_code
        == 200
    )
    assert (
        requester.post(
            "/v1/access-recertifications",
            json={
                "request_id": access["id"],
                "justification": "Role still needs access.",
            },
        ).status_code
        == 201
    )
    assert (
        owner.put(
            member_path, json=member | {"expected_version": 1, "groups": []}
        ).status_code
        == 200
    )
    assert (
        requester.post("/v1/access-requests", json=data).json()["assessment"][
            "disposition"
        ]
        == "deny"
    )
    assert (
        owner.put(
            member_path, json=member | {"expected_version": 2, "state": "suspended"}
        ).status_code
        == 200
    )
    assert requester.get("/v1/session").status_code == 403


def test_executive_trends_signed_export_and_scheduled_alerts(
    tenant, monkeypatch, tmp_path
):
    from datetime import UTC, datetime

    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from aigovkit.verify_audit import verify

    editor, auditor = tenant["editor"], tenant["auditor"]
    assert editor.post("/v1/reports", json=SCENARIO).status_code == 201
    path = "/v1/executive-report"
    trend = editor.get(
        path, params={"department": "customer-support", "system": "support-ai"}
    ).json()
    assert trend["report_count"] == 1
    assert (
        editor.get(path, params={"department": "unknown"}).json()["report_count"] == 0
    )
    assert editor.get(path, params={"risk": "high"}).json()["report_count"] == 0
    day = datetime.now(UTC).date().isoformat()
    event = {
        "kind": "signal",
        "title": "Runtime failure",
        "source": "fixture",
        "agent_id": "helper",
        "event": "error",
        "count": 10,
        "observed_on": day,
    }
    assert editor.put("/v1/registers/signal/first", json=event).status_code == 200
    assert editor.post("/v1/incident-alerts/run").json() == {"created": 1}
    assert editor.post("/v1/incident-alerts/run").json() == {"created": 0}
    assert editor.get("/v1/registers/incident").json()[0]["system_id"] == "helper"
    assert editor.post("/v1/review-reminders/run").json() == {"queued": 0}
    course = {
        "kind": "training",
        "title": "Training fixture",
        "assignee": "publisher",
        "due_date": "2027-01-01",
        "status": "assigned",
        "course_id": "secure-ai-basics",
    }
    assert editor.put("/v1/registers/training/t1", json=course).status_code == 200
    complete = "/v1/training/assignments/t1/complete"
    assert editor.post(complete).status_code == 404
    assert tenant["publisher"].post(complete).json()["status"] == "completed"
    assert len(editor.get("/v1/training/courses").json()) == 2
    key = Ed25519PrivateKey.generate()
    path = tmp_path / "private.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    monkeypatch.setenv("AIGOVKIT_AUDIT_SIGNING_KEY_FILE", str(path))
    assert editor.get("/v1/audit-export").status_code == 403
    exported = auditor.get("/v1/audit-export").json()
    verify(exported, key.public_key())
    exported["payload"]["events"].clear()
    with pytest.raises(InvalidSignature):
        verify(exported, key.public_key())
    assert not auditor.post("/v1/retention/audit", json={"days": 30}).json()["applied"]
    assert (
        auditor.post(
            "/v1/retention/audit", json={"days": 30, "apply": True}
        ).status_code
        == 403
    )


def test_reviewed_discovery_promotion_is_idempotent(tenant):
    editor = tenant["editor"]
    path = "/v1/registers/discovery/item"
    promotion = "/v1/discovery/item/promote"
    evidence = {
        "kind": "discovery",
        "title": "Example",
        "source": "entra",
        "service": "Discovered tool",
        "count": 1,
        "status": "needs_review",
        "observed_on": "2026-11-19",
    }
    assert editor.put(path, json=evidence).status_code == 200
    assert editor.post(promotion, json={"owner": "security"}).status_code == 409
    assert (
        editor.put(
            path + "?expected_version=1", json=evidence | {"status": "approved"}
        ).status_code
        == 200
    )
    created = editor.post(promotion, json={"owner": "security"})
    assert created.status_code == 201
    assert created.json()["name"] == "Discovered tool"
    assert editor.post(promotion, json={"owner": "security"}).status_code == 409
