"""Shared logged-in/logged-out heuristics for the three auth tenants.

The v1 manual-login scripts each carry near-identical copies of these lists
and a `looks_logged_in(page)` function that differs only in which expected
host the post-login state must be on. Consolidating fixes the heuristic drift
v1's CLAUDE.md flagged (prod still misclassified `auth.myscheme.gov.in/`
itself as a sign-in surface; dev/UMANG had already learned to handle that).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page


# Per-tenant hint tables. These are the EXACT lists each login script used
# before they were consolidated — kept per-tenant on purpose: prod's post-login
# "platform chooser" must NOT be read as a sign-in surface, whereas dev/UMANG
# DO treat "choose a platform to sign in" / "new to myscheme?" as sign-in. A
# single shared negative list broke prod's auto-close (the window never closed
# after a successful login), so the distinction is preserved here.
_TENANTS = {
    "prod": {
        "host": "auth.myscheme.gov.in",
        "post_login": ["please choose a platform to continue", "sign out"],
        "signin_body": [
            "sign in to your account", "enter mobile", "send otp", "enter otp",
            "security pin", "already a user?", "new user? sign up",
        ],
        "signin_url": [
            "digilocker.meripehchaan.gov.in", "consent.digilocker.gov.in",
            "eparichay", "/oidc/v1/auth", "/signinv2",
        ],
    },
    "dev": {
        "host": "devauth.myscheme.gov.in",
        "post_login": ["welcome ", "please choose a platform to continue"],
        "signin_body": [
            "sign in to your account", "enter mobile", "send otp", "security pin",
            "already a user?", "choose a platform to sign in", "new to myscheme?",
        ],
        "signin_url": ["digilocker.meripehchaan.gov.in", "/oidc/v1/auth", "eparichay/signin"],
    },
    "umang": {
        "host": "myauth.umangapp.in",
        "post_login": ["welcome ", "please choose a platform to continue"],
        "signin_body": [
            "sign in to your account", "enter mobile", "send otp", "security pin",
            "already a user?", "choose a platform to sign in", "new to myscheme?",
        ],
        "signin_url": ["digilocker.meripehchaan.gov.in", "/oidc/v1/auth", "eparichay/signin"],
    },
}

# Where each tenant's post-login landing lives (for callers that want it).
EXPECTED_HOST = {t: cfg["host"] for t, cfg in _TENANTS.items()}


def looks_logged_in(page: "Page", tenant: str) -> bool:
    """True only when the page has settled on the tenant's post-login landing.

    All three tenants share the gotcha that the post-login dashboard and the
    pre-login sign-in selector live at the same URL, so the two states must be
    distinguished by body content rather than URL alone — and the distinguishing
    word lists differ per tenant (see _TENANTS).
    """
    cfg = _TENANTS[tenant]
    try:
        url = (page.url or "").lower()
    except Exception:
        url = ""
    if cfg["host"] not in url:
        return False
    if any(h in url for h in cfg["signin_url"]):
        return False
    try:
        body = page.evaluate(
            "() => (document.body && document.body.innerText) || ''"
        )[:4000].lower()
    except Exception:
        body = ""
    if any(s in body for s in cfg["signin_body"]):
        return False
    return any(s in body for s in cfg["post_login"])
