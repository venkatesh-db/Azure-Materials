"""Tests for the real (SQLite-backed) persistence layer.

Replaces day2/workflow.py's JSON-file store. Written first, per TDD:
these define the contract before db.py exists.
"""
import pytest

from incidentops.db import IncidentRepository
from incidentops.models import Incident, InvalidTransitionError, WorkflowState


@pytest.fixture
def repo(tmp_path):
    return IncidentRepository(db_path=str(tmp_path / "test.db"))


def test_save_and_load_round_trip(repo):
    incident = Incident.new("payment-service latency spike")
    repo.save(incident)

    loaded = repo.load(incident.correlation_id)

    assert loaded is not None
    assert loaded.correlation_id == incident.correlation_id
    assert loaded.raw_request == "payment-service latency spike"
    assert loaded.state == WorkflowState.RECEIVED


def test_load_missing_incident_returns_none(repo):
    assert repo.load("does-not-exist") is None


def test_valid_transition_persists(repo):
    incident = Incident.new("db timeout")
    repo.save(incident)

    repo.transition(incident.correlation_id, WorkflowState.TRIAGED)

    reloaded = repo.load(incident.correlation_id)
    assert reloaded.state == WorkflowState.TRIAGED


def test_invalid_transition_raises_and_does_not_persist(repo):
    incident = Incident.new("db timeout")
    repo.save(incident)

    with pytest.raises(InvalidTransitionError):
        repo.transition(incident.correlation_id, WorkflowState.EXECUTING)

    reloaded = repo.load(incident.correlation_id)
    assert reloaded.state == WorkflowState.RECEIVED  # unchanged


def test_survives_a_fresh_repository_instance(tmp_path):
    """Simulates a process restart: a NEW IncidentRepository object,
    same db file, must see previously persisted state."""
    db_path = str(tmp_path / "restart_test.db")
    incident = Incident.new("kubernetes crashloop")

    repo1 = IncidentRepository(db_path=db_path)
    repo1.save(incident)
    repo1.transition(incident.correlation_id, WorkflowState.TRIAGED)

    repo2 = IncidentRepository(db_path=db_path)  # fresh instance
    reloaded = repo2.load(incident.correlation_id)

    assert reloaded.state == WorkflowState.TRIAGED


def test_idempotency_store_prevents_duplicate_action(repo):
    assert repo.check_and_record_idempotency_key("action-key-1") is True  # first use: not seen before
    assert repo.check_and_record_idempotency_key("action-key-1") is False  # second use: already seen


def test_approval_token_single_use(repo):
    token = repo.issue_approval(
        correlation_id="corr-1", scope="restart:payment-service:production", ttl_seconds=300
    )

    ok, reason = repo.validate_and_consume_approval(token, "restart:payment-service:production", "corr-1")
    assert ok is True

    ok2, reason2 = repo.validate_and_consume_approval(token, "restart:payment-service:production", "corr-1")
    assert ok2 is False
    assert reason2 == "token_already_used"


def test_approval_token_scope_mismatch_rejected(repo):
    token = repo.issue_approval(
        correlation_id="corr-1", scope="restart:payment-service:production", ttl_seconds=300
    )

    ok, reason = repo.validate_and_consume_approval(token, "restart:database-cluster-prod:production", "corr-1")

    assert ok is False
    assert reason == "token_scope_mismatch"
