"""Click 'Meri Pehchaan' under 'Already a user?' on auth.myscheme.gov.in and report destination."""
from playwright.sync_api import sync_playwright
import os, time

PROFILE_DIR = "/home/user/NeGD/Claude Code/Health Check/_browser_profile"
TARGET = "https://auth.myscheme.gov.in/"
ART = "/home/user/NeGD/Claude Code/Health Check/_hc_artifacts/after_meripehchaan_click.png"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        viewport={"width": 1366, "height": 900},
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(TARGET, wait_until="networkidle", timeout=20_000)
    time.sleep(1)

    # The "Already a user?" Meri Pehchaan link is the one with class containing
    # 'indexButtons' AND href starting with '/oidc/v1/auth'
    sel = "a.indexButtons[href^='/oidc/v1/auth']"
    link = page.locator(sel).first
    print(f"target link count={page.locator(sel).count()} visible={link.is_visible()}")

    url_before = page.url
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=25_000):
            link.click()
    except Exception as e:
        print(f"nav-wait note: {e}")

    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass
    time.sleep(2)

    print(f"URL before: {url_before}")
    print(f"URL after : {page.url}")

    try:
        page.screenshot(path=ART, full_page=True)
        print(f"screenshot: {ART}")
    except Exception as e:
        print(f"screenshot err: {e}")

    body = page.evaluate("() => document.body ? document.body.innerText : ''")[:1500]
    print("---BODY (first 1500)---")
    print(body)
    ctx.close()
