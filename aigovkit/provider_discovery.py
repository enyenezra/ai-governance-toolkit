"""Read-only provider metadata. Run as an operator with narrowly scoped credentials."""

import argparse
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import quote, urlsplit
from uuid import UUID

import boto3
import httpx
from botocore.exceptions import BotoCoreError, ClientError

Provider = Literal[
    "entra", "microsoft365", "purview", "azure", "aws-iam", "mcp", "ai-gateway"
]
PROVIDERS = (
    "entra",
    "microsoft365",
    "purview",
    "azure",
    "aws-iam",
    "mcp",
    "ai-gateway",
)
MCP_VERSION = "2025-11-25"
MAX_BYTES = 2 * 1024 * 1024


def read_only_http(client, method, url, **kwargs):
    with client.stream(method, url, **kwargs) as response:
        response.raise_for_status()
        raw = bytearray()
        deadline = time.monotonic() + 20
        for chunk in response.iter_bytes():
            if time.monotonic() > deadline:
                raise ValueError("Provider response timed out.")
            raw.extend(chunk)
            if len(raw) > MAX_BYTES:
                raise ValueError("Provider response exceeds the discovery limit.")
            if (
                response.headers.get("content-type", "").split(";")[0]
                == "text/event-stream"
            ):
                for line in raw.decode(errors="replace").splitlines():
                    if line.startswith("data:"):
                        try:
                            value = json.loads(line[5:])
                        except ValueError:
                            continue
                        if value.get("id") == (kwargs.get("json") or {}).get("id"):
                            return value, response.headers
        return (json.loads(raw) if raw else {}), response.headers


def https_endpoint(key: str) -> str:
    value = os.environ[key]
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("Configure a trusted HTTPS provider endpoint.")
    return value.rstrip("/")


def list_mcp(client, url: str, pages: int = 1) -> tuple[list[dict], bool]:
    headers = {"Accept": "application/json, text/event-stream"}

    def rpc(method: str, params=None, request_id=None):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if request_id is not None:
            payload["id"] = request_id
        result, returned_headers = read_only_http(
            client, "POST", url, json=payload, headers=headers
        )
        if request_id is not None and (
            result.get("id") != request_id or "error" in result
        ):
            raise ValueError("MCP discovery request rejected.")
        return result.get("result", {}), returned_headers

    result, initial_headers = rpc(
        "initialize",
        {
            "protocolVersion": MCP_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "AIGovKit", "version": "0.1.0"},
        },
        1,
    )
    version = result.get("protocolVersion")
    if version != MCP_VERSION:
        raise ValueError("Unsupported MCP protocol version.")
    headers["MCP-Protocol-Version"] = version
    if session := initial_headers.get("Mcp-Session-Id"):
        headers["Mcp-Session-Id"] = session
    rpc("notifications/initialized")
    tools = []
    cursor = None
    for index in range(pages):
        result, _ = rpc("tools/list", {"cursor": cursor} if cursor else None, index + 2)
        tools.extend(result["tools"])
        cursor = result.get("nextCursor")
        if not cursor:
            break
    return tools, bool(cursor)


def linked_pages(client, url: str, params: dict, next_key: str, pages: int):
    origin = urlsplit(url)
    items = []
    next_url = url
    for index in range(pages):
        result, _ = read_only_http(
            client, "GET", next_url, params=params if index == 0 else None
        )
        items.extend(result["value"])
        next_url = result.get(next_key)
        if not next_url:
            break
        if index + 1 == pages:
            break
        target = urlsplit(next_url)
        if (target.scheme, target.netloc, target.path) != (
            origin.scheme,
            origin.netloc,
            origin.path,
        ):
            raise ValueError("Unexpected provider pagination URL.")
    return items, bool(next_url)


def discover(provider: Provider, client: httpx.Client, pages: int = 1) -> dict:
    if not 1 <= pages <= 25:
        raise ValueError("Discovery requires 1–25 pages.")
    if provider == "aws-iam":
        iam = boto3.client("iam")
        records = []
        marker = None
        partial = False
        for _ in range(pages):
            cursor = {"Marker": marker} if marker else {}
            result = iam.list_roles(MaxItems=100, **cursor)
            records.extend(
                {"id": role["RoleId"], "name": role["RoleName"], "type": "iam_role"}
                for role in result["Roles"]
            )
            partial = result["IsTruncated"]
            marker = result.get("Marker")
            if not partial or not marker:
                break
        return {"provider": provider, "records": records, "partial": partial}
    if provider == "mcp":
        items, partial = list_mcp(client, https_endpoint("AIGOVKIT_MCP_URL"), pages)
        records = [
            {"id": row["name"], "name": row["name"], "type": "mcp_tool"}
            for row in items
        ]
        return {"provider": provider, "records": records, "partial": partial}
    if provider in {"entra", "microsoft365"}:
        path, select = (
            ("servicePrincipals", "id,displayName,servicePrincipalType")
            if provider == "entra"
            else ("subscribedSkus", "id,skuPartNumber")
        )
        items, partial = linked_pages(
            client,
            f"https://graph.microsoft.com/v1.0/{path}",
            {"$select": select},
            "@odata.nextLink",
            pages,
        )
        records = [
            {
                "id": row["id"],
                "name": row.get("displayName") or row.get("skuPartNumber"),
                "type": row.get("servicePrincipalType") or "subscription_sku",
            }
            for row in items
        ]
    elif provider == "azure":
        subscription = str(UUID(os.environ["AIGOVKIT_AZURE_SUBSCRIPTION"]))
        items, partial = linked_pages(
            client,
            f"https://management.azure.com/subscriptions/{quote(subscription)}/resources",
            {"api-version": "2021-04-01", "$top": 100},
            "nextLink",
            pages,
        )
        records = [
            {"id": row["id"], "name": row["name"], "type": row["type"]} for row in items
        ]
    elif provider == "purview":
        records = []
        continuation = None
        for _ in range(pages):
            body = {"keywords": "*", "limit": 100}
            if continuation:
                body["continuationToken"] = continuation
            result, _ = read_only_http(
                client,
                "POST",
                https_endpoint("AIGOVKIT_PURVIEW_URL") + "/datamap/api/search/query",
                params={"api-version": "2023-09-01"},
                json=body,
            )
            records.extend(
                {"id": row["id"], "name": row["name"], "type": row["entityType"]}
                for row in result["value"]
            )
            continuation = result.get("continuationToken")
            if not continuation:
                break
        partial = bool(continuation)
    elif provider == "ai-gateway":
        result, _ = read_only_http(
            client, "GET", https_endpoint("AIGOVKIT_GATEWAY_MODELS_URL")
        )
        partial = bool(result.get("has_more"))
        records = [
            {"id": row["id"], "name": row["id"], "type": "model"}
            for row in result["data"]
        ]
    else:
        raise ValueError("Unknown provider.")
    return {
        "provider": provider,
        "records": records[: 100 * pages],
        "partial": partial or len(records) > 100 * pages,
    }


def submit_observations(report: dict, client: httpx.Client) -> dict:
    base = https_endpoint("AIGOVKIT_OBSERVATION_API")
    key = os.environ["AIGOVKIT_OBSERVER_KEY"]
    if len(key) < 32:
        raise ValueError("Configure a scoped observer key.")
    day = datetime.now(UTC).date().isoformat()
    source = report["provider"]
    saved, already_recorded = 0, 0
    for entry in report["records"]:
        # Daily identifiers make repeated scheduled runs safe.
        key_id = hashlib.sha256(f"{source}\n{day}\n{entry['id']}".encode()).hexdigest()
        service = str(entry["name"] or entry["id"])[:500].strip() or "Unnamed service"
        response = client.put(
            f"{base}/v1/registers/discovery/{key_id}",
            headers={"X-API-Key": key},
            json={
                "kind": "discovery",
                "title": service,
                "source": source,
                "service": service,
                "count": 1,
                "status": "needs_review",
                "observed_on": day,
            },
        )
        if response.status_code == 409:
            already_recorded += 1
        else:
            response.raise_for_status()
            saved += 1
    return {
        "provider": source,
        "saved": saved,
        "already_recorded": already_recorded,
        "partial": report["partial"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", choices=PROVIDERS)
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Submit observations to your AIGovKit workspace.",
    )
    parser.add_argument("--pages", type=int, default=1)
    args = parser.parse_args()
    token = os.getenv("AIGOVKIT_CONNECTOR_TOKEN")
    if args.provider not in {"aws-iam", "mcp"} and not token:
        parser.exit(2, "Provide a read-only token for the selected provider.\n")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with httpx.Client(
            headers=headers, timeout=8, follow_redirects=False, trust_env=False
        ) as client:
            report = discover(args.provider, client, args.pages)
        if args.submit:
            # The provider bearer credential is never sent to the governance service.
            with httpx.Client(
                timeout=8, follow_redirects=False, trust_env=False
            ) as observer:
                report = submit_observations(report, observer)
        print(json.dumps(report, indent=2))
    except (
        httpx.HTTPError,
        BotoCoreError,
        ClientError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
    ):
        parser.exit(
            1, "Discovery failed. Check endpoint, scope and provider configuration.\n"
        )


if __name__ == "__main__":
    main()
