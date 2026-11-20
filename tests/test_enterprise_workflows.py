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


def test_provider_governance_adapter_blocks_models_and_verifies_current_version(tenant):
    import httpx
    from fastapi import FastAPI
    from pydantic import BaseModel

    from aigovkit.model_gate_adapter import ModelEnforcedRoutes

    editor, publisher, gateway = (
        tenant[key] for key in ("editor", "publisher", "gateway")
    )
    registration = {
        "name": "Synthetic model gateway",
        "provider_type": "openai_compatible",
        "endpoint": "https://model.example.invalid",
        "gateway_member": "gateway",
        "available_models": ["allowed", "denied"],
    }
    assert editor.post("/v1/providers/fixture", json=registration).status_code == 201
    assert (
        editor.post(
            "/v1/providers/copilot",
            json=registration
            | {
                "provider_type": "copilot",
            },
        ).status_code
        == 201
    )
    policy = {"expected_version": 0, "allowed_models": ["allowed"]}
    assert (
        publisher.post("/v1/provider-deployments/copilot", json=policy).status_code
        == 409
    )
    assert (
        editor.post("/v1/provider-deployments/fixture", json=policy).status_code == 403
    )
    assert (
        publisher.post("/v1/provider-deployments/fixture", json=policy).status_code
        == 200
    )
    assert {row["id"]: row["status"] for row in editor.get("/v1/providers").json()} == {
        "fixture": "deployed_unverified",
        "copilot": "unsupported",
    }
    rule = editor.post(
        "/v1/guardrail-rules", json={"scope": SCENARIO, "decision": "allow"}
    ).json()
    assert (
        publisher.post(
            "/v1/guardrail-deployments",
            json={
                "agent_id": "helper",
                "revision_id": rule["id"],
                "operation": "deploy",
                "expected_version": 0,
            },
        ).status_code
        == 200
    )

    received = []
    backend = FastAPI()

    class Input(BaseModel):
        model: str
        input: str

    @backend.post("/v1/responses")
    def execute(body: Input):
        received.append(body.input)
        return {"model": body.model}

    def gate(request):
        metadata = json.loads(request.content)
        assert set(metadata) == {"model", "scope"}
        decision = gateway.post(request.url.path, json=metadata)
        return httpx.Response(decision.status_code, json=decision.json())

    proxy = TestClient(
        ModelEnforcedRoutes(
            backend,
            "https://gate.example.invalid",
            gateway.headers["X-API-Key"],
            "fixture",
            {("POST", "/v1/responses"): SCENARIO},
            transport=httpx.MockTransport(gate),
        )
    )
    endpoint = "/v1/responses"
    assert (
        proxy.post(
            endpoint, json={"model": "allowed", "input": "private prompt"}
        ).status_code
        == 200
    )
    assert (
        proxy.post(
            endpoint, json={"model": "denied", "input": "blocked prompt"}
        ).status_code
        == 403
    )
    assert (
        proxy.post(
            endpoint,
            content='{"model":"allowed","model":"denied"}',
            headers={"Content-Type": "application/json"},
        ).status_code
        == 422
    )
    assert editor.post("/v1/security-detections/run").json()["findings_created"] == 1
    assert (
        editor.get("/v1/security-findings").json()[0]["rule"] == "model_not_allowlisted"
    )
    assert received == ["private prompt"]
    assert editor.get("/v1/provider-checks/fixture").status_code == 403
    checks = publisher.get("/v1/provider-checks/fixture").json()
    evidence = {
        "allowed_check" if row["decision"] == "allow" else "denied_check": row["id"]
        for row in checks
    }
    assert "private prompt" not in json.dumps(checks)
    assert (
        publisher.post("/v1/provider-verifications/fixture", json=evidence).status_code
        == 200
    )
    assert (
        next(
            row for row in editor.get("/v1/providers").json() if row["id"] == "fixture"
        )["status"]
        == "verified_gateway_checks"
    )
    assert (
        publisher.post(
            "/v1/provider-deployments/fixture",
            json={
                "expected_version": 1,
                "rollback_to": 1,
            },
        ).status_code
        == 200
    )
    assert (
        publisher.post("/v1/provider-verifications/fixture", json=evidence).status_code
        == 422
    )


def test_detection_and_temporary_containment(tenant, monkeypatch):
    import psycopg

    editor, publisher, gateway = (
        tenant[key] for key in ("editor", "publisher", "gateway")
    )
    rule = editor.post(
        "/v1/guardrail-rules", json={"scope": SCENARIO, "decision": "allow"}
    ).json()
    assert (
        publisher.post(
            "/v1/guardrail-deployments",
            json={
                "agent_id": "helper",
                "revision_id": rule["id"],
                "operation": "deploy",
                "expected_version": 0,
            },
        ).status_code
        == 200
    )
    route = "/v1/guardrail-checks"
    for _ in range(3):
        assert (
            gateway.post(route, json=SCENARIO | {"action": "admin"}).status_code == 403
        )
    submitted = editor.post("/v1/security-detections/run")
    assert submitted.status_code == 200
    assert submitted.json() == {"findings_created": 2, "incidents_created": 1}
    assert editor.post("/v1/security-detections/run").json()["findings_created"] == 0
    findings = {row["rule"]: row for row in editor.get("/v1/security-findings").json()}
    high = findings["privileged_action_denied"]
    assert len(high["evidence_ids"]) == 3
    assert editor.get("/v1/registers/incident").json()[0]["evidence_references"] == [
        high["id"]
    ]
    data = {"finding_id": high["id"], "minutes": 15}
    assert editor.post("/v1/containment", json=data).json()["status"] == "preview"
    assert editor.get("/v1/containment").json() == []
    assert gateway.post(route, json=SCENARIO).status_code == 200
    assert (
        editor.post("/v1/containment", json=data | {"dry_run": False}).status_code
        == 200
    )
    action = "/v1/containment/" + high["id"] + "/transition"
    assert publisher.post(action, json={"action": "execute"}).status_code in {403, 409}
    assert editor.post(action, json={"action": "approve"}).status_code == 403
    assert (
        publisher.post(action, json={"action": "approve"}).json()["status"]
        == "approved"
    )
    assert publisher.post(action, json={"action": "execute"}).status_code == 403
    monkeypatch.setenv("AIGOVKIT_CONTAINMENT_ENABLED", "yes")
    active = publisher.post(action, json={"action": "execute"})
    assert active.status_code == 200
    assert publisher.post(action, json={"action": "execute"}).json() == active.json()
    denied = gateway.post(route, json=SCENARIO)
    assert denied.status_code == 403 and denied.json()["containment_id"] == high["id"]
    monkeypatch.setenv("AIGOVKIT_CONTAINMENT_ENABLED", "no")
    assert (
        publisher.post(action, json={"action": "rollback"}).json()["status"]
        == "rolled_back"
    )
    assert gateway.post(route, json=SCENARIO).status_code == 200

    monkeypatch.setenv("AIGOVKIT_CONTAINMENT_ENABLED", "yes")
    other = findings["repeated_gate_denials"]["id"]
    assert (
        editor.post(
            "/v1/containment",
            json={"finding_id": other, "minutes": 1, "dry_run": False},
        ).status_code
        == 200
    )
    other_route = "/v1/containment/" + other + "/transition"
    for op in ("approve", "execute"):
        assert publisher.post(other_route, json={"action": op}).status_code == 200

    # Move only the disposable test restriction into the past instead of sleeping.
    dsn = os.environ["AIGOVKIT_TEST_DATABASE_URL"]
    tenant_id = editor.get("/v1/session").json()["organisation_id"]
    schema = schema_for(tenant_id)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            psycopg.sql.SQL("SET search_path TO {}").format(
                psycopg.sql.Identifier(schema)
            )
        )
        conn.execute(
            """UPDATE foundation_documents SET body=jsonb_set(body,'{expires_at}',to_jsonb(%s::text))
               WHERE kind IN ('containment_active','containment_request') AND body->>'id'=%s""",
            ("2000-01-01T00:00:00+00:00", other),
        )
    assert gateway.post(route, json=SCENARIO).status_code == 200
    assert any(
        row["id"] == other and row["status"] == "expired"
        for row in editor.get("/v1/containment").json()
    )
    auditor = tenant["auditor"]
    actions = {
        row["action"] for row in auditor.get("/v1/audit-events?limit=100").json()
    }
    assert {
        "containment.execute",
        "containment.execute_rejected",
        "containment.rollback",
    } <= actions
