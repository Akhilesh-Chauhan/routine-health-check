"""Open headed Chromium pointed at the UMANG persistent profile so the user can
complete MeriPehchaan OTP login through myauth.umangapp.in (the UMANG-specific
DigiLocker OAuth ingress).

UMANG mirror domains do NOT share the prod auth.myscheme.gov.in session — they
use their own session host (myauth.umangapp.in). One OTP login here establishes
the UMANG-side session cookies that downstream UMANG workspace checks rely on.

Auto-closes once myauth.umangapp.in is in the post-login state
("Welcome <name>!" / "Please choose a platform to continue").
"""
from health_check.paths import PROFILE_UMANG
from health_check.auth.heuristics import find_logged_in_page
import os, time
from playwright.sync_api import sync_playwright

PROFILE_DIR = str(PROFILE_UMANG)
ENTRY_URL   = "https://myauth.umangapp.in/"

MAX_WAIT_SECONDS = 600
POLL_INTERVAL    = 2
STABLE_SECONDS   = 6

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

            print(f"[login] Browser open at {page.url}", flush=True)
            print("[login] Complete the MeriPehchaan / DigiLocker OTP login flow on the UMANG auth ingress.", flush=True)
            deadline = time.time() + MAX_WAIT_SECONDS
            stable_since = None
            last_urls = ""
            while time.time() < deadline:
                # Watch every tab — the post-login can land in a new one while
                # the original tab stays parked on the sign-in/consent surface.
                try:
                    urls = " | ".join(pg.url for pg in ctx.pages)
                except Exception:
                    urls = ""
                if urls != last_urls:
                    print(f"[login] URL -> {urls}", flush=True)
                    last_urls = urls
                if find_logged_in_page(ctx, "umang") is not None:
                    if stable_since is None:
                        stable_since = time.time()
                        print(f"[login] UMANG post-login state detected; confirming for {STABLE_SECONDS}s...", flush=True)
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
        finally:
            try:
                ctx.close()
            except Exception:
                pass

if __name__ == "__main__":
    main()
