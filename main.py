from typing import Annotated, Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

app = FastAPI(title="AI Governance Toolkit", version="0.1.0")

Rating = Annotated[StrictInt, Field(ge=1, le=5)]
RiskLevel = Literal["low", "medium", "high"]


class AssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    likelihood: Rating
    impact: Rating
    uses_personal_data: StrictBool
    affects_high_stakes_decisions: StrictBool


class AssessmentResult(BaseModel):
    score: int
    risk_level: RiskLevel
    review_required: bool
    review_reasons: list[str]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/assessments", response_model=AssessmentResult)
def assess(request: AssessmentRequest) -> AssessmentResult:
    score = request.likelihood * request.impact
    if score >= 15:
        level = "high"
    elif score >= 6:
        level = "medium"
    else:
        level = "low"

    reasons = []
    if level == "high":
        reasons.append("High likelihood-impact score")
    if request.uses_personal_data:
        reasons.append("Uses personal data")
    if request.affects_high_stakes_decisions:
        reasons.append("Affects high-stakes decisions")

    return AssessmentResult(
        score=score,
        risk_level=level,
        review_required=bool(reasons),
        review_reasons=reasons,
    )
