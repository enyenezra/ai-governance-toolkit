# Governance expansion

This release adds usable workflows across identity, policy management, access
governance, runtime guardrails, provider discovery, risk and operational
governance. Start from [the README](../README.md). Before upgrading, back up the
database and run `python -m aigovkit.bootstrap` or recreate the Compose API
service. The schema changes are additive. The runtime database account needs
read/write access to its configured tenant schemas and to the managed directory.
Run inside a trusted deployment with TLS. PostgreSQL is the system of record.

## Identity and access

OIDC bearer tokens continue to use the configured issuer, API audience and
mounted public JWKS. For browser SSO configure
`AIGOVKIT_SSO_AUTHORIZATION_URL`, `AIGOVKIT_SSO_TOKEN_URL`,
`AIGOVKIT_SSO_CALLBACK_URL` (HTTPS with path `/v1/sso/callback`),
`AIGOVKIT_SSO_CLIENT_ID`, and `AIGOVKIT_SSO_COOKIE_KEY`. Generate the cookie
key with `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`
and put it in the deployment secret manager. Configure
`AIGOVKIT_SSO_CLIENT_SECRET` if the provider uses client-secret POST and
`AIGOVKIT_SSO_SCOPE` if the provider requires scope beyond `openid`.
The provider must issue an RFC 9068 access token for AIGovKit to that client.
Use the documented [OIDC Compose override](oidc-audit.md). Set token and
authorisation URLs only to trusted endpoints and omit callback query strings
from proxy logs. Browser sign-in uses PKCE, encrypted Secure HttpOnly cookies,
and an Origin check on writes. Sign-out clears the local cookie. Token refresh
and federated logout remain outside this release.

Bootstrap a named `identity_admin` in the tenant's deployment configuration.
It can list managed members with `GET /v1/identity/members`, and join, change
or suspend a member using `PUT /v1/identity/members/{id}`. Supply a verified
issuer subject, role, state, groups and expected version. Keep subject bindings
and groups aligned with your identity system. This is operator-managed provisioning.
Provider SCIM and automatic synchronisation are future integrations.

Named members can request an access recommendation in the workspace or through
`POST /v1/access-requests`. Policy 1.1.0 evaluates the exact agent, role,
department, asset, action and purpose. A managed group must also match. The
requester sees their own requests. A separate reviewer sees the queue and can
decide via `POST /v1/access-decisions`. Approval rechecks group membership
and policy. Approved recommendations have a 90-day review date.
`GET /v1/access-recertifications` lists due requests. `POST` creates a linked
request and runs the policy again. Nothing grants or revokes external access.

## Policy lifecycle

- `GET /v1/policy-drafts/{id}/compare?from_version=1&to_version=2` returns
  clause-level redlines with word operations and original text.
- `GET /v1/policy-review-schedule` returns the date due for each current
  publication. It uses the published UTC date and that version's review interval.
  Poll it from your scheduling system. No notifications are sent automatically.
- Published policy detail supports authenticated Markdown, DOCX and PDF
  downloads in the workspace and at
  `GET /v1/published-policies/{id}/{version}/export/{md|docx|pdf}`.
- Named auditors and publishers can request organisation-wide aggregate
  acknowledgement coverage at
  `GET /v1/published-policies/{id}/{version}/acknowledgement-summary`.
  Counts use currently active named members. Personal receipts stay private.

## Agent guardrails and monitoring

Use a configured named `gateway` service credential scoped to
`POST /v1/guardrail-checks`. Your application must call the gate before the
protected action, halt on denial, timeout or unavailability, and prevent a
direct route around the gate. The gate returns HTTP 403 for an unknown,
suspended or denied action and HTTP 200 for an exact deployed allow rule
that still matches inventory and policy. Requests carry scope metadata.
Credentials and prompt content do not belong in the payload.

Each agent has one active exact-scope rule at this gate. An editor proposes a rule at `POST /v1/guardrail-rules`. A separate
publisher uses `POST /v1/guardrail-deployments` to deploy, roll back to a
prior rule, suspend or resume that agent at the gate. Publish against the
expected deployment version. Check IDs refer to actual decisions at this
endpoint. A publisher can record a comparison with the expected result using
`POST /v1/guardrail-verifications`. Verification covers this gate only.
Suspension stops decisions through this gate. External agents, cloud
permissions and upstream services require their own integration to enforce
or revoke access.

Monitor submitted agent activity, credential rotation dates, control tests,
risks, incidents, training and discovery via `GET /v1/monitoring`.
A named `observer` can write new signal and discovery records without read
access to tenant inventory. Operators can integrate their own telemetry
sender. No credentials or prompt content are stored in these registers.

## Provider discovery

Use `python -m aigovkit.provider_discovery PROVIDER` with a separately scoped
credential for each run. The CLI returns a bounded page of metadata with a
`partial` flag for truncated results. Review records before importing or
submitting them as discovery evidence. These connectors do not modify upstream
systems, fetch user content, or invoke MCP tools. Live production access and
service scopes must be verified in the deploying organisation.

| Provider | Metadata collected | Configuration |
| --- | --- | --- |
| `entra` | Application service principals | Graph read token. [Service principals](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-list?view=graph-rest-1.0) |
| `microsoft365` | Subscribed SKUs | Graph read token. [Subscribed SKUs](https://learn.microsoft.com/graph/api/subscribedsku-list?view=graph-rest-1.0) |
| `purview` | Search result asset IDs, types and names | Read token and `AIGOVKIT_PURVIEW_URL`. [Data Map search](https://learn.microsoft.com/en-us/rest/api/purview/datamapdataplane/discovery/query?view=rest-purview-datamapdataplane-2023-09-01) |
| `azure` | Resource metadata | ARM read token and `AIGOVKIT_AZURE_SUBSCRIPTION`. [List resources](https://learn.microsoft.com/en-us/rest/api/resources/resources/list?view=rest-resources-2021-04-01) |
| `aws-iam` | IAM role IDs and names | Scoped AWS SDK credential chain. [List roles](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/iam/client/list_roles.html) |
| `mcp` | Tool names | `AIGOVKIT_MCP_URL`, HTTPS Streamable HTTP, and a read token if required. [MCP transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) |
| `ai-gateway` | Model IDs | Read token and `AIGOVKIT_GATEWAY_MODELS_URL` pointing to a compatible models endpoint. [Models API](https://developers.openai.com/api/reference/resources/models/methods/list) |

Supply HTTP connector tokens via `AIGOVKIT_CONNECTOR_TOKEN`. Never reuse a
broad token across providers or log its value. To submit the bounded page as
discovery observations, add `--submit` and set `AIGOVKIT_OBSERVATION_API`
to your HTTPS workspace base URL and `AIGOVKIT_OBSERVER_KEY` to its separately
scoped observer key. You can schedule that command with your existing job
runner. A provider record is submitted once per UTC day. Submission creates
reviewable observations and leaves inventory and upstream systems unchanged.

## Risk, readiness and operations

Use the Governance registers screen or `/v1/registers/{kind}`. Risk entries
record a system, owner, scoring inputs, treatment owner, due date, evidence
references and previous versions. Inherent score is likelihood × impact.
Residual score rounds that value up after applying the recorded percentage
reduction from controls. Control checks record evidence and reviewer judgement
separately. No score proves compliance. Adaptive readiness 2.0 adds questions
based on the organisation adoption stage and declared sensitive-data handling.
Submit answers against the applicable question set and see ranked gaps.

The versioned framework catalogue links primary sources and controls for
qualified applicability review. Use the `framework_assessment` register to
record a tenant-specific decision, evidence and mapped controls. It includes no copied standards text and is
not a certification or automated regulatory opinion.

Incident cases progress through open, contained, recovering and resolved, with
versioned updates, system references, evidence references and ownership.
Vendor assessments cover hosting, data reuse, subprocessors and evidence.
Training assignments track due dates and completion evidence. Discovery
observations and monitoring signals accept metadata from scoped collectors.
This release provides registers, intake and live summaries. It does not
supply automated discovery agents, external runtime collectors, full
courseware or provider-specific containment playbooks.
