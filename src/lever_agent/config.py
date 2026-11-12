"""Static configuration for the Lever agent.

No secrets live here — the API key is read from the macOS Keychain at runtime
(see keychain.py). This module only holds values that are safe to commit.
"""

LEVER_API_BASE = "https://api.lever.co/v1"

# Nikita Zinevich's Lever user UID — the standing `perform_as` for every write
# this agent makes. Verified against the live API 2026-08-18 (see docs/PLAN.md T0.4).
MY_LEVER_UID = "a245ada8-57eb-4bf7-8354-4635c02627d4"

# Lever's steady-state rate limit is 10 req/s per API key (bursts to 20).
LEVER_RATE_LIMIT = 10

# Keychain lookup for the API key — never a .env file, never a shell-exported var.
KEYCHAIN_SERVICE = "lever-api-key"

# Same convention for the OpenAI key used by screening (ADR-0006).
OPENAI_KEYCHAIN_SERVICE = "openai-api-key"

# Epic 3 — writing back to Lever.

# The only tag this agent ever adds. A fixed constant on purpose: Lever tags
# are free-text, case-sensitive, and auto-created on write, so a typo would
# silently mint a new tag rather than reusing this one (docs/CONTEXT.md §3.4).
SCREENING_TAG = "screened"

# "AI Screened" stage. Was hard-blocked as a stage-move target pending T0.7;
# answered 2026-08-18 (Thomas Hansen) — no vendor/marketplace integration owns
# it, just manual use by some HR/hiring managers — so the block was lifted.
# See docs/CONTEXT.md §8 and docs/PLAN.md T0.7.
AI_SCREENED_STAGE_ID = "011016a8-16d0-44f4-b95e-1af10019606f"
