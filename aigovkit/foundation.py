from typing import Annotated, Literal
from uuid import uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, StringConstraints

from aigovkit.api import Store
from aigovkit.models import Identifier, StrictModel
from aigovkit.templates import CONTROLS, TEMPLATES
from aigovkit.tenancy import Session, authenticate

router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])
Actor = Annotated[Session, Depends(authenticate)]
Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
]
Answer = Literal["in_place", "partial", "missing"]
QUESTIONS = {
    "inventory": "Do you keep a current register of AI tools and agents?",
    "ownership": "Does each in-scope AI system have an accountable owner?",
    "security": "Do you review identity and access permissions before enabling AI?",
    "data": "Do you classify data before approving AI access?",
    "privacy": "Do you review privacy and jurisdiction before deployment?",
    "training": "Do staff receive AI safety and security training?",
    "suppliers": "Do you assess external AI providers before purchase?",
    "incidents": "Do you maintain and test an AI incident response process?",
    "oversight": "Do high-impact AI actions require human approval?",
}
MITIGATIONS = {
    "inventory": "List AI systems and assign an inventory custodian.",
    "ownership": "Assign owners and review dates for AI systems.",
    "security": "Review role needs and declared agent permissions.",
    "data": "Classify datasets before registering access connections.",
    "privacy": "Record applicability and ask privacy reviewers to confirm it.",
    "training": "Assign training and record completion.",
    "suppliers": "Collect evidence and document a supplier review.",
    "incidents": "Agree on incident owners, escalation contacts and a drill.",
    "oversight": "Document a human approval checkpoint for high-impact actions.",
}


class Profile(StrictModel):
    name: Text
    sector: Text
    jurisdiction: Text
    adoption_stage: Literal["exploring", "piloting", "operating"]


class ReadinessInput(StrictModel):
    answers: dict[Identifier, Answer] = Field(min_length=1, max_length=len(QUESTIONS))


class DraftInput(StrictModel):
    template_id: Identifier
    owner: Text
    scope: Text
    review_days: int = Field(ge=30, le=365)
    applies_to_agents: bool
    oversight_contact: Text | None = None


def database_call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except psycopg.Error:
        raise HTTPException(503, "Governance database unavailable.") from None


def save(store: Store, kind: str, body: dict) -> dict:
    record = {"id": uuid4().hex, **body}
    database_call(store.put_document, kind, record["id"], record)
    return record


def calculate_readiness(answers: dict[Identifier, Answer]) -> dict:
    if answers.keys() != QUESTIONS.keys():
        raise HTTPException(422, "Answer each readiness question exactly once.")
    points = {"in_place": 2, "partial": 1, "missing": 0}
    gaps = [
        {"domain": domain, "status": status, "task": MITIGATIONS[domain]}
        for status in ("missing", "partial")
        for domain in QUESTIONS
        if answers[domain] == status
    ]
    return {
        "scoring_version": "1.0.0",
        "score": round(
            100
            * sum(points[answer] for answer in answers.values())
            / (2 * len(QUESTIONS))
        ),
        "answers": answers,
        "gaps": gaps,
    }


@router.get("/session")
def session(actor: Actor) -> dict:
    return {
        "organisation_id": actor.tenant,
        "role": actor.role,
        **({"member_id": actor.member} if actor.member else {}),
    }


@router.get("/organisation")
def organisation(store: Store) -> Profile | None:
    return database_call(store.get_document, "profile", "default")


@router.put("/organisation")
def update_organisation(profile: Profile, store: Store) -> Profile:
    database_call(
        store.put_document, "profile", "default", profile.model_dump(), replace=True
    )
    return profile


@router.get("/readiness/questions")
def questions() -> dict:
    return {"scoring_version": "1.0.0", "questions": QUESTIONS}


@router.post("/readiness/assessments", status_code=201)
def assess_readiness(request: ReadinessInput, store: Store) -> dict:
    return save(store, "readiness", calculate_readiness(request.answers))


@router.get("/policy-templates")
def templates() -> list[dict]:
    return [
        {"id": key, "title": title, "version": "1.0.0"}
        for key, (title, _) in TEMPLATES.items()
    ]


@router.get("/controls")
def controls() -> list[dict]:
    return [
        {"id": key, "description": text, "status": "proposed"}
        for key, text in CONTROLS.items()
    ]


@router.post("/policy-drafts", status_code=201)
def create_draft(request: DraftInput, store: Store, actor: Actor) -> dict:
    template = TEMPLATES.get(request.template_id)
    if template is None:
        raise HTTPException(404, "Policy template not found.")
    profile = database_call(store.get_document, "profile", "default")
    if profile is None:
        raise HTTPException(409, "Complete organisation onboarding first.")
    if request.applies_to_agents and not request.oversight_contact:
        raise HTTPException(422, "Supply an oversight contact for agent policies.")
    title, clauses = template
    if request.applies_to_agents:
        clauses = (
            *clauses,
            (
                "AGENT-01",
                "CTRL-APPROVAL",
                (
                    f"Obtain documented human approval from {request.oversight_contact} "
                    "before high-impact agent actions."
                ),
            ),
        )
    return save(
        store,
        "draft",
        {
            **({"created_by": actor.member} if actor.member else {}),
            "title": title,
            "template_id": request.template_id,
            "template_version": "1.0.0",
            "status": "draft",
            "human_approval_required": True,
            "organisation": profile,
            "owner": request.owner,
            "scope": request.scope,
            "review_days": request.review_days,
            "clauses": [
                {
                    "id": f"{request.template_id}:{clause_id}",
                    "control_id": control,
                    "text": text,
                }
                for clause_id, control, text in clauses
            ],
        },
    )


@router.get("/policy-drafts/{draft_id}")
def get_draft(draft_id: Identifier, store: Store) -> dict:
    draft = database_call(store.get_document, "draft", draft_id)
    if draft is None:
        raise HTTPException(404, "Policy draft not found.")
    return draft


Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/policy-drafts")
def list_drafts(store: Store, offset: Offset = 0, limit: Limit = 20) -> list[dict]:
    return database_call(store.documents, "draft", offset, limit)


@router.get("/readiness/assessments")
def list_readiness(store: Store, offset: Offset = 0, limit: Limit = 20) -> list[dict]:
    return database_call(store.documents, "readiness", offset, limit)


@router.get("/audit-events")
def audit_events(
    store: Store,
    actor: Actor,
    before: Annotated[int | None, Query(ge=1, le=9_223_372_036_854_775_807)] = None,
    limit: Limit = 20,
) -> list[dict]:
    if actor.role != "auditor" or actor.member is None:
        raise HTTPException(403, "A named auditor is required.")
    return database_call(store.audit_events, before, limit)
