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
