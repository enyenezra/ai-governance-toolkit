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
        for role in ("editor", "publisher", "gateway", "identity_admin", "reviewer")
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
    assert deploy(1, "deploy", deny).status_code == 200
    assert gateway.post(check, json=SCENARIO).status_code == 403
    assert deploy(2, "rollback", allow).status_code == 200
    assert gateway.post(check, json=SCENARIO).status_code == 200
    assert deploy(3, "suspend").status_code == 200
    assert gateway.post(check, json=SCENARIO).status_code == 403


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
