"""Multi-agent orchestrator: coordinates Triage -> Diagnosis ->
Remediation -> (human approval) -> Execution -> Communication.

Replaces day1/day2's single "do everything" agent with 4 specialist
calls, each producing a typed, persisted result — and replaces
day2/workflow.py's in-memory approval/idempotency checks with the real
SQLite-backed repository.
"""
from incidentops.agents.base import AgentSuite
from incidentops.db import IncidentRepository
from incidentops.executor import ActionExecutor
from incidentops.models import DiagnosisResult, Incident, RemediationProposal, WorkflowState
from incidentops.retrieval import Retriever


class Orchestrator:
    def __init__(self, repo: IncidentRepository, agents: AgentSuite, executor: ActionExecutor, retriever: Retriever):
        self.repo = repo
        self.agents = agents
        self.executor = executor
        self.retriever = retriever

    def handle_new_incident(self, raw_request: str) -> Incident:
        incident = Incident.new(raw_request)
        self.repo.save(incident)

        # Any of the 3 agent calls below can raise — most notably Azure's
        # platform content-safety filter, which the security-attack
        # simulation showed can reject a request before generation (see
        # ROADMAP.md). An agent call failing is not a code bug: escalate
        # to a human rather than let it crash the caller. A genuine
        # programming error elsewhere (e.g. in db.py) is not caught here —
        # only the 3 external agent-call sites are wrapped.
        try:
            incident.triage = self.agents.triage(raw_request)
            self.repo.save(incident)
            self.repo.transition(incident.correlation_id, WorkflowState.TRIAGED)
            incident.state = WorkflowState.TRIAGED  # keep the local copy in sync,
            # otherwise the next repo.save() below would overwrite the DB's
            # state with this object's stale value (a real bug caught by the
            # orchestrator tests on first run — see test_orchestrator.py)

            evidence = self.retriever.retrieve(incident.raw_request)
            incident.diagnosis = self.agents.diagnose(incident.triage, evidence)
            self.repo.save(incident)
            self.repo.transition(incident.correlation_id, WorkflowState.DIAGNOSED)
            incident.state = WorkflowState.DIAGNOSED

            incident.remediation = self.agents.propose_remediation(incident.diagnosis)
            self.repo.save(incident)
        except Exception as exc:
            incident.diagnosis = incident.diagnosis or DiagnosisResult(
                root_cause_hypothesis=f"Agent pipeline failed: {exc}",
                supporting_doc_ids=(), confidence="low",
            )
            incident.remediation = RemediationProposal(
                action="escalate_to_human", scope="escalation:unspecified",
                justification=f"Automated pipeline could not complete: {exc}",
            )
            self.repo.save(incident)
            self.repo.transition(incident.correlation_id, WorkflowState.ESCALATED)
            return self.repo.load(incident.correlation_id)

        # The authoritative signal for whether there's a real action to
        # approve is remediation.action, not diagnosis.confidence — found
        # via eval dataset design: a medium-confidence diagnosis whose
        # remediation is 'escalate_to_human' was routing to
        # AWAITING_APPROVAL, which is meaningless (there's no restart to
        # approve). Confirmed live in the attack simulation's output.
        if incident.remediation.action == "escalate_to_human":
            self.repo.transition(incident.correlation_id, WorkflowState.ESCALATED)
        else:
            self.repo.transition(incident.correlation_id, WorkflowState.ACTION_PROPOSED)
            incident.state = WorkflowState.ACTION_PROPOSED
            self.repo.transition(incident.correlation_id, WorkflowState.AWAITING_APPROVAL)

        return self.repo.load(incident.correlation_id)

    def approve_and_execute(self, correlation_id: str, approval_token: str) -> Incident:
        incident = self.repo.load(correlation_id)
        if incident is None:
            raise ValueError(f"No incident found for {correlation_id}")
        if incident.state != WorkflowState.AWAITING_APPROVAL:
            raise ValueError(f"Incident {correlation_id} is not awaiting approval (state={incident.state})")

        ok, reason = self.repo.validate_and_consume_approval(
            approval_token, incident.remediation.scope, correlation_id
        )
        if not ok:
            raise PermissionError(f"Approval rejected: {reason}")

        idempotency_key = f"execute:{correlation_id}"
        if not self.repo.check_and_record_idempotency_key(idempotency_key):
            raise ValueError(f"Action for {correlation_id} was already executed (idempotency key already recorded)")

        self.repo.transition(correlation_id, WorkflowState.APPROVED)
        self.repo.transition(correlation_id, WorkflowState.EXECUTING)
        incident.state = WorkflowState.EXECUTING  # keep local copy in sync — same
        # class of bug as handle_new_incident; save() below would otherwise
        # stomp the DB's EXECUTING state back to the stale AWAITING_APPROVAL
        # this object was loaded with at the top of this method.

        try:
            self.executor.execute(
                incident.remediation, idempotency_key=idempotency_key,
                approval_token=approval_token, correlation_id=correlation_id,
            )
        except Exception:
            self.repo.transition(correlation_id, WorkflowState.FAILED)
            raise

        incident.communication = self.agents.draft_communication(incident.diagnosis, incident.remediation)
        self.repo.save(incident)
        self.repo.transition(correlation_id, WorkflowState.COMMUNICATED)
        self.repo.transition(correlation_id, WorkflowState.COMPLETED)

        return self.repo.load(correlation_id)
