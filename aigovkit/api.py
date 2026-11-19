import os
from datetime import UTC, datetime
from typing import Annotated, Protocol
from uuid import uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from aigovkit.classification import suggest_classification
from aigovkit.models import (
    Assessment,
    ClassificationInput,
    ClassificationSuggestion,
    Connection,
    ConnectionAssessment,
    Identifier,
    Kind,
    PolicyVersion,
    Record,
    RiskReport,
    Simulation,
)
from aigovkit.policy import POLICY_VERSIONS, evaluate
from aigovkit.storage import PostgresInventory
from aigovkit.tenancy import Session, authenticate, schema_for


class Inventory(Protocol):
    def connect(self) -> psycopg.Connection: ...
    def audit(
        self,
        executor,
        action: str,
        resource_type: str,
        resource_id: str,
        version: int | None = None,
    ) -> None: ...
    def audit_events(self, before: int | None, limit: int) -> list[dict]: ...
    def put(self, records: list[Record]) -> None: ...
    def records(self) -> list[Record]: ...
    def save_report(self, report: RiskReport) -> None: ...
    def get_report(self, report_id: str) -> RiskReport | None: ...
    def list_reports(self, offset: int, limit: int) -> list[RiskReport]: ...
    def put_document(
        self, kind: str, document_id: str, body: dict, *, replace=False
    ): ...
    def get_document(self, kind: str, document_id: str) -> dict | None: ...
    def documents(self, kind: str, offset: int, limit: int) -> list[dict]: ...


def get_inventory(session: Annotated[Session, Depends(authenticate)]) -> Inventory:
    dsn = os.environ.get("AIGOVKIT_DATABASE_URL")
    if not dsn:
        raise HTTPException(503, "Governance database is not configured.")
    return PostgresInventory(
        dsn, schema_for(session.tenant) if session.tenant else None, actor=session
    )


router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])
Store = Annotated[Inventory, Depends(get_inventory)]


def load(store: Inventory) -> list[Record]:
    try:
        return store.records()
    except psycopg.Error:
        raise HTTPException(503, "Governance database unavailable.") from None


@router.get("/policies")
def policies() -> dict[str, list[str]]:
    return {"versions": POLICY_VERSIONS}


@router.put("/inventory/{kind}/{record_id}", response_model=Record)
def register(kind: Kind, record_id: Identifier, record: Record, store: Store) -> Record:
    if record.id != record_id or record.kind != kind:
        raise HTTPException(422, "The path kind and ID must match the record.")
    try:
        store.put([record])
    except psycopg.Error:
        raise HTTPException(503, "Governance database unavailable.") from None
    return record


@router.get("/inventory", response_model=list[Record])
def inventory(
    store: Store,
    kind: Kind | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[Record]:
    entries = [entry for entry in load(store) if kind is None or entry.kind == kind]
    return entries[offset : offset + limit]


@router.post("/simulations", response_model=Assessment)
def simulate(request: Simulation, store: Store) -> Assessment:
    return evaluate(request, load(store))


@router.get("/connection-assessments", response_model=list[ConnectionAssessment])
def evaluate_connections(
    store: Store,
    role: Identifier,
    policy_version: PolicyVersion = "1.0.0",
    department_id: Identifier | None = None,
    purpose: Identifier | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ConnectionAssessment]:
    entries = load(store)
    if policy_version == "1.0.0" and (department_id or purpose):
        raise HTTPException(422, "Department and purpose require policy version 1.1.0.")
    scopes = [
        (entry, action)
        for entry in entries
        if isinstance(entry, Connection)
        for action in sorted(set(entry.actions))
    ]
    return [
        ConnectionAssessment(
            connection_id=entry.id,
            action=action,
            assessment=evaluate(
                Simulation(
                    role=role,
                    agent_id=entry.agent_id,
                    asset_id=entry.asset_id,
                    action=action,
                    policy_version=policy_version,
                    department_id=department_id,
                    purpose=purpose,
                ),
                entries,
            ),
        )
        for entry, action in scopes[offset : offset + limit]
    ]


@router.post("/classification/suggestions")
def classify(metadata: ClassificationInput) -> ClassificationSuggestion:
    return suggest_classification(metadata)


@router.post("/reports", status_code=201)
def create_report(request: Simulation, store: Store) -> RiskReport:
    assessment = evaluate(request, load(store))
    report = RiskReport(
        id=uuid4().hex,
        created_at=datetime.now(UTC),
        request=request,
        assessment=assessment,
        risk_score={"low": 25, "medium": 50, "high": 100}[assessment.risk],
    )
    try:
        store.save_report(report)
    except psycopg.Error:
        raise HTTPException(503, "Governance database unavailable.") from None
    return report


@router.get("/reports/{report_id}")
def report_detail(report_id: Identifier, store: Store) -> RiskReport:
    try:
        report = store.get_report(report_id)
    except psycopg.Error:
        raise HTTPException(503, "Governance database unavailable.") from None
    if report is None:
        raise HTTPException(404, "Report not found.")
    return report


@router.get("/reports")
def reports(
    store: Store,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[RiskReport]:
    try:
        return store.list_reports(offset, limit)
    except psycopg.Error:
        raise HTTPException(503, "Governance database unavailable.") from None
