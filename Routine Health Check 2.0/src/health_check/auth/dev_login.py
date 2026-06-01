"""Open headed Chromium pointed at the dev persistent profile so the user can
complete MeriPehchaan OTP login through devauth.myscheme.gov.in.

Cognito perimeter cookies are reused from a prior run; if Cognito re-prompts
(session expired), it auto-fills the configured Cognito credentials (from
HC_DEV_COGNITO_USER / HC_DEV_COGNITO_PASS or config/secrets.env) before handing
off to the user for OTP.

Auto-closes once devauth.myscheme.gov.in is in the post-login state
("Welcome <name>!" / "Please choose a platform to continue").
"""
from health_check.paths import PROFILE_DEV
from health_check.secrets import cognito_credentials
from health_check.auth.heuristics import looks_logged_in
import os, time
from playwright.sync_api import sync_playwright

PROFILE_DIR = str(PROFILE_DEV)
ENTRY_URL = "https://devauth.myscheme.gov.in/"
COGNITO_HOST = "myscheme.auth.ap-south-1.amazoncognito.com"
COGNITO_USER, COGNITO_PASS = cognito_credentials()

MAX_WAIT_SECONDS = 600
POLL_INTERVAL   = 2
STABLE_SECONDS  = 6


def handle_cognito_if_present(page):
    if COGNITO_HOST not in (page.url or ""):
        return False
    if not COGNITO_PASS:
        print("[login] Cognito gate detected but no password configured — set "
              "HC_DEV_COGNITO_PASS or add it to config/secrets.env.", flush=True)
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
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            viewport={"width": 1366, "height": 900},
        )
        try:
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
                if looks_logged_in(page, "dev"):
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
        finally:
            try:
                ctx.close()
            except Exception:
                pass

if __name__ == "__main__":
    main()
