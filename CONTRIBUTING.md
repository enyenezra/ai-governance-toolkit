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
To run it locally, install the Python development dependencies and build the
React frontend with Node.js 24 and npm. Set `AIGOVKIT_TEST_DATABASE_URL`
to a disposable PostgreSQL database before running the following commands.

```sh
npm ci --prefix frontend
npm run build --prefix frontend
npm ci --prefix tests/browser
tests/browser/node_modules/.bin/playwright-core install chromium
bash scripts/browser-smoke.sh
```

## Frontend pages

Build all new user-facing pages and views as React components under `frontend/`.
FastAPI serves the compiled bundles and their minimal HTML entry pages. Keep
assets same-origin and extend browser checks for changed workflows. The workspace
controller preserves existing API calls and form handlers while the view
components move to React. Add new interactions through React components.
