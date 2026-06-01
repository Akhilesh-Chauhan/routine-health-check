"""Operator-supplied secrets (spec D8).

Credentials are NOT baked into source. They come from the process environment
or a gitignored `config/secrets.env` (simple KEY=VALUE lines). Loading is
lazy and best-effort: a missing file is fine, real env vars always win.

Security note: the dev AWS Cognito password was committed to source in earlier
history. Removing the literal default here does NOT purge it from git history —
it must be ROTATED by the operator (out of scope for this change).
"""
from __future__ import annotations

import functools
import os

from health_check import paths


@functools.lru_cache(maxsize=1)
def _load_secrets_env() -> None:
    """Read `config/secrets.env` (if present) into os.environ, without
    overriding anything already set in the real environment. Idempotent."""
    try:
        text = paths.SECRETS_ENV.read_text()
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def cognito_credentials() -> tuple[str, str | None]:
    """(username, password) for the shared dev AWS Cognito gate.

    Username falls back to the well-known, non-secret ``devadmin``; the
    password has NO source default — when it isn't configured the caller must
    degrade with a clear message instead of shipping a literal credential.
    Honours ``HC_DEV_COGNITO_*`` (preferred) and legacy ``DEV_COGNITO_*`` names.
    """
    _load_secrets_env()
    user = (os.environ.get("HC_DEV_COGNITO_USER")
            or os.environ.get("DEV_COGNITO_USER")
            or "devadmin")
    pwd = (os.environ.get("HC_DEV_COGNITO_PASS")
           or os.environ.get("DEV_COGNITO_PASS"))
    return user, pwd
