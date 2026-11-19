"""Policy diffs, review schedules, exports and acknowledgement coverage."""

from datetime import UTC, datetime
from difflib import SequenceMatcher
from io import BytesIO
from typing import Literal
from xml.sax.saxutils import escape

from docx import Document
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from psycopg.rows import dict_row
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from aigovkit.api import Store
from aigovkit.foundation import Actor, Limit, Offset, database_call
from aigovkit.models import Identifier
from aigovkit.policy_publication import CURRENT_PUBLICATIONS, published_policy
from aigovkit.policy_review import Version, policy_revision
from aigovkit.tenancy import authenticate, configured_tenants

router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])


@router.get("/policy-drafts/{draft_id}/compare")
def compare(
    draft_id: Identifier, from_version: Version, to_version: Version, store: Store
) -> dict:
    old = policy_revision(draft_id, from_version, store)["body"]["clauses"]
    new = policy_revision(draft_id, to_version, store)["body"]["clauses"]
    before = {clause["id"]: clause["text"] for clause in old}
    after = {clause["id"]: clause["text"] for clause in new}
    changes = []
    for key in dict.fromkeys([*before, *after]):
        previous, next_text = before.get(key, ""), after.get(key, "")
        if previous != next_text:
            words = previous.split()
            updates = next_text.split()
            operations = [
                {
                    "op": tag,
                    "before": " ".join(words[i:j]),
                    "after": " ".join(updates[k:l]),
                }
                for tag, i, j, k, l in SequenceMatcher(
                    None, words, updates, autojunk=False
                ).get_opcodes()
            ]
            changes.append(
                {
                    "clause_id": key,
                    "before": previous,
                    "after": next_text,
                    "operations": operations,
                }
            )
    return {
        "draft_id": draft_id,
        "from_version": from_version,
        "to_version": to_version,
        "changes": changes,
    }


@router.get("/policy-review-schedule")
def schedule(store: Store, offset: Offset = 0, limit: Limit = 20) -> list[dict]:
    def read():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(
                f"""SELECT p.*, r.body->>'title' AS title,
                    (p.published_at AT TIME ZONE 'UTC')::date +
                       (r.body->>'review_days')::int AS due_date
                    FROM ({CURRENT_PUBLICATIONS}) p JOIN policy_revisions r USING (draft_id,version)
                    ORDER BY due_date,p.draft_id LIMIT %s OFFSET %s""",
                (limit, offset),
            ).fetchall()

    today = datetime.now(UTC).date()
    return [{**item, "due": item["due_date"] <= today} for item in database_call(read)]


@router.get("/published-policies/{draft_id}/{version}/acknowledgement-summary")
def coverage(
    draft_id: Identifier, version: Version, store: Store, actor: Actor
) -> dict:
    if not actor.member or actor.role not in {"auditor", "publisher"}:
        raise HTTPException(403, "A named auditor or publisher is required.")
    published_policy(draft_id, version, store, actor)
    tenants = configured_tenants() or []
    static_ids = {
        member.id
        for tenant in tenants
        if tenant.id == actor.tenant
        for member in tenant.members
        if member.role not in {"gateway", "observer", "scheduler"}
    }

    def read():
        with store.connect() as conn:
            active = {
                row[0]
                for row in conn.execute(
                    """SELECT member_id FROM public.governance_members
                       WHERE tenant_id=%s AND state='active'""",
                    (actor.tenant,),
                )
            } | static_ids
            acknowledged = {
                row[0]
                for row in conn.execute(
                    """SELECT member_id FROM policy_acknowledgements
                       WHERE draft_id=%s AND version=%s""",
                    (draft_id, version),
                )
            }
            return {
                "draft_id": draft_id,
                "version": version,
                "active_members": len(active),
                "acknowledged": len(active & acknowledged),
                "pending": len(active - acknowledged),
            }

    return database_call(read)


def text_lines(policy: dict) -> list[str]:
    body = policy["body"]
    return [
        body["title"],
        f"Published revision {policy['version']}",
        f"Organisation: {body['organisation']['name']}",
        f"Owner: {body['owner']}",
        f"Scope: {body['scope']}",
        *(f"{clause['id']} · {clause['text']}" for clause in body["clauses"]),
    ]


@router.get("/published-policies/{draft_id}/{version}/export/{format_name}")
def export(
    draft_id: Identifier,
    version: Version,
    format_name: Literal["md", "docx", "pdf"],
    store: Store,
    actor: Actor,
) -> Response:
    lines = text_lines(published_policy(draft_id, version, store, actor))
    output = BytesIO()
    if format_name == "md":
        # Plain code fencing prevents interpreting embedded policy text as HTML or links.
        fenced = "\n".join(
            "    " + line for text in lines for line in text.splitlines()
        )
        output.write((fenced + "\n").encode())
        media = "text/markdown; charset=utf-8"
    elif format_name == "docx":
        document = Document()
        document.add_heading(lines[0], 0)
        for line in lines[1:]:
            document.add_paragraph(line)
        document.save(output)
        media = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    else:
        styles = getSampleStyleSheet()
        elements = [Paragraph(escape(lines[0]), styles["Title"])]
        for line in lines[1:]:
            elements.extend(
                (
                    Paragraph(escape(line).replace("\n", "<br/>"), styles["BodyText"]),
                    Spacer(1, 10),
                )
            )
        SimpleDocTemplate(output).build(elements)
        media = "application/pdf"
    return Response(
        output.getvalue(),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="policy-{draft_id}-{version}.{format_name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
