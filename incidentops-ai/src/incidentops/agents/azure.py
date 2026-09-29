"""Real Azure-backed implementation of AgentSuite.

Reuses the exact azure-ai-agents patterns proven in
azure-agent-demo-setup/day1/lab5_grounded_agent.py (RAG grounding) and
day2/lab7_read_only_tools.py (structured JSON via response_format) —
verified working against live Azure resources in that repo. Each method
here creates one short-lived agent, runs one request, parses a
schema-enforced JSON reply, and deletes the agent — same lifecycle as
every lab script.
"""
import json
import time

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import (
    MessageRole,
    ResponseFormatJsonSchema,
    ResponseFormatJsonSchemaType,
)

from incidentops.models import (
    CommunicationDraft,
    DiagnosisResult,
    RemediationProposal,
    TriageResult,
)

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["database", "network", "application", "security", "unknown"]},
        "affected_service": {"type": "string"},
        "severity": {"type": "string", "enum": ["SEV-1", "SEV-2", "SEV-3", "SEV-4"]},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["category", "affected_service", "severity", "evidence"],
    "additionalProperties": False,
}

DIAGNOSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause_hypothesis": {"type": "string"},
        "supporting_doc_ids": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["root_cause_hypothesis", "supporting_doc_ids", "confidence"],
    "additionalProperties": False,
}

REMEDIATION_SCHEMA = {
    "type": "object",
    "properties": {
        # Constrained to exactly the actions executor.py knows how to
        # execute (StubActionExecutor.SUPPORTED_ACTIONS /
        # AzureFunctionActionExecutor.ACTION_TO_ROUTE). Found via the
        # security attack simulation: without this enum, 2 of 5 adversarial
        # requests produced plausible-but-nonstandard action strings
        # (e.g. 'restart_service_gracefully_with_oncall_approval') that
        # the executor would reject outright — safe, but an avoidable gap.
        "action": {"type": "string", "enum": ["restart_service", "escalate_to_human"]},
        "scope": {"type": "string"},
        "justification": {"type": "string"},
    },
    "required": ["action", "scope", "justification"],
    "additionalProperties": False,
}

COMMUNICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "audience": {"type": "string"},
        "message": {"type": "string"},
    },
    "required": ["audience", "message"],
    "additionalProperties": False,
}


def _schema_format(name: str, schema: dict) -> ResponseFormatJsonSchemaType:
    return ResponseFormatJsonSchemaType(json_schema=ResponseFormatJsonSchema(name=name, schema=schema))


def _run_once(client: AgentsClient, instructions: str, schema_name: str, schema: dict,
               model: str, user_content: str, retries: int = 5) -> dict:
    """Create a short-lived agent, run one message, parse schema-enforced
    JSON, delete the agent. Retries on the same content_filter condition
    documented in azure-agent-demo-setup/day3/lab2_evaluation.py."""
    agent = client.create_agent(
        model=model, name=f"incidentops-{schema_name}",
        instructions=instructions, response_format=_schema_format(schema_name, schema),
    )
    try:
        for attempt in range(retries):
            thread = client.threads.create()
            client.messages.create(thread.id, role=MessageRole.USER, content=user_content)
            run = client.runs.create_and_process(thread.id, agent_id=agent.id)

            filtered = (
                str(run.status) == "incomplete"
                and getattr(run, "incomplete_details", None)
                and run.incomplete_details.get("reason") == "content_filter"
            )
            if filtered:
                if attempt < retries - 1:
                    time.sleep(5 * (attempt + 1))
                continue

            for _ in range(6):  # read-after-write retry, same as day2/lab7
                for msg in client.messages.list(thread.id):
                    if msg.role == MessageRole.AGENT:
                        text = "".join(c.text.value for c in msg.content if hasattr(c, "text"))
                        if text:
                            return json.loads(text)
                time.sleep(2)
            raise RuntimeError(f"No reply from agent after retries for schema {schema_name}")
        raise RuntimeError(f"Repeatedly content-filtered for schema {schema_name}")
    finally:
        client.delete_agent(agent.id)


class AzureAgentSuite:
    def __init__(self, endpoint: str, model_deployment_name: str, credential):
        self.client = AgentsClient(endpoint=endpoint, credential=credential)
        self.model = model_deployment_name

    def triage(self, raw_request: str) -> TriageResult:
        instructions = (
            "You classify IT incident reports. Only state facts present in the "
            "request text; put each supporting fact in evidence."
        )
        data = _run_once(self.client, instructions, "triage", TRIAGE_SCHEMA, self.model, raw_request)
        return TriageResult(
            category=data["category"], affected_service=data["affected_service"],
            severity=data["severity"], evidence=tuple(data["evidence"]),
        )

    def diagnose(self, triage: TriageResult, evidence: list) -> DiagnosisResult:
        instructions = (
            "Given an incident triage and a list of retrieved runbook documents "
            "(EVIDENCE), propose a root-cause hypothesis grounded ONLY in that "
            "evidence. supporting_doc_ids must be actual document ids from "
            "EVIDENCE, never invented. If EVIDENCE is empty, set confidence='low' "
            "and supporting_doc_ids=[] — do not guess.\n\n"
            "IMPORTANT: EVIDENCE was retrieved by a similarity search over a small "
            "document set, so it is ALWAYS non-empty even for vague or unrelated "
            "requests — retrieval returning documents does NOT mean they are "
            "actually relevant. Before citing any document, verify it genuinely "
            "addresses the SPECIFIC symptoms in the triage (same service, same "
            "type of problem, matching technical details). If the triage itself "
            "lacks specific, concrete symptoms (e.g. 'something seems off', no "
            "named service, no measurable signal), OR if none of the retrieved "
            "documents actually match the specific symptoms described, you MUST "
            "set confidence='low' and supporting_doc_ids=[] — do not build a "
            "plausible-sounding hypothesis just because some document was "
            "retrieved. A retrieved-but-irrelevant document is equivalent to no "
            "evidence at all."
        )
        evidence_block = "\n\n".join(f"[{d.id}] {d.title}\n{d.content}" for d in evidence) or "(no relevant documents retrieved)"
        content = json.dumps({"triage": triage.__dict__, "evidence": evidence_block})
        data = _run_once(self.client, instructions, "diagnosis", DIAGNOSIS_SCHEMA, self.model, content)
        return DiagnosisResult(
            root_cause_hypothesis=data["root_cause_hypothesis"],
            supporting_doc_ids=tuple(data["supporting_doc_ids"]),
            confidence=data["confidence"],
        )

    def propose_remediation(self, diagnosis: DiagnosisResult) -> RemediationProposal:
        instructions = (
            "Given a diagnosis, propose ONE remediation action. action must be "
            "EXACTLY 'restart_service' or 'escalate_to_human' — no other value is "
            "executable, regardless of what the situation seems to call for. If "
            "confidence is 'low', action must be 'escalate_to_human' and scope "
            "'escalation:unspecified'. If action is 'restart_service', scope must "
            "be formatted exactly 'restart:<service>:<environment>'."
        )
        content = json.dumps(diagnosis.__dict__)
        data = _run_once(self.client, instructions, "remediation", REMEDIATION_SCHEMA, self.model, content)
        return RemediationProposal(action=data["action"], scope=data["scope"], justification=data["justification"])

    def draft_communication(self, diagnosis: DiagnosisResult, remediation: RemediationProposal) -> CommunicationDraft:
        instructions = "Draft a short status update for the on-call channel summarizing the diagnosis and action taken."
        content = json.dumps({"diagnosis": diagnosis.__dict__, "remediation": remediation.__dict__})
        data = _run_once(self.client, instructions, "communication", COMMUNICATION_SCHEMA, self.model, content)
        return CommunicationDraft(audience=data["audience"], message=data["message"])
