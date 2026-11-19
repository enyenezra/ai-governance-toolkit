import os
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aigovkit.api import get_inventory
from aigovkit.connectors import JsonInventoryConnector
from aigovkit.models import Simulation
from aigovkit.policy import evaluate
from aigovkit.storage import PostgresInventory
from main import app

SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "inventory.json"
REQUEST = {
    "role": "support",
    "agent_id": "helper",
    "asset_id": "tickets",
    "action": "read",
}


class MemoryInventory:
    def __init__(self):
        self.entries = {}

    def put(self, records):
        for entry in records:
            self.entries[entry.kind, entry.id] = entry

    def records(self):
        return list(self.entries.values())


@pytest.fixture
def client(monkeypatch):
    key = secrets.token_urlsafe(32)
    monkeypatch.setenv("AIGOVKIT_API_KEY", key)
    store = MemoryInventory()
    store.put(JsonInventoryConnector(SAMPLE).records())
    monkeypatch.setitem(app.dependency_overrides, get_inventory, lambda: store)
    return TestClient(app, headers={"X-API-Key": key})


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"role": "unknown"}, "No matching role need"),
        ({"asset_id": "unknown"}, "is unknown"),
        ({"agent_id": "unknown"}, "is unknown"),
        ({"action": "write"}, "No matching role need"),
        ({"action": "delete"}, "destructive actions"),
        ({"asset_id": "payroll"}, "Restricted assets"),
    ],
)
def test_deny_by_default(changes, reason):
    entries = JsonInventoryConnector(SAMPLE).records()
    request = Simulation.model_validate(REQUEST | changes)
    result = evaluate(request, entries)
    assert result == evaluate(request, reversed(entries))
    assert result.policy_version == "1.0.0"
    assert result.disposition == "deny"
    assert result.risk == "high"
    assert result.human_approval_required
    assert any(reason in item for item in result.reasons)
    assert result.controls


def test_undeclared_connection_denies_even_with_role_need():
    entries = [
        entry
        for entry in JsonInventoryConnector(SAMPLE).records()
        if entry.kind != "connection"
    ]
    result = evaluate(Simulation.model_validate(REQUEST), entries)
    assert result.disposition == "deny"
    assert any("No declared agent connection" in reason for reason in result.reasons)


def test_simulation_and_connection_scan(client):
    response = client.post("/v1/simulations", json=REQUEST)
    assert response.status_code == 200
    result = response.json()
    assert result["disposition"] == "consider_after_review"
    assert result["risk"] == "medium"
    assert result["human_approval_required"] is True
    scan = client.get("/v1/connection-assessments", params={"role": "support"}).json()
    assert {
        (row["connection_id"], row["action"], row["assessment"]["disposition"])
        for row in scan
    } == {
        ("ticket-access", "read", "consider_after_review"),
        ("ticket-access", "write", "deny"),
        ("payroll-access", "read", "deny"),
    }


def test_inventory_and_validation(client):
    record = {
        "kind": "asset",
        "id": "manual",
        "name": "Manual",
        "classification": "public",
    }
    assert client.put("/v1/inventory/asset/manual", json=record).json() == record
    assert client.put("/v1/inventory/asset/other", json=record).status_code == 422
    assert client.put("/v1/inventory/tool/manual", json=record).status_code == 422
    invalid = record | {"classification": "unknown"}
    assert client.put("/v1/inventory/asset/manual", json=invalid).status_code == 422
    assert record in client.get("/v1/inventory?kind=asset").json()
    assert len(client.get("/v1/inventory?limit=1").json()) == 1
    assert (
        client.post(
            "/v1/simulations", json=REQUEST | {"policy_version": "9"}
        ).status_code
        == 422
    )


def test_authentication(client, monkeypatch):
    assert TestClient(app).get("/v1/inventory").status_code == 401
    assert (
        client.get("/v1/inventory", headers={"X-API-Key": "wrong"}).status_code == 401
    )
    assert client.get("/v1/policies").json() == {"versions": ["1.0.0", "1.1.0"]}
    monkeypatch.delenv("AIGOVKIT_API_KEY")
    assert client.get("/v1/inventory").status_code == 503


def test_postgres_round_trip(monkeypatch):
    dsn = os.getenv("AIGOVKIT_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set AIGOVKIT_TEST_DATABASE_URL to a disposable database")
    store = PostgresInventory(dsn)
    store.initialize()
    entries = JsonInventoryConnector(SAMPLE).records()
    store.put(entries)
    store.put(entries)
    actual = {(r.kind, r.id): r for r in PostgresInventory(dsn).records()}
    assert all(actual[(record.kind, record.id)] == record for record in entries)
    key = secrets.token_urlsafe(32)
    monkeypatch.setenv("AIGOVKIT_API_KEY", key)
    monkeypatch.setenv("AIGOVKIT_DATABASE_URL", dsn)
    client = TestClient(app, headers={"X-API-Key": key})
    record = {
        "kind": "asset",
        "id": "tickets",
        "name": "Tickets",
        "classification": "restricted",
    }
    assert client.put("/v1/inventory/asset/tickets", json=record).status_code == 200
    response = client.post("/v1/simulations", json=REQUEST)
    assert response.status_code == 200
    assert response.json()["disposition"] == "deny"
