# Architecture

AIGovKit is a FastAPI process with a PostgreSQL database. The versioned REST API authenticates requests and resolves a server-side
organisation schema before loading records. See [the foundation plan](foundation-plan.md). The original scoring demo is stateless and independent.

## Data and flow

1. An operator records AI tools, agents and their parent tools, assets with an
   explicit classification, role needs, and declared agent-to-asset connections.
2. A role need specifies an exact tool, asset and action. A connection specifies
   an exact agent, asset and one or more actions. Neither is proof of real access.
3. A simulation reads one inventory snapshot and passes it to a pure policy
   function. The connection scan applies that same function to each declared
   action for the supplied role. The API returns reasons and controls.
4. A human reviews recommendations and handles any decision separately.

PostgreSQL stores typed Pydantic records as JSONB under the composite key
`(kind, id)`. A single read provides a consistent snapshot per request. Writes
use parameterised SQL and atomic upserts. The bootstrap command sets up the
initial schema and can import a validated JSON file transactionally. References
may arrive out of order. A missing reference always produces a denied simulation.

## Policy 1.0.0

An exact role need and a declared connection are both required. Unknown agents,
parent tools, assets or access needs produce a deny recommendation. Restricted
assets and administrative or destructive actions also produce deny
recommendations. Otherwise confidential access and writes are medium risk.
Reads of public or internal assets are low risk. The favourable outcome is
`consider_after_review`. All outcomes carry a human approval requirement.

## Policy 1.1.0

This version also requires a registered department, an exact purpose shared by
the agent and its tool, a declared owner on both records, and a role need
matching department, purpose and scope. Older records still load. A role need
without department and purpose can only justify a legacy 1.0.0 simulation.
Use 1.1.0 for new governance workflows. Capabilities are declared metadata.

## Classification and reports

Classification rules use structured flags. Credentials or regulated sensitive
data take precedence, followed by personal data or confidential business data.
Otherwise a declared public release leads to a public suggestion and the
default is internal. Suggestions serve human review and leave inventory unchanged.

Identical validated inventory and inputs yield the same assessment regardless
of input order. A report stores its request and computed decision, policy version,
score, scoring version and timestamp. Reports remain stable as inventory changes
and have no update endpoint. They do not preserve an inventory snapshot or prove
that approval happened. The scoring rubric maps low, medium and high risks to
25, 50 and 100. These values are ordinal indicators.

## Connectors and limits

`InventoryConnector.records()` yields typed candidate records. The local JSON
connector validates the entire input before bootstrap writes it. The optional
PostgreSQL verifier returns separate permission evidence for a named role,
schema and ordinary or partitioned table. It reads catalog metadata in a
read-only transaction and distinguishes unknown objects from known objects
with no relevant grants. It covers schema usage and the table privileges
SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES and TRIGGER. It does not
evaluate row-level security, column grants, role switching or actual queries.
Operators reconcile this evidence with declarations. The verifier never
writes inventory or alters access. No connector sends data to an LLM.

Version 0.1.0 loads the inventory for each evaluation and relies on an operator
to verify declarations. It supports small inventories. Tenant keys isolate
records at the application layer. Use a separate deployment and database if
you need an infrastructure isolation boundary. Additional provider connectors, approval
workflows, audit logs and enterprise identity are future work.
