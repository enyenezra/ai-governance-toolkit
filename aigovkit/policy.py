from collections.abc import Iterable

from aigovkit.models import (
    Agent,
    Assessment,
    Asset,
    Connection,
    Department,
    Record,
    RoleNeed,
    Simulation,
    Tool,
)

LEGACY_POLICY = "1.0.0"
CONTEXT_POLICY = "1.1.0"
POLICY_VERSIONS = [LEGACY_POLICY, CONTEXT_POLICY]


def evaluate(request: Simulation, inventory: Iterable[Record]) -> Assessment:
    records = list(inventory)
    agent = next(
        (
            entry
            for entry in records
            if isinstance(entry, Agent) and entry.id == request.agent_id
        ),
        None,
    )
    asset = next(
        (
            entry
            for entry in records
            if isinstance(entry, Asset) and entry.id == request.asset_id
        ),
        None,
    )
    tool = next(
        (
            entry
            for entry in records
            if isinstance(entry, Tool)
            and agent is not None
            and entry.id == agent.tool_id
        ),
        None,
    )
    declared = any(
        isinstance(entry, Connection)
        and entry.agent_id == request.agent_id
        and entry.asset_id == request.asset_id
        and request.action in entry.actions
        for entry in records
    )
    needed = agent is not None and any(
        isinstance(entry, RoleNeed)
        and entry.role == request.role
        and entry.scope.tool_id == agent.tool_id
        and entry.scope.asset_id == request.asset_id
        and entry.scope.action == request.action
        and entry.department_id == request.department_id
        and entry.purpose == request.purpose
        for entry in records
    )

    reasons = []
    controls = []
    if request.policy_version == CONTEXT_POLICY:
        if not any(
            isinstance(entry, Department) and entry.id == request.department_id
            for entry in records
        ):
            reasons.append("The request has no registered department.")
            controls.append("Identify and verify the requesting department.")
        if not request.purpose or not (
            agent
            and tool
            and request.purpose in agent.purposes
            and request.purpose in tool.purposes
        ):
            reasons.append(
                "The purpose is missing or undeclared for this tool or agent."
            )
            controls.append(
                "Restrict access to a documented purpose shared by the tool and agent."
            )
        if agent and tool and (not tool.owner or not agent.owner):
            reasons.append("The tool or agent does not have a declared owner.")
            controls.append("Assign accountable owners before reviewing access.")
    if tool is None or asset is None:
        reasons.append("Agent, parent tool or asset is unknown.")
        controls.append("Register and verify the missing inventory entries.")
    if not declared:
        reasons.append("No declared agent connection covers this action on this asset.")
        controls.append("Verify the agent's exact asset and action permissions.")
    if not needed:
        reasons.append("No matching role need covers this tool, asset and action.")
        controls.append(
            "Remove unnecessary access or document its business justification for review."
        )
    if request.action in {"admin", "delete"}:
        reasons.append(
            "Administrative and destructive actions are denied by this policy."
        )
        controls.append(
            "Use narrower permissions and route exceptional access to a separate review."
        )
    if asset is not None and asset.classification == "restricted":
        reasons.append("Restricted assets are denied by this policy.")
        controls.append(
            "Use a lower-sensitivity substitute or a separately reviewed workflow."
        )

    if reasons:
        return Assessment(
            policy_version=request.policy_version,
            disposition="deny",
            risk="high",
            reasons=reasons,
            controls=controls,
        )

    sensitive = asset is not None and asset.classification == "confidential"
    higher_risk = sensitive or request.action == "write"
    return Assessment(
        policy_version=request.policy_version,
        disposition="consider_after_review",
        risk="medium" if higher_risk else "low",
        reasons=[
            "A declared connection and an exact role need match."
            if request.policy_version == LEGACY_POLICY
            else "The connection, department, role and purpose match the declared scope.",
            "The request needs additional scrutiny for confidential data or write access."
            if higher_risk
            else "The request is scoped to a lower-sensitivity read.",
        ],
        controls=[
            "Limit access to the exact asset and action, and record a human approval.",
            "Set an expiry and review access before renewing it.",
        ],
    )
