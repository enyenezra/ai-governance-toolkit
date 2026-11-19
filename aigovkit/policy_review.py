from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import Field, StringConstraints

from aigovkit.api import Store
from aigovkit.foundation import Actor, database_call
from aigovkit.models import Identifier, StrictModel
from aigovkit.tenancy import Session, authenticate

router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])
Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
Version = Annotated[int, Field(ge=1, le=2_147_483_647)]
ClauseID = Annotated[str, StringConstraints(min_length=1, max_length=100)]


class RevisionInput(StrictModel):
    expected_version: int = Field(ge=0, le=2_147_483_646)
    clause_texts: dict[ClauseID, Text] = Field(min_length=1, max_length=100)


class Decision(StrictModel):
    draft_id: Identifier
    version: Version
    action: Literal["approved", "changes_requested"]
    note: Text


def named_member(actor: Session, role: str) -> str:
    if actor.role != role or actor.member is None:
        raise HTTPException(403, f"A named {role} key is required.")
    return actor.member


def draft(cursor, draft_id: str, *, lock: bool = False) -> dict:
    statement = "SELECT body FROM foundation_documents WHERE kind = 'draft' AND id = %s"
    row = cursor.execute(
        statement + (" FOR UPDATE" if lock else ""), (draft_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Policy draft not found.")
    return row["body"]


def revision(cursor, draft_id: str, version: int | None = None) -> dict | None:
    query = """
        SELECT r.*, COALESCE(
            (SELECT e.action FROM policy_review_events e
             WHERE e.draft_id = r.draft_id AND e.version = r.version
             ORDER BY (e.action = 'submitted'), e.recorded_at DESC LIMIT 1), 'draft'
        ) AS status, (SELECT p.published_at FROM policy_publications p
           WHERE p.draft_id = r.draft_id AND p.version = r.version) AS published_at
        FROM policy_revisions r WHERE r.draft_id = %s
    """
    if version is not None:
        return cursor.execute(
            query + " AND r.version = %s", (draft_id, version)
        ).fetchone()
    return cursor.execute(
        query + " ORDER BY r.version DESC LIMIT 1", (draft_id,)
    ).fetchone()


def write_revision(
    store: Store, draft_id: str, request: RevisionInput, author: str
) -> dict:
    with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
        original = draft(cursor, draft_id, lock=True)
        latest = revision(cursor, draft_id)
        current = latest["version"] if latest else 0
        if request.expected_version != current:
            raise HTTPException(
                409, "Load the latest version before saving a revision."
            )
        if (
            latest
            and latest["status"] in {"draft", "submitted"}
            and latest["author"] != author
        ):
            raise HTTPException(
                403, "Only the current author can replace an open draft revision."
            )
        if latest and latest["status"] == "submitted":
            raise HTTPException(409, "Wait until the submitted revision is reviewed.")
        source = latest["body"] if latest else original
        clauses = source["clauses"]
        unknown = request.clause_texts.keys() - {clause["id"] for clause in clauses}
        if unknown:
            raise HTTPException(422, "Clause IDs must come from the current policy.")
        snapshot = {
            **source,
            "clauses": [
                {
                    **clause,
                    "text": request.clause_texts.get(clause["id"], clause["text"]),
                }
                for clause in clauses
            ],
        }
        version = current + 1
        cursor.execute(
            "INSERT INTO policy_revisions (draft_id, version, author, body) VALUES (%s, %s, %s, %s)",
            (draft_id, version, author, Jsonb(snapshot)),
        )
        return revision(cursor, draft_id, version)


def record_event(
    store: Store, draft_id: str, version: int, actor: str, action: str, note: str | None
) -> dict:
    with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
        original = draft(cursor, draft_id, lock=True)
        latest = revision(cursor, draft_id)
        if latest is None or latest["version"] != version:
            raise HTTPException(409, "Only the latest revision can transition.")
        if action == "submitted":
            if actor != latest["author"]:
                raise HTTPException(403, "Only the revision author can submit it.")
            required = "draft"
        else:
            if actor in {latest["author"], original.get("created_by")}:
                raise HTTPException(403, "The author cannot review their own policy.")
            required = "submitted"
        if latest["status"] != required:
            raise HTTPException(409, "The revision has already moved past this stage.")
        result = cursor.execute(
            """
            INSERT INTO policy_review_events (draft_id, version, action, actor, note)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING action, actor, note, recorded_at
            """,
            (draft_id, version, action, actor, note),
        ).fetchone()
        return result


@router.get("/policy-drafts/{draft_id}/revisions")
def list_policy_revisions(draft_id: Identifier, store: Store) -> list[dict]:
    def load():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            draft(cursor, draft_id)
            return cursor.execute(
                """
                SELECT version, author, created_at FROM policy_revisions
                WHERE draft_id = %s ORDER BY version DESC
                """,
                (draft_id,),
            ).fetchall()

    return database_call(load)


@router.get("/policy-drafts/{draft_id}/revisions/{version}")
def policy_revision(draft_id: Identifier, version: Version, store: Store) -> dict:
    def load():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            result = revision(cursor, draft_id, version)
            if result is None:
                raise HTTPException(404, "Policy revision not found.")
            events = cursor.execute(
                """
                SELECT action, actor, note, recorded_at FROM policy_review_events
                WHERE draft_id = %s AND version = %s ORDER BY (action <> 'submitted'), recorded_at
                """,
                (draft_id, version),
            ).fetchall()
            return {
                **result,
                "status": events[-1]["action"] if events else "draft",
                "events": events,
            }

    return database_call(load)


@router.post("/policy-drafts/{draft_id}/revisions", status_code=201)
def create_policy_revision(
    draft_id: Identifier, request: RevisionInput, store: Store, actor: Actor
) -> dict:
    return database_call(
        write_revision, store, draft_id, request, named_member(actor, "editor")
    )


@router.post("/policy-drafts/{draft_id}/revisions/{version}/submit")
def submit_policy_revision(
    draft_id: Identifier, version: Version, store: Store, actor: Actor
) -> dict:
    member = named_member(actor, "editor")
    return database_call(
        record_event, store, draft_id, version, member, "submitted", None
    )


@router.post("/policy-reviews")
def decide_policy_revision(request: Decision, store: Store, actor: Actor) -> dict:
    member = named_member(actor, "reviewer")
    return database_call(
        record_event,
        store,
        request.draft_id,
        request.version,
        member,
        request.action,
        request.note,
    )
