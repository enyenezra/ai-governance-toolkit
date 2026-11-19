"""A deny-by-default policy decision gate for trusted runtime callers."""

from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import Field

from aigovkit.api import Store, load
from aigovkit.foundation import Actor, Limit, Offset, database_call
from aigovkit.models import Agent, Identifier, Simulation, StrictModel
from aigovkit.policy import evaluate
from aigovkit.policy_review import named_member
from aigovkit.tenancy import authenticate

router = APIRouter(prefix="/v1", dependencies=[Depends(authenticate)])


class ProposedRule(StrictModel):
    scope: Simulation
    decision: Literal["allow", "deny"]


class Deployment(StrictModel):
    agent_id: Identifier
    revision_id: Identifier | None = None
    operation: Literal["deploy", "rollback", "suspend", "resume"]
    expected_version: int = Field(ge=0, le=2_147_483_646)


class Verification(StrictModel):
    check_id: Identifier
    expected: Literal["allow", "deny"]


def get(cursor, kind: str, key: str):
    row = cursor.execute(
        "SELECT body FROM foundation_documents WHERE kind=%s AND id=%s", (kind, key)
    ).fetchone()
    return row["body"] if row else None


def insert(cursor, kind: str, key: str, body: dict) -> None:
    cursor.execute(
        "INSERT INTO foundation_documents (kind,id,body) VALUES (%s,%s,%s)",
        (kind, key, Jsonb(body)),
    )


@router.post("/guardrail-rules", status_code=201)
def propose(request: ProposedRule, actor: Actor, store: Store) -> dict:
    author = named_member(actor, "editor")
    if request.scope.policy_version != "1.1.0" or not all(
        [request.scope.department_id, request.scope.purpose]
    ):
        raise HTTPException(422, "Specify a department, purpose and policy 1.1.0.")
    if not any(
        isinstance(item, Agent) and item.id == request.scope.agent_id
        for item in load(store)
    ):
        raise HTTPException(422, "Register the agent first.")
    rule = {"id": uuid4().hex, "author": author, **request.model_dump(mode="json")}
    database_call(store.put_document, "guardrail_rule", rule["id"], rule)
    return rule


@router.post("/guardrail-deployments")
def deploy(request: Deployment, actor: Actor, store: Store) -> dict:
    publisher = named_member(actor, "publisher")

    def apply():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(current_schema() || %s,0))",
                (f":gate:{request.agent_id}",),
            )
            current = get(cursor, "guardrail_current", request.agent_id)
            previous_version = current["version"] if current else 0
            if request.expected_version != previous_version:
                raise HTTPException(409, "Load the current gate version first.")
            selected = current["revision_id"] if current else None
            suspended = current["suspended"] if current else False
            if request.operation in {"suspend", "resume"}:
                if request.revision_id is not None:
                    raise HTTPException(422, "Suspend and resume do not select a rule.")
                suspended = request.operation == "suspend"
            else:
                rule = (
                    get(cursor, "guardrail_rule", request.revision_id)
                    if request.revision_id
                    else None
                )
                if not rule or rule["scope"]["agent_id"] != request.agent_id:
                    raise HTTPException(404, "Agent rule not found.")
                if rule["author"] == publisher:
                    raise HTTPException(403, "A rule author cannot deploy that rule.")
                if (
                    request.operation == "rollback"
                    and not cursor.execute(
                        """SELECT 1 FROM foundation_documents WHERE kind='guardrail_deployment'
                       AND body->>'agent_id'=%s AND body->>'revision_id'=%s LIMIT 1""",
                        (request.agent_id, rule["id"]),
                    ).fetchone()
                ):
                    raise HTTPException(
                        409, "Rollback requires a previously deployed rule."
                    )
                selected = rule["id"]
            state = {
                "agent_id": request.agent_id,
                "revision_id": selected,
                "suspended": suspended,
                "publisher": publisher,
                "operation": request.operation,
                "version": previous_version + 1,
                "target": "aigovkit_gateway",
            }
            cursor.execute(
                """INSERT INTO foundation_documents (kind,id,body)
                   VALUES ('guardrail_current',%s,%s)
                   ON CONFLICT (kind,id) DO UPDATE SET body=EXCLUDED.body""",
                (request.agent_id, Jsonb(state)),
            )
            insert(
                cursor,
                "guardrail_deployment",
                f"{request.agent_id}:{state['version']}",
                state,
            )
            store.audit(
                cursor,
                f"guardrail.{request.operation}",
                "agent",
                request.agent_id,
                state["version"],
            )
            return state

    return database_call(apply)


@router.get("/guardrails")
def deployments(store: Store, offset: Offset = 0, limit: Limit = 20) -> list[dict]:
    return database_call(store.documents, "guardrail_current", offset, limit)


@router.get("/guardrail-rules")
def rules(store: Store, offset: Offset = 0, limit: Limit = 20) -> list[dict]:
    return database_call(store.documents, "guardrail_rule", offset, limit)


@router.post("/guardrail-checks")
def gateway(request: Simulation, actor: Actor, store: Store) -> JSONResponse:
    named_member(actor, "gateway")
    records = load(store)

    def check():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock_shared(hashtextextended(current_schema() || %s,0))",
                (f":gate:{request.agent_id}",),
            )
            state = get(cursor, "guardrail_current", request.agent_id)
            decision, reason = "deny", "No active rule covers this request."
            if state and state["suspended"]:
                reason = "This agent is suspended at the AIGovKit gate."
            elif state and state["revision_id"]:
                rule = get(cursor, "guardrail_rule", state["revision_id"])
                if rule and rule["scope"] == request.model_dump(mode="json"):
                    assessment = evaluate(request, records)
                    if (
                        rule["decision"] == "allow"
                        and assessment.disposition == "consider_after_review"
                    ):
                        decision, reason = (
                            "allow",
                            "Published gate rule and current inventory match.",
                        )
                    else:
                        reason = "The rule or current inventory denies this request."
            evidence = {
                "id": uuid4().hex,
                "agent_id": request.agent_id,
                "decision": decision,
                "reason": reason,
                "deployment_version": state["version"] if state else None,
            }
            insert(cursor, "guardrail_check", evidence["id"], evidence)
            store.audit(
                cursor, f"guardrail.{decision}", "guardrail_check", evidence["id"]
            )
            return evidence

    result = database_call(check)
    return JSONResponse(
        result, status_code=200 if result["decision"] == "allow" else 403
    )


@router.post("/guardrail-verifications", status_code=201)
def verify(request: Verification, actor: Actor, store: Store) -> dict:
    verifier = named_member(actor, "publisher")

    def record():
        with store.connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
            observation = get(cursor, "guardrail_check", request.check_id)
            if not observation or observation["deployment_version"] is None:
                raise HTTPException(404, "No deployed gate decision with that ID.")
            result = {
                "id": uuid4().hex,
                **request.model_dump(mode="json"),
                "observed": observation["decision"],
                "agent_id": observation["agent_id"],
                "deployment_version": observation["deployment_version"],
                "verifier": verifier,
                "matched": request.expected == observation["decision"],
                "target": "aigovkit_gateway",
            }
            insert(cursor, "guardrail_verification", result["id"], result)
            store.audit(
                cursor, "guardrail.verified", "guardrail_check", request.check_id
            )
            return result

    return database_call(record)


@router.get("/guardrail-verifications")
def verification_history(
    store: Store, offset: Offset = 0, limit: Limit = 20
) -> list[dict]:
    return database_call(store.documents, "guardrail_verification", offset, limit)


@router.get("/guardrail-deployments")
def deployment_history(
    store: Store, offset: Offset = 0, limit: Limit = 20
) -> list[dict]:
    return database_call(store.documents, "guardrail_deployment", offset, limit)
