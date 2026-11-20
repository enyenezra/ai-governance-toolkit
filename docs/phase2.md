# Enterprise expansion audit and Sprint 1–2 handover

## Repository audit

- **Network collector.** `aigovkit.passive_collector` reads normalised JSON Lines
  and sends authorised passive device and domain observations to AIGovKit. It
  does not capture packets or export SIEM events. It exits on delivery failure.
  There is no durable collector spool or outbound exporter queue.
- **Scheduler.** `aigovkit.scheduled_jobs` is a bounded-time HTTP client invoked
  by an external scheduler. It runs reminders, incident intake and discovery.
  Some handlers deduplicate their own results. The CLI owns no recurrence,
  timezone schedule, job database, retry queue, leader election or durable run
  history. Retain the CLI as the dispatcher and add job-specific durability
  where required.
- **Enforcement.** The existing gate applies versioned exact-scope rules,
  deny precedence, rollback and suspension. Its ASGI adapter checks fixed
  route scopes. It has no native provider administration or JSON model check.
- **Incidents.** The scheduled worker groups submitted denials and errors.
  It deduplicates opened cases by agent and UTC day. Detection coverage depends
  on ingested signals. Publisher-controlled gate suspension is available.
- **Reporting.** Executive trends aggregate saved reports by date, risk,
  department, system and decision. Policy exports support Markdown, PDF and
  DOCX. Audit exports are signed. Board packs and scheduled reporting do not
  exist yet.
- **Notifications and learning.** Review reminders are persisted for the
  workspace. No outbound queue or channel worker exists. Training has two
  versioned courses and completion attestations, with no graded assessments.

## Implemented slice

The provider registry stores tenant-scoped metadata and a named gateway
binding. It declares capabilities separately for each provider. An editor
registers the provider and a different publisher deploys an explicit model
allowlist. Decisions combine the allowlist with the existing agent and
asset guardrail. An ASGI wrapper checks the model in a bounded JSON body
before allowing the protected route to run. AIGovKit receives only model ID
and the operator-defined scope. Deployments are versioned and can roll back.
Verification records an observed allow and deny against the current version.

This slice uses the existing `foundation_documents` table, tenant schemas
and audit writes. It introduces new document kinds without a schema migration.
Existing gate routes and clients remain available. The provider registry stores
no upstream access secrets. Operate provider credentials in the protected
gateway or application. The registry endpoint is descriptive and is never
contacted by the AIGovKit API.

## Backlog

1. Add provider-specific contracts and prove live enforcement on a test
   gateway. Add explainable warning and approval where supported. Add native
   provider controls only after capability, scope and rollback verification.
2. Add telemetry-backed detections with provenance. Build a versioned approval
   and expiry workflow for reversible gate containment before automation.
3. Add a tenant-scoped transactional notification outbox, delivery workers,
   retry ceilings, deduplication, and operator-managed SMTP and webhook targets.
   Reuse the existing scheduled dispatcher for bounded job starts.
4. Add board reports and snapshots from persisted, documented metrics. Include
   date and department scope and distinguish zero from missing evidence.
5. Add versioned pathways, assessments, assignments and refresher evidence.
6. Add a durable outbound event exporter, receiver authentication, backpressure,
   and failure replay. Validate with a dedicated test destination before rollout.

Only the provider gateway slice is in this change. Live provider deployments and
the remaining roadmap require subsequent work and approved test environments.
