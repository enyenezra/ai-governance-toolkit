import json
from collections.abc import Iterable

import psycopg
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter

from aigovkit.models import Record, RiskReport

SCHEMA = """
CREATE TABLE IF NOT EXISTS governance_inventory (
    kind text NOT NULL,
    id text NOT NULL,
    body jsonb NOT NULL,
    PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS governance_reports (
    id text PRIMARY KEY,
    created_at timestamptz NOT NULL,
    body jsonb NOT NULL
);
"""
SCHEMA_LOCK_ID = 0x4149474F564B4954
record_adapter = TypeAdapter(Record)


class PostgresInventory:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def initialize(self) -> None:
        with psycopg.connect(self.dsn, connect_timeout=5) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s::bigint)", (SCHEMA_LOCK_ID,))
            conn.execute(SCHEMA)

    def put(self, records: Iterable[Record]) -> None:
        with (
            psycopg.connect(self.dsn, connect_timeout=5) as conn,
            conn.cursor() as cursor,
        ):
            cursor.executemany(
                """
                INSERT INTO governance_inventory (kind, id, body) VALUES (%s, %s, %s)
                ON CONFLICT (kind, id) DO UPDATE SET body = EXCLUDED.body
                """,
                [(r.kind, r.id, Jsonb(r.model_dump(mode="json"))) for r in records],
            )

    def records(self) -> list[Record]:
        with psycopg.connect(self.dsn, connect_timeout=5) as conn:
            return [
                record_adapter.validate_python(body)
                for (body,) in conn.execute(
                    "SELECT body FROM governance_inventory ORDER BY kind, id"
                )
            ]

    def save_report(self, report: RiskReport) -> None:
        with psycopg.connect(self.dsn, connect_timeout=5) as conn:
            conn.execute(
                "INSERT INTO governance_reports (id, created_at, body) VALUES (%s, %s, %s)",
                (report.id, report.created_at, Jsonb(report.model_dump(mode="json"))),
            )

    def get_report(self, report_id: str) -> RiskReport | None:
        with psycopg.connect(self.dsn, connect_timeout=5) as conn:
            row = conn.execute(
                "SELECT body FROM governance_reports WHERE id = %s", (report_id,)
            ).fetchone()
        return RiskReport.model_validate_json(json.dumps(row[0])) if row else None

    def list_reports(self, offset: int, limit: int) -> list[RiskReport]:
        with psycopg.connect(self.dsn, connect_timeout=5) as conn:
            return [
                RiskReport.model_validate_json(json.dumps(body))
                for (body,) in conn.execute(
                    """
                    SELECT body FROM governance_reports
                    ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s
                    """,
                    (limit, offset),
                )
            ]
