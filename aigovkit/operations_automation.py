"""Scheduled incident intake and versioned training material."""

import hashlib
import os
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from aigovkit.api import Store
from aigovkit.enterprise import Training, write_register
from aigovkit.foundation import Actor, database_call
from aigovkit.models import Identifier, StrictModel, Tool
from aigovkit.policy_review import named_member
from aigovkit.tenancy import authenticate, configured_tenants

router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])
COURSES = {
    "secure-ai-basics": {
        "version": "1.0.0",
        "title": "Secure AI basics",
        "lessons": [
            "Use approved AI applications and document the purpose before granting access.",
            "Keep credentials and restricted data out of unapproved AI services.",
            "Stop and escalate unexpected high-impact actions to the accountable reviewer.",
        ],
    },
    "incident-response": {
        "version": "1.0.0",
        "title": "AI incident response",
        "lessons": [
            "Record the affected system, time, impact and responsible owner.",
            "Preserve approved evidence and request human approval for disruptive containment.",
            "Verify recovery and assign corrective work before closing an incident.",
        ],
    },
}


@router.get("/training/courses")
def courses() -> list[dict]:
    return [{"id": key, **course} for key, course in COURSES.items()]


@router.post("/training/assignments/{assignment_id}/complete")
def complete(assignment_id: Identifier, store: Store, actor: Actor) -> dict:
    item = database_call(store.get_document, "register_training", assignment_id)
    if not item or not actor.member or actor.member != item["assignee"]:
        raise HTTPException(404, "Training assignment not found.")
    if item["status"] == "completed":
        return item
    course_id = item.get("course_id")
    course = COURSES.get(course_id or "")
    if not course:
        raise HTTPException(409, "The assignment has no available course.")
    fields = {key: value for key, value in item.items() if key in Training.model_fields}
    result = Training.model_validate(
        fields
        | {
            "status": "completed",
            "evidence_reference": f"self-attestation:{course_id}:{course['version']}",
        }
    )
    return database_call(write_register, store, result, assignment_id, item["version"])


@router.post("/incident-alerts/run")
def incidents(store: Store, actor: Actor) -> dict:
    owner = named_member(actor, "scheduler" if actor.role == "scheduler" else "editor")
    if actor.role == "scheduler":
        owner = os.getenv("AIGOVKIT_INCIDENT_OWNER", "")
        if not any(
            member.id == owner and member.role == "editor"
            for tenant in configured_tenants() or []
            if tenant.id == actor.tenant
            for member in tenant.members
        ):
            raise HTTPException(
                503, "Assign a named editor as the scheduled incident owner."
            )
    today = datetime.now(UTC).date().isoformat()

    def create():
        created = 0
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            groups = cursor.execute(
                """
                SELECT body->>'agent_id' AS agent, sum((body->>'count')::bigint) AS total
                FROM foundation_documents WHERE kind='register_signal'
                    AND body->>'observed_on'=%s AND body->>'event' IN ('denied','error')
                GROUP BY agent HAVING sum((body->>'count')::bigint) >= 10
                """,
                (today,),
            ).fetchall()
            for group in groups:
                key = hashlib.sha256(
                    f"incident:{today}:{group['agent']}".encode()
                ).hexdigest()
                body = {
                    "id": key,
                    "kind": "incident",
                    "version": 1,
                    "title": "Repeated runtime denials or errors",
                    "system_id": group["agent"],
                    "owner": owner,
                    "status": "open",
                    "severity": "medium",
                    "update": f"{group['total']} submitted denials or errors on {today}; investigate.",
                    "evidence_references": [],
                }
                if cursor.execute(
                    """INSERT INTO foundation_documents (kind,id,body)
                       VALUES ('register_incident',%s,%s) ON CONFLICT DO NOTHING""",
                    (key, Jsonb(body)),
                ).rowcount:
                    cursor.execute(
                        """INSERT INTO foundation_documents (kind,id,body)
                           VALUES ('register_incident_history',%s,%s)""",
                        (key + ":1", Jsonb(body)),
                    )
                    store.audit(cursor, "incident.alerted", "incident", key, 1)
                    created += 1
        return {"created": created}

    return database_call(create)


class InventoryPromotion(StrictModel):
    owner: Identifier


@router.post("/discovery/{observation_id}/promote", status_code=201)
def promote_discovery(
    observation_id: Identifier, request: InventoryPromotion, store: Store, actor: Actor
) -> dict:
    named_member(actor, "editor")
    key = "discovered-" + hashlib.sha256(observation_id.encode()).hexdigest()[:40]

    def promote():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                """SELECT body FROM foundation_documents
                   WHERE kind='register_discovery' AND id=%s FOR SHARE""",
                (observation_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(404, "Discovery observation not found.")
            if row["body"]["status"] != "approved":
                raise HTTPException(409, "Approve the observation before promoting it.")
            record = Tool(
                kind="tool",
                id=key,
                name=row["body"]["service"][:120],
                owner=request.owner,
            )
            result = cursor.execute(
                """INSERT INTO governance_inventory (kind,id,body) VALUES ('tool',%s,%s)
                   ON CONFLICT DO NOTHING""",
                (key, Jsonb(record.model_dump(mode="json"))),
            )
            if not result.rowcount:
                raise HTTPException(409, "The observation has already been promoted.")
            store.audit(cursor, "discovery.promoted", "tool", key)
            return record.model_dump(mode="json")

    return database_call(promote)
