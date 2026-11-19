import json
from collections.abc import Iterable

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter

from aigovkit.directory import DIRECTORY_SCHEMA
from aigovkit.models import Record, RiskReport
from aigovkit.tenancy import Session

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
CREATE INDEX IF NOT EXISTS foundation_documents_kind_time
    ON foundation_documents (kind, created_at);
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
CREATE TABLE IF NOT EXISTS governance_audit (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    actor_id text,
    credential text NOT NULL,
    action text NOT NULL,
    resource_type text NOT NULL,
    resource_id text NOT NULL,
    version integer
);
"""
SCHEMA_LOCK_ID = 0x4149474F564B4954
record_adapter = TypeAdapter(Record)


class PostgresInventory:
    def __init__(
        self, dsn: str, schema: str | None = None, actor: Session | None = None
    ):
        self.dsn = dsn
        self.schema = schema
        self.actor = actor

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
            conn.execute(DIRECTORY_SCHEMA)
            conn.execute(SCHEMA)

    def put(self, records: Iterable[Record]) -> None:
        entries = list(records)
        with (
            self.connect() as conn,
            conn.cursor() as cursor,
        ):
            cursor.executemany(
                """
                INSERT INTO governance_inventory (kind, id, body) VALUES (%s, %s, %s)
                ON CONFLICT (kind, id) DO UPDATE SET body = EXCLUDED.body
                """,
                [(r.kind, r.id, Jsonb(r.model_dump(mode="json"))) for r in entries],
            )

            for record in entries:
                self.audit(cursor, "inventory.upserted", record.kind, record.id)

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

            self.audit(conn, "risk_report.created", "risk_report", report.id)

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

            self.audit(
                conn,
                "profile.updated" if replace else f"{kind}.created",
                kind,
                document_id,
            )

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

    def audit(
        self,
        executor,
        action: str,
        resource_type: str,
        resource_id: str,
        version: int | None = None,
    ) -> None:
        if self.actor is None:
            return
        credential = self.actor.credential if self.actor.member else "shared_key"
        executor.execute(
            """
            INSERT INTO governance_audit (actor_id, credential, action, resource_type, resource_id, version)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                self.actor.member,
                credential,
                action,
                resource_type,
                resource_id,
                version,
            ),
        )

    def audit_events(self, before: int | None, limit: int) -> list[dict]:
        statement = """
            SELECT event_id, occurred_at, actor_id, credential, action, resource_type, resource_id, version
            FROM governance_audit
        """
        where = " WHERE event_id < %s" if before is not None else ""
        params = (before, limit) if before is not None else (limit,)
        with self.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(
                statement + where + " ORDER BY event_id DESC LIMIT %s", params
            ).fetchall()
