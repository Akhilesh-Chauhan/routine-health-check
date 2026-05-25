"""Single helper for launching Chromium against a tenant's persistent profile.

Consolidates the otherwise-duplicated `p.chromium.launch_persistent_context(...)`
block that appears in the orchestrator's `probe_auth`, the three manual-login
scripts, and every workspace check. Only the manual-login scripts and the
orchestrator are migrated to this helper — individual check scripts keep their
own inline launch code so per-script behaviour is not accidentally changed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from health_check import paths

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Playwright


def launch_persistent_context(
    p: "Playwright",
    tenant: str,
    headless: bool = True,
) -> "BrowserContext":
    """Open Chromium against the persistent profile for `tenant`.

    `tenant` is one of "prod" / "dev" / "umang"; the profile path comes from
    `paths.PROFILES[tenant]`. Arguments mirror v1 exactly: --no-sandbox,
    --disable-dev-shm-usage, 1366x900 viewport.
    """
    profile = paths.require_profile(tenant)
    return p.chromium.launch_persistent_context(
        str(profile),
        headless=headless,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        viewport={"width": 1366, "height": 900},
    )
