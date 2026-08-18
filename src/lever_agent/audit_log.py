"""Local audit trail for every write path (T3.4).

Same discipline as the Epic 1 snapshots (ADR-0004): stage IDs, tag names, and
short details only — never a candidate's name or email. `state/lever_agent.db`
is the pointer; Lever itself stays the system of record for the person.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "state" / "lever_agent.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS write_audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_ms    INTEGER NOT NULL,
    opportunity_id  TEXT NOT NULL,
    posting_id      TEXT NOT NULL,
    action          TEXT NOT NULL CHECK (action IN ('note', 'tag', 'stage_move')),
    detail          TEXT NOT NULL,
    dry_run         INTEGER NOT NULL,
    success         INTEGER NOT NULL
);
"""


@dataclass
class AuditLogEntry:
    timestamp_ms: int
    opportunity_id: str
    posting_id: str
    action: str  # 'note' | 'tag' | 'stage_move'
    detail: str
    dry_run: bool
    success: bool


class AuditLog:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "AuditLog":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def record(self, entry: AuditLogEntry) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO write_audit_log
                    (timestamp_ms, opportunity_id, posting_id, action, detail, dry_run, success)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.timestamp_ms,
                    entry.opportunity_id,
                    entry.posting_id,
                    entry.action,
                    entry.detail,
                    int(entry.dry_run),
                    int(entry.success),
                ),
            )

    def recent(self, limit: int = 50) -> list[AuditLogEntry]:
        rows = self._conn.execute(
            """
            SELECT timestamp_ms, opportunity_id, posting_id, action, detail, dry_run, success
            FROM write_audit_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            AuditLogEntry(
                timestamp_ms=r[0],
                opportunity_id=r[1],
                posting_id=r[2],
                action=r[3],
                detail=r[4],
                dry_run=bool(r[5]),
                success=bool(r[6]),
            )
            for r in rows
        ]
