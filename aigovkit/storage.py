import json
from collections.abc import Iterable

import psycopg
from psycopg import sql
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
CREATE TABLE IF NOT EXISTS foundation_documents (
    kind text NOT NULL,
    id text NOT NULL,
    body jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS policy_revisions (
    draft_id text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    author text NOT NULL,
    body jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (draft_id, version)
);
CREATE TABLE IF NOT EXISTS policy_review_events (
    draft_id text NOT NULL,
    version integer NOT NULL,
    action text NOT NULL CHECK (action IN ('submitted', 'approved', 'changes_requested')),
    actor text NOT NULL,
    note text,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (draft_id, version, action),
    FOREIGN KEY (draft_id, version) REFERENCES policy_revisions (draft_id, version)
);
CREATE TABLE IF NOT EXISTS policy_publications (
    draft_id text NOT NULL,
    version integer NOT NULL,
    publisher text NOT NULL,
    published_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (draft_id, version),
    FOREIGN KEY (draft_id, version) REFERENCES policy_revisions (draft_id, version)
);
CREATE TABLE IF NOT EXISTS policy_acknowledgements (
    draft_id text NOT NULL,
    version integer NOT NULL,
    member_id text NOT NULL,
    acknowledged_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (draft_id, version, member_id),
    FOREIGN KEY (draft_id, version) REFERENCES policy_publications (draft_id, version)
);
"""
SCHEMA_LOCK_ID = 0x4149474F564B4954
record_adapter = TypeAdapter(Record)


class PostgresInventory:
    def __init__(self, dsn: str, schema: str | None = None):
        self.dsn = dsn
        self.schema = schema

    def connect(self):
        conn = psycopg.connect(self.dsn, connect_timeout=5)
        if self.schema is not None:
            try:
                conn.execute(
                    sql.SQL("SET search_path TO {}, pg_catalog").format(
                        sql.Identifier(self.schema)
                    )
                )
            except BaseException:
                conn.close()
                raise
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s::bigint)", (SCHEMA_LOCK_ID,))
            if self.schema is not None:
                conn.execute(
                    sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                        sql.Identifier(self.schema)
                    )
                )
            conn.execute(SCHEMA)

    def put(self, records: Iterable[Record]) -> None:
        with (
            self.connect() as conn,
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
        with self.connect() as conn:
            return [
                record_adapter.validate_python(body)
                for (body,) in conn.execute(
                    "SELECT body FROM governance_inventory ORDER BY kind, id"
                )
            ]

    def save_report(self, report: RiskReport) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO governance_reports (id, created_at, body) VALUES (%s, %s, %s)",
                (report.id, report.created_at, Jsonb(report.model_dump(mode="json"))),
            )

    def get_report(self, report_id: str) -> RiskReport | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT body FROM governance_reports WHERE id = %s", (report_id,)
            ).fetchone()
        return RiskReport.model_validate_json(json.dumps(row[0])) if row else None

    def list_reports(self, offset: int, limit: int) -> list[RiskReport]:
        with self.connect() as conn:
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

    def put_document(self, kind: str, document_id: str, body: dict, *, replace=False):
        # Only the singleton organisation profile uses replacement.
        statement = (
            "INSERT INTO foundation_documents (kind, id, body) VALUES (%s, %s, %s)"
        )
        if replace:
            statement += " ON CONFLICT (kind, id) DO UPDATE SET body = EXCLUDED.body"
        with self.connect() as conn:
            conn.execute(statement, (kind, document_id, Jsonb(body)))

    def get_document(self, kind: str, document_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT body FROM foundation_documents WHERE kind = %s AND id = %s",
                (kind, document_id),
            ).fetchone()
            return row[0] if row else None

    def documents(self, kind: str, offset: int, limit: int) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT body FROM foundation_documents WHERE kind = %s
                   ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s""",
                (kind, limit, offset),
            )
            return [body for (body,) in rows]
