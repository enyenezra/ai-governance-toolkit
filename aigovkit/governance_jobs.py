"""Scheduled enrolment and evidence-based reassessment queues."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import Field

from aigovkit.api import Store
from aigovkit.foundation import Actor, Limit, Offset, database_call
from aigovkit.learning import course_answer
from aigovkit.models import Identifier, StrictModel
from aigovkit.policy_review import named_member
from aigovkit.tenancy import authenticate, configured_tenants

router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])
LearnerRole = Literal["reader", "editor", "reviewer", "publisher", "auditor"]


class EnrolmentRule(StrictModel):
    course_id: Identifier
    role: LearnerRole
    group: Identifier | None = None
    enabled: bool = True
    due_days: int = Field(default=14, ge=1, le=365)
    refresher_days: int | None = Field(default=None, ge=1, le=3650)


@router.get("/learning/enrolment-rules")
def rules(store: Store, actor: Actor, offset: Offset = 0, limit: Limit = 20):
    named_member(actor, "editor")
    return database_call(store.documents, "enrolment_rule", offset, limit)


@router.put("/learning/enrolment-rules/{rule_id}")
def rule(rule_id: Identifier, request: EnrolmentRule, store: Store, actor: Actor):
    named_member(actor, "editor")

    def write():
        data = {**request.model_dump(), "id": rule_id}
        with store.connect() as conn:
            course_answer(conn, request.course_id)
            conn.execute(
                """INSERT INTO foundation_documents (kind,id,body)
                   VALUES ('enrolment_rule',%s,%s) ON CONFLICT(kind,id)
                   DO UPDATE SET body=EXCLUDED.body""",
                (rule_id, Jsonb(data)),
            )
            store.audit(
                conn, "learning.enrolment_rule_updated", "enrolment_rule", rule_id
            )
        return data

    return database_call(write)


@router.post("/learning/enrolments/run")
def enrol(store: Store, actor: Actor):
    named_member(actor, "scheduler")
    today = datetime.now(UTC).date()
    static_members = [
        {"member": member.id, "role": member.role, "groups": []}
        for tenant in configured_tenants() or []
        if tenant.id == actor.tenant
        for member in tenant.members
    ]

    def write():
        with store.connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':enrolment', 0))"
            )
            rows = conn.execute(
                """
                WITH members AS (
                    SELECT member_id AS member, role, groups FROM public.governance_members
                    WHERE tenant_id=%s AND state='active'
                    UNION ALL
                    SELECT member,role,groups FROM jsonb_to_recordset(%s)
                    AS m(member text,role text,groups text[])
                ), eligible AS (
                    SELECT DISTINCT ON (m.member, rule.body->>'course_id')
                        m.member, rule.body->>'course_id' AS course_id, rule.id AS rule_id,
                        (rule.body->>'due_days')::int AS due_days
                    FROM foundation_documents rule JOIN members m
                      ON m.role=rule.body->>'role'
                      AND (rule.body->>'group' IS NULL OR rule.body->>'group'=ANY(m.groups))
                    LEFT JOIN LATERAL (
                        SELECT bool_or(body->>'status'='assigned') AS assigned,
                               max((body->>'completed_at')::timestamptz) AS completed_at
                        FROM foundation_documents assignment WHERE
                            assignment.kind='learning_assignment'
                            AND assignment.body->>'learner'=m.member
                            AND assignment.body->>'course_id'=rule.body->>'course_id'
                    ) previous ON true
                    WHERE rule.kind='enrolment_rule' AND rule.body->>'enabled'='true'
                    AND NOT coalesce(previous.assigned,false)
                    AND (previous.completed_at IS NULL OR
                       (previous.completed_at AT TIME ZONE 'UTC')::date
                       + (rule.body->>'refresher_days')::int <= %s)
                    ORDER BY m.member, rule.body->>'course_id', rule.id
                    LIMIT 100
                )
                SELECT member, course_id, rule_id, %s::date+due_days FROM eligible
                """,
                (actor.tenant, Jsonb(static_members), today, today),
            ).fetchall()
            for member, course_id, rule_id, due in rows:
                assignment_id = conn.execute(
                    "SELECT gen_random_uuid()::text"
                ).fetchone()[0]
                data = {
                    "id": assignment_id,
                    "learner": member,
                    "course_id": course_id,
                    "due": due.isoformat(),
                    "rule_id": rule_id,
                    "score": None,
                    "status": "assigned",
                }
                conn.execute(
                    "INSERT INTO foundation_documents (kind,id,body) VALUES ('learning_assignment',%s,%s)",
                    (assignment_id, Jsonb(data)),
                )
                store.audit(
                    conn, "learning.assigned", "learning_assignment", assignment_id
                )
            return {"assigned": len(rows)}

    return database_call(write)


@router.post("/reassessments/run")
def reassess(store: Store, actor: Actor):
    named_member(actor, "scheduler")
    today = datetime.now(UTC).date()

    def write():
        with store.connect() as conn:
            rows = conn.execute(
                """
                WITH due AS (
                    SELECT kind,id,body,
                        CASE kind WHEN 'register_risk' THEN (body->>'due_date')::date
                                  WHEN 'register_vendor' THEN (body->>'reassessment_due')::date
                                  ELSE (body->>'checked_on')::date + 90 END AS due_date
                    FROM foundation_documents
                    WHERE (kind='register_risk' AND body->>'status'<>'closed')
                       OR (kind='register_vendor' AND body->>'status'<>'rejected')
                       OR (kind='register_control_check' AND NOT EXISTS (
                           SELECT 1 FROM foundation_documents newer
                           WHERE newer.kind=foundation_documents.kind
                             AND newer.body->>'control_id'=foundation_documents.body->>'control_id'
                             AND (newer.body->>'checked_on',newer.id) >
                                 (foundation_documents.body->>'checked_on',foundation_documents.id)
                       ))
                )
                SELECT kind,id,body,due_date FROM due WHERE due_date<=%s AND NOT EXISTS (
                    SELECT 1 FROM foundation_documents task WHERE task.kind='reassessment_task'
                      AND task.id=md5(due.kind || ':' || due.id || ':' || due.due_date::text)
                ) ORDER BY due_date,kind,id LIMIT 100
                """,
                (today,),
            ).fetchall()
            created = 0
            for kind, identifier, entry, due in rows:
                data = {
                    "source_kind": kind,
                    "source_id": identifier,
                    "title": entry["title"],
                    "owner": entry.get("treatment_owner")
                    or entry.get("owner")
                    or entry.get("reviewer"),
                    "due": due.isoformat(),
                }
                row = conn.execute(
                    """INSERT INTO foundation_documents (kind,id,body)
                       VALUES ('reassessment_task',md5(%s),%s) ON CONFLICT DO NOTHING RETURNING id""",
                    (f"{kind}:{identifier}:{due.isoformat()}", Jsonb(data)),
                ).fetchone()
                if row:
                    created += 1
                    store.audit(conn, "reassessment.due", "reassessment_task", row[0])
            return {"created": created}

    return database_call(write)


@router.get("/reassessments")
def tasks(store: Store, actor: Actor, offset: Offset = 0, limit: Limit = 20):
    if not actor.member or actor.role not in {"editor", "auditor", "reviewer"}:
        raise HTTPException(403, "Reassessments require a named governance role.")
    return database_call(store.documents, "reassessment_task", offset, limit)
