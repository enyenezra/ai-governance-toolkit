"""Adaptive readiness and versioned framework references."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from aigovkit.api import Store
from aigovkit.foundation import (
    MITIGATIONS,
    QUESTIONS,
    Answer,
    Limit,
    Offset,
    database_call,
    save,
)
from aigovkit.models import Identifier, StrictModel
from aigovkit.tenancy import authenticate

router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])
EXTRA = {
    "development": (
        "Are material AI changes tested and approved before release?",
        "Document an AI change checklist and independent release review.",
    ),
    "monitoring": (
        "Do you monitor AI activity and exercise incident escalation?",
        "Assign monitoring owners, alert thresholds and escalation exercises.",
    ),
    "sensitive_data": (
        "Have you assessed data flows involving sensitive or regulated information?",
        "Map sensitive data flows and obtain a qualified governance review.",
    ),
    "identity_lifecycle": (
        "Do joiners, movers and leavers trigger an AI access review?",
        "Test group changes and suspension against AI access recommendations.",
    ),
    "data_lifecycle": (
        "Do AI data flows have approved retention and deletion rules?",
        "Assign retention and deletion owners and verify the controls.",
    ),
    "evidence": (
        "Can reviewers trace governance decisions to reliable evidence?",
        "Collect dated approval and verification evidence.",
    ),
    "vendor_exit": (
        "Can you exit AI providers and verify data return or deletion?",
        "Document supplier exit and deletion requirements.",
    ),
}
REFERENCES = [
    (
        "nist-ai-rmf",
        "NIST AI Risk Management Framework",
        "1.0",
        "2023-01-26",
        "https://www.nist.gov/itl/ai-risk-management-framework",
        ["CTRL-INVENTORY", "CTRL-EVIDENCE"],
    ),
    (
        "nist-genai-profile",
        "NIST Generative AI Profile",
        "AI 600-1",
        "2024-07-26",
        "https://doi.org/10.6028/NIST.AI.600-1",
        ["CTRL-TEST", "CTRL-DATA"],
    ),
    (
        "iso-42001",
        "ISO/IEC 42001",
        "2023",
        None,
        "https://www.iso.org/standard/42001",
        ["CTRL-INVENTORY", "CTRL-EVIDENCE"],
    ),
    (
        "iso-27001",
        "ISO/IEC 27001",
        "2022",
        None,
        "https://www.iso.org/standard/27001",
        ["CTRL-ACCESS", "CTRL-EVIDENCE"],
    ),
    (
        "owasp-llm",
        "OWASP Top 10 for LLM Applications",
        "2026",
        "2026-08-03",
        "https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/",
        ["CTRL-TEST", "CTRL-DATA"],
    ),
    (
        "owasp-agentic",
        "OWASP Top 10 for Agentic Applications",
        "2026",
        "2025-12-09",
        "https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/",
        ["CTRL-ACCESS", "CTRL-APPROVAL"],
    ),
    (
        "eu-ai-act",
        "EU AI Act",
        "Regulation (EU) 2024/1689",
        None,
        "https://eur-lex.europa.eu/eli/reg/2024/1689/oj",
        ["CTRL-INVENTORY", "CTRL-APPROVAL"],
    ),
    (
        "uk-data-protection",
        "UK data protection",
        "Data Protection Act 2018 / UK GDPR",
        None,
        "https://www.legislation.gov.uk/ukpga/2018/12/contents",
        ["CTRL-DATA", "CTRL-EVIDENCE"],
    ),
]


class AdaptiveInput(StrictModel):
    answers: dict[Identifier, Answer] = Field(min_length=1, max_length=16)


def adaptive_questions(store: Store, sensitive: bool) -> dict:
    profile = database_call(store.get_document, "profile", "default")
    if profile is None:
        raise HTTPException(409, "Complete organisation onboarding first.")
    additions = ["identity_lifecycle", "evidence"]
    if profile["adoption_stage"] in {"piloting", "operating"}:
        additions.append("development")
    if profile["adoption_stage"] == "operating":
        additions.extend(("monitoring", "vendor_exit"))
    if sensitive:
        additions.extend(("sensitive_data", "data_lifecycle"))
    return {**QUESTIONS, **{key: EXTRA[key][0] for key in additions}}


@router.get("/readiness/adaptive")
def adaptive(store: Store, handles_sensitive_data: bool = False) -> dict:
    return {
        "version": "2.1.0",
        "questions": adaptive_questions(store, handles_sensitive_data),
    }


@router.post("/readiness/adaptive", status_code=201)
def assess(
    request: AdaptiveInput, store: Store, handles_sensitive_data: bool = False
) -> dict:
    expected = adaptive_questions(store, handles_sensitive_data)
    if request.answers.keys() != expected.keys():
        raise HTTPException(
            422, "Answer every question from the applicable questionnaire."
        )
    points = {"missing": 0, "partial": 1, "in_place": 2}
    score = round(
        100 * sum(points[a] for a in request.answers.values()) / (2 * len(expected))
    )
    gaps = [
        {"domain": key, "status": status, "task": MITIGATIONS.get(key) or EXTRA[key][1]}
        for status in ("missing", "partial")
        for key in expected
        if request.answers[key] == status
    ]
    return save(
        store,
        "adaptive_readiness",
        {
            "scoring_version": "2.1.0",
            "score": score,
            "gaps": gaps,
            "answers": request.answers,
            "handles_sensitive_data": handles_sensitive_data,
        },
    )


@router.get("/readiness/adaptive/results")
def results(store: Store, offset: Offset = 0, limit: Limit = 20) -> list[dict]:
    return database_call(store.documents, "adaptive_readiness", offset, limit)


@router.get("/frameworks")
def frameworks() -> dict:
    return {
        "registry_version": "1.0.0",
        "applicability": "requires_review",
        "references": [
            {
                "id": key,
                "title": title,
                "version": version,
                "published_on": published,
                "source": source,
                "related_controls": controls,
            }
            for key, title, version, published, source, controls in REFERENCES
        ],
    }
