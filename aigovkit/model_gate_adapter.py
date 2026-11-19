"""Apply a tenant provider policy to a dedicated OpenAI-compatible HTTP route."""

import json

import httpx
from pydantic import TypeAdapter, ValidationError
from starlette.responses import JSONResponse

from aigovkit.gate_adapter import EnforcedRoutes
from aigovkit.models import Identifier
from aigovkit.provider_enforcement import ModelID

MODEL = TypeAdapter(ModelID)
PROVIDER = TypeAdapter(Identifier)
MAX_REQUEST_BYTES = 1024 * 1024


def unique_fields(pairs):
    fields = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("Repeated JSON fields are unsupported.")
        fields[key] = value
    return fields


class ModelEnforcedRoutes(EnforcedRoutes):
    """Check the model and exact static scope before dispatching the original request."""

    def __init__(
        self,
        app,
        endpoint: str,
        key: str,
        provider_id: str,
        routes: dict,
        transport=None,
    ):
        super().__init__(app, endpoint, key, routes, transport)
        provider = PROVIDER.validate_python(provider_id)
        self.endpoint = endpoint.rstrip("/") + "/v1/provider-decisions/" + provider

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        governance_scope = self.routes.get((scope["method"], scope["path"]))
        if governance_scope is None:
            await JSONResponse({"detail": "No governed route."}, status_code=403)(
                scope, receive, send
            )
            return

        headers = dict(scope.get("headers", []))
        media_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
        if (
            media_type != b"application/json"
            or headers.get(b"content-encoding", b"identity") != b"identity"
        ):
            await JSONResponse({"detail": "Use uncompressed JSON."}, status_code=415)(
                scope, receive, send
            )
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_REQUEST_BYTES:
                await JSONResponse(
                    {"detail": "Request is too large."}, status_code=413
                )(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        try:
            document = json.loads(body.decode("utf-8"), object_pairs_hook=unique_fields)
            model = MODEL.validate_python(document["model"], strict=True)
        except (KeyError, TypeError, ValidationError, ValueError, RecursionError):
            await JSONResponse(
                {"detail": "A valid model is required."}, status_code=422
            )(scope, receive, send)
            return

        try:
            async with httpx.AsyncClient(
                timeout=5, trust_env=False, transport=self.transport
            ) as client:
                response = await client.post(
                    self.endpoint,
                    headers={"X-API-Key": self.key},
                    json={"model": model, "scope": governance_scope},
                )
            decision = response.json()
            permitted = (
                response.status_code == 200
                and decision.get("decision") == "allow"
                and decision.get("model") == model
            )
        except (httpx.HTTPError, ValueError, AttributeError):
            permitted = False
        if not permitted:
            await JSONResponse(
                {"detail": "Governance gate blocked the model request."},
                status_code=403,
            )(scope, receive, send)
            return

        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
