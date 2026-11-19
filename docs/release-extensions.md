# Reporting, automation and enforcement extensions

These workflows build on the existing tenant-scoped API. The standard Compose
setup still works. Third-party rollout requires credentials and an approved
deployment target. No external account is modified by default.

## Executive reporting and readiness

Use the dashboard's trend filters or `GET /v1/executive-report` to query saved
risk assessments by trailing date window, department, tool or agent, risk and
decision. Trends count saved assessments per UTC day. Inventory totals cover
the whole authenticated organisation. Readiness adds identity lifecycle,
evidence, retention and supplier exit questions as applicable. Draft generation
adds review guidance for declared sector and jurisdiction. It makes no legal
applicability determination.

## Scheduled reviews, incident alerts and training

Configure a named `scheduler` key and supply `AIGOVKIT_JOBS_API` (trusted HTTPS
API base) and `AIGOVKIT_JOBS_KEY`. Set `AIGOVKIT_INCIDENT_OWNER` on the server to a
named editor in the scheduler’s tenant. Schedule
`python -m aigovkit.scheduled_jobs` through your deployment scheduler.
Jobs queue one in-product reminder per due published revision and open an
incident after ten reported runtime errors or denials for an agent in one UTC
day. The operations are repeat-safe and publish no email or external messages.
Containment remains publisher-controlled at the gate.

The Training screen includes two versioned courses. Assign a course by setting
`course_id` on a training register record. The assigned named member can
self-attest completion. The evidence identifies the course and version. This
does not verify comprehension.

## Discovery and group synchronisation

Discovery supports `--pages 1..25` where the provider returns supported
continuations. Review and approve an observation before calling
`POST /v1/discovery/{id}/promote` with a named editor and an accountable
`owner`. Promotion creates a tool record and leaves the source unchanged.

Use `python -m aigovkit.entra_sync mapping.json` to preview changes. The
mapping contains `groups` from AIGovKit group IDs to Entra group GUIDs, and
`members` from existing AIGovKit member IDs to verified Entra user GUIDs.
Set `AIGOVKIT_ENTRA_TOKEN` to a scoped Graph read credential,
`AIGOVKIT_SYNC_API` to the trusted HTTPS API base and `AIGOVKIT_SYNC_KEY`
to a named identity administrator key. Use `--apply` only after verifying
the mappings. Schedule that same command for repeat sync. Changes affect
only the mapped groups of active managed members and use version checks.
Provider access and consent must be validated by the operator.
[Graph transitive group membership](https://learn.microsoft.com/en-us/graph/api/group-list-transitivemembers?view=graph-rest-1.0)

## Rules and external enforcement

Deploy up to 20 exact-scope rules per agent via `revision_ids`. The previous
single rule field stays supported. A matching deny takes precedence, and
unmatched requests are denied. For policy-driven enforcement, set
`policy_clause` on a proposed rule with `draft_id`, `version` and
`clause_id`. Deployment rejects a stale linkage, and a later publication
invalidates an older linked allow rule.

Wrap a dedicated ASGI application with `aigovkit.gate_adapter.EnforcedRoutes`.
The operator maps each protected HTTP method and path to a fixed simulation
scope. The adapter only dispatches a mapped request after an authenticated
allow, and blocks when the gate denies or fails. Protect the service so clients
cannot bypass the wrapper. The adapter sends scope metadata, not request
contents. No upstream IAM permissions are changed.

## Audit export and retention

Mount an Ed25519 PEM signing key and set `AIGOVKIT_AUDIT_SIGNING_KEY_FILE`.
A named auditor can fetch `GET /v1/audit-export`. It signs a bounded event page. Use `before` with the last event ID
to export earlier pages. Save the JSON and verify it using
`python -m aigovkit.verify_audit export.json trusted-public-key.pem`.
Distribute the public key through a trusted channel. The signature detects
changes after export. Database administrators can still change stored events.

`POST /v1/retention/audit` accepts `days` and defaults to a dry run. Set
`apply` only after reviewing counts, exports, backups and retention
requirements. An operator must set `AIGOVKIT_ENABLE_AUDIT_PRUNE=yes` before
a named auditor can delete eligible rows. Each deletion batch is capped at
5,000 rows and records a new audit event. Other registers are unaffected.
