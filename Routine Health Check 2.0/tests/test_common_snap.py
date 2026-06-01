"""D12: the shared snap() helper preserves each module's exact artifact naming."""
from __future__ import annotations

import importlib

import pytest

from health_check.checks import _common


class _FakePage:
    """Records screenshot(path=, full_page=) calls."""
    def __init__(self, boom=False):
        self.calls = []
        self.boom = boom

    def screenshot(self, path=None, full_page=None):
        self.calls.append((path, full_page))
        if self.boom:
            raise RuntimeError("screenshot failed")


def test_make_snap_path_and_flag():
    page = _FakePage()
    snap = _common.make_snap("/tmp/art", "cms_", full_page=True)
    assert snap(page, "step1") == "/tmp/art/cms_step1.png"
    assert page.calls == [("/tmp/art/cms_step1.png", True)]


def test_make_snap_swallows_errors_and_still_returns_path():
    page = _FakePage(boom=True)
    snap = _common.make_snap("/tmp/art", "")
    # screenshot raises internally, but snap must not propagate and still
    # returns the intended path (matches the prior best-effort helpers).
    assert snap(page, "x") == "/tmp/art/x.png"


# (module, expected prefix, expected full_page) — the EXACT prior per-module
# behaviour the extraction must preserve (artifact filenames feed the dashboard).
SNAP_MATRIX = [
    ("health_check.checks.prod.forms",         "forms_",   False),
    ("health_check.checks.prod.cms",           "cms_",     False),
    ("health_check.checks.prod.govai",         "govai_",   False),
    ("health_check.checks.public.aistore",     "aistore_", False),
    ("health_check.checks.public.myscheme",    "",         True),
    ("health_check.checks.public.docs_portal", "docs_",    False),
    ("health_check.checks.public.chatbots",    "chatbot_", False),
    ("health_check.checks.umang.integration",  "umang_",   False),
    ("health_check.checks.public.rules_engine", "rules_",  True),
    ("health_check.checks.dev.environment",    "dev_",     False),
]


@pytest.mark.parametrize("modpath,prefix,full_page", SNAP_MATRIX)
def test_module_snap_matches_prior_behaviour(modpath, prefix, full_page):
    mod = importlib.import_module(modpath)
    page = _FakePage()
    out = mod.snap(page, "TAG")
    assert out == f"{mod.ART_DIR}/{prefix}TAG.png", f"{modpath} artifact filename changed"
    assert page.calls[-1][1] is full_page, f"{modpath} full_page flag changed"
