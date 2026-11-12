"""Lever agent CLI."""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime
from pathlib import Path

import httpx
import typer
from openai import APIError, OpenAI
from rich.console import Console
from rich.table import Table

from lever_agent.audit_log import AuditLog
from lever_agent.digest import build_digest
from lever_agent.keychain import get_lever_api_key, get_openai_api_key
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
from lever_agent.writes import (
    advance_stage,
    build_note_text,
    write_note,
    write_tag,
)

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
        SCREENING_MODEL, "--model", help="OpenAI model to screen with (default: gpt-6.1-terra, a deliberate cost choice — ADR-0006)"
    ),
    post_notes: bool = typer.Option(
        False, "--post-notes", help="Write a note + the 'screened' tag to Lever for each candidate screened (T3.1/T3.2)"
    ),
    tag_only: bool = typer.Option(
        False, "--tag", help="Add the 'screened' tag without a note. Combines with --post-notes if both given."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="With --post-notes/--tag: print what would be sent instead of writing to Lever"
    ),
    opportunity: str = typer.Option(
        None, "--opportunity", help="Screen only this one opportunity ID, ignoring --limit/--all"
    ),
) -> None:
    """Screen a posting's candidates against its rubric with OpenAI (Epic 2, ADR-0006)."""
    console = Console()
    asyncio.run(
        _screen(console, posting_id, limit, all_candidates, detail, model, post_notes, tag_only, dry_run, opportunity)
    )


async def _screen(
    console: Console,
    posting_id: str,
    limit: int,
    all_candidates: bool,
    detail: str | None,
    model: str,
    post_notes: bool = False,
    tag_only: bool = False,
    dry_run: bool = False,
    opportunity: str | None = None,
) -> None:
    try:
        rubric = load_rubric(posting_id)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    lever_key = get_lever_api_key()
    openai_client = OpenAI(api_key=get_openai_api_key())

    async with LeverClient(lever_key) as client:
        opportunities = await client.get_opportunities_for_posting(posting_id)
        active = [o for o in opportunities if not o.get("archived")]
        if opportunity:
            to_screen = [o for o in active if o["id"] == opportunity]
            if not to_screen:
                console.print(f"[red]Opportunity {opportunity} not found or not active under {posting_id}[/red]")
                raise typer.Exit(code=1)
        else:
            to_screen = active if all_candidates else active[:limit]

        console.print(
            f"Screening {len(to_screen)} of {len(active)} active candidates for "
            f"[bold]{rubric.posting_title}[/bold] ({len(rubric.criteria)}-criterion rubric)…"
        )

        scores: list[CandidateScore] = []
        input_tokens_total = 0
        output_tokens_total = 0
        for opp in to_screen:
            try:
                resume_bytes = await fetch_resume_bytes(client, opp["id"])
                verdict, response = score_resume(openai_client, rubric, resume_bytes, model=model)
            except ScreeningRefusalError as exc:
                console.print(f"  [red]{opp.get('name', opp['id'])}: {exc}[/red]")
                continue
            except ValueError as exc:
                console.print(f"  [yellow]{opp.get('name', opp['id'])}: skipped — {exc}[/yellow]")
                continue
            except (APIError, httpx.HTTPError) as exc:
                # One bad resume or a Lever/OpenAI error that outlived its retries
                # must not throw away the rest of the cohort's (already paid) scores.
                console.print(f"  [yellow]{opp.get('name', opp['id'])}: skipped — {type(exc).__name__}: {exc}[/yellow]")
                continue

            usage = getattr(response, "usage", None)
            input_tokens_total += getattr(usage, "input_tokens", 0) or 0
            output_tokens_total += getattr(usage, "output_tokens", 0) or 0
            overall = compute_overall_score(rubric, verdict)
            score = CandidateScore(
                opportunity_id=opp["id"],
                name=opp.get("name", "?"),
                overall_score=overall,
                recommendation=recommendation_band(overall),
                verdict=verdict,
            )
            scores.append(score)

            if post_notes or tag_only:
                now_ms = int(time.time() * 1000)
                with AuditLog() as audit:
                    if post_notes:
                        note_text = build_note_text(rubric, score)
                        note_result = await write_note(
                            client, audit, posting_id, score, note_text, now_ms=now_ms, dry_run=dry_run
                        )
                        if dry_run:
                            console.print(f"  [dim]would POST note for {score.name}:[/dim]\n{note_text}")
                        else:
                            console.print(f"  [green]note posted for {score.name}[/green]")
                    if tag_only or post_notes:
                        tag_result = await write_tag(
                            client, audit, posting_id, score.opportunity_id, now_ms=now_ms, dry_run=dry_run
                        )
                        if dry_run:
                            console.print(f"  [dim]would tag {score.name}: {tag_result.would_send}[/dim]")
                        else:
                            console.print(f"  [green]tagged {score.name} '{tag_result.detail}'[/green]")

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
    if scores:
        # No prompt-cache line any more: the shared rubric prefix is below OpenAI's
        # 1,024-token cache minimum (ADR-0006), so cached tokens stay at zero.
        console.print(
            f"[dim]tokens across this cohort ({model}): "
            f"input {input_tokens_total}, output {output_tokens_total}[/dim]"
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


@app.command("advance")
def advance(
    opportunity_id: str = typer.Argument(..., help="Lever opportunity ID"),
    target_stage: str = typer.Argument(..., help="Target stage name (e.g. 'Interview') or raw stage ID"),
    posting_id: str = typer.Option(..., "--posting", help="Posting ID this opportunity belongs to"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the intended call without sending it"),
) -> None:
    """Move one candidate to a new stage — one at a time, explicit confirmation (T3.3)."""
    console = Console()
    asyncio.run(_advance(console, opportunity_id, target_stage, posting_id, dry_run))


async def _advance(
    console: Console, opportunity_id: str, target_stage: str, posting_id: str, dry_run: bool
) -> None:
    lever_key = get_lever_api_key()
    async with LeverClient(lever_key) as client:
        stage_lookup = await get_stage_lookup(client)

        target_stage_id = target_stage
        target_stage_text = target_stage
        if target_stage not in stage_lookup:
            match = next(
                (sid for sid, info in stage_lookup.items() if info["text"].lower() == target_stage.lower()),
                None,
            )
            if match is None:
                console.print(f"[red]Unknown stage '{target_stage}'. Known stages:[/red]")
                for info in stage_lookup.values():
                    console.print(f"  {info['text']}")
                raise typer.Exit(code=1)
            target_stage_id = match
            target_stage_text = stage_lookup[match]["text"]

        opportunities = await client.get_opportunities_for_posting(posting_id)
        opp = next((o for o in opportunities if o["id"] == opportunity_id), None)
        if opp is None:
            console.print(f"[red]Opportunity {opportunity_id} not found under posting {posting_id}[/red]")
            raise typer.Exit(code=1)

        current_stage_text = stage_name(stage_lookup, opp.get("stage", "?"))

        if not dry_run:
            confirmed = typer.confirm(
                f"Move {opp.get('name', opportunity_id)} from '{current_stage_text}' "
                f"to '{target_stage_text}'?"
            )
            if not confirmed:
                console.print("[yellow]Cancelled — no change made.[/yellow]")
                raise typer.Exit(code=0)

        now_ms = int(time.time() * 1000)
        with AuditLog() as audit:
            result = await advance_stage(
                client, audit, posting_id, opportunity_id, target_stage_id, target_stage_text,
                now_ms=now_ms, dry_run=dry_run,
            )

        if dry_run:
            console.print(f"[dim]would PUT stage for {opportunity_id}: {result.would_send}[/dim]")
        else:
            console.print(
                f"[green]{opp.get('name', opportunity_id)} moved from "
                f"'{current_stage_text}' to '{target_stage_text}'.[/green]"
            )


@app.command("audit")
def audit_command(limit: int = typer.Option(50, help="How many recent entries to show")) -> None:
    """Show the local write audit log (T3.4) — most recent first."""
    console = Console()
    with AuditLog() as audit:
        entries = audit.recent(limit)

    table = Table(title=f"Write audit log (last {len(entries)})")
    table.add_column("When")
    table.add_column("Opportunity")
    table.add_column("Action")
    table.add_column("Detail")
    table.add_column("Dry-run")
    table.add_column("Success")

    for entry in entries:
        when = datetime.fromtimestamp(entry.timestamp_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
        table.add_row(
            when,
            entry.opportunity_id,
            entry.action,
            entry.detail,
            "yes" if entry.dry_run else "no",
            "yes" if entry.success else "[red]no[/red]",
        )

    console.print(table)


if __name__ == "__main__":
    app()
