"""Day-over-day snapshot storage for the digest (T1.5).

Per ADR-0004: stores stage IDs and counts, never candidate names, emails, or
resume data. The opportunity/posting ID is the pointer back to Lever, which
stays the system of record for the person.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "state" / "lever_agent.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candidate_snapshots (
    snapshot_date   TEXT NOT NULL,
    opportunity_id  TEXT NOT NULL,
    posting_id      TEXT NOT NULL,
    stage_id        TEXT NOT NULL,
    last_advanced_at INTEGER NOT NULL,
    flagged         INTEGER NOT NULL,
    PRIMARY KEY (snapshot_date, opportunity_id)
);

CREATE TABLE IF NOT EXISTS posting_snapshots (
    snapshot_date   TEXT NOT NULL,
    posting_id      TEXT NOT NULL,
    active_count    INTEGER NOT NULL,
    health_flags    TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, posting_id)
);
"""


@dataclass
class CandidateSnapshotRow:
    opportunity_id: str
    posting_id: str
    stage_id: str
    last_advanced_at: int
    flagged: bool


@dataclass
class PostingSnapshotRow:
    posting_id: str
    active_count: int
    health_flags: str  # comma-joined flag names, e.g. "below_min_active,stale_publication"


def diff_candidates(
    today: dict[str, CandidateSnapshotRow],
    previous: dict[str, CandidateSnapshotRow],
) -> list[str]:
    """Human-readable day-over-day movement, keyed by opportunity ID only — no names."""
    lines: list[str] = []
    for opportunity_id, current in today.items():
        prior = previous.get(opportunity_id)
        if prior is None:
            if current.flagged:
                lines.append(f"{opportunity_id}: new, already flagged in {current.stage_id}")
            continue
        if current.stage_id != prior.stage_id:
            lines.append(f"{opportunity_id}: moved {prior.stage_id} -> {current.stage_id}")
        if current.flagged and not prior.flagged:
            lines.append(f"{opportunity_id}: newly flagged in {current.stage_id}")
        elif prior.flagged and not current.flagged:
            lines.append(f"{opportunity_id}: flag cleared in {current.stage_id}")
    return lines


def diff_postings(
    today: dict[str, PostingSnapshotRow],
    previous: dict[str, PostingSnapshotRow],
) -> list[str]:
    lines: list[str] = []
    for posting_id, current in today.items():
        prior = previous.get(posting_id)
        if prior is None:
            continue
        if current.health_flags != prior.health_flags:
            lines.append(
                f"{posting_id}: health flags '{prior.health_flags}' -> '{current.health_flags}'"
            )
        if current.active_count != prior.active_count:
            lines.append(
                f"{posting_id}: active count {prior.active_count} -> {current.active_count}"
            )
    return lines


class SnapshotStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SnapshotStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def save_snapshot(
        self,
        snapshot_date: str,
        candidates: list[CandidateSnapshotRow],
        postings: list[PostingSnapshotRow],
    ) -> None:
        with self._conn:
            self._conn.executemany(
                """
                INSERT OR REPLACE INTO candidate_snapshots
                    (snapshot_date, opportunity_id, posting_id, stage_id, last_advanced_at, flagged)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot_date,
                        c.opportunity_id,
                        c.posting_id,
                        c.stage_id,
                        c.last_advanced_at,
                        int(c.flagged),
                    )
                    for c in candidates
                ],
            )
            self._conn.executemany(
                """
                INSERT OR REPLACE INTO posting_snapshots
                    (snapshot_date, posting_id, active_count, health_flags)
                VALUES (?, ?, ?, ?)
                """,
                [(snapshot_date, p.posting_id, p.active_count, p.health_flags) for p in postings],
            )

    def load_previous_snapshot(
        self, before_date: str
    ) -> tuple[dict[str, CandidateSnapshotRow], dict[str, PostingSnapshotRow]]:
        """The most recent snapshot strictly before `before_date`, keyed by ID."""
        row = self._conn.execute(
            "SELECT MAX(snapshot_date) FROM candidate_snapshots WHERE snapshot_date < ?",
            (before_date,),
        ).fetchone()
        previous_date = row[0] if row else None
        if previous_date is None:
            return {}, {}

        candidates = {
            opportunity_id: CandidateSnapshotRow(
                opportunity_id=opportunity_id,
                posting_id=posting_id,
                stage_id=stage_id,
                last_advanced_at=last_advanced_at,
                flagged=bool(flagged),
            )
            for opportunity_id, posting_id, stage_id, last_advanced_at, flagged in self._conn.execute(
                """
                SELECT opportunity_id, posting_id, stage_id, last_advanced_at, flagged
                FROM candidate_snapshots WHERE snapshot_date = ?
                """,
                (previous_date,),
            )
        }
        postings = {
            posting_id: PostingSnapshotRow(
                posting_id=posting_id, active_count=active_count, health_flags=health_flags
            )
            for posting_id, active_count, health_flags in self._conn.execute(
                "SELECT posting_id, active_count, health_flags FROM posting_snapshots WHERE snapshot_date = ?",
                (previous_date,),
            )
        }
        return candidates, postings
