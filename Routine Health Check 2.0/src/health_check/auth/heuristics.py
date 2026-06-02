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
        "post_login": [
            "welcome ", "please choose a platform to continue",
            # The UMANG integration check treats these same words as proof of a
            # live SSO session — mirror them so a finished login auto-closes.
            "choose a platform to continue", "sign out",
        ],
        "signin_body": [
            "sign in to your account", "enter mobile", "send otp", "security pin",
            "already a user?", "choose a platform to sign in", "new to myscheme?",
        ],
        "signin_url": ["digilocker.meripehchaan.gov.in", "/oidc/v1/auth", "eparichay/signin"],
        # After OTP, UMANG's flow often settles on a workspace *app* host rather
        # than back on the auth host. Reaching one of these (and NOT a sign-in
        # surface) is itself proof the session was established, so close on it
        # too — otherwise a *successful* login would still hang on the auth-host
        # gate below.
        "app_hosts": ["myapp.umangapp.in", "mycms.umangapp.in", "myforms.umangapp.in"],
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
    # Never treat an active sign-in / OTP / consent surface as logged-in,
    # regardless of host (e.g. the DigiLocker MeriPehchaan consent page).
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
    # Landing on a known post-login app host (and past the sign-in guards
    # above) is itself proof the session is live — UMANG's OTP flow can settle
    # on the app rather than back on its auth host.
    if any(h in url for h in cfg.get("app_hosts", ())):
        return True
    # Otherwise require the tenant's auth host AND a positive post-login signal.
    if cfg["host"] not in url:
        return False
    return any(s in body for s in cfg["post_login"])
