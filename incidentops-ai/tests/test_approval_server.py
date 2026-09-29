import json
import threading
import urllib.error
import urllib.request

import pytest

from incidentops.approval_server import run_approval_server
from incidentops.db import IncidentRepository
from incidentops.models import Incident, WorkflowState


@pytest.fixture
def server_and_repo(tmp_path):
    repo = IncidentRepository(db_path=str(tmp_path / "approval_server_test.db"))
    server = run_approval_server(repo, port=0)  # port=0 -> OS picks a free port
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield repo, port
    server.shutdown()


def _post(port, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_approve_pending_incident_issues_a_real_token(server_and_repo):
    repo, port = server_and_repo
    incident = Incident.new("payment-service latency spike")
    incident.state = WorkflowState.RECEIVED
    repo.save(incident)
    repo.transition(incident.correlation_id, WorkflowState.TRIAGED)
    repo.transition(incident.correlation_id, WorkflowState.DIAGNOSED)
    repo.transition(incident.correlation_id, WorkflowState.ACTION_PROPOSED)
    repo.transition(incident.correlation_id, WorkflowState.AWAITING_APPROVAL)

    status, body = _post(port, "/approve", {
        "correlation_id": incident.correlation_id, "scope": "restart:payment-service:production",
    })

    assert status == 200
    assert "approval_token" in body

    # The token issued via HTTP is a REAL token — usable through the same
    # repo.validate_and_consume_approval() path executor.py calls.
    ok, reason = repo.validate_and_consume_approval(
        body["approval_token"], "restart:payment-service:production", incident.correlation_id,
    )
    assert ok is True


def test_approve_nonexistent_incident_returns_404(server_and_repo):
    _, port = server_and_repo
    status, body = _post(port, "/approve", {"correlation_id": "does-not-exist", "scope": "restart:x:y"})
    assert status == 404


def test_approve_incident_not_awaiting_approval_returns_409(server_and_repo):
    repo, port = server_and_repo
    incident = Incident.new("test")
    repo.save(incident)  # stays in RECEIVED state

    status, body = _post(port, "/approve", {"correlation_id": incident.correlation_id, "scope": "restart:x:y"})
    assert status == 409
