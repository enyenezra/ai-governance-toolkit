"""Operator-managed identity bindings for a single trusted issuer."""

import os
from typing import Annotated, Literal

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row
from pydantic import Field, StringConstraints

from aigovkit.models import Identifier, StrictModel

MANAGED_ROLES = Literal["reader", "editor", "reviewer", "publisher", "auditor"]
Subject = Annotated[str, StringConstraints(min_length=1, max_length=255)]
DIRECTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS public.governance_members (
    tenant_id text NOT NULL,
    member_id text NOT NULL,
    issuer text NOT NULL,
    subject text NOT NULL,
    role text NOT NULL CHECK (role IN ('reader','editor','reviewer','publisher','auditor')),
    state text NOT NULL CHECK (state IN ('active','suspended')),
    groups text[] NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    PRIMARY KEY (tenant_id, member_id),
    UNIQUE (issuer, subject)
)
"""


class MemberInput(StrictModel):
    subject: Subject
    role: MANAGED_ROLES
    state: Literal["active", "suspended"]
    groups: list[Identifier] = Field(max_length=50)
    expected_version: int = Field(ge=0, le=2_147_483_646)


def managed_member(issuer: str, subject: str) -> dict | None:
    dsn = os.environ.get("AIGOVKIT_DATABASE_URL")
    if not dsn:
        return None
    try:
        with psycopg.connect(dsn, connect_timeout=5, row_factory=dict_row) as conn:
            return conn.execute(
                """SELECT tenant_id, member_id, role, state FROM public.governance_members
                   WHERE issuer = %s AND subject = %s""",
                (issuer, subject),
            ).fetchone()
    except psycopg.Error:
        raise HTTPException(503, "Identity directory unavailable.") from None
