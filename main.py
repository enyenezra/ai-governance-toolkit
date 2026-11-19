from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from aigovkit.api import router

app = FastAPI(title="AI Governance Toolkit", version="0.1.0")
app.include_router(router)

WEB_DIR = Path(__file__).resolve().parent / "web"
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")

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


@app.get("/", include_in_schema=False)
def assessment_page() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


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
