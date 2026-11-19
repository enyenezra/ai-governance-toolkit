# Security

## Report a vulnerability

Use GitHub's private vulnerability reporting if it is enabled, or contact a
repository maintainer privately. Include the affected version, impact and a
minimal synthetic example. Keep credentials and organisational data out of
the report.

## Deployment boundaries

Run the API on a trusted network behind TLS. For shared deployments, provision unique, randomly generated tenant reader
and editor keys. Editors can change governance records. The API chooses the
schema using the verified key. It ignores tenant identifiers supplied by
clients. Store keys and the database connection string in a secret manager
and restart the service after rotation. Browser sign-in keeps the key in
memory and clears it on reload. Shared keys provide role separation but do
not identify individual users. Database administrator or API compromise can
expose all schemas. Use separate instances and database credentials where
that infrastructure-level boundary is required.
Avoid logging request headers and bodies at your proxy.

Use a dedicated PostgreSQL runtime account with only the required table read
and write permissions. Use a separate operator connection for initial schema
creation. Protect backups and restrict access to the API and the database.
Set request size and rate limits at the proxy for exposed deployments.

Inventory represents operator declarations. Keep sensitive data contents out
of the registry. Recommendations have no enforcement effect and need a human
decision. The health endpoint, stateless demo and OpenAPI schema are unauthenticated.

Reports contain assessment inputs and outputs. Apply your inventory retention
and backup policies to reports. For the PostgreSQL verifier, use a separate
read-only login, scope its database access, set TLS verification as appropriate,
and avoid placing its connection URL in shell history or logs.

Policy review uses distinct named credentials and stable member IDs. Configure
those IDs for separate individuals and keep a private provisioning record.
See [policy review](docs/policy-review.md) for separation and audit boundaries.

[OIDC access-token verification](docs/oidc-audit.md) trusts one configured
issuer and API audience. Provision its public signing keys through the
deployment and avoid logging bearer credentials. Remove subject bindings
when users leave. The audit feed is application-level evidence and relies
on PostgreSQL access controls and backups.

Run the [runtime gate](docs/governance-expansion.md#agent-guardrails-and-monitoring)
on a trusted HTTPS boundary. Scope gateway and observer credentials to their
single purpose, keep those credentials out of browsers, and fail closed when
the gate is unavailable. External services must route protected operations
through the gate for its decisions to take effect.

For [model gateway enforcement](docs/provider-enforcement.md), expose only the
wrapped routes and bind each to its fixed upstream. API decisions cannot
protect direct access to the upstream. Keep provider credentials in the
protected application and scope its AIGovKit key to the gateway role.

Deploy [outbound notification destinations](docs/queued-notifications.md) via
trusted operator configuration. Use scoped credentials, restrict egress to
approved receivers, and validate webhook signatures and timestamps at the
receiver. Use test destinations before enabling production delivery.
