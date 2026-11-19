# AIGovKit v0.1.0

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

## Foundation workspace

Open [the workspace](http://127.0.0.1:8000/workspace) after starting the demo.
Sign in with the configured key. Set the organisation profile, register an AI
application or agent, and complete the readiness questionnaire. Generate one
of 12 saved policy drafts and review its clauses and proposed controls in the
policy library. The dashboard uses saved assessments and registered inventory.
The original scoring demo remains available at `/`.

Named editors and independent reviewers can revise, submit and review drafts.
A separate publisher can publish an approved revision inside the organisation.
Named members can acknowledge a specific published version. See the
[policy review](docs/policy-review.md) and [publication](docs/policy-publication.md) guides. See the
[foundation plan](docs/foundation-plan.md) for the baseline audit, security
model and release roadmap.

## Run a local demo

The full demo requires Docker Compose and a terminal. Run these commands from
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

### Run the API directly

Use Python 3.13 and Docker with its daemon running. Run these commands from the
repository root in the same terminal. The database and API bind to loopback.
Use a fresh container and synthetic data for the demo.

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt

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
| `GET /health` | Check process liveness |

For example, register an asset with
`PUT /v1/inventory/asset/handbook` and a JSON body of
`{"kind":"asset","id":"handbook","name":"Staff handbook","classification":"internal"}`.
See [the example inventory](examples/department-inventory.json) for all five record shapes.

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

| Capability | v0.1.0 status |
| --- | --- |
| AI tool and agent registry | Owners, allowed purposes and declared capabilities, with PostgreSQL persistence |
| Department access assessment | Policy 1.1.0 checks department, role, business purpose, sensitivity and exact scope. Version 1.0.0 remains available for older clients |
| Agent permission checker | Scans declared connections and flags unneeded, restricted and high-impact actions. Offline JSON import and a read-only PostgreSQL table-grant verifier are available |
| Data classification | Explainable suggestions from structured flags. A human records the applicable classification |
| Risk scoring and reporting | Versioned JSON findings, controls and saved reports. Scores are 25 for low, 50 for medium, and 100 for high |
| Developer integrations | REST and OpenAPI, synthetic examples, and a documented read-only connector contract. Other providers are unimplemented |
| Open-source infrastructure | Docker Compose, PostgreSQL integration tests, CI, MIT licence, contribution and security docs, and issue templates |
| Identity, approvals and audit | Tenant-scoped shared keys and named editor and reviewer keys. Policy decisions record an actor and rationale. OIDC and cross-module audit logging are planned |
| Foundation workspace | Dashboard, organisation setup, inventory, readiness, access risk, draft generator and library, and proposed control catalogue |

## Run multiple organisations

Configure `AIGOVKIT_TENANTS` with a JSON array of objects containing `id`,
`editor_key` and an optional `reader_key`. Generate a different random key of
at least 32 characters for each role and organisation. Run bootstrap before
starting the API, or recreate the Compose API service after updating the
configuration. Each key resolves to one organisation and schema. Reader keys
can view records. Editor keys can write records and run simulations.
The legacy key works only when the tenant configuration is absent.

To load example inventory in tenant mode, use
`python -m aigovkit.bootstrap --tenant YOUR_TENANT --import-json examples/department-inventory.json`.
Existing single-organisation data stays in its legacy schema. Moving it into
a tenant schema requires an operator-managed migration. See
[deployment boundaries](SECURITY.md).

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
