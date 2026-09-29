"""SQLite-backed persistence layer, replacing day2/workflow.py's JSON files.

Repository pattern: business logic (orchestrator.py, agents) depends on
this interface, not on SQLite directly — swapping to Cosmos DB/Postgres
later means replacing this file's internals, not any caller.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Optional

from incidentops.models import (
    CommunicationDraft,
    DiagnosisResult,
    Incident,
    InvalidTransitionError,
    RemediationProposal,
    TriageResult,
    VALID_TRANSITIONS,
    WorkflowState,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    correlation_id TEXT PRIMARY KEY,
    raw_request TEXT NOT NULL,
    state TEXT NOT NULL,
    triage_json TEXT,
    diagnosis_json TEXT,
    remediation_json TEXT,
    communication_json TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    recorded_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_tokens (
    token TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    issued_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
"""


class IncidentRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        conn = self._connect()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    # --- Incident state ---------------------------------------------------

    def save(self, incident: Incident) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO incidents
                   (correlation_id, raw_request, state, triage_json, diagnosis_json,
                    remediation_json, communication_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    incident.correlation_id,
                    incident.raw_request,
                    incident.state.value,
                    json.dumps(incident.triage.__dict__) if incident.triage else None,
                    json.dumps(incident.diagnosis.__dict__) if incident.diagnosis else None,
                    json.dumps(incident.remediation.__dict__) if incident.remediation else None,
                    json.dumps(incident.communication.__dict__) if incident.communication else None,
                    incident.created_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def load(self, correlation_id: str) -> Optional[Incident]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM incidents WHERE correlation_id = ?", (correlation_id,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        (cid, raw_request, state, triage_json, diagnosis_json,
         remediation_json, communication_json, created_at) = row

        triage = None
        if triage_json:
            data = json.loads(triage_json)
            data["evidence"] = tuple(data["evidence"])  # JSON has no tuple type — round-trips as a list otherwise
            triage = TriageResult(**data)

        diagnosis = None
        if diagnosis_json:
            data = json.loads(diagnosis_json)
            data["supporting_doc_ids"] = tuple(data["supporting_doc_ids"])
            diagnosis = DiagnosisResult(**data)

        return Incident(
            correlation_id=cid,
            raw_request=raw_request,
            state=WorkflowState(state),
            triage=triage,
            diagnosis=diagnosis,
            remediation=RemediationProposal(**json.loads(remediation_json)) if remediation_json else None,
            communication=CommunicationDraft(**json.loads(communication_json)) if communication_json else None,
            created_at=created_at,
        )

    def transition(self, correlation_id: str, new_state: WorkflowState) -> None:
        incident = self.load(correlation_id)
        if incident is None:
            raise ValueError(f"No incident found for {correlation_id}")
        if new_state not in VALID_TRANSITIONS[incident.state]:
            raise InvalidTransitionError(f"{incident.state} -> {new_state} is not a valid transition")
        incident.state = new_state
        self.save(incident)

    # --- Idempotency ---------------------------------------------------------

    def check_and_record_idempotency_key(self, key: str) -> bool:
        """Returns True if this is the FIRST time this key has been seen
        (i.e. safe to proceed), False if it's a duplicate (already recorded)."""
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT 1 FROM idempotency_keys WHERE key = ?", (key,)
            ).fetchone()
            if existing is not None:
                return False
            conn.execute(
                "INSERT INTO idempotency_keys (key, recorded_at) VALUES (?, ?)", (key, time.time())
            )
            conn.commit()
            return True
        finally:
            conn.close()

    # --- Approval tokens -------------------------------------------------

    def issue_approval(self, correlation_id: str, scope: str, ttl_seconds: int = 300) -> str:
        token = str(uuid.uuid4())
        now = time.time()
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO approval_tokens (token, scope, correlation_id, issued_at, expires_at, used)
                   VALUES (?, ?, ?, ?, ?, 0)""",
                (token, scope, correlation_id, now, now + ttl_seconds),
            )
            conn.commit()
        finally:
            conn.close()
        return token

    def validate_and_consume_approval(self, token: str, required_scope: str, correlation_id: str) -> tuple[bool, str]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT scope, correlation_id, expires_at, used FROM approval_tokens WHERE token = ?",
                (token,),
            ).fetchone()
            if row is None:
                return False, "token_not_found"
            scope, token_correlation_id, expires_at, used = row
            if used:
                return False, "token_already_used"
            if token_correlation_id != correlation_id:
                return False, "token_wrong_correlation_id"
            if scope != required_scope:
                return False, "token_scope_mismatch"
            if time.time() > expires_at:
                return False, "token_expired"

            conn.execute("UPDATE approval_tokens SET used = 1 WHERE token = ?", (token,))
            conn.commit()
            return True, "ok"
        finally:
            conn.close()
