"""Verify effective table-level PostgreSQL privileges using a read-only connection."""

import argparse
import os
from typing import Literal

import psycopg

from aigovkit.models import StrictModel

Privilege = Literal[
    "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"
]
PRIVILEGES: tuple[Privilege, ...] = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)


class PermissionEvidence(StrictModel):
    source: Literal["postgresql"] = "postgresql"
    role: str
    schema_name: str
    table: str
    schema_usage: bool
    table_privileges: list[Privilege]


class PostgresPermissionConnector:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def verify(self, role: str, schema: str, table: str) -> PermissionEvidence | None:
        with psycopg.connect(self.dsn, connect_timeout=5) as conn:
            conn.read_only = True
            row = conn.execute(
                """
                SELECT has_schema_privilege(r.oid, n.oid, 'USAGE'),
                       ARRAY(
                           SELECT p.privilege
                           FROM unnest(%s::text[]) WITH ORDINALITY AS p(privilege, position)
                           WHERE has_table_privilege(r.oid, c.oid, p.privilege)
                           ORDER BY p.position
                       )
                FROM pg_roles AS r
                CROSS JOIN pg_namespace AS n
                JOIN pg_class AS c ON c.relnamespace = n.oid
                WHERE r.rolname = %s AND n.nspname = %s AND c.relname = %s
                  AND c.relkind IN ('r', 'p')
                """,
                (list(PRIVILEGES), role, schema, table),
            ).fetchone()
        if row is None:
            return None
        return PermissionEvidence(
            role=role,
            schema_name=schema,
            table=table,
            schema_usage=row[0],
            table_privileges=row[1],
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role")
    parser.add_argument("schema")
    parser.add_argument("table")
    args = parser.parse_args()
    dsn = os.environ.get("AIGOVKIT_POSTGRES_CONNECTOR_URL")
    if not dsn:
        parser.exit(2, "Set AIGOVKIT_POSTGRES_CONNECTOR_URL to a scoped connection.\n")
    try:
        result = PostgresPermissionConnector(dsn).verify(
            args.role, args.schema, args.table
        )
    except psycopg.Error:
        parser.exit(2, "Unable to verify permissions against PostgreSQL.\n")
    if result is None:
        parser.exit(1, "The role or table is unknown.\n")
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
