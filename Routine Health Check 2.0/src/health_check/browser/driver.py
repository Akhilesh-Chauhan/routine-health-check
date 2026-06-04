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
    def screenshot(self, path: str, full_page: bool = False) -> str: ...


@runtime_checkable
class BrowserDriver(Protocol):
    def open(self, tenant: str, headless: bool = True) -> PageHandle: ...
    def close(self) -> None: ...
