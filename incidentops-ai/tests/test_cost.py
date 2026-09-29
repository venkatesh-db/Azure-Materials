import pytest

from incidentops.cost import BudgetExceededError, CostTracker, choose_model
from incidentops.tenancy import ServiceRegistry, Tenant


@pytest.fixture
def registry():
    reg = ServiceRegistry()
    reg.register_tenant(Tenant(tenant_id="payments-team", display_name="Payments", monthly_token_budget=1000))
    return reg


def test_records_usage_and_allows_calls_under_budget(registry):
    tracker = CostTracker(registry)
    tracker.record("payments-team", prompt_tokens=100, completion_tokens=50)

    tracker.check_budget("payments-team")  # should not raise
    assert tracker.usage_for("payments-team").total == 150


def test_raises_when_budget_exceeded(registry):
    tracker = CostTracker(registry)
    tracker.record("payments-team", prompt_tokens=900, completion_tokens=200)  # 1100 > 1000 budget

    with pytest.raises(BudgetExceededError):
        tracker.check_budget("payments-team")


def test_unknown_tenant_raises(registry):
    tracker = CostTracker(registry)
    with pytest.raises(ValueError, match="Unknown tenant_id"):
        tracker.check_budget("nonexistent-team")


def test_model_routing_by_severity():
    assert choose_model("SEV-1", cheap_model="gpt-5-nano", capable_model="gpt-5-mini") == "gpt-5-mini"
    assert choose_model("SEV-2", cheap_model="gpt-5-nano", capable_model="gpt-5-mini") == "gpt-5-mini"
    assert choose_model("SEV-3", cheap_model="gpt-5-nano", capable_model="gpt-5-mini") == "gpt-5-nano"
    assert choose_model("SEV-4", cheap_model="gpt-5-nano", capable_model="gpt-5-mini") == "gpt-5-nano"
