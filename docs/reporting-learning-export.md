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

## Governance automation

Executive report version 1.1 adds live snapshot counts from the risk, access,
incident, vendor, control, policy and training records. Each source indicates
whether it has records. Policy acknowledgements count receipts for the latest
published versions. Existing snapshots keep their original metrics. Department
filters apply to historical assessments.

Named editors can create and edit course drafts in **Training courses**. Named
publishers can review the current draft and publish it from the same page.
Assignments retain the published version they started with. The learner
catalogue excludes the answer key. Custom courses currently use one graded
question and two choices.

Editors can create an enrolment rule for a published course version, a member
role and optionally a managed directory group. A scheduler run assigns up to
100 eligible members. It skips open assignments and starts refreshers after
the specified interval from the last completion. Set the rule to disabled to
stop future enrolment. Published course versions are explicit in each rule.
A new version requires an editor to update the rule. Enrolment uses the
current directory records available to AIGovKit.

The scheduler also queues risk treatment reviews and vendor reassessments
when a source due date arrives. It queues control reviews 90 days after the
most recent check. A source record and due date produce one task. Reviewers
resolve the underlying work in the source registers and advance the due date
or record newer evidence there. Tasks are historical evidence that a review
became due. The scheduler does not change permissions or risk decisions.

## Native audit sinks

Configure one audit destination per tenant in
`AIGOVKIT_NOTIFICATION_DESTINATIONS`. The ordinary notification webhook can
be configured separately. Credentials come from the deployment secret manager.

| Key | URL | Credential |
| --- | --- | --- |
| `audit_webhook` | Approved signed webhook endpoint | `signing_key` |
| `audit_otlp` | HTTPS OTLP/HTTP JSON logs endpoint, typically ending in `/v1/logs` | Optional bearer `token` |
| `audit_splunk` | HTTPS Splunk HEC endpoint ending in `/services/collector/event` | HEC `token` |

OpenTelemetry exports audit logs over OTLP/HTTP JSON. It records rejected
log records as a terminal failure so a partially accepted batch is not
replayed automatically. Splunk uses HEC event ingestion with standard token
authentication and checks the response code. Use a token without indexer
acknowledgements. HEC acceptance does not establish indexing. Receivers can
use the stable batch key and event ID to identify duplicate deliveries.
Exercise a destination in a pilot before connecting it to production. A
transport change applies to new batches. Existing batches retain the selected
transport and can be downloaded for manual recovery if delivery fails.

- [OpenTelemetry OTLP specification](https://opentelemetry.io/docs/specs/otlp/)
- [Splunk HTTP Event Collector setup](https://help.splunk.com/en/splunk-enterprise/get-data-in/collect-http-event-data/set-up-and-use-http-event-collector-in-splunk-web)
