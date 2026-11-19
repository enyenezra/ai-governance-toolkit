import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

BASE = {
    "likelihood": 1,
    "impact": 1,
    "uses_personal_data": False,
    "affects_high_stakes_decisions": False,
}


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("likelihood", "impact", "score", "level", "review"),
    [(1, 5, 5, "low", False), (2, 3, 6, "medium", False), (3, 5, 15, "high", True)],
)
def test_risk_levels(likelihood, impact, score, level, review):
    response = client.post(
        "/assessments", json={**BASE, "likelihood": likelihood, "impact": impact}
    )
    assert response.status_code == 200
    result = response.json()
    assert result["score"] == score
    assert result["risk_level"] == level
    assert result["review_required"] is review


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("uses_personal_data", "Uses personal data"),
        ("affects_high_stakes_decisions", "Affects high-stakes decisions"),
    ],
)
def test_flag_requires_review_at_low_score(field, reason):
    response = client.post("/assessments", json={**BASE, field: True})
    assert response.status_code == 200
    assert response.json() == {
        "score": 1,
        "risk_level": "low",
        "review_required": True,
        "review_reasons": [reason],
    }


def test_rejects_out_of_range_rating():
    response = client.post("/assessments", json={**BASE, "impact": 6})
    assert response.status_code == 422
