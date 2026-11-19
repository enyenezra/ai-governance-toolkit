from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row

from aigovkit.api import Store
from aigovkit.foundation import Actor, Limit, Offset, database_call
from aigovkit.models import Identifier, StrictModel
from aigovkit.policy_review import Version, draft, named_member, revision
from aigovkit.tenancy import authenticate

router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])

CURRENT_PUBLICATIONS = """
    SELECT DISTINCT ON (draft_id) draft_id, version, publisher, published_at
    FROM policy_publications ORDER BY draft_id, version DESC
"""


class PolicyVersion(StrictModel):
    draft_id: Identifier
    version: Version


@router.post("/policy-publications", status_code=201)
def publish(request: PolicyVersion, store: Store, actor: Actor) -> dict:
    publisher = named_member(actor, "publisher")

    def write():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            original = draft(cursor, request.draft_id, lock=True)
            latest = revision(cursor, request.draft_id)
            if (
                not latest
                or latest["version"] != request.version
                or latest["status"] != "approved"
            ):
                raise HTTPException(409, "Publish the latest approved revision.")
            approval = cursor.execute(
                """
                SELECT actor FROM policy_review_events
                WHERE draft_id = %s AND version = %s AND action = 'approved'
                """,
                (request.draft_id, request.version),
            ).fetchone()
            if publisher in {
                latest["author"],
                original.get("created_by"),
                approval["actor"],
            }:
                raise HTTPException(
                    403, "Publication requires an independent publisher."
                )
            result = cursor.execute(
                """
                INSERT INTO policy_publications (draft_id, version, publisher) VALUES (%s, %s, %s)
                ON CONFLICT (draft_id, version) DO NOTHING
                RETURNING draft_id, version, publisher, published_at
                """,
                (request.draft_id, request.version, publisher),
            ).fetchone()
            if result is None:
                raise HTTPException(409, "This revision is already published.")
            return result

    return database_call(write)


@router.get("/published-policies")
def published_policies(
    store: Store, offset: Offset = 0, limit: Limit = 20
) -> list[dict]:
    def load():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(
                f"""
                SELECT p.*, r.body->>'title' AS title FROM ({CURRENT_PUBLICATIONS}) p
                JOIN policy_revisions r USING (draft_id, version)
                ORDER BY p.published_at DESC, p.draft_id LIMIT %s OFFSET %s
                """,
                (limit, offset),
            ).fetchall()

    return database_call(load)


@router.get("/published-policies/{draft_id}/{version}")
def published_policy(
    draft_id: Identifier, version: Version, store: Store, actor: Actor
) -> dict:
    def load():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                """
                SELECT p.*, r.body, p.version = (
                    SELECT max(version) FROM policy_publications WHERE draft_id = p.draft_id
                ) AS current
                FROM policy_publications p JOIN policy_revisions r USING (draft_id, version)
                WHERE p.draft_id = %s AND p.version = %s
                """,
                (draft_id, version),
            ).fetchone()
            if row is None:
                raise HTTPException(404, "Published policy not found.")
            receipt = cursor.execute(
                """
                SELECT acknowledged_at FROM policy_acknowledgements
                WHERE draft_id = %s AND version = %s AND member_id = %s
                """,
                (draft_id, version, actor.member),
            ).fetchone()
            return {
                **row,
                "acknowledged_at": receipt["acknowledged_at"] if receipt else None,
            }

    return database_call(load)


@router.post("/policy-acknowledgements")
def acknowledge(request: PolicyVersion, store: Store, actor: Actor) -> dict:
    if not actor.member:
        raise HTTPException(403, "A named member key is required.")

    def write():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            draft(cursor, request.draft_id, lock=True)
            current = cursor.execute(
                "SELECT max(version) AS version FROM policy_publications WHERE draft_id = %s",
                (request.draft_id,),
            ).fetchone()["version"]
            if current != request.version:
                raise HTTPException(409, "Acknowledge the current published version.")
            cursor.execute(
                """
                INSERT INTO policy_acknowledgements (draft_id, version, member_id) VALUES (%s, %s, %s)
                ON CONFLICT (draft_id, version, member_id) DO NOTHING
                """,
                (request.draft_id, request.version, actor.member),
            )
            return cursor.execute(
                """
                SELECT * FROM policy_acknowledgements
                WHERE draft_id = %s AND version = %s AND member_id = %s
                """,
                (request.draft_id, request.version, actor.member),
            ).fetchone()

    return database_call(write)


@router.get("/policy-acknowledgements")
def acknowledgements(
    store: Store, actor: Actor, offset: Offset = 0, limit: Limit = 20
) -> list[dict]:
    if not actor.member:
        raise HTTPException(403, "A named member key is required.")

    def load():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(
                """
                SELECT * FROM policy_acknowledgements WHERE member_id = %s
                ORDER BY acknowledged_at DESC, draft_id, version LIMIT %s OFFSET %s
                """,
                (actor.member, limit, offset),
            ).fetchall()

    return database_call(load)
