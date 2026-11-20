"""Native outbound audit transports for OTLP/HTTP and Splunk HEC."""

import json
from datetime import UTC, datetime

import httpx

from aigovkit.notification_delivery import DeliveryFailure


def otlp_payload(batch, batch_key):
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    records = []
    for event in batch["events"]:
        elapsed = datetime.fromisoformat(event["occurred_at"]) - epoch
        nanos = (
            elapsed.days * 86400 + elapsed.seconds
        ) * 10**9 + elapsed.microseconds * 1000
        records.append(
            {
                "timeUnixNano": str(nanos),
                "body": {"stringValue": event["action"]},
                "attributes": [
                    {
                        "key": "aigovkit.event_id",
                        "value": {"intValue": str(event["event_id"])},
                    },
                    {"key": "aigovkit.batch_key", "value": {"stringValue": batch_key}},
                ],
            }
        )
    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "aigovkit"}}
                    ]
                },
                "scopeLogs": [
                    {"scope": {"name": "aigovkit.audit"}, "logRecords": records}
                ],
            }
        ]
    }


def deliver_audit(destination, transport, event):
    batch = event["batch"]
    if transport == "audit_otlp":
        content = json.dumps(otlp_payload(batch, event["id"]))
        credentials = "Bearer"
        retryable = {429, 502, 503, 504}
    else:
        content = "\n".join(
            json.dumps(
                {
                    "time": datetime.fromisoformat(record["occurred_at"]).timestamp(),
                    "source": "aigovkit",
                    "sourcetype": "_json",
                    "event": {**record, "batch_key": event["id"]},
                }
            )
            for record in batch["events"]
        )
        credentials = "Splunk"
        retryable = {429, 500, 502, 503, 504}
    headers = {"Content-Type": "application/json"}
    if destination.token:
        headers["Authorization"] = (
            f"{credentials} {destination.token.get_secret_value()}"
        )
    try:
        with httpx.Client(timeout=8, follow_redirects=False, trust_env=False) as client:
            response = client.post(
                destination.url, content=content.encode(), headers=headers
            )
    except httpx.RequestError:
        raise DeliveryFailure("audit_sink_unreachable", retry=True) from None
    if response.status_code != 200:
        raise DeliveryFailure(
            "audit_sink_rejected", retry=response.status_code in retryable
        )
    try:
        reply = response.json()
        if transport == "audit_otlp":
            accepted = (
                int(reply.get("partialSuccess", {}).get("rejectedLogRecords", 0)) == 0
            )
        else:
            accepted = reply.get("code") == 0
    except (ValueError, AttributeError, TypeError):
        raise DeliveryFailure("audit_sink_invalid_response", retry=False) from None
    if not accepted:
        raise DeliveryFailure("audit_sink_partial_or_rejected", retry=False)
