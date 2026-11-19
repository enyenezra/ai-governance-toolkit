# Preliminary AI use-case screening

`POST /v1/use-case-screenings` extends AIGovKit with an **additive, versioned,
deterministic questionnaire-based assessment**. It helps people identify
governance questions *before* registering agent-to-asset connections. It does
not change existing access-policy outcomes.

The request accepts a **user-approved, non-sensitive short use-case summary**
(20–3000 characters), AI type, provider, optional model name, deployment
method, autonomy, personal-data processing, decision impact, human oversight
and external tool use.

Example:

```bash
curl -X POST http://127.0.0.1:8000/v1/use-case-screenings \
  -H "X-API-Key: $AIGOVKIT_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"description":"A synthetic agent proposes invoices for staff review.","ai_type":"agent","provider":"example-provider","deployment":"self_hosted","autonomy":"human_approved","personal_data":false,"high_stakes":false,"human_review":true,"external_tools":true}'
```

Response: screening version, assessment type, preliminary review priority,
mandatory human review, evidence-verified flag (always false), findings and
explicit limitations. Review priorities are not measured probabilities.

## Privacy and limitations

- The checks run in-process; no external AI API, file upload or storage is added.
- The description is **not echoed** in the result. This is **not anonymisation**.
  Client, proxy and infrastructure logging remain separate operational concerns.
- Unknown answers are flagged, never assumed to be safe.
- This endpoint does not inspect uploaded documents, infer facts from prose,
  technically verify controls, change permissions, provide regulatory advice
  or certify AI safety.
- The existing `/v1` API-key protection applies. A shared API key does not
  provide multi-user authorisation; follow `SECURITY.md`.
- Do not provide confidential information, sensitive records or secrets.

## Future separately reviewed work

1. Reviewed local redaction and secure document ingestion.
2. Evidence submissions and a governed reviewer workflow.
3. Mapping screen outcomes into the existing inventory and access engine.
4. A simple browser intake form after privacy and authentication review.
