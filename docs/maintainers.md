# Maintainer guide

Review tenant scoping and credential handling for every API or storage change.
Require passing CI, test database isolation with synthetic fixtures, and check
the Compose onboarding flow before cutting a release. Publish release notes
from the changelog, list tested deployment modes and link to the security policy.
MIT keeps terms permissive and matches the existing project licence.

Use GitHub Discussions for questions and design proposals where enabled. Use
issues for reproducible bugs and accepted work. Label well-scoped, documented
starter tasks `good first issue` and larger contributor tasks `help wanted`.
Keep vulnerabilities private using the process in SECURITY.md.

## Initial contributor workstreams

1. Backend security: add policy invariants and threat-model regression cases;
   cover tenant scoping and immutable decision records.
2. Integrations: document read-only Entra permission requirements and implement
   fixture-backed normalisation before requesting live credentials.
3. Frontend: test keyboard navigation, add a safe draft revision workflow,
   and keep unavailable publication controls out of the interface.
