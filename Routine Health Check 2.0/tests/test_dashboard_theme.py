"""Part B: the dashboard renders with the Luminous Glass system, a theme
toggle, the unified classifier, SVG icons (no emoji glyphs), and stays
offline-safe / self-contained."""
from __future__ import annotations

import json
import re

from health_check.orchestration import dashboard


def _render(tmp_path):
    rep = tmp_path / "master_report.json"
    out = tmp_path / "dashboard.html"
    rep.write_text(json.dumps({
        "started_ist": "2026-06-01T10:00:00+05:30",
        "ended_ist": "2026-06-01T10:08:00+05:30",
        "total_duration_s": 480.0,
        "auth_preflight": {"prod": "AUTHED"},
        "liveness": {"results": [
            {"label": "home", "url": "https://www.myscheme.gov.in/", "project": "myScheme",
             "environment": "production", "status": "UP", "http": 200, "ms": 120.0, "err": None},
        ], "counts": {"UP": 1, "SLOW": 0, "DOWN": 0}},
        "scripts": [
            {"label": "myscheme E2E", "filename": "health_check.checks.public.myscheme",
             "duration_s": 40.0, "verdict": "HEALTHY",
             "payload": {"steps": [{"name": "Home", "verdict": "UP", "duration_ms": 120}]}},
        ],
    }))
    dashboard.main(["--report", str(rep), "--out", str(out)])
    return out.read_text()


def test_no_leftover_placeholders(tmp_path):
    html = _render(tmp_path)
    for ph in ("__DESIGN_TOKENS__", "__SVG_SPRITE__", "__THEME_TOGGLE__",
               "__THEME_BOOT_JS__", "__JS_CLASSIFIER__", "__DATA_PLACEHOLDER__"):
        assert ph not in html, f"unfilled template placeholder: {ph}"


def test_design_system_and_theme_present(tmp_path):
    html = _render(tmp_path)
    assert "--glass:" in html                       # tokens inlined
    assert '[data-theme="dark"]' in html            # dark variant
    assert "toggleTheme()" in html                  # toggle wired
    assert "hc-theme" in html                       # persisted preference
    assert 'id="i-activity"' in html and 'id="i-chevron"' in html  # sprite


def test_uses_unified_classifier(tmp_path):
    html = _render(tmp_path)
    assert "function classifyVerdict(" in html


def test_no_emoji_glyphs(tmp_path):
    html = _render(tmp_path)
    for glyph in ("▸", "▣", "❝", "◆", "◉", "📷"):
        assert glyph not in html, f"emoji/text glyph {glyph!r} not replaced by an SVG icon"


def test_offline_safe(tmp_path):
    html = _render(tmp_path)
    # No CSS/font/image asset fetched from a remote origin, no CSS @import.
    assert not re.search(r'url\(\s*["\']?https?://', html)
    assert "@import" not in html
    assert "cdn" not in html.lower()
