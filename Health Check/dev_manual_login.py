"""Open headed Chromium pointed at the dev persistent profile so the user can
complete MeriPehchaan OTP login through devauth.myscheme.gov.in.

Cognito perimeter cookies are reused from a prior run; if Cognito re-prompts
(session expired), it auto-fills devadmin / Myscheme@3211 before handing off
to the user for OTP.

Auto-closes once devauth.myscheme.gov.in is in the post-login state
("Welcome <name>!" / "Please choose a platform to continue").
"""
import os, time
from playwright.sync_api import sync_playwright

PROFILE_DIR = "/home/user/NeGD/Claude Code/Health Check/_dev_browser_profile"
ENTRY_URL = "https://devauth.myscheme.gov.in/"
COGNITO_HOST = "myscheme.auth.ap-south-1.amazoncognito.com"
COGNITO_USER = os.environ.get("DEV_COGNITO_USER", "devadmin")
COGNITO_PASS = os.environ.get("DEV_COGNITO_PASS", "Myscheme@3211")

MAX_WAIT_SECONDS = 600
POLL_INTERVAL   = 2
STABLE_SECONDS  = 6

# Positive signals — devauth is post-login when these appear
POST_LOGIN_HINTS = [
    "welcome ",                          # "Welcome <name>!"
    "please choose a platform to continue",
]
# Negative signals — still on a sign-in surface
SIGNIN_HINTS = [
    "sign in to your account",
    "enter mobile",
    "send otp",
    "security pin",
    "already a user?",
    "choose a platform to sign in",      # pre-login text on devauth landing
    "new to myscheme?",
]
SIGNIN_URL_HINTS = [
    "digilocker.meripehchaan.gov.in",
    "/oidc/v1/auth",
    "eparichay/signin",
]

def looks_logged_in(page):
    try:
        body = page.evaluate("() => (document.body && document.body.innerText) || ''")[:4000].lower()
    except Exception:
        body = ""
    url = (page.url or "").lower()
    # Must specifically be on devauth host (the post-login Welcome page)
    if "devauth.myscheme.gov.in" not in url:
        return False
    if any(h in url for h in SIGNIN_URL_HINTS):
        return False
    if any(h in body for h in SIGNIN_HINTS):
        return False
    if any(h in body for h in POST_LOGIN_HINTS):
        return True
    return False

def handle_cognito_if_present(page):
    if COGNITO_HOST not in (page.url or ""):
        return False
    print(f"[login] Cognito gate detected -> auto-filling {COGNITO_USER}", flush=True)
    try:
        u = page.locator("input#signInFormUsername:visible").first
        p = page.locator("input#signInFormPassword:visible").first
        s = page.locator("button[name='signInSubmitButton']:visible, input[type=submit][name='signInSubmitButton']:visible").first
        u.wait_for(state="visible", timeout=15_000)
        u.fill(COGNITO_USER); p.fill(COGNITO_PASS)
        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=20_000):
                s.click()
        except Exception:
            pass
        time.sleep(2)
        return True
    except Exception as e:
        print(f"[login] Cognito auto-fill error: {e}", flush=True)
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

        # Cognito gate (if cookies expired)
        if COGNITO_HOST in (page.url or ""):
            handle_cognito_if_present(page)

        print(f"[login] Browser open at {page.url}", flush=True)
        print("[login] Complete the MeriPehchaan / DigiLocker OTP login flow now.", flush=True)
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
            if COGNITO_HOST in (cur or ""):
                handle_cognito_if_present(page)
                stable_since = None
                time.sleep(POLL_INTERVAL); continue
            if looks_logged_in(page):
                if stable_since is None:
                    stable_since = time.time()
                    print(f"[login] devauth post-login state detected; confirming for {STABLE_SECONDS}s...", flush=True)
                elif time.time() - stable_since >= STABLE_SECONDS:
                    print("[login] Confirmed. Closing browser cleanly.", flush=True)
                    break
            else:
                if stable_since is not None:
                    print("[login] State reverted; resetting stability timer.", flush=True)
                stable_since = None
            time.sleep(POLL_INTERVAL)
        else:
            print("[login] Timed out waiting for devauth login. Cookies set so far will be flushed on close.", flush=True)

        try:
            ctx.close()
        except Exception as e:
            print(f"[login] close warning: {e}", flush=True)
        print("[login] Done. Now run: python3 dev_environment_check.py", flush=True)

if __name__ == "__main__":
    main()
