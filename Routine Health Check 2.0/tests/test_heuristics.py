"""D12(b): the login scripts now share auth.heuristics.looks_logged_in.

These pin the canonical post-login detection the three login poll loops rely on.
"""
from __future__ import annotations

import pytest

from health_check.auth import heuristics


class FakePage:
    def __init__(self, url, body=""):
        self._url = url
        self._body = body

    @property
    def url(self):
        return self._url

    def evaluate(self, _js):
        return self._body


@pytest.mark.parametrize("tenant,host", [
    ("prod", "auth.myscheme.gov.in"),
    ("dev", "devauth.myscheme.gov.in"),
    ("umang", "myauth.umangapp.in"),
])
def test_logged_in_on_post_login_landing(tenant, host):
    page = FakePage(f"https://{host}/", "Welcome Sahil! Please choose a platform to continue")
    assert heuristics.looks_logged_in(page, tenant) is True


@pytest.mark.parametrize("tenant,host", [
    ("prod", "auth.myscheme.gov.in"),
    ("dev", "devauth.myscheme.gov.in"),
    ("umang", "myauth.umangapp.in"),
])
def test_signin_surface_is_not_logged_in(tenant, host):
    page = FakePage(f"https://{host}/", "Sign in to your account. Enter mobile, send OTP")
    assert heuristics.looks_logged_in(page, tenant) is False


def test_mid_oauth_host_is_not_logged_in():
    page = FakePage("https://digilocker.meripehchaan.gov.in/signin", "Welcome")
    assert heuristics.looks_logged_in(page, "prod") is False


def test_wrong_host_is_not_logged_in():
    page = FakePage("https://example.com/", "Please choose a platform to continue")
    assert heuristics.looks_logged_in(page, "prod") is False


def test_umang_app_host_landing_counts_as_logged_in():
    # UMANG's OTP flow often settles on a workspace app host rather than back on
    # myauth.umangapp.in. Reaching one (past the sign-in guards) must close the
    # window — otherwise a *successful* login hangs forever on the auth-host gate.
    for host in ("myapp.umangapp.in", "mycms.umangapp.in", "myforms.umangapp.in"):
        page = FakePage(f"https://{host}/national-e-governance-division", "Dashboard")
        assert heuristics.looks_logged_in(page, "umang") is True, host


def test_umang_stuck_on_digilocker_consent_is_not_logged_in():
    # Regression for the observed hang: the browser sat on the DigiLocker
    # MeriPehchaan consent/signup page the whole time. That is a sign-in surface,
    # so it must NOT be read as logged-in (the window correctly keeps waiting).
    page = FakePage(
        "https://digilocker.meripehchaan.gov.in/signinv2/oauth_partner/"
        "...redirect_uri=myauth.umangapp.in/digilocker/signin/callback...signup=signup",
        "Consent to share your details",
    )
    assert heuristics.looks_logged_in(page, "umang") is False


def test_umang_app_host_signin_surface_is_not_logged_in():
    # If an app host itself shows a sign-in prompt, that is NOT logged-in.
    page = FakePage("https://myapp.umangapp.in/", "Sign in to your account")
    assert heuristics.looks_logged_in(page, "umang") is False


def test_sign_out_text_counts_as_logged_in():
    page = FakePage("https://auth.myscheme.gov.in/dashboard", "Account · Sign Out")
    assert heuristics.looks_logged_in(page, "prod") is True


def test_prod_platform_chooser_is_logged_in_even_with_marketing_copy():
    # Regression: prod's post-login chooser ("please choose a platform to
    # continue") must read as logged-in even if the page also carries marketing
    # copy like "New to myScheme?" — prod must NOT treat that as a sign-in
    # surface (a shared, over-broad list made the login window never close).
    body = ("Welcome! Please choose a platform to continue. "
            "New to myScheme? Choose a platform to sign in.")
    prod_page = FakePage("https://auth.myscheme.gov.in/", body)
    assert heuristics.looks_logged_in(prod_page, "prod") is True
    # dev DOES treat that copy as a sign-in surface (its pre-login devauth text).
    dev_page = FakePage("https://devauth.myscheme.gov.in/", body)
    assert heuristics.looks_logged_in(dev_page, "dev") is False
