"""The single definition of the health-check verdict vocabulary.

`Verdict` subclasses `str`, so a member is interchangeable with its wire string:
`Verdict.UP == "UP"`, `json.dumps(Verdict.UP) == '"UP"'`, and `.upper()/.split()`
behave like a plain string. Producers return `Verdict.*`; the vocabulary lives
here and nowhere else.
"""
from __future__ import annotations

from enum import Enum


class Verdict(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    DEGRADED = "DEGRADED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    KNOWN_ISSUE = "KNOWN-ISSUE"
    SLOW = "SLOW"
    PASS = "PASS"
    PASSED = "PASSED"
    MISSING = "MISSING"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"

    def __str__(self) -> str:  # so f"{Verdict.UP}" == "UP", not "Verdict.UP"
        return self.value
