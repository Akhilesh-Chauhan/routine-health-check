# myScheme / NeGD Synthetic Health Check Suite

Playwright-based health-check scripts for the National e-Governance Division (NeGD) portal family. Four surfaces are covered:

- **Public surface** — basic reachability of all 20 known URLs (no auth) and end-to-end functional checks of public flagship sites (`myscheme.gov.in`, `aistore.myscheme.in`, `rules.myscheme.in`, `docs.myscheme.in`).
- **Authenticated production surface** — internal workspace routes for the NeGD tenant on `govai.myscheme.in`, `cms.myscheme.gov.in`, and `forms.myscheme.gov.in`, accessed via a persistent Chromium profile holding live SSO cookies from `auth.myscheme.gov.in`.
- **Authenticated dev surface** — all `dev*` subdomains, gated by a two-tier auth model: an AWS **Cognito perimeter** (network gate) and a **devauth** user-identity layer (mirrors prod's MeriPehchaan OTP). Uses a separate persistent profile `_dev_browser_profile/`.
- **UMANG mirror surface** — `*.umangapp.in` hosts (`myapp`, `mycms`, `myforms`). Despite sharing the DigiLocker identity provider with prod, **UMANG runs its own OAuth ingress at `myauth.umangapp.in`** and does **not** share session cookies with `auth.myscheme.gov.in`. Treated as a third independent auth tenant with its own persistent profile `_umang_browser_profile/`.

All scripts are Python + Playwright sync API. Browser is `ms-playwright/chromium-1091` (headless except for the `*_manual_login.py` scripts).

## Files in this directory

| File | What it does |
|---|---|
| `Health Check.txt` | Original spec for the public liveness sweep. |
| **Orchestration / reporting** | |
| `url_registry.json` | **Single source of truth for monitored URLs** — organised by project; each URL tagged production/development; each project carries a SPOC slot. Add a new API/URL here. |
| `master_health_check.py` | **Start here.** Orchestrator — STEP 0 auth-login preflight, STEP 1 the liveness sweep, STEP 2 the 11 functional checks with automatic re-login + retry on any auth bounce. Writes `_hc_artifacts/master_report.json`. |
| `generate_dashboard.py` | Renders a self-contained `dashboard.html` (no server needed) from `master_report.json`. Failure screenshots for any DEGRADED/DOWN/KNOWN-ISSUE step are inlined as base64 and shown as click-to-enlarge thumbnails next to the error code/detail. |
| **Scheduled monitoring (cron)** | |
| `liveness_monitor.py` | Near-real-time tier — runs the URL liveness sweep (HTTP only), emails **only on state change**. Cron every 15 min. |
| `scheduled_sweep.py` | Heavy tier — runs the full sweep non-interactively + rebuilds the dashboard, emails on issues / recovery. Cron 3×/day. |
| `alerts.py` | Email-alert helper (SMTP, STARTTLS). `python3 alerts.py` self-checks SMTP login; `python3 alerts.py --send-test` sends a test mail. |
| `alert_config.json` | SMTP server / sender / recipients / `env_file` path for alerts. No secrets — credentials come from `env_file`. |
| **Public / production functional checks** | |
| `healthcheck_myscheme.py` | E2E functional test of `www.myscheme.gov.in` — Sign-In redirect → search → chatbot prompter reply. Headless, no auth. |
| `aistore_check.py` | Public marketplace at `aistore.myscheme.in` — load store, click a bot card, verify chat workspace renders. |
| `rules_engine_check.py` | Eligibility engine at `rules.myscheme.in` — click 'Check Eligibility' on first scheme, traverse the dynamic form selecting Yes for every question, submit, observe terminal state. |
| `docs_portal_check.py` | API doc portal at `docs.myscheme.in` — landing + 6 versioned API category pages (Accounts/Transactions/Search/Schemes/Forms/RAG Service). Docusaurus card layout detection. |
| **Production auth + workspace** | |
| `auth_precheck.py` | Loads the persistent profile, hits `https://auth.myscheme.gov.in/`, reports Scenario A (active session — should see "Welcome <name>!" + platform tiles) vs Scenario B (sign-in screen). |
| `manual_login.py` | Headed Chromium against `_browser_profile/`. Operator completes MeriPehchaan OTP login interactively. Auto-closes when post-login state is detected (or after 10 min). Run with `DISPLAY=:0`. |
| `govai_workspace_check.py` | Authenticated route checks for `govai.myscheme.in/national-e-governance-division/{,knowledge-bases,assistants,settings}`. |
| `cms_workspace_check.py`   | Authenticated route checks for `cms.myscheme.gov.in/national-e-governance-division/{dashboard,schemes,users,mailbox,profile}`. |
| `forms_workspace_check.py` | Authenticated route checks for `forms.myscheme.gov.in/national-e-governance-division/{dashboard,formlist,submissions,templates}`. |
| **Dev environment** | |
| `dev_manual_login.py` | Headed Chromium against `_dev_browser_profile/`. Auto-fills Cognito if it prompts (devadmin / Myscheme@3211), then operator completes the devauth/DigiLocker OTP login. Auto-closes on post-login. |
| `dev_environment_check.py` | Master check for all 5 dev subdomains (`dev`, `devgovai`, `devcms`, `devforms`, `devaistore`). Step 1 passes the Cognito perimeter, Step 2 runs prod-mirror checks per domain. |
| **UMANG mirror** | |
| `umang_manual_login.py` | Headed Chromium against `_umang_browser_profile/`. Entry point `https://myauth.umangapp.in/`. Operator completes a UMANG-side DigiLocker OTP login. Auto-closes on post-login. |
| `umang_integration_check.py` | Authenticated route checks for `myapp.umangapp.in`, `mycms.umangapp.in`, `myforms.umangapp.in`. Uses `_umang_browser_profile/`. |
| **Profiles / artifacts** | |
| `_browser_profile/`        | Persistent Chromium `user-data-dir` for **production**. Holds live SSO cookies. Treat as sensitive. |
| `_dev_browser_profile/`    | Persistent Chromium `user-data-dir` for **dev**. Holds Cognito perimeter cookie + devauth session cookies. Treat as sensitive. |
| `_umang_browser_profile/`  | Persistent Chromium `user-data-dir` for the **UMANG mirror**. Holds myauth.umangapp.in session cookies. Treat as sensitive. |
| `_hc_artifacts/`           | Run artifacts — failure screenshots, `master_report.json`, monitor logs, and alert-state files. |

## URL registry (projects)

`url_registry.json` is the **single source of truth** for every monitored URL. It is organised by **project** (11 today), each project carrying:

- a list of URLs, each tagged `environment: production | development`;
- a `spoc` (single point of contact) — `{name, email}`, currently blank.

`master_health_check.py` loads it for the liveness sweep; `generate_dashboard.py` reads it to group the dashboard's liveness section **by project** (with prod/dev badges + the project's SPOC). **To start monitoring a new API, add one entry here — nothing else changes.**

Projects: **myScheme Portal** (portal + dev + Rules Engine + API Docs), **GovAI**, **AI Store**, **CMS**, **GovForms**, the five domain chatbots (**DoE / PSQ / Sandarbh / NMC / TATHYA-PIB**, each its own project), and **UMANG Mirror**.

Once a project's `spoc.email` is filled in, that project's failure alerts can route to that person — per-SPOC email routing is the planned next step. Until then all alerts go to the `recipients` list in `alert_config.json`.

## How prod auth works (read this before touching anything)

1. **Cross-domain SSO.** All three internal portals (`govai`, `cms`, `forms`) trust session cookies set by `auth.myscheme.gov.in` after a MeriPehchaan / DigiLocker OAuth handshake. A single login propagates to all of them.
2. **The persistent profile is the credential.** `_browser_profile/Default/Cookies` (SQLite) holds:
   - `auth.myscheme.gov.in._session` — main session cookie, ~2-week TTL.
   - `connect.sid`, `_interaction*`, `digilocker.meripehchaan.gov.in.ci_session`, `.meripehchaan.gov.in.DLEPJP` — shorter-lived (30–60 min) supporting cookies that get refreshed on each visit.
3. **Re-authentication procedure** (when `auth_precheck.py` reports Scenario B):
   ```bash
   DISPLAY=:0 python3 manual_login.py
   ```
   A Chromium window opens on the user's display. The user completes OTP login. The script auto-closes when it detects the post-login state. Cookies persist to `_browser_profile/`.

   The auto-detect heuristic (`looks_logged_in` in `manual_login.py`) currently flags `auth.myscheme.gov.in/` itself as a sign-in surface — that's a **false negative** for the case where the post-login dashboard lives at exactly that URL. Workaround used in this session: send `SIGTERM` to the Chromium parent PID after the user signals login completion; cookies flush cleanly to disk. Consider refining the heuristic to recognize the "Welcome <name>! / Please choose a platform" state as logged-in (the dev variant `dev_manual_login.py` already does this — port it back).
4. **Cookie expiry watch.** As of the last successful prod login, `auth.myscheme.gov.in._session` was set to expire on **2026-06-01**. Re-run `manual_login.py` before that date or any post-expiry headless check will silently fall back to Scenario B.

## How dev auth works (two-tier model)

Every dev subdomain (`dev`, `devgovai`, `devcms`, `devforms`, `devaistore`) sits behind **two** independent auth layers. You must clear both before headless workspace checks pass.

1. **AWS Cognito perimeter** — first hit on any dev URL 302s to `myscheme.auth.ap-south-1.amazoncognito.com/login?client_id=6evh56qnt3r4ppu1mkmsbi1o6g&redirect_uri=...`. This is a **shared** client across all dev subdomains (one Cognito session unlocks all of them).
   - **Service credentials** (provided by the project): username `devadmin`, password `Myscheme@3211`. The `dev_environment_check.py` script reads them from env vars `DEV_COGNITO_USER` / `DEV_COGNITO_PASS` and falls back to those defaults.
   - **Form gotcha:** the page renders **two identical copies** of the form (a hidden Cognito ASF clone and the visible one). `page.locator("#signInFormUsername").first` picks the hidden one and times out. Use the `:visible` filter: `page.locator("input#signInFormUsername:visible").first`. Same for `#signInFormPassword` and `button[name=signInSubmitButton]`.
   - **Cognito session cookie TTL is ~60 min** by default — much shorter than the prod `_session` cookie. If you see a Cognito form in a previously-working dev run, that's expected: the script auto-re-fills credentials.
2. **devauth user identity** — once Cognito accepts the request, workspace apps (`devgovai`/`devcms`/`devforms`) then bounce *unauthenticated* users to `devauth.myscheme.gov.in` → DigiLocker MeriPehchaan OTP. Same pattern as prod, just with a dev OAuth client.
   - **Dev OAuth fingerprint:** `client_id=LOC6FDB0D3`, `state` values typically prefixed with `myschemeDev` or random tokens, `redirect_uri` callbacks point to `devauth.myscheme.gov.in/digilocker/signin/callback` (or `dev.myscheme.gov.in/api/auth/digilocker/callback` for the main portal).
   - **Note:** `devauth.myscheme.gov.in/` itself is **NOT** behind Cognito — you can hit its landing directly without the perimeter creds. Useful for triggering devauth login independently.
3. **Re-authentication procedure** (when dev workspace routes start bouncing to DigiLocker):
   ```bash
   DISPLAY=:0 python3 dev_manual_login.py
   ```
   Opens headed Chromium at `https://devauth.myscheme.gov.in/`. If Cognito prompts (cookies expired), the script auto-fills `devadmin` creds; operator then clicks "Already a user? → Meri Pehchaan" and completes OTP. Auto-closes on the post-login "Welcome <name>!" / "Please choose a platform to continue" page.

   The dev heuristic explicitly recognises the devauth post-login state, unlike the prod variant — so it closes cleanly without manual SIGTERM.
4. **Cookie expiry watch (dev).** Same ~2-week TTL on `devauth.myscheme.gov.in._session`. Re-login via `dev_manual_login.py` when it expires. The Cognito perimeter cookie (`6evh56qnt3r4ppu1mkmsbi1o6g`) refreshes silently on every run as long as the service credentials remain valid.

## How UMANG auth works (separate tenant, NOT a true SSO mirror)

Despite the spec language calling it a "shared DigiLocker/MeriPehchaan SSO session", the UMANG mirror is operationally a **separate auth tenant**. Empirical findings from the 2026-05-19 integration sweep:

1. **UMANG owns its own OAuth ingress at `myauth.umangapp.in`** — workspace bounces use `redirect_uri=https://myauth.umangapp.in/digilocker/signin/callback`, *not* `auth.myscheme.gov.in`. Browsers correctly isolate cookies between the two hosts, so the prod `_session` cookie cannot be presented to the UMANG side.
2. **Same OAuth client_id as prod** (`JN4A657B18`, `state=myscheme`, `app_name=bXlTY2hlbWU=`), but DigiLocker still presented the OTP login form rather than a consent skip — so cross-domain DigiLocker session reuse is also not working in practice. Two possible causes (for the platform team to confirm): the DigiLocker `ci_session` cookie has likely already expired (~30 min TTL), or DigiLocker treats `JN4A657B18 + redirect_uri=myauth.umangapp.in` as a distinct app context requiring re-consent.
3. **`myapp.umangapp.in` uses a different redirect host** than the CMS/Forms paths: `redirect_uri=https://myapp.umangapp.in/api/auth/digilocker/callback` (callback back to the app itself, matching the prod main-portal pattern). The CMS and Forms paths go through `myauth.umangapp.in` instead. Same OAuth client, different callback host.
4. **Re-authentication procedure for UMANG**:
   ```bash
   DISPLAY=:0 python3 umang_manual_login.py
   ```
   Opens headed Chromium at `https://myauth.umangapp.in/`. Operator clicks "Already a user? → Meri Pehchaan" and completes OTP. Auto-closes on the post-login "Welcome <name>! / Please choose a platform to continue" page (same UX as prod's `auth.myscheme.gov.in` and dev's `devauth.myscheme.gov.in`).
5. **Cookie expiry watch (UMANG).** The `myauth.umangapp.in` session cookie should have the same ~2-week TTL as the prod/dev `_session` cookies. Re-run `umang_manual_login.py` when `umang_integration_check.py` starts reporting DEGRADED OAuth bounces on workspace routes.
6. **Public surfaces don't require this login.** `myapp.umangapp.in/` landing and `/search` are public — they returned UP even before the UMANG manual login (search found 59 'student' matches, the catalog had `4630+ Total Schemes` vs prod's `3810+`, indicating a separate but live tenant database). Only the Sign-In click and the CMS/Forms workspace routes need the UMANG-side session.

## Running checks

All scripts must be run from this directory:

```bash
cd "/home/user/NeGD/Claude Code/Health Check"
```

### Recommended: one command does everything

```bash
python3 master_health_check.py     # OTP-login preflight -> full sweep -> consolidated report
python3 generate_dashboard.py      # rebuild dashboard.html from the latest master_report.json
```

`master_health_check.py` runs in three phases:

- **STEP 0 — Auth preflight (OTP login is the FIRST thing).** Probes each tenant's
  auth landing (`auth.myscheme.gov.in`, `devauth.myscheme.gov.in`,
  `myauth.umangapp.in`). For any tenant that is logged out it **pops up the headed
  manual-login window** so the operator completes the MeriPehchaan / DigiLocker OTP
  **once**. After that, every authenticated URL is reachable for the rest of the run.
- **STEP 1** — the 20-URL liveness sweep.
- **STEP 2** — the 11 functional checks. If an authenticated route still **bounces
  to a DigiLocker / MeriPehchaan sign-in surface**, it is **not** reported as DOWN —
  the orchestrator re-pops that tenant's login window, waits for the operator to
  re-authenticate, and retries the check once. Only if it *still* bounces after a
  fresh login is it surfaced as a failure (`DOWN (auth bounce persists after
  re-login)`).

The login pop-ups need a display — run under `DISPLAY=:0` if it is not already set.

### Running individual scripts

Do the OTP login(s) FIRST, then the checks:

```bash
# 1. OTP logins — headed, interactive, once per ~2-week session
DISPLAY=:0 python3 manual_login.py        # prod   -> _browser_profile/
DISPLAY=:0 python3 dev_manual_login.py    # dev    -> _dev_browser_profile/
DISPLAY=:0 python3 umang_manual_login.py  # UMANG  -> _umang_browser_profile/

# 2. Public checks — no auth needed
python3 healthcheck_myscheme.py
python3 aistore_check.py
python3 rules_engine_check.py
python3 docs_portal_check.py
python3 chatbot_endpoints_check.py

# 3. Authenticated checks
python3 auth_precheck.py                  # prod session canary
python3 govai_workspace_check.py
python3 cms_workspace_check.py
python3 forms_workspace_check.py
python3 dev_environment_check.py          # handles the Cognito gate inline
python3 umang_integration_check.py
```

Each script prints a single JSON report to stdout. Failures also save full-page screenshots to `_hc_artifacts/`.

## Scheduled monitoring (cron)

Two tiers run from this box's crontab (installed 2026-05-20; the older `Daily Health Check` cron is left untouched):

| Tier | Script | Schedule | Behaviour |
|---|---|---|---|
| Liveness | `liveness_monitor.py` | every 15 min (`*/15 * * * *`) | URL liveness sweep (HTTP only, no browser/auth). Emails **only when a URL goes DOWN** (or a previously-DOWN URL recovers) — SLOW is recorded but never emailed. Baseline state in `_hc_artifacts/liveness_state.json`. |
| Full sweep | `scheduled_sweep.py` | 10:00 / 14:00 / 18:00 IST (`0 10,14,18 * * *`) | Runs `master_health_check.py` non-interactively + rebuilds `dashboard.html`. Emails **only when a check or URL is DOWN**, and once when the last DOWN clears — DEGRADED/SLOW show on the dashboard but are not emailed. |

- **Email** goes through `alerts.py` + `alert_config.json`, reusing the SMTP account from `../Gov AI/Daily Health Check/.env` (`smtp.gmail.com`, STARTTLS). Recipients live in `alert_config.json`. Verify without sending: `python3 alerts.py`. Send a test: `python3 alerts.py --send-test`.
- **`HC_NONINTERACTIVE=1`** — set by `scheduled_sweep.py`; makes `master_health_check.py` skip the headed OTP-login pop-ups (cron can't complete an OTP). Expired sessions then surface as DEGRADED checks plus an "auth session expired" line naming the tenant + re-login command in the alert email.
- **Mass-down suppression.** If *every* URL reports DOWN in one cycle, that is the monitoring host's own network/DNS failing — not a real outage — so it is logged but **not emailed**, and the good baseline state is kept (no false "all recovered" afterwards).
- **Caveat — this box is not always-on.** Cron only fires while it is powered on; scheduled coverage has gaps whenever the machine is off. True 24/7 needs an always-on host.
- **Auth expiry is not an outage.** When an OTP session lapses (~2-week TTL), the affected checks are marked **`AUTH_EXPIRED`** (not DOWN) and are **never emailed** — an expired session does not mean the service is down. They show amber on the dashboard. Re-login with `DISPLAY=:0 python3 manual_login.py` (and the dev/umang variants) to clear them.

## Known selectors / page facts

Empirical findings from this session — useful when modifying scripts:

### Production

- **`www.myscheme.gov.in` Sign-In** is `button[aria-label="Sign In"]`. Click navigates the **same tab** (not a new tab) to `https://digilocker.meripehchaan.gov.in/signinv2/oauth_partner/...`. Don't use `context.expect_page()` — use `page.expect_navigation()`.
- **myscheme chatbot** launcher: `div#chatbot-button` on the parent page. The widget itself is an iframe `name="chatbot-iframe"`, src under `aistore.myscheme.in` (note: keyword `aistore` doesn't match a naive "chat/bot" iframe filter).
  - Prompter cards: `.conv-starter-item` (there are four).
  - Bot reply bubbles: `.markdownText`. Detection signal: count increases by ≥1 after clicking a prompter (typically within ~2–10 s).
  - **Known intermittent issue (already flagged to development):** the chatbot iframe sometimes loads blank or stays stuck on the govai loading screen. Workaround: click inside the chatbot window to force it to render. `healthcheck_myscheme.py` STEP 3 applies this click-to-load workaround automatically and records the condition as a non-failing `KNOWN-ISSUE` step status — it must **not** be reported as DEGRADED/DOWN and never degrades the E2E verdict.
- **`auth.myscheme.gov.in/` "Already a user?" — Meri Pehchaan** link is `a.indexButtons[href^='/oidc/v1/auth']`. The same page also has a Meri Pehchaan signup link with `href="javascript:void(0)"` higher up — don't confuse them.
- **AI Store cards** (`aistore.myscheme.in`) are clickable `div.bg-secondary-200` containers — not `<a>` tags. Naive `get_by_text(name)` clicks the inner H3 which doesn't always propagate the onclick. Use the container selector directly.
- **Rules engine** (`rules.myscheme.in`):
  - "Check Eligibility" buttons live in `td[2]` of each scheme row, in an initially-empty-looking `col-3` div. Text match `button:has-text('Check Eligibility')` works; the absolute xpath `/html/body/div/div/div/div[2]/table/tbody/tr[1]/td[2]/div/div[2]/div/button` also works for the first row. `locator(...).count()` returns 0 due to a render race even though `.first.click()` works — drop count gates, use `.wait_for(state="attached")` instead.
  - Form fields: questions use radio groups named `radio_multiple_root_<fieldName>`; each has Yes/No options. Settle ~3 s after each Yes click to let new conditional questions render.
  - Submit button: `button[type='submit']:has-text('Submit')`.
  - Known engine failure mode (as of 2026-05-19): submit returns a generic **"We're Sorry! Something went wrong, Please Try Again"** modal for all schemes tested — reproducible across ≥4 unrelated schemes, so flag as engine-wide, not data-specific.
- **Docs portal** (`docs.myscheme.in`, Docusaurus): category index pages don't have HTTP method tags; detect via `a.card, article.col` containers + `"\\d+ items?"` body regex. Method tags & `<pre>/<code>` only exist on **leaf** API ref pages.
- **Workspace app versions seen on last green run (prod):** govai `v-1.1.17`, CMS `v-2.4.2`, GovForms `1.2.0` (last updated 12/11/2025).

### Dev

- **Cognito form** (`myscheme.auth.ap-south-1.amazoncognito.com/login`):
  - Visible fields: `input#signInFormUsername:visible`, `input#signInFormPassword:visible`.
  - Submit: `button[name='signInSubmitButton']:visible, input[type=submit][name='signInSubmitButton']:visible`.
  - **Always filter to `:visible`** — the page contains a hidden Cognito ASF (Advanced Security Features) duplicate form.
- **Dev OAuth client ID** to recognize as "this is the dev flow, not prod": `LOC6FDB0D3`. Dev state strings often contain `myschemeDev`. The prod equivalent is `JN4A657B18`.
- **Dev Sign-In click on `dev.myscheme.gov.in`** can route to **any** of these (all valid):
  - `digilocker.meripehchaan.gov.in/signinv2/...` (OTP entry, fresh DigiLocker session)
  - `consent.digilocker.gov.in/consent-form?...` (consent step when DigiLocker session already exists — typical after `dev_manual_login.py` has run)
  - `devauth.myscheme.gov.in/...` (only on the very last redirect of the chain)
  Don't gate on `devauth.myscheme.gov.in` alone; accept any host in the OAuth chain or the dev client_id/state signals.
- **Authenticated-session UX twist:** `devgovai.myscheme.in/` and `devforms.myscheme.gov.in/` **auto-redirect** logged-in users straight to the workspace, skipping the marketing landing. As a result, the "Get Started" / "Build Now" CTAs do **not** render. Check: if `final_url.startswith(DEV_GOVAI_ORG)` (or `DEV_FORMS_DASHBOARD`), treat it as a pass — `dev_environment_check.py` already does this.
- **devauth `_interaction` post-login URL** looks like `https://devauth.myscheme.gov.in/interaction/<id>/organization/lists/<long-base64>` — useful as a positive signal that the OAuth callback completed.
- **Dev workspace versions seen on last green run:** devgovai `v-0.5.45`, devforms `0.4.130` (last updated 01/12/2025). All show a `"This is a development environment. Please visit Live Environment"` banner.

### UMANG mirror

- **OAuth ingress host:** `myauth.umangapp.in` (NOT `auth.myscheme.gov.in`). Workspace bounces use `redirect_uri=https://myauth.umangapp.in/digilocker/signin/callback`.
- **Main app callback** is different: `myapp.umangapp.in` uses `redirect_uri=https://myapp.umangapp.in/api/auth/digilocker/callback` (mirrors the prod main-portal pattern, callback back to the app host rather than via a separate auth ingress).
- **OAuth client_id:** `JN4A657B18` (same as prod main portal), `state=myscheme`, `app_name=bXlTY2hlbWU=`. DigiLocker treats this as a distinct app context anyway, so cross-domain session reuse from prod doesn't work in practice.
- **UMANG main-app catalog is a separate tenant database** from prod — the landing showed `4630+ Total Schemes` vs prod's `3810+`. Public search still works without auth.
- **DigiLocker bounce body fingerprint** (so you can recognize it in scripts): `"Sign In to your account via DigiLocker | Mobile | Username | Other ID | Forgot security PIN? | PIN less authentication | I consent to terms of use. | Sign In | New user? Sign up"`.

## Common pitfalls

- **F-string + Playwright selector quoting**: `f"...locator('a[href^={var}]').count()..."` breaks because the inner quotes collide. Use a separate variable: `sel = "a[href^='/oidc/v1/auth']"; page.locator(sel)`.
- **Bash heredocs with newlines** inside the `Bash` tool sometimes get concatenated when the harness joins lines — chain with `&&` or `;` explicitly, or use a single multi-line quoted string.
- **`page.expect_navigation` vs `context.expect_page`**: the former waits for the current page's URL to change; the latter waits for a new tab to be created. `myscheme.gov.in` Sign-In needs the former.
- **`auth.myscheme.gov.in/` / `devauth.myscheme.gov.in/` are ambiguous** — both the pre-login selector screen *and* the post-login platform-tile screen live at the same URL. Distinguish by body content (`"Welcome"` / `"choose a platform to continue"` = logged in; `"Already a user?"` / `"Sign up"` = logged out).
- **Duplicate forms on Cognito** — see Cognito section above. `:visible` filter is mandatory.
- **`.count() == 0` is not a reliable "element missing" check** — Playwright can return 0 even for elements that respond to `.first.click()` and `.evaluate()`. Seen on `rules.myscheme.in` and some Docusaurus pages. Use `.wait_for(state="attached"|"visible")` or just try the action and catch the failure.
- **Authenticated landing pages can skip onboarding CTAs.** Dev govai/forms auto-redirect past their "Get Started" / "Build Now" marketing screens when a session is present. Check the URL first; if already at the workspace, count it as success.
- **Network-idle timeouts** on these portals are sometimes slow (10–15 s). Don't shrink `wait_for_load_state("networkidle", timeout=...)` below 15 s.
- **Don't reuse the prod `_browser_profile/` for dev** (or vice versa). Each domain set has its own cookies and the two would collide / clobber each other on shared hosts like `digilocker.meripehchaan.gov.in`.
- **Scripts hardcode absolute paths rooted at this directory** (`/home/user/NeGD/Claude Code/Health Check/...`) for their profile dirs and `_hc_artifacts/`. If the project directory is moved, **every authenticated check silently fails** in a confusing way: `os.makedirs` recreates an empty profile at the stale path, Chromium launches logged-out, and all authenticated routes bounce to sign-in (looks like a session expiry / outage but is not). This actually happened on 2026-05-20 when the project moved into `Health Check/`. `master_health_check.py` and `generate_dashboard.py` resolve their root dynamically via `__file__`; the rest do not — after any move, re-point the hardcoded paths in every other script.

## Report shape

Every authenticated-check script emits JSON with this structure:

```json
{
  "target": "...",
  "tenant": "national-e-governance-division",
  "started_ist": "...",
  "steps": [
    {"name":"...", "url":"...", "final_url":"...", "http_status":200,
     "duration_ms":1234.5, "verdict":"UP|DEGRADED|DOWN",
     "detail":"...", "artifact":"path/to/screenshot or null",
     "body_excerpt":"first 240 chars"}
  ],
  "overall": "HEALTHY|DEGRADED ...|DOWN ...",
  "ended_ist": "..."
}
```

Verdicts:
- **UP**: HTTP 2xx/3xx, no auth-loop, expected content signal present.
- **DEGRADED**: loaded but content signal missing OR bounced to a sign-in surface.
- **DOWN**: 4xx/5xx, timeout, or Step-1-style hard failure that halts the script.
- **AUTH_EXPIRED**: an authenticated check bounced to a sign-in surface — the OTP session has lapsed. Treated as an auth problem, **not** a service outage: the orchestrator marks the script `AUTH_EXPIRED` (never DOWN) and the monitors never email it. Re-login to clear.

## Identity used during this build-out

- **Production operator:** Akhilesh Chauhan (`akhilesh.chauhan@digitalindia.gov.in`). Mobile masked as `******3541`. Confirmed via prod check on 2026-05-18 IST.
- **Dev operator:** Akhilesh Chauhan (same identity, separate dev session). Confirmed via dev check on 2026-05-19 IST.
- **UMANG operator:** UMANG-side session established 2026-05-20 IST (one-time OTP login completed via the master sweep's auth preflight/recovery). Session cookies now persist in `_umang_browser_profile/`; `umang_integration_check.py` runs HEALTHY against all three hosts.
- **Cognito service account (dev perimeter only):** `devadmin` / `Myscheme@3211`. This is *not* a user identity — it gates network access to dev hosts; user identity is still established via devauth/MeriPehchaan OTP afterwards.
- **Tenant slug** (all three environments): `national-e-governance-division`.
