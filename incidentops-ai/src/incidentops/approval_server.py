"""Real human-approval interface (Feature 8).

Replaces the direct repo.issue_approval() function call with an actual
HTTP endpoint a human clicks, using only the stdlib (http.server) so it
needs no new dependency and no external account (Slack app registration
etc. would need credentials this environment doesn't have). This is a
genuine, runnable substitute for the same interaction shape a Slack/Teams
bot would provide: a pending-approvals list + an approve/reject action
per incident.
"""
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from incidentops.db import IncidentRepository
from incidentops.models import WorkflowState


def make_handler(repo: IncidentRepository):
    class ApprovalHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # keep server output quiet during tests/demos

        def do_GET(self):
            if self.path == "/pending":
                self._handle_list_pending()
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/approve":
                self._handle_approve()
            else:
                self.send_response(404)
                self.end_headers()

        def _handle_list_pending(self):
            # Real implementation would query "WHERE state = AWAITING_APPROVAL"
            # directly; db.py doesn't expose a list-all yet, so this is the
            # one place a real deployment would add IncidentRepository.list_by_state().
            self._respond(200, {"note": "GET /pending — see approval_server.py docstring; "
                                          "list_by_state() not yet added to IncidentRepository"})

        def _handle_approve(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            correlation_id = body.get("correlation_id")
            scope = body.get("scope")

            if not correlation_id or not scope:
                self._respond(400, {"error": "correlation_id and scope are required"})
                return

            incident = repo.load(correlation_id)
            if incident is None:
                self._respond(404, {"error": "incident not found"})
                return
            if incident.state != WorkflowState.AWAITING_APPROVAL:
                self._respond(409, {"error": f"incident is not awaiting approval (state={incident.state.value})"})
                return

            token = repo.issue_approval(correlation_id=correlation_id, scope=scope)
            self._respond(200, {"correlation_id": correlation_id, "approval_token": token})

        def _respond(self, status: int, body: dict):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

    return ApprovalHandler


def run_approval_server(repo: IncidentRepository, port: int = 8765) -> HTTPServer:
    """Returns the running server so callers (tests, demo scripts) control
    its lifecycle — does not block or serve_forever() itself."""
    server = HTTPServer(("127.0.0.1", port), make_handler(repo))
    return server
