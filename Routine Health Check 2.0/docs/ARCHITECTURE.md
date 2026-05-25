# Architecture

## Four auth surfaces

| Surface | Hosts | Persistent profile | Identity provider |
|---|---|---|---|
| Public | `www.myscheme.gov.in`, `aistore.myscheme.in`, `rules.myscheme.in`, `docs.myscheme.in`, 5 chatbot subdomains, `myapp.umangapp.in/` (landing/search only) | none — fresh contexts | n/a |
| Production (NeGD tenant) | `auth.myscheme.gov.in`, `govai.myscheme.in/national-e-governance-division/*`, `cms.myscheme.gov.in/national-e-governance-division/*`, `forms.myscheme.gov.in/national-e-governance-division/*` | `profiles/_browser_profile` | DigiLocker / MeriPehchaan OTP via `auth.myscheme.gov.in` |
| Dev environment | `dev`, `devgovai`, `devcms`, `devforms`, `devaistore` (all `*.myscheme.*`) | `profiles/_dev_browser_profile` | Two-tier: AWS Cognito perimeter + devauth/MeriPehchaan OTP |
| UMANG mirror | `myauth.umangapp.in`, `myapp.umangapp.in`, `mycms.umangapp.in`, `myforms.umangapp.in` | `profiles/_umang_browser_profile` | DigiLocker / MeriPehchaan OTP via `myauth.umangapp.in` (separate tenant; does **not** share cookies with prod) |

## Projects (`config/url_registry.json`)

Single source of truth for monitored URLs. Eleven projects today, each
carrying:

- A list of URLs, each tagged `environment: production | development`.
- A `spoc` (single point of contact) — `{name, email}`. Once filled in,
  per-project alert routing can be enabled on top of this.

Projects: **myScheme Portal**, **GovAI**, **AI Store**, **CMS**, **GovForms**,
**DoE / PSQ / Sandarbh / NMC / TATHYA (PIB) Chatbots** (one project each),
**UMANG Mirror**.

`hc liveness` and `hc sweep` both read this file; `hc dashboard` reads it
again for the per-project SPOC display.

## Artifacts (`artifacts/`)

- `master_report.json` — consolidated output from the last `hc sweep`.
- `*.png` — failure screenshots referenced by `master_report.json`.
- `liveness_state.json` / `liveness_latest.json` — `hc monitor liveness`
  state + most recent result.
- `sweep_state.json` — `hc monitor sweep` "previously healthy?" flag for
  the recovered-from-down email.

The whole directory is gitignored; v1's `_hc_artifacts/` is not copied
over — v2 starts fresh.

## Dispatcher model

`hc sweep` (`orchestration/master.py`) drives the show:

1. **Preflight** — for each tenant, headlessly probes the auth landing; if
   logged out, dispatches `hc login <tenant>` (which subprocess-runs the
   tenant's headed `auth/*_login.py` module).
2. **Liveness** — parallel `urllib.urlopen` against every URL in the
   registry (5-way thread pool, 10 s timeout).
3. **Functional checks** — `subprocess.run([python, "-m", module])` per
   row of the `SCRIPTS` table. Each check writes a single JSON object to
   stdout; the orchestrator parses the last balanced `{...}` block and
   stores it as the row's `payload`. If an authenticated check bounces to
   a sign-in surface, the orchestrator re-runs `hc login` for that tenant
   exactly once and retries; if it bounces again, the row is marked
   `AUTH_EXPIRED` (never `DOWN`, never emailed).

Subprocess isolation is intentional — a Playwright instance leak or
hang in one check cannot affect the others.
