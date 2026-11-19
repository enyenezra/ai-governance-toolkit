import argparse
import os
from pathlib import Path

from aigovkit.connectors import InventoryConnector, JsonInventoryConnector
from aigovkit.storage import PostgresInventory
from aigovkit.tenancy import configured_tenants, schema_for


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize governance storage.")
    parser.add_argument(
        "--import-json", type=Path, help="Import or replace inventory by kind and ID."
    )
    parser.add_argument(
        "--tenant", help="Select a configured tenant for inventory import."
    )
    args = parser.parse_args()
    connector: InventoryConnector | None = (
        JsonInventoryConnector(args.import_json) if args.import_json else None
    )
    records = list(connector.records()) if connector else None
    try:
        tenants = configured_tenants()
    except ValueError:
        parser.error("Invalid tenant authentication configuration.")
    scopes = {tenant.id: schema_for(tenant.id) for tenant in tenants or []}
    if args.tenant and args.tenant not in scopes:
        parser.error("Select a configured tenant.")
    if records is not None and scopes and args.tenant is None:
        parser.error("Specify --tenant before importing inventory in tenant mode.")
    schemas = [scopes[args.tenant]] if args.tenant else list(scopes.values()) or [None]
    for schema in schemas:
        store = PostgresInventory(os.environ["AIGOVKIT_DATABASE_URL"], schema)
        store.initialize()
        if records is not None:
            store.put(records)


if __name__ == "__main__":
    main()
