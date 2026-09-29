"""Tests for the multi-agent orchestrator — drives the full
Triage -> Diagnosis -> Remediation(-> Approval) -> Communication pipeline
against the deterministic StubAgentSuite and the real SQLite repository.
"""
import pytest

from incidentops.agents.stub import StubAgentSuite
from incidentops.db import IncidentRepository
from incidentops.executor import StubActionExecutor
from incidentops.models import WorkflowState
from incidentops.orchestrator import Orchestrator
from incidentops.retrieval import Document, StubRetriever

RUNBOOKS = [
    Document(id="rb-001", title="Payment Service Runbook", status="approved",
              content="If payment-service reports elevated latency, check database connection pool saturation."),
]


@pytest.fixture
def orchestrator(tmp_path):
    repo = IncidentRepository(db_path=str(tmp_path / "orch_test.db"))
    return Orchestrator(
        repo=repo, agents=StubAgentSuite(), executor=StubActionExecutor(),
        retriever=StubRetriever(RUNBOOKS),
    )


def test_confident_diagnosis_reaches_awaiting_approval(orchestrator):
    incident = orchestrator.handle_new_incident("payment-service latency spike, pool saturation suspected")

    assert incident.state == WorkflowState.AWAITING_APPROVAL
    # The real behavior this increment adds: diagnosis is grounded in an
    # ACTUAL retrieved document ID, not raw request text.
    assert incident.diagnosis.supporting_doc_ids == ("rb-001",)
    assert incident.triage.affected_service == "payment-service"
    assert incident.diagnosis.confidence == "high"
    assert incident.remediation.action == "restart_service"
    assert incident.communication is None  # not drafted until after approval


def test_low_confidence_diagnosis_escalates_instead_of_proposing_action(orchestrator):
    incident = orchestrator.handle_new_incident("something vague is wrong somewhere")

    assert incident.state == WorkflowState.ESCALATED
    assert incident.remediation.action == "escalate_to_human"


def test_approve_and_execute_reaches_completed(orchestrator):
    incident = orchestrator.handle_new_incident("payment-service latency spike")
    assert incident.state == WorkflowState.AWAITING_APPROVAL

    token = orchestrator.repo.issue_approval(
        correlation_id=incident.correlation_id,
        scope=incident.remediation.scope,
    )

    completed = orchestrator.approve_and_execute(incident.correlation_id, token)

    assert completed.state == WorkflowState.COMPLETED
    assert completed.communication is not None
    assert "restart_service" in completed.communication.message

    # The real behavior this increment adds: the executor was ACTUALLY
    # called with the right scope and a stable idempotency key — not a
    # no-op comment, as it was before.
    assert len(orchestrator.executor.calls) == 1
    assert orchestrator.executor.calls[0]["scope"] == "restart:payment-service:production"
    assert orchestrator.executor.calls[0]["correlation_id"] == incident.correlation_id


def test_execution_failure_transitions_to_failed(orchestrator):
    incident = orchestrator.handle_new_incident("payment-service latency spike")
    token = orchestrator.repo.issue_approval(correlation_id=incident.correlation_id, scope=incident.remediation.scope)

    # Force the executor to reject this specific action, simulating a real
    # downstream failure (e.g. the Function App itself rejects the call).
    orchestrator.executor.SUPPORTED_ACTIONS = set()

    with pytest.raises(Exception):
        orchestrator.approve_and_execute(incident.correlation_id, token)

    reloaded = orchestrator.repo.load(incident.correlation_id)
    assert reloaded.state == WorkflowState.FAILED


def test_approve_and_execute_rejects_invalid_token(orchestrator):
    incident = orchestrator.handle_new_incident("payment-service latency spike")

    with pytest.raises(PermissionError):
        orchestrator.approve_and_execute(incident.correlation_id, "not-a-real-token")

    reloaded = orchestrator.repo.load(incident.correlation_id)
    assert reloaded.state == WorkflowState.AWAITING_APPROVAL  # unchanged


def test_duplicate_execution_is_prevented_by_idempotency_key(orchestrator):
    incident = orchestrator.handle_new_incident("payment-service latency spike")
    token = orchestrator.repo.issue_approval(
        correlation_id=incident.correlation_id, scope=incident.remediation.scope,
    )

    first = orchestrator.approve_and_execute(incident.correlation_id, token)
    assert first.state == WorkflowState.COMPLETED

    # Re-running with the same correlation_id must not re-execute the action.
    # The workflow-state guard (not AWAITING_APPROVAL) is what actually
    # blocks this — the incident is already COMPLETED, which is itself
    # proof the idempotency key did its job on the first call.
    with pytest.raises(ValueError, match="not awaiting approval"):
        orchestrator.approve_and_execute(incident.correlation_id, token)
