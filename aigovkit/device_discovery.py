"""Passive device and domain metadata intake for authorised collectors."""

import hashlib
import hmac
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import Field, StringConstraints

from aigovkit.api import Store
from aigovkit.foundation import Actor, Limit, Offset, database_call
from aigovkit.models import StrictModel
from aigovkit.tenancy import authenticate

router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])
Label = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
]
NETWORK_SOURCES = {"dhcp", "wifi", "switch", "nac"}
MANAGED_SOURCES = {"intune", "google-chromeos", "google-mobile"}


class Observation(StrictModel):
    source: Literal["dhcp", "wifi", "switch", "nac"]
    mac: str = Field(min_length=12, max_length=17)
    seen_at: str = Field(min_length=19, max_length=40)
    name: Label | None = None


class DomainSignal(StrictModel):
    source: Literal["dns", "proxy"]
    mac: str = Field(min_length=12, max_length=17)
    seen_at: str = Field(min_length=19, max_length=40)
    domain: str = Field(min_length=1, max_length=253)
    count: int = Field(ge=1, le=100_000)


def timestamp(value: str, *, network: bool = True) -> str:
    try:
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is None or moment > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError
        if network and moment < datetime.now(UTC) - timedelta(days=30):
            raise ValueError
    except (OverflowError, ValueError):
        raise HTTPException(
            422, "Supply a valid observation time with a timezone."
        ) from None
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def mac_address(value: str) -> str:
    key = value.lower().replace(":", "").replace("-", "")
    if (
        not re.fullmatch(r"[0-9a-f]{12}", key)
        or key == "000000000000"
        or int(key[:2], 16) & 1
    ):
        raise HTTPException(422, "Supply a valid unicast MAC address.")
    return key


def fingerprint(actor: Actor, value: str) -> str:
    secret = os.environ.get("AIGOVKIT_DEVICE_HASH_KEY", "")
    if len(secret) < 32:
        raise HTTPException(503, "Device identity hashing is unavailable.")
    return hmac.new(
        secret.encode(), f"{actor.tenant}:{value}".encode(), hashlib.sha256
    ).hexdigest()


def upsert_device(
    cursor,
    actor: Actor,
    source: str,
    seen_at: str,
    name: str | None,
    *,
    mac: str | None = None,
    provider_id: str | None = None,
) -> dict:
    # A locally administered MAC may be randomized. Scope it to its source.
    stable = mac and not (int(mac[:2], 16) & 2)
    if stable:
        identity = f"mac:{mac}"
        confidence = "exact_mac"
    else:
        identity = f"{source}:{provider_id or mac}"
        confidence = "source_only"
    device_id = fingerprint(actor, identity)
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || %s,0))",
        (":device:" + device_id,),
    )
    previous = cursor.execute(
        "SELECT body FROM foundation_documents WHERE kind='device' AND id=%s",
        (device_id,),
    ).fetchone()
    body = (
        previous["body"]
        if previous
        else {"id": device_id, "sources": {}, "match": confidence}
    )
    current = body["sources"].get(source)
    if not current or seen_at >= current["last_seen"]:
        body["sources"][source] = {
            "last_seen": seen_at,
            "name": name or (current or {}).get("name"),
        }
    sources = body["sources"]
    body["last_seen"] = max(value["last_seen"] for value in sources.values())
    body["managed"] = bool(MANAGED_SOURCES & sources.keys())
    body["network_seen"] = bool(NETWORK_SOURCES & sources.keys())
    cursor.execute(
        """INSERT INTO foundation_documents (kind,id,body,created_at)
           VALUES ('device',%s,%s,%s::timestamptz)
           ON CONFLICT (kind,id) DO UPDATE SET body=EXCLUDED.body, created_at=EXCLUDED.created_at""",
        (device_id, Jsonb(body), body["last_seen"]),
    )
    return body


def require_collector(actor: Actor) -> None:
    if actor.member is None or actor.role not in {"observer", "editor"}:
        raise HTTPException(403, "A named observer or editor is required.")


@router.post("/device-observations", status_code=201)
def observe(request: Observation, store: Store, actor: Actor) -> dict:
    require_collector(actor)
    mac = mac_address(request.mac)
    seen_at = timestamp(request.seen_at)

    def write():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            row = upsert_device(
                cursor, actor, request.source, seen_at, request.name, mac=mac
            )
            store.audit(cursor, "device.observed", "device", row["id"])
            return row

    return database_call(write)


@router.post("/device-domain-signals", status_code=202)
def signal(request: DomainSignal, store: Store, actor: Actor) -> dict:
    require_collector(actor)
    domain = request.domain.lower().rstrip(".")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", domain) or ".." in domain:
        raise HTTPException(422, "Supply a domain without a URL or path.")
    approved_domains = [
        item.strip().lower().rstrip(".")
        for item in os.environ.get("AIGOVKIT_AI_SIGNAL_DOMAINS", "").split(",")
        if item.strip()
    ]
    match = next(
        (
            suffix
            for suffix in approved_domains
            if domain == suffix or domain.endswith("." + suffix)
        ),
        None,
    )
    if match is None:
        return {"recorded": False}
    mac = mac_address(request.mac)
    seen = timestamp(request.seen_at)
    # Keep only the configured AI suffix, rather than the full queried hostname.
    key = fingerprint(actor, f"signal:{request.source}:{mac}:{match}:{seen[:10]}")
    body = {
        "id": key,
        "version": 1,
        "kind": "discovery",
        "title": match,
        "source": request.source,
        "service": match,
        "department_id": None,
        "count": request.count,
        "status": "needs_review",
        "observed_on": seen[:10],
    }

    def write():
        with store.connect() as conn:
            result = conn.execute(
                """INSERT INTO foundation_documents (kind,id,body) VALUES ('register_discovery',%s,%s)
                   ON CONFLICT DO NOTHING""",
                (key, Jsonb(body)),
            )
            if result.rowcount:
                conn.execute(
                    "INSERT INTO foundation_documents (kind,id,body) VALUES ('register_discovery_history',%s,%s)",
                    (key + ":1", Jsonb(body)),
                )
                store.audit(conn, "device.domain_signal", "discovery", key)
            return {"recorded": bool(result.rowcount)}

    return database_call(write)


@router.get("/devices")
def devices(store: Store, offset: Offset = 0, limit: Limit = 50) -> list[dict]:
    return database_call(store.documents, "device", offset, limit)
