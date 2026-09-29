"""Tests for the action-executor layer that calls the deployed Azure
Function tools. StubActionExecutor is the test double; the real
AzureFunctionActionExecutor is verified separately by demo_live.py
against the actual deployed endpoint (HTTP calls aren't unit-tested here
for the same reason live Azure agent calls aren't — see agents/stub.py).
"""
import pytest

from incidentops.executor import StubActionExecutor, UnsupportedActionError
from incidentops.models import RemediationProposal


@pytest.fixture
def executor():
    return StubActionExecutor()


def test_restart_service_action_is_recorded(executor):
    remediation = RemediationProposal(
        action="restart_service", scope="restart:payment-service:production", justification="pool exhaustion"
    )

    result = executor.execute(remediation, idempotency_key="exec-1", approval_token="tok-1", correlation_id="corr-1")

    assert result["status"] == "restart_initiated"
    assert len(executor.calls) == 1
    assert executor.calls[0]["idempotency_key"] == "exec-1"


def test_duplicate_idempotency_key_returns_cached_result_without_re_executing(executor):
    remediation = RemediationProposal(
        action="restart_service", scope="restart:payment-service:production", justification="pool exhaustion"
    )

    first = executor.execute(remediation, idempotency_key="exec-2", approval_token="tok-1", correlation_id="corr-1")
    second = executor.execute(remediation, idempotency_key="exec-2", approval_token="tok-2", correlation_id="corr-1")

    assert first == second
    assert len(executor.calls) == 1  # NOT 2 — the second call was a cache hit, not a real execution


def test_unsupported_action_raises(executor):
    remediation = RemediationProposal(action="reboot_the_datacenter", scope="n/a", justification="n/a")

    with pytest.raises(UnsupportedActionError):
        executor.execute(remediation, idempotency_key="exec-3", approval_token="tok-1", correlation_id="corr-1")
