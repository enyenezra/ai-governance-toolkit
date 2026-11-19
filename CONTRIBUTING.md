# Contributing

Open an issue to discuss changes and use synthetic fixtures when sharing
examples. Create a branch and open a pull request against `main`.

Set up Python and PostgreSQL using the [README](README.md). Run
`python -m ruff check .` and `python -m pytest -q`. For storage changes, run
the integration test against a disposable PostgreSQL database. Add tests for
new decision rules and include unknown-access cases. Changes to existing policy
outcomes require a new version and a documented transition.

Connector changes should preserve the read-only contract and use local fixtures
for tests. Keep credentials in environment variables or a secret manager.
Report security issues privately using [SECURITY.md](SECURITY.md).

Review the [code of conduct](CODE_OF_CONDUCT.md) and [maintainer guide](docs/maintainers.md).
Use `node --check web/workspace.js` after changing the workspace script and
verify the Compose onboarding flow with synthetic inventory. Explicitly test keys
from a second organisation for changes to shared API or storage code.

The browser smoke suite runs in GitHub Actions against disposable PostgreSQL.
To run it locally, install the Python development dependencies, run
`npm ci --prefix tests/browser`, install Chromium with
`tests/browser/node_modules/.bin/playwright-core install chromium`, and run
`bash scripts/browser-smoke.sh` with `AIGOVKIT_TEST_DATABASE_URL` set.
