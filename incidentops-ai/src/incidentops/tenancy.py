"""Multi-tenant & multi-service coverage (Feature 5).

A service registry replaces the hardcoded 'payment-service' scenarios —
every incident now carries a tenant_id, and services are looked up from
a registry instead of being assumed. Tenant-scoped budgets (token/cost
limits) are tracked here too, enforced by cost.py (Feature 12).
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Service:
    name: str
    tenant_id: str
    owner_team: str
    pagerduty_schedule: str


@dataclass(frozen=True)
class Tenant:
    tenant_id: str
    display_name: str
    monthly_token_budget: int = 1_000_000


class ServiceRegistry:
    """In-memory registry; swap for a real table (Cosmos DB/Postgres) the
    same way db.py replaced JSON files — no callers need to change."""

    def __init__(self):
        self._services: dict[str, Service] = {}
        self._tenants: dict[str, Tenant] = {}

    def register_tenant(self, tenant: Tenant) -> None:
        self._tenants[tenant.tenant_id] = tenant

    def register_service(self, service: Service) -> None:
        if service.tenant_id not in self._tenants:
            raise ValueError(f"Unknown tenant_id '{service.tenant_id}' — register the tenant first")
        self._services[service.name] = service

    def get_service(self, name: str) -> Service | None:
        return self._services.get(name)

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self._tenants.get(tenant_id)

    def services_for_tenant(self, tenant_id: str) -> list[Service]:
        return [s for s in self._services.values() if s.tenant_id == tenant_id]

    def is_service_owned_by_tenant(self, service_name: str, tenant_id: str) -> bool:
        """RBAC boundary: an incident raised under one tenant must never
        be allowed to propose remediation against another tenant's
        service. Called by Orchestrator before accepting a remediation
        scope — see orchestrator.py's tenant_registry wiring."""
        service = self.get_service(service_name)
        return service is not None and service.tenant_id == tenant_id
