"""Deterministic test double for AgentSuite — no LLM calls, no network.

Used by orchestrator tests so the multi-agent pipeline logic is verified
independently of a live Foundry deployment. A real AzureAgentSuite swaps
in later behind the same Protocol (see agents/base.py) with zero changes
to orchestrator.py.
"""
from incidentops.models import (
    CommunicationDraft,
    DiagnosisResult,
    RemediationProposal,
    TriageResult,
)
from incidentops.retrieval import Document


class StubAgentSuite:
    """Canned, deterministic responses keyed on simple substring matches —
    enough to exercise the full pipeline and its branches in tests."""

    def triage(self, raw_request: str) -> TriageResult:
        if "payment-service" in raw_request.lower():
            return TriageResult(
                category="database",
                affected_service="payment-service",
                severity="SEV-2",
                evidence=(raw_request,),
            )
        return TriageResult(
            category="unknown",
            affected_service="unknown",
            severity="SEV-3",
            evidence=(raw_request,),
        )

    def diagnose(self, triage: TriageResult, evidence: list[Document]) -> DiagnosisResult:
        if not evidence:
            return DiagnosisResult(
                root_cause_hypothesis="Insufficient evidence to determine root cause",
                supporting_doc_ids=(),
                confidence="low",
            )
        return DiagnosisResult(
            root_cause_hypothesis=f"See {evidence[0].title}: {evidence[0].content}",
            supporting_doc_ids=tuple(d.id for d in evidence),
            confidence="high",
        )

    def propose_remediation(self, diagnosis: DiagnosisResult) -> RemediationProposal:
        if diagnosis.confidence == "low":
            return RemediationProposal(
                action="escalate_to_human",
                scope="escalation:unspecified",
                justification="Confidence too low to propose an automated action",
            )
        return RemediationProposal(
            action="restart_service",
            scope="restart:payment-service:production",
            justification=diagnosis.root_cause_hypothesis,
        )

    def draft_communication(self, diagnosis: DiagnosisResult, remediation: RemediationProposal) -> CommunicationDraft:
        return CommunicationDraft(
            audience="on-call-channel",
            message=(
                f"Diagnosis: {diagnosis.root_cause_hypothesis} "
                f"(confidence={diagnosis.confidence}). "
                f"Proposed action: {remediation.action} ({remediation.justification})."
            ),
        )
