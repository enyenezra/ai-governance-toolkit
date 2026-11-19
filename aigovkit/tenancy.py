import hashlib
import os
import secrets
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from pydantic import StringConstraints, TypeAdapter, ValidationError

from aigovkit.models import Identifier, StrictModel

api_key = APIKeyHeader(name="X-API-Key", auto_error=False)
Key = Annotated[str, StringConstraints(min_length=32, max_length=256)]


class TenantKeys(StrictModel):
    id: Identifier
    editor_key: Key
    reader_key: Key | None = None


@dataclass(frozen=True)
class Session:
    tenant: str | None
    role: Literal["reader", "editor"]


def configured_tenants() -> list[TenantKeys] | None:
    raw = os.environ.get("AIGOVKIT_TENANTS")
    if raw is None:
        return None
    tenants = TypeAdapter(list[TenantKeys]).validate_json(raw)
    keys = [
        key
        for tenant in tenants
        for key in (tenant.editor_key, tenant.reader_key)
        if key
    ]
    if (
        not tenants
        or len(keys) != len(set(keys))
        or len(tenants) != len({t.id for t in tenants})
    ):
        raise ValueError("Tenant IDs and keys must be unique.")
    return tenants


def schema_for(tenant: str) -> str:
    return "tenant_" + hashlib.sha256(tenant.encode()).hexdigest()[:48]


def authenticate(
    request: Request, provided: Annotated[str | None, Security(api_key)]
) -> Session:
    try:
        tenants = configured_tenants()
    except (ValidationError, ValueError):
        raise HTTPException(503, "Tenant authentication is misconfigured.") from None
    key = (provided or "").encode()

    if tenants is None:
        expected = os.environ.get("AIGOVKIT_API_KEY", "")
        if len(expected) < 32:
            raise HTTPException(503, "Governance API key is not configured.")
        if secrets.compare_digest(key, expected.encode()):
            return Session(None, "editor")
    else:
        for tenant in tenants:
            if secrets.compare_digest(key, tenant.editor_key.encode()):
                return Session(tenant.id, "editor")
            if tenant.reader_key and secrets.compare_digest(
                key, tenant.reader_key.encode()
            ):
                if request.method not in {"GET", "HEAD"}:
                    raise HTTPException(403, "An editor key is required.")
                return Session(tenant.id, "reader")
    raise HTTPException(401, "Invalid API key.")
