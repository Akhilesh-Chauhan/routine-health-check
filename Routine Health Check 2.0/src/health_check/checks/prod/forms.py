"""Internal route health check for https://forms.myscheme.gov.in/ (NeGD tenant)
using the authenticated persistent profile.

STEP 1 -> landing page; click 'Build Now'; verify redirect to tenant dashboard
STEP 2 -> sequential sub-route checks: formlist, submissions, templates
"""
from health_check.paths import ARTIFACTS_DIR
from health_check.checks._common import make_snap
from health_check.checks._primitives import route_result
from health_check.reporting.status import Verdict
from health_check.browser.playwright_driver import PlaywrightDriver
import json, os, time
from datetime import datetime, timezone, timedelta

ART_DIR = str(ARTIFACTS_DIR)
os.makedirs(ART_DIR, exist_ok=True)
IST = timezone(timedelta(hours=5, minutes=30))

BASE = "https://forms.myscheme.gov.in/"
ORG_BASE = "https://forms.myscheme.gov.in/national-e-governance-division"
DASHBOARD = f"{ORG_BASE}/dashboard"

SUBROUTES = [
    ("Form List",        f"{ORG_BASE}/formlist",    ["form", "name", "status", "created"]),
    ("Form Submissions", f"{ORG_BASE}/submissions", ["submission", "form", "submitted", "applicant", "no "]),
    ("Form Templates",   f"{ORG_BASE}/templates",   ["template", "form"]),
]

LOGIN_LOOP_URL = ["auth.myscheme.gov.in", "digilocker.meripehchaan.gov.in", "/oidc/v1/auth", "eparichay/signin"]
LOGIN_LOOP_BODY = ["sign in to your account", "enter mobile", "send otp", "security pin",
                   "please choose a platform to continue"]

report = {
    "target": BASE,
    "tenant": "national-e-governance-division",
    "started_ist": datetime.now(IST).isoformat(timespec="seconds"),
    "steps": [],
}

snap = make_snap(ART_DIR, "forms_", full_page=False)

def looks_like_login_loop(url, body):
    u = (url or "").lower(); b = (body or "").lower()
    return any(h in u for h in LOGIN_LOOP_URL) or any(h in b for h in LOGIN_LOOP_BODY)

def check_route(page, name, url, signals):
    t0 = time.perf_counter()
    status_code = None
    final_url = url
    body = ""
    err = None
    try:
        status_code = page.goto(url, timeout_ms=30_000)
        time.sleep(1.5)
        final_url = page.url
        body = (page.text() or "")[:2000]
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    ms = (time.perf_counter() - t0) * 1000

    base = {
        "name": name, "url": url, "final_url": final_url,
        "http_status": status_code, "duration_ms": round(ms, 1),
        "body_excerpt": body[:240].replace("\n", " "),
    }
    tag = name.lower().replace(" ", "_")
    if err:
        base.update(verdict=Verdict.DOWN, detail=err, artifact=snap(page, tag + "_err"))
        return base
    # Shared verdict ladder. Empty body must not trip the missing-signal branch
    # (original guarded it with `and body`), so signals are only enforced when a
    # body was captured.
    outcome = route_result(status=status_code, final_url=final_url, body=body,
                           signals=signals if body else [],
                           sso_urls=LOGIN_LOOP_URL, sso_body=LOGIN_LOOP_BODY)
    v = outcome["verdict"]
    if v == Verdict.DOWN:
        base.update(verdict=v, detail=f"HTTP {status_code}",
                    artifact=snap(page, tag + f"_http{status_code}"))
    # route_result already classified a bounce as DEGRADED; this re-detect only picks the bounce-specific detail/artifact — do NOT remove it or bounces lose their dedicated message/screenshot.
    elif looks_like_login_loop(final_url, body):
        base.update(verdict=Verdict.DEGRADED, detail=f"Bounced to sign-in surface ({final_url})",
                    artifact=snap(page, tag + "_loginloop"))
    elif v == Verdict.DEGRADED:
        base.update(verdict=v, detail=f"Page loaded but expected signals {signals} not found",
                    artifact=snap(page, tag + "_thin"))
    else:
        base.update(verdict=Verdict.UP,
                    detail=f"HTTP {status_code if status_code is not None else '?'}, content signals present",
                    artifact=None)
    return base

def run():
    driver = PlaywrightDriver()
    page = driver.open("prod")
    try:
        # ---------- STEP 1 ----------
        t0 = time.perf_counter()
        s1 = {"name": "Landing + Build Now", "url": BASE}
        try:
            landing_status = page.goto(BASE, timeout_ms=30_000)
            time.sleep(1)

            # Authenticated session may auto-redirect past the marketing landing
            # straight to the dashboard. Skip the CTA click in that case.
            cur_url = page.url
            if cur_url.startswith(DASHBOARD) or cur_url.startswith(ORG_BASE):
                ms = (time.perf_counter() - t0) * 1000
                s1.update(verdict=Verdict.UP, duration_ms=round(ms, 1), final_url=cur_url,
                          detail=f"Authenticated session auto-routed to dashboard (skipped Build Now CTA): {cur_url}")
                report["steps"].append(s1)
                for name, url, sig in SUBROUTES:
                    report["steps"].append(check_route(page, name, url, sig))
                verdicts = [s["verdict"] for s in report["steps"]]
                if all(v == "UP" for v in verdicts):
                    report["overall"] = Verdict.UP
                elif any(v == "DOWN" for v in verdicts):
                    report["overall"] = "DEGRADED (one or more routes DOWN)"
                else:
                    report["overall"] = Verdict.DEGRADED
                report["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
                print(json.dumps(report, indent=2))
                return

            # Find Build Now control
            build_now = None
            for sel in [
                "a:has-text('Build Now')",
                "button:has-text('Build Now')",
                "[role='button']:has-text('Build Now')",
                "text=/build\\s*now/i",
            ]:
                if page.is_visible(sel):
                    build_now = sel
                    break
            if build_now is None:
                raise RuntimeError("'Build Now' control not found on landing page")

            page.click_nav(build_now, timeout_ms=25_000)
            page.wait_idle()
            time.sleep(1)
            final_url = page.url
            body = (page.text() or "")[:600]
            ms = (time.perf_counter() - t0) * 1000

            if final_url.rstrip("/") == DASHBOARD.rstrip("/") or final_url.startswith(DASHBOARD):
                if looks_like_login_loop(final_url, body):
                    s1.update(verdict=Verdict.DOWN, duration_ms=round(ms, 1), final_url=final_url,
                              detail="Reached dashboard URL but page is a sign-in surface",
                              artifact=snap(page, "step1_login_loop"))
                else:
                    s1.update(verdict=Verdict.UP, duration_ms=round(ms, 1), final_url=final_url,
                              detail=f"Build Now routed to tenant dashboard (landing HTTP {landing_status})")
            else:
                s1.update(verdict=Verdict.DOWN, duration_ms=round(ms, 1), final_url=final_url,
                          detail=f"Expected redirect to {DASHBOARD} but got {final_url}",
                          artifact=snap(page, "step1_wrong_dest"))
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            s1.update(verdict=Verdict.DOWN, duration_ms=round(ms, 1),
                      detail=f"{type(e).__name__}: {e}",
                      artifact=snap(page, "step1_exc"))
        report["steps"].append(s1)

        if s1.get("verdict") != "UP":
            report["overall"] = "DOWN (GovForm service unreachable)"
            report["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
            print(json.dumps(report, indent=2))
            return

        # ---------- STEP 2 ----------
        for name, url, sig in SUBROUTES:
            report["steps"].append(check_route(page, name, url, sig))

        verdicts = [s["verdict"] for s in report["steps"]]
        if all(v == "UP" for v in verdicts):
            report["overall"] = Verdict.UP
        elif any(v == "DOWN" for v in verdicts):
            report["overall"] = "DEGRADED (one or more routes DOWN)"
        else:
            report["overall"] = Verdict.DEGRADED
        report["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
        print(json.dumps(report, indent=2))
    finally:
        driver.close()

def main():
    run()


if __name__ == "__main__":
    main()
