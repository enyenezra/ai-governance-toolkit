"""Tenant-bound model enforcement for operator-integrated request gateways."""

import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import Field, StringConstraints

from aigovkit.api import Store
from aigovkit.foundation import Actor, Limit, Offset, database_call
from aigovkit.guardrails import gateway, get, insert
from aigovkit.models import Identifier, Simulation, StrictModel
from aigovkit.policy_review import named_member
from aigovkit.tenancy import authenticate

router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])
ModelID = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
]
ProviderType = Literal[
    "openai_compatible",
    "azure_openai",
    "anthropic",
    "gemini",
    "bedrock",
    "copilot",
    "internal",
    "mcp",
    "self_hosted",
]
CAPABILITIES = (
    "model_allowlisting",
    "request_interception",
    "input_validation",
    "output_filtering",
    "data_redaction",
    "tool_call_authorisation",
    "agent_suspension",
    "request_logging",
    "token_cost_limits",
    "policy_deployment",
    "configuration_rollback",
)


class Registration(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    provider_type: ProviderType
    endpoint: str = Field(min_length=1, max_length=300)
    gateway_member: Identifier | None = None
    account_id: Identifier | None = None
    available_models: list[ModelID] = Field(default_factory=list, max_length=100)


class Deployment(StrictModel):
    expected_version: int = Field(ge=0, le=2_147_483_646)
    allowed_models: list[ModelID] = Field(default_factory=list, max_length=100)
    rollback_to: int | None = Field(default=None, ge=1, le=2_147_483_647)


class Decision(StrictModel):
    model: ModelID
    scope: Simulation


class Evidence(StrictModel):
    allowed_check: Identifier
    denied_check: Identifier


def supported(registration: dict) -> bool:
    return registration["provider_type"] in {
        "openai_compatible",
        "internal",
        "self_hosted",
    } and bool(registration["gateway_member"])


def read_registration(cursor, provider_id):
    value = get(cursor, "provider_registration", provider_id)
    if not value:
        raise HTTPException(404, "Provider not found.")
    return value


@router.post("/providers/{provider_id}", status_code=201)
def register_provider(
    provider_id: Identifier, config: Registration, actor: Actor, store: Store
) -> dict:
    author = named_member(actor, "editor")
    try:
        uri = urlsplit(config.endpoint)
        valid = (
            uri.scheme == "https"
            and uri.hostname
            and not any([uri.username, uri.password, uri.query, uri.fragment])
        )
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(
            422, "Provide an HTTPS endpoint without embedded credentials."
        )
    record = {"id": provider_id, "author": author, **config.model_dump()}

    def write():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || %s,0))",
                (":provider:" + provider_id,),
            )
            if get(cursor, "provider_registration", provider_id):
                raise HTTPException(409, "Provider ID is already registered.")
            insert(cursor, "provider_registration", provider_id, record)
            store.audit(cursor, "provider.registered", "provider", provider_id)
            return record

    return database_call(write)


@router.get("/providers")
def providers(store: Store, offset: Offset = 0, limit: Limit = 20) -> list[dict]:
    entries = database_call(store.documents, "provider_registration", offset, limit)
    results = []
    with_status = {
        "model_allowlisting",
        "request_interception",
        "request_logging",
        "policy_deployment",
        "configuration_rollback",
    }

    def read():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            for entry in entries:
                current = get(cursor, "provider_current", entry["id"])
                verified = get(cursor, "provider_verification", entry["id"])
                if (
                    not current
                    or not verified
                    or verified["version"] != current["version"]
                ):
                    verified = None
                configurable = supported(entry)
                results.append(
                    {
                        **entry,
                        "capabilities": {
                            key: (
                                "gateway"
                                if configurable and key in with_status
                                else "unsupported"
                            )
                            for key in CAPABILITIES
                        },
                        "status": "verified_gateway_checks"
                        if verified
                        else (
                            "deployed_unverified"
                            if current
                            else "not_deployed"
                            if configurable
                            else "unsupported"
                        ),
                        "deployment": current,
                        "verification": verified,
                    }
                )
        return results

    return database_call(read)


@router.post("/provider-deployments/{provider_id}")
def deploy(
    provider_id: Identifier, request: Deployment, actor: Actor, store: Store
) -> dict:
    publisher = named_member(actor, "publisher")

    def write():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || %s,0))",
                (":provider:" + provider_id,),
            )
            entry = read_registration(cursor, provider_id)
            if not supported(entry):
                raise HTTPException(
                    409, "This integration does not support gateway enforcement."
                )
            if entry["author"] == publisher:
                raise HTTPException(403, "An independent publisher is required.")
            current = get(cursor, "provider_current", provider_id)
            version = current["version"] if current else 0
            if request.expected_version != version:
                raise HTTPException(409, "Refresh the deployment version.")
            models = request.allowed_models
            if request.rollback_to:
                if models:
                    raise HTTPException(
                        422, "Rollback cannot specify a different allowlist."
                    )
                previous = get(
                    cursor,
                    "provider_deployment",
                    f"{provider_id}:{request.rollback_to}",
                )
                if not previous:
                    raise HTTPException(404, "Previous deployment not found.")
                models = previous["allowed_models"]
            if set(models) - set(entry["available_models"]):
                raise HTTPException(
                    422, "The allowlist must contain registered models only."
                )
            body = {
                "provider_id": provider_id,
                "version": version + 1,
                "allowed_models": sorted(set(models)),
                "publisher": publisher,
                "rollback_to": request.rollback_to,
            }
            insert(
                cursor, "provider_deployment", f"{provider_id}:{body['version']}", body
            )
            cursor.execute(
                """INSERT INTO foundation_documents (kind,id,body) VALUES ('provider_current',%s,%s)
                   ON CONFLICT(kind,id) DO UPDATE SET body=EXCLUDED.body""",
                (provider_id, Jsonb(body)),
            )
            store.audit(
                cursor, "provider.deployed", "provider", provider_id, body["version"]
            )
            return body

    return database_call(write)


@router.post("/provider-decisions/{provider_id}")
def decide(
    provider_id: Identifier, request: Decision, actor: Actor, store: Store
) -> JSONResponse:
    member = named_member(actor, "gateway")

    def read():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            entry = read_registration(cursor, provider_id)
            if not supported(entry) or entry["gateway_member"] != member:
                raise HTTPException(403, "This gateway cannot use the provider.")
            return get(cursor, "provider_current", provider_id)

    current = database_call(read)
    permit = False
    reason = "The requested model is outside the deployed allowlist."
    scope_check = None
    if current and request.model in current["allowed_models"]:
        scoped = gateway(request.scope, actor, store)
        permit = scoped.status_code == 200
        scope_check = json.loads(scoped.body)["id"]
        reason = (
            "Model and action allowed."
            if permit
            else "The existing agent guardrail denied this action."
        )
    body = {
        "id": uuid4().hex,
        "provider_id": provider_id,
        "version": current["version"] if current else None,
        "model": request.model,
        "decision": "allow" if permit else "deny",
        "reason": reason,
        "scope_check": scope_check,
    }

    def record():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock_shared(hashtextextended(current_schema() || %s,0))",
                (":provider:" + provider_id,),
            )
            latest = get(cursor, "provider_current", provider_id)
            if (latest["version"] if latest else None) != body["version"]:
                body.update(
                    decision="deny",
                    reason="Provider deployment changed during evaluation.",
                )
            insert(cursor, "provider_check", body["id"], body)
            store.audit(
                cursor,
                "provider." + body["decision"],
                "provider",
                provider_id,
                body["version"],
            )

    database_call(record)
    return JSONResponse(body, status_code=200 if body["decision"] == "allow" else 403)


@router.post("/provider-verifications/{provider_id}")
def verify(
    provider_id: Identifier, evidence: Evidence, actor: Actor, store: Store
) -> dict:
    reviewer = named_member(actor, "publisher")

    def write():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            current = get(cursor, "provider_current", provider_id)
            if not current:
                raise HTTPException(409, "Deploy the provider policy before verifying.")
            for expected, check_id in (
                ("allow", evidence.allowed_check),
                ("deny", evidence.denied_check),
            ):
                check = get(cursor, "provider_check", check_id)
                if not check or (
                    check["provider_id"],
                    check["version"],
                    check["decision"],
                ) != (
                    provider_id,
                    current["version"],
                    expected,
                ):
                    raise HTTPException(
                        422,
                        "Use matching allow and deny evidence from the current deployment.",
                    )
            body = {
                "version": current["version"],
                "verified_at": datetime.now(UTC).isoformat(),
                "verified_by": reviewer,
                "coverage": "gateway_decisions",
                **evidence.model_dump(),
            }
            cursor.execute(
                """INSERT INTO foundation_documents (kind,id,body) VALUES ('provider_verification',%s,%s)
                   ON CONFLICT(kind,id) DO UPDATE SET body=EXCLUDED.body""",
                (provider_id, Jsonb(body)),
            )
            store.audit(
                cursor, "provider.verified", "provider", provider_id, body["version"]
            )
            return body

    return database_call(write)


@router.get("/provider-checks/{provider_id}")
def checks(
    provider_id: Identifier, actor: Actor, store: Store, limit: Limit = 20
) -> list[dict]:
    if not actor.member or actor.role not in {"publisher", "auditor"}:
        raise HTTPException(403, "A named publisher or auditor is required.")

    def read():
        with store.connect() as conn:
            return [
                row[0]
                for row in conn.execute(
                    """SELECT body FROM foundation_documents
                       WHERE kind='provider_check' AND body->>'provider_id'=%s
                       ORDER BY created_at DESC,id DESC LIMIT %s""",
                    (provider_id, limit),
                )
            ]

    return database_call(read)
