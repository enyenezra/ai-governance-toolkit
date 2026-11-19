"""Read-only Microsoft 365 and Google Workspace discovery per tenant."""

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import SecretStr, TypeAdapter, ValidationError

from aigovkit.api import Store
from aigovkit.device_discovery import fingerprint, mac_address, timestamp, upsert_device
from aigovkit.foundation import Actor, Limit, Offset, database_call
from aigovkit.models import Identifier, StrictModel
from aigovkit.policy_review import named_member
from aigovkit.provider_discovery import linked_pages, read_only_http
from aigovkit.tenancy import authenticate

router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])
Provider = Literal["microsoft365", "google-workspace"]
PROVIDERS = ("microsoft365", "google-workspace")
PORTALS = {
    "microsoft365": "https://entra.microsoft.com/",
    "google-workspace": "https://admin.google.com/",
}
GRAPH = "https://graph.microsoft.com/v1.0"
GOOGLE = "https://admin.googleapis.com/admin"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
PAGES = 3


class Microsoft(StrictModel):
    tenant_id: str
    client_id: str
    client_secret: SecretStr
    applications: bool = True
    sign_ins: bool = False
    devices: bool = False


class Google(StrictModel):
    service_account_file: str
    delegated_admin: str
    customer_id: str
    oauth_audit: bool = True
    chromeos: bool = False
    mobile: bool = False


class TenantConnections(StrictModel):
    microsoft365: Microsoft | None = None
    google_workspace: Google | None = None


class Scheduling(StrictModel):
    enabled: bool


def configuration(tenant: str | None) -> TenantConnections:
    if tenant is None:
        return TenantConnections()
    try:
        entries = TypeAdapter(dict[Identifier, TenantConnections]).validate_json(
            os.getenv("AIGOVKIT_DISCOVERY_CONNECTIONS", "{}")
        )
    except ValidationError:
        raise HTTPException(
            503, "Discovery deployment configuration is invalid."
        ) from None
    return entries.get(tenant, TenantConnections())


def settings(tenant: str | None, provider: Provider) -> Microsoft | Google:
    config = configuration(tenant)
    selected = (
        config.microsoft365 if provider == "microsoft365" else config.google_workspace
    )
    if selected is None:
        raise HTTPException(
            503, "Complete provider administration and deployment configuration first."
        )
    return selected


def token(client: httpx.Client, config: Microsoft | Google) -> str:
    if isinstance(config, Microsoft):
        tenant, app = str(UUID(config.tenant_id)), str(UUID(config.client_id))
        url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
        form = {
            "client_id": app,
            "client_secret": config.client_secret.get_secret_value(),
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        }
    else:
        if config.customer_id == "my_customer" or not re.fullmatch(
            r"[A-Za-z0-9_-]{2,100}", config.customer_id
        ):
            raise ValueError("Configure the exact Google Workspace customer ID.")
        with Path(config.service_account_file).open("rb") as stream:
            credential = json.loads(stream.read(65536))
        if credential["type"] != "service_account":
            raise ValueError("Use a service account credential.")
        scopes = []
        if config.oauth_audit:
            scopes.append(
                "https://www.googleapis.com/auth/admin.reports.audit.readonly"
            )
        if config.chromeos:
            scopes.append(
                "https://www.googleapis.com/auth/admin.directory.device.chromeos.readonly"
            )
        if config.mobile:
            scopes.append(
                "https://www.googleapis.com/auth/admin.directory.device.mobile.readonly"
            )
        now = int(datetime.now(UTC).timestamp())
        assertion = jwt.encode(
            {
                "iss": credential["client_email"],
                "sub": config.delegated_admin,
                "scope": " ".join(scopes),
                "aud": GOOGLE_TOKEN,
                "iat": now,
                "exp": now + 300,
            },
            credential["private_key"],
            algorithm="RS256",
        )
        url = GOOGLE_TOKEN
        form = {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }
    response = client.post(url, data=form)
    response.raise_for_status()
    access = response.json()["access_token"]
    if not isinstance(access, str) or not access:
        raise TypeError("Provider returned no access token.")
    return access


def google_pages(client: httpx.Client, path: str, params: dict, key: str, pages: int):
    rows, cursor = [], None
    for _ in range(pages):
        query = params | ({"pageToken": cursor} if cursor else {})
        result, _ = read_only_http(client, "GET", GOOGLE + path, params=query)
        rows.extend(result.get(key, []))
        cursor = result.get("nextPageToken")
        if not cursor:
            break
    return rows, bool(cursor)


def label(value: object) -> str:
    return str(value or "Unnamed service").strip()[:160] or "Unnamed service"


def managed(row, source, id_key, time_key, name_key, mac_key=None):
    identifier, seen_at = row.get(id_key), row.get(time_key)
    if not identifier or not seen_at:
        return None
    try:
        observed = timestamp(seen_at, network=False)
    except HTTPException:
        return None
    mac = None
    if mac_key and row.get(mac_key):
        try:
            mac = mac_address(row[mac_key])
        except HTTPException:
            pass
    return {
        "source": source,
        "provider_id": identifier,
        "seen_at": observed,
        "name": label(row.get(name_key)),
        "mac": mac,
    }


def collect(client: httpx.Client, config: Microsoft | Google, pages: int) -> dict:
    applications = {}
    devices = []
    partial = False
    sources = []
    start = (
        (datetime.now(UTC) - timedelta(days=7))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )

    def apps(rows, source, id_key, label_key, more):
        nonlocal partial
        sources.append(source)
        partial |= more
        for row in rows:
            key = row.get(id_key)
            if not key:
                continue
            item = applications.setdefault(
                (source, key),
                {
                    "source": source,
                    "id": key,
                    "name": label(row.get(label_key)),
                    "count": 0,
                },
            )
            item["count"] += 1

    def endpoints(rows, source, id_key, time_key, name_key, mac_key, more):
        nonlocal partial
        sources.append(source)
        partial |= more
        for row in rows:
            item = managed(row, source, id_key, time_key, name_key, mac_key)
            if item:
                devices.append(item)
            else:
                partial = True

    if isinstance(config, Microsoft):
        if config.applications:
            rows, more = linked_pages(
                client,
                GRAPH + "/servicePrincipals",
                {"$select": "id,appId,displayName", "$top": 100},
                "@odata.nextLink",
                pages,
            )
            apps(rows, "entra-apps", "appId", "displayName", more)
        if config.sign_ins:
            rows, more = linked_pages(
                client,
                GRAPH + "/auditLogs/signIns",
                {"$filter": f"createdDateTime ge {start}", "$top": 100},
                "@odata.nextLink",
                pages,
            )
            apps(rows, "entra-sign-ins", "appId", "appDisplayName", more)
        if config.devices:
            rows, more = linked_pages(
                client,
                GRAPH + "/deviceManagement/managedDevices",
                {"$select": "id,model,lastSyncDateTime,wiFiMacAddress", "$top": 100},
                "@odata.nextLink",
                pages,
            )
            endpoints(
                rows,
                "intune",
                "id",
                "lastSyncDateTime",
                "model",
                "wiFiMacAddress",
                more,
            )
    else:
        customer = config.customer_id
        if config.oauth_audit:
            rows, more = google_pages(
                client,
                "/reports/v1/activity/users/all/applications/token",
                {
                    "customerId": customer,
                    "eventName": "authorize",
                    "startTime": start,
                    "maxResults": 100,
                    "fields": "nextPageToken,items(events(name,parameters(name,value)))",
                },
                "items",
                pages,
            )
            events = [
                {
                    param["name"]: param.get("value")
                    for param in event.get("parameters", [])
                }
                for row in rows
                for event in row.get("events", [])
                if event.get("name") == "authorize"
            ]
            apps(events, "google-oauth", "client_id", "app_name", more)
        if config.chromeos:
            rows, more = google_pages(
                client,
                f"/directory/v1/customer/{customer}/devices/chromeos",
                {
                    "maxResults": 100,
                    "projection": "FULL",
                    "fields": "nextPageToken,chromeosdevices(deviceId,model,macAddress,lastSync)",
                },
                "chromeosdevices",
                pages,
            )
            endpoints(
                rows,
                "google-chromeos",
                "deviceId",
                "lastSync",
                "model",
                "macAddress",
                more,
            )
        if config.mobile:
            rows, more = google_pages(
                client,
                f"/directory/v1/customer/{customer}/devices/mobile",
                {
                    "maxResults": 100,
                    "projection": "FULL",
                    "fields": "nextPageToken,mobiledevices(resourceId,model,lastSync)",
                },
                "mobiledevices",
                pages,
            )
            endpoints(
                rows, "google-mobile", "resourceId", "lastSync", "model", None, more
            )

    if not sources:
        raise ValueError("Select at least one discovery source.")
    return {
        "applications": list(applications.values()),
        "devices": devices,
        "sources": sources,
        "partial": partial,
    }


def discover(config: Microsoft | Google, pages: int) -> dict:
    try:
        with httpx.Client(
            timeout=10, follow_redirects=False, trust_env=False
        ) as auth_client:
            access = token(auth_client, config)
        with httpx.Client(
            headers={"Authorization": f"Bearer {access}"},
            timeout=10,
            follow_redirects=False,
            trust_env=False,
        ) as api_client:
            return collect(api_client, config, pages)
    except (
        httpx.HTTPError,
        jwt.PyJWTError,
        KeyError,
        TypeError,
        ValueError,
        OSError,
        AttributeError,
    ):
        raise HTTPException(
            502,
            "Discovery failed. Check provider consent, configuration and API access.",
        ) from None


def config_revision(config: Microsoft | Google) -> str:
    value = config.model_dump_json(exclude={"client_secret"})
    return hashlib.sha256(value.encode()).hexdigest()


def save_connection_state(
    store: Store, kind: str, provider: Provider, body: dict
) -> None:
    def write():
        with store.connect() as conn:
            conn.execute(
                """INSERT INTO foundation_documents (kind,id,body) VALUES (%s,%s,%s)
                   ON CONFLICT(kind,id) DO UPDATE SET body=EXCLUDED.body""",
                (kind, provider, Jsonb(body)),
            )
            store.audit(conn, f"discovery.{kind}", "provider", provider)

    database_call(write)


SOURCE_DETAILS = {
    "entra-apps": (
        "application_inventory",
        "Registered application. This does not establish usage.",
    ),
    "entra-sign-ins": ("sign_in", "Sign-in activity in the queried seven-day window."),
    "google-oauth": (
        "oauth_authorisation",
        "Authorisation in the queried seven-day window. This does not establish usage.",
    ),
}


def enabled_sources(config: Microsoft | Google | None) -> list[str]:
    if config is None:
        return []
    fields = (
        (
            ("applications", "entra-apps"),
            ("sign_ins", "entra-sign-ins"),
            ("devices", "intune"),
        )
        if isinstance(config, Microsoft)
        else (
            ("oauth_audit", "google-oauth"),
            ("chromeos", "google-chromeos"),
            ("mobile", "google-mobile"),
        )
    )
    return [source for field, source in fields if getattr(config, field)]


def disconnected(store: Store, provider: Provider) -> bool:
    state = database_call(
        store.get_document, "workspace_discovery_connection", provider
    )
    return bool(state and not state.get("enabled"))


@router.put("/workspace-discovery/{provider}/connection")
def set_connection(
    provider: Provider, request: Scheduling, actor: Actor, store: Store
) -> dict:
    named_member(actor, "editor")
    if request.enabled:
        settings(actor.tenant, provider)

    def write():
        with store.connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':workspace-sync',0))"
            )
            conn.execute(
                """INSERT INTO foundation_documents (kind,id,body)
                   VALUES ('workspace_discovery_connection',%s,%s)
                   ON CONFLICT(kind,id) DO UPDATE SET body=EXCLUDED.body""",
                (provider, Jsonb(request.model_dump())),
            )
            if not request.enabled:
                conn.execute(
                    """DELETE FROM foundation_documents
                       WHERE kind IN ('workspace_discovery_schedule','workspace_discovery_preview')
                         AND id=%s""",
                    (provider,),
                )
            store.audit(
                conn,
                "discovery.reconnected"
                if request.enabled
                else "discovery.disconnected",
                "provider",
                provider,
            )
            return request.model_dump()

    return database_call(write)


@router.get("/workspace-discovery/evidence")
def evidence(store: Store, offset: Offset = 0, limit: Limit = 20) -> list[dict]:
    return database_call(store.documents, "discovery_evidence", offset, limit)


@router.get("/workspace-discovery/connections")
def connections(store: Store, actor: Actor) -> list[dict]:
    config = configuration(actor.tenant)
    return [
        {
            "provider": provider,
            "configured": selected is not None,
            "admin_portal": PORTALS[provider],
            "enabled_sources": enabled_sources(selected),
            "disconnected": disconnected(store, provider),
            "last_attempt": database_call(
                store.get_document, "workspace_discovery_attempt", provider
            ),
            "scheduled": bool(
                (
                    database_call(
                        store.get_document, "workspace_discovery_schedule", provider
                    )
                    or {}
                ).get("enabled")
            ),
            "last_result": database_call(
                store.get_document, "workspace_discovery_result", provider
            ),
        }
        for provider, selected in (
            ("microsoft365", config.microsoft365),
            ("google-workspace", config.google_workspace),
        )
    ]


@router.post("/workspace-discovery/{provider}/preview")
def preview(provider: Provider, actor: Actor, store: Store) -> dict:
    named_member(actor, "editor")
    config = settings(actor.tenant, provider)
    if disconnected(store, provider):
        raise HTTPException(409, "Reconnect this provider before previewing.")
    result = discover(config, 1)
    save_connection_state(
        store,
        "workspace_discovery_preview",
        provider,
        {"revision": config_revision(config)},
    )
    return {
        "sources": result["sources"],
        "partial": result["partial"],
        "applications": [
            {"name": row["name"], "source": row["source"], "count": row["count"]}
            for row in result["applications"][:20]
        ],
        "devices": [
            {"name": row["name"], "source": row["source"], "last_seen": row["seen_at"]}
            for row in result["devices"][:20]
        ],
    }


@router.put("/workspace-discovery/{provider}/schedule")
def schedule(
    provider: Provider, request: Scheduling, actor: Actor, store: Store
) -> dict:
    named_member(actor, "editor")
    body = request.model_dump()
    if request.enabled:
        if disconnected(store, provider):
            raise HTTPException(409, "Reconnect this provider before scheduling.")
        config = settings(actor.tenant, provider)
        verified = database_call(
            store.get_document, "workspace_discovery_preview", provider
        )
        revision = config_revision(config)
        if not verified or verified["revision"] != revision:
            raise HTTPException(
                409, "Preview the current provider configuration before enabling sync."
            )
        body["revision"] = revision
    save_connection_state(store, "workspace_discovery_schedule", provider, body)
    return request.model_dump()


def persist(store: Store, actor: Actor, provider: Provider, result: dict) -> dict:
    now = datetime.now(UTC)
    day = now.date().isoformat()

    def write():
        created = 0
        devices = set()
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            # Serialise sync writes per tenant. Network observations use only the device lock.
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || ':workspace-sync',0))"
            )
            state = cursor.execute(
                """SELECT body FROM foundation_documents
                   WHERE kind='workspace_discovery_connection' AND id=%s""",
                (provider,),
            ).fetchone()
            if state and not state["body"].get("enabled"):
                raise HTTPException(
                    409, "The provider was disconnected before sync completed."
                )
            for item in result["applications"]:
                key = fingerprint(actor, f"workspace:{item['source']}:{item['id']}")
                body = {
                    "id": key,
                    "version": 1,
                    "kind": "discovery",
                    "title": item["name"],
                    "source": item["source"],
                    "service": item["name"],
                    "department_id": None,
                    "count": min(item["count"], 1_000_000),
                    "status": "needs_review",
                    "observed_on": day,
                }
                row = cursor.execute(
                    """INSERT INTO foundation_documents (kind,id,body)
                       VALUES ('register_discovery',%s,%s) ON CONFLICT DO NOTHING""",
                    (key, Jsonb(body)),
                )
                if row.rowcount:
                    cursor.execute(
                        "INSERT INTO foundation_documents (kind,id,body) VALUES ('register_discovery_history',%s,%s)",
                        (key + ":1", Jsonb(body)),
                    )
                    created += 1
                event_type, explanation = SOURCE_DETAILS.get(
                    item["source"], ("unknown", "Review the provider source.")
                )
                event = {
                    "finding_id": key,
                    "provider": provider,
                    "source": item["source"],
                    "name": item["name"],
                    "event_type": event_type,
                    "interpretation": explanation,
                    "observed_count": item["count"],
                    "collected_at": now.isoformat(),
                    "partial": result["partial"],
                }
                cursor.execute(
                    """INSERT INTO foundation_documents (kind,id,body)
                       VALUES ('discovery_evidence',%s,%s)
                       ON CONFLICT(kind,id) DO UPDATE SET body=EXCLUDED.body, created_at=clock_timestamp()""",
                    (key, Jsonb(event)),
                )
            for item in result["devices"]:
                kwargs = {key: item[key] for key in ("mac", "provider_id")}
                device = upsert_device(
                    cursor,
                    actor,
                    item["source"],
                    item["seen_at"],
                    item["name"],
                    **kwargs,
                )
                devices.add(device["id"])
            summary = {
                "synced_at": now.isoformat(),
                "new_findings": created,
                "devices_observed": len(devices),
                "sources": result["sources"],
                "partial": result["partial"],
            }
            cursor.execute(
                """INSERT INTO foundation_documents (kind,id,body)
                   VALUES ('workspace_discovery_result',%s,%s)
                   ON CONFLICT(kind,id) DO UPDATE SET body=EXCLUDED.body""",
                (provider, Jsonb(summary)),
            )
            store.audit(cursor, "discovery.workspace_synced", "provider", provider)
            return summary

    return database_call(write)


def run_sync(
    store: Store, actor: Actor, provider: Provider, state: dict | None = None
) -> dict:
    try:
        config = settings(actor.tenant, provider)
        if disconnected(store, provider):
            raise HTTPException(409, "Reconnect this provider before syncing.")
        if state and state.get("revision") != config_revision(config):
            raise HTTPException(
                409, "Preview and enable the changed configuration again."
            )
        result = persist(store, actor, provider, discover(config, PAGES))
    except HTTPException as error:
        save_connection_state(
            store,
            "workspace_discovery_attempt",
            provider,
            {
                "at": datetime.now(UTC).isoformat(),
                "status": "failed",
                "status_code": error.status_code,
            },
        )
        raise
    save_connection_state(
        store,
        "workspace_discovery_attempt",
        provider,
        {
            "at": result["synced_at"],
            "status": "partial" if result["partial"] else "success",
        },
    )
    return result


@router.post("/workspace-discovery/{provider}/sync")
def sync(provider: Provider, actor: Actor, store: Store) -> dict:
    named_member(actor, "editor")
    return run_sync(store, actor, provider)


@router.post("/workspace-discovery/run")
def scheduled(actor: Actor, store: Store) -> dict:
    named_member(actor, "scheduler" if actor.role == "scheduler" else "editor")
    outcomes = {}
    for provider in PROVIDERS:
        state = database_call(
            store.get_document, "workspace_discovery_schedule", provider
        )
        if state and state["enabled"]:
            try:
                outcomes[provider] = run_sync(store, actor, provider, state)
            except HTTPException as error:
                outcomes[provider] = {"failed": True, "status": error.status_code}
    return outcomes
