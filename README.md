# Routine Health Check

Playwright-based synthetic health-check suite for the **NeGD myScheme portal family** — covering public surfaces, authenticated production workspaces, a dev environment, and a UMANG mirror tenant.

---

## Overview

The suite monitors four auth surfaces across 20+ URLs:

| Surface | Hosts | Auth method |
|---|---|---|
| **Public** | `www.myscheme.gov.in`, `aistore.myscheme.in`, `rules.myscheme.in`, `docs.myscheme.in` | None (headless) |
| **Production (NeGD tenant)** | `govai.myscheme.in`, `cms.myscheme.gov.in`, `forms.myscheme.gov.in` | MeriPehchaan / DigiLocker OTP via `auth.myscheme.gov.in` |
| **Dev environment** | `dev*` subdomains | Two-tier: AWS Cognito perimeter + devauth DigiLocker OTP |
| **UMANG mirror** | `myapp.umangapp.in`, `mycms.umangapp.in`, `myforms.umangapp.in` | Separate DigiLocker OAuth via `myauth.umangapp.in` |

Each check emits a structured JSON report. A consolidated HTML dashboard is generated from all reports.

---

## Repository Layout

```
Health Check/                  # v1 — original flat scripts
  master_health_check.py       # Orchestrator: auth preflight → liveness → 11 functional checks
  generate_dashboard.py        # Renders dashboard.html from master_report.json
  liveness_monitor.py          # Near-real-time HTTP sweep (cron every 15 min)
  scheduled_sweep.py           # Full sweep 3×/day (cron 10:00/14:00/18:00 IST)
  alerts.py                    # SMTP email alerts helper
  alert_config.json            # SMTP config (no secrets — credentials from env_file)
  url_registry.json            # Single source of truth for all monitored URLs
  healthcheck_myscheme.py      # Public E2E check: myscheme.gov.in
  aistore_check.py             # Public check: AI Store marketplace
  rules_engine_check.py        # Public check: Eligibility rules engine
  docs_portal_check.py         # Public check: API docs portal
  chatbot_endpoints_check.py   # Public check: domain chatbot endpoints
  auth_precheck.py             # Prod session canary (Scenario A vs B)
  auth_signin_click.py         # Auth sign-in click helper
  auth_click_meripehchaan.py   # MeriPehchaan link click helper
  manual_login.py              # Headed OTP login → _browser_profile/ (prod)
  govai_workspace_check.py     # Authenticated: GovAI workspace routes
  cms_workspace_check.py       # Authenticated: CMS workspace routes
  forms_workspace_check.py     # Authenticated: GovForms workspace routes
  dev_environment_check.py     # Authenticated: all 5 dev subdomains
  dev_manual_login.py          # Headed OTP login → _dev_browser_profile/ (dev)
  umang_integration_check.py   # Authenticated: UMANG mirror workspaces
  umang_manual_login.py        # Headed OTP login → _umang_browser_profile/ (UMANG)
  _browser_profile/            # Persistent Chromium profile — prod SSO cookies (sensitive)
  _dev_browser_profile/        # Persistent Chromium profile — dev cookies (sensitive)
  _umang_browser_profile/      # Persistent Chromium profile — UMANG cookies (sensitive)
  _hc_artifacts/               # Run outputs: master_report.json, screenshots, logs

Routine Health Check 2.0/      # v2 — proper Python package with `hc` CLI
  src/health_check/            # Package source
  config/                      # url_registry.json + alert_config.json
  docs/                        # Architecture, auth surfaces, pitfalls, cron docs
  profiles/                    # Symlinks → ../Health Check/ profile dirs
  pyproject.toml
  README.md                    # v2-specific install & usage guide
```

> **v2 is a repackaging of v1.** Identical checks, identical JSON output — but a proper Python package, a single `hc` CLI entry point, and no hardcoded absolute paths. New work should target v2.

---

## Quickstart (v1)

```bash
cd "Health Check"

# 1. Complete OTP logins (headed, once per ~2-week session)
DISPLAY=:0 python3 manual_login.py        # prod
DISPLAY=:0 python3 dev_manual_login.py    # dev
DISPLAY=:0 python3 umang_manual_login.py  # UMANG

# 2. Run the full sweep + rebuild the dashboard
python3 master_health_check.py
python3 generate_dashboard.py
```

## Quickstart (v2)

```bash
cd "Routine Health Check 2.0"
pip install -e .
playwright install chromium      # first time only

# Set up profile symlinks (one-time)
mkdir -p profiles
ln -s "../../Health Check/_browser_profile"        profiles/_browser_profile
ln -s "../../Health Check/_dev_browser_profile"    profiles/_dev_browser_profile
ln -s "../../Health Check/_umang_browser_profile"  profiles/_umang_browser_profile

# Run
hc sweep                          # full master sweep
hc dashboard                      # rebuild dashboard.html
hc liveness                       # HTTP-only URL sweep
hc login {prod|dev|umang}         # headed OTP login
hc check <name>                   # single functional check
```

Set `HC_NONINTERACTIVE=1` to suppress OTP pop-ups in cron/non-interactive mode.

---

## Scheduled Monitoring (Cron)

| Tier | Script | Schedule | Behaviour |
|---|---|---|---|
| **Liveness** | `liveness_monitor.py` | Every 15 min | HTTP sweep only. Emails on state change (UP↔DOWN). Suppresses alerts if every URL is down (host network failure). |
| **Full sweep** | `scheduled_sweep.py` | 10:00 / 14:00 / 18:00 IST | Full sweep + dashboard rebuild. Emails on check failures or recoveries. Skips OTP pop-ups (`HC_NONINTERACTIVE=1`). |

> **Note:** Cron only fires while the host machine is powered on. True 24/7 coverage requires an always-on server.

---

## Report Shape

Every check script emits JSON to stdout:

```json
{
  "target": "...",
  "tenant": "national-e-governance-division",
  "started_ist": "...",
  "steps": [
    {
      "name": "...",
      "url": "...",
      "final_url": "...",
      "http_status": 200,
      "duration_ms": 1234.5,
      "verdict": "UP|DEGRADED|DOWN|AUTH_EXPIRED",
      "detail": "...",
      "artifact": "path/to/screenshot or null",
      "body_excerpt": "first 240 chars"
    }
  ],
  "overall": "HEALTHY|DEGRADED ...|DOWN ...",
  "ended_ist": "..."
}
```

**Verdicts:**
- `UP` — HTTP 2xx/3xx, no auth-loop, expected content signal present.
- `DEGRADED` — loaded but content signal missing, or bounced to a sign-in surface.
- `DOWN` — 4xx/5xx, timeout, or hard failure that halts the script.
- `AUTH_EXPIRED` — authenticated check bounced to a sign-in surface (session lapsed). Treated as an auth issue, **not** a service outage. Never emailed.

---

## Auth & Session Management

### Production
- Sessions last ~2 weeks. Re-run `manual_login.py` before expiry.
- Session canary: `python3 auth_precheck.py` (Scenario A = logged in, Scenario B = logged out).

### Dev
- Two-tier: **AWS Cognito perimeter** (service creds: `devadmin` / read from env vars) + **devauth DigiLocker OTP** (operator-completed, ~2-week TTL).
- Re-run `dev_manual_login.py` when dev workspace routes start bouncing.

### UMANG
- Separate OAuth tenant at `myauth.umangapp.in` — independent from prod sessions.
- Re-run `umang_manual_login.py` when `umang_integration_check.py` starts seeing auth bounces.

---

## URL Registry

`url_registry.json` is the **single source of truth** for all monitored URLs. Add new URLs/APIs here. URLs are organised by project (11 projects), each tagged `production` or `development`, with a SPOC slot for alert routing.

---

## Tech Stack

- **Python 3** + **Playwright** (sync API, `ms-playwright/chromium`)
- **SMTP** (Gmail, STARTTLS) for alerts
- Zero external runtime dependencies beyond Playwright for v1; `pyproject.toml`-managed for v2

---

## Further Reading

- [`Health Check/CLAUDE.md`](Health%20Check/CLAUDE.md) — detailed auth mechanics, known selectors, cron config, common pitfalls.
- [`Routine Health Check 2.0/README.md`](Routine%20Health%20Check%202.0/README.md) — v2 install guide and CLI reference.
- [`Routine Health Check 2.0/docs/`](Routine%20Health%20Check%202.0/docs/) — architecture notes, auth surface deep-dives, empirical gotchas.
