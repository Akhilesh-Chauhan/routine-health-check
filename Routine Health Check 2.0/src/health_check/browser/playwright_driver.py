"""Playwright implementation of the BrowserDriver port."""
from __future__ import annotations

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from health_check.browser import context as ctx


class PlaywrightPage:
    def __init__(self, page):
        self._p = page

    def goto(self, url, timeout_ms=30000):
        r = self._p.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            self._p.wait_for_load_state("networkidle", timeout=15_000)
        except PWTimeout:
            pass
        return r.status if r is not None else None

    @property
    def url(self):
        return self._p.url

    def text(self):
        return self._p.evaluate("() => (document.body && document.body.innerText) || ''")

    def count(self, selector):
        return self._p.locator(selector).count()

    def screenshot(self, path, full_page=False):
        try:
            self._p.screenshot(path=path, full_page=full_page)
        except Exception:
            pass
        return path


class PlaywrightDriver:
    def __init__(self):
        self._pw = None
        self._browser = None
        self._ctx = None

    def open(self, tenant, headless=True):
        self._pw = sync_playwright().start()
        if tenant == "public":
            # Clean, non-persistent context: public checks must not carry an SSO
            # session. Mirrors the inline `chromium.launch() + new_context()` the
            # public check modules used before migrating to the port.
            self._browser = self._pw.chromium.launch(
                headless=headless, args=["--no-sandbox", "--disable-dev-shm-usage"])
            self._ctx = self._browser.new_context(viewport={"width": 1366, "height": 900})
            page = self._ctx.new_page()
        else:
            self._ctx = ctx.launch_persistent_context(self._pw, tenant, headless=headless)
            page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return PlaywrightPage(page)

    def close(self):
        try:
            if self._ctx:
                self._ctx.close()
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()
