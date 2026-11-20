import json

import httpx
import pytest

from aigovkit import audit_transports
from aigovkit.notification_delivery import AuditSink, DeliveryFailure


@pytest.mark.parametrize("transport", ["audit_otlp", "audit_splunk"])
def test_native_audit_transport_wire_format_and_retry(monkeypatch, transport):
    token = "test-credential"
    batch = {
        "id": "batch-key",
        "batch": {
            "events": [
                {
                    "event_id": 4,
                    "occurred_at": "2026-11-20T08:00:00.123456+00:00",
                    "action": "security.detected",
                },
            ]
        },
    }
    target = AuditSink(url="https://collector.example.invalid/logs", token=token)
    replies = iter(
        [
            httpx.Response(503),
            httpx.Response(200, json={} if transport == "audit_otlp" else {"code": 0}),
            httpx.Response(
                200,
                json={"partialSuccess": {"rejectedLogRecords": "1"}}
                if transport == "audit_otlp"
                else {"code": 6},
            ),
        ]
    )

    def receive(request):
        assert request.url == target.url
        assert request.headers["content-type"] == "application/json"
        body = json.loads(request.content)
        if transport == "audit_otlp":
            assert request.headers["authorization"] == f"Bearer {token}"
            record = body["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
            assert record["timeUnixNano"].endswith("123456000")
            assert record["body"] == {"stringValue": "security.detected"}
            assert record["attributes"][0]["value"] == {"intValue": "4"}
        else:
            assert request.headers["authorization"] == f"Splunk {token}"
            assert body["event"] == {
                **batch["batch"]["events"][0],
                "batch_key": "batch-key",
            }
        return next(replies)

    client = httpx.Client
    monkeypatch.setattr(
        audit_transports.httpx,
        "Client",
        lambda **options: client(transport=httpx.MockTransport(receive), **options),
    )
    with pytest.raises(DeliveryFailure) as transient:
        audit_transports.deliver_audit(target, transport, batch)
    assert transient.value.retry
    audit_transports.deliver_audit(target, transport, batch)
    with pytest.raises(DeliveryFailure) as rejected:
        audit_transports.deliver_audit(target, transport, batch)
    assert not rejected.value.retry
    assert rejected.value.code == "audit_sink_partial_or_rejected"
