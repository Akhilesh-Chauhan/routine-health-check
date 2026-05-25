"""Open headed Chromium pointed at the UMANG persistent profile so the user can
complete MeriPehchaan OTP login through myauth.umangapp.in (the UMANG-specific
DigiLocker OAuth ingress).

UMANG mirror domains do NOT share the prod auth.myscheme.gov.in session — they
use their own session host (myauth.umangapp.in). One OTP login here establishes
the UMANG-side session cookies that downstream UMANG workspace checks rely on.

Auto-closes once myauth.umangapp.in is in the post-login state
("Welcome <name>!" / "Please choose a platform to continue").
"""
import os, time
from playwright.sync_api import sync_playwright

PROFILE_DIR = "/home/user/NeGD/Claude Code/Health Check/_umang_browser_profile"
ENTRY_URL   = "https://myauth.umangapp.in/"

MAX_WAIT_SECONDS = 600
POLL_INTERVAL    = 2
STABLE_SECONDS   = 6

POST_LOGIN_HINTS = [
    "welcome ",                          # "Welcome <name>!"
    "please choose a platform to continue",
]
SIGNIN_HINTS = [
    "sign in to your account",
    "enter mobile",
    "send otp",
    "security pin",
    "already a user?",
    "choose a platform to sign in",
    "new to myscheme?",
]
SIGNIN_URL_HINTS = [
    "digilocker.meripehchaan.gov.in",
    "/oidc/v1/auth",
    "eparichay/signin",
]

def looks_logged_in(page):
    url = (page.url or "").lower()
    if "myauth.umangapp.in" not in url:
        return False
    if any(h in url for h in SIGNIN_URL_HINTS):
        return False
    try:
        body = page.evaluate("() => (document.body && document.body.innerText) || ''")[:4000].lower()
    except Exception:
        body = ""
    if any(h in body for h in SIGNIN_HINTS):
        return False
    if any(h in body for h in POST_LOGIN_HINTS):
        return True
    return False

def main():
    os.makedirs(PROFILE_DIR, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            viewport={"width": 1366, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(ENTRY_URL, wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            print(f"[login] initial nav issue: {e}", flush=True)

        print(f"[login] Browser open at {page.url}", flush=True)
        print("[login] Complete the MeriPehchaan / DigiLocker OTP login flow on the UMANG auth ingress.", flush=True)
        deadline = time.time() + MAX_WAIT_SECONDS
        stable_since = None
        last_url = ""
        while time.time() < deadline:
            try:
                cur = page.url
            except Exception:
                cur = ""
            if cur != last_url:
                print(f"[login] URL -> {cur}", flush=True)
                last_url = cur
            if looks_logged_in(page):
                if stable_since is None:
                    stable_since = time.time()
                    print(f"[login] myauth.umangapp.in post-login state detected; confirming for {STABLE_SECONDS}s...", flush=True)
                elif time.time() - stable_since >= STABLE_SECONDS:
                    print("[login] Confirmed. Closing browser cleanly.", flush=True)
                    break
            else:
                if stable_since is not None:
                    print("[login] State reverted; resetting stability timer.", flush=True)
                stable_since = None
            time.sleep(POLL_INTERVAL)
        else:
            print("[login] Timed out waiting for UMANG login. Cookies set so far will be flushed on close.", flush=True)

        try:
            ctx.close()
        except Exception as e:
            print(f"[login] close warning: {e}", flush=True)
        print("[login] Done. Now run: python3 umang_integration_check.py", flush=True)

if __name__ == "__main__":
    main()
