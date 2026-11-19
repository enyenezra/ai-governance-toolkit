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
