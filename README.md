# AI Governance Toolkit

A FastAPI service for initial AI use-case risk assessment. The scoring
thresholds are illustrative. Use the result to guide human review.

## Run locally

From the repository root, using Python 3.13:

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m uvicorn main:app --reload
```

Open the [interactive API docs](http://127.0.0.1:8000/docs).
`GET /health` returns `{"status":"ok"}`.

## Assess a use case

```sh
curl -fsS http://127.0.0.1:8000/assessments \
  -H 'Content-Type: application/json' \
  -d '{"likelihood":2,"impact":3,"uses_personal_data":true,"affects_high_stakes_decisions":false}'
```

Likelihood ranges from rare (1) to almost certain (5). Impact ranges from
negligible (1) to severe (5). The score is likelihood × impact. Scores of
1–5 are low, 6–14 are medium, and 15–25 are high.

A high score, personal data use, or involvement in high-stakes decisions
triggers human review. The example returns a score of 6, a medium risk
level, and a review requirement because the use case involves personal data.
The service stores no assessments.

## Contribute

Open an issue to propose a change or submit a pull request against `main`.
Run these checks before opening a pull request:

```sh
python -m ruff check .
python -m pytest -q
```

## Licence

[MIT](LICENSE)
