"""Health check for the AI Store marketplace at https://aistore.myscheme.in/.

STEP 1: load the store landing
STEP 2: click first bot card; verify chat workspace opens with input bar or welcome message
"""
import json, os, time
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ART_DIR = "/home/user/NeGD/Claude Code/Health Check/_hc_artifacts"
os.makedirs(ART_DIR, exist_ok=True)
IST = timezone(timedelta(hours=5, minutes=30))

BASE = "https://aistore.myscheme.in/"
CARD_SELECTOR = "div.bg-secondary-200"  # clickable bot card container

LANDING_TILE_SIGNALS = [
    "explore assistants", "store", "myscheme", "samajik", "rajmarg",
    "rr generator", "poshan", "poochho didi", "nsws", "nhai", "nfs sathi",
]

report = {
    "target": BASE,
    "started_ist": datetime.now(IST).isoformat(timespec="seconds"),
    "steps": [],
}

def snap(page, tag):
    path = f"{ART_DIR}/aistore_{tag}.png"
    try:
        page.screenshot(path=path, full_page=False)
    except Exception:
        pass
    return path

def run():
    overall_t0 = time.perf_counter()
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = b.new_context(viewport={"width": 1366, "height": 900})
        page = ctx.new_page()

        # ---------- STEP 1 ----------
        t0 = time.perf_counter()
        s1 = {"name": "Landing page", "url": BASE}
        try:
            resp = page.goto(BASE, wait_until="domcontentloaded", timeout=30_000)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PWTimeout:
                pass
            # Up to 10s for catalog to render
            try:
                page.wait_for_selector(CARD_SELECTOR, state="visible", timeout=10_000)
            except PWTimeout:
                pass
            status = resp.status if resp else None
            body = page.evaluate("() => (document.body && document.body.innerText) || ''")
            card_count = page.locator(CARD_SELECTOR).count()
            low = body.lower()
            sig_hit = sum(1 for kw in LANDING_TILE_SIGNALS if kw in low)
            ms = (time.perf_counter() - t0) * 1000

            s1.update(http_status=status, duration_ms=round(ms,1),
                      final_url=page.url, card_count=card_count,
                      tile_signal_hits=sig_hit,
                      body_excerpt=body[:240].replace("\n"," | "))
            if status is not None and status >= 400:
                s1.update(verdict="DOWN", detail=f"HTTP {status}", artifact=snap(page, "step1_http_err"))
            elif card_count == 0:
                s1.update(verdict="DOWN", detail="No bot cards rendered on landing", artifact=snap(page, "step1_no_cards"))
            elif sig_hit < 3:
                s1.update(verdict="DEGRADED", detail=f"Landing rendered but only {sig_hit} expected tile signals found",
                          artifact=snap(page, "step1_thin"))
            else:
                s1.update(verdict="UP", detail=f"HTTP {status}, {card_count} bot cards, {sig_hit} tile signals")
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            s1.update(verdict="DOWN", duration_ms=round(ms,1),
                      detail=f"{type(e).__name__}: {e}", artifact=snap(page, "step1_exc"))
        report["steps"].append(s1)

        if s1["verdict"] != "UP":
            report["overall"] = "DOWN (AI Store unreachable)"
            report["total_duration_ms"] = round((time.perf_counter() - overall_t0)*1000, 1)
            report["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
            ctx.close(); b.close()
            print(json.dumps(report, indent=2)); return

        # ---------- STEP 2 ----------
        t0 = time.perf_counter()
        s2 = {"name": "Bot card -> chat window"}
        try:
            url_before = page.url
            first_card = page.locator(CARD_SELECTOR).first
            first_card_text = first_card.inner_text()[:80].replace("\n", " ").strip()
            # Click & wait for either navigation OR modal/drawer
            try:
                with page.expect_navigation(wait_until="domcontentloaded", timeout=8_000):
                    first_card.click()
            except PWTimeout:
                pass
            # Up to 5s for chat UI to settle
            deadline = time.time() + 5
            chat_signals = {}
            while time.time() < deadline:
                try:
                    chat_signals = page.evaluate(r"""
                      () => ({
                        url: location.href,
                        textareas: document.querySelectorAll('textarea').length,
                        inputs_text: document.querySelectorAll('input[type=text], input[type=search]').length,
                        modals: document.querySelectorAll('[role=dialog], [class*="modal" i], [class*="drawer" i]').length,
                        welcome_present: /hi! i am|welcome|how can i help|i'm your assistant|i am your assistant/i.test(document.body.innerText || ''),
                        new_conv_btn: !!Array.from(document.querySelectorAll('button')).find(b => /new conversation/i.test(b.innerText || '')),
                      })
                    """)
                except Exception:
                    chat_signals = {}
                has_chat_ui = bool(
                    chat_signals.get("textareas", 0) > 0
                    or chat_signals.get("welcome_present")
                    or chat_signals.get("modals", 0) > 0
                    or chat_signals.get("new_conv_btn")
                )
                if has_chat_ui:
                    break
                time.sleep(0.5)

            ms = (time.perf_counter() - t0) * 1000
            url_after = chat_signals.get("url") or page.url
            url_changed = url_after != url_before
            chat_present = (
                chat_signals.get("textareas", 0) > 0
                or chat_signals.get("welcome_present")
                or chat_signals.get("new_conv_btn")
            )
            s2.update(duration_ms=round(ms,1),
                      url_before=url_before, url_after=url_after,
                      clicked_card_text=first_card_text,
                      chat_signals=chat_signals)
            if not url_changed and not chat_present:
                s2.update(verdict="DEGRADED",
                          detail="Click did not transition to chat workspace (no URL change, no chat UI)",
                          artifact=snap(page, "step2_no_chat"))
            elif chat_present:
                bits = []
                if chat_signals.get("textareas"): bits.append(f"{chat_signals['textareas']} <textarea>")
                if chat_signals.get("welcome_present"): bits.append("welcome message present")
                if chat_signals.get("new_conv_btn"): bits.append("'New Conversation' button")
                if chat_signals.get("modals"): bits.append(f"{chat_signals['modals']} modal/drawer")
                s2.update(verdict="UP", detail="; ".join(bits))
            else:
                s2.update(verdict="DEGRADED",
                          detail=f"URL changed to {url_after} but no chat input/welcome detected within 5s",
                          artifact=snap(page, "step2_url_no_ui"))
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            s2.update(verdict="DOWN", duration_ms=round(ms,1),
                      detail=f"{type(e).__name__}: {e}", artifact=snap(page, "step2_exc"))
        report["steps"].append(s2)

        report["total_duration_ms"] = round((time.perf_counter() - overall_t0)*1000, 1)
        verdicts = [s["verdict"] for s in report["steps"]]
        if all(v == "UP" for v in verdicts):
            report["overall"] = "HEALTHY"
        elif any(v == "DOWN" for v in verdicts):
            report["overall"] = "DOWN"
        else:
            report["overall"] = "DEGRADED (Chat Window Initialization Failure)"
        report["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
        ctx.close(); b.close()
        print(json.dumps(report, indent=2))

if __name__ == "__main__":
    run()
