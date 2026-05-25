"""Dev environment pre-auth + workspace validation.

STEP 1: Pass the shared AWS Cognito gateway (devadmin / Myscheme@3211)
STEP 2: Sub-checks mirroring production for each dev subdomain
"""
from health_check.paths import ARTIFACTS_DIR, PROFILE_DEV
import json, os, time
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ART_DIR  = str(ARTIFACTS_DIR)
DEV_PROFILE = str(PROFILE_DEV)
os.makedirs(ART_DIR, exist_ok=True)
IST = timezone(timedelta(hours=5, minutes=30))

COGNITO_USER = os.environ.get("DEV_COGNITO_USER", "devadmin")
COGNITO_PASS = os.environ.get("DEV_COGNITO_PASS", "Myscheme@3211")
COGNITO_HOST = "myscheme.auth.ap-south-1.amazoncognito.com"

# Functional targets
DEV_MAIN     = "https://dev.myscheme.gov.in/"
DEV_SEARCH   = "https://dev.myscheme.gov.in/search"
DEV_AUTH     = "https://devauth.myscheme.gov.in/"
DEV_GOVAI    = "https://devgovai.myscheme.in/"
DEV_GOVAI_ORG  = "https://devgovai.myscheme.in/national-e-governance-division"
DEV_GOVAI_SUB  = [
    ("Knowledge Base", f"{DEV_GOVAI_ORG}/knowledge-bases", ["knowledge"]),
    ("My Assistants",  f"{DEV_GOVAI_ORG}/assistants",       ["assistant"]),
    ("Settings",       f"{DEV_GOVAI_ORG}/settings",         ["setting"]),
]
DEV_CMS_BASE = "https://devcms.myscheme.gov.in/national-e-governance-division"
DEV_CMS = [
    ("Dashboard",     f"{DEV_CMS_BASE}/dashboard", ["dashboard","schemes","users"]),
    ("Schemes",       f"{DEV_CMS_BASE}/schemes",   ["scheme"]),
    ("Users",         f"{DEV_CMS_BASE}/users",     ["user","name"]),
    ("Mailbox",       f"{DEV_CMS_BASE}/mailbox",   ["inbox","approv","submission","mailbox"]),
    ("Profile",       f"{DEV_CMS_BASE}/profile",   ["profile","name","email"]),
]
DEV_FORMS_BASE = "https://devforms.myscheme.gov.in/national-e-governance-division"
DEV_FORMS_LANDING = "https://devforms.myscheme.gov.in/"
DEV_FORMS_DASHBOARD = f"{DEV_FORMS_BASE}/dashboard"
DEV_FORMS_SUB = [
    ("Form List",        f"{DEV_FORMS_BASE}/formlist",    ["form","status"]),
    ("Form Submissions", f"{DEV_FORMS_BASE}/submissions", ["submission","form","select"]),
    ("Form Templates",   f"{DEV_FORMS_BASE}/templates",   ["template","form"]),
]
DEV_AISTORE   = "https://devaistore.myscheme.in/"
DEV_AISTORE_CARD_SELECTOR = "div.bg-secondary-200"

# Sign-in bounce detectors (post-Cognito, app still asks for devauth)
DEVAUTH_SIGNIN_URL_HINTS = ["devauth.myscheme.gov.in", "/oidc/v1/auth", "eparichay", "digilocker.meripehchaan"]
DEVAUTH_SIGNIN_BODY_HINTS = [
    "sign in to your account", "enter mobile", "send otp", "security pin",
    "please choose a platform to continue", "already a user?", "choose a platform to sign in",
]

report = {
    "started_ist": datetime.now(IST).isoformat(timespec="seconds"),
    "steps": [],
}

def snap(page, tag):
    path = f"{ART_DIR}/dev_{tag}.png"
    try:
        page.screenshot(path=path, full_page=False)
    except Exception:
        pass
    return path

def is_on_cognito(page):
    return COGNITO_HOST in (page.url or "")

def looks_devauth_loop(url, body):
    u = (url or "").lower(); b = (body or "").lower()
    return any(h in u for h in DEVAUTH_SIGNIN_URL_HINTS) or any(h in b for h in DEVAUTH_SIGNIN_BODY_HINTS)

def cognito_login(page, expected_redirect_host):
    """Submit Cognito credentials on the current page. Returns dict with outcome."""
    t0 = time.perf_counter()
    # Cognito renders TWO copies of the form (one hidden ASF, one visible).
    # Filter to the visible elements explicitly.
    user_loc = page.locator("input#signInFormUsername:visible").first
    pass_loc = page.locator("input#signInFormPassword:visible").first
    submit_loc = page.locator("button[name='signInSubmitButton']:visible, input[type=submit][name='signInSubmitButton']:visible").first
    try:
        user_loc.wait_for(state="visible", timeout=15_000)
    except PWTimeout:
        return {"verdict":"DOWN","detail":"Cognito form did not render (no visible username field)"}
    user_loc.fill(COGNITO_USER)
    pass_loc.fill(COGNITO_PASS)
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=20_000):
            submit_loc.click()
    except PWTimeout:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PWTimeout:
        pass
    time.sleep(1.5)
    ms = (time.perf_counter() - t0) * 1000
    final_url = page.url
    body = ""
    try:
        body = page.evaluate("() => (document.body && document.body.innerText) || ''")[:1500]
    except Exception:
        pass
    low = body.lower()
    # Look for typical Cognito error texts
    bad_creds = any(s in low for s in [
        "incorrect username or password", "bad credentials",
        "user does not exist", "password attempts exceeded",
        "your password has expired",
    ])
    if bad_creds or is_on_cognito(page):
        return {"verdict":"DOWN", "duration_ms":round(ms,1), "final_url":final_url,
                "detail":"Cognito rejected credentials or did not advance past login",
                "body_excerpt":body[:300].replace("\n"," | ")}
    if expected_redirect_host and expected_redirect_host not in final_url:
        return {"verdict":"DEGRADED","duration_ms":round(ms,1),"final_url":final_url,
                "detail":f"Cognito accepted but redirect host mismatched: expected {expected_redirect_host}"}
    return {"verdict":"UP","duration_ms":round(ms,1),"final_url":final_url,
            "detail":f"Cognito auth succeeded -> {final_url}"}

def goto_with_optional_cognito(page, url, ctx_label="visit"):
    """goto + auto-handle Cognito gate if it appears. Returns (final_url, body, on_devauth_signin)."""
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    try:
        page.wait_for_load_state("networkidle", timeout=12_000)
    except PWTimeout:
        pass
    time.sleep(1)
    if is_on_cognito(page):
        # Re-auth (Cognito session probably present but app re-prompted)
        r = cognito_login(page, None)
        if r["verdict"] != "UP":
            return page.url, "", False, r
        try:
            page.wait_for_load_state("networkidle", timeout=12_000)
        except PWTimeout:
            pass
        time.sleep(1)
    final = page.url
    body = ""
    try:
        body = page.evaluate("() => (document.body && document.body.innerText) || ''")
    except Exception:
        pass
    return final, body, looks_devauth_loop(final, body), None

# ---------------- Domain checks ----------------

def check_route(page, name, url, signals):
    t0 = time.perf_counter()
    final, body, devauth_bounce, cog_err = goto_with_optional_cognito(page, url)
    ms = (time.perf_counter() - t0) * 1000
    base = {"name": name, "url": url, "final_url": final,
            "duration_ms": round(ms,1),
            "body_excerpt": body[:200].replace("\n"," | ")}
    if cog_err:
        base.update(verdict="DOWN", detail=f"Cognito re-auth failure: {cog_err.get('detail')}",
                    artifact=snap(page, f"{name.lower().replace(' ','_')}_cogerr"))
        return base
    if devauth_bounce:
        base.update(verdict="DEGRADED",
                    detail="Bounced to dev SSO (devauth) sign-in surface — Cognito passed, but app needs devauth login (no credentials provided)",
                    artifact=snap(page, f"{name.lower().replace(' ','_')}_devauth"))
        return base
    body_l = body.lower()
    sig_hit = any(s in body_l for s in signals) if signals else True
    if not sig_hit and body:
        base.update(verdict="DEGRADED", detail=f"Page loaded but expected signals {signals} not found",
                    artifact=snap(page, f"{name.lower().replace(' ','_')}_thin"))
        return base
    base.update(verdict="UP", detail="Content signals present")
    return base

def check_dev_main(page):
    sub = {"domain": "dev.myscheme.gov.in", "checks": []}
    # Landing
    sub["checks"].append(check_route(page, "Main landing", DEV_MAIN, ["myscheme","scheme"]))
    if sub["checks"][-1]["verdict"] != "DOWN":
        # Sign In click -> verify it targets devauth host
        s = {"name": "Sign In click -> devauth"}
        t0 = time.perf_counter()
        try:
            signin = page.locator("button[aria-label='Sign In']").first
            try: signin.wait_for(state="visible", timeout=8000)
            except Exception: pass
            url_before = page.url
            try:
                with page.expect_navigation(wait_until="domcontentloaded", timeout=15_000):
                    signin.click()
            except PWTimeout:
                pass
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except PWTimeout:
                pass
            time.sleep(1)
            final = page.url
            ms = (time.perf_counter() - t0) * 1000
            # Any host along the dev OAuth chain is a valid progress signal:
            #   devauth.myscheme.gov.in (final callback target)
            #   digilocker.meripehchaan.gov.in (OAuth entry / OTP page)
            #   consent.digilocker.gov.in (consent step when DigiLocker session exists)
            sso_hosts = (
                "devauth.myscheme.gov.in",
                "digilocker.meripehchaan.gov.in",
                "consent.digilocker.gov.in",
            )
            dev_oauth_signals = ("client_id=LOC6FDB0D3", "state=myschemeDev",
                                 "redirect_uri=https%3A%2F%2Fdev.myscheme.gov.in",
                                 "myschemeDev", "LOC6FDB0D3")
            on_sso_host = any(h in final for h in sso_hosts)
            dev_oauth = any(sig in final for sig in dev_oauth_signals)
            if on_sso_host or dev_oauth:
                hit = next((h for h in sso_hosts if h in final), None)
                s.update(verdict="UP", duration_ms=round(ms,1), final_url=final,
                         detail=f"Sign In initiated dev OAuth flow (on {hit or 'dev-tagged URL'})")
            elif final == url_before:
                s.update(verdict="DEGRADED", duration_ms=round(ms,1),
                         detail="Sign In did not trigger navigation",
                         artifact=snap(page, "devmain_signin_nochange"))
            else:
                s.update(verdict="DEGRADED", duration_ms=round(ms,1),
                         detail=f"Sign In routed to unexpected destination: {final}",
                         artifact=snap(page, "devmain_signin_wrong"))
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            s.update(verdict="DOWN", duration_ms=round(ms,1),
                     detail=f"{type(e).__name__}: {e}",
                     artifact=snap(page, "devmain_signin_exc"))
        sub["checks"].append(s)

    # Search "student"
    ss = {"name": "Search 'student'"}
    t0 = time.perf_counter()
    try:
        final, body, dauth, cog_err = goto_with_optional_cognito(page, DEV_SEARCH)
        if cog_err:
            ss.update(verdict="DOWN", duration_ms=round((time.perf_counter()-t0)*1000,1),
                      detail=cog_err.get('detail'))
        else:
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
                raise RuntimeError("Search input not found")
            inp.click(); inp.fill("student"); inp.press("Enter")
            try: page.wait_for_load_state("networkidle", timeout=15_000)
            except PWTimeout: pass
            try: page.wait_for_selector("a, h2, h3, [class*='card']", timeout=10_000)
            except PWTimeout: pass
            time.sleep(1.5)
            txt = "\n".join(page.locator("h1,h2,h3,h4,a,p,span").all_inner_texts())
            matches = [ln.strip() for ln in txt.splitlines() if "student" in ln.lower() and ln.strip()]
            ms = (time.perf_counter() - t0) * 1000
            if matches:
                ss.update(verdict="UP", duration_ms=round(ms,1),
                          detail=f"{len(matches)} 'student' matches; sample: {matches[:3]}")
            else:
                ss.update(verdict="DEGRADED", duration_ms=round(ms,1),
                          detail="No result text containing 'student' found",
                          artifact=snap(page, "devmain_search_thin"))
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        ss.update(verdict="DOWN", duration_ms=round(ms,1),
                  detail=f"{type(e).__name__}: {e}", artifact=snap(page, "devmain_search_exc"))
    sub["checks"].append(ss)
    # Chatbot widget — the dev portal ships the same chatbot widget the prod
    # portal does; verify it actually opens and replies (previously untested).
    sub["checks"].append(check_dev_chatbot(page))
    return sub

def check_dev_chatbot(page):
    """Open the dev portal chatbot widget, send a prompter, verify a bot reply.

    Mirrors healthcheck_myscheme.py STEP 3 (#chatbot-button -> chatbot-iframe ->
    .conv-starter-item -> .markdownText reply). Unlike the prod check, a chatbot
    that will not open / will not reply is reported here as DOWN — a chatbot
    that does not work is a real failure, not a mere degradation.
    """
    s = {"name": "Chatbot widget"}
    t0 = time.perf_counter()
    try:
        final, body, dauth, cog_err = goto_with_optional_cognito(page, DEV_MAIN)
        if cog_err:
            s.update(verdict="DOWN", duration_ms=round((time.perf_counter()-t0)*1000,1),
                     detail=f"Cognito re-auth failure: {cog_err.get('detail')}")
            return s

        launcher = page.locator("#chatbot-button")
        try:
            launcher.wait_for(state="visible", timeout=10_000)
        except PWTimeout:
            s.update(verdict="DOWN", duration_ms=round((time.perf_counter()-t0)*1000,1),
                     detail="Chatbot launcher (#chatbot-button) not present on dev landing",
                     artifact=snap(page, "devmain_chatbot_nolauncher"))
            return s
        launcher.click()

        # Locate the chatbot iframe (named chatbot-iframe; src on (dev)aistore).
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
                     artifact=snap(page, "devmain_chatbot_noiframe"))
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
                     artifact=snap(page, "devmain_chatbot_blank"))
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
                     artifact=snap(page, "devmain_chatbot_noreply"))
        return s
    except Exception as e:
        s.update(verdict="DOWN", duration_ms=round((time.perf_counter()-t0)*1000,1),
                 detail=f"{type(e).__name__}: {e}",
                 artifact=snap(page, "devmain_chatbot_exc"))
        return s

def check_devgovai(page):
    sub = {"domain": "devgovai.myscheme.in", "checks": []}
    # Step 1: Get Started -> org workspace
    s = {"name": "Landing + Get Started"}
    t0 = time.perf_counter()
    try:
        final, body, dauth, cog_err = goto_with_optional_cognito(page, DEV_GOVAI)
        if cog_err:
            s.update(verdict="DOWN", detail=cog_err.get('detail')); sub["checks"].append(s)
        elif dauth:
            s.update(verdict="DEGRADED", duration_ms=round((time.perf_counter()-t0)*1000,1),
                     detail="Landing bounced to devauth sign-in",
                     artifact=snap(page, "devgovai_landing_devauth"))
            sub["checks"].append(s)
        else:
            # If the authenticated user is auto-redirected straight to the workspace,
            # the "Get Started" CTA never renders — count that as a pass.
            if final.startswith(DEV_GOVAI_ORG):
                ms = (time.perf_counter() - t0) * 1000
                s.update(verdict="UP", duration_ms=round(ms,1), final_url=final,
                         detail=f"Authenticated session auto-routed to workspace (skipped Get Started CTA): {final}")
                sub["checks"].append(s)
                for name, url, sig in DEV_GOVAI_SUB:
                    sub["checks"].append(check_route(page, name, url, sig))
                return sub
            gs = None
            for sel in ["a:has-text('Get Started')","button:has-text('Get Started')","text=/get\\s*started/i"]:
                loc = page.locator(sel).first
                try:
                    if loc.count() > 0 and loc.is_visible():
                        gs = loc; break
                except Exception:
                    continue
            if gs is None:
                raise RuntimeError("'Get Started' not found on landing")
            try:
                with page.expect_navigation(wait_until="domcontentloaded", timeout=20_000):
                    gs.click()
            except PWTimeout:
                pass
            try: page.wait_for_load_state("networkidle", timeout=12_000)
            except PWTimeout: pass
            time.sleep(1)
            final = page.url
            ms = (time.perf_counter() - t0) * 1000
            body = page.evaluate("() => (document.body && document.body.innerText) || ''")
            if looks_devauth_loop(final, body):
                s.update(verdict="DEGRADED", duration_ms=round(ms,1), final_url=final,
                         detail="Get Started click bounced to devauth sign-in (Cognito passed but workspace needs devauth login)",
                         artifact=snap(page, "devgovai_getstarted_devauth"))
            elif final.startswith(DEV_GOVAI_ORG):
                s.update(verdict="UP", duration_ms=round(ms,1), final_url=final,
                         detail="Get Started routed to org workspace")
            else:
                s.update(verdict="DEGRADED", duration_ms=round(ms,1), final_url=final,
                         detail=f"Get Started routed to unexpected URL: {final}",
                         artifact=snap(page, "devgovai_getstarted_wrong"))
            sub["checks"].append(s)
    except Exception as e:
        s.update(verdict="DOWN", detail=f"{type(e).__name__}: {e}",
                 artifact=snap(page, "devgovai_exc"))
        sub["checks"].append(s)
    # Step 2: sub-routes
    for name, url, sig in DEV_GOVAI_SUB:
        sub["checks"].append(check_route(page, name, url, sig))
    return sub

def check_devcms(page):
    sub = {"domain": "devcms.myscheme.gov.in", "checks": []}
    for name, url, sig in DEV_CMS:
        sub["checks"].append(check_route(page, name, url, sig))
    return sub

def check_devforms(page):
    sub = {"domain": "devforms.myscheme.gov.in", "checks": []}
    # Landing + Build Now
    s = {"name": "Landing + Build Now"}
    t0 = time.perf_counter()
    try:
        final, body, dauth, cog_err = goto_with_optional_cognito(page, DEV_FORMS_LANDING)
        if cog_err:
            s.update(verdict="DOWN", detail=cog_err.get('detail')); sub["checks"].append(s)
        elif dauth:
            s.update(verdict="DEGRADED", duration_ms=round((time.perf_counter()-t0)*1000,1),
                     detail="Landing bounced to devauth sign-in",
                     artifact=snap(page, "devforms_landing_devauth"))
            sub["checks"].append(s)
        else:
            # Authenticated session may auto-route past the landing CTA.
            if final.startswith(DEV_FORMS_DASHBOARD) or final.startswith(DEV_FORMS_BASE):
                ms = (time.perf_counter() - t0) * 1000
                s.update(verdict="UP", duration_ms=round(ms,1), final_url=final,
                         detail=f"Authenticated session auto-routed to dashboard (skipped Build Now CTA): {final}")
                sub["checks"].append(s)
                for name, url, sig in DEV_FORMS_SUB:
                    sub["checks"].append(check_route(page, name, url, sig))
                return sub
            bn = None
            for sel in ["a:has-text('Build Now')","button:has-text('Build Now')","text=/build\\s*now/i"]:
                loc = page.locator(sel).first
                try:
                    if loc.count() > 0 and loc.is_visible():
                        bn = loc; break
                except Exception:
                    continue
            if bn is None:
                raise RuntimeError("'Build Now' not found")
            try:
                with page.expect_navigation(wait_until="domcontentloaded", timeout=20_000):
                    bn.click()
            except PWTimeout:
                pass
            try: page.wait_for_load_state("networkidle", timeout=12_000)
            except PWTimeout: pass
            time.sleep(1)
            final = page.url
            body2 = page.evaluate("() => (document.body && document.body.innerText) || ''")
            ms = (time.perf_counter() - t0) * 1000
            if looks_devauth_loop(final, body2):
                s.update(verdict="DEGRADED", duration_ms=round(ms,1), final_url=final,
                         detail="Build Now bounced to devauth sign-in",
                         artifact=snap(page, "devforms_buildnow_devauth"))
            elif final.startswith(DEV_FORMS_DASHBOARD):
                s.update(verdict="UP", duration_ms=round(ms,1), final_url=final,
                         detail="Build Now routed to dashboard")
            else:
                s.update(verdict="DEGRADED", duration_ms=round(ms,1), final_url=final,
                         detail=f"Build Now routed to unexpected URL: {final}",
                         artifact=snap(page, "devforms_buildnow_wrong"))
            sub["checks"].append(s)
    except Exception as e:
        s.update(verdict="DOWN", detail=f"{type(e).__name__}: {e}",
                 artifact=snap(page, "devforms_exc"))
        sub["checks"].append(s)
    for name, url, sig in DEV_FORMS_SUB:
        sub["checks"].append(check_route(page, name, url, sig))
    return sub

def check_devaistore(page):
    sub = {"domain": "devaistore.myscheme.in", "checks": []}
    s = {"name": "Marketplace + card click"}
    t0 = time.perf_counter()
    try:
        final, body, dauth, cog_err = goto_with_optional_cognito(page, DEV_AISTORE)
        if cog_err:
            s.update(verdict="DOWN", detail=cog_err.get('detail')); sub["checks"].append(s); return sub
        if dauth:
            s.update(verdict="DEGRADED", duration_ms=round((time.perf_counter()-t0)*1000,1),
                     detail="Marketplace bounced to devauth sign-in",
                     artifact=snap(page, "devaistore_devauth"))
            sub["checks"].append(s); return sub
        # Wait for cards
        try: page.wait_for_selector(DEV_AISTORE_CARD_SELECTOR, state="visible", timeout=10_000)
        except PWTimeout: pass
        card_count = page.locator(DEV_AISTORE_CARD_SELECTOR).count()
        if card_count == 0:
            ms = (time.perf_counter() - t0) * 1000
            s.update(verdict="DOWN", duration_ms=round(ms,1),
                     detail="No bot cards rendered on dev marketplace",
                     artifact=snap(page, "devaistore_nocards"))
            sub["checks"].append(s); return sub
        url_before = page.url
        card = page.locator(DEV_AISTORE_CARD_SELECTOR).first
        clicked_text = card.inner_text()[:80].replace("\n", " ").strip()
        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=8_000):
                card.click()
        except PWTimeout:
            pass
        deadline = time.time() + 5
        sig = {}
        while time.time() < deadline:
            try:
                sig = page.evaluate(r"""
                  () => ({
                    url: location.href,
                    textareas: document.querySelectorAll('textarea').length,
                    welcome_present: /hi! i am|welcome|how can i help|i'm your assistant|i am your assistant/i.test(document.body.innerText || ''),
                    new_conv_btn: !!Array.from(document.querySelectorAll('button')).find(b => /new conversation/i.test(b.innerText || '')),
                    modals: document.querySelectorAll('[role=dialog], [class*="modal" i], [class*="drawer" i]').length,
                  })
                """)
            except Exception:
                sig = {}
            if sig.get("textareas",0) > 0 or sig.get("welcome_present") or sig.get("new_conv_btn") or sig.get("modals",0) > 0:
                break
            time.sleep(0.5)
        ms = (time.perf_counter() - t0) * 1000
        chat_present = sig.get("textareas",0) > 0 or sig.get("welcome_present") or sig.get("new_conv_btn")
        if chat_present:
            bits = []
            if sig.get("textareas"): bits.append(f"{sig['textareas']} <textarea>")
            if sig.get("welcome_present"): bits.append("welcome message")
            if sig.get("new_conv_btn"): bits.append("New Conversation")
            s.update(verdict="UP", duration_ms=round(ms,1), card_count=card_count,
                     clicked_card_text=clicked_text, chat_signals=sig,
                     detail="; ".join(bits))
        else:
            s.update(verdict="DEGRADED", duration_ms=round(ms,1), card_count=card_count,
                     clicked_card_text=clicked_text, chat_signals=sig,
                     detail="Card clicked but no chat UI rendered within 5s",
                     artifact=snap(page, "devaistore_nochat"))
        sub["checks"].append(s)
    except Exception as e:
        s.update(verdict="DOWN", detail=f"{type(e).__name__}: {e}",
                 artifact=snap(page, "devaistore_exc"))
        sub["checks"].append(s)
    return sub

# ---------------- Driver ----------------

def aggregate_verdict(checks):
    vs = [c.get("verdict","?") for c in checks]
    if all(v == "UP" for v in vs): return "HEALTHY"
    if any(v == "DOWN" for v in vs): return "DOWN"
    return "DEGRADED"

def run():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            DEV_PROFILE, headless=True,
            args=["--no-sandbox","--disable-dev-shm-usage"],
            viewport={"width":1366,"height":900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # ---------- STEP 1: Cognito Gate ----------
        gate_t0 = time.perf_counter()
        gate = {"name":"Cognito Gateway Authentication","user":COGNITO_USER}
        try:
            page.goto(DEV_MAIN, wait_until="domcontentloaded", timeout=30_000)
            try: page.wait_for_load_state("networkidle", timeout=10_000)
            except PWTimeout: pass
            time.sleep(1)
            if not is_on_cognito(page):
                # Already authenticated from a previous run (persistent profile)
                gate.update(verdict="UP",
                            duration_ms=round((time.perf_counter()-gate_t0)*1000,1),
                            detail=f"Reused existing Cognito session; landed at {page.url}",
                            already_authenticated=True)
            else:
                r = cognito_login(page, expected_redirect_host="dev.myscheme.gov.in")
                gate.update(r)
        except Exception as e:
            gate.update(verdict="DOWN",
                        duration_ms=round((time.perf_counter()-gate_t0)*1000,1),
                        detail=f"{type(e).__name__}: {e}",
                        artifact=snap(page,"cognito_exc"))
        report["steps"].append(gate)

        if gate.get("verdict") != "UP":
            report["overall"] = "DEV_AUTH: CRITICAL - Cognito authentication failed."
            report["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
            ctx.close()
            print(json.dumps(report, indent=2)); return

        # ---------- STEP 2: Per-domain checks ----------
        report["steps"].append({"name":"dev.myscheme.gov.in",  **check_dev_main(page)})
        report["steps"].append({"name":"devgovai.myscheme.in", **check_devgovai(page)})
        report["steps"].append({"name":"devcms.myscheme.gov.in", **check_devcms(page)})
        report["steps"].append({"name":"devforms.myscheme.gov.in", **check_devforms(page)})
        report["steps"].append({"name":"devaistore.myscheme.in", **check_devaistore(page)})

        # Compute per-domain verdicts and overall
        domain_verdicts = {}
        for s in report["steps"]:
            if "checks" in s:
                s["verdict"] = aggregate_verdict(s["checks"])
                domain_verdicts[s["domain"]] = s["verdict"]
        report["domain_verdicts"] = domain_verdicts
        if all(v == "HEALTHY" for v in domain_verdicts.values()):
            report["overall"] = "HEALTHY"
        elif any(v == "DOWN" for v in domain_verdicts.values()):
            report["overall"] = "DOWN (one or more dev domains failed)"
        else:
            report["overall"] = "DEGRADED"
        report["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
        ctx.close()
        print(json.dumps(report, indent=2))

def main():
    run()


if __name__ == "__main__":
    main()
