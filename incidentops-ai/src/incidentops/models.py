"""Core domain types for IncidentOps AI.

Extends day2/workflow.py's state machine with two more states
(TRIAGED, DIAGNOSED) to make room for the multi-agent pipeline
(Triage -> Diagnosis -> Remediation -> Communication), each of which now
owns one state transition instead of one agent doing everything.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class WorkflowState(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    DIAGNOSED = "DIAGNOSED"
    ACTION_PROPOSED = "ACTION_PROPOSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    COMMUNICATED = "COMMUNICATED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"


VALID_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.RECEIVED: {WorkflowState.TRIAGED, WorkflowState.ESCALATED},
    WorkflowState.TRIAGED: {WorkflowState.DIAGNOSED, WorkflowState.ESCALATED},
    WorkflowState.DIAGNOSED: {WorkflowState.ACTION_PROPOSED, WorkflowState.ESCALATED},
    WorkflowState.ACTION_PROPOSED: {WorkflowState.AWAITING_APPROVAL, WorkflowState.ESCALATED},
    WorkflowState.AWAITING_APPROVAL: {WorkflowState.APPROVED, WorkflowState.FAILED, WorkflowState.ESCALATED},
    WorkflowState.APPROVED: {WorkflowState.EXECUTING},
    WorkflowState.EXECUTING: {WorkflowState.COMMUNICATED, WorkflowState.FAILED},
    WorkflowState.COMMUNICATED: {WorkflowState.COMPLETED},
    WorkflowState.FAILED: {WorkflowState.ESCALATED},
    WorkflowState.COMPLETED: set(),
    WorkflowState.ESCALATED: set(),
}


class InvalidTransitionError(Exception):
    pass


@dataclass(frozen=True)
class TriageResult:
    category: str
    affected_service: str
    severity: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class DiagnosisResult:
    root_cause_hypothesis: str
    supporting_doc_ids: tuple[str, ...]
    confidence: str  # "high" | "medium" | "low"


@dataclass(frozen=True)
class RemediationProposal:
    action: str
    scope: str  # approval-token scope string, e.g. "restart:payment-service:production"
    justification: str


@dataclass(frozen=True)
class CommunicationDraft:
    audience: str
    message: str


@dataclass
class Incident:
    correlation_id: str
    raw_request: str
    state: WorkflowState = WorkflowState.RECEIVED
    triage: Optional[TriageResult] = None
    diagnosis: Optional[DiagnosisResult] = None
    remediation: Optional[RemediationProposal] = None
    communication: Optional[CommunicationDraft] = None
    created_at: float = field(default_factory=time.time)

    @staticmethod
    def new(raw_request: str) -> "Incident":
        return Incident(correlation_id=str(uuid.uuid4()), raw_request=raw_request)
