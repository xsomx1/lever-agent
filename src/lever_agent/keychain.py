"""Read API keys from the macOS Keychain at runtime.

Deliberately the only place these keys are read from. No `.env`, no
environment variable, no value ever written to a file or logged. See
docs/PLAN.md T0.3 and the security notes at the end of that file.
"""

from __future__ import annotations

import getpass
import os
import subprocess

from lever_agent.config import KEYCHAIN_SERVICE, OPENAI_KEYCHAIN_SERVICE


class KeychainReadError(RuntimeError):
    """Raised when a key cannot be read from the Keychain."""


def _read_keychain_secret(service: str) -> str:
    """Equivalent to: security find-generic-password -a "$USER" -s <service> -w"""
    # $USER isn't guaranteed under launchd (T1.4) the way it is in an
    # interactive shell — fall back to getpass, which asks the OS directly.
    user = os.environ.get("USER") or getpass.getuser()
    if not user:
        raise KeychainReadError("could not determine the current user — cannot look up the Keychain entry")

    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", user, "-s", service, "-w"],
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
            f"Keychain lookup for service '{service}' failed "
            f"(account '{user}'): {exc.stderr.strip()}"
        ) from exc

    value = result.stdout.strip()
    if not value:
        raise KeychainReadError(f"Keychain entry '{service}' for account '{user}' is empty")
    return value


def get_lever_api_key() -> str:
    """Return the Lever API key stored in the macOS Keychain (T0.3)."""
    return _read_keychain_secret(KEYCHAIN_SERVICE)


def get_openai_api_key() -> str:
    """Return the OpenAI API key stored in the macOS Keychain (ADR-0006)."""
    return _read_keychain_secret(OPENAI_KEYCHAIN_SERVICE)
