"""Lever agent CLI."""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from lever_agent.keychain import get_lever_api_key
from lever_agent.lever_client import LeverClient

app = typer.Typer(help="Personal Lever hiring agent.")
postings_app = typer.Typer(help="Posting-level commands.")
app.add_typer(postings_app, name="postings")

console = Console()


@postings_app.command("mine")
def postings_mine() -> None:
    """List postings where I'm the owner or a follower (T0.5)."""
    asyncio.run(_postings_mine())


async def _postings_mine() -> None:
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


if __name__ == "__main__":
    app()
