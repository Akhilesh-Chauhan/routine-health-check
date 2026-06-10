"""Workspace checks (govai/forms) must surface an SSO sign-out/sign-in bounce as
an AUTH_EXPIRED-detectable payload — not crash on a missing CTA and mislabel a
healthy service as "Workspace Inaccessible" / "GovForm service unreachable".

Regression for the 2026-06-10 incident: the per-app SSO token in the profile had
expired, so each workspace dashboard redirected the browser to
`auth.myscheme.gov.in/oidc/v1/session/end?...` (the "Do you want to sign-out?"
page). cms/umang recorded that bounce (final_url + "bounced to … sign-in" detail)
and the orchestrator relabelled them AUTH_EXPIRED, but govai/forms looked for
"Get Started"/"Build Now", raised RuntimeError, dropped final_url, and rolled up
to a scary service-DOWN that would page an on-call engineer about a non-outage.
"""
from __future__ import annotations

import json

import pytest

from health_check.checks.prod import govai, forms
from health_check.orchestration import master

# A real bounce URL shape captured from artifacts/master_report.json on 2026-06-10.
SIGNOUT_URL = (
    "https://auth.myscheme.gov.in/oidc/v1/session/end"
    "?id_token_hint=eyJhbGciOiJSUzI1NiJ9.payload.sig"
    "&post_logout_redirect_uri=https://govai.myscheme.in/logout"
)
SIGNOUT_BODY = "myScheme GovAI Auth Sign out Do you want to sign-out from myScheme GovAI? Yes No"


class FakeSignOutPage:
    """A page that has bounced to the OIDC sign-out surface: the dashboard URL
    redirected away and none of the workspace CTAs are present."""

    def __init__(self, url=SIGNOUT_URL, body=SIGNOUT_BODY):
        self._url = url
        self._body = body

    def goto(self, url, timeout_ms=None):
        return 200

    @property
    def url(self):
        return self._url

    def text(self):
        return self._body

    def is_visible(self, selector):
        return False  # no "Get Started" / "Build Now" on a sign-out page

    def click_nav(self, selector, timeout_ms=None):
        return None

    def wait_idle(self):
        return None

    def screenshot(self, path=None, full_page=False):
        return None


class FakeDriver:
    def __init__(self, page):
        self._page = page

    def open(self, tenant):
        return self._page

    def close(self):
        return None


def _run_check(check_module, monkeypatch, capsys):
    """Run a check module's run() against a sign-out page; return its payload."""
    monkeypatch.setattr(check_module, "PlaywrightDriver",
                        lambda: FakeDriver(FakeSignOutPage()))
    # Module-level report dict is reused across calls — reset it.
    check_module.report["steps"].clear()
    check_module.report.pop("overall", None)
    check_module.report.pop("ended_ist", None)
    capsys.readouterr()  # drop anything buffered before the run
    check_module.run()
    out = capsys.readouterr().out
    return json.loads(out)


@pytest.mark.parametrize("check_module", [govai, forms], ids=["govai", "forms"])
def test_signout_bounce_is_detectable_as_auth_expired(check_module, monkeypatch, capsys):
    payload = _run_check(check_module, monkeypatch, capsys)

    # The orchestrator relabels a row AUTH_EXPIRED only when detect_bounce sees
    # a bounced step in the payload. This is the contract that was broken.
    assert master.detect_bounce(payload), (
        f"{check_module.__name__} sign-out bounce not detectable by the "
        f"orchestrator — it would be mislabelled a service outage. "
        f"overall={payload.get('overall')!r}"
    )
    # And the check's own rollup must not claim the service is unreachable.
    overall = str(payload.get("overall", "")).upper()
    assert "AUTH_EXPIRED" in overall, overall
    assert "INACCESSIBLE" not in overall and "UNREACHABLE" not in overall, overall
