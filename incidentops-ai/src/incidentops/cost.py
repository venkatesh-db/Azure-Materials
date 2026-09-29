"""Cost governance (Feature 12): per-tenant token budgets and
cheap-model-first routing.

Wraps agent calls to track token usage per tenant and enforce a budget —
extends tenancy.py's Tenant.monthly_token_budget from a declared number
into something actually checked before allowing another call.
"""
from dataclasses import dataclass, field


class BudgetExceededError(Exception):
    pass


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class CostTracker:
    """In-memory tracker; a real deployment would persist this the same
    way db.py persists workflow state — same 'swap the storage, keep the
    interface' pattern used throughout this codebase."""

    def __init__(self, tenant_registry):
        self.tenant_registry = tenant_registry
        self._usage_by_tenant: dict[str, TokenUsage] = {}

    def usage_for(self, tenant_id: str) -> TokenUsage:
        return self._usage_by_tenant.setdefault(tenant_id, TokenUsage())

    def check_budget(self, tenant_id: str) -> None:
        tenant = self.tenant_registry.get_tenant(tenant_id)
        if tenant is None:
            raise ValueError(f"Unknown tenant_id '{tenant_id}'")
        usage = self.usage_for(tenant_id)
        if usage.total >= tenant.monthly_token_budget:
            raise BudgetExceededError(
                f"Tenant '{tenant_id}' has used {usage.total}/{tenant.monthly_token_budget} tokens this period"
            )

    def record(self, tenant_id: str, prompt_tokens: int, completion_tokens: int) -> None:
        usage = self.usage_for(tenant_id)
        usage.prompt_tokens += prompt_tokens
        usage.completion_tokens += completion_tokens


def choose_model(severity: str, cheap_model: str, capable_model: str) -> str:
    """Model routing: cheap model for routine triage, escalate to the
    capable model only when severity is high enough to warrant it. Applied
    at the call site (agents/azure.py) by passing the result of this
    function instead of a single hardcoded self.model."""
    if severity in ("SEV-1", "SEV-2"):
        return capable_model
    return cheap_model
