# Luminous Glass — UI redesign + code hardening

**Project:** Routine Health Check 2.0 (v2 package only)
**Date:** 2026-05-29
**Status:** approved design → pending spec review

## Goal

Two outcomes in one pass:

1. **UI redesign** of both front-ends to a single modern "Luminous Glass" look
   (bright/airy base + frosted-glass surfaces + grid texture + neon-ish status +
   monospace data), with proper SVG icons and tasteful motion.
2. **Code hardening** — fix the correctness/security/robustness findings from the
   review, plus four agreed maintainability refactors.

No change to the `master_report.json` schema or any check's pass/fail semantics.

## Non-goals

- v1 (`../Health Check/`) — untouched.
- Rotating the leaked password / rewriting git history — flagged to the operator, out of scope here.
- New checks, new dashboard data, or auth-flow redesign.

---

## Part A — Design system: "Luminous Glass"

A single token block, defined once and reused by both UIs (CSS custom properties).
The control panel keeps them in `static/style.css`; the dashboard inlines the same
tokens in its template (it must stay a self-contained single file).

| Token | Value |
|---|---|
| `--bg` | `linear-gradient(135deg,#eef2fb,#f5f3ff)` + 22px grid overlay `rgba(99,102,241,.06)` |
| `--glass` | `rgba(255,255,255,.55)`, `backdrop-filter: blur(14px)` |
| `--glass-border` | hairline `rgba(255,255,255,.8)` highlight + `rgba(148,163,184,.18)` |
| `--shadow` | `0 8px 28px rgba(31,41,72,.07)` |
| `--accent` | gradient `#6366f1 → #22d3ee` (headlines, primary buttons) |
| `--up` | `#10b981` · `--warn` `#f59e0b` · `--down` `#f43f5e` · `--auth` `#a855f7` (each with a soft glow ring) |
| `--text` / `--text-2` / `--text-3` | `#0f172a` / `#475069` / `#8089a8` |
| fonts | UI: Inter/system-ui · Data: JetBrains Mono / `ui-monospace` |

**Icons:** one inline SVG sprite (Lucide-style 1.5px line icons) — activity, layout-grid,
braces, history, refresh-cw, play, log-in, trash, chevron, check-circle, alert-triangle,
x-circle, shield-x. No emoji glyphs, no icon-font, no CDN.

**Motion** (all gated behind `@media (prefers-reduced-motion: reduce)`):
count-up on stat numbers, card hover-lift, status-dot pulse, view cross-fade, and a
subtle shimmer on the running-job pill / log stream.

**Hard constraint:** everything self-contained / offline-safe — fonts fall back to
system stacks, icons inline, zero external requests.

---

## Part B — Dashboard (`orchestration/dashboard.py`)

Restyle the embedded `TEMPLATE` to the design system. Pure presentation:

- Hero: gradient headline, glass verdict pill (keeps the data-age/freshness banner
  added earlier), monospace timestamps.
- Donut + legend: recolored to status tokens, animated sweep.
- Stat cards: glass, top accent bar per status, monospace numbers with count-up.
- Liveness bar + grid: glass, neon status, monospace HTTP/ms.
- Project cards + screenshot tiles: glass, SVG status icons, lightbox unchanged.
- Replace all text glyphs with the SVG sprite.

The `TEMPLATE` string stays inline (self-contained requirement). The verdict→class
logic in the template JS is replaced by the unified classifier (Part D).

## Part C — Control panel (`web/templates/index.html`, `web/static/style.css`, `web/static/app.js`)

Restyle to the design system; behavior unchanged:

- Sidebar/brand/nav → glass, SVG nav icons, animated active state.
- Project tiles, env chips, badges → glass + status tokens + glow.
- Buttons (primary/ghost/warn) → gradient primary, glass ghost, motion.
- Right rail live log → glass, monospace stream, animated state pill + shimmer while running.
- `app.js` badge/verdict coloring uses the unified classifier (Part D); add markup
  hooks for the cancel button (Part D timeout/cancel).

---

## Part D — Code fixes

### Auto-fix (low-risk)
1. `web/runner.py` — guard `_current_id` and `next(self._counter)` under `_lock` (race).
2. `web/app.py` `/report` & `/verdicts` — `try/except` around read/parse → 503 JSON, not 500.
3. `orchestration/master.py` — write `master_report.json` to a temp file + `os.replace` (atomic), so mid-sweep reads can't see a partial file.
4. `web/app.py` `/run` — `get_json(silent=True)`, validate payload is a dict, 400 on bad input.
5. All check modules + `browser/context.py` consumers — `ctx.close()` moved into `try/finally`.
6. `orchestration/master.py` — lazy-load `LIVENESS_URLS` (function, not import-time global).
7. `web/app.py` `serve()` — log a warning when `--host` is non-loopback (Werkzeug dev server).

### Decided fixes
8. **Secrets** (`auth/dev_login.py`, `checks/dev/environment.py`, `checks/public/chatbots.py`):
   read Cognito user/pass from env (`HC_DEV_COGNITO_USER` / `HC_DEV_COGNITO_PASS`) or a
   gitignored `config/secrets.env`; **keep working** by loading that file if present.
   Remove the literal password defaults from source. Document that the committed secret
   remains in git history and should be rotated (operator action, out of scope).
9. **`probe_auth` bug** (`orchestration/master.py:~138`): return `UNKNOWN`/`LOGGED_OUT`
   on the no-signal branch instead of `AUTHED`. Expected effect: expired sessions are
   detected and re-login is triggered (more accurate; may prompt OTP more often).
10. **CSRF/Origin guard** on `POST /run`: reject requests whose `Origin`/`Host` isn't the
    local panel; lightweight, localhost-scoped.
11. **Per-job timeout + cancel**: `web/runner.py` gets a configurable per-step timeout
    and a kill path; new `POST /cancel/<job_id>` endpoint + a cancel button in the rail.
12. **Dedupe check helpers**: extract shared `snap` / route-check / cognito-goto / login-bounce
    heuristics into `checks/_common.py`; migrate `auth/*_login.py` poll loops to
    `auth/heuristics.looks_logged_in`. Behavior-preserving refactor.
13. **Unify verdict classifier**: one canonical verdict→{up,warn,down,unknown} mapping
    (new `reporting/verdicts.py`), consumed by `web/app.py`, `master.py`, and emitted
    into the dashboard template so the JS uses the same table.

---

## Testing

- Extend `tests/` (pytest): unit-test the unified classifier; `probe_auth` no-signal →
  not AUTHED; runner concurrency (no duplicate IDs under parallel submit); atomic report
  write (no partial read); `/run` rejects bad body + cross-origin; `/cancel` kills a job;
  `_common.py` helpers. Keep the existing 6 staleness tests green.
- UI: regenerate `dashboard.html` and load the control panel in the browser; verify both
  render, animate, and degrade with `prefers-reduced-motion`; confirm no external network
  requests (offline check).
- Full `hc sweep` smoke after the check-module refactor to confirm verdict parity.

## Rollout / order

1. Design tokens + SVG sprite + unified classifier (foundation).
2. Code fixes D1–D11 (with tests).
3. Refactors D12–D13 (with sweep parity check).
4. Dashboard restyle. 5. Control panel restyle. 6. Browser + offline verification.

## Risks

- Check-module refactor (D12) could change verdicts subtly → gated by a full-sweep parity check vs the pre-refactor `master_report.json`.
- `probe_auth` fix (D9) increases re-login frequency → expected; documented.
- Removing credential defaults (D8) could break dev checks if env/secrets file absent → mitigated by loading a gitignored secrets file and a clear startup error.
