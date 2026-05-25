"""Open headed Chromium pointed at the persistent profile so the user can complete
MeriPehchaan OTP login manually. Closes cleanly once login is detected,
so cookies are flushed to the profile directory for later headless reuse.
"""
from health_check.paths import PROFILE_PROD
import os, time, sys
from playwright.sync_api import sync_playwright

PROFILE_DIR = str(PROFILE_PROD)
TARGET = "https://auth.myscheme.gov.in/"
MAX_WAIT_SECONDS = 600        # give user up to 10 min
POLL_INTERVAL = 2
STABLE_SECONDS = 6            # require login state to persist this long before closing

# Positive signals — auth.myscheme.gov.in is post-login when these appear
# ("Welcome <name>! / Please choose a platform to continue / Sign Out").
POST_LOGIN_HINTS = [
    "please choose a platform to continue",
    "sign out",
]
# Negative signals — still on a sign-in surface.
SIGNIN_BODY_HINTS = [
    "sign in to your account", "enter mobile", "send otp", "enter otp",
    "security pin", "already a user?", "new user? sign up",
]
SIGNIN_URL_HINTS = [
    "digilocker.meripehchaan.gov.in", "consent.digilocker.gov.in",
    "eparichay", "/oidc/v1/auth", "/signinv2",
]

def looks_logged_in(page):
    """True only when the page has settled on the post-login auth dashboard.

    The post-login dashboard lives at exactly https://auth.myscheme.gov.in/ —
    the SAME URL as the pre-login sign-in selector — so the two must be told
    apart by body content, not URL. (The old heuristic listed the auth host
    itself as a sign-in hint, so it never detected login and hung forever.)
    """
    try:
        body = page.evaluate("() => (document.body && document.body.innerText) || ''")[:4000].lower()
    except Exception:
        body = ""
    url = (page.url or "").lower()
    # Must be back on the auth host (not mid-OAuth on DigiLocker / MeriPehchaan).
    if "auth.myscheme.gov.in" not in url:
        return False
    if any(h in url for h in SIGNIN_URL_HINTS):
        return False
    if any(s in body for s in SIGNIN_BODY_HINTS):
        return False
    return any(s in body for s in POST_LOGIN_HINTS)

def main():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            viewport={"width": 1366, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(TARGET, wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            print(f"[note] initial navigation issue: {e}", flush=True)

        print(f"[login] Browser open. Complete OTP login. URL now: {page.url}", flush=True)
        deadline = time.time() + MAX_WAIT_SECONDS
        stable_since = None
        last_url = ""
        while time.time() < deadline:
            try:
                cur_url = page.url
            except Exception:
                cur_url = ""
            if cur_url != last_url:
                print(f"[login] URL -> {cur_url}", flush=True)
                last_url = cur_url
            if looks_logged_in(page):
                if stable_since is None:
                    stable_since = time.time()
                    print(f"[login] Detected logged-in state at {cur_url}; confirming stability for {STABLE_SECONDS}s...", flush=True)
                elif time.time() - stable_since >= STABLE_SECONDS:
                    print(f"[login] Confirmed. Closing browser cleanly to flush cookies.", flush=True)
                    break
            else:
                if stable_since is not None:
                    print("[login] State reverted to sign-in surface; resetting stability timer.", flush=True)
                stable_since = None
            time.sleep(POLL_INTERVAL)
        else:
            print("[login] Timed out waiting for login. Closing browser anyway — cookies may still be saved if you got partway.", flush=True)

        try:
            ctx.close()
        except Exception as e:
            print(f"[login] close warning: {e}", flush=True)
        print("[login] Done. Run auth_precheck.py to verify session is active.", flush=True)

if __name__ == "__main__":
    main()
