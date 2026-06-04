"""Part C: the control panel renders with the shared Luminous Glass assets,
a theme toggle, SVG nav icons, the unified classifier, and a cancel control."""
from __future__ import annotations

import re

import pytest

from health_check.web import app as web_app


@pytest.fixture()
def html():
    return web_app.create_app().test_client().get("/").get_data(as_text=True)


def test_panel_serves_ok(html):
    assert len(html) > 1000


def test_shared_design_system_injected(html):
    assert "--glass:" in html
    assert '[data-theme="dark"]' in html
    assert "toggleTheme()" in html
    assert "hc-theme" in html


def test_sprite_and_svg_nav_icons(html):
    assert 'id="i-activity"' in html and 'id="i-trash"' in html
    assert 'href="#i-layout-grid"' in html      # Dashboard nav icon
    # the old text glyphs must be gone from the nav/rail
    for glyph in ("◎", "▦", "⌛", "⌫"):
        assert glyph not in html, f"nav/rail still uses text glyph {glyph!r}"


def test_unified_classifier_present(html):
    assert "function classifyVerdict(" in html


def test_cancel_control_present(html):
    assert 'id="btn-cancel"' in html


def test_no_external_asset_requests(html):
    # Same-origin static (style.css / app.js via url_for) is fine; what must NOT
    # appear is a remote CSS/font/image fetch.
    assert not re.search(r'url\(\s*["\']?https?://', html)
    assert "@import" not in html
