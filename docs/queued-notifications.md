# Queued governance notifications

Run the normal database bootstrap when upgrading. It creates an outbox and
an attempt history in the authenticated tenant's PostgreSQL schema. The
governance operation, audit event and notification enqueue share one
transaction. Selected events always appear in the tenant's Notifications
workspace. Older audit events are not replayed.

## Configure outbound delivery

Set `AIGOVKIT_NOTIFICATION_DESTINATIONS` through the deployment secret
manager. Configure only destinations approved to receive governance alerts.
This example uses placeholders.

```json
{
  "your-tenant": {
    "webhook": {
      "url": "https://receiver.example.invalid/aigovkit",
      "signing_key": "REPLACE_WITH_AT_LEAST_32_RANDOM_CHARACTERS"
    },
    "smtp": {
      "host": "smtp.example.invalid",
      "port": 465,
      "sender": "alerts@example.invalid",
      "recipient": "governance@example.invalid",
      "username": "service-user",
      "password": "DEPLOYMENT_SECRET"
    }
  }
}
```

The SMTP transport uses TLS from connection start and sends to one configured
mailbox or distribution address. The webhook uses HTTPS and does not follow
redirects. A named editor uses **Outbound preferences** to enable configured
channels, select events and set a minimum priority. Priorities are routing
defaults for event types and do not change incident severity. Destinations
and credentials are supplied by operators and are excluded from API responses.

Run the existing `python -m aigovkit.scheduled_jobs` command with a named
scheduler key. It invokes `POST /v1/notifications/run` once per run and sends
up to eight eligible jobs. A disabled preference cancels eligible queued
deliveries when they are processed. If an operator removes a destination
without first changing the preferences, its queued items fail visibly.

## Delivery and verification

A job is unique by tenant, audit event and channel. Workers claim using
`FOR UPDATE SKIP LOCKED` and a two-minute lease. Transient failures retry
after delays of 30, 60, 120 and 240 seconds. Permanent failures and exhausted
jobs enter the dead-letter state. Finished attempts remain inspectable at
`GET /v1/notifications/{event_id}/attempts` by a named editor, publisher or
auditor. An expired lease can be recovered. SMTP and webhook transport are
at least once if a worker loses its acknowledgement after handing off an event.

A webhook receiver should reject stale timestamps, calculate HMAC-SHA256
over the literal string `v1.<X-AIGovKit-Timestamp>.` followed by the exact body,
and compare its result to `X-AIGovKit-Signature` with a constant-time
comparison. Deduplicate effects by `Idempotency-Key`. SMTP uses a stable
Message-ID on retries. Message acceptance by the mail server does not
establish recipient delivery or read status. Use a non-production recipient
or receiver for a pilot.

Outbound messages contain an opaque notification ID, type, priority and
timestamp. Policy text, prompts, resources, identities, raw provider errors
and credentials are excluded. The workspace shows authorised resource
references and delivery status. This version has no native Teams or Slack
templates, quiet hours, automatic escalation, or retention policy for the
outbox. Provision receivers through approved infrastructure.
