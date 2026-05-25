"""Internal route health check for https://cms.myscheme.gov.in/ (NeGD tenant)
using the authenticated persistent profile.

STEP 1 -> dashboard accessibility (halt on fail)
STEP 2 -> sequential sub-route checks
"""
import json, os, time
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PROFILE_DIR = "/home/user/NeGD/Claude Code/Health Check/_browser_profile"
ART_DIR = "/home/user/NeGD/Claude Code/Health Check/_hc_artifacts"
os.makedirs(ART_DIR, exist_ok=True)
IST = timezone(timedelta(hours=5, minutes=30))

ORG_BASE = "https://cms.myscheme.gov.in/national-e-governance-division"
DASHBOARD = f"{ORG_BASE}/dashboard"

ROUTES = [
    ("Schemes Repository", f"{ORG_BASE}/schemes",  ["scheme"]),
    ("User Management",    f"{ORG_BASE}/users",    ["user", "member", "role", "email"]),
    ("Approval Mailbox",   f"{ORG_BASE}/mailbox",  ["mailbox", "approval", "request", "submitted", "inbox"]),
    ("User Profile",       f"{ORG_BASE}/profile",  ["profile", "name", "email"]),
]

LOGIN_LOOP_URL = ["auth.myscheme.gov.in", "digilocker.meripehchaan.gov.in", "/oidc/v1/auth", "eparichay/signin"]
LOGIN_LOOP_BODY = ["sign in to your account", "enter mobile", "send otp", "security pin",
                   "please choose a platform to continue"]

report = {
    "target": "https://cms.myscheme.gov.in/",
    "tenant": "national-e-governance-division",
    "started_ist": datetime.now(IST).isoformat(timespec="seconds"),
    "steps": [],
}

def snap(page, tag):
    path = f"{ART_DIR}/cms_{tag}.png"
    try:
        page.screenshot(path=path, full_page=False)
    except Exception:
        pass
    return path

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
        resp = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        if resp is not None:
            status_code = resp.status
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except PWTimeout:
            pass
        time.sleep(1.5)
        final_url = page.url
        body = page.evaluate("() => (document.body && document.body.innerText) || ''")[:2000]
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    ms = (time.perf_counter() - t0) * 1000

    base = {
        "name": name, "url": url, "final_url": final_url,
        "http_status": status_code, "duration_ms": round(ms, 1),
        "body_excerpt": body[:240].replace("\n", " "),
    }
    if err:
        base.update(verdict="DOWN", detail=err, artifact=snap(page, name.lower().replace(" ", "_") + "_err"))
        return base
    if status_code is not None and status_code >= 400:
        base.update(verdict="DOWN", detail=f"HTTP {status_code}",
                    artifact=snap(page, name.lower().replace(" ", "_") + f"_http{status_code}"))
        return base
    if looks_like_login_loop(final_url, body):
        base.update(verdict="DEGRADED", detail=f"Bounced to sign-in surface ({final_url})",
                    artifact=snap(page, name.lower().replace(" ", "_") + "_loginloop"))
        return base

    body_l = body.lower()
    sig_hit = any(s in body_l for s in signals) if signals else True
    if not sig_hit and body:
        base.update(verdict="DEGRADED",
                    detail=f"Page loaded but expected signals {signals} not found",
                    artifact=snap(page, name.lower().replace(" ", "_") + "_thin"))
        return base
    base.update(verdict="UP", detail=f"HTTP {status_code if status_code is not None else '?'}, content signals present", artifact=None)
    return base

def run():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            viewport={"width": 1366, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # ---------- STEP 1 ----------
        s1 = check_route(page, "CMS Dashboard", DASHBOARD,
                         ["dashboard", "schemes", "users", "mailbox", "total", "metric", "analytics"])
        report["steps"].append(s1)
        if s1.get("verdict") != "UP":
            report["overall"] = "DOWN (CMS portal unreachable)"
            report["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
            ctx.close()
            print(json.dumps(report, indent=2))
            return

        # ---------- STEP 2 ----------
        for name, url, sig in ROUTES:
            report["steps"].append(check_route(page, name, url, sig))

        verdicts = [s["verdict"] for s in report["steps"]]
        if all(v == "UP" for v in verdicts):
            report["overall"] = "HEALTHY"
        elif any(v == "DOWN" for v in verdicts):
            report["overall"] = "DEGRADED (one or more routes DOWN)"
        else:
            report["overall"] = "DEGRADED"
        report["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
        ctx.close()
        print(json.dumps(report, indent=2))

if __name__ == "__main__":
    run()
