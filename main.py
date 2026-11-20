from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from aigovkit.access_workflow import router as access_router
from aigovkit.api import router
from aigovkit.assurance import router as assurance_router
from aigovkit.containment import router as containment_router
from aigovkit.device_discovery import router as device_router
from aigovkit.enterprise import router as enterprise_router
from aigovkit.foundation import router as foundation_router
from aigovkit.guardrails import router as gate_router
from aigovkit.operations_automation import router as automation_router
from aigovkit.policy_outputs import router as output_router
from aigovkit.policy_publication import router as publication_router
from aigovkit.policy_review import router as review_router
from aigovkit.provider_enforcement import router as provider_router
from aigovkit.readiness_extensions import router as readiness_router
from aigovkit.sso import router as sso_router
from aigovkit.workspace_discovery import router as workspace_discovery_router

app = FastAPI(title="AI Governance Toolkit", version="0.1.0")
app.include_router(router)
app.include_router(assurance_router)
app.include_router(access_router)
app.include_router(enterprise_router)
app.include_router(device_router)
app.include_router(workspace_discovery_router)
app.include_router(sso_router)
app.include_router(gate_router)
app.include_router(containment_router)
app.include_router(provider_router)
app.include_router(automation_router)
app.include_router(output_router)
app.include_router(readiness_router)
app.include_router(foundation_router)
app.include_router(review_router)
app.include_router(publication_router)


@app.middleware("http")
async def protect_sensitive_responses(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/v1/"):
        response.headers["Cache-Control"] = "no-store"
    if request.url.path.startswith("/v1/sso/"):
        response.headers["Referrer-Policy"] = "no-referrer"
    return response


WORKSPACE_CSP = (
    "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
    "object-src 'none'; form-action 'self'"
)
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


@app.get("/workspace", include_in_schema=False)
def workspace_page() -> FileResponse:
    return FileResponse(
        WEB_DIR / "workspace.html", headers={"Content-Security-Policy": WORKSPACE_CSP}
    )


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
