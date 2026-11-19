import os
import secrets
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from aigovkit.connectors import JsonInventoryConnector
from aigovkit.models import Simulation
from aigovkit.policy import evaluate
from aigovkit.storage import PostgresInventory
from aigovkit.verify_postgres import PostgresPermissionConnector
from main import app

SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "department-inventory.json"
REQUEST = {
    "role": "support",
    "agent_id": "helper",
    "asset_id": "tickets",
    "action": "read",
    "department_id": "customer-support",
    "purpose": "ticket-summary",
    "policy_version": "1.1.0",
}


@pytest.mark.parametrize(
    ("updates", "outcome"),
    [
        ({}, "consider_after_review"),
        ({"department_id": "unregistered"}, "deny"),
        ({"department_id": None}, "deny"),
        ({"purpose": "analytics"}, "deny"),
        ({"purpose": None}, "deny"),
        ({"action": "write"}, "deny"),
        ({"asset_id": "payroll"}, "deny"),
    ],
)
def test_context_policy(updates, outcome):
    inventory = JsonInventoryConnector(SAMPLE).records()
    request = Simulation.model_validate(REQUEST | updates)
    result = evaluate(request, inventory)
    assert result == evaluate(request, reversed(inventory))
    assert result.disposition == outcome
    assert result.human_approval_required
    assert result.policy_version == "1.1.0"


def test_context_policy_denies_missing_owner():
    entries = [
        record.model_copy(update={"owner": None}) if record.kind == "tool" else record
        for record in JsonInventoryConnector(SAMPLE).records()
    ]
    result = evaluate(Simulation.model_validate(REQUEST), entries)
    assert result.disposition == "deny"
    assert any("owner" in reason for reason in result.reasons)


@pytest.mark.parametrize(
    ("changes", "classification"),
    [
        ({}, "internal"),
        ({"approved_for_public_release": True}, "public"),
        (
            {"approved_for_public_release": True, "contains_personal_data": True},
            "confidential",
        ),
        ({"contains_confidential_business_data": True}, "confidential"),
        (
            {
                "contains_personal_data": True,
                "contains_credentials_or_regulated_sensitive_data": True,
            },
            "restricted",
        ),
    ],
)
def test_classification(monkeypatch, changes, classification):
    key = secrets.token_urlsafe(32)
    monkeypatch.setenv("AIGOVKIT_API_KEY", key)
    client = TestClient(app)
    body = {
        "approved_for_public_release": False,
        "contains_personal_data": False,
        "contains_confidential_business_data": False,
        "contains_credentials_or_regulated_sensitive_data": False,
    } | changes
    assert client.post("/v1/classification/suggestions", json=body).status_code == 401
    response = client.post(
        "/v1/classification/suggestions", json=body, headers={"X-API-Key": key}
    )
    assert response.status_code == 200
    assert response.json()["classification"] == classification
    assert response.json()["human_approval_required"]


@pytest.fixture
def database():
    dsn = os.getenv("AIGOVKIT_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set AIGOVKIT_TEST_DATABASE_URL to a disposable database")
    return dsn


def test_saved_report(database, monkeypatch):
    store = PostgresInventory(database)
    store.initialize()
    store.put(JsonInventoryConnector(SAMPLE).records())
    key = secrets.token_urlsafe(32)
    monkeypatch.setenv("AIGOVKIT_API_KEY", key)
    monkeypatch.setenv("AIGOVKIT_DATABASE_URL", database)
    client = TestClient(app, headers={"X-API-Key": key})
    created = client.post("/v1/reports", json=REQUEST)
    assert created.status_code == 201
    report = created.json()
    assert report["risk_score"] == 50
    assert report["assessment"]["disposition"] == "consider_after_review"

    restricted = {
        "kind": "asset",
        "id": "tickets",
        "name": "Tickets",
        "classification": "restricted",
    }
    assert client.put("/v1/inventory/asset/tickets", json=restricted).status_code == 200
    assert client.post("/v1/simulations", json=REQUEST).json()["disposition"] == "deny"
    assert client.get(f"/v1/reports/{report['id']}").json() == report
    assert client.get("/v1/reports?limit=1").json() == [report]
    assert client.get("/v1/reports/unrecognised").status_code == 404
    assert TestClient(app).get("/v1/reports").status_code == 401
    scan = client.get(
        "/v1/connection-assessments",
        params={
            key: REQUEST[key]
            for key in ("role", "policy_version", "department_id", "purpose")
        },
    )
    assert scan.status_code == 200
    assert all(row["assessment"]["disposition"] == "deny" for row in scan.json())


def test_postgres_permission_connector(database):
    name = f"aigovkit_test_{uuid4().hex}"
    identifier = sql.Identifier(name)
    with psycopg.connect(database) as conn:
        conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(identifier))
        conn.execute(sql.SQL("CREATE TABLE {} (id int)").format(identifier))
        conn.commit()
        try:
            connector = PostgresPermissionConnector(database)
            assert connector.verify(name, "public", "table_that_is_missing") is None
            assert connector.verify(name, "public", name).table_privileges == []
            conn.execute(
                sql.SQL("GRANT SELECT ON {} TO {}").format(identifier, identifier)
            )
            conn.commit()
            verified = connector.verify(name, "public", name)
            assert verified.schema_usage
            assert verified.table_privileges == ["SELECT"]
        finally:
            conn.execute(sql.SQL("DROP TABLE {}").format(identifier))
            conn.execute(sql.SQL("DROP ROLE {}").format(identifier))
