# Routine Health Check 2.0

Playwright-based synthetic health-check suite for the NeGD myScheme portal
family. v2 is a repackaging of `../Health Check/` (v1): identical checks,
identical JSON output, but a proper Python package, a single `hc` CLI, and
no hardcoded absolute paths.

Start here, not in v1. v1's `CLAUDE.md` covers the **same domain**
(auth flows, selectors, empirical gotchas) — read it once for that
background, but day-to-day work is in this tree.

## Run it

```bash
cd "Routine Health Check 2.0"
hc sweep             # auth preflight -> liveness -> 11 functional checks
hc dashboard         # rebuild artifacts/dashboard.html
hc liveness          # HTTP-only 20-URL sweep (no browser/auth)
hc login {prod|dev|umang}   # re-do an OTP login (~2-week TTL)
hc check <name>      # one check: myscheme|aistore|rules|docs|chatbots|auth|govai|cms|forms|devenv|umang
hc monitor {liveness|sweep} # cron entry points
hc alerts {selfcheck|test}  # SMTP wiring check / test email
hc serve             # web control panel — clickable buttons for every check, live SSE log,
                     # embedded dashboard link. Defaults to http://localhost:5050/.
```

The `serve` subcommand is the operator-friendly entry point — see
`src/health_check/web/` for the Flask app, runner, and frontend. Jobs
launched from the UI inherit `HC_NONINTERACTIVE=1` so an unattended
sweep won't pop OTP windows; use the "Login: prod/dev/umang" buttons
to refresh sessions explicitly.

Headed OTP pop-ups need `DISPLAY=:0`. Set `HC_NONINTERACTIVE=1` for cron.

## Layout

```
config/           url_registry.json (source of truth for URLs), alert_config.json
docs/             ARCHITECTURE.md, AUTH.md, PITFALLS.md, CRON.md  ← read these
profiles/         persistent Chromium profiles (symlinked to v1's _*_browser_profile/)
artifacts/        master_report.json, dashboard.html, failure screenshots, monitor state
src/health_check/
    cli.py          `hc` entry point (subcommand table at the top)
    paths.py        single source of truth for filesystem locations
    auth/           prod_login.py, dev_login.py, umang_login.py + heuristics.py
    browser/        shared Chromium launch helper
    checks/         public/  prod/  dev/  umang/  — one module per check
    orchestration/  master.py (sweep), dashboard.py, liveness_monitor.py,
                    scheduled_sweep.py, alerts.py
    reporting/      dataclasses for the consolidated report shape
    web/            Flask control panel (`hc serve`):
                      app.py        routes (/, /run, /events/<job>, /dashboard, /report, /status)
                      runner.py     one-job-at-a-time subprocess runner + SSE pubsub
                      projects.py   url_registry → CLI check mapping for project tiles
                      templates/    index.html
                      static/       app.js, style.css
```

## Where to look first

| If you need to… | Open |
|---|---|
| Understand the four auth surfaces, the dispatcher, parity with v1 | `docs/ARCHITECTURE.md` |
| Modify an auth flow (prod / dev Cognito+devauth / UMANG) | `docs/AUTH.md` + `src/health_check/auth/` |
| Add a URL to the liveness sweep / dashboard | `config/url_registry.json` (one entry — nothing else changes) |
| Debug a flaky selector / empirical site quirk | `docs/PITFALLS.md` (and v1's `CLAUDE.md` for older notes) |
| Touch cron tiers / email behaviour | `docs/CRON.md` + `src/health_check/orchestration/{liveness_monitor,scheduled_sweep,alerts}.py` |
| Add a new functional check | `src/health_check/checks/<surface>/<name>.py` + register in `cli.py` `CHECKS` table |

## Profiles (live SSO cookies — sensitive)

`profiles/` are **symlinks** into v1's `_*_browser_profile/` directories.
Treat them as credentials. If they're missing on a fresh checkout, set
them up once:

```bash
mkdir -p profiles
ln -s "../../Health Check/_browser_profile"       profiles/_browser_profile
ln -s "../../Health Check/_dev_browser_profile"   profiles/_dev_browser_profile
ln -s "../../Health Check/_umang_browser_profile" profiles/_umang_browser_profile
```

If v1 has never been run on this machine either, do the OTP login from
v2 (`hc login prod`, then `dev`, then `umang`) to populate the targets.

## Report shape

`artifacts/master_report.json` is the consolidated output of `hc sweep`.
Schema matches v1 exactly — see v1's `CLAUDE.md` "Report shape" section.
Verdicts: `UP | DEGRADED | DOWN | AUTH_EXPIRED | KNOWN-ISSUE`.

## Parity status (as of 2026-05-26)

v2 is on branch `feat/v2-heavy-refactor`. The intent is full output
parity with v1 before merge — diff `master_report.json` between the two
trees when validating. v1 lives at `../Health Check/` and remains the
production cron target until v2 is cut over.

Parity confirmed on 2026-05-26: zero diffs across 17/3 UP/DOWN liveness,
all 11 functional verdicts, and the auth preflight.

## Known workspace-session symptom: full profile wipe, not just `hc login`

When a workspace check bounces to a URL like
`auth.myscheme.gov.in/oidc/v1/session/end?id_token_hint=...&post_logout_redirect_uri=https://<app>/logout`
**and** the body excerpt says
`"Auth | Sign out | Do you want to sign-out from <App>? | Yes | No"`, the
fingerprint is "workspace app rejecting the session". The
`id_token_hint` JWT's `iat` claim will be fresh (seconds old) — a
freshly authenticated user being asked to sign out is the giveaway.

**The fix is a full profile wipe + fresh OTP, not just `hc login`.**
Plain `hc login` refreshes OP-side cookies in the existing profile but
leaves workspace-side state (cookies / localStorage / IndexedDB) intact —
and that's what triggers the apps' logout flow.

Recovery procedure:

```bash
cd "../Health Check"
mv _browser_profile      _browser_profile.bak_$(date +%F)
mv _dev_browser_profile  _dev_browser_profile.bak_$(date +%F)
mkdir _browser_profile _dev_browser_profile  # Playwright can't mkdir through a dangling symlink
cd "../Routine Health Check 2.0"
DISPLAY=:0 hc login prod
DISPLAY=:0 hc login dev
hc check cms && hc check govai && hc check forms && hc check devenv
```

Expect the headed Chromium to show the full DigiLocker OTP screen and a
consent step (no warm cookies). The orchestrator's `AUTH_EXPIRED` label
on these rows is *technically* correct — there is no usable session for
the workspace tier — but the cause is profile-side, not auth-tier.

First observed 2026-05-26 across prod govai/cms/forms + dev
devgovai/devcms/devforms simultaneously. Initial diagnosis blamed the
workspace-app backend; the wipe-and-relogin procedure cleared all six
to HEALTHY. Both backends were fine the whole time.
