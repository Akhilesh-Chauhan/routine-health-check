# Routine Health Check 2.0

Playwright-based synthetic health-check suite for the NeGD myScheme portal
family, covering four auth surfaces:

- **Public** — reachability + functional E2E on the public flagships.
- **Production (NeGD tenant)** — internal workspaces on `govai`, `cms`,
  `forms` behind `auth.myscheme.gov.in` SSO.
- **Dev environment** — `dev*` subdomains behind a two-tier Cognito +
  devauth gate.
- **UMANG mirror** — `*.umangapp.in` workspaces behind their own DigiLocker
  OAuth ingress at `myauth.umangapp.in`.

v2 is a repackaging of v1 (`../Health Check/`): identical checks, identical
JSON output, but a proper Python package, a single `hc` CLI, and no
hardcoded absolute paths.

## Install

```bash
cd "Routine Health Check 2.0"
pip install -e .
playwright install chromium     # first time only
```

### One-time profile bootstrap

The persistent Chromium profiles (which hold the live SSO cookies) are
**not** in the repo — they're per-operator. Set up symlinks pointing at
v1's profile dirs once:

```bash
mkdir -p profiles
ln -s "../../Health Check/_browser_profile"        profiles/_browser_profile
ln -s "../../Health Check/_dev_browser_profile"    profiles/_dev_browser_profile
ln -s "../../Health Check/_umang_browser_profile"  profiles/_umang_browser_profile
```

If v1's profiles don't exist yet, complete the OTP login in v1 first
(`cd "../Health Check" && DISPLAY=:0 python3 manual_login.py` etc.) —
that's what creates the profile directories. Then the symlinks
auto-resolve. `hc login {prod|dev|umang}` works against v2's symlinks
once the targets exist.

## Common commands

```bash
hc sweep                    # full master check (auth preflight + liveness + 11 functional checks)
hc dashboard                # rebuild dashboard.html from the latest master_report.json
hc liveness                 # 20-URL HTTP sweep only (no browser, no auth)
hc login {prod|dev|umang}   # headed OTP login for one tenant — re-run when the ~2-week session expires
hc check <name>             # run one functional check (myscheme/aistore/rules/docs/chatbots/auth/govai/cms/forms/devenv/umang)
hc monitor {liveness|sweep} # cron entry points
hc alerts {selfcheck|test}  # SMTP connectivity check / send-test
hc serve                    # web control panel at http://localhost:5050/
```

Set `HC_NONINTERACTIVE=1` to disable the headed OTP pop-ups (cron mode).

## Layout

```
config/               url_registry.json + alert_config.json
docs/                 architecture / auth / pitfalls / cron docs
profiles/             persistent Chromium profiles (symlinks → ../Health Check/)
artifacts/            run outputs: master_report.json, screenshots, monitor state
src/health_check/
    paths.py          single source of truth for filesystem locations
    logging.py        stdlib logger setup
    cli.py            `hc` entry point
    browser/          shared Chromium launch helper
    auth/             OTP login scripts (prod/dev/umang) + shared heuristics
    checks/           public/ prod/ dev/ umang/ functional checks
    orchestration/    master sweep, dashboard, liveness monitor, scheduled sweep, alerts
    reporting/        dataclasses for the consolidated report
    web/              Flask control panel served by `hc serve`
```

See `docs/` for deeper notes on each auth surface, known selectors, the
empirical gotchas, and cron tier behaviour.
