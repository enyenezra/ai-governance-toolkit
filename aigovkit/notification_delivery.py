"""Operator-configured SMTP and signed webhook transports."""

import hashlib
import hmac
import json
import os
import smtplib
import ssl
import time
from email.message import EmailMessage
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from pydantic import Field, SecretStr, StringConstraints, TypeAdapter, ValidationError

from aigovkit.models import Identifier, StrictModel

Secret = Annotated[SecretStr, Field(min_length=32)]
Mailbox = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$"),
]


class Webhook(StrictModel):
    url: str
    signing_key: Secret


class SMTP(StrictModel):
    host: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9.-]{1,253}$")]
    port: int = Field(default=465, ge=1, le=65535)
    sender: Mailbox
    recipient: Mailbox
    username: str | None = None
    password: SecretStr | None = None


class Destinations(StrictModel):
    webhook: Webhook | None = None
    audit_webhook: Webhook | None = None
    smtp: SMTP | None = None


class DeliveryFailure(Exception):
    def __init__(self, code: str, *, retry: bool):
        self.code = code
        self.retry = retry


def configured(tenant: str | None) -> Destinations:
    if tenant is None:
        return Destinations()
    try:
        tenants = TypeAdapter(dict[Identifier, Destinations]).validate_json(
            os.getenv("AIGOVKIT_NOTIFICATION_DESTINATIONS", "{}")
        )
    except ValidationError as error:
        raise ValueError("Invalid notification configuration.") from error
    result = tenants.get(tenant, Destinations())
    for destination in (result.webhook, result.audit_webhook):
        if not destination:
            continue
        uri = urlsplit(destination.url)
        if (
            uri.scheme != "https"
            or not uri.hostname
            or uri.username
            or uri.password
            or uri.query
            or uri.fragment
        ):
            raise ValueError("Use a trusted HTTPS webhook URL.")
    if result.smtp and bool(result.smtp.username) != bool(result.smtp.password):
        raise ValueError("SMTP credentials must be configured together.")
    return result


def packet(tenant: str, item: dict) -> dict:
    identifier = hashlib.sha256(
        f"{tenant}:{item['event_id']}:{item['channel']}".encode()
    ).hexdigest()
    return {
        "id": identifier,
        "schema": "aigovkit.notification.v1",
        "event": item["action"],
        "priority": item["priority"],
        "occurred_at": item["created_at"].isoformat(),
    }


def signed_headers(
    destination: Webhook, payload: bytes, identifier: str, sent_at: str
) -> dict:
    signature = hmac.new(
        destination.signing_key.get_secret_value().encode(),
        b"v1." + sent_at.encode() + b"." + payload,
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "Idempotency-Key": identifier,
        "X-AIGovKit-Timestamp": sent_at,
        "X-AIGovKit-Signature": "v1=" + signature,
    }


def deliver_webhook(destination: Webhook, event: dict) -> None:
    body = json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
    headers = signed_headers(destination, body, event["id"], str(int(time.time())))
    try:
        with (
            httpx.Client(timeout=8, follow_redirects=False, trust_env=False) as client,
            client.stream(
                "POST", destination.url, content=body, headers=headers
            ) as response,
        ):
            code = response.status_code
    except httpx.HTTPError:
        raise DeliveryFailure("webhook_unavailable", retry=True) from None
    if not 200 <= code < 300:
        raise DeliveryFailure(
            f"webhook_{code}", retry=code in {408, 429} or code >= 500
        )


def deliver_smtp(destination: SMTP, event: dict) -> None:
    message = EmailMessage()
    message["From"] = destination.sender
    message["To"] = destination.recipient
    message["Subject"] = "AIGovKit governance notification"
    message["Message-ID"] = f"<{event['id']}@{destination.sender.rsplit('@', 1)[1]}>"
    message.set_content(
        f"Event: {event['event']}\nPriority: {event['priority']}\n"
        f"Notification: {event['id']}\nOpen your AIGovKit workspace for details.\n"
    )
    try:
        with smtplib.SMTP_SSL(
            destination.host,
            destination.port,
            timeout=8,
            context=ssl.create_default_context(),
        ) as client:
            if destination.username and destination.password:
                client.login(
                    destination.username, destination.password.get_secret_value()
                )
            client.send_message(message)
    except smtplib.SMTPRecipientsRefused as error:
        code = next(iter(error.recipients.values()))[0]
        raise DeliveryFailure(f"smtp_{code}", retry=400 <= code < 500) from None
    except smtplib.SMTPResponseException as error:
        code = error.smtp_code
        raise DeliveryFailure(f"smtp_{code}", retry=400 <= code < 500) from None
    except (OSError, smtplib.SMTPException):
        raise DeliveryFailure("smtp_unavailable", retry=True) from None


def deliver(destinations: Destinations, tenant: str, item: dict) -> None:
    event = packet(tenant, item)
    if item["channel"] == "webhook" and destinations.webhook:
        deliver_webhook(destinations.webhook, event)
    elif item["channel"] == "smtp" and destinations.smtp:
        deliver_smtp(destinations.smtp, event)
    else:
        raise DeliveryFailure("destination_unavailable", retry=False)
