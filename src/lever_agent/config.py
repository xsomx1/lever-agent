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

# Same convention for the Anthropic key, needed from Epic 2 on.
ANTHROPIC_KEYCHAIN_SERVICE = "anthropic-api-key"

# Epic 3 — writing back to Lever.

# The only tag this agent ever adds. A fixed constant on purpose: Lever tags
# are free-text, case-sensitive, and auto-created on write, so a typo would
# silently mint a new tag rather than reusing this one (docs/CONTEXT.md §3.4).
SCREENING_TAG = "screened"

# "AI Screened" stage — hard-blocked as a stage-move target until T0.7
# (who else writes to it) is answered. See docs/PLAN.md T0.7 and T3.3.
AI_SCREENED_STAGE_ID = "011016a8-16d0-44f4-b95e-1af10019606f"
