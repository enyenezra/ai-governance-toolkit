# OIDC access tokens and governance audit

AIGovKit accepts signed access tokens issued for this API. Configure a trusted
issuer that produces RFC 9068 access tokens with `typ=at+jwt`, `alg=RS256`,
a single API audience and a lifetime of up to one hour. The verifier checks the
signature, issuer, audience, expiry and required token claims. ID tokens and
opaque access tokens are unsupported. The feature is disabled by default.

Set these values through the deployment configuration:

| Setting | Value |
| --- | --- |
| `AIGOVKIT_OIDC_ISSUER` | Exact HTTPS issuer, including any trailing slash |
| `AIGOVKIT_OIDC_AUDIENCE` | Audience issued specifically for the AIGovKit API |
| `AIGOVKIT_OIDC_JWKS_FILE` | Absolute path to the issuer's trusted **public** JWKS |
| `AIGOVKIT_TENANTS` | Organisation and approved memberships |

Configure the JWKS from a trusted copy of the issuer's public signing keys.
The service reads the local file. It never follows URLs from tokens. Update
the public keys during issuer rotation and keep valid old keys through their
token lifetimes, unless revoking a key. Recreate the API container after
replacing a bind-mounted file. Never mount private signing keys.

Each named member entry has an `id`, `role`, and a `key`, `oidc_subject`,
or both. The subject is the exact `sub` the issuer emits **for this API**.
Configure a subject in only one membership. AIGovKit derives organisation,
role and actor ID from that local mapping. Token roles, group claims, emails
and client-supplied tenant headers have no effect. Remove a subject binding to
revoke its AIGovKit access. Keep actor IDs stable through credential rotation.
When changing issuers, revalidate all subject mappings before enabling tokens.

For example, this synthetic tenant has a token-authenticated editor and auditor:

```json
[
  {
    "id": "demo",
    "members": [
      {"id": "policy-editor", "role": "editor", "oidc_subject": "replace-with-editor-sub"},
      {"id": "governance-auditor", "role": "auditor", "oidc_subject": "replace-with-auditor-sub"}
    ]
  }
]
```

After setting the environment values, start Docker Compose with the optional
override. The JWKS file must be readable by the container's non-root account.

```sh
docker compose -f compose.yaml -f compose.oidc.yaml up --build --wait
```

Use your issuer-approved client to obtain an access token for the API.
Choose **OIDC access token** on the workspace sign-in form, or send it through
`Authorization: Bearer` in API calls. The browser keeps it in memory. API keys
remain available through `X-API-Key`. Send one credential per request.
Browser redirect sign-in and token refresh, discovery and automatic JWKS
rotation, multiple issuers, and identity provisioning remain future work.
Provider-specific tokens that lack the required access-token profile need a
separately reviewed integration.

## Audit events

A named `auditor` can open **Audit events** or call `GET /v1/audit-events`.
The endpoint reads only the auditor's organisation. Use `limit` (1–100)
and `before` with the last event ID to view older records.

The feed records successful API changes to organisation profile, inventory,
risk reports, readiness results, policy drafts, revisions, review and
publication. Each event contains the member ID (or a shared-key marker),
authentication method, action, resource reference and timestamp. Writes
and their events commit together. The feed excludes tokens, raw subjects,
policy text, notes and private acknowledgement receipts. Historic changes
are not backfilled. Offline imports, reads and denied requests are outside
the feed. It is append-only through the API. Database administrators still
control the underlying records.
