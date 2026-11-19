import hashlib
import os
import secrets
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, StringConstraints, TypeAdapter, ValidationError

from aigovkit.models import Identifier, StrictModel
from aigovkit.oidc import CHALLENGE, invalid_token, verify_access_token

api_key = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer = HTTPBearer(auto_error=False)
Key = Annotated[str, StringConstraints(min_length=32, max_length=256)]


Role = Literal["reader", "editor", "reviewer", "publisher", "auditor"]


class MemberKey(StrictModel):
    id: Identifier
    role: Role
    key: Key | None = None
    oidc_subject: (
        Annotated[str, StringConstraints(min_length=1, max_length=255)] | None
    ) = None


class TenantKeys(StrictModel):
    id: Identifier
    editor_key: Key | None = None
    reader_key: Key | None = None
    members: list[MemberKey] = Field(default_factory=list, max_length=100)


@dataclass(frozen=True)
class Session:
    tenant: str | None
    role: Role
    member: str | None = None
    credential: Literal["api_key", "oidc"] = "api_key"


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
    subjects: list[str] = []
    for tenant in tenants:
        if not tenant.editor_key and not tenant.members:
            raise ValueError("Every tenant requires configured credentials.")
        if len({member.id for member in tenant.members}) != len(tenant.members):
            raise ValueError("Member IDs must be unique within their tenant.")
        if any(not member.key and not member.oidc_subject for member in tenant.members):
            raise ValueError("Each member requires an authentication method.")
        keys.extend(member.key for member in tenant.members if member.key)
        subjects.extend(
            member.oidc_subject for member in tenant.members if member.oidc_subject
        )
    if (
        not tenants
        or len(keys) != len(set(keys))
        or len(subjects) != len(set(subjects))
        or len(tenants) != len({t.id for t in tenants})
    ):
        raise ValueError("Tenant IDs and keys must be unique.")
    return tenants


def schema_for(tenant: str) -> str:
    return "tenant_" + hashlib.sha256(tenant.encode()).hexdigest()[:48]


def authorize_member(request: Request, session: Session) -> Session:
    allowed_post = request.method == "POST" and (
        request.url.path == "/v1/policy-acknowledgements"
        or (session.role == "reviewer" and request.url.path == "/v1/policy-reviews")
        or (
            session.role == "publisher"
            and request.url.path == "/v1/policy-publications"
        )
    )
    if (
        request.method not in {"GET", "HEAD"}
        and session.role != "editor"
        and not allowed_post
    ):
        raise HTTPException(403, "This role cannot perform that operation.")
    return session


def authenticate(
    request: Request,
    provided: Annotated[str | None, Security(api_key)],
    authorization: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
) -> Session:
    try:
        tenants = configured_tenants()
    except (ValidationError, ValueError):
        raise HTTPException(503, "Tenant authentication is misconfigured.") from None

    if "authorization" in request.headers:
        if provided is not None:
            raise HTTPException(400, "Send one authentication credential.")
        if not authorization or not tenants:
            raise invalid_token()
        subject = verify_access_token(authorization.credentials)
        for tenant in tenants:
            for member in tenant.members:
                if member.oidc_subject == subject:
                    return authorize_member(
                        request, Session(tenant.id, member.role, member.id, "oidc")
                    )
        raise HTTPException(
            403, "This identity has no configured membership.", headers=CHALLENGE
        )

    key = (provided or "").encode()
    if tenants is None:
        expected = os.environ.get("AIGOVKIT_API_KEY", "")
        if len(expected) < 32:
            raise HTTPException(503, "Governance API key is not configured.")
        if secrets.compare_digest(key, expected.encode()):
            return Session(None, "editor")
    else:
        for tenant in tenants:
            for member in tenant.members:
                if member.key and secrets.compare_digest(key, member.key.encode()):
                    return authorize_member(
                        request, Session(tenant.id, member.role, member.id)
                    )
            if tenant.editor_key and secrets.compare_digest(
                key, tenant.editor_key.encode()
            ):
                return Session(tenant.id, "editor")
            if tenant.reader_key and secrets.compare_digest(
                key, tenant.reader_key.encode()
            ):
                if request.method not in {"GET", "HEAD"}:
                    raise HTTPException(403, "An editor key is required.")
                return Session(tenant.id, "reader")
    raise HTTPException(401, "Invalid API key.", headers=CHALLENGE)
