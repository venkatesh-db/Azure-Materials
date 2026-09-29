"""Tests that an agent-pipeline failure (e.g. Azure's content filter, or
any other exception from the AgentSuite) escalates gracefully instead of
raising an unhandled exception — found missing by the live security
attack simulation (attack_test_live.py's prompt_injection_in_request case).
"""
import pytest

from incidentops.db import IncidentRepository
from incidentops.executor import StubActionExecutor
from incidentops.models import DiagnosisResult, RemediationProposal, TriageResult, WorkflowState
from incidentops.orchestrator import Orchestrator
from incidentops.retrieval import StubRetriever


class FailingAgentSuite:
    """Simulates an agent call raising — e.g. Azure's content filter."""

    def triage(self, raw_request):
        raise RuntimeError("Repeatedly content-filtered for schema triage")

    def diagnose(self, triage, evidence):
        raise AssertionError("should not be reached — triage already failed")

    def propose_remediation(self, diagnosis):
        raise AssertionError("should not be reached — triage already failed")

    def draft_communication(self, diagnosis, remediation):
        raise AssertionError("should not be reached")


def test_agent_failure_escalates_instead_of_raising(tmp_path):
    repo = IncidentRepository(db_path=str(tmp_path / "resilience_test.db"))
    orchestrator = Orchestrator(
        repo=repo, agents=FailingAgentSuite(), executor=StubActionExecutor(), retriever=StubRetriever([]),
    )

    incident = orchestrator.handle_new_incident("payment-service latency spike")

    assert incident.state == WorkflowState.ESCALATED
    assert incident.remediation.action == "escalate_to_human"
    assert "content-filtered" in incident.diagnosis.root_cause_hypothesis


class MediumConfidenceButEscalatingAgentSuite:
    """Real pattern seen live in the attack simulation: diagnosis
    confidence='medium' (not 'low'), but the agent still correctly
    proposes action='escalate_to_human' as the safer choice. Before the
    fix, the orchestrator only checked diagnosis.confidence and would
    have routed this to AWAITING_APPROVAL — a meaningless state, since
    there's no restart action to approve."""

    def triage(self, raw_request):
        return TriageResult(category="database", affected_service="payment-service",
                              severity="SEV-2", evidence=(raw_request,))

    def diagnose(self, triage, evidence):
        return DiagnosisResult(root_cause_hypothesis="plausible but not conclusive",
                                 supporting_doc_ids=("rb-001",), confidence="medium")

    def propose_remediation(self, diagnosis):
        return RemediationProposal(action="escalate_to_human", scope="escalation:unspecified",
                                     justification="chose to escalate despite medium confidence")

    def draft_communication(self, diagnosis, remediation):
        raise AssertionError("should not be reached — escalated incidents don't get a communication draft")


def test_escalate_to_human_action_routes_to_escalated_even_with_medium_confidence(tmp_path):
    repo = IncidentRepository(db_path=str(tmp_path / "medium_confidence_test.db"))
    orchestrator = Orchestrator(
        repo=repo, agents=MediumConfidenceButEscalatingAgentSuite(),
        executor=StubActionExecutor(), retriever=StubRetriever([]),
    )

    incident = orchestrator.handle_new_incident("payment-service latency spike")

    assert incident.state == WorkflowState.ESCALATED  # not AWAITING_APPROVAL
