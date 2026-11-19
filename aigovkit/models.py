from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
Action = Literal["read", "write", "delete", "admin"]
Kind = Literal["tool", "agent", "asset", "role_need", "connection", "department"]
Classification = Literal["public", "internal", "confidential", "restricted"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Entry(StrictModel):
    id: Identifier
    name: str = Field(min_length=1, max_length=120)


class Department(Entry):
    kind: Literal["department"]


class AIEntry(Entry):
    owner: Identifier | None = None
    purposes: list[Identifier] = Field(default_factory=list, max_length=30)
    capabilities: list[Identifier] = Field(default_factory=list, max_length=30)


class Tool(AIEntry):
    kind: Literal["tool"]


class Agent(AIEntry):
    kind: Literal["agent"]
    tool_id: Identifier


class Asset(Entry):
    kind: Literal["asset"]
    classification: Classification


class Scope(StrictModel):
    tool_id: Identifier
    asset_id: Identifier
    action: Action


class RoleNeed(Entry):
    kind: Literal["role_need"]
    role: Identifier
    scope: Scope
    department_id: Identifier | None = None
    purpose: Identifier | None = None


class Connection(Entry):
    kind: Literal["connection"]
    agent_id: Identifier
    asset_id: Identifier
    actions: list[Action] = Field(min_length=1, max_length=4)


Record = Annotated[
    Tool | Agent | Asset | RoleNeed | Connection | Department,
    Field(discriminator="kind"),
]


PolicyVersion = Literal["1.0.0", "1.1.0"]


class Simulation(StrictModel):
    role: Identifier
    agent_id: Identifier
    asset_id: Identifier
    action: Action
    policy_version: PolicyVersion = "1.0.0"
    department_id: Identifier | None = None
    purpose: Identifier | None = None

    @model_validator(mode="after")
    def check_context_version(self) -> "Simulation":
        if self.policy_version == "1.0.0" and (self.department_id or self.purpose):
            raise ValueError("Department and purpose require policy version 1.1.0")
        return self


class Assessment(StrictModel):
    policy_version: str
    disposition: Literal["deny", "consider_after_review"]
    human_approval_required: Literal[True] = True
    risk: Literal["low", "medium", "high"]
    reasons: list[str]
    controls: list[str]


class ConnectionAssessment(StrictModel):
    connection_id: Identifier
    action: Action
    assessment: Assessment


class ClassificationInput(StrictModel):
    approved_for_public_release: bool
    contains_personal_data: bool
    contains_confidential_business_data: bool
    contains_credentials_or_regulated_sensitive_data: bool


class ClassificationSuggestion(StrictModel):
    classification: Classification
    rules_version: Literal["1.0.0"] = "1.0.0"
    reason: str
    human_approval_required: Literal[True] = True


class RiskReport(StrictModel):
    id: Identifier
    created_at: datetime
    request: Simulation
    assessment: Assessment
    risk_score: int = Field(ge=0, le=100)
    scoring_version: Literal["1.0.0"] = "1.0.0"
