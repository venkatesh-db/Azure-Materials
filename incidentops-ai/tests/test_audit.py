import sqlite3

import pytest

from incidentops.audit import AuditLog


@pytest.fixture
def audit(tmp_path):
    return AuditLog(db_path=str(tmp_path / "audit_test.db"))


def test_record_and_retrieve_history(audit):
    audit.record("corr-1", "incident_received", {"raw_request": "payment-service latency spike"})
    audit.record("corr-1", "triaged", {"category": "database", "severity": "SEV-2"})

    history = audit.history_for("corr-1")

    assert len(history) == 2
    assert history[0]["event_type"] == "incident_received"
    assert history[1]["event_type"] == "triaged"


def test_chain_is_valid_after_normal_writes(audit):
    audit.record("corr-1", "incident_received", {"a": 1})
    audit.record("corr-2", "incident_received", {"b": 2})
    audit.record("corr-1", "triaged", {"c": 3})

    is_valid, reason = audit.verify_chain()

    assert is_valid is True
    assert reason == "ok"


def test_tampering_with_a_past_entry_breaks_chain_verification(audit, tmp_path):
    audit.record("corr-1", "incident_received", {"a": 1})
    audit.record("corr-1", "triaged", {"category": "database"})
    audit.record("corr-1", "diagnosed", {"confidence": "high"})

    # Simulate tampering: directly edit a past row's detail_json without
    # going through AuditLog.record() (bypassing the append-only interface,
    # exactly what a malicious actor with raw DB access would attempt).
    conn = sqlite3.connect(audit.db_path)
    conn.execute("UPDATE audit_log SET detail_json = ? WHERE event_type = 'triaged'",
                  ('{"category": "TAMPERED"}',))
    conn.commit()
    conn.close()

    is_valid, reason = audit.verify_chain()

    assert is_valid is False
    assert "tampered" in reason.lower() or "broken" in reason.lower()


def test_empty_log_is_valid(audit):
    is_valid, reason = audit.verify_chain()
    assert is_valid is True
