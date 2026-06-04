from health_check.checks._primitives import route_result, looks_login_bounce
from health_check.reporting.status import Verdict

SSO_URLS = ["digilocker.meripehchaan.gov.in", "auth.myscheme.gov.in"]
SSO_BODY = ["sign in to your account", "send otp"]

def test_login_bounce_detected_by_url():
    assert looks_login_bounce("https://auth.myscheme.gov.in/x", "", SSO_URLS, SSO_BODY)

def test_login_bounce_detected_by_body():
    assert looks_login_bounce("https://app/x", "Please Send OTP", SSO_URLS, SSO_BODY)

def test_no_bounce_when_clean():
    assert not looks_login_bounce("https://mycms.umangapp.in/dashboard", "Dashboard Users", SSO_URLS, SSO_BODY)

def test_route_http_error_is_down():
    r = route_result(status=503, final_url="https://x/", body="boom", signals=["dashboard"], sso_urls=SSO_URLS, sso_body=SSO_BODY)
    assert r["verdict"] == Verdict.DOWN

def test_route_bounce_is_degraded():
    r = route_result(status=200, final_url="https://auth.myscheme.gov.in/", body="send otp", signals=["dashboard"], sso_urls=SSO_URLS, sso_body=SSO_BODY)
    assert r["verdict"] == Verdict.DEGRADED

def test_route_missing_signal_is_degraded():
    r = route_result(status=200, final_url="https://app/x", body="totally unrelated text", signals=["dashboard"], sso_urls=SSO_URLS, sso_body=SSO_BODY)
    assert r["verdict"] == Verdict.DEGRADED

def test_route_ok_is_up():
    r = route_result(status=200, final_url="https://app/x", body="Dashboard and users", signals=["dashboard"], sso_urls=SSO_URLS, sso_body=SSO_BODY)
    assert r["verdict"] == Verdict.UP
