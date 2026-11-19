"""Synchronise operator-approved Entra group mappings into managed memberships."""

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import Field, TypeAdapter, ValidationError

from aigovkit.models import Identifier, StrictModel
from aigovkit.provider_discovery import https_endpoint, read_only_http


class Mapping(StrictModel):
    groups: dict[Identifier, str] = Field(min_length=1, max_length=50)
    members: dict[Identifier, str] = Field(min_length=1, max_length=500)


def group_members(client: httpx.Client, group_id: str) -> set[str]:
    group = str(UUID(group_id))
    path = f"/v1.0/groups/{group}/transitiveMembers/microsoft.graph.user"
    url: str | None = f"https://graph.microsoft.com{path}?$select=id&$count=true"
    members = set()
    for _ in range(100):
        result, _ = read_only_http(
            client, "GET", url, headers={"ConsistencyLevel": "eventual"}
        )
        members.update(str(UUID(row["id"])) for row in result["value"])
        url = result.get("@odata.nextLink")
        if not url:
            return members
        target = urlsplit(url)
        if (
            target.scheme != "https"
            or target.netloc != "graph.microsoft.com"
            or target.path != path
        ):
            raise ValueError("Unexpected Graph pagination URL.")
    raise ValueError("Graph group snapshot is incomplete.")


def synchronize(
    graph: httpx.Client,
    governance: httpx.Client,
    base: str,
    mapping: Mapping,
    apply: bool,
) -> dict:
    snapshots = {
        group: group_members(graph, remote) for group, remote in mapping.groups.items()
    }
    remote_members = {
        member: str(UUID(remote)) for member, remote in mapping.members.items()
    }
    if len(set(remote_members.values())) != len(remote_members):
        raise ValueError("Each mapped member requires a distinct Graph user ID.")
    current = {}
    for offset in range(0, 5000, 100):
        result = governance.get(
            base + "/v1/identity/members", params={"offset": offset, "limit": 100}
        )
        result.raise_for_status()
        page = result.json()
        current.update({row["member_id"]: row for row in page})
        if len(page) < 100:
            break
    if mapping.members.keys() - current.keys():
        raise ValueError("Provision every mapped member before synchronising.")
    planned, applied = 0, 0
    for member, remote in remote_members.items():
        row = current[member]
        if row["state"] != "active":
            continue
        groups = set(row["groups"]) - mapping.groups.keys()
        groups.update(
            group for group, snapshot in snapshots.items() if remote in snapshot
        )
        if groups == set(row["groups"]):
            continue
        planned += 1
        if apply:
            updated = governance.put(
                base + f"/v1/identity/members/{member}",
                json={
                    "subject": row["subject"],
                    "role": row["role"],
                    "state": row["state"],
                    "expected_version": row["version"],
                    "groups": sorted(groups),
                },
            )
            updated.raise_for_status()
            applied += 1
    return {"planned": planned, "applied": applied}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mapping", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        mapping = TypeAdapter(Mapping).validate_json(args.mapping.read_bytes())
        base = https_endpoint("AIGOVKIT_SYNC_API")
        with (
            httpx.Client(
                headers={
                    "Authorization": "Bearer " + os.environ["AIGOVKIT_ENTRA_TOKEN"]
                },
                timeout=15,
                trust_env=False,
            ) as graph,
            httpx.Client(
                headers={"X-API-Key": os.environ["AIGOVKIT_SYNC_KEY"]},
                timeout=15,
                trust_env=False,
            ) as governance,
        ):
            print(json.dumps(synchronize(graph, governance, base, mapping, args.apply)))
    except (httpx.HTTPError, KeyError, ValueError, ValidationError, TypeError, OSError):
        parser.exit(
            1,
            "Group sync stopped. Check configuration and prior audit events before retrying.\n",
        )


if __name__ == "__main__":
    main()
