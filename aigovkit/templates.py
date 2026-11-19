"""Structured clauses used for deterministic draft generation."""

CONTROLS = {
    "CTRL-INVENTORY": "Record the system, owner, purpose and review date.",
    "CTRL-ACCESS": "Assess exact permissions against approved role needs.",
    "CTRL-DATA": "Classify data and verify permitted destinations before disclosure.",
    "CTRL-APPROVAL": "Record an authorised human decision for high-impact actions.",
    "CTRL-TEST": "Test material changes and record the result before release.",
    "CTRL-SUPPLIER": "Assess suppliers and keep assurance evidence.",
    "CTRL-INCIDENT": "Record incidents and follow the agreed escalation procedure.",
    "CTRL-TRAINING": "Assign relevant training and keep completion evidence.",
    "CTRL-EVIDENCE": "Record control tests and retain evidence according to policy.",
}

TEMPLATES = {
    "acceptable-use": (
        "Organisation-wide AI Acceptable Use Policy",
        (
            (
                "01",
                "CTRL-INVENTORY",
                "Use registered AI systems for an approved business purpose.",
            ),
            (
                "02",
                "CTRL-DATA",
                "Check the data classification and destination before sharing any data.",
            ),
        ),
    ),
    "generative-ai": (
        "Generative AI Usage Policy",
        (
            (
                "01",
                "CTRL-DATA",
                "Submit organisational information only to approved services and scopes.",
            ),
            (
                "02",
                "CTRL-APPROVAL",
                "Assign a human reviewer to verify material outputs before use.",
            ),
        ),
    ),
    "data-protection": (
        "AI Data Protection Policy",
        (
            (
                "01",
                "CTRL-DATA",
                "Classify AI inputs and outputs and record the permitted destinations.",
            ),
            (
                "02",
                "CTRL-EVIDENCE",
                "Document retention, deletion and access reviews for AI-held data.",
            ),
        ),
    ),
    "agent-security": (
        "AI Agent Security Policy",
        (
            (
                "01",
                "CTRL-ACCESS",
                "Declare each agent identity and its exact tool and data permissions.",
            ),
            (
                "02",
                "CTRL-APPROVAL",
                "Require approval before destructive or privileged agent actions.",
            ),
        ),
    ),
    "access-control": (
        "AI Access Control Policy",
        (
            (
                "01",
                "CTRL-ACCESS",
                "Approve only the asset and action needed for the documented role.",
            ),
            (
                "02",
                "CTRL-EVIDENCE",
                "Set access expiry and record periodic recertification decisions.",
            ),
        ),
    ),
    "risk-management": (
        "AI Risk Management Policy",
        (
            (
                "01",
                "CTRL-INVENTORY",
                "Assign an accountable owner for every assessed AI system.",
            ),
            (
                "02",
                "CTRL-APPROVAL",
                "Record treatment decisions and obtain approval for residual risk.",
            ),
        ),
    ),
    "procurement": (
        "AI Procurement & Vendor Policy",
        (
            (
                "01",
                "CTRL-SUPPLIER",
                "Review data handling, subprocessors, hosting and exit terms.",
            ),
            (
                "02",
                "CTRL-APPROVAL",
                "Obtain recorded approval before supplier onboarding.",
            ),
        ),
    ),
    "incident-response": (
        "AI Incident Response Plan",
        (
            (
                "01",
                "CTRL-INCIDENT",
                "Record the affected system, severity, owner and escalation timeline.",
            ),
            (
                "02",
                "CTRL-EVIDENCE",
                "Preserve relevant evidence and record containment and recovery.",
            ),
        ),
    ),
    "human-oversight": (
        "AI Human Oversight Policy",
        (
            (
                "01",
                "CTRL-APPROVAL",
                "Define high-impact decisions and assign authorised reviewers.",
            ),
            (
                "02",
                "CTRL-EVIDENCE",
                "Keep a record of each decision, rationale and exception.",
            ),
        ),
    ),
    "ai-training": (
        "AI Training & Literacy Policy",
        (
            (
                "01",
                "CTRL-TRAINING",
                "Assign role-appropriate AI literacy and security training.",
            ),
            (
                "02",
                "CTRL-EVIDENCE",
                "Review completion records and resolve overdue assignments.",
            ),
        ),
    ),
    "development": (
        "AI Development & Deployment Policy",
        (
            (
                "01",
                "CTRL-TEST",
                "Test security, privacy, reliability and intended use before release.",
            ),
            (
                "02",
                "CTRL-APPROVAL",
                "Review material changes and retain release approval evidence.",
            ),
        ),
    ),
    "monitoring": (
        "AI Monitoring & Audit Policy",
        (
            (
                "01",
                "CTRL-EVIDENCE",
                "Define monitoring scope and verify controls at agreed intervals.",
            ),
            (
                "02",
                "CTRL-INCIDENT",
                "Triage observed violations and record remediation owners.",
            ),
        ),
    ),
}
