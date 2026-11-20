# AIGovKit

AIGovKit is an open-source, self-hosted AI governance toolkit for teams that
need to understand which organisational data their AI applications and agents
can access. It gives platform, security and governance teams a shared
inventory and a way to review access before granting it.

Register tools, agents and data assets, record what a department needs for a
specific purpose, and simulate access through the REST API. Each assessment
explains its recommendation and suggests narrower permissions where appropriate.
Policy evaluation runs within your deployment and uses declared metadata.
Every decision requires human approval, and AIGovKit never changes permissions.

For a first look, run the synthetic support example below. Developers can use
the OpenAPI documentation, [architecture overview](docs/architecture.md) and
[sample inputs](examples/README.md). See [Contributing](CONTRIBUTING.md) for
ways to help and [Security](SECURITY.md) for deployment and reporting guidance.

## Governance workspace

Open [the workspace](http://127.0.0.1:8000/workspace) after starting the demo.
Sign in with the configured key. Set the organisation profile, register an AI
application or agent, and complete the readiness questionnaire. Generate one
of 12 saved policy drafts and review its clauses and proposed controls in the
policy library. The dashboard uses saved assessments and registered inventory.
The original scoring demo remains available at `/`.

Named editors and independent reviewers can revise, submit and review drafts.
A separate publisher can publish an approved revision inside the organisation.
Named members can acknowledge a specific published version. See the
[policy review](docs/policy-review.md) and [publication](docs/policy-publication.md)
guides for the workflow, and the [foundation plan](docs/foundation-plan.md) for the baseline audit, security
model and release roadmap.

## Run a local demo

The single-organisation demo requires Docker Compose and a terminal. Run these commands from
the repository root in the same terminal:

```sh
export AIGOVKIT_DB_PASSWORD="$(openssl rand -hex 24)"
export AIGOVKIT_API_KEY="$(openssl rand -hex 32)"
docker compose up --build --wait
docker compose exec -T api python -m aigovkit.bootstrap --import-json examples/department-inventory.json
```

For the demo organisation, open **Organisation setup** in the workspace and
enter your own profile, or load the synthetic profile:

```sh
curl -fsS -X PUT http://127.0.0.1:8000/v1/organisation \
  -H "X-API-Key: $AIGOVKIT_API_KEY" -H 'Content-Type: application/json' \
  --data-binary @examples/organisation.json
```

The API listens on localhost. Compose retains inventory and reports in its
database volume when you run `docker compose down`. Keep the database password
in a secure location and reuse it when restarting an existing volume. The sample
import replaces records with matching kinds and IDs. Use it only for demo data.

The risk assessment and governance workspace are built with React. Docker
compiles both pages as part of the image build.

### Run the API directly

Use Python 3.13, Node.js 24 with npm, and Docker with its daemon running. Run these commands from the
repository root in the same terminal. The database and API bind to loopback.
Use a fresh container and synthetic data for the demo.

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm ci --prefix frontend
npm run build --prefix frontend

export POSTGRES_PASSWORD="$(python -c 'import secrets; print(secrets.token_hex(24))')"
export AIGOVKIT_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export AIGOVKIT_DATABASE_URL="postgresql://postgres:${POSTGRES_PASSWORD}@127.0.0.1:55432/aigovkit"

docker run --rm -d --name aigovkit-demo -p 127.0.0.1:55432:5432 \
  -e POSTGRES_PASSWORD -e POSTGRES_DB=aigovkit postgres:16
```

Run `docker exec aigovkit-demo pg_isready -h 127.0.0.1 -U postgres -d aigovkit`.
Once it reports that it is accepting connections, initialize storage and import
the sample inventory:

```sh
python -m aigovkit.bootstrap --import-json examples/department-inventory.json
python -m uvicorn main:app --host 127.0.0.1
```

For an existing PostgreSQL database, configure `AIGOVKIT_DATABASE_URL` and
`AIGOVKIT_API_KEY` via your secret manager and run `python -m aigovkit.bootstrap`
without the sample import. Use a dedicated database per organisation. See
[deployment boundaries](SECURITY.md) before exposing the service beyond localhost.

## Try the governance API

Open [interactive API docs](http://127.0.0.1:8000/docs) and use **Authorize**
to enter the value of `AIGOVKIT_API_KEY`. If you used Compose, you can also
run these commands in the same terminal.

```sh
curl -fsS http://127.0.0.1:8000/v1/reports \
  -H "X-API-Key: $AIGOVKIT_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"role":"support","agent_id":"helper","asset_id":"tickets","action":"read","policy_version":"1.1.0","department_id":"customer-support","purpose":"ticket-summary"}'

curl -fsS 'http://127.0.0.1:8000/v1/connection-assessments?role=support&policy_version=1.1.0&department_id=customer-support&purpose=ticket-summary' \
  -H "X-API-Key: $AIGOVKIT_API_KEY"
```

The support read comes back as medium risk and `consider_after_review`. The
report includes a score of 50 and an ID you can retrieve later. The scan shows
denied requests for ticket writes and payroll reads. Each
result gives reasons and recommended controls. Every result requires human
approval for any real-world access decision. AIGovKit never grants or changes access.

| Method and path | Purpose |
| --- | --- |
| `PUT /v1/inventory/{kind}/{record_id}` | Register or replace a tool, agent, asset, department, role need or connection by stable ID |
| `GET /v1/inventory` | List inventory with optional kind and pagination |
| `GET /v1/policies` | List supported policy versions |
| `POST /v1/simulations` | Explain a recommendation for one role, agent, asset and action |
| `GET /v1/connection-assessments?role=support` | Review declared connection actions against one role, with pagination |
| `POST /v1/classification/suggestions` | Suggest a classification from structured data flags |
| `POST /v1/reports` | Run a simulation and save its JSON result |
| `GET /v1/reports` and `GET /v1/reports/{report_id}` | List past reports or retrieve one by ID |
| `GET /v1/session` | Return the authenticated organisation and role |
| `GET /v1/organisation`, `PUT /v1/organisation` | Read or update the organisation profile |
| `GET /v1/readiness/questions` | Get the readiness questionnaire and scoring version |
| `GET /v1/readiness/assessments`, `POST /v1/readiness/assessments` | List or save explainable readiness results |
| `GET /v1/policy-templates`, `GET /v1/controls` | List the templates and proposed controls |
| `GET /v1/policy-drafts`, `POST /v1/policy-drafts`, `GET /v1/policy-drafts/{id}` | List, generate or retrieve saved drafts |
| `GET /v1/policy-drafts/{id}/revisions`, `POST /v1/policy-drafts/{id}/revisions` | List or create versioned clause revisions |
| `POST /v1/policy-reviews` | Record an independent review decision |
| `POST /v1/policy-publications`, `GET /v1/published-policies` | Publish an approved version or list current published policies |
| `POST /v1/policy-acknowledgements`, `GET /v1/policy-acknowledgements` | Acknowledge a version or list your receipts |
| `GET /health` | Check process liveness |

For example, register an asset with
`PUT /v1/inventory/asset/handbook` and a JSON body of
`{"kind":"asset","id":"handbook","name":"Staff handbook","classification":"internal"}`.
See [the example inventory](examples/department-inventory.json) for all six record shapes.

Use Control-C to stop Uvicorn and `docker stop aigovkit-demo` to remove the
temporary demo database. Use persistent PostgreSQL storage and backups for real inventory.

## Verify PostgreSQL permissions

Set `AIGOVKIT_POSTGRES_CONNECTOR_URL` using a read-only connection to the
PostgreSQL database you administer. Run:

```sh
python -m aigovkit.verify_postgres actual_agent_role public table_name
```

The command reports schema usage and effective table grants for the supplied
role on one table. Review the JSON alongside declared inventory. The verifier
reads PostgreSQL metadata and makes no changes. See the
[architecture](docs/architecture.md#connectors-and-limits) for its coverage.

## Feature status

| Capability | Current status |
| --- | --- |
| AI tool and agent registry | Owners, allowed purposes and declared capabilities, with PostgreSQL persistence |
| Department access assessment | Policy 1.1.0 checks department, role, business purpose, sensitivity and exact scope. Version 1.0.0 remains available for older clients |
| Agent permission checker | Scans declared connections and flags unneeded, restricted and high-impact actions. Offline JSON import and a read-only PostgreSQL table-grant verifier are available |
| Data classification | Explainable suggestions from structured flags. A human records the applicable classification |
| Risk scoring and reporting | Versioned JSON findings, controls and saved reports. Scores are 25 for low, 50 for medium, and 100 for high |
| Developer integrations | REST and OpenAPI, synthetic examples, and a documented read-only connector contract. Other providers are unimplemented |
| Open-source infrastructure | Docker Compose, PostgreSQL integration tests, CI, MIT licence, contribution and security docs, and issue templates |
| Policy workflow | Save immutable revisions, require independent review and publication, and record acknowledgements against the exact published version |
| Identity and audit | Tenant-scoped keys or OIDC access tokens with named roles. Auditors can view attributable changes across the governance API. Optional browser SSO and managed provisioning are available for compatible issuers |
| Foundation workspace | Dashboard, organisation setup, inventory, readiness, access risk, draft generator, policy library, published policies and proposed control catalogue |

## Run multiple organisations

Configure `AIGOVKIT_TENANTS` with a JSON array of organisations. Each has
an `id` and a `members` array whose entries have a stable `id`, a `role` and a
unique `key`. Generate random keys of at least 32 characters. The configuration
also accepts optional shared `editor_key` and `reader_key` values for existing
API clients. Shared keys cannot act in the named policy workflow.

| Role | Policy workflow |
| --- | --- |
| `editor` | Generate drafts, save revisions and submit their own revisions |
| `reviewer` | Approve or request changes to a revision they did not author |
| `publisher` | Publish the latest approved revision. Must be separate from the draft creator, revision author and approver |
| `reader` | Read policies and acknowledge a published version with a named key |

All named members can acknowledge the current published version. Each key
resolves server-side to one organisation and schema. Run bootstrap before
starting the API, or recreate the Compose API service after updating the
configuration. `AIGOVKIT_API_KEY` is used only when tenant mode is absent.

To load example inventory in tenant mode, use
`python -m aigovkit.bootstrap --tenant YOUR_TENANT --import-json examples/department-inventory.json`.
Existing single-organisation data stays in its legacy schema. Moving it into
a tenant schema requires an operator-managed migration. See
[deployment boundaries](SECURITY.md).

## OIDC access tokens and audit

Use [the OIDC and audit guide](docs/oidc-audit.md) to connect a compatible
issuer, bind subjects to tenant roles and enable the auditor view. AIGovKit
accepts access tokens issued for this API. The workspace also accepts API keys.

## Original risk scoring demo

The [browser form](http://127.0.0.1:8000/) and `POST /assessments` are
a separate, stateless scoring demo. They accept ratings and flags and do not
read governance inventory. Use the versioned API for access simulation.


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

## Checks and contribution

Run `python -m ruff check .` and `python -m pytest -q`. Set
`AIGOVKIT_TEST_DATABASE_URL` to a **disposable** PostgreSQL database to run
the integration tests. They write test records and create a temporary database
role and table. Use a dedicated test database and an account permitted to do this. CI provides its own database.

## Licence

[MIT](LICENSE)

## Governance expansion

See [the expansion guide](docs/governance-expansion.md) for configurable
browser SSO, managed identity and access requests, policy exports, review
schedules, acknowledgement coverage, runtime gate deployment, provider
discovery, the risk register and operational monitoring. Provider connectors
are read-only. Live provider access, external enforcement and telemetry
coverage depend on deployment configuration.

## Reporting and operations extensions

See the [extensions guide](docs/release-extensions.md) for filtered executive
trends, scheduled reviews and incident intake, training, managed Entra group
sync, policy-linked gate rules, external ASGI enforcement, signed audit
exports and audit retention. Provider rollout and telemetry coverage depend
on the deployment.

## Cloud and network discovery

Connect Microsoft 365 / Entra and Google Workspace for read-only application and
managed-device discovery. Add passive network observations to reconcile devices
where a reliable identifier exists. See the [connected discovery guide](docs/connected-discovery.md)
for administrator permissions, scheduled sync, and DHCP, Wi-Fi, switch, NAC,
DNS and proxy metadata intake.

## Repeatable demo and recovery

Use `bash scripts/demo.sh start` for a separate local Compose project on port
8001. Run `bash scripts/demo.sh seed` to load synthetic inventory into that demo.
Seeding replaces matching synthetic IDs. Use `bash scripts/demo.sh stop` to
stop it and retain the demo volume. The generated `.env.aigovkit-demo` contains
local credentials and is ignored by Git.

See the [pilot checklist](docs/pilot-checklist.md) and [backup and restore guide](docs/backup-restore.md).

## Executive reporting, learning and audit export

Create scoped executive snapshots, schedule daily reports and export them
as JSON, CSV, PDF or DOCX. Assign versioned AI literacy lessons with
server-graded quizzes. Forward selected audit metadata to an approved
signed webhook, OpenTelemetry collector, or Splunk HEC endpoint. Editors can
submit courses for independent publication, configure enrolment and refreshers,
and queue risk, vendor, and control reassessments through the existing scheduler.
See [operator setup and feature scope](docs/reporting-learning-export.md).

## Phase 2 provider enforcement

See the [repository audit and backlog](docs/phase2.md) and the
[provider enforcement guide](docs/provider-enforcement.md) for registered
providers, approved model allowlists and gateway decision evidence.

See [controlled containment](docs/controlled-containment.md) for evidence-backed
detections, incident intake, independent approval and temporary gate restrictions.

See [queued notifications](docs/queued-notifications.md) for in-app alerts,
operator-configured SMTP and signed webhooks, retry behaviour, and delivery history.
