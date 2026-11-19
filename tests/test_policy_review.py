import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from aigovkit.storage import PostgresInventory
from aigovkit.tenancy import schema_for
from main import app


def test_named_review_is_independent_atomic_and_tenant_scoped(monkeypatch):
    dsn = os.getenv("AIGOVKIT_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("A disposable PostgreSQL database is required.")
    members = [
        {"id": name, "role": role, "key": secrets.token_urlsafe(32)}
        for name, role in [
            ("author", "editor"),
            ("reviewer", "reviewer"),
            ("reader", "reader"),
        ]
    ]
    tenant = {"id": f"test-{secrets.token_hex(8)}", "members": members}
    other = {
        "id": f"test-{secrets.token_hex(8)}",
        "editor_key": secrets.token_urlsafe(32),
    }
    shared_key = secrets.token_urlsafe(32)
    tenant["editor_key"] = shared_key
    monkeypatch.setenv("AIGOVKIT_DATABASE_URL", dsn)

    def configure():
        monkeypatch.setenv("AIGOVKIT_TENANTS", json.dumps([tenant, other]))

    def client(key):
        return TestClient(app, headers={"X-API-Key": key})

    configure()
    author, reviewer, reader = [client(member["key"]) for member in members]
    for tenant_id in (tenant["id"], other["id"]):
        PostgresInventory(dsn, schema_for(tenant_id)).initialize()
    profile = {
        "name": "Example team",
        "sector": "Technology",
        "jurisdiction": "United Kingdom",
        "adoption_stage": "piloting",
    }
    assert author.put("/v1/organisation", json=profile).status_code == 200
    assert reviewer.put("/v1/organisation", json=profile).status_code == 403
    created = author.post(
        "/v1/policy-drafts",
        json={
            "template_id": "agent-security",
            "owner": "Security",
            "scope": "Synthetic agents",
            "review_days": 90,
            "applies_to_agents": False,
        },
    )
    assert created.status_code == 201
    original = created.json()
    draft_id = original["id"]
    clause_id = original["clauses"][0]["id"]
    base = f"/v1/policy-drafts/{draft_id}/revisions"
    revision = {
        "expected_version": 0,
        "clause_texts": {clause_id: "Review exact permissions."},
    }
    assert client(shared_key).post(base, json=revision).status_code == 403
    assert (
        author.post(
            base, json=revision | {"clause_texts": {"unknown": "Invalid"}}
        ).status_code
        == 422
    )

    with ThreadPoolExecutor() as executor:
        codes = list(
            executor.map(
                lambda _: (
                    client(members[0]["key"]).post(base, json=revision).status_code
                ),
                range(2),
            )
        )
    assert sorted(codes) == [201, 409]
    assert author.post(f"{base}/1/submit").status_code == 200
    assert author.post(f"{base}/1/submit").status_code == 409
    decision = {
        "draft_id": draft_id,
        "version": 1,
        "action": "changes_requested",
        "note": "Clarify scope.",
    }
    assert author.post("/v1/policy-reviews", json=decision).status_code == 403
    assert reader.post("/v1/policy-reviews", json=decision).status_code == 403

    members[0]["role"] = "reviewer"
    configure()
    assert author.post("/v1/policy-reviews", json=decision).status_code == 403
    members[0]["role"] = "editor"
    configure()
    assert reviewer.post("/v1/policy-reviews", json=decision).status_code == 200
    changed = {
        "expected_version": 1,
        "clause_texts": {clause_id: "Review read-only support access."},
    }
    assert author.post(base, json=changed).status_code == 201
    assert author.post(f"{base}/2/submit").status_code == 200
    approve = decision | {
        "version": 2,
        "action": "approved",
        "note": "Reviewed role and purpose.",
    }
    with ThreadPoolExecutor() as executor:
        codes = list(
            executor.map(
                lambda _: (
                    client(members[1]["key"])
                    .post("/v1/policy-reviews", json=approve)
                    .status_code
                ),
                range(2),
            )
        )
    assert sorted(codes) == [200, 409]
    approved = reader.get(f"{base}/2").json()
    assert approved["status"] == "approved"
    assert [event["actor"] for event in approved["events"]] == ["author", "reviewer"]
    assert (
        reader.get(f"{base}/1").json()["body"]["clauses"][0]["text"]
        == "Review exact permissions."
    )
    assert author.post(base, json=changed | {"expected_version": 2}).status_code == 201
    assert reader.get(f"{base}/2").json() == approved
    assert author.get(f"/v1/policy-drafts/{draft_id}").json() == original
    assert client(other["editor_key"]).get(f"{base}/2").status_code == 404
    assert client(other["editor_key"]).get(base).status_code == 404
