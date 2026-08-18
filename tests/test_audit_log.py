"""Local write audit trail (T3.4) and its PII guard (ADR-0004)."""

from lever_agent.audit_log import AuditLog, AuditLogEntry


def test_record_and_recent_round_trip(tmp_path):
    db_path = tmp_path / "audit.db"
    with AuditLog(db_path) as audit:
        audit.record(
            AuditLogEntry(
                timestamp_ms=1000,
                opportunity_id="opp-1",
                posting_id="post-1",
                action="note",
                detail="score=8.3",
                dry_run=False,
                success=True,
            )
        )
        audit.record(
            AuditLogEntry(
                timestamp_ms=2000,
                opportunity_id="opp-2",
                posting_id="post-1",
                action="tag",
                detail="screened",
                dry_run=True,
                success=True,
            )
        )

    with AuditLog(db_path) as audit:
        entries = audit.recent()

    assert len(entries) == 2
    assert entries[0].opportunity_id == "opp-2"  # most recent first
    assert entries[1].detail == "score=8.3"
    assert entries[1].dry_run is False


def test_recent_respects_limit(tmp_path):
    db_path = tmp_path / "audit.db"
    with AuditLog(db_path) as audit:
        for i in range(5):
            audit.record(
                AuditLogEntry(
                    timestamp_ms=i,
                    opportunity_id=f"opp-{i}",
                    posting_id="post-1",
                    action="tag",
                    detail="screened",
                    dry_run=False,
                    success=True,
                )
            )
        entries = audit.recent(limit=2)

    assert len(entries) == 2


def test_write_audit_log_schema_has_no_pii_columns(tmp_path):
    with AuditLog(tmp_path / "audit.db") as audit:
        columns = {row[1] for row in audit._conn.execute("PRAGMA table_info(write_audit_log)")}
    forbidden = {"name", "email", "emails", "resume", "phone", "phones"}
    assert not columns & forbidden
