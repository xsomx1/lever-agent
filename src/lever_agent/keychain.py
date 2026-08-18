"""Read the Lever API key from the macOS Keychain at runtime.

Deliberately the only place this key is read from. No `.env`, no environment
variable, no value ever written to a file or logged. See docs/PLAN.md T0.3 and
the security notes at the end of that file.
"""

from __future__ import annotations

import os
import subprocess

from lever_agent.config import KEYCHAIN_SERVICE


class KeychainReadError(RuntimeError):
    """Raised when the Lever API key cannot be read from the Keychain."""


def get_lever_api_key() -> str:
    """Return the Lever API key stored in the macOS Keychain.

    Equivalent to:
        security find-generic-password -a "$USER" -s lever-api-key -w
    """
    user = os.environ.get("USER")
    if not user:
        raise KeychainReadError("$USER is not set — cannot look up the Keychain entry")

    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-a",
                user,
                "-s",
                KEYCHAIN_SERVICE,
                "-w",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise KeychainReadError(
            "'security' CLI not found — this only works on macOS"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise KeychainReadError(
            f"Keychain lookup for service '{KEYCHAIN_SERVICE}' failed "
            f"(account '{user}'): {exc.stderr.strip()}"
        ) from exc

    key = result.stdout.strip()
    if not key:
        raise KeychainReadError(
            f"Keychain entry '{KEYCHAIN_SERVICE}' for account '{user}' is empty"
        )
    return key
