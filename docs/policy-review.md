# Policy revision and independent review

The workflow uses individually provisioned API keys. Add a `members` array to
each organisation in `AIGOVKIT_TENANTS`. Each member has a stable `id`, one
`role` (`reader`, `editor`, `reviewer`, or `publisher`), and a separately generated
`key`. Store keys in a secret manager. Use separate people for authoring and
review. Keep member IDs stable when rotating credentials and never reassign an
old member ID to another person. The legacy editor and reader keys still work
for their original operations. Policy revisions and decisions require named keys.

Run `python -m aigovkit.bootstrap` (or restart Compose with the new image) to
create the revision and review event tables for all configured organisations.
These tables are additive. Existing generated drafts become the initial
snapshot when a named editor writes the first revision.

In the workspace policy library, an editor can edit clause text, save a
revision and submit it. An independent reviewer can approve or request changes
and must give a reason. Reviewers cannot author revisions or write other
governance records. The original creator and the revision author cannot review
the revision even if their role changes. A submitted revision cannot be
replaced before review. Readers can inspect version history and decisions.

| Method and path | Operation |
| --- | --- |
| `GET /v1/policy-drafts/{id}/revisions` | List version numbers, authors and timestamps |
| `GET /v1/policy-drafts/{id}/revisions/{version}` | View the snapshot, state and review events |
| `POST /v1/policy-drafts/{id}/revisions` | Save `clause_texts` keyed by clause ID with the `expected_version` (0 for the initial snapshot) |
| `POST /v1/policy-drafts/{id}/revisions/{version}/submit` | Submit the latest version as its author |
| `POST /v1/policy-reviews` | Record `draft_id`, `version`, `action` (`approved` or `changes_requested`) and `note` |

PostgreSQL serialises operations per policy draft. Stale or repeated
transitions return 409. New revisions use a new row, so an approved snapshot
and its attributable review events remain readable after subsequent edits.
Audit events apply to this workflow. Database administrators retain direct
database access. An approval is an internal decision. See [publication](policy-publication.md) for publishing and acknowledgements.
Enforcement, OIDC and cryptographically verifiable audit exports remain future work.
