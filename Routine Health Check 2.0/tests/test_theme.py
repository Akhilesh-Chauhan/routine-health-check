"""Guards for the shared Luminous Glass design-system module (spec Part A).

Pins the contract both front-ends rely on: every named icon exists, both
theme variants are defined, the toggle is wired, and — per the hard
"offline-safe" constraint — the assets make zero external requests.
"""
from __future__ import annotations

import re

from health_check.reporting import theme

# The icon set the spec enumerates, plus the sun/moon used by the toggle.
REQUIRED_ICONS = [
    "activity", "layout-grid", "braces", "history", "refresh-cw", "play",
    "log-in", "trash", "chevron", "check-circle", "alert-triangle",
    "x-circle", "shield-x", "sun", "moon",
]


def test_all_required_icons_present():
    for name in REQUIRED_ICONS:
        assert f'id="i-{name}"' in theme.SVG_SPRITE, f"missing icon i-{name}"


def test_both_theme_variants_defined():
    assert ":root" in theme.DESIGN_TOKENS_CSS
    assert '[data-theme="dark"]' in theme.DESIGN_TOKENS_CSS
    # A token that must exist in both so component CSS never resolves to nothing.
    assert theme.DESIGN_TOKENS_CSS.count("--glass:") >= 2


def test_theme_toggle_is_wired():
    assert "toggleTheme" in theme.THEME_BOOT_JS
    assert "toggleTheme()" in theme.THEME_TOGGLE_BUTTON
    assert "localStorage" in theme.THEME_BOOT_JS
    assert "prefers-color-scheme" in theme.THEME_BOOT_JS


def test_motion_is_gated_behind_reduced_motion():
    assert "prefers-reduced-motion: reduce" in theme.DESIGN_TOKENS_CSS


def test_no_external_requests_in_assets():
    """Offline-safe hard constraint: no http(s):// or url() fetches, no CDN."""
    blob = theme.DESIGN_TOKENS_CSS + theme.SVG_SPRITE + theme.THEME_BOOT_JS
    assert "http://" not in blob and "https://" not in blob
    assert "@import" not in blob
    # url(...) is how a CSS file would pull a remote font/image.
    assert not re.search(r"url\(\s*['\"]?https?:", blob)
