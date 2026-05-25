# Known selectors / page facts / common pitfalls

Empirical findings from build-out of v1. All still apply unchanged in v2 —
selectors and gotchas are baked into the migrated check scripts.

## Production

- **`www.myscheme.gov.in` Sign-In** is `button[aria-label="Sign In"]`.
  Click navigates the **same tab** (not a new tab) to
  `https://digilocker.meripehchaan.gov.in/signinv2/oauth_partner/...`.
  Use `page.expect_navigation()`, not `context.expect_page()`.
- **myscheme chatbot** launcher: `div#chatbot-button` on the parent
  page. The widget itself is an iframe `name="chatbot-iframe"`, src
  under `aistore.myscheme.in` (keyword `aistore` doesn't match a naive
  "chat/bot" iframe filter).
  - Prompter cards: `.conv-starter-item` (four of them).
  - Bot reply bubbles: `.markdownText`. Detection signal: count
    increases by ≥1 after clicking a prompter (~2–10 s).
  - **Known intermittent issue (already flagged):** the chatbot iframe
    sometimes loads blank or stays stuck on the govai loading screen.
    Workaround: click inside the chatbot window to force render.
    `health_check.checks.public.myscheme` STEP 3 applies this click-to-
    load workaround automatically and records the condition as a non-
    failing `KNOWN-ISSUE` step status. Never report it as
    DEGRADED/DOWN; never degrades the E2E verdict.
- **`auth.myscheme.gov.in/` "Already a user? — Meri Pehchaan"** link is
  `a.indexButtons[href^='/oidc/v1/auth']`. The same page also has a
  Meri Pehchaan signup link with `href="javascript:void(0)"` higher up
  — don't confuse them.
- **AI Store cards** (`aistore.myscheme.in`) are clickable
  `div.bg-secondary-200` containers — not `<a>` tags. Naive
  `get_by_text(name)` clicks the inner H3 which doesn't always
  propagate the onclick. Use the container selector directly.
- **Rules engine** (`rules.myscheme.in`):
  - "Check Eligibility" buttons live in `td[2]` of each scheme row, in
    an initially-empty-looking `col-3` div. Text match
    `button:has-text('Check Eligibility')` works; absolute xpath
    `/html/body/div/div/div/div[2]/table/tbody/tr[1]/td[2]/div/div[2]/div/button`
    also works for the first row. `locator(...).count()` returns 0 due
    to a render race even though `.first.click()` works — drop count
    gates, use `.wait_for(state="attached")`.
  - Form fields: questions use radio groups named
    `radio_multiple_root_<fieldName>`; each has Yes/No. Settle ~3 s
    after each Yes click to let new conditional questions render.
  - Submit button: `button[type='submit']:has-text('Submit')`.
  - Known engine failure mode (2026-05-19): submit returns a generic
    **"We're Sorry! Something went wrong, Please Try Again"** modal for
    all schemes tested — reproducible across ≥4 unrelated schemes, so
    flag as engine-wide, not data-specific.
- **Docs portal** (`docs.myscheme.in`, Docusaurus): category index
  pages don't have HTTP method tags; detect via `a.card, article.col`
  containers + `"\\d+ items?"` body regex. Method tags & `<pre>/<code>`
  only exist on **leaf** API ref pages.
- **Workspace app versions seen on last green run (prod):** govai
  `v-1.1.17`, CMS `v-2.4.2`, GovForms `1.2.0` (12/11/2025).

## Dev

- **Cognito form** (`myscheme.auth.ap-south-1.amazoncognito.com/login`):
  - Visible fields: `input#signInFormUsername:visible`,
    `input#signInFormPassword:visible`.
  - Submit: `button[name='signInSubmitButton']:visible,
    input[type=submit][name='signInSubmitButton']:visible`.
  - **Always filter to `:visible`** — the page contains a hidden Cognito
    ASF (Advanced Security Features) duplicate form.
- **Dev OAuth client ID** to recognize "this is dev, not prod":
  `LOC6FDB0D3`. Dev state strings often contain `myschemeDev`. Prod
  equivalent: `JN4A657B18`.
- **Dev Sign-In click on `dev.myscheme.gov.in`** can route to **any** of
  these (all valid):
  - `digilocker.meripehchaan.gov.in/signinv2/...` (fresh OTP entry)
  - `consent.digilocker.gov.in/consent-form?...` (consent step when
    DigiLocker session already exists — typical after `hc login dev` ran)
  - `devauth.myscheme.gov.in/...` (only on the very last redirect)

  Don't gate on `devauth.myscheme.gov.in` alone; accept any host in the
  OAuth chain or the dev `client_id`/`state` signals.
- **Authenticated-session UX twist:** `devgovai.myscheme.in/` and
  `devforms.myscheme.gov.in/` **auto-redirect** logged-in users straight
  to the workspace, skipping the marketing landing. The "Get Started" /
  "Build Now" CTAs do **not** render. Check: if
  `final_url.startswith(DEV_GOVAI_ORG)` (or `DEV_FORMS_DASHBOARD`),
  treat it as a pass — `health_check.checks.dev.environment` already
  does this.
- **devauth `_interaction` post-login URL** looks like
  `https://devauth.myscheme.gov.in/interaction/<id>/organization/lists/<long-base64>`
  — positive signal that the OAuth callback completed.
- **Dev workspace versions seen on last green run:** devgovai
  `v-0.5.45`, devforms `0.4.130` (01/12/2025). All show a
  `"This is a development environment. Please visit Live Environment"` banner.

## UMANG mirror

- **OAuth ingress host:** `myauth.umangapp.in` (NOT
  `auth.myscheme.gov.in`). Workspace bounces use
  `redirect_uri=https://myauth.umangapp.in/digilocker/signin/callback`.
- **Main app callback** is different: `myapp.umangapp.in` uses
  `redirect_uri=https://myapp.umangapp.in/api/auth/digilocker/callback`
  (callback back to the app host, mirrors prod main-portal).
- **OAuth client_id:** `JN4A657B18` (same as prod main portal),
  `state=myscheme`, `app_name=bXlTY2hlbWU=`. DigiLocker treats this as a
  distinct app context anyway, so cross-domain session reuse doesn't work.
- **UMANG main-app catalog is a separate tenant database** from prod —
  the landing showed `4630+ Total Schemes` vs prod's `3810+`. Public
  search works without auth.
- **DigiLocker bounce body fingerprint:** `"Sign In to your account via
  DigiLocker | Mobile | Username | Other ID | Forgot security PIN? | PIN
  less authentication | I consent to terms of use. | Sign In | New user?
  Sign up"`.

## Common pitfalls (apply everywhere)

- **F-string + Playwright selector quoting**:
  `f"...locator('a[href^={var}]').count()..."` breaks because the inner
  quotes collide. Use a separate variable:
  `sel = "a[href^='/oidc/v1/auth']"; page.locator(sel)`.
- **`page.expect_navigation` vs `context.expect_page`**: the former
  waits for the current page's URL to change; the latter waits for a new
  tab. `myscheme.gov.in` Sign-In needs the former.
- **`auth.myscheme.gov.in/` / `devauth.myscheme.gov.in/` /
  `myauth.umangapp.in/` are ambiguous** — both the pre-login selector
  screen *and* the post-login platform-tile screen live at the same URL.
  Distinguish by body content (`"Welcome"` / `"choose a platform to
  continue"` = logged in; `"Already a user?"` / `"Sign up"` = logged
  out). v2 centralises this in `health_check.auth.heuristics.looks_logged_in`.
- **Duplicate forms on Cognito** — see Dev section above. `:visible` is
  mandatory.
- **`.count() == 0` is not a reliable "element missing" check** —
  Playwright can return 0 even for elements that respond to
  `.first.click()` and `.evaluate()`. Seen on `rules.myscheme.in` and
  some Docusaurus pages. Use `.wait_for(state="attached"|"visible")` or
  just try the action and catch the failure.
- **Authenticated landing pages can skip onboarding CTAs.** See the dev
  UX twist above.
- **Network-idle timeouts** on these portals are sometimes slow
  (10–15 s). Don't shrink `wait_for_load_state("networkidle", …)` below
  15 s.
- **Don't reuse profiles across tenants.** Each profile has its own
  cookies and the two would collide on shared hosts like
  `digilocker.meripehchaan.gov.in`. v2's symlinks enforce one-profile-
  per-tenant by name.
- **v1 footgun (fixed in v2):** v1 scripts hardcoded
  `/home/user/NeGD/Claude Code/Health Check/...` for profile and
  artifact dirs. Moving the project directory silently broke every
  authenticated check (`os.makedirs` recreated empty profile dirs at the
  stale path → Chromium launched logged-out → every authenticated route
  bounced to sign-in, looking like a session expiry). v2 routes every
  path through `health_check.paths`; the package itself is relocatable,
  and `paths.require_profile()` raises loudly if a profile symlink's
  target is missing.
