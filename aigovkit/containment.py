"""Evidence-backed detections and approved, temporary AIGovKit gate restrictions."""

import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import Field

from aigovkit.api import Store, load
from aigovkit.foundation import Actor, Limit, Offset, database_call
from aigovkit.guardrails import get, insert
from aigovkit.models import Agent, Identifier, StrictModel
from aigovkit.policy_review import named_member
from aigovkit.tenancy import authenticate

router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])
VERSION = "1.0.0"


class Proposal(StrictModel):
    finding_id: Identifier
    minutes: int = Field(ge=1, le=60)
    dry_run: bool = True


class Transition(StrictModel):
    action: Literal["approve", "execute", "rollback"]


@router.post("/security-detections/run")
def detect(actor: Actor, store: Store) -> dict:
    named_member(actor, "scheduler" if actor.role == "scheduler" else "editor")
    now = datetime.now(UTC)
    since = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)

    def run():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            groups = cursor.execute(
                """
                WITH evidence AS (
                    SELECT 'repeated_gate_denials' AS rule,id,created_at,body->>'agent_id' AS agent
                    FROM foundation_documents WHERE kind='guardrail_check' AND created_at >= %s
                      AND body->>'decision'='deny' AND body->>'containment_id' IS NULL
                    UNION ALL
                    SELECT 'privileged_action_denied',id,created_at,body->>'agent_id'
                    FROM foundation_documents WHERE kind='guardrail_check' AND created_at >= %s
                      AND body->>'decision'='deny' AND body->>'action' IN ('admin','delete')
                      AND body->>'containment_id' IS NULL
                    UNION ALL
                    SELECT 'model_not_allowlisted',id,created_at,body->>'agent_id'
                    FROM foundation_documents WHERE kind='provider_check' AND created_at >= %s
                      AND body->>'decision'='deny' AND body->>'reason_code'='model_not_allowlisted'
                      AND body->>'version' IS NOT NULL
                ), groups AS (
                    SELECT rule,agent,
                           date_trunc('hour',created_at AT TIME ZONE 'UTC') AS hour,
                           count(*) AS count, (array_agg(id ORDER BY created_at,id))[1:10] AS checks
                    FROM evidence WHERE agent IS NOT NULL GROUP BY rule,agent,hour
                )
                SELECT * FROM groups WHERE rule <> 'repeated_gate_denials' OR count >= 3
                ORDER BY hour,rule,agent
                """,
                (since, since, since),
            ).fetchall()
            created, incidents = 0, 0
            for entry in groups:
                key = hashlib.sha256(
                    f"{VERSION}:{entry['rule']}:{entry['agent']}:{entry['hour']}".encode()
                ).hexdigest()
                severity = (
                    "high" if entry["rule"] == "privileged_action_denied" else "medium"
                )
                finding = {
                    "id": key,
                    "rule": entry["rule"],
                    "rule_version": VERSION,
                    "agent_id": entry["agent"],
                    "window_utc": entry["hour"].isoformat() + "Z",
                    "severity": severity,
                    "count": entry["count"],
                    "evidence_ids": entry["checks"],
                    "detected_at": now.isoformat(),
                }
                inserted = cursor.execute(
                    """INSERT INTO foundation_documents (kind,id,body)
                       VALUES ('security_finding',%s,%s) ON CONFLICT DO NOTHING""",
                    (key, Jsonb(finding)),
                ).rowcount
                if not inserted:
                    continue
                created += 1
                store.audit(cursor, "security.detected", "security_finding", key)
                if severity == "high":
                    owner = os.getenv("AIGOVKIT_INCIDENT_OWNER") or actor.member
                    incident = {
                        "id": key,
                        "kind": "incident",
                        "version": 1,
                        "system_id": entry["agent"],
                        "title": "Denied privileged AI action",
                        "status": "open",
                        "severity": "high",
                        "owner": owner,
                        "update": "Review the denied privileged action and its finding evidence.",
                        "evidence_references": [key],
                    }
                    insert(cursor, "register_incident", key, incident)
                    insert(cursor, "register_incident_history", key + ":1", incident)
                    store.audit(cursor, "incident.alerted", "incident", key, 1)
                    incidents += 1
            return {"findings_created": created, "incidents_created": incidents}

    return database_call(run)


@router.get("/security-findings")
def findings(store: Store, offset: Offset = 0, limit: Limit = 20) -> list[dict]:
    return database_call(store.documents, "security_finding", offset, limit)


@router.get("/containment")
def containment_requests(
    store: Store, offset: Offset = 0, limit: Limit = 20
) -> list[dict]:
    records = database_call(store.documents, "containment_request", offset, limit)
    now = datetime.now(UTC)
    return [
        record | {"status": "expired"}
        if record["status"] in {"approved", "active"}
        and datetime.fromisoformat(
            record["expires_at"]
            if record["status"] == "active"
            else record["approval_expires_at"]
        )
        <= now
        else record
        for record in records
    ]


@router.post("/containment")
def propose(request: Proposal, actor: Actor, store: Store) -> dict:
    editor = named_member(actor, "editor")
    finding = database_call(store.get_document, "security_finding", request.finding_id)
    if not finding:
        raise HTTPException(404, "Security finding not found.")
    if not any(
        isinstance(item, Agent) and item.id == finding["agent_id"]
        for item in load(store)
    ):
        raise HTTPException(
            409, "Only registered agents can receive temporary restrictions."
        )
    body = {
        "id": request.finding_id,
        "agent_id": finding["agent_id"],
        "minutes": request.minutes,
        "target": "aigovkit_gateway",
        "proposed_by": editor,
    }
    if request.dry_run:
        return {**body, "status": "preview", "changes_applied": False}

    def write():
        with store.connect() as conn:
            result = conn.execute(
                """INSERT INTO foundation_documents (kind,id,body)
                   VALUES ('containment_request',%s,%s) ON CONFLICT DO NOTHING""",
                (body["id"], Jsonb({**body, "status": "pending"})),
            )
            if not result.rowcount:
                raise HTTPException(
                    409, "This finding already has a containment request."
                )
            store.audit(conn, "containment.proposed", "containment", body["id"])
        return {**body, "status": "pending"}

    return database_call(write)


@router.post("/containment/{request_id}/transition")
def transition(
    request_id: Identifier, request: Transition, actor: Actor, store: Store
) -> dict:
    publisher = named_member(actor, "publisher")

    def apply():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            record = cursor.execute(
                """SELECT body FROM foundation_documents
                   WHERE kind='containment_request' AND id=%s FOR UPDATE""",
                (request_id,),
            ).fetchone()
            if not record:
                raise HTTPException(404, "Containment request not found.")
            body = record["body"]
            if body["proposed_by"] == publisher:
                raise HTTPException(
                    403, "The requester cannot approve or execute containment."
                )
            state = body["status"]
            now = datetime.now(UTC)
            if request.action == "approve":
                if state != "pending":
                    raise HTTPException(409, "Only pending requests can be approved.")
                body.update(
                    status="approved",
                    approved_by=publisher,
                    approval_expires_at=(now + timedelta(minutes=15)).isoformat(),
                )
            else:
                if state == "active" and request.action == "execute":
                    return body
                if state == "rolled_back" and request.action == "rollback":
                    return body
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || %s,0))",
                    (f":gate:{body['agent_id']}",),
                )
                now = datetime.now(UTC)
                active = get(cursor, "containment_active", body["agent_id"])
                if request.action == "execute":
                    if os.getenv("AIGOVKIT_CONTAINMENT_ENABLED") != "yes":
                        raise HTTPException(
                            403, "Temporary containment is disabled by the operator."
                        )
                    if (
                        state != "approved"
                        or datetime.fromisoformat(body["approval_expires_at"]) <= now
                    ):
                        raise HTTPException(409, "An unexpired approval is required.")
                    if active and datetime.fromisoformat(active["expires_at"]) > now:
                        raise HTTPException(
                            409,
                            "A temporary restriction is already active for this agent.",
                        )
                    body.update(
                        status="active",
                        executed_by=publisher,
                        expires_at=(
                            now + timedelta(minutes=body["minutes"])
                        ).isoformat(),
                    )
                    cursor.execute(
                        """INSERT INTO foundation_documents (kind,id,body)
                           VALUES ('containment_active',%s,%s)
                           ON CONFLICT(kind,id) DO UPDATE SET body=EXCLUDED.body""",
                        (
                            body["agent_id"],
                            Jsonb({"id": request_id, "expires_at": body["expires_at"]}),
                        ),
                    )
                else:
                    if state != "active" or not active or active["id"] != request_id:
                        raise HTTPException(
                            409, "Only the matching active restriction can roll back."
                        )
                    cursor.execute(
                        "DELETE FROM foundation_documents WHERE kind='containment_active' AND id=%s",
                        (body["agent_id"],),
                    )
                    body.update(
                        status="rolled_back",
                        rolled_back_by=publisher,
                        rolled_back_at=now.isoformat(),
                    )
            cursor.execute(
                "UPDATE foundation_documents SET body=%s WHERE kind='containment_request' AND id=%s",
                (Jsonb(body), request_id),
            )
            store.audit(
                cursor, f"containment.{request.action}", "containment", request_id
            )
            return body

    try:
        return database_call(apply)
    except HTTPException as exc:
        if exc.status_code != 404:

            def log_failure():
                with store.connect() as conn:
                    store.audit(
                        conn,
                        f"containment.{request.action}_rejected",
                        "containment",
                        request_id,
                    )

            database_call(log_failure)
        raise
