"""Session/auth pre-check against https://auth.myscheme.gov.in/"""
from playwright.sync_api import sync_playwright
import os, time, json

PROFILE_DIR = "/home/user/NeGD/Claude Code/Health Check/_browser_profile"
TARGET = "https://auth.myscheme.gov.in/"
ART = "/home/user/NeGD/Claude Code/Health Check/_hc_artifacts/auth_precheck.png"
os.makedirs(PROFILE_DIR, exist_ok=True)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        viewport={"width": 1366, "height": 900},
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    final_url = ""
    body_text = ""
    try:
        page.goto(TARGET, wait_until="domcontentloaded", timeout=20_000)
        try:
            page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass
        time.sleep(2)
        final_url = page.url
        try:
            body_text = page.evaluate("() => document.body ? document.body.innerText : ''")[:2000]
        except Exception:
            body_text = ""
        try:
            page.screenshot(path=ART, full_page=False)
        except Exception:
            pass
    except Exception as e:
        final_url = f"ERROR: {type(e).__name__}: {e}"

    print("FINAL_URL:", final_url)
    print("---BODY (first 2000)---")
    print(body_text)
    # Check signals for SCENARIO B
    lower_url = final_url.lower()
    lower_body = body_text.lower()
    redirected_to_digilocker = "digilocker.meripehchaan.gov.in" in lower_url
    has_signin_signal = any(s in lower_body for s in ["sign in", "enter mobile", "enter your mobile", "user id", "otp", "send otp"])
    print("---SIGNALS---")
    print("redirected_to_digilocker:", redirected_to_digilocker)
    print("signin/otp signals in body:", has_signin_signal)
    ctx.close()

    logged_out = redirected_to_digilocker or has_signin_signal
    print(json.dumps({
        "target": TARGET,
        "verdict": "AUTH_EXPIRED" if logged_out else "UP",
        "final_url": final_url,
        "detail": ("Sign-in surface (Scenario B) — prod OTP re-login needed"
                   if logged_out else "Active session (Scenario A)"),
    }))
