import pytest

from incidentops.tenancy import Service, ServiceRegistry, Tenant


@pytest.fixture
def registry():
    reg = ServiceRegistry()
    reg.register_tenant(Tenant(tenant_id="payments-team", display_name="Payments"))
    reg.register_tenant(Tenant(tenant_id="data-team", display_name="Platform Data"))
    reg.register_service(Service(name="payment-service", tenant_id="payments-team",
                                    owner_team="Payments", pagerduty_schedule="PAY-ONCALL"))
    reg.register_service(Service(name="database-cluster-prod", tenant_id="data-team",
                                    owner_team="Platform Data", pagerduty_schedule="DATA-ONCALL"))
    return reg


def test_service_lookup(registry):
    assert registry.get_service("payment-service").owner_team == "Payments"


def test_unknown_service_returns_none(registry):
    assert registry.get_service("nonexistent-service") is None


def test_services_scoped_to_tenant(registry):
    payments_services = registry.services_for_tenant("payments-team")
    assert [s.name for s in payments_services] == ["payment-service"]


def test_cross_tenant_ownership_check_blocks_wrong_tenant(registry):
    # payment-service belongs to payments-team, not data-team
    assert registry.is_service_owned_by_tenant("payment-service", "payments-team") is True
    assert registry.is_service_owned_by_tenant("payment-service", "data-team") is False


def test_cannot_register_service_for_unknown_tenant(registry):
    with pytest.raises(ValueError, match="Unknown tenant_id"):
        registry.register_service(Service(name="rogue-service", tenant_id="nonexistent-team",
                                             owner_team="?", pagerduty_schedule="?"))
