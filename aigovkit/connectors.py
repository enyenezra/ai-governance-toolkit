from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from pydantic import TypeAdapter

from aigovkit.models import Record


class InventoryConnector(Protocol):
    """Read-only source of validated candidate inventory records."""

    def records(self) -> Iterable[Record]: ...


class JsonInventoryConnector:
    """Offline connector for a trusted local JSON inventory export."""

    def __init__(self, path: Path):
        self.path = path

    def records(self) -> list[Record]:
        return TypeAdapter(list[Record]).validate_json(self.path.read_bytes())
