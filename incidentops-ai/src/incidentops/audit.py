"""Compliance & audit (Feature 13): a real append-only, hash-chained audit
log — replaces the mutable `incidents` table's implicit history (which
`UPDATE`/`INSERT OR REPLACE` can silently overwrite) with a separate,
insert-only table where each row's hash commits to the previous row's
hash. Tampering with or deleting a past entry breaks the chain, which
verify_chain() detects.
"""
import hashlib
import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    correlation_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    recorded_at REAL NOT NULL,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL
);
"""

GENESIS_HASH = "0" * 64


def _compute_hash(correlation_id: str, event_type: str, detail_json: str, recorded_at: float, prev_hash: str) -> str:
    payload = f"{correlation_id}|{event_type}|{detail_json}|{recorded_at}|{prev_hash}"
    return hashlib.sha256(payload.encode()).hexdigest()


class AuditLog:
    def __init__(self, db_path: str):
        self.db_path = db_path
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _last_hash(self, conn) -> str:
        row = conn.execute("SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
        return row[0] if row else GENESIS_HASH

    def record(self, correlation_id: str, event_type: str, detail: dict) -> None:
        conn = self._connect()
        try:
            prev_hash = self._last_hash(conn)
            recorded_at = time.time()
            detail_json = json.dumps(detail, sort_keys=True)
            entry_hash = _compute_hash(correlation_id, event_type, detail_json, recorded_at, prev_hash)
            conn.execute(
                """INSERT INTO audit_log (correlation_id, event_type, detail_json, recorded_at, prev_hash, entry_hash)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (correlation_id, event_type, detail_json, recorded_at, prev_hash, entry_hash),
            )
            conn.commit()
        finally:
            conn.close()

    def history_for(self, correlation_id: str) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT event_type, detail_json, recorded_at FROM audit_log WHERE correlation_id = ? ORDER BY seq",
                (correlation_id,),
            ).fetchall()
        finally:
            conn.close()
        return [{"event_type": r[0], "detail": json.loads(r[1]), "recorded_at": r[2]} for r in rows]

    def verify_chain(self) -> tuple[bool, str]:
        """Recomputes every entry's hash from its stored fields and
        confirms it matches the stored entry_hash, and that prev_hash
        correctly points at the prior row. Returns (is_valid, reason)."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT correlation_id, event_type, detail_json, recorded_at, prev_hash, entry_hash "
                "FROM audit_log ORDER BY seq"
            ).fetchall()
        finally:
            conn.close()

        expected_prev = GENESIS_HASH
        for i, (cid, event_type, detail_json, recorded_at, prev_hash, entry_hash) in enumerate(rows):
            if prev_hash != expected_prev:
                return False, f"row {i}: prev_hash does not match prior entry's hash — chain broken"
            recomputed = _compute_hash(cid, event_type, detail_json, recorded_at, prev_hash)
            if recomputed != entry_hash:
                return False, f"row {i}: stored entry_hash does not match recomputed hash — tampered"
            expected_prev = entry_hash

        return True, "ok"
