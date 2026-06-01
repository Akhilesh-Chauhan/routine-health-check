"""Canonical verdict classifier (spec D13).

ONE source of truth for mapping a raw verdict string to a status bucket:

    up | warn | down | unknown

Before this module the same mapping lived in three places that had quietly
diverged: the dashboard template JS `classifyVerdict`, web/app.py's private
`_classify`, and (in emoji form) master.py's `severity_emoji`. They are now
all routed through `classify()`; the dashboard gets a JS transcription emitted
by `js_classifier()` so the browser uses the identical table.

The rule order matters and is the behaviour contract:

  * "up" rules first  — HEALTHY / UP / PASS / PASSED.
  * "warn" before "down" — so a verdict mentioning BOTH (e.g.
    "DEGRADED (some bots DOWN)") classifies as warn, matching the prior
    dashboard + app.py behaviour.
  * SLOW is warn (the dashboard already treated it so); it only ever
    appears on liveness rows, which app.py keeps as a separate signal.
"""
from __future__ import annotations

# Ordered rules: (bucket, kind, tokens). First match wins.
#   kind "contains" -> match if ANY token is a substring of the upper-cased verdict
#   kind "exact"    -> match if the upper-cased verdict EQUALS any token
_RULES = [
    ("up",   "contains", ["HEALTHY"]),
    ("up",   "exact",    ["UP", "PASS", "PASSED"]),
    ("warn", "contains", ["AUTH_EXPIRED", "DEGRADED"]),
    ("warn", "exact",    ["SLOW"]),
    ("down", "exact",    ["TIMEOUT", "ERROR", "MISSING"]),
    ("down", "contains", ["DOWN", "FAIL"]),
]


def classify(verdict) -> str:
    """Map a raw verdict string to 'up' | 'warn' | 'down' | 'unknown'."""
    if not verdict:
        return "unknown"
    s = str(verdict).upper()
    for bucket, kind, tokens in _RULES:
        if kind == "contains":
            if any(t in s for t in tokens):
                return bucket
        elif s in tokens:
            return bucket
    return "unknown"


def js_classifier(func_name: str = "classifyVerdict") -> str:
    """Emit a JS function whose branches mirror `classify()` exactly.

    The dashboard template inlines this so the browser and the server agree
    on every verdict, instead of carrying a hand-maintained copy that drifts.
    """
    lines = [
        f"function {func_name}(v) {{",
        '  if (!v) return "unknown";',
        "  const s = String(v).toUpperCase();",
    ]
    for bucket, kind, tokens in _RULES:
        if kind == "contains":
            cond = " || ".join(f's.includes("{t}")' for t in tokens)
        else:
            cond = " || ".join(f's === "{t}"' for t in tokens)
        lines.append(f"  if ({cond}) return \"{bucket}\";")
    lines.append('  return "unknown";')
    lines.append("}")
    return "\n".join(lines)
