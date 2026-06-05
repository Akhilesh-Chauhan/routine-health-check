"""Session/auth pre-check against https://auth.myscheme.gov.in/"""
from health_check.paths import ARTIFACTS_DIR
from health_check.reporting.status import Verdict
from health_check.browser.playwright_driver import PlaywrightDriver
import time, json

TARGET = "https://auth.myscheme.gov.in/"
ART = str(ARTIFACTS_DIR / "auth_precheck.png")


def main():
    driver = PlaywrightDriver()
    page = driver.open("prod")
    try:
        final_url = ""
        body_text = ""
        try:
            page.goto(TARGET, timeout_ms=20_000)
            time.sleep(2)
            final_url = page.url
            try:
                body_text = (page.text() or "")[:2000]
            except Exception:
                body_text = ""
            page.screenshot(ART)
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

        logged_out = redirected_to_digilocker or has_signin_signal
        print(json.dumps({
            "target": TARGET,
            "verdict": Verdict.AUTH_EXPIRED if logged_out else Verdict.UP,
            "final_url": final_url,
            "detail": ("Sign-in surface (Scenario B) — prod OTP re-login needed"
                       if logged_out else "Active session (Scenario A)"),
        }))
    finally:
        driver.close()


if __name__ == "__main__":
    main()
