"""Lever agent CLI."""

from __future__ import annotations

import asyncio
import time
from datetime import date
from pathlib import Path

import typer
from anthropic import Anthropic
from rich.console import Console
from rich.table import Table

from lever_agent.digest import build_digest
from lever_agent.keychain import get_anthropic_api_key, get_lever_api_key
from lever_agent.lever_client import LeverClient
from lever_agent.pipeline_config import load_pipeline_config
from lever_agent.rubric import load_rubric
from lever_agent.screening import MODEL as SCREENING_MODEL
from lever_agent.screening import (
    CandidateScore,
    ScreeningRefusalError,
    compute_overall_score,
    fetch_resume_bytes,
    rank_candidates,
    recommendation_band,
    score_resume,
)
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


@app.command("screen")
def screen(
    posting_id: str = typer.Argument(..., help="Lever posting ID (see 'lever postings mine')"),
    limit: int = typer.Option(5, help="Max candidates to screen. Ignored if --all is set."),
    all_candidates: bool = typer.Option(
        False, "--all", help="Screen every active candidate in the posting (real $ per candidate)"
    ),
    detail: str = typer.Option(
        None, "--detail", help="Opportunity ID to show the full per-criterion breakdown for"
    ),
    model: str = typer.Option(
        SCREENING_MODEL, "--model", help="Anthropic model to screen with (default: sonnet-5, a deliberate cost choice)"
    ),
) -> None:
    """Screen a posting's candidates against its rubric with Claude (Epic 2)."""
    console = Console()
    asyncio.run(_screen(console, posting_id, limit, all_candidates, detail, model))


async def _screen(
    console: Console,
    posting_id: str,
    limit: int,
    all_candidates: bool,
    detail: str | None,
    model: str,
) -> None:
    try:
        rubric = load_rubric(posting_id)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    lever_key = get_lever_api_key()
    anthropic_client = Anthropic(api_key=get_anthropic_api_key())

    async with LeverClient(lever_key) as client:
        opportunities = await client.get_opportunities_for_posting(posting_id)
        active = [o for o in opportunities if not o.get("archived")]
        to_screen = active if all_candidates else active[:limit]

        console.print(
            f"Screening {len(to_screen)} of {len(active)} active candidates for "
            f"[bold]{rubric.posting_title}[/bold] ({len(rubric.criteria)}-criterion rubric)…"
        )

        scores: list[CandidateScore] = []
        cache_read_tokens_total = 0
        for opp in to_screen:
            try:
                resume_bytes = await fetch_resume_bytes(client, opp["id"])
                verdict, response = score_resume(anthropic_client, rubric, resume_bytes, model=model)
            except ScreeningRefusalError as exc:
                console.print(f"  [red]{opp.get('name', opp['id'])}: {exc}[/red]")
                continue
            except ValueError as exc:
                console.print(f"  [yellow]{opp.get('name', opp['id'])}: skipped — {exc}[/yellow]")
                continue

            cache_read_tokens_total += getattr(response.usage, "cache_read_input_tokens", 0) or 0
            overall = compute_overall_score(rubric, verdict)
            scores.append(
                CandidateScore(
                    opportunity_id=opp["id"],
                    name=opp.get("name", "?"),
                    overall_score=overall,
                    recommendation=recommendation_band(overall),
                    verdict=verdict,
                )
            )

    ranked = rank_candidates(scores)

    table = Table(title=f"Screening — {rubric.posting_title}")
    table.add_column("Candidate")
    table.add_column("Score", justify="right")
    table.add_column("Recommendation")
    table.add_column("Summary")

    for score in ranked:
        table.add_row(
            score.name,
            f"{score.overall_score:.1f}",
            score.recommendation,
            score.verdict.summary,
        )

    console.print(table)
    if len(scores) > 1:
        console.print(
            f"[dim]cache_read_input_tokens across this cohort: {cache_read_tokens_total} "
            f"(non-zero from candidate 2 on confirms prompt caching is working, T2.4)[/dim]"
        )

    if detail:
        match = next((s for s in ranked if s.opportunity_id == detail), None)
        if match is None:
            console.print(f"[yellow]No screened candidate with opportunity ID {detail} in this run.[/yellow]")
        else:
            console.rule(f"Detail — {match.name}")
            for cv in match.verdict.criterion_verdicts:
                console.print(f"[bold]{cv.name}[/bold]: {cv.score}/10")
                console.print(f"  Evidence: [italic]{cv.evidence_quote}[/italic]")
                console.print(f"  Rationale: {cv.rationale}")


if __name__ == "__main__":
    app()
