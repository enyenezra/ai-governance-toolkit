import json

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aigovkit.entra_sync import Mapping, synchronize
from aigovkit.gate_adapter import EnforcedRoutes


def test_external_route_gate_fails_closed():
    application = FastAPI()

    @application.post("/operation")
    def run():
        return {"ran": True}

    def make_client(decision):
        def check(request):
            if decision is None:
                raise httpx.ConnectError("Unavailable")
            return httpx.Response(200, json={"decision": decision})

        return TestClient(
            EnforcedRoutes(
                application,
                "https://gate.example.invalid",
                "x" * 32,
                {("POST", "/operation"): {"agent_id": "fixture"}},
                transport=httpx.MockTransport(check),
            )
        )

    assert make_client("allow").post("/operation").json() == {"ran": True}
    assert make_client("deny").post("/operation").status_code == 403
    assert make_client(None).post("/operation").status_code == 403
    assert make_client("allow").get("/other").status_code == 403


def test_group_sync_preview_and_application():
    group = "00000000-0000-0000-0000-000000000010"
    member = "00000000-0000-0000-0000-000000000011"
    writes = []

    def graph(request):
        assert request.url.host == "graph.microsoft.com"
        return httpx.Response(200, json={"value": [{"id": member}]})

    def governance(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {
                        "member_id": "alice",
                        "subject": "provider-sub",
                        "role": "reader",
                        "state": "active",
                        "version": 1,
                        "groups": ["manual"],
                    }
                ],
            )
        writes.append(json.loads(request.content))
        return httpx.Response(200, json={})

    mapping = Mapping(groups={"support": group}, members={"alice": member})
    with (
        httpx.Client(transport=httpx.MockTransport(graph)) as g,
        httpx.Client(transport=httpx.MockTransport(governance)) as a,
    ):
        assert synchronize(g, a, "https://gov.example.invalid", mapping, False) == {
            "planned": 1,
            "applied": 0,
        }
        assert not writes
        assert synchronize(g, a, "https://gov.example.invalid", mapping, True) == {
            "planned": 1,
            "applied": 1,
        }
    assert writes[0]["groups"] == ["manual", "support"]
    assert writes[0]["expected_version"] == 1


def test_provider_pagination_rejects_a_different_host():
    import pytest

    from aigovkit.provider_discovery import discover

    def graph(request):
        assert request.url.host == "graph.microsoft.com"
        return httpx.Response(
            200, json={"value": [], "@odata.nextLink": "https://other.invalid/next"}
        )

    with (
        httpx.Client(transport=httpx.MockTransport(graph)) as client,
        pytest.raises(ValueError, match="Unexpected provider"),
    ):
        discover("entra", client, pages=2)
