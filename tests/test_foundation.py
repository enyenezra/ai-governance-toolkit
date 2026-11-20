import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from aigovkit.foundation import QUESTIONS
from aigovkit.storage import PostgresInventory
from aigovkit.tenancy import schema_for
from main import app

PROFILE = {
    "name": "Synthetic Support",
    "sector": "Technology",
    "jurisdiction": "United Kingdom",
    "adoption_stage": "piloting",
}
DRAFT = {
    "template_id": "agent-security",
    "owner": "Support operations",
    "scope": "Synthetic support-ticket summarisation",
    "review_days": 90,
    "applies_to_agents": True,
    "oversight_contact": "Support supervisor",
}


def test_workspace_assets():
    client = TestClient(app)
    for path, script in (("/", "assessment.js"), ("/workspace", "workspace.js")):
        response = client.get(path)
        assert response.status_code == 200
        assert f"/assets/generated/{script}" in response.text
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_invalid_explicit_tenant_config_does_not_fall_back(monkeypatch):
    key = secrets.token_urlsafe(32)
    monkeypatch.setenv("AIGOVKIT_API_KEY", key)
    monkeypatch.setenv("AIGOVKIT_TENANTS", "[]")
    assert (
        TestClient(app).get("/v1/session", headers={"X-API-Key": key}).status_code
        == 503
    )


def test_foundation_tenant_lifecycle(monkeypatch):
    dsn = os.getenv("AIGOVKIT_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("A disposable PostgreSQL database is required.")
    tenants = [
        {
            "id": f"test-{secrets.token_hex(8)}",
            "editor_key": secrets.token_urlsafe(32),
            "reader_key": secrets.token_urlsafe(32),
        }
        for _ in range(2)
    ]
    monkeypatch.setenv("AIGOVKIT_DATABASE_URL", dsn)
    monkeypatch.setenv("AIGOVKIT_TENANTS", json.dumps(tenants))
    stores = [PostgresInventory(dsn, schema_for(tenant["id"])) for tenant in tenants]
    with ThreadPoolExecutor() as executor:
        list(executor.map(lambda store: store.initialize(), [*stores, stores[0]]))
    editor, other = [
        TestClient(app, headers={"X-API-Key": t["editor_key"]}) for t in tenants
    ]
    reader = TestClient(app, headers={"X-API-Key": tenants[0]["reader_key"]})

    assert editor.get("/v1/session").json()["organisation_id"] == tenants[0]["id"]
    assert editor.post("/v1/policy-drafts", json=DRAFT).status_code == 409
    assert editor.put("/v1/organisation", json=PROFILE).status_code == 200
    assert reader.get("/v1/organisation").json() == PROFILE
    assert reader.put("/v1/organisation", json=PROFILE).status_code == 403
    assert (
        other.get("/v1/organisation", headers={"X-Tenant-ID": tenants[0]["id"]}).json()
        is None
    )
    asset = {
        "kind": "asset",
        "id": "test",
        "name": "Test asset",
        "classification": "internal",
    }
    assert editor.put("/v1/inventory/asset/test", json=asset).status_code == 200
    assert other.get("/v1/inventory").json() == []
    simulation = {
        "role": "support",
        "agent_id": "helper",
        "asset_id": "test",
        "action": "read",
    }
    report = editor.post("/v1/reports", json=simulation).json()
    assert other.get(f"/v1/reports/{report['id']}").status_code == 404

    assert (
        editor.post(
            "/v1/readiness/assessments", json={"answers": {"data": "partial"}}
        ).status_code
        == 422
    )
    answers = {domain: "in_place" for domain in QUESTIONS} | {
        "data": "missing",
        "training": "partial",
    }
    readiness = editor.post("/v1/readiness/assessments", json={"answers": answers})
    assert readiness.status_code == 201
    assert readiness.json()["score"] == 83
    assert [gap["domain"] for gap in readiness.json()["gaps"]] == ["data", "training"]
    assert other.get("/v1/readiness/assessments").json() == []

    templates = reader.get("/v1/policy-templates").json()
    controls = reader.get("/v1/controls").json()
    assert len(templates) == 12
    assert all(control["status"] == "proposed" for control in controls)
    assert (
        editor.post(
            "/v1/policy-drafts", json=DRAFT | {"oversight_contact": None}
        ).status_code
        == 422
    )
    known_controls = {control["id"] for control in controls}
    for template in templates:
        response = editor.post(
            "/v1/policy-drafts", json=DRAFT | {"template_id": template["id"]}
        )
        assert response.status_code == 201
        draft = response.json()
        assert draft["status"] == "draft"
        assert draft["human_approval_required"]
        assert all(
            clause["control_id"] in known_controls for clause in draft["clauses"]
        )
        assert reader.get(f"/v1/policy-drafts/{draft['id']}").json() == draft
        assert other.get(f"/v1/policy-drafts/{draft['id']}").status_code == 404
    repeat = editor.post("/v1/policy-drafts", json=DRAFT).json()
    original = editor.get("/v1/policy-drafts").json()
    assert any(
        row["id"] != repeat["id"] and row["clauses"] == repeat["clauses"]
        for row in original
    )
    assert other.get("/v1/policy-drafts").json() == []
