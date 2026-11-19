# Repository audit and release plan

Baseline: `main` at `9f2e93f`. The repository has one FastAPI service, a
stateless scoring page, Pydantic request contracts, psycopg-backed JSONB inventory
and reports, deterministic access policies, an offline JSON importer and a
PostgreSQL grant verifier. It has pytest, Docker Compose and PostgreSQL CI.
The existing API provides useful scoped simulations and saved recommendations.
It has no organisation onboarding, readiness workflow, policy authoring, or shared
deployment isolation. The original shared key grants read and write access.

## Architecture for the foundation

Use one service and one deployable image. Keep FastAPI as the API boundary and
serve a small same-origin web workspace with the supplied dark navy and purple
design as its reference. Retain the existing demo at its original route. This
keeps installation compatible with the existing Compose workflow and avoids a
second runtime before the product workflows stabilise. Extract independently
versioned packages only when they have distinct consumers. Evaluate React and
Next.js before the larger editing and analytics work.

Use PostgreSQL schemas to namespace each configured tenant. A key resolves
server-side to one schema and role. The API accepts no tenant override. Staff
receive reader or editor keys provisioned by the deployment operator. A legacy
single-organisation mode preserves existing data and callers. Future OIDC will
replace shared keys with identities and verified organisation membership.

Keep the existing inventory and report tables. Add a foundation document table
for an organisation profile, saved readiness results and immutable generated
policy drafts. Store scoring and template versions alongside the saved inputs
and outputs. Bootstrap schema changes before serving requests.

## API and roles

| Resource | Reader | Editor |
| --- | --- | --- |
| Profile, inventory, reports and readiness history | View | View and create or update as supported |
| Template and control catalogues | View | View |
| Policy drafts | View | Generate and save |
| External enforcement, approval and publication | Unavailable | Unavailable |

The tenant comes from authentication even on pre-existing inventory and report
routes. The generated OpenAPI document is the request and response contract.

## Threat model and verification

Protect organisation metadata, keys, policy drafts and decision history. The
trust boundary is the API, database and operator who provisions keys. Test
cross-tenant requests, guessed draft IDs, read-only writes, missing credentials,
and invalid input. Test schema isolation with live PostgreSQL and verify
deterministic scoring and clause generation. Use a localhost-only Compose demo
and test a complete workflow over HTTP. Operator or database compromise exceeds
this boundary. This release requires TLS termination, proxy limits, backups and
a hardened identity layer before enterprise exposure.

## Prioritised backlog

1. Foundation: tenant-scoped authentication, organisation onboarding, inventory,
   readiness, draft policy generation, control catalogue, risk and web workspace.
2. Governance workflows: per-user OIDC, approval and publication transitions,
   versioned editing, access reviews, evidence retention, and document exports.
3. Security workflows: incident timelines, shadow AI intake, audit events,
   policy simulation, and explicit deployment and verification contracts.
4. Integrations: prioritise read-only Entra, Microsoft 365 and MCP discovery,
   then assess low-risk enforcement targets individually.

Assess OPA when a deployable control contract exists. Require independent
deployment evidence before labelling a rule enforced. Keep jurisdictional
requirements as reviewed references and applicability decisions. Scores serve
prioritisation and provide no certification.
