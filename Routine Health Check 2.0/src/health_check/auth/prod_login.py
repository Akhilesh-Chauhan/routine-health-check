"""Open headed Chromium pointed at the persistent profile so the user can complete
MeriPehchaan OTP login manually. Closes cleanly once login is detected,
so cookies are flushed to the profile directory for later headless reuse.
"""
from health_check.paths import PROFILE_PROD, ARTIFACTS_DIR
from health_check.auth.heuristics import find_logged_in_page, record_login_diagnostic
import os, time, sys
from playwright.sync_api import sync_playwright

PROFILE_DIR = str(PROFILE_PROD)
TARGET = "https://auth.myscheme.gov.in/"
MAX_WAIT_SECONDS = 600        # give user up to 10 min
POLL_INTERVAL = 2
STABLE_SECONDS = 6            # require login state to persist this long before closing


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
                page.goto(TARGET, wait_until="domcontentloaded", timeout=30_000)
            except Exception as e:
                print(f"[note] initial navigation issue: {e}", flush=True)

            print(f"[login] Browser open. Complete OTP login. URL now: {page.url}", flush=True)
            deadline = time.time() + MAX_WAIT_SECONDS
            stable_since = None
            last_urls = ""
            while time.time() < deadline:
                # The post-login state often lands in a NEW tab while the
                # original tab stays on the sign-in/consent surface, so watch
                # every open page — not just the one we opened.
                try:
                    urls = " | ".join(p.url for p in ctx.pages)
                except Exception:
                    urls = ""
                if urls != last_urls:
                    print(f"[login] URL -> {urls}", flush=True)
                    last_urls = urls
                    record_login_diagnostic(str(ARTIFACTS_DIR), "prod", ctx,
                                            note="url changed (not yet confirmed)")
                hit = find_logged_in_page(ctx, "prod")
                if hit is not None:
                    if stable_since is None:
                        stable_since = time.time()
                        print(f"[login] Detected logged-in state; confirming stability for {STABLE_SECONDS}s...", flush=True)
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
                record_login_diagnostic(str(ARTIFACTS_DIR), "prod", ctx,
                                        note="TIMED OUT — never auto-closed")

            try:
                ctx.close()
            except Exception as e:
                print(f"[login] close warning: {e}", flush=True)
            print("[login] Done. Run auth_precheck.py to verify session is active.", flush=True)
        finally:
            try:
                ctx.close()
            except Exception:
                pass

if __name__ == "__main__":
    main()
