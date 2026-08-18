"""Lever agent CLI."""

from __future__ import annotations

import asyncio
import time
from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from lever_agent.digest import build_digest
from lever_agent.keychain import get_lever_api_key
from lever_agent.lever_client import LeverClient
from lever_agent.pipeline_config import load_pipeline_config
from lever_agent.snapshot_store import (
    CandidateSnapshotRow,
    PostingSnapshotRow,
    SnapshotStore,
    diff_candidates,
    diff_postings,
)
from lever_agent.stages import get_stage_lookup, stage_name

app = typer.Typer(help="Personal Lever hiring agent.")
postings_app = typer.Typer(help="Posting-level commands.")
app.add_typer(postings_app, name="postings")

DIGEST_LOG_DIR = Path.home() / "Library" / "Logs" / "lever-agent"


@postings_app.command("mine")
def postings_mine() -> None:
    """List postings where I'm the owner or a follower (T0.5)."""
    console = Console()
    asyncio.run(_postings_mine(console))


async def _postings_mine(console: Console) -> None:
    api_key = get_lever_api_key()
    async with LeverClient(api_key) as client:
        postings = await client.get_my_postings()

    table = Table(title=f"My postings ({len(postings)})")
    table.add_column("Title")
    table.add_column("State")
    table.add_column("Distribution")
    table.add_column("Owner")

    for posting in postings:
        owner = posting.get("owner") or {}
        channels = posting.get("distributionChannels") or []
        table.add_row(
            posting.get("text", "?"),
            posting.get("state", "?"),
            ", ".join(channels) or "?",
            owner.get("name", owner.get("id", "?")),
        )

    console.print(table)


@app.command("digest")
def digest() -> None:
    """Daily pipeline-hygiene digest: stale-candidate flags + posting health (Epic 1)."""
    console = Console(record=True)
    asyncio.run(_digest(console))

    DIGEST_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = DIGEST_LOG_DIR / f"digest-{date.today().isoformat()}.log"
    console.save_text(str(log_path))
    console.print(f"\n[dim]Saved to {log_path}[/dim]")


async def _digest(console: Console) -> None:
    config = load_pipeline_config()
    now_ms = int(time.time() * 1000)
    snapshot_date = date.today().isoformat()

    api_key = get_lever_api_key()
    async with LeverClient(api_key) as client:
        postings = await client.get_my_postings()
        stage_lookup = await get_stage_lookup(client)
        postings_with_opportunities = []
        for posting in postings:
            opportunities = await client.get_opportunities_for_posting(posting["id"])
            postings_with_opportunities.append((posting, opportunities))

    posting_digests = build_digest(postings_with_opportunities, config, now_ms)

    with SnapshotStore() as store:
        previous_candidates, previous_postings = store.load_previous_snapshot(snapshot_date)

        today_candidates: dict[str, CandidateSnapshotRow] = {}
        today_postings: dict[str, PostingSnapshotRow] = {}
        flagged_ids = set()

        for pd in posting_digests:
            flagged_ids.update(f.opportunity_id for f in pd.candidate_flags)

        for posting, opportunities in postings_with_opportunities:
            for opp in opportunities:
                if opp.get("archived"):
                    continue
                today_candidates[opp["id"]] = CandidateSnapshotRow(
                    opportunity_id=opp["id"],
                    posting_id=posting["id"],
                    stage_id=opp.get("stage", "?"),
                    last_advanced_at=opp.get("lastAdvancedAt") or 0,
                    flagged=opp["id"] in flagged_ids,
                )

        for pd in posting_digests:
            flags = []
            if pd.health.below_min_active:
                flags.append("below_min_active")
            if pd.health.no_recent_applicant:
                flags.append("no_recent_applicant")
            if pd.health.stale_publication:
                flags.append("stale_publication")
            today_postings[pd.health.posting_id] = PostingSnapshotRow(
                posting_id=pd.health.posting_id,
                active_count=pd.health.active_count,
                health_flags=",".join(flags),
            )

        candidate_deltas = diff_candidates(today_candidates, previous_candidates)
        posting_deltas = diff_postings(today_postings, previous_postings)

        store.save_snapshot(
            snapshot_date,
            list(today_candidates.values()),
            list(today_postings.values()),
        )

    _render_digest(console, posting_digests, stage_lookup, candidate_deltas, posting_deltas)


def _render_digest(console, posting_digests, stage_lookup, candidate_deltas, posting_deltas) -> None:
    console.rule(f"Lever digest — {date.today().isoformat()}")

    for pd in posting_digests:
        health = pd.health
        title = health.posting_title
        if health.has_flags:
            title = f"⚠ {title}"

        table = Table(title=title, title_justify="left")
        table.add_column("Candidate")
        table.add_column("Stage")
        table.add_column("Days over SLA", justify="right")

        for flag in pd.candidate_flags:
            table.add_row(
                flag.name,
                stage_name(stage_lookup, flag.stage_id),
                f"+{flag.days_over:.1f}d",
            )

        if not pd.candidate_flags:
            table.add_row("[dim]no stale candidates[/dim]", "", "")

        console.print(table)

        health_notes = []
        if health.below_min_active:
            health_notes.append(f"only {health.active_count} active candidates")
        if health.no_recent_applicant:
            days = health.days_since_last_applicant
            health_notes.append(f"no new applicant in {days:.0f} days" if days is not None else "no applicants yet")
        if health.stale_publication:
            health_notes.append(f"published {health.days_published:.0f} days ago")
        if health_notes:
            console.print(f"  [yellow]{'; '.join(health_notes)}[/yellow]")
        console.print()

    if candidate_deltas or posting_deltas:
        console.rule("Since yesterday")
        for line in posting_deltas + candidate_deltas:
            console.print(f"  {line}")
    else:
        console.print("[dim]No prior snapshot to diff against, or nothing changed.[/dim]")


if __name__ == "__main__":
    app()
