import json

import httpx
import pytest

from aigovkit import provider_discovery


@pytest.mark.parametrize(
    ("provider", "method", "url", "response", "expected_type"),
    [
        (
            "entra",
            "GET",
            "https://graph.microsoft.com/v1.0/servicePrincipals",
            {
                "value": [
                    {
                        "id": "a",
                        "displayName": "Synthetic service",
                        "servicePrincipalType": "Application",
                    }
                ],
                "@odata.nextLink": "opaque",
            },
            "Application",
        ),
        (
            "microsoft365",
            "GET",
            "https://graph.microsoft.com/v1.0/subscribedSkus",
            {"value": [{"id": "a", "skuPartNumber": "SYNTHETIC"}]},
            "subscription_sku",
        ),
        (
            "azure",
            "GET",
            "https://management.azure.com/subscriptions/00000000-0000-0000-0000-000000000000/resources",
            {"value": [{"id": "a", "name": "Synthetic resource", "type": "Model"}]},
            "Model",
        ),
        (
            "purview",
            "POST",
            "https://catalog.example.invalid/datamap/api/search/query",
            {
                "value": [
                    {"id": "a", "name": "Synthetic asset", "entityType": "dataset"}
                ]
            },
            "dataset",
        ),
        (
            "ai-gateway",
            "GET",
            "https://gateway.example.invalid/v1/models",
            {"data": [{"id": "a", "owned_by": "ignore"}]},
            "model",
        ),
    ],
)
def test_read_only_http_connectors(
    monkeypatch, provider, method, url, response, expected_type
):
    monkeypatch.setenv(
        "AIGOVKIT_AZURE_SUBSCRIPTION", "00000000-0000-0000-0000-000000000000"
    )
    monkeypatch.setenv("AIGOVKIT_PURVIEW_URL", "https://catalog.example.invalid")
    monkeypatch.setenv(
        "AIGOVKIT_GATEWAY_MODELS_URL", "https://gateway.example.invalid/v1/models"
    )
    calls = []

    def handle(request):
        calls.append(request)
        assert request.method == method
        assert str(request.url).split("?")[0] == url
        return httpx.Response(200, json=response)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = provider_discovery.discover(provider, client)
    assert len(calls) == 1
    assert result["records"][0]["type"] == expected_type
    assert set(result["records"][0]) == {"id", "name", "type"}
    assert result["partial"] == (provider == "entra")


def test_mcp_discovery_never_calls_tools(monkeypatch):
    monkeypatch.setenv("AIGOVKIT_MCP_URL", "https://mcp.example.invalid/")
    methods = []

    def handle(request):
        rpc = json.loads(request.content)
        methods.append(rpc["method"])
        if rpc["method"] == "initialize":
            return httpx.Response(
                200,
                headers={"Mcp-Session-Id": "synthetic"},
                json={
                    "id": rpc["id"],
                    "result": {"protocolVersion": "2025-11-25"},
                },
            )
        assert request.headers["Mcp-Session-Id"] == "synthetic"
        if rpc["method"] == "notifications/initialized":
            return httpx.Response(202)
        return httpx.Response(
            200,
            json={
                "id": rpc["id"],
                "result": {
                    "tools": [{"name": "synthetic-tool"}],
                    "nextCursor": "opaque",
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        found = provider_discovery.discover("mcp", client)
    assert methods == ["initialize", "notifications/initialized", "tools/list"]
    assert found["partial"] and found["records"][0]["id"] == "synthetic-tool"


def test_aws_iam_role_metadata(monkeypatch):
    class IAM:
        def list_roles(self, **kwargs):
            assert kwargs == {"MaxItems": 100}
            return {
                "Roles": [{"RoleId": "synthetic", "RoleName": "fixture"}],
                "IsTruncated": True,
            }

    monkeypatch.setattr(provider_discovery.boto3, "client", lambda service: IAM())
    with httpx.Client() as client:
        result = provider_discovery.discover("aws-iam", client)
    assert result == {
        "provider": "aws-iam",
        "partial": True,
        "records": [{"id": "synthetic", "name": "fixture", "type": "iam_role"}],
    }


def test_observation_submission_separates_credentials_and_uses_stable_id(monkeypatch):
    import secrets

    key = secrets.token_urlsafe(32)
    monkeypatch.setenv("AIGOVKIT_OBSERVATION_API", "https://governance.example.invalid")
    monkeypatch.setenv("AIGOVKIT_OBSERVER_KEY", key)
    submitted = []

    def handle(request):
        assert request.headers["X-API-Key"] == key
        assert "Authorization" not in request.headers
        assert json.loads(request.content)["status"] == "needs_review"
        first = not submitted
        submitted.append(request.url.path)
        return httpx.Response(200 if first else 409, json={})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        report = {
            "provider": "entra",
            "partial": False,
            "records": [{"id": "x", "name": "Test"}],
        }
        assert provider_discovery.submit_observations(report, client)["saved"] == 1
        assert (
            provider_discovery.submit_observations(report, client)["already_recorded"]
            == 1
        )
    assert submitted[0] == submitted[1]
