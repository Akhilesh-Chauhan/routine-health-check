"""The browser port the checks depend on, instead of Playwright directly.

A check receives a `PageHandle`; it never imports playwright. Today's adapter
wraps Playwright (`browser/playwright_driver.py`); a Selenium (or other) adapter
can be added later by implementing this same Protocol without touching a check.

The Protocol is intentionally minimal — it currently covers what the migrated
checks need (navigate + read url/text + screenshot). It is expected to GROW
(form fill, frame access, JS eval, click/wait) as more checks migrate; add
methods here and to every adapter together.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PageHandle(Protocol):
    def goto(self, url: str, timeout_ms: int = 30000) -> int | None:
        """Navigate, wait for the page to settle, return the HTTP status (or None)."""
        ...
    @property
    def url(self) -> str: ...
    def text(self) -> str:
        """document.body.innerText of the current page (empty string if none)."""
        ...
    def count(self, selector: str) -> int:
        """Number of elements currently matching `selector` (0 if none)."""
        ...
    def is_visible(self, selector: str) -> bool:
        """True if the first element matching `selector` exists and is visible."""
        ...
    def click_nav(self, selector: str, timeout_ms: int = 25000) -> None:
        """Click the first element matching `selector` and await the resulting
        navigation. A click that does not navigate (timeout) is swallowed, matching
        the `with expect_navigation(): loc.click()` idiom the checks used."""
        ...
    def wait_idle(self, timeout_ms: int = 15000) -> None:
        """Best-effort wait for the network to go idle (never raises)."""
        ...
    def screenshot(self, path: str, full_page: bool = False) -> str:
        """Save a screenshot to `path`, returning it (best-effort, never raises).

        The `(path, full_page)` signature is the port contract: it is called by
        the shared `checks._common.make_snap` helper as
        `page.screenshot(path=..., full_page=...)`. Those keywords also match
        Playwright's keyword-only `Page.screenshot`, which is why make_snap works
        on both an un-migrated raw Playwright page and a migrated PageHandle.
        Any future adapter MUST keep accepting these keyword args.
        """
        ...


@runtime_checkable
class BrowserDriver(Protocol):
    def open(self, tenant: str, headless: bool = True) -> PageHandle:
        """Open a page for `tenant`.

        `tenant` is one of "prod" / "dev" / "umang" for a persistent profile
        (authenticated session), or "public" for a clean throwaway context with
        no profile — used by the public checks that must NOT carry an SSO session.
        """
        ...
    def close(self) -> None: ...
