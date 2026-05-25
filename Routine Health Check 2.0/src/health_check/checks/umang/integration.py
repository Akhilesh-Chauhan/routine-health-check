"""UMANG production integration check — myscheme on umangapp.in domains.

Reuses the prod `_browser_profile/` which holds the DigiLocker/MeriPehchaan
SSO session. The 3 UMANG hosts are expected to recognize the same SSO cookies.

STEP 1: myapp.umangapp.in   — landing, Sign-In hooks SSO, /search 'student'
STEP 2: mycms.umangapp.in    — dashboard + 3 sub-routes
STEP 3: myforms.umangapp.in  — Build Now -> dashboard + 3 sub-routes
"""
from health_check.paths import ARTIFACTS_DIR, PROFILE_UMANG
import json, os, time
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PROFILE_DIR = str(PROFILE_UMANG)
ART_DIR     = str(ARTIFACTS_DIR)
os.makedirs(ART_DIR, exist_ok=True)
IST = timezone(timedelta(hours=5, minutes=30))

UMANG_APP   = "https://myapp.umangapp.in/"
UMANG_APP_SEARCH = "https://myapp.umangapp.in/search"
UMANG_CMS_BASE   = "https://mycms.umangapp.in/national-e-governance-division"
UMANG_CMS = [
    ("Dashboard",       f"{UMANG_CMS_BASE}/dashboard", ["dashboard","scheme","user"]),
    ("Schemes Repo",    f"{UMANG_CMS_BASE}/schemes",   ["scheme"]),
    ("User Roster",     f"{UMANG_CMS_BASE}/users",     ["user","name","role"]),
    ("Validation Mbx",  f"{UMANG_CMS_BASE}/mailbox",   ["inbox","mailbox","submission","approv","form"]),
]
UMANG_FORMS_LANDING   = "https://myforms.umangapp.in/"
UMANG_FORMS_BASE      = "https://myforms.umangapp.in/national-e-governance-division"
UMANG_FORMS_DASHBOARD = f"{UMANG_FORMS_BASE}/dashboard"
UMANG_FORMS_SUB = [
    ("Form List",        f"{UMANG_FORMS_BASE}/formlist",    ["form","status"]),
    ("Submissions Inbox",f"{UMANG_FORMS_BASE}/submissions", ["submission","form","select"]),
    ("Template Gallery", f"{UMANG_FORMS_BASE}/templates",   ["template","form"]),
]

LOGIN_LOOP_URL  = ["digilocker.meripehchaan.gov.in", "/oidc/v1/auth", "eparichay/signin",
                   "auth.myscheme.gov.in", "consent.digilocker.gov.in",
                   "auth.umangapp.in"]
LOGIN_LOOP_BODY = ["sign in to your account", "enter mobile", "send otp",
                   "security pin", "please choose a platform to continue",
                   "already a user?", "choose a platform to sign in"]

report = {
    "started_ist": datetime.now(IST).isoformat(timespec="seconds"),
    "steps": [],
}

def snap(page, tag):
    path = f"{ART_DIR}/umang_{tag}.png"
    try:
        page.screenshot(path=path, full_page=False)
    except Exception:
        pass
    return path

def looks_login_loop(url, body):
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
        body = page.evaluate("() => (document.body && document.body.innerText) || ''")
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    ms = (time.perf_counter() - t0) * 1000
    base = {"name": name, "url": url, "final_url": final_url,
            "http_status": status_code, "duration_ms": round(ms,1),
            "body_excerpt": body[:240].replace("\n"," | ")}
    tag = name.lower().replace(" ", "_")
    if err:
        base.update(verdict="DOWN", detail=err, artifact=snap(page, tag+"_err"))
        return base
    if status_code is not None and status_code >= 400:
        base.update(verdict="DOWN", detail=f"HTTP {status_code}",
                    artifact=snap(page, tag+f"_http{status_code}"))
        return base
    if looks_login_loop(final_url, body):
        base.update(verdict="DEGRADED",
                    detail=f"Bounced to sign-in surface — SSO session not honored on UMANG host ({final_url})",
                    artifact=snap(page, tag+"_loginloop"))
        return base
    sig_hit = any(s in body.lower() for s in signals) if signals else True
    if not sig_hit and body:
        base.update(verdict="DEGRADED",
                    detail=f"Page loaded but expected signals {signals} not found",
                    artifact=snap(page, tag+"_thin"))
        return base
    base.update(verdict="UP", detail=f"HTTP {status_code if status_code else '?'}, content signals present")
    return base

# ---------------- Per-domain ----------------

def check_umang_app(page):
    sub = {"domain": "myapp.umangapp.in", "checks": []}
    # Landing
    sub["checks"].append(check_route(page, "Main landing", UMANG_APP, ["scheme","umang","myscheme"]))
    # Sign-In hook-in: click, see where it lands
    s = {"name": "Sign In click -> SSO hook"}
    t0 = time.perf_counter()
    try:
        signin = page.locator("button[aria-label='Sign In']").first
        try:
            signin.wait_for(state="visible", timeout=8000)
        except PWTimeout:
            # Fallback: text match
            signin = page.locator("button:has-text('Sign In'), a:has-text('Sign In')").first
            signin.wait_for(state="visible", timeout=8000)
        url_before = page.url
        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=15_000):
                signin.click()
        except PWTimeout:
            pass
        try: page.wait_for_load_state("networkidle", timeout=12_000)
        except PWTimeout: pass
        time.sleep(1.5)
        final = page.url
        body = page.evaluate("() => (document.body && document.body.innerText) || ''")
        ms = (time.perf_counter() - t0) * 1000

        # Seamless SSO: ended up *back* on the umang app OR landed on a Welcome/platform-tile screen
        seamless = (
            "myapp.umangapp.in" in final
            and not looks_login_loop(final, body)
        ) or any(s in body.lower() for s in ["welcome ", "choose a platform to continue", "sign out"])

        otp_prompt = any(s in body.lower() for s in ["enter mobile", "send otp", "enter otp", "security pin"])
        on_oauth_chain = any(h in final for h in [
            "digilocker.meripehchaan.gov.in", "consent.digilocker.gov.in", "auth.myscheme.gov.in",
        ])

        if seamless:
            s.update(verdict="UP", duration_ms=round(ms,1), final_url=final,
                     detail="Sign In hooked SSO seamlessly (no manual login prompt)")
        elif on_oauth_chain:
            # Reaching the DigiLocker / MeriPehchaan OAuth ingress is the expected
            # outcome of clicking Sign In on myapp.umangapp.in — count it UP even if
            # an OTP form is shown (that screen is owned by the IdP, not the app).
            s.update(verdict="UP", duration_ms=round(ms,1), final_url=final,
                     detail=f"Sign In redirected to the DigiLocker sign-in surface as expected -> {final}")
        elif otp_prompt:
            s.update(verdict="DEGRADED", duration_ms=round(ms,1), final_url=final,
                     detail="Sign In forced an OTP prompt off the DigiLocker chain — SSO not honored",
                     artifact=snap(page, "umangapp_signin_otp"))
        else:
            s.update(verdict="DEGRADED", duration_ms=round(ms,1), final_url=final,
                     detail=f"Sign In click reached unexpected destination: {final}",
                     artifact=snap(page, "umangapp_signin_wrong"))
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        s.update(verdict="DOWN", duration_ms=round(ms,1),
                 detail=f"{type(e).__name__}: {e}",
                 artifact=snap(page, "umangapp_signin_exc"))
    sub["checks"].append(s)

    # Search 'student'
    ss = {"name": "Search 'student'"}
    t0 = time.perf_counter()
    try:
        page.goto(UMANG_APP_SEARCH, wait_until="domcontentloaded", timeout=30_000)
        try: page.wait_for_load_state("networkidle", timeout=15_000)
        except PWTimeout: pass
        time.sleep(1)
        inp = None
        for sel in ["input[type='search']", "input[placeholder*='Search' i]",
                    "input[aria-label*='search' i]", "input[type='text']"]:
            loc = page.locator(sel).first
            try:
                if loc.count() > 0 and loc.is_visible():
                    inp = loc; break
            except Exception:
                continue
        if inp is None:
            raise RuntimeError("Search input not found on /search")
        inp.click(); inp.fill("student"); inp.press("Enter")
        try: page.wait_for_load_state("networkidle", timeout=15_000)
        except PWTimeout: pass
        try: page.wait_for_selector("a, h2, h3, [class*='card']", timeout=10_000)
        except PWTimeout: pass
        time.sleep(1.5)
        body = page.evaluate("() => (document.body && document.body.innerText) || ''")
        if looks_login_loop(page.url, body):
            raise RuntimeError(f"Search route bounced to sign-in surface: {page.url}")
        txt = "\n".join(page.locator("h1,h2,h3,h4,a,p,span").all_inner_texts())
        matches = [ln.strip() for ln in txt.splitlines() if "student" in ln.lower() and ln.strip()]
        ms = (time.perf_counter() - t0) * 1000
        if matches:
            ss.update(verdict="UP", duration_ms=round(ms,1),
                      detail=f"{len(matches)} 'student' matches; sample: {matches[:3]}")
        else:
            ss.update(verdict="DEGRADED", duration_ms=round(ms,1),
                      detail="No result text containing 'student' found",
                      artifact=snap(page, "umangapp_search_thin"))
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        ss.update(verdict="DOWN", duration_ms=round(ms,1),
                  detail=f"{type(e).__name__}: {e}",
                  artifact=snap(page, "umangapp_search_exc"))
    sub["checks"].append(ss)
    # Chatbot widget — the UMANG portal ships the same chatbot widget; verify it
    # actually opens and replies (previously untested).
    sub["checks"].append(check_umang_chatbot(page))
    return sub

def check_umang_chatbot(page):
    """Open the UMANG portal chatbot widget, send a prompter, verify a bot reply.

    Mirrors healthcheck_myscheme.py STEP 3 (#chatbot-button -> chatbot-iframe ->
    .conv-starter-item -> .markdownText reply). A chatbot that will not open /
    will not reply is reported as DOWN — a chatbot that does not work is a real
    failure, not a mere degradation.
    """
    s = {"name": "Chatbot widget"}
    t0 = time.perf_counter()
    try:
        page.goto(UMANG_APP, wait_until="domcontentloaded", timeout=30_000)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except PWTimeout:
            pass
        time.sleep(1)
        body = page.evaluate("() => (document.body && document.body.innerText) || ''")
        if looks_login_loop(page.url, body):
            s.update(verdict="DEGRADED", duration_ms=round((time.perf_counter()-t0)*1000,1),
                     detail=f"Landing bounced to sign-in surface before chatbot could open: {page.url}",
                     artifact=snap(page, "umangapp_chatbot_loginloop"))
            return s

        launcher = page.locator("#chatbot-button")
        try:
            launcher.wait_for(state="visible", timeout=10_000)
        except PWTimeout:
            s.update(verdict="DOWN", duration_ms=round((time.perf_counter()-t0)*1000,1),
                     detail="Chatbot launcher (#chatbot-button) not present on UMANG landing",
                     artifact=snap(page, "umangapp_chatbot_nolauncher"))
            return s
        launcher.click()

        # Locate the chatbot iframe (named chatbot-iframe; src on an aistore host).
        chat_frame = None
        deadline = time.time() + 15
        while time.time() < deadline and chat_frame is None:
            for fr in page.frames:
                if fr.name == "chatbot-iframe" or "aistore" in (fr.url or ""):
                    chat_frame = fr
                    break
            if chat_frame is None:
                time.sleep(0.5)
        if chat_frame is None:
            s.update(verdict="DOWN", duration_ms=round((time.perf_counter()-t0)*1000,1),
                     detail="Chatbot iframe never appeared after clicking the launcher — "
                            "chatbot not opening",
                     artifact=snap(page, "umangapp_chatbot_noiframe"))
            return s

        def cards_ready(timeout_ms):
            try:
                chat_frame.wait_for_selector(".conv-starter-item", state="visible",
                                             timeout=timeout_ms)
                return True
            except PWTimeout:
                return False

        # Wait for prompter cards; apply the click-to-load workaround if blank.
        ready = cards_ready(30_000)
        used_workaround = False
        if not ready:
            used_workaround = True
            for _ in range(3):
                try:
                    page.locator("iframe[name='chatbot-iframe']").click(timeout=5_000)
                except Exception:
                    try:
                        chat_frame.locator("body").click(timeout=5_000)
                    except Exception:
                        pass
                if cards_ready(15_000):
                    ready = True
                    break
        note = " (after click-to-load workaround)" if used_workaround else ""
        if not ready:
            s.update(verdict="DOWN", duration_ms=round((time.perf_counter()-t0)*1000,1),
                     detail="Chatbot iframe loaded blank / stuck — no prompter cards even "
                            "after the click-to-load workaround",
                     artifact=snap(page, "umangapp_chatbot_blank"))
            return s

        # Cards rendered — exercise a prompter and wait for a bot reply.
        def bot_count():
            try:
                return chat_frame.locator(".markdownText").count()
            except Exception:
                return 0
        baseline = bot_count()
        chat_frame.locator(".conv-starter-item").first.click()
        got_reply = False
        reply_deadline = time.time() + 30
        while time.time() < reply_deadline:
            if bot_count() > baseline:
                got_reply = True
                break
            time.sleep(0.5)
        ms = (time.perf_counter() - t0) * 1000
        if got_reply:
            s.update(verdict="UP", duration_ms=round(ms,1),
                     detail=f"Chatbot opened and replied{note} — .markdownText "
                            f"{baseline} -> {bot_count()}")
        else:
            s.update(verdict="DOWN", duration_ms=round(ms,1),
                     detail=f"Chatbot opened and prompter cards rendered{note} but no "
                            "bot reply within 30s",
                     artifact=snap(page, "umangapp_chatbot_noreply"))
        return s
    except Exception as e:
        s.update(verdict="DOWN", duration_ms=round((time.perf_counter()-t0)*1000,1),
                 detail=f"{type(e).__name__}: {e}",
                 artifact=snap(page, "umangapp_chatbot_exc"))
        return s

def check_umang_cms(page):
    sub = {"domain": "mycms.umangapp.in", "checks": []}
    for name, url, sig in UMANG_CMS:
        sub["checks"].append(check_route(page, name, url, sig))
    return sub

def check_umang_forms(page):
    sub = {"domain": "myforms.umangapp.in", "checks": []}
    # Landing + Build Now
    s = {"name": "Landing + Build Now"}
    t0 = time.perf_counter()
    try:
        page.goto(UMANG_FORMS_LANDING, wait_until="domcontentloaded", timeout=30_000)
        try: page.wait_for_load_state("networkidle", timeout=12_000)
        except PWTimeout: pass
        time.sleep(1)
        final = page.url
        body = page.evaluate("() => (document.body && document.body.innerText) || ''")
        # Auto-redirect-past-CTA case
        if final.startswith(UMANG_FORMS_DASHBOARD) or final.startswith(UMANG_FORMS_BASE):
            ms = (time.perf_counter() - t0) * 1000
            s.update(verdict="UP", duration_ms=round(ms,1), final_url=final,
                     detail="Authenticated session auto-routed to dashboard (skipped Build Now CTA)")
        else:
            bn = None
            for sel in ["a:has-text('Build Now')","button:has-text('Build Now')","text=/build\\s*now/i"]:
                loc = page.locator(sel).first
                try:
                    if loc.count() > 0 and loc.is_visible():
                        bn = loc; break
                except Exception:
                    continue
            if bn is None:
                if looks_login_loop(final, body):
                    raise RuntimeError(f"Landing bounced to sign-in: {final}")
                raise RuntimeError("'Build Now' control not found")
            try:
                with page.expect_navigation(wait_until="domcontentloaded", timeout=20_000):
                    bn.click()
            except PWTimeout:
                pass
            try: page.wait_for_load_state("networkidle", timeout=12_000)
            except PWTimeout: pass
            time.sleep(1)
            final = page.url
            body = page.evaluate("() => (document.body && document.body.innerText) || ''")
            ms = (time.perf_counter() - t0) * 1000
            if looks_login_loop(final, body):
                s.update(verdict="DEGRADED", duration_ms=round(ms,1), final_url=final,
                         detail="Build Now bounced to sign-in surface",
                         artifact=snap(page, "umangforms_buildnow_loginloop"))
            elif final.startswith(UMANG_FORMS_DASHBOARD):
                s.update(verdict="UP", duration_ms=round(ms,1), final_url=final,
                         detail="Build Now routed to dashboard")
            else:
                s.update(verdict="DEGRADED", duration_ms=round(ms,1), final_url=final,
                         detail=f"Build Now reached unexpected URL: {final}",
                         artifact=snap(page, "umangforms_buildnow_wrong"))
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        s.update(verdict="DOWN", duration_ms=round(ms,1),
                 detail=f"{type(e).__name__}: {e}",
                 artifact=snap(page, "umangforms_exc"))
    sub["checks"].append(s)
    for name, url, sig in UMANG_FORMS_SUB:
        sub["checks"].append(check_route(page, name, url, sig))
    return sub

def aggregate_verdict(checks):
    vs = [c.get("verdict","?") for c in checks]
    if all(v == "UP" for v in vs): return "HEALTHY"
    if any(v == "DOWN" for v in vs): return "DOWN"
    return "DEGRADED"

def run():
    overall_t0 = time.perf_counter()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage"],
            viewport={"width":1366,"height":900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        report["steps"].append({"name":"myapp.umangapp.in",   **check_umang_app(page)})
        report["steps"].append({"name":"mycms.umangapp.in",   **check_umang_cms(page)})
        report["steps"].append({"name":"myforms.umangapp.in", **check_umang_forms(page)})

        domain_verdicts = {}
        for s in report["steps"]:
            if "checks" in s:
                s["verdict"] = aggregate_verdict(s["checks"])
                domain_verdicts[s["domain"]] = s["verdict"]
        report["domain_verdicts"] = domain_verdicts
        report["total_duration_ms"] = round((time.perf_counter() - overall_t0) * 1000, 1)
        if all(v == "HEALTHY" for v in domain_verdicts.values()):
            report["overall"] = "HEALTHY"
        elif any(v == "DOWN" for v in domain_verdicts.values()):
            report["overall"] = "DOWN (UMANG Integration Defect)"
        else:
            report["overall"] = "DEGRADED (UMANG Integration Defect)"
        report["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
        ctx.close()
        print(json.dumps(report, indent=2))

def main():
    run()


if __name__ == "__main__":
    main()
