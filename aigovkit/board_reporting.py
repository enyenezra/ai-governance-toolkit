"""Tenant-scoped executive snapshots and scheduled, versioned exports."""

import csv
import io
import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import uuid4
from xml.sax.saxutils import escape

from docx import Document
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import Field
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate

from aigovkit.api import Store
from aigovkit.foundation import Actor, Limit, Offset, database_call
from aigovkit.models import Identifier, StrictModel
from aigovkit.policy_review import named_member
from aigovkit.tenancy import authenticate

router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])


class Scope(StrictModel):
    start: str
    end: str
    department: Identifier | None = None
    template: Literal["board", "risk", "security", "operations"] = "board"


class Schedule(StrictModel):
    enabled: bool
    days: int = Field(default=30, ge=1, le=366)
    department: Identifier | None = None
    template: Literal["board", "risk", "security", "operations"] = "board"


def require_report_access(actor):
    if not actor.member or actor.role not in {"editor", "publisher", "auditor"}:
        raise HTTPException(403, "Executive reports require a named governance role.")


def days(scope):
    try:
        start, end = date.fromisoformat(scope.start), date.fromisoformat(scope.end)
        if start.isoformat() != scope.start or end.isoformat() != scope.end:
            raise ValueError
        if start > end or (end - start).days >= 366 or end > datetime.now(UTC).date():
            raise ValueError
    except (ValueError, OverflowError):
        raise HTTPException(
            422, "Supply a valid period of at most 366 UTC days."
        ) from None
    return start, end


def snapshot(store, actor, scope: Scope, report_id: str) -> dict:
    start, end = days(scope)

    def persist():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || %s,0))",
                (":board:" + report_id,),
            )
            previous = cursor.execute(
                "SELECT body FROM foundation_documents WHERE kind='board_report' AND id=%s",
                (report_id,),
            ).fetchone()
            if previous:
                return {"created": False, "report": previous["body"]}
            trend = cursor.execute(
                """
                SELECT (created_at AT TIME ZONE 'UTC')::date AS day,
                       body->'assessment'->>'risk' AS risk, count(*) AS total
                FROM governance_reports WHERE (created_at AT TIME ZONE 'UTC')::date BETWEEN %s AND %s
                  AND (%s::text IS NULL OR body->'request'->>'department_id'=%s)
                GROUP BY day,risk ORDER BY day,risk
                """,
                (start, end, scope.department, scope.department),
            ).fetchall()
            metrics = {
                "assessments": sum(row["total"] for row in trend),
                "high_risk_assessments": sum(
                    row["total"] for row in trend if row["risk"] == "high"
                ),
            }
            if scope.department is None and scope.template != "risk":
                metrics.update(
                    cursor.execute(
                        """
                    SELECT
                      count(*) FILTER (WHERE kind='register_incident' AND body->>'status' <> 'resolved') AS open_incidents,
                      count(*) FILTER (WHERE kind='guardrail_current' AND body->>'suspended'='false'
                                       AND body->>'revision_id' IS NOT NULL) AS active_gate_rules,
                      count(*) FILTER (WHERE kind='learning_assignment') AS assigned_training,
                      count(*) FILTER (WHERE kind='learning_assignment' AND body->>'status'='completed') AS completed_training
                    FROM foundation_documents
                    """,
                    ).fetchone()
                )
                metrics.update(
                    cursor.execute(
                        """
                    SELECT count(DISTINCT p.draft_id) AS published_policies
                    FROM policy_publications p
                    """
                    ).fetchone()
                )
            profile = cursor.execute(
                "SELECT body->>'name' AS name FROM foundation_documents WHERE kind='profile' AND id='default'"
            ).fetchone()
            data = {
                "id": report_id,
                "version": "1.0.0",
                "generated_at": datetime.now(UTC).isoformat(),
                "organisation": profile["name"] if profile else actor.tenant,
                "scope": scope.model_dump(),
                "metrics": metrics,
                "trend": [{**row, "day": row["day"].isoformat()} for row in trend],
                "coverage": {
                    "assessments": "observed" if trend else "no_assessment_records",
                    "organisation_totals": "current_snapshot"
                    if len(metrics) > 2
                    else "excluded_by_scope",
                },
                "recommended_actions": (
                    ["Assign a risk owner to review high-risk assessments."]
                    if metrics["high_risk_assessments"]
                    else []
                )
                + (
                    ["Collect assessment evidence for the selected period."]
                    if not trend
                    else []
                ),
            }
            cursor.execute(
                "INSERT INTO foundation_documents (kind,id,body) VALUES ('board_report',%s,%s)",
                (report_id, Jsonb(data)),
            )
            store.audit(cursor, "report.generated", "board_report", report_id)
            return {"created": True, "report": data}

    return database_call(persist)


@router.post("/board-reports", status_code=201)
def create(scope: Scope, store: Store, actor: Actor) -> dict:
    named_member(actor, "editor")
    return snapshot(store, actor, scope, uuid4().hex)["report"]


@router.get("/board-reports")
def board_reports(
    store: Store, actor: Actor, offset: Offset = 0, limit: Limit = 20
) -> list[dict]:
    require_report_access(actor)
    return database_call(store.documents, "board_report", offset, limit)


@router.get("/board-reports/schedule")
def schedule(store: Store, actor: Actor) -> dict:
    require_report_access(actor)
    return (
        database_call(store.get_document, "board_schedule", "daily")
        or Schedule(enabled=False).model_dump()
    )


@router.put("/board-reports/schedule")
def configure(request: Schedule, store: Store, actor: Actor) -> dict:
    named_member(actor, "editor")
    data = request.model_dump()

    def write():
        with store.connect() as conn:
            conn.execute(
                """INSERT INTO foundation_documents (kind,id,body) VALUES ('board_schedule','daily',%s)
                   ON CONFLICT(kind,id) DO UPDATE SET body=EXCLUDED.body""",
                (Jsonb(data),),
            )
            store.audit(conn, "report.schedule_updated", "board_schedule", "daily")
        return data

    return database_call(write)


@router.post("/board-reports/run")
def run(store: Store, actor: Actor) -> dict:
    named_member(actor, "scheduler")
    config = database_call(store.get_document, "board_schedule", "daily")
    if not config or not config["enabled"]:
        return {"created": False}
    today = datetime.now(UTC).date()
    last_complete_day = today - timedelta(days=1)
    spec = Scope(
        start=(today - timedelta(days=config["days"])).isoformat(),
        end=last_complete_day.isoformat(),
        department=config["department"],
        template=config["template"],
    )
    result = snapshot(store, actor, spec, "daily-" + today.isoformat())
    return {"created": result["created"], "report_id": result["report"]["id"]}


@router.get("/board-reports/{report_id}/export/{format_name}")
def export(
    report_id: Identifier,
    format_name: Literal["json", "csv", "pdf", "docx"],
    store: Store,
    actor: Actor,
):
    require_report_access(actor)
    report = database_call(store.get_document, "board_report", report_id)
    if not report:
        raise HTTPException(404, "Executive report not found.")

    scope = report["scope"]
    rows = [
        ("Organisation", report["organisation"] or "Unknown"),
        ("Template", scope["template"]),
        ("Period start", scope["start"]),
        ("Period end", scope["end"]),
        ("Department", scope["department"] or "All"),
        ("Generated", report["generated_at"]),
        ("Report version", report["version"]),
        ("Assessment coverage", report["coverage"]["assessments"]),
        *report["metrics"].items(),
        *(
            (f"{row['day']} {row['risk']} risk", row["total"])
            for row in report["trend"]
        ),
        *(("Recommended action", note) for note in report["recommended_actions"]),
    ]
    rows = [
        (
            name,
            re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]", "", item)
            if isinstance(item, str)
            else item,
        )
        for name, item in rows
    ]
    stream = io.BytesIO()
    if format_name == "json":
        stream.write(json.dumps(report).encode())
        media = "application/json"
    elif format_name == "csv":
        table = io.StringIO()
        writer = csv.writer(table)
        writer.writerow(("Metric", "Value"))
        writer.writerows(
            (
                name,
                "'" + item
                if isinstance(item, str)
                and item.lstrip().startswith(("=", "+", "-", "@"))
                else item,
            )
            for name, item in rows
        )
        stream.write(table.getvalue().encode())
        media = "text/csv"
    elif format_name == "pdf":
        styles = getSampleStyleSheet()
        SimpleDocTemplate(stream).build(
            [
                Paragraph("AIGovKit executive report", styles["Title"]),
                *(
                    Paragraph(escape(f"{name}: {item}"), styles["BodyText"])
                    for name, item in rows
                ),
            ]
        )
        media = "application/pdf"
    else:
        document = Document()
        document.add_heading("AIGovKit executive report", 0)
        for name, item in rows:
            document.add_paragraph(f"{name}: {item}")
        document.save(stream)
        media = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    return Response(
        stream.getvalue(),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="report-{report_id}.{format_name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
