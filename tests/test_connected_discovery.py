import json
import os
import secrets
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from aigovkit import workspace_discovery as cloud
from aigovkit.storage import PostgresInventory
from aigovkit.tenancy import schema_for
from main import app

MAC = "00:11:22:33:44:55"


def test_provider_token_acquisition_and_metadata_selection(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "service.json"
    path.write_text(
        json.dumps(
            {
                "type": "service_account",
                "client_email": "fixture@example.invalid",
                "private_key": key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                ).decode(),
            }
        )
    )
    google = cloud.Google(
        service_account_file=str(path),
        delegated_admin="reader@example.invalid",
        customer_id="C1234",
        chromeos=True,
    )
    seen = datetime.now(UTC).isoformat()

    def provider(request):
        if request.url.host == "oauth2.googleapis.com":
            body = parse_qs(request.content.decode())
            claims = jwt.decode(
                body["assertion"][0],
                key.public_key(),
                algorithms=["RS256"],
                audience=cloud.GOOGLE_TOKEN,
            )
            assert claims["sub"] == "reader@example.invalid"
            assert claims["scope"].endswith("admin.directory.device.chromeos.readonly")
            return httpx.Response(200, json={"access_token": "fixture"})
        assert request.url.host == "admin.googleapis.com"
        if "/reports/" in request.url.path:
            assert request.url.params["customerId"] == "C1234"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "actor": {"email": "private@example.invalid"},
                            "events": [
                                {
                                    "name": "authorize",
                                    "parameters": [
                                        {"name": "client_id", "value": "client"},
                                        {"name": "app_name", "value": "Example"},
                                    ],
                                }
                            ],
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "chromeosdevices": [
                    {
                        "deviceId": "d1",
                        "model": "Chromebook",
                        "macAddress": MAC,
                        "lastSync": seen,
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        assert cloud.token(client, google) == "fixture"
        result = cloud.collect(client, google, 1)
    assert result["applications"][0]["name"] == "Example"
    assert result["devices"][0]["source"] == "google-chromeos"
    assert "private@example.invalid" not in json.dumps(result)


def test_microsoft_app_grant_and_optional_sources():
    config = cloud.Microsoft.model_validate(
        {
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "client_id": "00000000-0000-0000-0000-000000000002",
            "client_secret": "fixture",
            "devices": True,
            "sign_ins": True,
        }
    )
    seen = datetime.now(UTC).isoformat()

    def provider(request):
        if request.url.host == "login.microsoftonline.com":
            body = parse_qs(request.content.decode())
            assert body["grant_type"] == ["client_credentials"]
            assert body["scope"] == ["https://graph.microsoft.com/.default"]
            return httpx.Response(200, json={"access_token": "fixture"})
        if request.url.path.endswith("servicePrincipals"):
            return httpx.Response(
                200, json={"value": [{"appId": "client", "displayName": "Example"}]}
            )
        if request.url.path.endswith("signIns"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "appId": "client",
                            "appDisplayName": "Example",
                            "userPrincipalName": "private@example.invalid",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "managed-id",
                        "model": "Example device",
                        "lastSyncDateTime": seen,
                        "wiFiMacAddress": MAC,
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        assert cloud.token(client, config) == "fixture"
        result = cloud.collect(client, config, 1)
    assert result["sources"] == ["entra-apps", "entra-sign-ins", "intune"]
    assert result["devices"][0]["mac"] == "001122334455"
    assert "private@example.invalid" not in json.dumps(result)


def test_tenant_discovery_schedule_device_matching_and_passive_signals(monkeypatch):
    dsn = os.getenv("AIGOVKIT_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("A disposable PostgreSQL database is required.")
    tenant, other = (f"test-{secrets.token_hex(8)}" for _ in range(2))
    members = [
        {"id": role, "role": role, "key": secrets.token_urlsafe(32)}
        for role in ("editor", "observer", "scheduler")
    ]
    outside = {"id": "outside", "role": "editor", "key": secrets.token_urlsafe(32)}
    monkeypatch.setenv(
        "AIGOVKIT_TENANTS",
        json.dumps(
            [
                {"id": tenant, "members": members},
                {"id": other, "members": [outside]},
            ]
        ),
    )
    monkeypatch.setenv("AIGOVKIT_DATABASE_URL", dsn)
    monkeypatch.setenv("AIGOVKIT_DEVICE_HASH_KEY", secrets.token_hex(32))
    monkeypatch.setenv("AIGOVKIT_AI_SIGNAL_DOMAINS", "ai.example.invalid")
    monkeypatch.setenv(
        "AIGOVKIT_DISCOVERY_CONNECTIONS",
        json.dumps(
            {
                tenant: {
                    "microsoft365": {
                        "tenant_id": "test",
                        "client_id": "test",
                        "client_secret": "fixture-secret",
                        "devices": True,
                    }
                },
            }
        ),
    )
    for item in (tenant, other):
        PostgresInventory(dsn, schema_for(item)).initialize()
    editor, collector, scheduler = [
        TestClient(app, headers={"X-API-Key": m["key"]}) for m in members
    ]
    outside_api = TestClient(app, headers={"X-API-Key": outside["key"]})
    seen = datetime.now(UTC).isoformat(timespec="seconds")
    result = {
        "applications": [
            {
                "source": "entra-apps",
                "id": "external-only",
                "name": "Example app",
                "count": 1,
            }
        ],
        "devices": [
            {
                "source": "intune",
                "provider_id": "managed-id",
                "mac": "001122334455",
                "seen_at": seen,
                "name": "Example computer",
            }
        ],
        "sources": ["intune", "entra-apps"],
        "partial": False,
    }
    monkeypatch.setattr(cloud, "discover", lambda config, pages: result)
    base = "/v1/workspace-discovery/microsoft365"
    preview = editor.post(base + "/preview")
    assert preview.status_code == 200
    assert "external-only" not in preview.text
    assert (
        "fixture-secret" not in editor.get("/v1/workspace-discovery/connections").text
    )
    assert editor.get("/v1/devices").json() == []
    assert (
        outside_api.get("/v1/workspace-discovery/connections").json()[0]["configured"]
        is False
    )
    assert (
        collector.post(
            "/v1/device-observations",
            json={
                "source": "dhcp",
                "mac": MAC,
                "seen_at": seen,
            },
        ).status_code
        == 201
    )
    assert collector.get("/v1/devices").status_code == 403
    assert editor.put(base + "/schedule", json={"enabled": True}).status_code == 200
    assert (
        scheduler.post("/v1/workspace-discovery/run").json()["microsoft365"][
            "new_findings"
        ]
        == 1
    )
    assert (
        scheduler.post("/v1/workspace-discovery/run").json()["microsoft365"][
            "new_findings"
        ]
        == 0
    )
    records = editor.get("/v1/devices").json()
    assert len(records) == 1 and records[0]["managed"] and records[0]["network_seen"]
    assert MAC not in json.dumps(records)
    assert outside_api.get("/v1/devices").json() == []
    signal = {"source": "dns", "mac": MAC, "seen_at": seen, "count": 1}
    path = "/v1/device-domain-signals"
    assert not collector.post(
        path, json=signal | {"domain": "unrelated.invalid"}
    ).json()["recorded"]
    assert collector.post(
        path, json=signal | {"domain": "user.ai.example.invalid"}
    ).json()["recorded"]
    assert not collector.post(
        path, json=signal | {"domain": "user.ai.example.invalid"}
    ).json()["recorded"]
    rows = editor.get("/v1/registers/discovery").json()
    assert {item["service"] for item in rows} == {"Example app", "ai.example.invalid"}
    assert "user.ai.example.invalid" not in json.dumps(rows)
    assert editor.put(base + "/schedule", json={"enabled": False}).status_code == 200
    assert not editor.get("/v1/workspace-discovery/connections").json()[0]["scheduled"]
    assert scheduler.post("/v1/workspace-discovery/run").json() == {}
