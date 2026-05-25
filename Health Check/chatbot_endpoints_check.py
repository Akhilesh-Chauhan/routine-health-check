"""Interactive functional health check on 6 specialized chatbot domains.

Some domains are public, others sit behind the same AWS Cognito gate as the dev
environment (shared client_id=6evh56qnt3r4ppu1mkmsbi1o6g). We reuse
`_dev_browser_profile/` for its Cognito session and re-auth if it has expired.

For each bot we: open page -> click launcher -> type query -> wait <=30s for a
substantive bot reply.
"""
import json, os, time
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

PROFILE_DIR = "/home/user/NeGD/Claude Code/Health Check/_dev_browser_profile"
ART_DIR     = "/home/user/NeGD/Claude Code/Health Check/_hc_artifacts"
os.makedirs(ART_DIR, exist_ok=True)
IST = timezone(timedelta(hours=5, minutes=30))

COGNITO_HOST = "myscheme.auth.ap-south-1.amazoncognito.com"
COGNITO_USER = os.environ.get("DEV_COGNITO_USER", "devadmin")
COGNITO_PASS = os.environ.get("DEV_COGNITO_PASS", "Myscheme@3211")

# (domain_url, query, optional_human_name)
TARGETS = [
    ("https://doe.myscheme.in/",         "what is GFR",
        "D.o.E Sahayak"),
    ("https://psq.myscheme.in/",         "AI summit 2026",
        "PSQ"),
    ("https://sandarbh.myscheme.in/",    "What initiatives government has taken for financial inclusion & digital payments?",
        "Sandarbh"),
    ("https://nmc.myscheme.in/",         "What do I need to establish a medical college in India?",
        "NMC"),
    ("https://pib.myscheme.in/",         "Is the Modi Loan Scheme offering ₹75,000 to citizens real?",
        "TATHYA (PIB)"),
    ("https://sports-psq.myscheme.in/",  "Khelo India",
        "SAI Sahayak"),
]

# Error / empty / 500 substrings that disqualify a reply
ERROR_STRINGS = [
    "something went wrong",
    "internal server error",
    "error 500",
    "we're sorry",
    "please try again later",
    "request failed",
]

report = {
    "started_ist": datetime.now(IST).isoformat(timespec="seconds"),
    "bots": [],
}

def snap(page, tag):
    path = f"{ART_DIR}/chatbot_{tag}.png"
    try:
        page.screenshot(path=path, full_page=False)
    except Exception:
        pass
    return path

def cognito_login_inline(page):
    """If we're on Cognito, fill devadmin creds and submit."""
    if COGNITO_HOST not in (page.url or ""):
        return False
    try:
        u = page.locator("input#signInFormUsername:visible").first
        p = page.locator("input#signInFormPassword:visible").first
        s = page.locator("button[name='signInSubmitButton']:visible, input[type=submit][name='signInSubmitButton']:visible").first
        u.wait_for(state="visible", timeout=15_000)
        u.fill(COGNITO_USER); p.fill(COGNITO_PASS)
        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=20_000):
                s.click()
        except PWTimeout:
            pass
        time.sleep(2)
        return True
    except Exception as e:
        return False

def find_chat_launcher(page):
    """Return a Locator for the bot launcher button, or None."""
    candidates = [
        "#chat-toggle-button",
        "button[title^='Chat with' i]",
        "button.fixed.bottom-6.right-6",
        "button.fixed.bottom-7.right-7",
    ]
    for sel in candidates:
        loc = page.locator(sel).first
        try:
            if loc.count() > 0 and loc.is_visible():
                return loc, sel
        except Exception:
            continue
    # Fallback: any fixed-position bottom-right small-ish button
    handle = page.evaluate_handle(r"""
      () => Array.from(document.querySelectorAll('button')).find(b => {
        const cs = getComputedStyle(b);
        const r = b.getBoundingClientRect();
        return cs.position === 'fixed' && r.bottom > innerHeight - 200 &&
               r.right > innerWidth - 200 && r.width > 30 && r.width < 200;
      })
    """)
    el = handle.as_element()
    if el:
        return el, "fallback:fixed-br-button"
    return None, None

def find_chat_input(page):
    """Find the chat text input. Try textarea first, then text input."""
    selectors = [
        "textarea:visible",
        "input[placeholder*='Ask' i]:visible",
        "input[placeholder*='Type' i]:visible",
        "input[placeholder*='Message' i]:visible",
        "input[type='text']:visible",
    ]
    for sel in selectors:
        loc = page.locator(sel).last  # prefer last (chat input usually last on page)
        try:
            if loc.count() > 0 and loc.is_visible():
                return loc, sel
        except Exception:
            continue
    return None, None

def check_one_bot(page, url, query, name):
    result = {"url": url, "name": name, "query": query}
    t_overall = time.perf_counter()
    try:
        # Navigate (handle Cognito if it appears)
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except PWTimeout:
            pass
        time.sleep(1.5)
        if COGNITO_HOST in (page.url or ""):
            cognito_login_inline(page)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PWTimeout:
                pass
            time.sleep(2)
        if COGNITO_HOST in (page.url or ""):
            raise RuntimeError("Stuck on Cognito after auto-auth — credentials may be wrong or rate-limited")

        # Locate + click launcher
        launcher, launcher_sel = find_chat_launcher(page)
        if launcher is None:
            raise RuntimeError("Chatbot launcher not found")
        result["launcher_sel"] = launcher_sel
        # Many of these launchers have CSS animations (animate-pulse) which
        # cause Playwright actionability waits to time out. Use a short timeout
        # first, then force the click via JS dispatch.
        click_ok = False
        try:
            launcher.click(timeout=5_000)
            click_ok = True
        except Exception:
            try:
                launcher.click(timeout=3_000, force=True)
                click_ok = True
            except Exception:
                # JS dispatch fallback (works around pointer-events / overlay issues)
                try:
                    page.evaluate("(el) => el.click()", launcher)
                    click_ok = True
                except Exception as e:
                    raise RuntimeError(f"Launcher click failed (all 3 strategies): {e}")
        if not click_ok:
            raise RuntimeError("Launcher click could not be performed")
        time.sleep(3)

        # Find input
        inp, inp_sel = find_chat_input(page)
        if inp is None:
            raise RuntimeError("Chat input field not found after opening chat")
        result["input_sel"] = inp_sel

        # Capture baseline body text
        baseline_text = page.evaluate("() => (document.body && document.body.innerText) || ''")
        baseline_len = len(baseline_text)

        # Type query and submit
        inp.click()
        inp.fill(query)
        send_t = time.perf_counter()
        inp.press("Enter")

        # Poll up to 30s for substantive growth past the query echo
        deadline = time.time() + 30
        new_text_tail = ""
        latency_ms = None
        bot_replied = False
        while time.time() < deadline:
            time.sleep(0.7)
            try:
                cur_text = page.evaluate("() => (document.body && document.body.innerText) || ''")
            except Exception:
                continue
            growth = len(cur_text) - baseline_len
            # Approx: growth must be > len(query) + some bot reply tokens
            min_growth = max(80, len(query) + 60)
            if growth >= min_growth:
                # Trim out the user's query echo to capture the new content tail
                new_text_tail = cur_text[baseline_len:]
                # Strip the first occurrence of the query in the new chunk
                idx = new_text_tail.find(query)
                if idx >= 0:
                    candidate = new_text_tail[idx+len(query):].strip()
                else:
                    candidate = new_text_tail.strip()
                # Need at least some non-trivial content beyond the echo
                if len(candidate) >= 40:
                    new_text_tail = candidate[:1200]
                    latency_ms = (time.perf_counter() - send_t) * 1000
                    bot_replied = True
                    break

        overall_ms = (time.perf_counter() - t_overall) * 1000
        result["total_duration_ms"] = round(overall_ms, 1)

        if not bot_replied:
            result.update(verdict="DOWN",
                          detail="No substantive bot reply detected within 30s",
                          artifact=snap(page, name.lower().replace(" ", "_").replace("(","").replace(")","") + "_timeout"))
            return result

        result["reply_latency_ms"] = round(latency_ms, 1)
        result["reply_excerpt"] = new_text_tail[:400].replace("\n", " | ")

        # Error / empty detection
        low = new_text_tail.lower()
        if any(s in low for s in ERROR_STRINGS):
            result.update(verdict="DOWN",
                          detail="Bot replied with an error/exception string",
                          artifact=snap(page, name.lower().replace(" ", "_").replace("(","").replace(")","") + "_errreply"))
            return result
        # Anything that looks like a Cognito bounce/login text
        if any(s in low for s in ["sign in with your username", "incorrect username or password"]):
            result.update(verdict="DOWN", detail="Reply area shows auth bounce text",
                          artifact=snap(page, name.lower().replace(" ", "_") + "_auth"))
            return result
        result.update(verdict="UP", detail="Bot returned a populated reply")
        return result
    except Exception as e:
        overall_ms = (time.perf_counter() - t_overall) * 1000
        result.update(total_duration_ms=round(overall_ms,1), verdict="DOWN",
                      detail=f"{type(e).__name__}: {e}",
                      artifact=snap(page, (name or "bot").lower().replace(" ","_") + "_exc"))
        return result

def run():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            viewport={"width": 1366, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for url, q, nm in TARGETS:
            r = check_one_bot(page, url, q, nm)
            report["bots"].append(r)

        verdicts = [b["verdict"] for b in report["bots"]]
        if all(v == "UP" for v in verdicts):
            report["overall"] = "HEALTHY"
        elif any(v == "DOWN" for v in verdicts):
            report["overall"] = "DEGRADED (one or more bots unresponsive)"
        else:
            report["overall"] = "DEGRADED"
        report["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
        ctx.close()
        print(json.dumps(report, indent=2))

if __name__ == "__main__":
    run()
