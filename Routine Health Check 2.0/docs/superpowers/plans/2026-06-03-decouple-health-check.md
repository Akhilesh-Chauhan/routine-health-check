# Decouple Health-Check Framework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the structural coupling that makes a change to one service break unrelated ones, so the suite is safe to evolve (including a future Playwright→Selenium backend swap) without cascading regressions.

**Architecture:** Introduce four seams, each behind a parity gate that proves zero behaviour change: (1) a single `Verdict` status type, (2) shared check primitives replacing copy-pasted logic, (3) a `BrowserDriver` port so checks no longer import Playwright, (4) a single atomic report writer + v2-owned profiles to stop status churn.

**Tech Stack:** Python 3.10, Playwright (sync API), pytest, Flask (web panel). Package is installed editable (`pip install -e .`); `hc` is the CLI entry point.

---

## Why (audit summary — the cascade sources this plan removes)

| # | Root cause | Evidence | Removed by |
|---|---|---|---|
| 1 | Stringly-typed verdicts — no single definition | ~280 literal verdict strings; `reporting/verdicts.py` only *classifies* | Phase 1 |
| 2 | No browser abstraction | 16 modules `import playwright` + launch their own context; `browser/context.py` helper bypassed by every check | Phase 3 |
| 3 | Copy-paste not reuse (already drifting) | `check_route`×5, chatbot widget×3 (prod=KNOWN-ISSUE vs dev=DOWN), `cognito_login`×2, `aggregate_verdict`×2, login-loop detectors ×4 | Phase 2 |
| 4 | Shared mutable report + shared profiles → status churn | one `master_report.json` written by sweep + per-check merge + v1 cron; `profiles/` symlinked into v1 | Phase 4 |
| 5 | Workspace session coupled to OP session | cms/mycms keep own session; one shared profile + login flow | Phase 4 (de-symlink) + documented |

**Execution order is the dependency order.** Phase 0 must land first. Phases 1, 2, 4 are independent of each other and each independently valuable. Phase 3 depends on Phase 2 (primitives must exist before the driver is threaded through them). If you want to stop early, 0→1→2 removes the two worst cascade sources.

---

## Phase 0 — Parity gate (do this first)

**Rationale:** `_common.py` already says consolidation was blocked because there was no verdict-parity check. We build that check now: a golden fixture exercised through every *pure* report-processing path (`classify`, `derive_verdict`, the `/verdicts` rollup, the dashboard JS classifier). These run offline (no browser, no network), so they lock reporting behaviour while Phases 1–4 refactor underneath.

### Task 0.1: Capture a representative golden report fixture

**Files:**
- Create: `tests/fixtures/golden_master_report.json`
- Create: `tests/test_parity_golden.py`

- [ ] **Step 1: Write the golden fixture**

Create `tests/fixtures/golden_master_report.json` with a hand-built report that exercises every verdict and payload shape (bots, steps, domains, liveness). Use this exact content:

```json
{
  "started_ist": "2026-06-03T13:40:42+05:30",
  "ended_ist": "2026-06-03T13:50:35+05:30",
  "total_duration_s": 593.0,
  "auth_preflight": {"prod": "AUTHED", "dev": "AUTHED", "umang": "AUTHED"},
  "liveness": {"counts": {"UP": 18, "SLOW": 1, "DOWN": 2},
    "results": [
      {"label": "home", "url": "https://www.myscheme.gov.in/", "project": "myScheme Portal", "environment": "production", "status": "UP", "http": 200, "ms": 120.0, "err": null},
      {"label": "cms", "url": "https://cms.myscheme.gov.in/", "project": "CMS", "environment": "production", "status": "SLOW", "http": 200, "ms": 4200.0, "err": null},
      {"label": "doe", "url": "https://doe.myscheme.in/", "project": "DoE Chatbot", "environment": "production", "status": "DOWN", "http": 503, "ms": 0.0, "err": "HTTP 503"}
    ]},
  "scripts": [
    {"label": "Public — myscheme.gov.in E2E", "filename": "health_check.checks.public.myscheme",
     "duration_s": 102.0, "exit_code": 0, "verdict": "UP",
     "payload": {"overall": "UP", "steps": [
       {"name": "Home", "verdict": "UP"}, {"name": "Search", "verdict": "UP"},
       {"name": "Chatbot reply", "verdict": "KNOWN-ISSUE"}]}},
    {"label": "Public — 6 standalone bots", "filename": "health_check.checks.public.chatbots",
     "duration_s": 60.0, "exit_code": 0, "verdict": "DEGRADED (some bots DOWN)",
     "payload": {"bots": [
       {"name": "DoE", "url": "https://doe.myscheme.in/", "verdict": "UP"},
       {"name": "SAI", "url": "https://sports-psq.myscheme.in/", "verdict": "DOWN"}]}},
    {"label": "Dev environment full sweep", "filename": "health_check.checks.dev.environment",
     "duration_s": 162.0, "exit_code": 0, "verdict": "DOWN (one or more dev domains failed)",
     "payload": {"overall": "DOWN (one or more dev domains failed)", "steps": [
       {"name": "dev.myscheme.gov.in", "verdict": "DOWN", "checks": [
         {"name": "Main landing", "url": "https://dev.myscheme.gov.in/", "verdict": "UP"},
         {"name": "Chatbot widget", "verdict": "DOWN"}]}]}},
    {"label": "UMANG integration", "filename": "health_check.checks.umang.integration",
     "duration_s": 90.0, "exit_code": 0, "verdict": "AUTH_EXPIRED (sign-in required — not a service outage)",
     "payload": {"overall": "DEGRADED (UMANG Integration Defect)", "steps": [
       {"name": "mycms.umangapp.in", "verdict": "DEGRADED", "checks": [
         {"name": "Dashboard", "url": "https://mycms.umangapp.in/national-e-governance-division/dashboard", "verdict": "DEGRADED"}]}]}}
  ]
}
```

- [ ] **Step 2: Write the golden parity test**

Create `tests/test_parity_golden.py`:

```python
"""Parity gate: locks the PURE report-processing behaviour (no browser/network)
so Phases 1-4 can refactor underneath without changing observable output.

If a refactor is meant to preserve behaviour and one of these fails, the refactor
changed something. If a change is intentional, update the golden values in the
SAME commit with a message explaining the behaviour change.
"""
from __future__ import annotations

import json
from pathlib import Path

from health_check import paths
from health_check.orchestration import master
from health_check.reporting import verdicts
from health_check.web import app as web_app

FIXTURE = Path(__file__).parent / "fixtures" / "golden_master_report.json"


def _load():
    return json.loads(FIXTURE.read_text())


def test_classify_corpus_is_stable():
    corpus = ["UP", "DOWN", "DEGRADED", "DEGRADED (some bots DOWN)",
              "AUTH_EXPIRED", "SLOW", "PASS", "PASSED", "KNOWN-ISSUE",
              "TIMEOUT", "ERROR", "MISSING", "", "WAT"]
    got = {v: verdicts.classify(v) for v in corpus}
    assert got == {
        "UP": "up", "DOWN": "down", "DEGRADED": "warn",
        "DEGRADED (some bots DOWN)": "warn", "AUTH_EXPIRED": "warn",
        "SLOW": "warn", "PASS": "up", "PASSED": "up", "KNOWN-ISSUE": "unknown",
        "TIMEOUT": "down", "ERROR": "down", "MISSING": "down",
        "": "unknown", "WAT": "unknown",
    }


def test_derive_verdict_is_stable():
    assert master.derive_verdict({"overall": "UP"}, 0) == "UP"
    assert master.derive_verdict({"bots": [{"verdict": "UP"}, {"verdict": "UP"}]}, 0) == "UP"
    assert master.derive_verdict({"steps": [{"verdict": "UP"}, {"verdict": "UP"}]}, 0) == "UP"
    assert master.derive_verdict({"bots": [{"verdict": "UP"}, {"verdict": "DOWN"}]}, 0) == "DEGRADED (some bots DOWN)"
    assert master.derive_verdict({"steps": [{"verdict": "UP"}, {"verdict": "DOWN"}]}, 0) == "DOWN"


def test_verdicts_endpoint_rollup_is_stable(monkeypatch, tmp_path):
    rep = tmp_path / "master_report.json"
    rep.write_text(FIXTURE.read_text())
    monkeypatch.setattr(paths, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(paths, "MASTER_REPORT", rep)
    data = web_app.create_app().test_client().get("/verdicts").get_json()
    assert data["summary"] == {"up": 6, "warn": 3, "down": 3, "total": 12}
    assert data["checks"]["myscheme"] == "UP"
    assert data["checks"]["devenv"] == "DOWN"
    assert data["checks"]["umang"] == "AUTH_EXPIRED"
```

- [ ] **Step 3: Run the parity tests and CALIBRATE**

Run: `python3 -m pytest tests/test_parity_golden.py -v`
Expected: tests run. The `summary`/`checks` asserted values above are predictions — if a value differs, **the current code is the source of truth**: update the assertion to the value the current code actually produces (do NOT change production code). Re-run until green. This green state is now the golden baseline.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/golden_master_report.json tests/test_parity_golden.py
git commit -m "test: parity gate locking pure report-processing behaviour"
```

---

## Phase 1 — Single `Verdict` status type (removes cause #1)

**Rationale:** ~280 verdict string literals mean a vocabulary change touches 11+ files and misses are silent. A `str`-subclass enum is a drop-in: `Verdict.UP == "UP"` is `True`, `json.dumps(Verdict.UP)` is `"UP"`, and `.upper()/.split()/.startswith()` all work — verified. So producers migrate to `Verdict.UP` with **zero wire/behaviour change**, and the vocabulary lives in one file.

### Task 1.1: Create the status module

**Files:**
- Create: `src/health_check/reporting/status.py`
- Test: `tests/test_status.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_status.py`:

```python
import json
from health_check.reporting.status import Verdict


def test_verdict_is_str_compatible():
    assert Verdict.UP == "UP"
    assert Verdict.DOWN in ("DOWN", "FAILED")
    assert Verdict.UP.upper() == "UP"


def test_verdict_serialises_as_plain_string():
    assert json.dumps({"verdict": Verdict.UP}) == '{"verdict": "UP"}'


def test_all_members_present():
    assert {v.value for v in Verdict} == {
        "UP", "DOWN", "DEGRADED", "AUTH_EXPIRED", "KNOWN-ISSUE",
        "SLOW", "PASS", "PASSED", "MISSING", "TIMEOUT", "ERROR",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_status.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'health_check.reporting.status'`

- [ ] **Step 3: Write minimal implementation**

Create `src/health_check/reporting/status.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_status.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/health_check/reporting/status.py tests/test_status.py
git commit -m "feat: single Verdict status type (str-enum, drop-in)"
```

### Task 1.2: Migrate the dev + UMANG aggregate_verdict to Verdict

**Files:**
- Modify: `src/health_check/checks/dev/environment.py` (`aggregate_verdict`)
- Modify: `src/health_check/checks/umang/integration.py` (`aggregate_verdict`)
- Test: `tests/test_dev_aggregate.py` (already exists; keep green)

- [ ] **Step 1: Run the existing test to confirm baseline green**

Run: `python3 -m pytest tests/test_dev_aggregate.py -v`
Expected: PASS (3 cases × 2 params = 6)

- [ ] **Step 2: Edit `dev/environment.py`** — add the import after the existing `_common` import and rewrite `aggregate_verdict`:

```python
from health_check.reporting.status import Verdict
```
```python
def aggregate_verdict(checks):
    vs = [c.get("verdict", "?") for c in checks]
    if all(v == Verdict.UP for v in vs): return Verdict.UP
    if any(v == Verdict.DOWN for v in vs): return Verdict.DOWN
    return Verdict.DEGRADED
```

- [ ] **Step 3: Edit `umang/integration.py`** — same import line and identical `aggregate_verdict` body as Step 2.

- [ ] **Step 4: Run tests (unit + parity)**

Run: `python3 -m pytest tests/test_dev_aggregate.py tests/test_parity_golden.py -v`
Expected: PASS (still green — `Verdict.UP == "UP"`)

- [ ] **Step 5: Commit**

```bash
git add src/health_check/checks/dev/environment.py src/health_check/checks/umang/integration.py
git commit -m "refactor: aggregate_verdict returns Verdict (no behaviour change)"
```

### Task 1.3: Migrate `master.derive_verdict` to Verdict

**Files:**
- Modify: `src/health_check/orchestration/master.py` (`derive_verdict`, lines ~330–352)

- [ ] **Step 1: Add import** near the top imports of `master.py`:

```python
from health_check.reporting.status import Verdict
```

- [ ] **Step 2: Rewrite the rollup branches** in `derive_verdict` (the `bots` / `steps` blocks) to return `Verdict.*`:

```python
        if "bots" in payload:
            bot_verdicts = [b.get("verdict", "?") for b in payload.get("bots", [])]
            if all(v == Verdict.UP for v in bot_verdicts):
                return Verdict.UP
            if any(v == Verdict.DOWN for v in bot_verdicts):
                return "DEGRADED (some bots DOWN)"
            return Verdict.DEGRADED
        if "steps" in payload:
            step_verdicts = [s.get("verdict", "?") for s in payload.get("steps", [])]
            if all(v == Verdict.UP for v in step_verdicts):
                return Verdict.UP
            if any(v == Verdict.DOWN for v in step_verdicts):
                return Verdict.DOWN
            return Verdict.DEGRADED
    return Verdict.PASSED if returncode == 0 else "FAILED"
```

(Note: `"DEGRADED (some bots DOWN)"` and `"FAILED"` stay as literals — they are not single-token members; `Verdict.DEGRADED`/`Verdict.PASSED` cover the plain cases.)

- [ ] **Step 3: Run tests**

Run: `python3 -m pytest tests/test_individual_check_persist.py tests/test_parity_golden.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/health_check/orchestration/master.py
git commit -m "refactor: derive_verdict returns Verdict (no behaviour change)"
```

### Task 1.4: Migrate the single-domain check producers to Verdict

**Files (each has `report["overall"] = "..."` and per-step `verdict="..."` assignments):**
- Modify: `src/health_check/checks/prod/cms.py`, `prod/forms.py`, `prod/govai.py`, `public/aistore.py`, `public/docs_portal.py`, `public/rules_engine.py`, `public/chatbots.py`, `public/myscheme.py`, `prod/auth_precheck.py`, `checks/dev/environment.py`, `checks/umang/integration.py`

- [ ] **Step 1: For EACH module, add the import** (after its existing imports):

```python
from health_check.reporting.status import Verdict
```

- [ ] **Step 2: In EACH module, replace overall/verdict string literals with members.** Run this guided replacement per file and eyeball each hit (multi-word strings like `"DEGRADED (...)"` stay literals):

```bash
# show every literal to convert, per file:
grep -nE '"(UP|DOWN|DEGRADED|AUTH_EXPIRED|KNOWN-ISSUE|SLOW|PASS|PASSED|MISSING|TIMEOUT|ERROR)"' src/health_check/checks/prod/cms.py
```

Convert exact single-token assignments, e.g.:
- `report["overall"] = "UP"` → `report["overall"] = Verdict.UP`
- `verdict="DOWN"` → `verdict=Verdict.DOWN`
- `log_step("X", "KNOWN-ISSUE", ...)` → `log_step("X", Verdict.KNOWN_ISSUE, ...)`

Leave compound strings (`"DEGRADED (UMANG Integration Defect)"`, `"AUTH_EXPIRED (sign-in required — not a service outage)"`) as literals.

- [ ] **Step 3: After each file, run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS. Commit per file (or per logical group) so a parity break is bisectable:

```bash
git add src/health_check/checks/prod/cms.py
git commit -m "refactor: cms check returns Verdict (no behaviour change)"
```

- [ ] **Step 4: Final guard — assert no bare single-token verdict literals remain in producers**

Run:
```bash
grep -rnE 'verdict[ =]+"(UP|DOWN|DEGRADED|KNOWN-ISSUE|AUTH_EXPIRED)"|overall"\] = "(UP|DOWN|DEGRADED)"' src/health_check/checks/
```
Expected: no output (compound-string assignments are allowed and won't match the single-token pattern).

---

## Phase 2 — Shared check primitives (removes cause #3)

**Rationale:** `check_route`×5, the chatbot widget×3 (already drifted: prod=KNOWN-ISSUE, dev=DOWN), `cognito_login`×2, login-bounce detectors ×4. One bug fix today must be made N times and gets missed. Consolidate into one module; per-surface differences become parameters. Every step is parity-gated.

### Task 2.1: Extract the chatbot-widget primitive

**Files:**
- Create: `src/health_check/checks/_primitives.py`
- Test: `tests/test_primitives_chatbot.py`

- [ ] **Step 1: Write the failing test** (drives a fake page/frame — no real browser):

Create `tests/test_primitives_chatbot.py`:

```python
"""The chatbot-widget primitive: one implementation parameterised by the
on-blank verdict (prod records KNOWN-ISSUE; dev records DOWN)."""
from health_check.checks._primitives import chatbot_widget_result
from health_check.reporting.status import Verdict


def test_blank_maps_to_configured_verdict_dev():
    # cards never render, frame ended on a cognito/chrome-error url
    r = chatbot_widget_result(cards_ready=False, got_reply=False,
                              frame_url="chrome-error://chromewebdata/",
                              on_blank=Verdict.DOWN)
    assert r["verdict"] == Verdict.DOWN
    assert "X-Frame-Options" in r["detail"]


def test_blank_maps_to_configured_verdict_prod():
    r = chatbot_widget_result(cards_ready=False, got_reply=False,
                              frame_url="chrome-error://chromewebdata/",
                              on_blank=Verdict.KNOWN_ISSUE)
    assert r["verdict"] == Verdict.KNOWN_ISSUE


def test_reply_is_up():
    r = chatbot_widget_result(cards_ready=True, got_reply=True,
                              frame_url="https://aistore.myscheme.in/x?isEmbed=true",
                              on_blank=Verdict.DOWN)
    assert r["verdict"] == Verdict.UP


def test_cards_but_no_reply_is_down():
    r = chatbot_widget_result(cards_ready=True, got_reply=False,
                              frame_url="https://aistore.myscheme.in/x?isEmbed=true",
                              on_blank=Verdict.DOWN)
    assert r["verdict"] == Verdict.DOWN
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_primitives_chatbot.py -v`
Expected: FAIL (`ModuleNotFoundError` / `ImportError: chatbot_widget_result`)

- [ ] **Step 3: Write the primitive** — the pure verdict-decision split out from the I/O:

Create `src/health_check/checks/_primitives.py`:

```python
"""Reusable check primitives shared by the public / prod / dev / umang surfaces.

The DECISION logic (what verdict a set of observations maps to) is kept pure and
unit-testable here; the per-surface modules supply the I/O (driving the browser)
and pass the observations in. This is the single home for behaviour that was
previously copy-pasted (and drifting) across modules.
"""
from __future__ import annotations

from health_check.reporting.status import Verdict


def chatbot_widget_result(*, cards_ready: bool, got_reply: bool,
                          frame_url: str, on_blank: Verdict,
                          note: str = "") -> dict:
    """Map chatbot-widget observations to a verdict dict.

    `on_blank` lets each surface choose how a blank widget is recorded:
    dev uses Verdict.DOWN (a broken chatbot is a real failure); the public
    portal uses Verdict.KNOWN_ISSUE (flagged-to-dev intermittent issue).
    """
    if not cards_ready:
        detail = ("Chatbot iframe loaded blank / stuck — no prompter cards even "
                  f"after the click-to-load workaround (frame on {frame_url or 'about:blank'}). "
                  "Cause: chatbot embed redirects to the Cognito hosted login inside the "
                  "iframe and Cognito sets X-Frame-Options: DENY, so it cannot render.")
        return {"verdict": on_blank, "detail": detail}
    if got_reply:
        return {"verdict": Verdict.UP, "detail": f"Chatbot opened and replied{note}"}
    return {"verdict": Verdict.DOWN,
            "detail": f"Prompter cards rendered{note} but no bot reply within 30s"}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_primitives_chatbot.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/health_check/checks/_primitives.py tests/test_primitives_chatbot.py
git commit -m "feat: shared chatbot-widget verdict primitive"
```

### Task 2.2: Rewire `dev/environment.py:check_dev_chatbot` to the primitive

**Files:**
- Modify: `src/health_check/checks/dev/environment.py` (`check_dev_chatbot`)

- [ ] **Step 1:** In `check_dev_chatbot`, keep all the Playwright I/O (launcher click, frame find, `cards_ready`, reply polling) but replace the three hand-written `s.update(verdict=...)` outcome blocks with a single call. After computing `ready` (bool), `got_reply` (bool, default False when not reached), and `frame_url = (chat_frame.url or "")`:

```python
from health_check.checks._primitives import chatbot_widget_result
...
        outcome = chatbot_widget_result(
            cards_ready=ready, got_reply=got_reply, frame_url=frame_url,
            on_blank=Verdict.DOWN, note=note)
        s.update(verdict=outcome["verdict"],
                 duration_ms=round((time.perf_counter()-t0)*1000, 1),
                 detail=outcome["detail"])
        if outcome["verdict"] != Verdict.UP:
            s["artifact"] = snap(page, "devmain_chatbot_blank")
        return s
```

- [ ] **Step 2: Run the full suite + a live dev check (parity in practice)**

Run: `python3 -m pytest -q`
Then: `DISPLAY=:0 HC_NONINTERACTIVE=1 hc check devenv 2>&1 | grep "recorded 'devenv'"`
Expected: tests PASS; live check records `devenv -> DOWN` with the chatbot detail mentioning `X-Frame-Options`.

- [ ] **Step 3: Commit**

```bash
git add src/health_check/checks/dev/environment.py
git commit -m "refactor: dev chatbot check uses shared primitive (DOWN on blank)"
```

### Task 2.3: Rewire `public/myscheme.py` + `umang/integration.py` chatbot blocks

**Files:**
- Modify: `src/health_check/checks/public/myscheme.py` (STEP 3 chatbot block, ~lines 201–310)
- Modify: `src/health_check/checks/umang/integration.py` (chatbot block)

- [ ] **Step 1:** In each, replace the bespoke outcome `log_step(...)`/`s.update(...)` branches with `chatbot_widget_result(..., on_blank=Verdict.KNOWN_ISSUE)` for myscheme (preserves today's KNOWN-ISSUE behaviour) and `on_blank=Verdict.DOWN` for umang (preserves today's behaviour). Keep each module's existing logging call shape; only the verdict/detail values come from the primitive.

- [ ] **Step 2: Run the suite**

Run: `python3 -m pytest -q`
Expected: PASS

- [ ] **Step 3: Live parity spot-check**

Run: `DISPLAY=:0 HC_NONINTERACTIVE=1 hc check myscheme 2>&1 | grep -i "recorded 'myscheme'"`
Expected: `myscheme -> UP` (unchanged).

- [ ] **Step 4: Commit**

```bash
git add src/health_check/checks/public/myscheme.py src/health_check/checks/umang/integration.py
git commit -m "refactor: prod+umang chatbot checks use shared primitive"
```

### Task 2.4: Extract the route-check + login-bounce primitives

**Files:**
- Modify: `src/health_check/checks/_primitives.py` (add `route_result`, `looks_login_bounce`)
- Modify: `src/health_check/checks/dev/environment.py`, `umang/integration.py`, `prod/cms.py`, `prod/forms.py`, `prod/govai.py` (the 5 `check_route` copies)
- Test: `tests/test_primitives_route.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_primitives_route.py`:

```python
from health_check.checks._primitives import route_result, looks_login_bounce
from health_check.reporting.status import Verdict

SSO_URLS = ["digilocker.meripehchaan.gov.in", "auth.myscheme.gov.in"]
SSO_BODY = ["sign in to your account", "send otp"]


def test_login_bounce_detected_by_url():
    assert looks_login_bounce("https://auth.myscheme.gov.in/x", "", SSO_URLS, SSO_BODY)


def test_login_bounce_detected_by_body():
    assert looks_login_bounce("https://app/x", "Please Send OTP", SSO_URLS, SSO_BODY)


def test_no_bounce_when_clean():
    assert not looks_login_bounce("https://mycms.umangapp.in/dashboard", "Dashboard Users", SSO_URLS, SSO_BODY)


def test_route_http_error_is_down():
    r = route_result(status=503, final_url="https://x/", body="boom",
                     signals=["dashboard"], sso_urls=SSO_URLS, sso_body=SSO_BODY)
    assert r["verdict"] == Verdict.DOWN


def test_route_bounce_is_degraded():
    r = route_result(status=200, final_url="https://auth.myscheme.gov.in/", body="send otp",
                     signals=["dashboard"], sso_urls=SSO_URLS, sso_body=SSO_BODY)
    assert r["verdict"] == Verdict.DEGRADED


def test_route_missing_signal_is_degraded():
    r = route_result(status=200, final_url="https://app/x", body="totally unrelated text",
                     signals=["dashboard"], sso_urls=SSO_URLS, sso_body=SSO_BODY)
    assert r["verdict"] == Verdict.DEGRADED


def test_route_ok_is_up():
    r = route_result(status=200, final_url="https://app/x", body="Dashboard and users",
                     signals=["dashboard"], sso_urls=SSO_URLS, sso_body=SSO_BODY)
    assert r["verdict"] == Verdict.UP
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_primitives_route.py -v`
Expected: FAIL (`ImportError`)

- [ ] **Step 3: Implement** — append to `_primitives.py`:

```python
def looks_login_bounce(url: str, body: str, sso_urls: list[str],
                       sso_body: list[str]) -> bool:
    u = (url or "").lower(); b = (body or "").lower()
    return any(h in u for h in sso_urls) or any(h in b for h in sso_body)


def route_result(*, status, final_url: str, body: str, signals: list[str],
                 sso_urls: list[str], sso_body: list[str]) -> dict:
    """Map a navigated route's observations to a verdict dict (pure)."""
    if status is not None and status >= 400:
        return {"verdict": Verdict.DOWN, "detail": f"HTTP {status}"}
    if looks_login_bounce(final_url, body, sso_urls, sso_body):
        return {"verdict": Verdict.DEGRADED,
                "detail": f"Bounced to sign-in surface — SSO session not honored ({final_url})"}
    body_l = (body or "").lower()
    if signals and not any(s in body_l for s in signals):
        return {"verdict": Verdict.DEGRADED,
                "detail": f"Page loaded but expected signals {signals} not found"}
    return {"verdict": Verdict.UP, "detail": "Content signals present"}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_primitives_route.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Migrate the 5 `check_route` copies** one module at a time. In each, keep the navigation/`goto`/screenshot I/O; replace the verdict-decision tail with `route_result(...)`, passing that surface's SSO url/body hint lists. Run `python3 -m pytest -q` after each, then a live `hc check <name>` parity spot-check, then commit:

```bash
git add src/health_check/checks/dev/environment.py
git commit -m "refactor: dev check_route uses shared route_result primitive"
```

Repeat for `umang/integration.py`, `prod/cms.py`, `prod/forms.py`, `prod/govai.py`.

- [ ] **Step 6: Final dedup guard**

Run: `grep -rcE "^def check_route" src/health_check/checks/`
Expected: every file reports `0` (the local copies are gone; only `route_result` in `_primitives.py` remains).

---

## Phase 3 — Browser driver port (removes cause #2; enables Selenium swap)

**Rationale:** 16 modules import Playwright and each launches its own context. Define a narrow port the checks depend on; provide a Playwright adapter now. A Selenium adapter later is then additive, not a rewrite. Phase 2 must land first so the surface area calling the browser is already centralised in primitives.

### Task 3.1: Define the `BrowserDriver` / `PageHandle` protocol

**Files:**
- Create: `src/health_check/browser/driver.py`
- Test: `tests/test_browser_driver_contract.py`

- [ ] **Step 1: Write the contract test** against a fake adapter implementing the protocol:

Create `tests/test_browser_driver_contract.py`:

```python
from health_check.browser.driver import PageHandle


class FakePage:
    def __init__(self): self._url = "https://start/"
    def goto(self, url, timeout_ms=30000): self._url = url; return 200
    @property
    def url(self): return self._url
    def inner_text(self): return "Dashboard"
    def click(self, selector, timeout_ms=5000): return None
    def wait_for(self, selector, timeout_ms=10000): return True
    def screenshot(self, path): return path


def test_fake_satisfies_protocol():
    p: PageHandle = FakePage()           # type: ignore[assignment]
    assert p.goto("https://x/") == 200
    assert p.url == "https://x/"
    assert p.inner_text() == "Dashboard"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_browser_driver_contract.py -v`
Expected: FAIL (`ModuleNotFoundError: health_check.browser.driver`)

- [ ] **Step 3: Implement the protocol**

Create `src/health_check/browser/driver.py`:

```python
"""The browser port the checks depend on, instead of Playwright directly.

A check receives a `PageHandle`; it never imports playwright. Today's adapter
wraps Playwright (`browser/playwright_driver.py`); a Selenium adapter can be
added later without touching a single check.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PageHandle(Protocol):
    def goto(self, url: str, timeout_ms: int = 30000) -> int | None: ...
    @property
    def url(self) -> str: ...
    def inner_text(self) -> str: ...
    def click(self, selector: str, timeout_ms: int = 5000) -> None: ...
    def wait_for(self, selector: str, timeout_ms: int = 10000) -> bool: ...
    def screenshot(self, path: str) -> str: ...


@runtime_checkable
class BrowserDriver(Protocol):
    def open(self, tenant: str, headless: bool = True) -> PageHandle: ...
    def close(self) -> None: ...
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_browser_driver_contract.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/health_check/browser/driver.py tests/test_browser_driver_contract.py
git commit -m "feat: BrowserDriver/PageHandle port (checks no longer bound to Playwright)"
```

### Task 3.2: Implement the Playwright adapter

**Files:**
- Create: `src/health_check/browser/playwright_driver.py`
- Test: `tests/test_playwright_adapter_smoke.py` (skipped unless browsers available)

- [ ] **Step 1: Implement the adapter** wrapping `browser/context.py:launch_persistent_context` and a Playwright `Page`, mapping each protocol method to the Playwright call (e.g. `goto` → `page.goto(...).status`, `inner_text` → `page.evaluate("() => document.body.innerText")`, `wait_for` → `page.wait_for_selector` returning bool).

Create `src/health_check/browser/playwright_driver.py`:

```python
from __future__ import annotations

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from health_check.browser import context as ctx


class PlaywrightPage:
    def __init__(self, page): self._p = page
    def goto(self, url, timeout_ms=30000):
        r = self._p.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        return r.status if r is not None else None
    @property
    def url(self): return self._p.url
    def inner_text(self):
        return self._p.evaluate("() => (document.body && document.body.innerText) || ''")
    def click(self, selector, timeout_ms=5000):
        self._p.locator(selector).first.click(timeout=timeout_ms)
    def wait_for(self, selector, timeout_ms=10000):
        try:
            self._p.wait_for_selector(selector, state="visible", timeout=timeout_ms)
            return True
        except PWTimeout:
            return False
    def screenshot(self, path):
        try: self._p.screenshot(path=path)
        except Exception: pass
        return path


class PlaywrightDriver:
    def __init__(self): self._pw = None; self._ctx = None
    def open(self, tenant, headless=True):
        self._pw = sync_playwright().start()
        self._ctx = ctx.launch_persistent_context(self._pw, tenant, headless=headless)
        page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return PlaywrightPage(page)
    def close(self):
        try:
            if self._ctx: self._ctx.close()
        finally:
            if self._pw: self._pw.stop()
```

- [ ] **Step 2: Smoke test** (auto-skip when browser/profile absent):

Create `tests/test_playwright_adapter_smoke.py`:

```python
import os, pytest
from health_check.browser.driver import PageHandle


@pytest.mark.skipif(not os.environ.get("HC_LIVE_BROWSER"),
                    reason="set HC_LIVE_BROWSER=1 to run the live adapter smoke test")
def test_adapter_is_a_pagehandle():
    from health_check.browser.playwright_driver import PlaywrightDriver
    d = PlaywrightDriver()
    page = d.open("prod")
    try:
        assert isinstance(page, PageHandle)
        assert page.goto("https://www.myscheme.gov.in/") in (200, None)
    finally:
        d.close()
```

- [ ] **Step 3: Run**

Run: `python3 -m pytest tests/test_playwright_adapter_smoke.py -v`
Expected: SKIPPED (no `HC_LIVE_BROWSER`). With `HC_LIVE_BROWSER=1 DISPLAY=:0`: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/health_check/browser/playwright_driver.py tests/test_playwright_adapter_smoke.py
git commit -m "feat: Playwright adapter implementing the BrowserDriver port"
```

### Task 3.3: Migrate ONE check end-to-end as the reference (cms)

**Files:**
- Modify: `src/health_check/checks/prod/cms.py` to receive a `PageHandle` and stop importing playwright.

- [ ] **Step 1:** Refactor `cms.py` so its `run()` accepts an injected driver (defaulting to `PlaywrightDriver`) and all browser calls go through `PageHandle`. Remove `from playwright.sync_api import ...`. Keep the printed JSON shape identical.

- [ ] **Step 2: Parity check (offline + live)**

Run: `python3 -m pytest -q`
Then: `DISPLAY=:0 HC_NONINTERACTIVE=1 hc check cms 2>&1 | grep -i "recorded 'cms'"`
Expected: tests PASS; `cms -> UP` (unchanged). Diff the printed payload against a pre-migration capture to confirm identical fields.

- [ ] **Step 3: Commit**

```bash
git add src/health_check/checks/prod/cms.py
git commit -m "refactor: cms check depends on BrowserDriver port, not Playwright"
```

- [ ] **Step 4:** Migrate the remaining checks the same way, one commit each, parity-checked. After the last, assert decoupling:

```bash
grep -rl "from playwright" src/health_check/checks/
```
Expected: empty (only `browser/playwright_driver.py` imports Playwright). A Selenium adapter is now a single new file implementing `BrowserDriver`.

---

## Phase 4 — Stop the status churn (removes cause #4/#5)

**Rationale:** One `master_report.json` is mutated by full sweeps, per-check `hc check` merges, and (via shared profiles) v1 cron runs — so unrelated runs flip statuses (the HEALTHY→DEGRADED→UP flap you saw on UMANG). Make writes atomic + single-writer, and give v2 its own profiles.

### Task 4.1: Atomic, single-writer report merge

**Files:**
- Modify: `src/health_check/orchestration/master.py` (`merge_script_result` and the sweep writer)
- Test: `tests/test_report_atomic_merge.py`

- [ ] **Step 1: Write the failing test** — concurrent merges never corrupt or lose entries:

```python
import json, threading
from health_check import paths
from health_check.orchestration import master


def test_concurrent_merges_are_atomic(monkeypatch, tmp_path):
    rep = tmp_path / "master_report.json"
    rep.write_text(json.dumps({"scripts": []}))
    monkeypatch.setattr(paths, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(paths, "MASTER_REPORT", rep)
    mods = [f"health_check.checks.public.bot{i}" for i in range(20)]

    def merge(m):
        master.merge_script_result(m, json.dumps({"bots": [{"verdict": "UP"}]}), 0, 1.0)

    ts = [threading.Thread(target=merge, args=(m,)) for m in mods]
    [t.start() for t in ts]; [t.join() for t in ts]
    scripts = json.loads(rep.read_text())["scripts"]
    assert len({s["filename"] for s in scripts}) == 20  # no lost updates, valid JSON
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_report_atomic_merge.py -v`
Expected: FAIL (lost updates / `JSONDecodeError` under contention)

- [ ] **Step 3: Implement** — wrap read-modify-write in a file lock (`fcntl.flock` on a `.lock` sidecar) and write via temp-file + `os.replace` (atomic rename). Add a helper `_locked_update(path, fn)` in `master.py` and route both `merge_script_result` and the sweep's final write through it.

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_report_atomic_merge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/health_check/orchestration/master.py tests/test_report_atomic_merge.py
git commit -m "fix: atomic single-writer report merge (stops status churn)"
```

### Task 4.2: Give v2 its own profiles (de-symlink from v1)

**Files:**
- Modify: `docs/AUTH.md` (+ `CLAUDE.md` "Profiles" section) — document the change.
- Operational (not code): replace the `profiles/_*` symlinks with real copies so a v1 cron run/login no longer mutates v2 session state.

- [ ] **Step 1: Document the rationale** in `CLAUDE.md` under "Profiles": v2 must NOT share live session state with v1; symlinks let v1's `*/15` liveness + `10,14,18` sweep cron mutate the same cookies/localStorage v2 reads, which is a churn source.

- [ ] **Step 2: One-time migration commands** (record them in `docs/AUTH.md`):

```bash
cd "Routine Health Check 2.0/profiles"
for t in _browser_profile _dev_browser_profile _umang_browser_profile; do
  if [ -L "$t" ]; then real=$(readlink -f "$t"); rm "$t"; cp -a "$real" "$t"; fi
done
```

- [ ] **Step 3: Verify isolation** — run a v2 check and confirm it reads the v2-local profile (not v1):

Run: `DISPLAY=:0 HC_NONINTERACTIVE=1 hc check auth 2>&1 | grep -i "recorded 'auth'"`
Expected: `auth -> UP`, and `ls -la profiles/` shows real directories, not symlinks.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/AUTH.md
git commit -m "docs: de-symlink v2 profiles from v1 to stop cross-tree session churn"
```

---

## Self-review notes

- **Spec coverage:** every audit cause (#1–#5) maps to a phase (1, 3, 2, 4, 4). Parity is gated by Phase 0 + per-task live spot-checks.
- **Type consistency:** `Verdict` member names are fixed in Task 1.1 and reused verbatim (`Verdict.UP`, `Verdict.DOWN`, `Verdict.DEGRADED`, `Verdict.KNOWN_ISSUE`); primitives return `{"verdict": ..., "detail": ...}` dicts consumed identically by callers; `PageHandle`/`BrowserDriver` method names are fixed in Task 3.1 and reused by the adapter and migrations.
- **Known intentional behaviour change:** none. Every phase is parity-preserving; the only place verdict *values* could change is if a future maintainer edits an enum value (one place, by design).
- **Split option:** Phases 3 and 4 are independent subsystems; they can be lifted into their own plans if you prefer to ship 0–2 first.
