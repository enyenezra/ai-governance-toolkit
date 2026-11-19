import json
import os
import secrets
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from aigovkit.storage import PostgresInventory
from aigovkit.tenancy import schema_for
from main import app

ISSUER = "https://identity.example.invalid/"
AUDIENCE = "https://governance.example.invalid/"


@pytest.fixture
def oidc(monkeypatch, tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    public.update(kid="test-key", use="sig", alg="RS256")
    path = tmp_path / "jwks.json"
    path.write_text(json.dumps({"keys": [public]}))
    monkeypatch.setenv("AIGOVKIT_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("AIGOVKIT_OIDC_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("AIGOVKIT_OIDC_JWKS_FILE", str(path))
    tenants = [
        {
            "id": f"test-{secrets.token_hex(8)}",
            "members": [
                {"id": "author", "role": "editor", "oidc_subject": "idp-author"},
                {"id": "reviewer", "role": "reviewer", "oidc_subject": "idp-reviewer"},
                {
                    "id": "publisher",
                    "role": "publisher",
                    "oidc_subject": "idp-publisher",
                },
                {"id": "auditor", "role": "auditor", "oidc_subject": "idp-auditor"},
            ],
        },
        {
            "id": f"test-{secrets.token_hex(8)}",
            "members": [
                {"id": "auditor", "role": "auditor", "oidc_subject": "other-auditor"},
            ],
        },
    ]
    monkeypatch.setenv("AIGOVKIT_TENANTS", json.dumps(tenants))

    def token(subject="idp-author", claims=None, headers=None, signing_key=None):
        now = int(time.time())
        return jwt.encode(
            {
                "iss": ISSUER,
                "aud": AUDIENCE,
                "sub": subject,
                "iat": now,
                "exp": now + 300,
                "jti": "synthetic-1",
                "client_id": "fixture",
            }
            | (claims or {}),
            signing_key or key,
            algorithm="RS256",
            headers={"kid": "test-key", "typ": "at+jwt"} | (headers or {}),
        )

    return token, tenants, path


def test_oidc_rejects_untrusted_tokens(oidc):
    token, tenants, path = oidc
    client = TestClient(app)

    def session(value, **headers):
        return client.get(
            "/v1/session", headers={"Authorization": "Bearer " + value} | headers
        )

    assert session(token()).json() == {
        "organisation_id": tenants[0]["id"],
        "role": "editor",
        "member_id": "author",
    }
    assert session(token("unknown")).status_code == 403
    assert session(token(headers={"typ": "JWT"})).status_code == 401
    assert session(token(headers={"kid": "unknown"})).status_code == 401
    assert session(token(claims={"aud": "other"})).status_code == 401
    assert (
        session(token(claims={"iss": "https://other.example.invalid/"})).status_code
        == 401
    )
    assert session(token(claims={"exp": int(time.time()) - 100})).status_code == 401
    assert session(token(claims={"exp": int(time.time()) + 7200})).status_code == 401
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert session(token(signing_key=wrong_key)).status_code == 401
    assert session(token(), **{"X-API-Key": "synthetic"}).status_code == 400
    response = session(
        token("other-auditor", claims={"role": "editor", "tenant": tenants[0]["id"]}),
        **{"X-Tenant-ID": tenants[0]["id"]},
    )
    assert response.json()["organisation_id"] == tenants[1]["id"]
    assert response.json()["role"] == "auditor"
    path.write_text("invalid")
    assert session(token()).status_code == 503


def test_oidc_policy_audit_uses_local_actor_and_tenant(oidc, monkeypatch):
    dsn = os.getenv("AIGOVKIT_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("A disposable PostgreSQL database is required.")
    token, tenants, _ = oidc
    monkeypatch.setenv("AIGOVKIT_DATABASE_URL", dsn)
    for tenant in tenants:
        PostgresInventory(dsn, schema_for(tenant["id"])).initialize()

    def client(subject):
        return TestClient(app, headers={"Authorization": "Bearer " + token(subject)})

    editor, reviewer, publisher, auditor, outsider = [
        client(subject)
        for subject in (
            "idp-author",
            "idp-reviewer",
            "idp-publisher",
            "idp-auditor",
            "other-auditor",
        )
    ]
    profile = {
        "name": "Synthetic profile",
        "sector": "Technology",
        "jurisdiction": "United Kingdom",
        "adoption_stage": "piloting",
    }
    assert auditor.put("/v1/organisation", json=profile).status_code == 403
    assert editor.put("/v1/organisation", json=profile).status_code == 200
    response = editor.post(
        "/v1/policy-drafts",
        json={
            "template_id": "agent-security",
            "owner": "Synthetic owner",
            "scope": "Synthetic agents",
            "review_days": 90,
            "applies_to_agents": False,
        },
    )
    assert response.status_code == 201
    policy = response.json()
    draft_id = policy["id"]
    path = f"/v1/policy-drafts/{draft_id}/revisions"
    target = {"draft_id": draft_id, "version": 1}
    revision = {
        "expected_version": 0,
        "clause_texts": {
            policy["clauses"][0]["id"]: "Review table grants.",
        },
    }
    assert editor.post(path, json=revision).status_code == 201
    assert editor.post(path, json=revision).status_code == 409
    assert editor.post(f"{path}/1/submit").status_code == 200
    assert (
        reviewer.post(
            "/v1/policy-reviews",
            json=target
            | {
                "action": "approved",
                "note": "Sensitive rationale fixture.",
            },
        ).status_code
        == 200
    )
    assert publisher.post("/v1/policy-publications", json=target).status_code == 201
    assert editor.get("/v1/audit-events").status_code == 403
    assert outsider.get("/v1/audit-events").json() == []
    events = auditor.get("/v1/audit-events").json()
    assert [(row["action"], row["actor_id"]) for row in events] == [
        ("policy.published", "publisher"),
        ("policy.approved", "reviewer"),
        ("policy.submitted", "author"),
        ("policy.revised", "author"),
        ("draft.created", "author"),
        ("profile.updated", "author"),
    ]
    assert all(row["credential"] == "oidc" for row in events)
    assert "Sensitive rationale fixture." not in json.dumps(events)
    cursor = events[0]["event_id"]
    assert auditor.get(f"/v1/audit-events?before={cursor}&limit=1").json() == [
        events[1]
    ]
