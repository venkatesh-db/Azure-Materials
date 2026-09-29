"""Action execution layer: takes an approved RemediationProposal and
actually performs it, by calling the real deployed Azure Function tools
(day2/azure_function/function_app.py — create_incident,
request_service_restart).

Same Protocol-seam pattern as agents/base.py: orchestrator.py depends on
ActionExecutor, not on HTTP or Azure directly, so tests use
StubActionExecutor and production uses AzureFunctionActionExecutor with
zero orchestrator changes.
"""
import time
from typing import Protocol

import requests

from incidentops.models import RemediationProposal


class UnsupportedActionError(Exception):
    pass


class ActionExecutor(Protocol):
    def execute(self, remediation: RemediationProposal, idempotency_key: str,
                approval_token: str, correlation_id: str) -> dict: ...


class StubActionExecutor:
    """Records calls in-memory instead of making real HTTP calls — used by
    orchestrator tests so they run without a deployed Function App."""

    SUPPORTED_ACTIONS = {"restart_service"}

    def __init__(self):
        self.calls: list[dict] = []
        self._results_by_key: dict[str, dict] = {}

    def execute(self, remediation: RemediationProposal, idempotency_key: str,
                approval_token: str, correlation_id: str) -> dict:
        if remediation.action not in self.SUPPORTED_ACTIONS:
            raise UnsupportedActionError(f"No executor mapping for action '{remediation.action}'")

        if idempotency_key in self._results_by_key:
            return self._results_by_key[idempotency_key]  # cache hit, no re-execution recorded

        self.calls.append({
            "action": remediation.action, "scope": remediation.scope,
            "idempotency_key": idempotency_key, "approval_token": approval_token,
            "correlation_id": correlation_id,
        })
        result = {"status": "restart_initiated", "idempotency_key": idempotency_key}
        self._results_by_key[idempotency_key] = result
        return result


class AzureFunctionActionExecutor:
    """Calls the real deployed Function App endpoints over HTTP.

    remediation.scope is formatted 'restart:<service_name>:<environment>'
    by the agents (see agents/azure.py, agents/stub.py) — parsed here to
    build the request body.
    """

    ACTION_TO_ROUTE = {
        "restart_service": "request-service-restart",
    }

    def __init__(self, function_app_base_url: str, function_key: str, timeout_seconds: float = 30.0):
        self.base_url = function_app_base_url.rstrip("/")
        self.function_key = function_key
        self.timeout_seconds = timeout_seconds

    def execute(self, remediation: RemediationProposal, idempotency_key: str,
                approval_token: str, correlation_id: str) -> dict:
        route = self.ACTION_TO_ROUTE.get(remediation.action)
        if route is None:
            raise UnsupportedActionError(f"No executor route mapping for action '{remediation.action}'")

        if remediation.action == "restart_service":
            _, service_name, environment = remediation.scope.split(":")
            body = {
                "service_name": service_name,
                "environment": environment,
                "justification": remediation.justification,
                "idempotency_key": idempotency_key,
                "correlation_id": correlation_id,
                "approval_token": approval_token,
            }
        else:  # pragma: no cover — unreachable given ACTION_TO_ROUTE gate above
            raise UnsupportedActionError(remediation.action)

        response = requests.post(
            f"{self.base_url}/api/{route}",
            params={"code": self.function_key},
            json=body,
            timeout=self.timeout_seconds,
        )
        if response.status_code == 403:
            raise PermissionError(f"Function rejected the call: {response.json()}")
        response.raise_for_status()
        return response.json()
