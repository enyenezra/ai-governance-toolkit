# Evidence-backed detection and temporary gate containment

The existing scheduled dispatcher calls `POST /v1/security-detections/run`
with its named scheduler key. A named editor can also run detection from
**Security findings**. No new scheduler is required. Run bootstrap during
deployment to add the evidence scan index.

## Detection rules

| Rule | Evidence | Result |
| --- | --- | --- |
| Repeated gate denials | At least three denied agent scope checks in one UTC hour | Medium finding |
| Denied privileged action | A logged denied admin or delete action | High finding and incident |
| Model outside allowlist | A provider check denies a model under a deployed allowlist | Medium finding |

The detector looks at the current and previous UTC hour. A repeated run
preserves the first finding for the same agent, rule, version and hour.
Counts and up to ten evidence identifiers reflect the first qualifying run.
Denials caused by temporary containment do not trigger further gate findings.
High-severity findings open cases with linked evidence. Set
`AIGOVKIT_INCIDENT_OWNER` to the triage owner for scheduled runs. The findings
contain identifiers and decisions. Prompts and response contents are excluded.
Detection coverage starts when the relevant action and decision metadata
become available.

## Control workflow

1. A named editor previews a restriction using a finding ID and a duration of
   1–60 minutes. Preview does not create records or affect a gateway.
2. The editor submits a request. A different named publisher approves it.
   Approval expires after 15 minutes.
3. An independent publisher executes the request before approval expires.
   Execution requires the operator to set `AIGOVKIT_CONTAINMENT_ENABLED=yes`.
   A retry returns the original execution result without extending expiry.
4. The AIGovKit gate denies that agent's operations while the restriction is
   active. Other gate policies remain in effect. The gate ignores the temporary
   restriction after its expiry. A publisher can roll back beforehand.
5. Audit actions record approval, execution, rollback and rejected transitions.
   The gate records the restriction ID on blocked checks.

The operator switch disables new executions. Existing temporary restrictions
will expire or can be rolled back by a publisher. The control is local to
AIGovKit's gate. It does not change cloud IAM or revoke external credentials.
Automatic execution, externally validated telemetry and broader playbooks remain
future work.

## API

- `GET /v1/security-findings` lists findings.
- `GET /v1/containment` lists requests and effective status.
- `POST /v1/containment` previews or requests a restriction with
  `finding_id`, `minutes` and `dry_run` (default true).
- `POST /v1/containment/{id}/transition` accepts `approve`, `execute`
  or `rollback` in the `action` field.
