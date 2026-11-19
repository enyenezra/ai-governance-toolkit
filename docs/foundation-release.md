# Foundation release candidate

The foundation adds an authenticated workspace, configuration-based tenant
scoping, organisation onboarding, saved readiness results, and deterministic
generation for 12 policy templates. It links draft clauses to proposed controls
and uses the existing risk engine and report store. The earlier scoring demo,
API routes, and bootstrap commands remain available.

Readiness assigns two points to in-place controls, one to partial controls and
zero to missing controls. It rounds the percentage obtained from the fixed
maximum score and lists missing controls before partial ones. Version 1.0.0
records self-reported answers. It supports prioritisation and provides no
compliance determination. The questionnaire has no branching in this release.

The workspace follows the supplied dark sidebar and purple accent. It provides
eight views backed by persisted records or versioned catalogues. It does not
include the editor, approvals, live discovery, incidents or deployment screens.
The dashboard uses registered counts capped at 100 per kind and the latest ten
reports. It does not infer policy coverage or active usage from registration.

## Verification

- Ruff, JavaScript syntax checks and 36 pytest tests passed with PostgreSQL 16.
- The PostgreSQL tests verify that a key from one tenant cannot read another
  tenant's profile, inventory, reports, readiness history or drafts. Reader
  keys cannot write, and missing prerequisites fail before draft creation.
- A local Compose and Chromium smoke test covered sign-in, onboarding,
  inventory search, readiness, draft generation and retrieval, risk
  assessment, mobile layout width and sign-out.
- The test client emits an HTTPX deprecation warning.

The candidate is ready for evaluation in local or controlled self-hosted
deployments. Shared API keys are a foundation and do not provide per-user
accountability. PostgreSQL schema scoping protects API requests and is not a
boundary against a compromised service account. Existing records need an
operator-managed migration when switching to tenant mode. For deployment
boundaries see SECURITY.md.

The next milestone is per-user identity, policy draft revision and independent
review and approval. Add audit events before enabling publication or connector
write-back. Use the foundation PR for review before tagging a release.
