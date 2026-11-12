# Setting up the agent on another machine

How to get `lever` running from scratch on a new Mac. Takes about 15 minutes, most of it
waiting for downloads.

## Requirements

- **macOS.** Both API keys are read from the macOS Keychain through the `security` CLI
  ([keychain.py](../src/lever_agent/keychain.py)). On Linux or Windows the agent won't start.
  There is deliberately no `.env` fallback (see the security notes in [PLAN.md](PLAN.md)).
- **Read access to the private repo** [xsomx1/lever-agent](https://github.com/xsomx1/lever-agent).
- **A Lever API key** with the scopes listed in the [README](../README.md#access).
- **An OpenAI API key** from the Xsolla corporate OpenAI organization, with access to
  `gpt-6.1-terra` ([ADR-0006](adr/0006-openai-gpt-6-1-terra.md)).

You don't need to install Python yourself: `uv` downloads Python 3.13, the version pinned in
`.python-version`.

## 1. Install the tooling

```bash
brew install uv gh
```

```bash
gh auth login
```

## 2. Clone and install dependencies

```bash
gh repo clone xsomx1/lever-agent ~/lever-agent
```

```bash
cd ~/lever-agent && git switch feature/lever-automation-agent && uv sync
```

`feature/lever-automation-agent` is the working branch. The repo has no `main`.

## 3. Put the keys in the Keychain

Both keys go under your macOS user as the account, with these service names:

| Service | Key |
|---|---|
| `lever-api-key` | Lever API key |
| `openai-api-key` | OpenAI API key (`sk-proj-…`) |

> **Don't use the interactive `-w` prompt.** It silently truncates input to 128 characters.
> OpenAI project keys are 164 characters long, so the key ends up truncated and the API
> returns `401 invalid_api_key`. Pass the key from the clipboard instead.

For each key, copy it to the clipboard, then run the matching command:

```bash
security add-generic-password -U -a "$USER" -s lever-api-key -w "$(pbpaste)"
```

```bash
security add-generic-password -U -a "$USER" -s openai-api-key -w "$(pbpaste)"
```

Clear the clipboard afterwards:

```bash
pbcopy < /dev/null
```

**Moving keys from your old Mac?** On the old machine, this copies a key to the clipboard
without printing it. Paste it on the new machine with the commands above.

```bash
security find-generic-password -a "$USER" -s openai-api-key -w | pbcopy
```

## 4. Check that it works

These cost nothing and write nothing to Lever:

```bash
uv run pytest -q
```

```bash
uv run lever postings mine
```

```bash
uv run lever digest
```

If the last two print tables, the Lever key works. For the OpenAI key, screen one candidate.
This is a real API call and costs well under a cent. Without `--post-notes` nothing is written
to Lever.

```bash
uv run lever screen f5349e52-94b9-4eb7-aaea-e83b001854a3 --limit 1
```

A `KeychainReadError` means a key is missing under that service name. An OpenAI `401` means
the key is wrong or truncated (see step 3).

## 5. Optional: run the digest on a schedule

[scripts/com.nzinevich.lever-agent.digest.plist](../scripts/com.nzinevich.lever-agent.digest.plist)
runs `lever digest` Mon–Fri at 11:00 local time. It hardcodes the original machine's paths:
the repo folder, `/Users/n.zinevich`, and `/opt/homebrew/bin/uv`. This installs a copy with
this machine's paths. Run it from the repo root:

```bash
mkdir -p ~/Library/Logs/lever-agent && sed -e "s|/Users/n.zinevich/Desktop/Desktop/Level Automation Agent|$PWD|g" -e "s|/Users/n.zinevich|$HOME|g" -e "s|/opt/homebrew/bin/uv|$(command -v uv)|g" scripts/com.nzinevich.lever-agent.digest.plist > ~/Library/LaunchAgents/com.nzinevich.lever-agent.digest.plist && plutil -lint ~/Library/LaunchAgents/com.nzinevich.lever-agent.digest.plist
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.nzinevich.lever-agent.digest.plist
```

The schedule follows the Mac's timezone. 11:00 means MSK only if the system timezone is
Europe/Moscow. Output goes to `~/Library/Logs/lever-agent/digest-<date>.log`. To turn it off:

```bash
launchctl bootout gui/$(id -u)/com.nzinevich.lever-agent.digest
```

## What does not carry over

- **`state/lever_agent.db`** (git-ignored, [ADR-0004](adr/0004-local-state-sqlite.md)) holds
  the digest snapshots and the write audit log. A new machine starts with an empty one. So
  the first `lever digest` has nothing to diff against yet, and `lever audit` shows no
  history. To keep the history, copy the file from the old machine into `state/` by hand.
  It holds opportunity IDs and short details only, no candidate names or resumes.
- **Rubrics.** `lever screen` only works for postings that have a file in
  `config/rubrics/<posting_id>.yaml`. Right now that's 3 of the 9 postings in
  `lever postings mine`.

## Setting it up for someone else

The agent is single-user by design ([ADR-0001](adr/0001-standalone-personal-agent.md)).
Another person would need their own Lever key, and would have to change `MY_LEVER_UID` in
[config.py](../src/lever_agent/config.py). That ID decides which postings count as "mine" and
whose name goes on every write to Lever (`perform_as`).
