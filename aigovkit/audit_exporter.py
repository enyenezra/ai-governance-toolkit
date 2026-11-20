"""Bounded delivery of minimised audit metadata to an operator-approved sink."""

import csv
import io
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from aigovkit.api import Store
from aigovkit.foundation import Actor, database_call
from aigovkit.models import Identifier
from aigovkit.notification_delivery import configured
from aigovkit.policy_review import named_member
from aigovkit.tenancy import authenticate

router = APIRouter(prefix="/v1/audit-exporter", dependencies=[Depends(authenticate)])
PREFIXES = ("security.", "containment.", "report.", "learning.", "provider.")
ACTION = "audit_export.batch"


@router.post("/run")
def queue_batch(store: Store, actor: Actor) -> dict:
    named_member(actor, "scheduler")
    try:
        enabled = configured(actor.tenant).audit_webhook is not None
    except ValueError:
        raise HTTPException(
            503, "Audit destination configuration is invalid."
        ) from None
    if not enabled:
        return {"state": "disabled", "events": 0}

    def queue():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':audit_export',0))"
            )
            pending = cursor.execute(
                """SELECT count(*) AS total FROM notification_outbox
                   WHERE action=%s AND state IN ('queued','sending')""",
                (ACTION,),
            ).fetchone()
            if pending["total"] >= 10:
                return {"state": "backpressure", "events": 0}
            rows = cursor.execute(
                """SELECT event_id,occurred_at,action FROM governance_audit a
                   WHERE action LIKE ANY(%s) AND NOT EXISTS (
                     SELECT 1 FROM foundation_documents d
                     WHERE d.kind='audit_export_receipt' AND d.id=a.event_id::text
                   ) ORDER BY event_id LIMIT 100""",
                ([prefix + "%" for prefix in PREFIXES],),
            ).fetchall()
            if not rows:
                return {"state": "idle", "events": 0}

            batch_id = str(rows[0]["event_id"])
            event_id = store.audit(cursor, ACTION, "audit_export_batch", batch_id)
            batch = {
                "schema_version": "1.0.0",
                "batch_id": batch_id,
                "events": [
                    {**row, "occurred_at": row["occurred_at"].isoformat()}
                    for row in rows
                ],
            }
            cursor.execute(
                "INSERT INTO foundation_documents (kind,id,body) VALUES ('audit_export_batch',%s,%s)",
                (batch_id, Jsonb(batch)),
            )
            cursor.execute(
                """INSERT INTO foundation_documents (kind,id,body)
                   SELECT 'audit_export_receipt',id,%s FROM unnest(%s::text[]) AS inputs(id)""",
                (Jsonb({"batch_id": batch_id}), [str(row["event_id"]) for row in rows]),
            )
            cursor.execute(
                """INSERT INTO notification_outbox
                   (event_id,channel,action,priority,resource_type,resource_id,state)
                   VALUES (%s,'webhook',%s,'info','audit_export_batch',%s,'queued')""",
                (event_id, ACTION, batch_id),
            )
            return {"state": "queued", "events": len(rows), "batch_id": batch_id}

    return database_call(queue)


def require_access(actor: Actor):
    if not actor.member or actor.role not in {"editor", "auditor"}:
        raise HTTPException(403, "Audit exports require a named editor or auditor.")


@router.get("/history")
def history(store: Store, actor: Actor):
    require_access(actor)

    def load():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(
                """SELECT event_id,resource_id AS batch_id,state,attempts,last_error,created_at,delivered_at
                   FROM notification_outbox WHERE action=%s ORDER BY event_id DESC LIMIT 100""",
                (ACTION,),
            ).fetchall()

    return database_call(load)


@router.get("/batches/{batch_id}/{format_name}")
def download(
    batch_id: Identifier,
    format_name: Literal["json", "csv"],
    store: Store,
    actor: Actor,
):
    require_access(actor)
    batch = database_call(store.get_document, "audit_export_batch", batch_id)
    if batch is None:
        raise HTTPException(404, "Audit export batch not found.")
    if format_name == "json":
        return batch
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=("event_id", "occurred_at", "action"))
    writer.writeheader()
    writer.writerows(batch["events"])
    return Response(
        stream.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="audit-{batch_id}.csv"'},
    )
