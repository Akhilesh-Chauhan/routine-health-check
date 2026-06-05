"""Internal workspace route health check for https://govai.myscheme.in/
using the authenticated persistent profile.

STEP 1 -> click 'Get Started', expect redirect to /national-e-governance-division
STEP 2a/b/c -> directly navigate to each sub-route, verify clean load
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

BASE = "https://govai.myscheme.in/"
ORG = "https://govai.myscheme.in/national-e-governance-division"
ROUTES = [
    ("Knowledge Base", "https://govai.myscheme.in/national-e-governance-division/knowledge-bases"),
    ("My Assistants",  "https://govai.myscheme.in/national-e-governance-division/assistants"),
    ("Settings",       "https://govai.myscheme.in/national-e-governance-division/settings"),
]

LOGIN_LOOP_HINTS = [
    "auth.myscheme.gov.in",
    "digilocker.meripehchaan.gov.in",
    "eparichay/signin",
    "/oidc/v1/auth",
]
LOGIN_BODY_HINTS = [
    "sign in to your account",
    "enter mobile",
    "send otp",
    "enter otp",
    "security pin",
    "please choose a platform to continue",  # auth landing page after login
]

report = {
    "target": BASE,
    "started_ist": datetime.now(IST).isoformat(timespec="seconds"),
    "steps": [],
}

snap = make_snap(ART_DIR, "govai_", full_page=False)

def looks_like_login_loop(url, body):
    u = (url or "").lower()
    b = (body or "").lower()
    if any(h in u for h in LOGIN_LOOP_HINTS): return True
    if any(h in b for h in LOGIN_BODY_HINTS): return True
    return False

def check_route(page, name, url):
    t0 = time.perf_counter()
    status_code = None
    final_url = url
    body = ""
    err = None
    try:
        status_code = page.goto(url, timeout_ms=30_000)
        time.sleep(1.5)
        final_url = page.url
        body = (page.text() or "")[:1500]
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    ms = (time.perf_counter() - t0) * 1000

    if err:
        art = snap(page, f"{name.lower().replace(' ', '_')}_err")
        return {
            "name": name, "url": url, "final_url": final_url,
            "http_status": status_code, "duration_ms": round(ms, 1),
            "verdict": Verdict.DOWN, "detail": err, "artifact": art,
            "body_excerpt": body[:200],
        }

    # Shared HTTP>=400 + login-bounce ladder via the primitive (the per-route
    # missing-signal decision below keeps govai's own no-guard semantics, which
    # differ from route_result for an empty signal list).
    outcome = route_result(status=status_code, final_url=final_url, body=body,
                           signals=[],  # signal decision handled locally below
                           sso_urls=LOGIN_LOOP_HINTS, sso_body=LOGIN_BODY_HINTS)
    if outcome["verdict"] == Verdict.DOWN:
        art = snap(page, f"{name.lower().replace(' ', '_')}_http{status_code}")
        return {
            "name": name, "url": url, "final_url": final_url,
            "http_status": status_code, "duration_ms": round(ms, 1),
            "verdict": Verdict.DOWN, "detail": f"HTTP {status_code}", "artifact": art,
            "body_excerpt": body[:200],
        }
    if looks_like_login_loop(final_url, body):
        art = snap(page, f"{name.lower().replace(' ', '_')}_loginloop")
        return {
            "name": name, "url": url, "final_url": final_url,
            "http_status": status_code, "duration_ms": round(ms, 1),
            "verdict": Verdict.DEGRADED,
            "detail": f"Page bounced to a sign-in surface (final URL: {final_url})",
            "artifact": art, "body_excerpt": body[:200],
        }

    # Optional content-presence sanity check per route
    text_lower = body.lower()
    expected_signals = {
        "Knowledge Base": ["knowledge", "base"],
        "My Assistants": ["assistant"],
        "Settings": ["setting"],
    }
    sig = expected_signals.get(name, [])
    sig_hit = any(s in text_lower for s in sig)
    verdict = Verdict.UP
    detail = f"HTTP {status_code if status_code is not None else '?'}, body excerpt ok"
    if not sig_hit and body:
        verdict = Verdict.DEGRADED
        detail = f"Page loaded but expected content signal {sig} not found"
        art = snap(page, f"{name.lower().replace(' ', '_')}_thin")
        return {
            "name": name, "url": url, "final_url": final_url,
            "http_status": status_code, "duration_ms": round(ms, 1),
            "verdict": verdict, "detail": detail, "artifact": art,
            "body_excerpt": body[:200],
        }
    return {
        "name": name, "url": url, "final_url": final_url,
        "http_status": status_code, "duration_ms": round(ms, 1),
        "verdict": verdict, "detail": detail, "artifact": None,
        "body_excerpt": body[:200],
    }

def run():
    driver = PlaywrightDriver()
    page = driver.open("prod")
    try:
        # ---------- STEP 1 ----------
        t0 = time.perf_counter()
        s1 = {"name": "Workspace Home + Get Started", "url": BASE}
        try:
            page.goto(BASE, timeout_ms=30_000)
            time.sleep(1)
            home_url = page.url
            home_body = (page.text() or "")[:800]

            # Authenticated session may auto-redirect past the marketing landing
            # straight to the org workspace. Treat that as a pass.
            if home_url.startswith(ORG):
                ms = (time.perf_counter() - t0) * 1000
                s1.update({
                    "verdict": Verdict.UP, "duration_ms": round(ms, 1),
                    "final_url": home_url,
                    "detail": f"Authenticated session auto-routed to workspace (skipped Get Started CTA): {home_url}",
                })
                report["steps"].append(s1)
                for name, url in ROUTES:
                    report["steps"].append(check_route(page, name, url))
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

            # Locate Get Started
            getstarted = None
            for sel in [
                "a:has-text('Get Started')",
                "button:has-text('Get Started')",
                "[role='button']:has-text('Get Started')",
                "text=/get\\s*started/i",
            ]:
                if page.is_visible(sel):
                    getstarted = sel
                    break
            if getstarted is None:
                snap(page, "step1_no_getstarted")
                raise RuntimeError(f"Get Started control not found on {home_url}")

            page.click_nav(getstarted, timeout_ms=20_000)
            page.wait_idle()
            time.sleep(1)
            final_url = page.url
            ms = (time.perf_counter() - t0) * 1000

            ok = final_url.rstrip("/") == ORG.rstrip("/") or final_url.startswith(ORG)
            if ok:
                s1.update({
                    "verdict": Verdict.UP, "duration_ms": round(ms, 1),
                    "final_url": final_url,
                    "detail": "Get Started routed to org workspace as expected",
                })
            else:
                art = snap(page, "step1_wrong_dest")
                s1.update({
                    "verdict": Verdict.DOWN, "duration_ms": round(ms, 1),
                    "final_url": final_url,
                    "detail": f"Expected redirect to {ORG} but got {final_url}",
                    "artifact": art,
                })
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            art = snap(page, "step1_exc")
            s1.update({
                "verdict": Verdict.DOWN, "duration_ms": round(ms, 1),
                "detail": f"{type(e).__name__}: {e}", "artifact": art,
            })
        report["steps"].append(s1)

        if s1.get("verdict") != "UP":
            report["overall"] = "DOWN (Workspace Inaccessible)"
            report["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
            print(json.dumps(report, indent=2))
            return

        # ---------- STEP 2: each sub-route ----------
        for name, url in ROUTES:
            report["steps"].append(check_route(page, name, url))

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
