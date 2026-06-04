"""Shared helpers for the functional check modules (spec D12).

The 10 check modules each carried a byte-identical `snap(page, tag)` screenshot
helper that differed only in its filename prefix and the `full_page` flag. This
consolidates that one helper; the per-check artifact filenames (which the
dashboard references) and the full_page flag are preserved exactly via the
factory's parameters.

Deliberately NOT consolidated here: the route-check / cognito-goto / login-bounce
helpers. Those differ in non-trivial ways per surface and unifying them safely
needs the full-sweep verdict-parity check the spec gates D12 on — out of scope
for an offline change.
"""
from __future__ import annotations


def make_snap(art_dir, prefix: str = "", full_page: bool = False):
    """Build a `snap(page, tag)` screenshot helper.

    Saves `{art_dir}/{prefix}{tag}.png` (best-effort — never raises) and returns
    the path, matching the prior per-module helpers exactly.
    """
    def snap(page, tag):
        path = f"{art_dir}/{prefix}{tag}.png"
        try:
            page.screenshot(path=path, full_page=full_page)
        except Exception:
            pass
        return path
    return snap
