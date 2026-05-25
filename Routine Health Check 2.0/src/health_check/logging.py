"""Minimal logging setup for the suite.

We mostly emit structured progress lines to stdout (the orchestrator parses
the LAST JSON object out of each check's stdout, so logging on stderr is
fine — and preferred for noise). Each check still prints its single JSON
report to stdout as its final line.
"""
import logging
import os
import sys


def setup(level: str | None = None) -> logging.Logger:
    """Configure the root logger once. Returns the package logger."""
    lvl_name = (level or os.environ.get("HC_LOG_LEVEL") or "INFO").upper()
    lvl = getattr(logging, lvl_name, logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                                         datefmt="%H:%M:%S"))
        root.addHandler(h)
    root.setLevel(lvl)
    return logging.getLogger("health_check")
