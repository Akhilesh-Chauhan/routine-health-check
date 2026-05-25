"""Central path resolution for the health-check suite.

Every other module imports its filesystem locations from here. Moving the
project directory only requires the package to still be importable — no
script in this codebase carries a hardcoded absolute path. This fixes the
v1 footgun where moving the directory silently broke every authenticated
check by recreating empty profile dirs at the stale path.
"""
from __future__ import annotations

import os
from pathlib import Path

# src/health_check/paths.py  →  src/health_check  →  src  →  <project root>
ROOT: Path = Path(__file__).resolve().parents[2]

CONFIG_DIR: Path = ROOT / "config"
DOCS_DIR: Path = ROOT / "docs"
PROFILES_DIR: Path = ROOT / "profiles"
ARTIFACTS_DIR: Path = ROOT / "artifacts"

URL_REGISTRY: Path = CONFIG_DIR / "url_registry.json"
ALERT_CONFIG: Path = CONFIG_DIR / "alert_config.json"

# Persistent Chromium profile dirs — one per auth tenant. In v2 these are
# symlinks pointing at the v1 directory so the same login works in both.
PROFILE_PROD: Path = PROFILES_DIR / "_browser_profile"
PROFILE_DEV: Path = PROFILES_DIR / "_dev_browser_profile"
PROFILE_UMANG: Path = PROFILES_DIR / "_umang_browser_profile"

PROFILES = {
    "prod": PROFILE_PROD,
    "dev": PROFILE_DEV,
    "umang": PROFILE_UMANG,
}

# Output locations
MASTER_REPORT: Path = ARTIFACTS_DIR / "master_report.json"
DASHBOARD_HTML: Path = ROOT / "dashboard.html"
LIVENESS_STATE: Path = ARTIFACTS_DIR / "liveness_state.json"
SCHEDULED_STATE: Path = ARTIFACTS_DIR / "scheduled_state.json"


def ensure_runtime_dirs() -> None:
    """Create the writable runtime directories. Called at startup by the CLI
    and by any script invoked directly. Idempotent."""
    for d in (ARTIFACTS_DIR,):
        d.mkdir(parents=True, exist_ok=True)
    # Profile dirs are symlinks in v2 — don't recreate them. If the symlink
    # target is missing (e.g. v1 was deleted), fail loudly rather than silently
    # creating an empty profile that would bounce every authenticated check.
    for tenant, p in PROFILES.items():
        if not p.exists():
            raise FileNotFoundError(
                f"Profile dir for tenant '{tenant}' is missing or its symlink "
                f"target was removed: {p}. Re-create the profile or fix the "
                f"symlink before running authenticated checks."
            )


# Convenience strings — many Playwright APIs accept str, not Path.
def as_str(p: Path) -> str:
    return os.fspath(p)
