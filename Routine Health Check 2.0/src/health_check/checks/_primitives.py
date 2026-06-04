"""Reusable check primitives shared by the public / prod / dev / umang surfaces.

The DECISION logic (what verdict a set of observations maps to) is kept pure and
unit-testable here; the per-surface modules supply the I/O (driving the browser)
and pass the observations in. This is the single home for behaviour that was
previously copy-pasted (and drifting) across modules.
"""
from __future__ import annotations

from health_check.reporting.status import Verdict


def chatbot_widget_result(*, cards_ready: bool, got_reply: bool, frame_url: str,
                          on_blank: Verdict, on_no_reply: Verdict,
                          on_reply: Verdict, note: str = "") -> dict:
    """Map post-iframe chatbot-widget observations to a verdict dict.

    Each surface chooses its own outcome policy:
      - dev / umang: on_blank=DOWN, on_no_reply=DOWN, on_reply=UP (hard-fail)
      - public myscheme: on_blank=KNOWN_ISSUE, on_no_reply=KNOWN_ISSUE,
        on_reply=PASS (never-fail; the script forces overall UP)
    The launcher-missing / iframe-missing / login-bounce preconditions are NOT
    handled here — they stay in each surface as that surface already does them.
    """
    if not cards_ready:
        return {"verdict": on_blank,
                "detail": ("Chatbot iframe loaded blank / stuck — no prompter cards even "
                           f"after the click-to-load workaround{note} (frame on "
                           f"{frame_url or 'about:blank'}). Cause: chatbot embed redirects to "
                           "the Cognito hosted login inside the iframe and Cognito sets "
                           "X-Frame-Options: DENY, so it cannot render.")}
    if got_reply:
        return {"verdict": on_reply,
                "detail": f"Chatbot opened and replied{note}"}
    return {"verdict": on_no_reply,
            "detail": f"Chatbot opened and prompter cards rendered{note} but no bot reply within 30s"}


def looks_login_bounce(url: str, body: str, sso_urls: list[str],
                       sso_body: list[str]) -> bool:
    u = (url or "").lower(); b = (body or "").lower()
    return any(h in u for h in sso_urls) or any(h in b for h in sso_body)


def route_result(*, status, final_url: str, body: str, signals: list[str],
                 sso_urls: list[str], sso_body: list[str]) -> dict:
    """Map a navigated route's observations to a verdict dict (pure)."""
    if status is not None and status >= 400:
        return {"verdict": Verdict.DOWN, "detail": f"HTTP {status}"}
    if looks_login_bounce(final_url, body, sso_urls, sso_body):
        return {"verdict": Verdict.DEGRADED,
                "detail": f"Bounced to sign-in surface — SSO session not honored ({final_url})"}
    body_l = (body or "").lower()
    if signals and not any(s in body_l for s in signals):
        return {"verdict": Verdict.DEGRADED,
                "detail": f"Page loaded but expected signals {signals} not found"}
    return {"verdict": Verdict.UP, "detail": "Content signals present"}
