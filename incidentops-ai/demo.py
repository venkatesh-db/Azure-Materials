"""Run the full multi-agent pipeline end to end, locally, no Azure needed.

Demonstrates: Triage -> Diagnosis -> Remediation proposal ->
AWAITING_APPROVAL -> (human approves) -> Execute -> Communicate ->
COMPLETED. Also demonstrates the escalation path for a low-confidence
diagnosis, and idempotent-execution + invalid-token rejection.
"""
import sys

sys.path.insert(0, "src")

from incidentops.agents.stub import StubAgentSuite
from incidentops.db import IncidentRepository
from incidentops.executor import StubActionExecutor
from incidentops.orchestrator import Orchestrator
from incidentops.retrieval import Document, StubRetriever

RUNBOOKS = [
    Document(id="rb-001", title="Payment Service Runbook", status="approved",
              content="If payment-service reports elevated latency, check database connection pool saturation. "
                       "Recommended action: check for long-running transactions holding connections."),
]


def main():
    repo = IncidentRepository(db_path="incidentops_demo.db")
    orchestrator = Orchestrator(
        repo=repo, agents=StubAgentSuite(), executor=StubActionExecutor(),
        retriever=StubRetriever(RUNBOOKS),
    )

    print("=" * 70)
    print("Scenario 1: confident diagnosis -> proposes action -> awaits approval")
    incident = orchestrator.handle_new_incident("payment-service latency spike, pool saturation suspected")
    print(f"  correlation_id: {incident.correlation_id}")
    print(f"  state: {incident.state.value}")
    print(f"  triage: {incident.triage}")
    print(f"  diagnosis: {incident.diagnosis}")
    print(f"  remediation proposed: {incident.remediation}")

    print("\n  Rejecting execution with a fake approval token...")
    try:
        orchestrator.approve_and_execute(incident.correlation_id, "fake-token")
    except PermissionError as e:
        print(f"  Correctly rejected: {e}")

    print("\n  Issuing a REAL approval token and executing...")
    token = repo.issue_approval(correlation_id=incident.correlation_id, scope=incident.remediation.scope)
    completed = orchestrator.approve_and_execute(incident.correlation_id, token)
    print(f"  Final state: {completed.state.value}")
    print(f"  Communication drafted: {completed.communication.message}")

    print("\n  Trying to execute AGAIN (idempotency/state guard)...")
    try:
        orchestrator.approve_and_execute(incident.correlation_id, token)
    except (PermissionError, ValueError) as e:
        print(f"  Correctly rejected: {e}")

    print("\n" + "=" * 70)
    print("Scenario 2: vague/low-confidence request -> escalates, no action proposed")
    escalated = orchestrator.handle_new_incident("something vague is wrong somewhere")
    print(f"  state: {escalated.state.value}")
    print(f"  remediation: {escalated.remediation}")

    print("\n" + "=" * 70)
    print("Scenario 3: process-restart durability check")
    print(f"  Reloading incident {incident.correlation_id[:8]}... from a FRESH repository instance")
    fresh_repo = IncidentRepository(db_path="incidentops_demo.db")
    reloaded = fresh_repo.load(incident.correlation_id)
    print(f"  State survived restart: {reloaded.state.value} (matches: {reloaded.state == completed.state})")


if __name__ == "__main__":
    main()
