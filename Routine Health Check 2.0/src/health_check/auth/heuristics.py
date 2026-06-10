"""Shared logged-in/logged-out heuristics for the three auth tenants.

The v1 manual-login scripts each carry near-identical copies of these lists
and a `looks_logged_in(page)` function that differs only in which expected
host the post-login state must be on. Consolidating fixes the heuristic drift
v1's CLAUDE.md flagged (prod still misclassified `auth.myscheme.gov.in/`
itself as a sign-in surface; dev/UMANG had already learned to handle that).
"""
from __future__ import annotations

import time
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


def why_not_logged_in(page: "Page", tenant: str) -> str:
    """Human-readable reason looks_logged_in() rejected `page`.

    Diagnostics only — mirrors the exact guard order in looks_logged_in() so a
    login that fails to auto-close tells us *which* gate the parked page tripped
    (the post-OTP visible tab often parks somewhere the detector doesn't expect).
    """
    cfg = _TENANTS[tenant]
    try:
        url = (page.url or "").lower()
    except Exception:
        return "url-unreadable"
    for h in cfg["signin_url"]:
        if h in url:
            return f"REJECT: on sign-in/OTP/consent URL ({h})"
    try:
        body = page.evaluate(
            "() => (document.body && document.body.innerText) || ''"
        )[:4000].lower()
    except Exception:
        body = "<body-unreadable>"
    for s in cfg["signin_body"]:
        if s in body:
            return f"REJECT: sign-in body text present ({s!r})"
    if any(h in url for h in cfg.get("app_hosts", ())):
        return "OK: on known post-login app host"
    if cfg["host"] not in url:
        return f"REJECT: host {cfg['host']!r} not in url"
    if any(s in body for s in cfg["post_login"]):
        return "OK: on auth host with post-login signal"
    return (f"REJECT: on {cfg['host']} but no post-login signal "
            f"{cfg['post_login']} in body")


def snapshot_login_state(ctx, tenant: str) -> str:
    """One diagnostic line per open page: its URL and why_not_logged_in()."""
    lines = []
    for pg in list(getattr(ctx, "pages", None) or []):
        try:
            url = pg.url
        except Exception:
            url = "<url-unreadable>"
        lines.append(f"    {url}\n        => {why_not_logged_in(pg, tenant)}")
    return "\n".join(lines) or "    <no open pages>"


def record_login_diagnostic(artifacts_dir, tenant: str, ctx, note: str = "") -> None:
    """Append a timestamped snapshot of why login hasn't auto-closed to
    `{artifacts_dir}/login_debug_{tenant}.log`. Best-effort; never raises.

    This turns the next interactive login into its own evidence run: if the
    window fails to auto-close, the parked page's URL + the exact rejecting
    guard land in this file for offline diagnosis.
    """
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        path = f"{artifacts_dir}/login_debug_{tenant}.log"
        with open(path, "a") as fh:
            fh.write(f"[{stamp}] {note}\n{snapshot_login_state(ctx, tenant)}\n\n")
    except Exception:
        pass


def find_logged_in_page(ctx, tenant: str):
    """Return the first open page in `ctx` that looks logged-in, else None.

    The MeriPehchaan / DigiLocker OAuth flow frequently lands the post-login
    state in a NEW tab while the original tab stays parked on the sign-in /
    consent surface. A login poller that only watches the tab it opened never
    sees the success and times out (the window appears not to auto-close even
    though the user *is* logged in). Checking every page fixes that.
    """
    for pg in list(getattr(ctx, "pages", None) or []):
        try:
            if looks_logged_in(pg, tenant):
                return pg
        except Exception:
            continue
    return None
