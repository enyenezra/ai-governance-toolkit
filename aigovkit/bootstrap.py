import argparse
import os
from pathlib import Path

from aigovkit.connectors import InventoryConnector, JsonInventoryConnector
from aigovkit.storage import PostgresInventory


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize governance storage.")
    parser.add_argument(
        "--import-json", type=Path, help="Import or replace inventory by kind and ID."
    )
    args = parser.parse_args()
    connector: InventoryConnector | None = (
        JsonInventoryConnector(args.import_json) if args.import_json else None
    )
    records = list(connector.records()) if connector else None
    store = PostgresInventory(os.environ["AIGOVKIT_DATABASE_URL"])
    store.initialize()
    if records is not None:
        store.put(records)


if __name__ == "__main__":
    main()
