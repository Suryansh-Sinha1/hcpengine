from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id                TEXT PRIMARY KEY,
    created_at        TEXT NOT NULL,
    decision          TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    reviewer          TEXT NOT NULL,
    note              TEXT,
    drug              TEXT NOT NULL,
    channel           TEXT NOT NULL,
    specialty         TEXT NOT NULL,
    therapy_area      TEXT NOT NULL,
    adoption_stage    TEXT NOT NULL,
    subject           TEXT,
    body              TEXT NOT NULL,
    claim_ids         TEXT NOT NULL,
    flags_at_decision TEXT NOT NULL,
    passed_automated  INTEGER NOT NULL
);
"""

_COLUMNS = [
    "id", "created_at", "decision", "reviewer", "note", "drug", "channel",
    "specialty", "therapy_area", "adoption_stage", "subject", "body",
    "claim_ids", "flags_at_decision", "passed_automated",
]


class DecisionStore:
    """Append-only audit log of human approval decisions.

    There is deliberately no update or delete method. An audit trail that can
    be edited is not an audit trail - if a decision was wrong, the remedy is a
    new record superseding it, not a rewrite of history.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["claim_ids"] = json.loads(data["claim_ids"])
        data["flags_at_decision"] = json.loads(data["flags_at_decision"])
        data["passed_automated"] = bool(data["passed_automated"])
        return data

    def record(self, entry: dict[str, Any]) -> dict[str, Any]:
        row = {
            "id": str(uuid.uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "note": None,
            "subject": None,
            **entry,
        }
        row["claim_ids"] = json.dumps(row["claim_ids"])
        row["flags_at_decision"] = json.dumps(row["flags_at_decision"])
        row["passed_automated"] = int(row["passed_automated"])

        columns = ", ".join(_COLUMNS)
        placeholders = ", ".join(f":{c}" for c in _COLUMNS)

        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO decisions ({columns}) VALUES ({placeholders})", row
            )

        result = self.get(row["id"])
        if result is None:
            raise RuntimeError("Decision was written but could not be read back")
        return result

    def get(self, decision_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM decisions WHERE id = ?", (decision_id,)
            ).fetchone()
        return self._to_dict(row) if row else None

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM decisions ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._to_dict(r) for r in rows]

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]