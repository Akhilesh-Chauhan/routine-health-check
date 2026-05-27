"""Project → CLI check mapping for the web control panel.

`url_registry.json` is organised by project (11 today). The `hc check`
CLI is organised by individual functional check (11 today). The mapping
is not 1:1 — e.g. "myScheme Portal" covers four CLI checks
(myscheme/rules/docs/devenv), the five chatbot projects all collapse to
the single `chatbots` check, and "GovAI" needs both the prod check and
the dev environment sweep.

This module owns that mapping. Keep it deliberate and discoverable so
the UI's project tiles do exactly what the operator expects.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable

from health_check import paths


# Functional check name (from cli.py CHECKS) per project.
# A project can map to >1 check, and multiple projects can share a check
# (the 5 chatbots all share `chatbots`).
PROJECT_CHECKS: dict[str, list[str]] = {
    "myScheme Portal":      ["myscheme", "rules", "docs"],
    "GovAI":                ["govai"],
    "AI Store":             ["aistore"],
    "CMS":                  ["cms"],
    "GovForms":             ["forms"],
    "DoE Chatbot":          ["chatbots"],
    "PSQ Chatbot":          ["chatbots"],
    "Sandarbh Chatbot":     ["chatbots"],
    "NMC Chatbot":          ["chatbots"],
    "TATHYA (PIB) Chatbot": ["chatbots"],
    "UMANG Mirror":         ["umang"],
}

# Env-level check rollups for the top-bar buttons.
ENV_CHECKS: dict[str, list[str]] = {
    "Public":      ["myscheme", "aistore", "rules", "docs", "chatbots"],
    "Production":  ["auth", "govai", "cms", "forms"],
    "Development": ["devenv"],
    "UMANG":       ["umang"],
}


@dataclass(frozen=True)
class Project:
    name: str
    spoc_name: str
    spoc_email: str
    urls: list[dict]                 # raw entries from url_registry
    check_names: list[str]           # CLI checks this project triggers


def load_projects() -> list[Project]:
    """Read url_registry.json + attach the check mapping for each project."""
    data = json.loads(paths.URL_REGISTRY.read_text())
    out: list[Project] = []
    for p in data["projects"]:
        out.append(Project(
            name=p["name"],
            spoc_name=p.get("spoc", {}).get("name", ""),
            spoc_email=p.get("spoc", {}).get("email", ""),
            urls=list(p.get("urls", [])),
            check_names=list(PROJECT_CHECKS.get(p["name"], [])),
        ))
    return out


def project_url_subset(project_name: str) -> list[dict]:
    """Just the URLs belonging to one project — for project-scoped liveness."""
    for p in load_projects():
        if p.name == project_name:
            return p.urls
    return []


def env_checks(env: str) -> list[str]:
    """Top-bar env button → ordered list of CLI checks to run."""
    return list(ENV_CHECKS.get(env, []))


def all_check_names() -> Iterable[str]:
    """All 11 CLI check names — for the per-check button grid."""
    return [
        "myscheme", "aistore", "rules", "docs", "chatbots",
        "auth", "govai", "cms", "forms",
        "devenv", "umang",
    ]


# Per-check buttons grouped for scannability in the UI.
# Mirrors how the orchestrator runs them: public surface first, then prod
# workspaces (gated on prod auth), then dev, then UMANG.
CHECK_GROUPS: list[tuple[str, list[str]]] = [
    ("Public",      ["myscheme", "aistore", "rules", "docs", "chatbots"]),
    ("Production",  ["auth", "govai", "cms", "forms"]),
    ("Development", ["devenv"]),
    ("UMANG",       ["umang"]),
]
