import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from aigovkit.storage import PostgresInventory
from aigovkit.tenancy import schema_for
from main import app


def test_approved_publication_and_versioned_acknowledgement(monkeypatch):
    dsn = os.getenv("AIGOVKIT_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("A disposable PostgreSQL database is required.")
    members = [
        {"id": role, "role": role, "key": secrets.token_urlsafe(32)}
        for role in ("editor", "reviewer", "publisher", "reader")
    ]
    tenant = {"id": f"test-{secrets.token_hex(8)}", "members": members}
    other = {
        "id": f"test-{secrets.token_hex(8)}",
        "editor_key": secrets.token_urlsafe(32),
    }
    for item in tenant, other:
        PostgresInventory(dsn, schema_for(item["id"])).initialize()

    def configure():
        monkeypatch.setenv("AIGOVKIT_TENANTS", json.dumps([tenant, other]))

    def client(key):
        return TestClient(app, headers={"X-API-Key": key})

    monkeypatch.setenv("AIGOVKIT_DATABASE_URL", dsn)
    configure()
    editor, reviewer, publisher, reader = [client(member["key"]) for member in members]
    outsider = client(other["editor_key"])
    assert (
        editor.put(
            "/v1/organisation",
            json={
                "name": "Example",
                "sector": "Technology",
                "jurisdiction": "UK",
                "adoption_stage": "piloting",
            },
        ).status_code
        == 200
    )
    response = editor.post(
        "/v1/policy-drafts",
        json={
            "template_id": "agent-security",
            "owner": "Security",
            "scope": "Synthetic",
            "review_days": 90,
            "applies_to_agents": False,
        },
    )
    assert response.status_code == 201
    draft = response.json()
    path = f"/v1/policy-drafts/{draft['id']}/revisions"
    first = {"draft_id": draft["id"], "version": 1}
    second = first | {"version": 2}

    def revise(version):
        result = editor.post(
            path,
            json={
                "expected_version": version - 1,
                "clause_texts": {
                    draft["clauses"][0]["id"]: f"Review policy version {version}."
                },
            },
        )
        assert result.status_code == 201

    def approve(version):
        assert editor.post(f"{path}/{version}/submit").status_code == 200
        result = reviewer.post(
            "/v1/policy-reviews",
            json=first
            | {
                "version": version,
                "action": "approved",
                "note": "Scope verified.",
            },
        )
        assert result.status_code == 200

    revise(1)
    assert publisher.post("/v1/policy-publications", json=first).status_code == 409
    assert reader.post("/v1/policy-acknowledgements", json=first).status_code == 409
    approve(1)
    assert editor.post("/v1/policy-publications", json=first).status_code == 403

    members[1]["role"] = "publisher"
    configure()
    assert reviewer.post("/v1/policy-publications", json=first).status_code == 403
    members[1]["role"] = "reviewer"
    configure()

    with ThreadPoolExecutor() as executor:
        results = list(
            executor.map(
                lambda _: (
                    client(members[2]["key"])
                    .post("/v1/policy-publications", json=first)
                    .status_code
                ),
                range(2),
            )
        )
    assert sorted(results) == [201, 409]
    detail = f"/v1/published-policies/{draft['id']}"
    assert outsider.get(f"{detail}/1").status_code == 404
    assert outsider.get("/v1/published-policies").json() == []
    assert outsider.post("/v1/policy-acknowledgements", json=first).status_code == 403
    assert reader.get(f"{detail}/1").json()["current"]
    assert reader.get(f"{detail}/1").json()["acknowledged_at"] is None
    receipt = reader.post("/v1/policy-acknowledgements", json=first).json()
    assert receipt["member_id"] == "reader"
    assert reader.post("/v1/policy-acknowledgements", json=first).json() == receipt
    assert reviewer.get("/v1/policy-acknowledgements").json() == []

    revise(2)
    assert reader.get("/v1/published-policies").json()[0]["version"] == 1
    assert reader.get(f"{detail}/2").status_code == 404
    approve(2)
    assert publisher.post("/v1/policy-publications", json=second).status_code == 201
    assert publisher.post("/v1/policy-publications", json=first).status_code == 409
    assert reader.get("/v1/published-policies").json()[0]["version"] == 2
    assert not reader.get(f"{detail}/1").json()["current"]
    assert (
        reader.get(f"{detail}/1").json()["acknowledged_at"]
        == receipt["acknowledged_at"]
    )
    assert reader.get(f"{detail}/2").json()["acknowledged_at"] is None
    assert reader.post("/v1/policy-acknowledgements", json=first).status_code == 409
    assert reader.post("/v1/policy-acknowledgements", json=second).status_code == 200
    assert len(reader.get("/v1/policy-acknowledgements").json()) == 2
