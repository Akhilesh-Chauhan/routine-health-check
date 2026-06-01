"""Self-hosted Roboto + Roboto Mono, inlined as base64 data URIs.

Both UIs render with the real Material/Google typeface and make ZERO external
requests (the dashboard must stay a self-contained single file; the control
panel must work offline). The woff2 files live alongside this module.

Licensing note: Roboto and Roboto Mono are Apache-2.0 (see fonts/LICENSE.txt)
and free to self-host. "Google Sans" is proprietary and is NOT licensable for
self-hosting — Roboto is Google's actual Material UI typeface and fills that
role here.
"""
from __future__ import annotations

import base64
import functools
from pathlib import Path

_DIR = Path(__file__).parent / "fonts"

# (css family, weight, style, filename)
_FACES = [
    ("Roboto",      400, "normal", "roboto-400.woff2"),
    ("Roboto",      500, "normal", "roboto-500.woff2"),
    ("Roboto",      700, "normal", "roboto-700.woff2"),
    ("Roboto Mono", 400, "normal", "roboto-mono-400.woff2"),
]


@functools.lru_cache(maxsize=1)
def font_face_css() -> str:
    """@font-face rules with the woff2 bytes inlined as data: URIs.

    Cached after the first build. Returns "" if the files are missing, so the
    UIs simply fall back to the system font stack rather than breaking.
    """
    rules = []
    for family, weight, style, filename in _FACES:
        try:
            b64 = base64.b64encode((_DIR / filename).read_bytes()).decode("ascii")
        except OSError:
            continue
        rules.append(
            "@font-face{font-family:'%s';font-style:%s;font-weight:%d;"
            "font-display:swap;"
            "src:url(data:font/woff2;base64,%s) format('woff2');}"
            % (family, style, weight, b64)
        )
    return "\n".join(rules)
