"""ASGI adapter that enforces AIGovKit decisions in an external application."""

from urllib.parse import urlsplit

import httpx
from starlette.responses import JSONResponse


class EnforcedRoutes:
    """Wrap exact, dedicated HTTP routes with operator-defined governance scopes."""

    def __init__(self, app, endpoint: str, key: str, routes: dict, transport=None):
        uri = urlsplit(endpoint)
        if (
            uri.scheme != "https"
            or not uri.hostname
            or uri.username
            or uri.password
            or uri.query
            or uri.fragment
        ):
            raise ValueError("Use a trusted HTTPS governance endpoint.")
        if len(key) < 32:
            raise ValueError("A scoped gateway key is required.")
        self.app = app
        self.endpoint = endpoint.rstrip("/") + "/v1/guardrail-checks"
        self.key = key
        self.routes = dict(routes)
        self.transport = transport

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        request = self.routes.get((scope["method"], scope["path"]))
        if request is None:
            await JSONResponse({"detail": "No governed route."}, status_code=403)(
                scope, receive, send
            )
            return
        try:
            async with httpx.AsyncClient(
                timeout=5, trust_env=False, transport=self.transport
            ) as client:
                response = await client.post(
                    self.endpoint, headers={"X-API-Key": self.key}, json=request
                )
            allowed = (
                response.status_code == 200
                and response.json().get("decision") == "allow"
            )
        except (httpx.HTTPError, ValueError, AttributeError):
            allowed = False
        if allowed:
            await self.app(scope, receive, send)
        else:
            await JSONResponse(
                {"detail": "Governance gate blocked the operation."}, status_code=403
            )(scope, receive, send)
