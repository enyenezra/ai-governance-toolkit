"""Tenant course drafts and immutable, independently published versions."""

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import Field, StringConstraints

from aigovkit.api import Store
from aigovkit.foundation import Actor, Limit, Offset, database_call
from aigovkit.models import Identifier, StrictModel
from aigovkit.policy_review import named_member
from aigovkit.tenancy import authenticate

router = APIRouter(prefix="/v1/learning", dependencies=[Depends(authenticate)])
Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]


class CourseDraft(StrictModel):
    title: Text
    lesson: Text
    question: Text
    choices: list[Text] = Field(min_length=2, max_length=2)
    correct_choice: int = Field(ge=0, le=1)
    expected_revision: int = Field(ge=0, le=1_000_000)


class Publication(StrictModel):
    expected_revision: int = Field(ge=1, le=1_000_000)


def authoring_access(actor):
    if not actor.member or actor.role not in {"editor", "publisher"}:
        raise HTTPException(403, "Course editing requires a named governance role.")


@router.get("/course-drafts")
def drafts(store: Store, actor: Actor, offset: Offset = 0, limit: Limit = 20):
    authoring_access(actor)
    return database_call(store.documents, "course_draft", offset, limit)


def draft_row(conn, course_id):
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || %s, 0))",
        (":course:" + course_id,),
    )
    row = conn.execute(
        "SELECT body FROM foundation_documents WHERE kind='course_draft' AND id=%s",
        (course_id,),
    ).fetchone()
    return row[0] if row else None


@router.put("/course-drafts/{course_id}")
def save(course_id: Identifier, request: CourseDraft, store: Store, actor: Actor):
    author = named_member(actor, "editor")
    if request.choices[0] == request.choices[1]:
        raise HTTPException(422, "Provide two distinct choices.")

    def write():
        with store.connect() as conn:
            old = draft_row(conn, course_id)
            revision = old["revision"] if old else 0
            if revision != request.expected_revision or revision >= 1_000_000:
                raise HTTPException(409, "The course draft has changed.")
            data = {
                **request.model_dump(mode="json", exclude={"expected_revision"}),
                "course_id": course_id,
                "author": author,
                "revision": revision + 1,
                "published_id": None,
            }
            conn.execute(
                """INSERT INTO foundation_documents (kind,id,body) VALUES ('course_draft',%s,%s)
                   ON CONFLICT(kind,id) DO UPDATE SET body=EXCLUDED.body""",
                (course_id, Jsonb(data)),
            )
            store.audit(
                conn, "learning.course_edited", "course_draft", course_id, revision + 1
            )
            return data

    return database_call(write)


@router.post("/course-drafts/{course_id}/publish")
def publish(course_id: Identifier, request: Publication, store: Store, actor: Actor):
    publisher = named_member(actor, "publisher")

    def write():
        with store.connect() as conn:
            draft = draft_row(conn, course_id)
            if not draft:
                raise HTTPException(404, "Course draft not found.")
            if (
                draft["revision"] != request.expected_revision
                or draft["author"] == publisher
            ):
                raise HTTPException(
                    409,
                    "Publication requires the current revision and an independent publisher.",
                )
            if draft["published_id"]:
                return {"id": draft["published_id"]}
            version_id = "course-" + uuid4().hex
            version = {**draft, "id": version_id, "published_by": publisher}
            conn.execute(
                "INSERT INTO foundation_documents (kind,id,body) VALUES ('course_version',%s,%s)",
                (version_id, Jsonb(version)),
            )
            draft["published_id"] = version_id
            conn.execute(
                "UPDATE foundation_documents SET body=%s WHERE kind='course_draft' AND id=%s",
                (Jsonb(draft), course_id),
            )
            store.audit(
                conn,
                "learning.course_published",
                "course_version",
                version_id,
                draft["revision"],
            )
            return {"id": version_id}

    return database_call(write)
