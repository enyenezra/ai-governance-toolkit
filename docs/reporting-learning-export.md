# Executive reports, learning and audit export

These features use the existing PostgreSQL tenant schemas. Run the normal
database bootstrap when upgrading. The workspace adds **Executive reports**
for named editors, publishers and auditors, alongside the existing **Training
courses** page. Scheduler credentials can run jobs but cannot read reports,
answer quizzes or configure destinations.

## Executive reports

A named editor can generate a snapshot in the workspace or submit
`POST /v1/board-reports` with `start` and `end` in YYYY-MM-DD format. The range
is inclusive in UTC and can span up to 366 days. Use the optional
`department` field to filter assessments to an exact department ID and
`template` to select board, risk, security, or operations. Risk trends
count saved assessments. Organisation totals reflect the current state
at generation time. Reports omit organisation totals for a selected
department or the risk template. Coverage fields distinguish an empty
assessment history from an actual finding count.

Named governance roles can download saved snapshots as JSON, CSV, PDF
or DOCX. A named editor can configure daily generation through the workspace
or `PUT /v1/board-reports/schedule`. If enabled, the first scheduler run
each UTC day saves a single report for the configured number of complete
days ending yesterday. Reruns for that UTC date return the existing report.

## Learning

A named editor assigns a versioned introductory lesson to an active named
member and sets a due date. Learners open their own assignments in
**Training courses** and answer the quiz. Grading runs on the server,
records the latest score, and preserves the first successful completion.
A named editor or auditor can review the tenant's assignment records.
The existing self-attested training and published policy acknowledgement
workflows are still available.

The scheduler emits one notification per incomplete assignment when
the due date arrives. Reminder delivery follows the tenant's existing
notification preferences. Outbound delivery targets the configured
governance recipient or webhook. The course library is bundled with the
application. Publish edits under a new course ID and retain existing
versions so earlier assignments remain gradable.

## Audit export

The existing network discovery API receives device observations from approved
collectors. The audit exporter is an outbound workflow that sends selected
governance event metadata already stored in AIGovKit.

Set `audit_webhook` for an approved tenant under
`AIGOVKIT_NOTIFICATION_DESTINATIONS`. Use an HTTPS destination and a signing
key of at least 32 characters, supplied via your deployment secrets.
The audit sink uses its own destination settings and is enabled by that
operator configuration. It has separate routing from regular webhooks.
The receiver verifies the timestamp and signature and deduplicates by
`Idempotency-Key`, as described in [queued notifications](queued-notifications.md).

Each run queues up to 100 selected records, with at most 10 batches queued
or sending at one time. It includes the event identifier, event type and
time, excluding actor identifiers, resources and event content. It processes
matching events that remain in the audit log, including events logged before
the export was enabled. A durable per-event receipt prevents repeat
batching and an immutable batch supports retry with a stable envelope.
Use a dedicated destination per tenant to keep streams separate.

Named editors and auditors can see recent delivery attempts in the workspace
or at `GET /v1/audit-exporter/history`. For a terminal failure, inspect the
failure, then retrieve the affected saved batch at
`GET /v1/audit-exporter/batches/{batch_id}/json` or the equivalent CSV
route for approved manual recovery. Retention for the audit log and saved
export batches should be considered separately.

## Deployment and remaining scope

Use the existing `python -m aigovkit.scheduled_jobs` command with a named
scheduler key. The application does not start its own clock. Run it
through your deployment scheduler often enough to drain the shared
delivery queue. You need an approved destination and a live pilot to
verify delivery in your environment.

The initial reporting templates use structured application records and
cover a limited set of metrics. Learning is an introductory catalogue
with manual assignments, one graded question per course and a due-date
reminder. Automatic role or risk-based enrolment, configurable refreshers,
in-product course authoring, native SIEM and OpenTelemetry adapters, and
additional recurring reassessment jobs remain future work.
