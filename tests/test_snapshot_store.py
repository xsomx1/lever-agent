"""Snapshot persistence and day-over-day diffing (T1.5) — and the PII guard from ADR-0004."""

from lever_agent.snapshot_store import (
    CandidateSnapshotRow,
    PostingSnapshotRow,
    SnapshotStore,
    diff_candidates,
    diff_postings,
)


def test_save_and_load_previous_snapshot(tmp_path):
    db_path = tmp_path / "test.db"

    with SnapshotStore(db_path) as store:
        store.save_snapshot(
            "2026-08-17",
            [CandidateSnapshotRow("opp-1", "post-1", "applicant-new", 1000, flagged=False)],
            [PostingSnapshotRow("post-1", active_count=3, health_flags="")],
        )

    with SnapshotStore(db_path) as store:
        candidates, postings = store.load_previous_snapshot("2026-08-18")

    assert candidates["opp-1"].stage_id == "applicant-new"
    assert candidates["opp-1"].flagged is False
    assert postings["post-1"].active_count == 3


def test_load_previous_snapshot_ignores_same_day_and_future(tmp_path):
    db_path = tmp_path / "test.db"

    with SnapshotStore(db_path) as store:
        store.save_snapshot(
            "2026-08-18",
            [CandidateSnapshotRow("opp-1", "post-1", "applicant-new", 1000, flagged=False)],
            [],
        )
        candidates, _ = store.load_previous_snapshot("2026-08-18")

    assert candidates == {}  # nothing strictly before today


def test_diff_candidates_detects_stage_move_and_new_flag():
    previous = {
        "opp-1": CandidateSnapshotRow("opp-1", "post-1", "applicant-new", 1000, flagged=False),
        "opp-2": CandidateSnapshotRow("opp-2", "post-1", "interview", 2000, flagged=True),
    }
    today = {
        "opp-1": CandidateSnapshotRow("opp-1", "post-1", "interview", 3000, flagged=False),
        "opp-2": CandidateSnapshotRow("opp-2", "post-1", "interview", 2000, flagged=False),
        "opp-3": CandidateSnapshotRow("opp-3", "post-1", "applicant-new", 4000, flagged=True),
    }

    lines = diff_candidates(today, previous)

    assert any("opp-1" in line and "moved applicant-new -> interview" in line for line in lines)
    assert any("opp-2" in line and "flag cleared" in line for line in lines)
    assert any("opp-3" in line and "new" in line for line in lines)


def test_diff_postings_detects_health_and_count_changes():
    previous = {"post-1": PostingSnapshotRow("post-1", active_count=5, health_flags="")}
    today = {"post-1": PostingSnapshotRow("post-1", active_count=3, health_flags="below_min_active")}

    lines = diff_postings(today, previous)

    assert any("health flags" in line for line in lines)
    assert any("active count 5 -> 3" in line for line in lines)


def test_snapshot_schema_has_no_pii_columns(tmp_path):
    """Guard rail for ADR-0004: snapshots may never grow a name/email column."""
    db_path = tmp_path / "test.db"
    with SnapshotStore(db_path) as store:
        columns = {
            row[1]
            for table in ("candidate_snapshots", "posting_snapshots")
            for row in store._conn.execute(f"PRAGMA table_info({table})")
        }
    forbidden = {"name", "email", "emails", "resume", "phone", "phones"}
    assert not columns & forbidden
