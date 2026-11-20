"""Notifications API and a bounded, lease-based delivery worker."""

from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Path
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import Field

from aigovkit.api import Store
from aigovkit.audit_exporter import ACTION as AUDIT_BATCH
from aigovkit.foundation import Actor, Limit, Offset, database_call
from aigovkit.models import StrictModel
from aigovkit.notification_delivery import (
    DeliveryFailure,
    configured,
    deliver,
    deliver_webhook,
    packet,
)
from aigovkit.notification_outbox import CHANNELS, EVENT_PRIORITIES, PRIORITIES
from aigovkit.policy_review import named_member
from aigovkit.tenancy import authenticate

router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])
MAX_ATTEMPTS = 5
BATCH_SIZE = 8


class Preferences(StrictModel):
    channels: list[Literal["webhook", "smtp"]] = Field(
        default_factory=list, max_length=2
    )
    minimum_priority: Literal["info", "attention", "urgent"] = "attention"
    events: list[str] = Field(default_factory=list, max_length=len(EVENT_PRIORITIES))


def destinations(actor):
    try:
        return configured(actor.tenant)
    except ValueError:
        raise HTTPException(
            503, "Notification destinations are misconfigured."
        ) from None


@router.get("/notifications/settings")
def settings(store: Store, actor: Actor) -> dict:
    named_member(actor, "editor")
    config = destinations(actor)
    prefs = database_call(store.get_document, "notification_settings", "default")
    return {
        "preferences": prefs or Preferences().model_dump(),
        "available_channels": [name for name in CHANNELS if getattr(config, name)],
        "event_priorities": EVENT_PRIORITIES,
    }


@router.put("/notifications/settings")
def update(request: Preferences, actor: Actor, store: Store) -> dict:
    named_member(actor, "editor")
    config = destinations(actor)
    if set(request.events) - EVENT_PRIORITIES.keys():
        raise HTTPException(422, "Select supported notification events.")
    if any(not getattr(config, name) for name in request.channels):
        raise HTTPException(
            422, "Configure each destination through the deployment operator."
        )
    prefs = {
        "channels": sorted(set(request.channels)),
        "events": sorted(set(request.events)),
        "minimum_priority": request.minimum_priority,
    }

    def save():
        with store.connect() as conn:
            conn.execute(
                """INSERT INTO foundation_documents (kind,id,body)
                   VALUES ('notification_settings','default',%s)
                   ON CONFLICT(kind,id) DO UPDATE SET body=EXCLUDED.body""",
                (Jsonb(prefs),),
            )
            store.audit(
                conn, "notifications.settings_updated", "notification", "settings"
            )
        return prefs

    return database_call(save)


@router.get("/notifications")
def notifications(
    store: Store, actor: Actor, offset: Offset = 0, limit: Limit = 20
) -> list[dict]:
    can_inspect = bool(
        actor.member and actor.role in {"editor", "publisher", "auditor"}
    )

    def read():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(
                """
                SELECT event_id,channel,action,priority,resource_type,resource_id,resource_version,
                       created_at,state,attempts,next_attempt_at,last_error,delivered_at
                FROM notification_outbox AS delivery
                WHERE %s OR (
                    channel='in_app' AND (
                        action <> 'learning.reminder' OR EXISTS (
                            SELECT 1 FROM foundation_documents AS assignment
                            WHERE assignment.kind='learning_assignment'
                              AND assignment.id=delivery.resource_id
                              AND assignment.body->>'learner'=%s
                        )
                    )
                )
                ORDER BY event_id DESC,channel LIMIT %s OFFSET %s
                """,
                (can_inspect, actor.member, limit, offset),
            ).fetchall()

    return database_call(read)


@router.get("/notifications/{event_id}/attempts")
def attempt_history(
    event_id: Annotated[int, Path(ge=1, le=9_223_372_036_854_775_807)],
    store: Store,
    actor: Actor,
) -> list[dict]:
    if not actor.member or actor.role not in {"editor", "publisher", "auditor"}:
        raise HTTPException(403, "Delivery history requires a named governance role.")

    def read():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(
                """SELECT channel,attempt,state,error_code,finished_at FROM notification_attempts
                   WHERE event_id=%s ORDER BY finished_at,channel,attempt""",
                (event_id,),
            ).fetchall()

    return database_call(read)


def claim(store: Store) -> dict | None:
    lease = uuid4().hex
    with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """UPDATE notification_outbox SET state='dead', last_error='delivery_lease_expired',
                 lease_id=NULL, lease_until=NULL
               WHERE channel<>'in_app' AND state='sending' AND lease_until <= clock_timestamp()
                 AND attempts >= %s""",
            (MAX_ATTEMPTS,),
        )
        return cursor.execute(
            """
            WITH next AS (
              SELECT event_id,channel FROM notification_outbox
              WHERE channel<>'in_app' AND attempts < %s AND (
                (state='queued' AND next_attempt_at <= clock_timestamp())
                OR (state='sending' AND lease_until <= clock_timestamp()))
              ORDER BY next_attempt_at,event_id,channel LIMIT 1 FOR UPDATE SKIP LOCKED
            )
            UPDATE notification_outbox AS queue
            SET state='sending', attempts=attempts+1, lease_id=%s,
                lease_until=clock_timestamp()+interval '120 seconds'
            FROM next WHERE (queue.event_id,queue.channel)=(next.event_id,next.channel)
            RETURNING queue.*
            """,
            (MAX_ATTEMPTS, lease),
        ).fetchone()


def finish(store: Store, item: dict, state: str, error: str | None = None) -> bool:
    backoff = 30 * 2 ** (item["attempts"] - 1)
    with store.connect() as conn:
        updated = conn.execute(
            """
            UPDATE notification_outbox
            SET state=%s, last_error=%s, lease_id=NULL, lease_until=NULL,
                next_attempt_at=clock_timestamp()+%s*interval '1 second',
                delivered_at=CASE WHEN %s='delivered' THEN clock_timestamp() ELSE NULL END
            WHERE event_id=%s AND channel=%s AND state='sending' AND lease_id=%s
            """,
            (
                state,
                error,
                backoff,
                state,
                item["event_id"],
                item["channel"],
                item["lease_id"],
            ),
        ).rowcount
        if updated:
            conn.execute(
                """INSERT INTO notification_attempts (event_id,channel,attempt,state,error_code)
                   VALUES (%s,%s,%s,%s,%s)""",
                (item["event_id"], item["channel"], item["attempts"], state, error),
            )
            store.audit(
                conn, f"notifications.{state}", "notification", str(item["event_id"])
            )
        return bool(updated)


def delivery_allowed(item: dict, prefs: dict) -> bool:
    return bool(
        item["channel"] in prefs["channels"]
        and PRIORITIES.index(item["priority"])
        >= PRIORITIES.index(prefs["minimum_priority"])
        and (not prefs["events"] or item["action"] in prefs["events"])
    )


@router.post("/notifications/run")
def dispatch(store: Store, actor: Actor) -> dict:
    named_member(actor, "scheduler")
    if not actor.tenant:
        raise HTTPException(403, "Tenant scheduling is required.")
    config = destinations(actor)
    summary = {"delivered": 0, "queued": 0, "dead": 0, "cancelled": 0}
    for _ in range(BATCH_SIZE):
        item = database_call(claim, store)
        if not item:
            break
        prefs = (
            database_call(store.get_document, "notification_settings", "default")
            or Preferences().model_dump()
        )
        is_export = item["action"] == AUDIT_BATCH
        if not is_export and not delivery_allowed(item, prefs):
            if database_call(finish, store, item, "cancelled", "delivery_disabled"):
                summary["cancelled"] += 1
            continue
        outcome, error = "delivered", None
        try:
            if is_export:
                if not config.audit_webhook:
                    raise DeliveryFailure("audit_destination_disabled", retry=False)
                batch = database_call(
                    store.get_document, "audit_export_batch", item["resource_id"]
                )
                if not batch:
                    raise DeliveryFailure("audit_batch_missing", retry=False)
                deliver_webhook(
                    config.audit_webhook, {**packet(actor.tenant, item), "batch": batch}
                )
            else:
                deliver(config, actor.tenant, item)
        except DeliveryFailure as failure:
            outcome = (
                "queued"
                if failure.retry and item["attempts"] < MAX_ATTEMPTS
                else "dead"
            )
            error = failure.code
        if database_call(finish, store, item, outcome, error):
            summary[outcome] += 1
    return summary
