"""Tenant executive reporting, in-product reminders and signed audit exports."""

import base64
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import Field

from aigovkit.api import Store, load
from aigovkit.foundation import Actor, Limit, Offset, database_call
from aigovkit.models import Agent, Identifier, StrictModel, Tool
from aigovkit.policy_outputs import schedule
from aigovkit.policy_review import named_member
from aigovkit.tenancy import authenticate

router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])


@router.get("/executive-report")
def executive_report(
    store: Store,
    department: Identifier | None = None,
    system: Identifier | None = None,
    risk: Literal["low", "medium", "high"] | None = None,
    disposition: Literal["deny", "consider_after_review"] | None = None,
    days: Annotated[int, Query(ge=1, le=366)] = 90,
) -> dict:
    now = datetime.now(UTC)
    entries = load(store)
    system_agents = [
        entry.id
        for entry in entries
        if isinstance(entry, Agent) and (entry.id == system or entry.tool_id == system)
    ]

    def read():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(
                """
                SELECT (created_at AT TIME ZONE 'UTC')::date AS day,
                    body->'assessment'->>'risk' AS risk, count(*) AS total
                FROM governance_reports
                WHERE created_at >= %s
                  AND (%s::text IS NULL OR body->'request'->>'department_id'=%s)
                  AND (%s::text IS NULL OR body->'request'->>'agent_id'=ANY(%s))
                  AND (%s::text IS NULL OR body->'assessment'->>'risk'=%s)
                  AND (%s::text IS NULL OR body->'assessment'->>'disposition'=%s)
                GROUP BY day,risk ORDER BY day,risk
                """,
                (
                    now - timedelta(days=days),
                    department,
                    department,
                    system,
                    system_agents,
                    risk,
                    risk,
                    disposition,
                    disposition,
                ),
            ).fetchall()

    trend = database_call(read)
    return {
        "from": (now - timedelta(days=days)).date(),
        "through": now.date(),
        "filters": {
            "department": department,
            "system": system,
            "risk": risk,
            "disposition": disposition,
            "days": days,
        },
        "inventory": {
            "tools": sum(isinstance(item, Tool) for item in entries),
            "agents": sum(isinstance(item, Agent) for item in entries),
        },
        "report_count": sum(row["total"] for row in trend),
        "trend": trend,
    }


@router.post("/review-reminders/run")
def queue_reminders(store: Store, actor: Actor) -> dict:
    named_member(actor, "scheduler" if actor.role == "scheduler" else "editor")
    due = []
    offset = 0
    while batch := schedule(store, offset, 100):
        due.extend(item for item in batch if item["due"])
        if len(batch) < 100 or not batch[-1]["due"]:
            break
        offset += len(batch)

    def write():
        created = 0
        with store.connect() as conn:
            for item in due:
                key = f"{item['draft_id']}:{item['version']}"
                body = {
                    **item,
                    "due_date": item["due_date"].isoformat(),
                    "published_at": item["published_at"].isoformat(),
                }
                count = conn.execute(
                    """INSERT INTO foundation_documents (kind,id,body)
                       VALUES ('review_reminder',%s,%s) ON CONFLICT DO NOTHING""",
                    (key, Jsonb(body)),
                ).rowcount
                if count:
                    store.audit(
                        conn,
                        "policy.review_reminder",
                        "policy",
                        item["draft_id"],
                        item["version"],
                    )
                    created += count
        return {"queued": created}

    return database_call(write)


@router.get("/review-reminders")
def reminders(store: Store, offset: Offset = 0, limit: Limit = 20) -> list[dict]:
    return database_call(store.documents, "review_reminder", offset, limit)


def canonical(payload: dict) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


@router.get("/audit-export")
def audit_export(
    store: Store,
    actor: Actor,
    limit: Limit = 100,
    before: Annotated[int | None, Query(ge=1, le=9_223_372_036_854_775_807)] = None,
) -> dict:
    named_member(actor, "auditor")
    try:
        path = Path(os.environ["AIGOVKIT_AUDIT_SIGNING_KEY_FILE"])
        with path.open("rb") as stream:
            key = serialization.load_pem_private_key(stream.read(16384), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise TypeError
    except (KeyError, OSError, TypeError, ValueError):
        raise HTTPException(503, "Audit signing key is unavailable.") from None
    events = database_call(store.audit_events, before, limit)
    payload = {
        "schema": "aigovkit.audit.v1",
        "tenant": actor.tenant,
        "exported_at": datetime.now(UTC).isoformat(),
        "coverage": "event_page",
        "before": before,
        "events": [
            {**row, "occurred_at": row["occurred_at"].isoformat()} for row in events
        ],
    }
    public = key.public_key().public_bytes_raw()
    return {
        "payload": payload,
        "algorithm": "Ed25519",
        "key_fingerprint": hashlib.sha256(public).hexdigest(),
        "signature": base64.b64encode(key.sign(canonical(payload))).decode(),
    }


class Retention(StrictModel):
    days: int = Field(ge=30, le=3650)
    apply: bool = False


@router.post("/retention/audit")
def retention(request: Retention, store: Store, actor: Actor) -> dict:
    named_member(actor, "auditor")
    cutoff = datetime.now(UTC) - timedelta(days=request.days)
    if request.apply and os.getenv("AIGOVKIT_ENABLE_AUDIT_PRUNE") != "yes":
        raise HTTPException(403, "Audit pruning is disabled by the operator.")

    def run():
        with store.connect() as conn:
            if request.apply:
                count = conn.execute(
                    """DELETE FROM governance_audit WHERE event_id IN (
                         SELECT event_id FROM governance_audit WHERE occurred_at < %s
                         ORDER BY event_id LIMIT 5000
                       )""",
                    (cutoff,),
                ).rowcount
                store.audit(conn, "audit.retention_applied", "audit", "retention")
            else:
                count = conn.execute(
                    "SELECT count(*) FROM governance_audit WHERE occurred_at < %s",
                    (cutoff,),
                ).fetchone()[0]
            return {"applied": request.apply, "count": count, "cutoff": cutoff}

    return database_call(run)
