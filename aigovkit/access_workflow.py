"""Directory lifecycle and access recommendations with independent decisions."""

import os
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from aigovkit.api import Store, load
from aigovkit.directory import MemberInput
from aigovkit.enterprise import Text
from aigovkit.foundation import Actor, Limit, Offset, database_call
from aigovkit.models import Identifier, Simulation, StrictModel
from aigovkit.policy import evaluate
from aigovkit.policy_review import named_member
from aigovkit.tenancy import authenticate, configured_tenants

router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])


class AccessRequest(StrictModel):
    simulation: Simulation
    group: Identifier
    justification: Text


class AccessDecision(StrictModel):
    request_id: Identifier
    decision: Literal["approved", "denied"]
    rationale: Text


class Recertification(StrictModel):
    request_id: Identifier
    justification: Text


@router.put("/identity/members/{member_id}")
def provision(
    member_id: Identifier, request: MemberInput, actor: Actor, store: Store
) -> dict:
    named_member(actor, "identity_admin")
    issuer = os.getenv("AIGOVKIT_OIDC_ISSUER")
    if not issuer:
        raise HTTPException(503, "Configure an OIDC issuer before provisioning.")
    tenants = configured_tenants() or []
    if any(
        (tenant.id == actor.tenant and member.id == member_id)
        or member.oidc_subject == request.subject
        for tenant in tenants
        for member in tenant.members
    ):
        raise HTTPException(
            409, "The member ID or subject is managed by deployment configuration."
        )

    def write():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended('member:' || %s || ':' || %s, 0))",
                (actor.tenant, member_id),
            )
            current = cursor.execute(
                """SELECT * FROM public.governance_members
                   WHERE tenant_id=%s AND member_id=%s FOR UPDATE""",
                (actor.tenant, member_id),
            ).fetchone()
            version = current["version"] if current else 0
            if request.expected_version != version:
                raise HTTPException(
                    409, "Load the current member version before provisioning."
                )
            if current and (current["subject"], current["issuer"]) != (
                request.subject,
                issuer,
            ):
                raise HTTPException(
                    409, "A stable member ID cannot be assigned a new identity."
                )
            if not current and request.state != "active":
                raise HTTPException(422, "A new member must start active.")
            row = cursor.execute(
                """
                INSERT INTO public.governance_members
                  (tenant_id, member_id, issuer, subject, role, state, groups, version)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id,member_id) DO UPDATE SET
                    role=EXCLUDED.role, state=EXCLUDED.state, groups=EXCLUDED.groups,
                    version=EXCLUDED.version
                RETURNING member_id, subject, role, state, groups, version
                """,
                (
                    actor.tenant,
                    member_id,
                    issuer,
                    request.subject,
                    request.role,
                    request.state,
                    sorted(set(request.groups)),
                    version + 1,
                ),
            ).fetchone()
            action = (
                "joined"
                if not current
                else "left"
                if request.state == "suspended"
                else "changed"
            )
            store.audit(
                cursor, f"identity.{action}", "member", member_id, row["version"]
            )
            return row

    try:
        return write()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "The subject is already managed.") from None
    except psycopg.Error:
        raise HTTPException(503, "Governance database unavailable.") from None


@router.get("/identity/members")
def directory(
    actor: Actor, store: Store, offset: Offset = 0, limit: Limit = 20
) -> list[dict]:
    named_member(actor, "identity_admin")

    def read():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(
                """SELECT member_id, subject, role, state, groups, version
                   FROM public.governance_members WHERE tenant_id=%s
                   ORDER BY member_id LIMIT %s OFFSET %s""",
                (actor.tenant, limit, offset),
            ).fetchall()

    return database_call(read)


def request_access(
    request: AccessRequest, store: Store, actor, previous: str | None = None
) -> dict:
    if actor.member is None:
        raise HTTPException(403, "A named member is required.")
    if request.simulation.policy_version != "1.1.0":
        raise HTTPException(422, "Use department and purpose policy version 1.1.0.")
    if request.simulation.role != request.group:
        raise HTTPException(
            422, "The simulated role must match the requested identity group."
        )
    assessment = evaluate(request.simulation, load(store)).model_dump(mode="json")

    def write():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            if previous:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || %s,0))",
                    (f":recertify:{previous}",),
                )
                if cursor.execute(
                    """SELECT 1 FROM foundation_documents WHERE kind='access_request'
                       AND body->>'previous'=%s AND body->>'status' IN ('pending','approved')
                       LIMIT 1""",
                    (previous,),
                ).fetchone():
                    raise HTTPException(
                        409, "A recertification already exists for that request."
                    )
            identity = cursor.execute(
                """SELECT groups FROM public.governance_members
                   WHERE tenant_id=%s AND member_id=%s AND state='active'""",
                (actor.tenant, actor.member),
            ).fetchone()
            if not identity or request.group not in identity["groups"]:
                assessment.update(
                    disposition="deny",
                    risk="high",
                    reasons=[
                        *assessment["reasons"],
                        "The requester lacks the managed identity group.",
                    ],
                )
            record = {
                "id": uuid4().hex,
                "requester": actor.member,
                "status": "pending",
                "request": request.model_dump(mode="json"),
                "assessment": assessment,
                "previous": previous,
            }
            cursor.execute(
                "INSERT INTO foundation_documents (kind,id,body) VALUES ('access_request',%s,%s)",
                (record["id"], Jsonb(record)),
            )
            store.audit(cursor, "access.requested", "access_request", record["id"])
            return record

    return database_call(write)


@router.post("/access-requests", status_code=201)
def create_request(request: AccessRequest, store: Store, actor: Actor) -> dict:
    return request_access(request, store, actor)


@router.get("/access-requests")
def queue(
    actor: Actor, store: Store, offset: Offset = 0, limit: Limit = 20
) -> list[dict]:
    if actor.member is None:
        raise HTTPException(403, "A named member is required.")

    def read():
        with store.connect() as conn:
            rows = conn.execute(
                """SELECT body FROM foundation_documents WHERE kind='access_request'
                   AND (%s OR body->>'requester'=%s)
                   ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s""",
                (actor.role == "reviewer", actor.member, limit, offset),
            ).fetchall()
            return [row[0] for row in rows]

    return database_call(read)


@router.post("/access-decisions")
def decide(request: AccessDecision, store: Store, actor: Actor) -> dict:
    reviewer = named_member(actor, "reviewer")
    records = load(store)

    def write():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                """SELECT body FROM foundation_documents
                   WHERE kind='access_request' AND id=%s FOR UPDATE""",
                (request.request_id,),
            ).fetchone()
            if not row:
                raise HTTPException(404, "Access request not found.")
            body = row["body"]
            if body["requester"] == reviewer:
                raise HTTPException(403, "A requester cannot review their own access.")
            if body["status"] != "pending":
                raise HTTPException(409, "The access request has already been decided.")
            if request.decision == "approved":
                current_group = cursor.execute(
                    """SELECT groups FROM public.governance_members
                       WHERE tenant_id=%s AND member_id=%s AND state='active' FOR SHARE""",
                    (actor.tenant, body["requester"]),
                ).fetchone()
                simulation = Simulation.model_validate(body["request"]["simulation"])
                still_allowed = (
                    evaluate(simulation, records).disposition == "consider_after_review"
                )
                if (
                    not current_group
                    or body["request"]["group"] not in current_group["groups"]
                    or body["assessment"]["disposition"] == "deny"
                    or not still_allowed
                ):
                    raise HTTPException(
                        409, "Current group or policy checks do not support approval."
                    )
            now = datetime.now(UTC)
            body.update(
                status=request.decision,
                reviewer=reviewer,
                rationale=request.rationale,
                decided_at=now.isoformat(),
                recertify_by=(now + timedelta(days=90)).date().isoformat()
                if request.decision == "approved"
                else None,
            )
            cursor.execute(
                "UPDATE foundation_documents SET body=%s WHERE kind='access_request' AND id=%s",
                (Jsonb(body), request.request_id),
            )
            store.audit(
                cursor,
                f"access.{request.decision}",
                "access_request",
                request.request_id,
            )
            return body

    return database_call(write)


@router.post("/access-recertifications", status_code=201)
def recertify(request: Recertification, actor: Actor, store: Store) -> dict:
    previous = database_call(store.get_document, "access_request", request.request_id)
    if not previous or previous["requester"] != actor.member:
        raise HTTPException(404, "Access request not found.")
    if previous["status"] != "approved":
        raise HTTPException(409, "Only an approved recommendation can be recertified.")
    data = AccessRequest.model_validate(
        previous["request"] | {"justification": request.justification}
    )
    return request_access(data, store, actor, previous["id"])


@router.get("/access-recertifications")
def due_recertifications(
    actor: Actor, store: Store, offset: Offset = 0, limit: Limit = 20
) -> list[dict]:
    if actor.member is None:
        raise HTTPException(403, "A named member is required.")

    def read():
        with store.connect() as conn:
            rows = conn.execute(
                """
                SELECT a.body FROM foundation_documents a
                WHERE a.kind='access_request' AND a.body->>'status'='approved'
                  AND a.body->>'recertify_by' <= %s
                  AND (%s OR a.body->>'requester'=%s)
                  AND NOT EXISTS (
                    SELECT 1 FROM foundation_documents child
                    WHERE child.kind='access_request' AND child.body->>'previous'=a.id
                      AND child.body->>'status' IN ('pending','approved')
                  )
                ORDER BY a.body->>'recertify_by',a.id LIMIT %s OFFSET %s
                """,
                (
                    datetime.now(UTC).date().isoformat(),
                    actor.role == "reviewer",
                    actor.member,
                    limit,
                    offset,
                ),
            ).fetchall()
            return [row[0] for row in rows]

    return database_call(read)
