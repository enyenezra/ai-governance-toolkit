"""Transactional event selection and delivery queue schema."""

EVENT_PRIORITIES = {
    "security.detected": "attention",
    "incident.alerted": "urgent",
    "containment.execute": "urgent",
    "containment.rollback": "attention",
    "containment.execute_rejected": "attention",
    "access.requested": "attention",
    "policy.submitted": "attention",
    "policy.review_reminder": "info",
    "report.generated": "info",
    "learning.reminder": "info",
    "reassessment.due": "attention",
}
PRIORITIES = ("info", "attention", "urgent")
CHANNELS = ("webhook", "smtp")

SCHEMA = """
CREATE TABLE IF NOT EXISTS notification_outbox (
    event_id bigint NOT NULL,
    channel text NOT NULL CHECK (channel IN ('in_app','webhook','smtp')),
    action text NOT NULL,
    priority text NOT NULL,
    resource_type text NOT NULL,
    resource_id text NOT NULL,
    resource_version integer,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    state text NOT NULL CHECK (state IN ('queued','sending','delivered','dead','cancelled')),
    attempts integer NOT NULL DEFAULT 0,
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_id text,
    lease_until timestamptz,
    last_error text,
    delivered_at timestamptz,
    PRIMARY KEY (event_id, channel)
);
CREATE INDEX IF NOT EXISTS notification_outbox_ready
    ON notification_outbox (next_attempt_at, event_id)
    WHERE state IN ('queued', 'sending');
CREATE TABLE IF NOT EXISTS notification_attempts (
    event_id bigint NOT NULL,
    channel text NOT NULL,
    attempt integer NOT NULL,
    state text NOT NULL,
    error_code text,
    finished_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (event_id, channel, attempt)
);
"""


def enqueue(executor, event_id, action, resource_type, resource_id, version, tenant):
    priority = EVENT_PRIORITIES.get(action)
    if priority is None:
        return
    payload = (event_id, action, priority, resource_type, resource_id, version)
    executor.execute(
        """INSERT INTO notification_outbox
           (event_id,channel,action,priority,resource_type,resource_id,resource_version,state,delivered_at)
           VALUES (%s,'in_app',%s,%s,%s,%s,%s,'delivered',clock_timestamp())""",
        payload,
    )
    if tenant is None:
        return
    row = executor.execute(
        "SELECT body FROM foundation_documents WHERE kind='notification_settings' AND id='default'"
    ).fetchone()
    if not row:
        return
    config = row[0] if not isinstance(row, dict) else row["body"]
    if PRIORITIES.index(priority) < PRIORITIES.index(config["minimum_priority"]):
        return
    if config["events"] and action not in config["events"]:
        return
    for channel in config["channels"]:
        executor.execute(
            """INSERT INTO notification_outbox
               (event_id,channel,action,priority,resource_type,resource_id,resource_version,state)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'queued')""",
            (event_id, channel, *payload[1:]),
        )
