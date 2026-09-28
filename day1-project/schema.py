"""The agent's output contract.

One structured response covers all seven capabilities of the Day 1 project,
so every one of them is machine-checkable rather than buried in prose.
"""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        # 1. Classify IT support requests
        "request_type": {
            "type": "string",
            "enum": ["incident", "how_to", "policy", "unclear", "out_of_scope"],
        },
        "classification": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["database", "kubernetes", "network", "application",
                             "security", "access", "unknown"],
                },
                "affected_service": {"type": "string"},
                "environment": {
                    "type": "string",
                    "enum": ["production", "staging", "development", "unknown"],
                },
                "severity": {
                    "type": "string",
                    "enum": ["SEV-1", "SEV-2", "SEV-3", "SEV-4", "unknown"],
                },
            },
            "required": ["category", "affected_service", "environment", "severity"],
            "additionalProperties": False,
        },
        # 2. Understand incomplete questions
        "clarifying_question": {"type": ["string", "null"]},
        # 4. Generate source-grounded answers
        "answer": {"type": ["string", "null"]},
        # 5. Return citations
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["doc_id", "quote"],
                "additionalProperties": False,
            },
        },
        # 6. Refuse unsupported conclusions
        "evidence_sufficient": {"type": "boolean"},
        "refusal_reason": {"type": ["string", "null"]},
        # 7. Escalate when evidence is insufficient
        "requires_human_escalation": {"type": "boolean"},
        "escalation_reason": {"type": ["string", "null"]},
        # Injection attempts spotted inside retrieved content
        "security_events": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "request_type", "classification", "clarifying_question", "answer",
        "citations", "evidence_sufficient", "refusal_reason",
        "requires_human_escalation", "escalation_reason", "security_events",
    ],
    "additionalProperties": False,
}
