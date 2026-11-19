"""Tenant governance registers and continuous monitoring from submitted evidence."""

from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import Field, StringConstraints

from aigovkit.api import Store, load
from aigovkit.foundation import Actor, Limit, Offset, database_call
from aigovkit.models import Agent, Identifier, StrictModel, Tool
from aigovkit.readiness_extensions import REFERENCES
from aigovkit.templates import CONTROLS
from aigovkit.tenancy import authenticate

router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])
Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
Score = Annotated[int, Field(ge=1, le=5)]
Day = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class Risk(StrictModel):
    kind: Literal["risk"]
    title: Text
    system_id: Identifier
    owner: Identifier
    domain: Literal[
        "security",
        "privacy",
        "fairness",
        "reliability",
        "transparency",
        "resilience",
        "oversight",
        "supplier",
        "financial",
        "reputational",
        "other",
    ] = "security"
    description: Text | None = None
    evidence_references: list[Text] = Field(default_factory=list, max_length=12)
    likelihood: Score
    impact: Score
    control_effectiveness: int = Field(ge=0, le=100)
    treatment: Literal["mitigate", "avoid", "transfer", "accept"]
    treatment_owner: Identifier
    due_date: Day
    status: Literal["open", "in_treatment", "closed"]


class Incident(StrictModel):
    kind: Literal["incident"]
    title: Text
    system_id: Identifier
    owner: Identifier
    severity: Literal["low", "medium", "high", "critical"]
    status: Literal["open", "contained", "recovering", "resolved"]
    update: Text
    evidence_references: list[Text] = Field(default_factory=list, max_length=12)


class Vendor(StrictModel):
    kind: Literal["vendor"]
    title: Text
    owner: Identifier
    hosting_region: Text
    data_reuse: Literal["prohibited", "permitted", "unknown"]
    subprocessors_reviewed: bool
    assurance_reference: Text
    exit_plan: Text | None = None
    data_processing_notes: Text | None = None
    residency_verified: bool = False
    contract_reviewed: bool = False
    status: Literal["assessment", "approved", "rejected"]
    reassessment_due: Day


class Training(StrictModel):
    kind: Literal["training"]
    title: Text
    assignee: Identifier
    due_date: Day
    status: Literal["assigned", "completed"]
    evidence_reference: Text | None = None


class Discovery(StrictModel):
    kind: Literal["discovery"]
    title: Text
    source: Identifier
    service: Text
    department_id: Identifier | None = None
    count: int = Field(ge=1, le=1_000_000)
    status: Literal["needs_review", "approved", "unapproved"]
    observed_on: Day


class Signal(StrictModel):
    kind: Literal["signal"]
    title: Text
    source: Identifier
    agent_id: Identifier
    event: Literal["activity", "denied", "error", "credential_rotation"]
    count: int = Field(ge=1, le=1_000_000)
    observed_on: Day


class Credential(StrictModel):
    kind: Literal["credential"]
    title: Text
    agent_id: Identifier
    owner: Identifier
    rotation_due: Day
    last_rotated: Day | None = None


class ControlCheck(StrictModel):
    kind: Literal["control_check"]
    title: Text
    control_id: Annotated[str, StringConstraints(pattern=r"^CTRL-[A-Z]+$")]
    reviewer: Identifier
    result: Literal["pass", "fail", "inconclusive"]
    evidence_reference: Text
    checked_on: Day


class FrameworkAssessment(StrictModel):
    kind: Literal["framework_assessment"]
    title: Text
    framework_id: Identifier
    framework_version: Text
    applicability: Literal["applicable", "not_applicable", "needs_review"]
    owner: Identifier
    rationale: Text
    control_ids: list[Text] = Field(max_length=20)
    evidence_references: list[Text] = Field(default_factory=list, max_length=12)
    reviewed_on: Day


Record = Annotated[
    Risk
    | Incident
    | Vendor
    | Training
    | Discovery
    | Signal
    | Credential
    | ControlCheck
    | FrameworkAssessment,
    Field(discriminator="kind"),
]
Register = Literal[
    "risk",
    "incident",
    "vendor",
    "training",
    "discovery",
    "signal",
    "credential",
    "control_check",
    "framework_assessment",
]


def checked_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, "Use a valid ISO calendar date.") from None


def write_register(store: Store, entry, key: str, expected: int) -> dict:
    kind = "register_" + entry.kind
    with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || %s, 0))",
            (f":{kind}:{key}",),
        )
        row = cursor.execute(
            "SELECT body FROM foundation_documents WHERE kind = %s AND id = %s",
            (kind, key),
        ).fetchone()
        old = row["body"] if row else None
        if expected != (old["version"] if old else 0):
            raise HTTPException(409, "Load the current record version before saving.")
        if old and entry.kind in {"signal", "control_check"}:
            raise HTTPException(
                409, "Evidence records are append-only. Submit a new observation."
            )
        if (
            old
            and entry.kind == "discovery"
            and any(
                old[key] != value
                for key, value in entry.model_dump(mode="json").items()
                if key != "status"
            )
        ):
            raise HTTPException(409, "Only the discovery review status can change.")
        if old and entry.kind == "incident":
            stages = ["open", "contained", "recovering", "resolved"]
            if stages.index(entry.status) not in {
                stages.index(old["status"]),
                stages.index(old["status"]) + 1,
            }:
                raise HTTPException(409, "Use the next incident stage.")
        body = {"id": key, "version": expected + 1, **entry.model_dump(mode="json")}
        if entry.kind == "risk":
            inherent = entry.likelihood * entry.impact
            body.update(
                scoring_version="1.0.0",
                inherent_score=inherent,
                residual_score=(inherent * (100 - entry.control_effectiveness) + 99)
                // 100,
            )
        cursor.execute(
            """INSERT INTO foundation_documents (kind, id, body) VALUES (%s, %s, %s)
               ON CONFLICT (kind, id) DO UPDATE SET body = EXCLUDED.body""",
            (kind, key, Jsonb(body)),
        )
        cursor.execute(
            "INSERT INTO foundation_documents (kind, id, body) VALUES (%s, %s, %s)",
            (kind + "_history", f"{key}:{body['version']}", Jsonb(body)),
        )
        store.audit(cursor, "register.saved", entry.kind, key, body["version"])
        return body


@router.put("/registers/{kind}/{key}")
def register(
    kind: Register,
    key: Identifier,
    entry: Record,
    store: Store,
    actor: Actor,
    expected_version: Annotated[int, Query(ge=0, le=2_147_483_646)] = 0,
) -> dict:
    if isinstance(entry, ControlCheck) and entry.control_id not in CONTROLS:
        raise HTTPException(422, "Select a control from the catalogue.")
    if isinstance(entry, FrameworkAssessment):
        if not any(
            key == entry.framework_id and version == entry.framework_version
            for key, _, version, _, _, _ in REFERENCES
        ):
            raise HTTPException(422, "Select a known framework and edition.")
        if set(entry.control_ids) - CONTROLS.keys():
            raise HTTPException(422, "Select controls from the catalogue.")
    if kind != entry.kind:
        raise HTTPException(422, "Path and record kind must match.")
    for field, value in entry.model_dump().items():
        if value and (
            field.endswith(("_date", "_due"))
            or field in {"observed_on", "checked_on", "last_rotated", "reviewed_on"}
        ):
            checked_date(value)
    if (
        isinstance(entry, Training)
        and entry.status == "completed"
        and not entry.evidence_reference
    ):
        raise HTTPException(422, "Supply a completion evidence reference.")
    if isinstance(entry, (Risk, Incident, Signal, Credential)):
        records = load(store)
        targets = {record.id for record in records if isinstance(record, Agent)}
        if isinstance(entry, (Risk, Incident)):
            targets.update(record.id for record in records if isinstance(record, Tool))
            reference = entry.system_id
        else:
            reference = entry.agent_id
        if reference not in targets:
            raise HTTPException(
                422, "Register the referenced AI system or agent first."
            )
    return database_call(write_register, store, entry, key, expected_version)


@router.get("/registers/{kind}")
def register_list(
    kind: Register, store: Store, offset: Offset = 0, limit: Limit = 20
) -> list[dict]:
    return database_call(store.documents, "register_" + kind, offset, limit)


@router.get("/registers/{kind}/{key}")
def register_detail(kind: Register, key: Identifier, store: Store) -> dict:
    entry = database_call(store.get_document, "register_" + kind, key)
    if entry is None:
        raise HTTPException(404, "Register entry not found.")
    return entry


@router.get("/registers/{kind}/{key}/history/{version}")
def register_history(
    kind: Register, key: Identifier, version: int, store: Store
) -> dict:
    entry = database_call(
        store.get_document, "register_" + kind + "_history", f"{key}:{version}"
    )
    if entry is None:
        raise HTTPException(404, "Register version not found.")
    return entry


@router.get("/monitoring")
def monitoring(store: Store) -> dict:
    today = datetime.now(UTC).date().isoformat()

    def collect():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                """
                SELECT
                    count(*) FILTER (WHERE kind='register_incident' AND body->>'status' <> 'resolved') AS open_incidents,
                    count(*) FILTER (WHERE kind='register_risk' AND body->>'status' <> 'closed'
                                      AND (body->>'residual_score')::int >= 15) AS high_residual_risks,
                    count(*) FILTER (WHERE kind='register_discovery' AND body->>'status' <> 'approved') AS unapproved_observations,
                    count(*) FILTER (WHERE kind='register_credential' AND body->>'rotation_due' <= %s) AS rotations_due,
                    count(*) FILTER (WHERE kind='register_training' AND body->>'status'='completed') AS completed_training,
                    count(*) FILTER (WHERE kind='register_training') AS assigned_training,
                    count(*) FILTER (WHERE kind='register_control_check' AND body->>'result'='fail') AS failed_control_checks,
                    count(*) FILTER (WHERE kind='guardrail_check' AND body->>'decision'='deny') AS gate_denials,
                    count(*) FILTER (WHERE kind='guardrail_current' AND body->>'suspended'='true') AS agents_suspended_at_gate
                FROM foundation_documents WHERE kind LIKE 'register_%%' OR kind IN ('guardrail_check','guardrail_current')
                """,
                (today,),
            ).fetchone()
            signals = cursor.execute(
                """SELECT body->>'event' AS event, sum((body->>'count')::bigint) AS total
                   FROM foundation_documents WHERE kind='register_signal'
                   GROUP BY body->>'event' ORDER BY event"""
            ).fetchall()
            return {
                **row,
                "signals": signals,
                "as_of": today,
                "coverage": "submitted_evidence",
            }

    return database_call(collect)
