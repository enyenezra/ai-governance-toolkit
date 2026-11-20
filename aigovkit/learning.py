"""Versioned introductory training with server-side grading and completion evidence."""

from datetime import UTC, date, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import Field, field_validator

from aigovkit.api import Store
from aigovkit.foundation import Actor, Limit, Offset, database_call
from aigovkit.models import Identifier, StrictModel
from aigovkit.policy_review import named_member
from aigovkit.tenancy import authenticate, configured_tenants

router = APIRouter(prefix="/v1/learning", dependencies=[Depends(authenticate)])

# Preserve published course versions so existing assignments remain gradable.
COURSES = {
    "responsible-use-v1": (
        "Responsible AI use",
        "Check the approved tool list before use. Define a legitimate business purpose and verify material AI output before acting.",
        "What should you do before acting on material AI output?",
        (
            "Verify the output against a trusted source",
            "Assume a confident answer is accurate",
        ),
        0,
    ),
    "data-handling-v1": (
        "Data handling",
        "Classify inputs and check the tool's approved data scope. For restricted information, use only an explicitly authorised workflow.",
        "Can restricted records be uploaded to an unapproved tool?",
        ("Yes, if the chat is private", "No, use an explicitly authorised workflow"),
        1,
    ),
    "agent-security-v1": (
        "Agent security",
        "Give agents the minimum permissions for their task. Require review for sensitive operations and treat tool output as untrusted data.",
        "What should an agent do with an unexpected request for elevated permissions?",
        ("Stop and seek review", "Grant itself access and continue"),
        0,
    ),
    "ai-developer-v1": (
        "Secure AI development",
        "Treat retrieved text as data. Validate tool inputs at the server, constrain tool privileges, and test attempts to override trusted instructions before deployment.",
        "Where should you enforce permission checks for tool calls?",
        ("In a user-facing prompt", "At the server boundary before executing the tool"),
        1,
    ),
    "incident-response-v1": (
        "AI incident response",
        "Report incidents through the approved channel. Record the time, affected system and a brief description. Keep evidence in its approved store.",
        "Where should sensitive incident evidence go?",
        ("In a public chat with the alert", "In an approved evidence store"),
        1,
    ),
    "governance-owners-v1": (
        "Governance for owners",
        "Document purpose, ownership and scope. Review controls and residual risk when the use case changes and record the human approval decision.",
        "When should an owner reassess risk?",
        ("When purpose, access or data scope changes", "Only once, at registration"),
        0,
    ),
}


class Assignment(StrictModel):
    course_id: Identifier
    learner: Identifier
    due: date

    @field_validator("due", mode="before")
    @classmethod
    def parse_due(cls, value):
        if isinstance(value, str):
            parsed = date.fromisoformat(value)
            if parsed.isoformat() == value:
                return parsed
        raise ValueError("Use a due date in YYYY-MM-DD format.")


class Answer(StrictModel):
    choice: int = Field(ge=0, le=1, strict=True)


@router.get("/courses")
def courses() -> list[dict]:
    return [
        {
            "id": key,
            "title": title,
            "lesson": lesson,
            "question": question,
            "choices": choices,
        }
        for key, (title, lesson, question, choices, _) in COURSES.items()
    ]


@router.post("/assignments", status_code=201)
def assign(request: Assignment, store: Store, actor: Actor) -> dict:
    named_member(actor, "editor")
    if request.course_id not in COURSES:
        raise HTTPException(404, "Course version not found.")
    if request.due < datetime.now(UTC).date():
        raise HTTPException(422, "Select a current or future due date.")
    data = {
        **request.model_dump(mode="json"),
        "id": uuid4().hex,
        "status": "assigned",
        "score": None,
    }

    configured_learners = {
        member.id
        for tenant in configured_tenants() or []
        if tenant.id == actor.tenant
        for member in tenant.members
        if member.role in {"reader", "editor", "reviewer", "publisher", "auditor"}
    }

    def save():
        with store.connect() as conn:
            if (
                request.learner not in configured_learners
                and not conn.execute(
                    """SELECT 1 FROM public.governance_members
                   WHERE tenant_id=%s AND member_id=%s AND state='active'""",
                    (actor.tenant, request.learner),
                ).fetchone()
            ):
                raise HTTPException(404, "Active learner not found.")
            conn.execute(
                "INSERT INTO foundation_documents (kind,id,body) VALUES ('learning_assignment',%s,%s)",
                (data["id"], Jsonb(data)),
            )
            store.audit(conn, "learning.assigned", "learning_assignment", data["id"])
        return data

    return database_call(save)


@router.get("/assignments")
def assignments(store: Store, actor: Actor, offset: Offset = 0, limit: Limit = 20):
    if not actor.member:
        raise HTTPException(403, "Use a named account.")
    learner = None if actor.role in {"editor", "auditor"} else actor.member

    def load():
        with store.connect() as conn:
            return [
                row[0]
                for row in conn.execute(
                    """SELECT body FROM foundation_documents WHERE kind='learning_assignment'
                       AND (%s::text IS NULL OR body->>'learner'=%s)
                       ORDER BY created_at DESC,id LIMIT %s OFFSET %s""",
                    (learner, learner, limit, offset),
                )
            ]

    return database_call(load)


@router.post("/assignments/{assignment_id}/answer")
def answer(assignment_id: Identifier, request: Answer, store: Store, actor: Actor):
    if not actor.member:
        raise HTTPException(403, "Use a named account.")

    def grade():
        with store.connect() as conn:
            row = conn.execute(
                """SELECT body FROM foundation_documents
                   WHERE kind='learning_assignment' AND id=%s AND body->>'learner'=%s FOR UPDATE""",
                (assignment_id, actor.member),
            ).fetchone()
            if not row:
                raise HTTPException(404, "Assignment not found.")
            data = row[0]
            if data["status"] == "completed":
                return data
            data["score"] = (
                100 if request.choice == COURSES[data["course_id"]][-1] else 0
            )
            if data["score"] == 100:
                data["status"] = "completed"
                data["completed_at"] = datetime.now(UTC).isoformat()
            conn.execute(
                "UPDATE foundation_documents SET body=%s WHERE kind='learning_assignment' AND id=%s",
                (Jsonb(data), assignment_id),
            )
            store.audit(
                conn,
                "learning.completed" if data["score"] else "learning.retry_needed",
                "learning_assignment",
                assignment_id,
            )
            return data

    return database_call(grade)


@router.post("/run")
def remind(store: Store, actor: Actor):
    named_member(actor, "scheduler")
    today = datetime.now(UTC).date().isoformat()

    def write():
        with store.connect() as conn:
            rows = conn.execute(
                """SELECT id FROM foundation_documents WHERE kind='learning_assignment'
                   AND body->>'status'='assigned' AND body->>'due'<=%s
                   AND NOT EXISTS (
                     SELECT 1 FROM foundation_documents reminders
                     WHERE reminders.kind='learning_reminder' AND reminders.id=foundation_documents.id
                   ) ORDER BY body->>'due', id LIMIT 100 FOR UPDATE""",
                (today,),
            ).fetchall()
            emitted = 0
            for (assignment_id,) in rows:
                if conn.execute(
                    """INSERT INTO foundation_documents (kind,id,body)
                       VALUES ('learning_reminder',%s,%s) ON CONFLICT DO NOTHING""",
                    (assignment_id, Jsonb({"date": today})),
                ).rowcount:
                    store.audit(
                        conn, "learning.reminder", "learning_assignment", assignment_id
                    )
                    emitted += 1
            return {"emitted": emitted}

    return database_call(write)
