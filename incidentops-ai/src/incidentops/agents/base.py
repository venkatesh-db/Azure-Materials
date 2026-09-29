"""Agent interface every specialist (and the orchestrator) depends on.

This is the seam that makes local testing possible without live Azure
resources: orchestrator.py only ever calls these 4 methods. A
StubAgentSuite (agents/stub.py) implements them deterministically for
tests; a real AzureAgentSuite (not built in this phase — see README.md)
would implement the same Protocol using azure-ai-agents, and the
orchestrator would not need to change at all.
"""
from typing import Protocol

from incidentops.models import (
    CommunicationDraft,
    DiagnosisResult,
    RemediationProposal,
    TriageResult,
)
from incidentops.retrieval import Document


class AgentSuite(Protocol):
    def triage(self, raw_request: str) -> TriageResult: ...

    def diagnose(self, triage: TriageResult, evidence: list[Document]) -> DiagnosisResult:
        """`evidence` is retrieved by the orchestrator (see retrieval.py)
        BEFORE this call — diagnose() should ground its hypothesis in
        these specific documents and cite their real IDs in
        supporting_doc_ids, or return confidence='low' with no doc IDs if
        evidence is empty/insufficient."""
        ...

    def propose_remediation(self, diagnosis: DiagnosisResult) -> RemediationProposal: ...

    def draft_communication(self, diagnosis: DiagnosisResult, remediation: RemediationProposal) -> CommunicationDraft: ...
