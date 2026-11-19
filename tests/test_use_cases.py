"""Focused tests for the additive preliminary AI use-case screen."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aigovkit.use_cases import UseCaseInput, router, screen_use_case

BASE = {
    "description": "A synthetic assistant helps staff summarise generic invoices.",
    "ai_type": "generative",
    "provider": "example-provider",
    "deployment": "self_hosted",
    "autonomy": "advisory",
    "personal_data": False,
    "high_stakes": False,
    "human_review": True,
    "external_tools": False,
}


def test_preliminary_result_never_grants_approval():
    result = screen_use_case(UseCaseInput.model_validate(BASE))
    assert result.risk_level == "review"
    assert result.human_approval_required is True
    assert result.evidence_verified is False
    assert "generative-output" in {item.id for item in result.findings}


def test_autonomous_sensitive_use_case():
    request = BASE | {
        "ai_type": "agent", "autonomy": "autonomous", "personal_data": True,
        "high_stakes": True, "human_review": False, "external_tools": True,
        "deployment": "api",
    }
    result = screen_use_case(UseCaseInput.model_validate(request))
    ids = {item.id for item in result.findings}
    assert result.risk_level == "elevated_review"
    assert {"autonomous-actions", "personal-data", "high-stakes",
            "no-human-review", "tool-boundaries", "external-provider"} <= ids


def test_unknowns_are_not_treated_as_safe():
    request = BASE | {
        "personal_data": None, "high_stakes": None, "human_review": None,
        "external_tools": None, "deployment": "unknown", "ai_type": "unknown",
    }
    findings = screen_use_case(UseCaseInput.model_validate(request)).findings
    assert sum(f.status == "unknown" for f in findings) >= 5


def test_description_is_not_echoed():
    marker = "Private-example-identifier-1234"
    request = BASE | {"description": BASE["description"] + " " + marker}
    result = screen_use_case(UseCaseInput.model_validate(request))
    assert marker not in result.model_dump_json()


@pytest.mark.parametrize("changes", [
    {"description": "too short"},
    {"description": "a" * 3001},
    {"ai_type": "invalid"},
    {"personal_data": "yes"},
    {"provider": ""},
    {"deployment": "local-cloud"},
    {"unexpected": "value"},
])
def test_bad_inputs_rejected(changes):
    with pytest.raises(ValidationError):
        UseCaseInput.model_validate(BASE | changes)


def test_deterministic_ordering():
    a = screen_use_case(UseCaseInput.model_validate(BASE))
    b = screen_use_case(UseCaseInput.model_validate(BASE))
    assert a == b


def test_endpoint_response():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.post("/use-case-screenings", json=BASE)
    assert response.status_code == 200
    assert response.json()["evidence_verified"] is False
    assert client.post("/use-case-screenings", json=BASE | {"autonomy": "bad"}).status_code == 422
