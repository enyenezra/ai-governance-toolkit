# Policy publication and acknowledgements

Assign a named `publisher` to the organisation in `AIGOVKIT_TENANTS`. The
publisher must be different from the original author, revision author and
approving reviewer. Use separate individuals and stable member IDs. Run
`python -m aigovkit.bootstrap` or restart Compose with the updated image to add
the PostgreSQL tables before use.

A publisher opens the approved revision in the Policy Library and selects
**Publish approved revision**. Only the latest approved revision is eligible.
A draft or approval does not replace a published version. A newer version takes
effect after its own publication and previous versions stay available by ID.
Publication makes the snapshot available in the tenant workspace. It does not
send notifications, change external permissions, or deploy a control.

Any named member can open **Published policies** and acknowledge the current
version. The acknowledgement records the member, exact version and first
acknowledgement time. A repeat returns the existing receipt. A new publication
requires its own acknowledgement. Shared keys cannot acknowledge, and receipts
are visible only to the member who recorded them. Reporting completion across
people and unpublishing remain future work.

| Method and path | Behaviour |
| --- | --- |
| `POST /v1/policy-publications` | Publish using `draft_id` and `version`. Requires a named publisher. |
| `GET /v1/published-policies` | List the current published version of each policy. Supports pagination. |
| `GET /v1/published-policies/{draft_id}/{version}` | Read a published snapshot, current status and your acknowledgement time. |
| `POST /v1/policy-acknowledgements` | Acknowledge the current `draft_id` and `version`. |
| `GET /v1/policy-acknowledgements` | List your acknowledgement receipts. Supports pagination. |
