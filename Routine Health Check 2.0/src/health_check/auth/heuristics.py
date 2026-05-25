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


# Positive — body text that means the tenant is in the post-login state
# ("Welcome <name>! / Please choose a platform to continue / Sign Out").
POST_LOGIN_HINTS = [
    "welcome ",
    "please choose a platform to continue",
    "sign out",
]

# Negative — body text that means we're still on a sign-in surface.
SIGNIN_BODY_HINTS = [
    "sign in to your account",
    "enter mobile",
    "send otp",
    "enter otp",
    "security pin",
    "already a user?",
    "new user? sign up",
    "choose a platform to sign in",
    "new to myscheme?",
]

# Negative — URL fragments that mean we're mid-OAuth on a sign-in host.
SIGNIN_URL_HINTS = [
    "digilocker.meripehchaan.gov.in",
    "consent.digilocker.gov.in",
    "eparichay",
    "/oidc/v1/auth",
    "/signinv2",
]

# Each tenant's post-login landing lives at exactly this host.
EXPECTED_HOST = {
    "prod":  "auth.myscheme.gov.in",
    "dev":   "devauth.myscheme.gov.in",
    "umang": "myauth.umangapp.in",
}


def looks_logged_in(page: "Page", tenant: str) -> bool:
    """True only when the page has settled on the tenant's post-login landing.

    All three tenants share the gotcha that the post-login dashboard and the
    pre-login sign-in selector live at the same URL, so the two states must
    be distinguished by body content rather than URL alone.
    """
    expected_host = EXPECTED_HOST[tenant]
    try:
        url = (page.url or "").lower()
    except Exception:
        url = ""
    if expected_host not in url:
        return False
    if any(h in url for h in SIGNIN_URL_HINTS):
        return False
    try:
        body = page.evaluate(
            "() => (document.body && document.body.innerText) || ''"
        )[:4000].lower()
    except Exception:
        body = ""
    if any(s in body for s in SIGNIN_BODY_HINTS):
        return False
    return any(s in body for s in POST_LOGIN_HINTS)
