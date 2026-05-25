"""Dataclasses for the consolidated master report.

Field names and the resulting `dataclasses.asdict()` JSON shape match v1's
`master_health_check.py` byte-for-byte so the existing dashboard generator
keeps reading without changes. Per-check `payload` stays as an untyped dict
because the 11 check scripts produce varying internal shapes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LivenessResult:
    label: str
    url: str
    project: str
    environment: str
    status: str           # UP | SLOW | DOWN
    http: int | None
    ms: float
    err: str | None


@dataclass
class LivenessSection:
    results: list[LivenessResult]
    counts: dict[str, int]


@dataclass
class ScriptResult:
    label: str
    filename: str
    duration_s: float
    verdict: str
    exit_code: int | None = None
    payload: dict[str, Any] | None = None
    stderr_tail: str = ""
    auth_relogin: bool = False
    auth_expired: bool = False
    detail: str | None = None


@dataclass
class MasterReport:
    started_ist: str
    auth_preflight: dict[str, str]
    liveness: LivenessSection
    scripts: list[ScriptResult]
    ended_ist: str = ""
    total_duration_s: float = 0.0
