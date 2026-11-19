"""Deterministic preliminary AI-use-case screening; no LLM, uploads or persistence."""
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter()


class UseCaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    description: str = Field(min_length=20, max_length=3000)
    ai_type: Literal["generative", "agent", "predictive", "vision", "other", "unknown"]
    provider: str = Field(min_length=1, max_length=100)
    model_name: str | None = Field(default=None, max_length=120)
    deployment: Literal["api", "hosted", "self_hosted", "unknown"]
    autonomy: Literal["advisory", "human_approved", "autonomous"]
    personal_data: bool | None = None
    high_stakes: bool | None = None
    human_review: bool | None = None
    external_tools: bool | None = None


class Finding(BaseModel):
    id: str
    status: Literal["attention", "unknown"]
    reason: str
    recommended_control: str


class UseCaseResult(BaseModel):
    screening_version: Literal["1.0.0"] = "1.0.0"
    assessment_type: Literal["preliminary_documentation_screening"] = (
        "preliminary_documentation_screening"
    )
    risk_level: Literal["review", "elevated_review"]
    human_approval_required: Literal[True] = True
    evidence_verified: Literal[False] = False
    findings: list[Finding]
    limitations: list[str]


def screen_use_case(request: UseCaseInput) -> UseCaseResult:
    findings: list[Finding] = []

    def add(id: str, reason: str, control: str, *, unknown: bool = False) -> None:
        findings.append(
            Finding(
                id=id,
                status="unknown" if unknown else "attention",
                reason=reason,
                recommended_control=control,
            )
        )

    if request.personal_data is True:
        add("personal-data", "Personal data processing is declared.",
            "Document lawful basis, minimisation, retention, access and privacy review.")
    elif request.personal_data is None:
        add("personal-data-unknown", "Personal data processing is not specified.",
            "Confirm data categories and affected individuals before approval.", unknown=True)

    if request.high_stakes is True:
        add("high-stakes", "The AI affects high-impact decisions.",
            "Assess decision impacts, fairness, oversight and applicable rules.")
    elif request.high_stakes is None:
        add("high-stakes-unknown", "Decision impact is not specified.",
            "Determine whether decisions materially affect people or rights.", unknown=True)

    if request.human_review is False:
        add("no-human-review", "Meaningful human review is not declared.",
            "Design documented human review and override procedures.")
    elif request.human_review is None:
        add("human-review-unknown", "Human review has not been confirmed.",
            "Identify the accountable reviewer and approval procedure.", unknown=True)

    if request.autonomy == "autonomous":
        add("autonomous-actions", "The system may act without individual approval.",
            "Limit tool privileges, set action limits and provide emergency disablement.")

    if request.external_tools is True or request.ai_type == "agent":
        add("tool-boundaries", "Agent or external-tool interaction is indicated.",
            "Inventory available tools, credentials, allowed actions and test isolation.")
    elif request.external_tools is None:
        add("tools-unknown", "Tool access is not specified.",
            "Confirm whether the application can access external tools or systems.", unknown=True)

    if request.ai_type == "generative":
        add("generative-output", "Generative outputs may be unreliable or manipulated.",
            "Evaluate factual reliability, prompt injection and sensitive-data disclosure.")
    elif request.ai_type == "predictive":
        add("predictive-model", "Predictive model performance needs validation.",
            "Evaluate data quality, model error, drift and relevant fairness measures.")
    elif request.ai_type == "vision":
        add("vision-model", "Vision systems can create privacy and accuracy risks.",
            "Evaluate consent, image-data handling and representative performance.")

    if request.deployment in {"hosted", "api"}:
        add("external-provider", "An external service or API deployment is declared.",
            "Review vendor data handling, credentials, retention and transfer arrangements.")
    elif request.deployment == "unknown":
        add("deployment-unknown", "Deployment method is undecided.",
            "Confirm hosting and data flows before deployment review.", unknown=True)

    if request.ai_type == "unknown":
        add("ai-type-unknown", "AI system type is not known.",
            "Identify system architecture, capabilities and model type.", unknown=True)

    elevated = (
        request.high_stakes is True
        or request.autonomy == "autonomous"
        or request.human_review is False
    )
    return UseCaseResult(
        risk_level="elevated_review" if elevated else "review",
        findings=findings,
        limitations=[
            "Answers are self-declared and have not been independently verified.",
            "This endpoint does not evaluate uploaded files, test AI systems or grant approval.",
            "No legal-compliance determination or assurance of safety is provided.",
            "Never submit secrets or confidential personal information in the description.",
        ],
    )


@router.post("/use-case-screenings", response_model=UseCaseResult)
def create_use_case_screening(request: UseCaseInput) -> UseCaseResult:
    return screen_use_case(request)
