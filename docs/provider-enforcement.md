# Provider enforcement and coverage

Register a provider in **Provider enforcement** or with
`POST /v1/providers/{id}`. Use a named editor, an HTTPS endpoint for reference,
registered model IDs and a named gateway identity. Provision the gateway's
own AIGovKit key through the existing tenant configuration. Manage provider
credentials in the application being protected.

An independent publisher deploys an explicit allowlist with
`POST /v1/provider-deployments/{id}`. The initial expected version is zero.
Supply the current revision when replacing a deployment. Supply `rollback_to`
to create a new deployment from the earlier allowlist. A deployment with an
empty allowlist denies models.

Wrap a dedicated OpenAI-compatible JSON route with
`aigovkit.model_gate_adapter.ModelEnforcedRoutes`:

```python
protected_app = ModelEnforcedRoutes(
    upstream_app,
    "https://governance.example.invalid",
    gateway_key,
    "approved-provider",
    {("POST", "/v1/responses"): approved_scope},
)
```

The operator provides `approved_scope` in the existing policy 1.1.0
simulation shape. Keep authentication and provider forwarding inside the
protected upstream app. It must honour the original model field and use
the fixed, registered provider associated with the route. Prevent clients
from bypassing the wrapper or selecting a different upstream downstream.
The wrapper accepts uncompressed JSON up to 1 MiB. It denies unknown models,
gate failures and policy denials. The request body reaches the app only
after approval. The app must independently secure authentication, routing,
output handling and request limits.

Named auditors and publishers can inspect check IDs at
`GET /v1/provider-checks/{id}`. A publisher records one allowed and one denied
check from the current deployment with `POST /v1/provider-verifications/{id}`.
The result verifies observed gateway decisions. A new deployment resets this
verification. No metadata about the request's prompt or response is included
in the recorded checks.

The gateway supports allow and deny, model allowlisting, request interception,
metadata logging, deployment and rollback. Native Azure OpenAI, Anthropic,
Gemini, Bedrock, Copilot and MCP administration is unsupported. Generic
OpenAI-compatible, internal and self-hosted routes are supported when
explicitly integrated. Redaction, output filtering, costs, provider-native
policy rollout and external agent suspension are outside this slice.
