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


def test_sign_out_text_counts_as_logged_in():
    page = FakePage("https://auth.myscheme.gov.in/dashboard", "Account · Sign Out")
    assert heuristics.looks_logged_in(page, "prod") is True
