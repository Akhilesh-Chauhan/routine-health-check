# Auth surfaces

Three independent persistent profiles, one per tenant. All three are
symlinks under `profiles/` pointing at the corresponding directory in
v1 (`../../Health Check/_*_browser_profile`), so a re-login in v1 or v2
benefits the other automatically.

## Production (`auth.myscheme.gov.in`)

1. **Cross-domain SSO** — `govai`, `cms`, `forms` all trust session
   cookies set by `auth.myscheme.gov.in` after a MeriPehchaan / DigiLocker
   OAuth handshake. One login propagates to all three.
2. **The persistent profile is the credential.**
   `profiles/_browser_profile/Default/Cookies` holds:
   - `auth.myscheme.gov.in._session` — ~2-week TTL.
   - `connect.sid`, `_interaction*`, `digilocker.meripehchaan.gov.in.ci_session`,
     `.meripehchaan.gov.in.DLEPJP` — 30–60 min, refreshed on each visit.
3. **Re-login:** `DISPLAY=:0 hc login prod`. Chromium opens on the user's
   display; OTP is completed manually; the script auto-closes once the
   post-login state ("Welcome <name>! / Please choose a platform to
   continue") is detected.
4. **Cookie expiry watch.** As of the last successful prod login,
   `auth.myscheme.gov.in._session` was set to expire **2026-06-01**.
   Re-run `hc login prod` before then or any post-expiry headless check
   silently falls back to the sign-in surface.

## Dev environment (two-tier)

Every dev subdomain sits behind **two** independent auth layers; both must
pass for a headless workspace check to succeed.

1. **AWS Cognito perimeter** — first hit on any dev URL 302s to
   `myscheme.auth.ap-south-1.amazoncognito.com/login?client_id=6evh56qnt3r4ppu1mkmsbi1o6g&redirect_uri=...`.
   Shared client across all dev subdomains.
   - **Service credentials** (provided by the project): `devadmin` /
     `Myscheme@3211`. `health_check.checks.dev.environment` reads them
     from `DEV_COGNITO_USER` / `DEV_COGNITO_PASS` and falls back to those
     defaults.
   - **Form gotcha:** the page renders **two identical copies** of the
     form (a hidden Cognito ASF clone and the visible one). Use the
     `:visible` filter on `#signInFormUsername`, `#signInFormPassword`,
     and `button[name=signInSubmitButton]`.
   - **Cognito session TTL ≈ 60 min.**
2. **devauth user identity** — once Cognito accepts, workspace apps bounce
   *unauthenticated* users to `devauth.myscheme.gov.in` → DigiLocker
   MeriPehchaan OTP. Same flow as prod, dev OAuth client `LOC6FDB0D3`,
   state strings typically prefixed `myschemeDev`.
   - `devauth.myscheme.gov.in/` itself is **not** behind Cognito — you
     can hit its landing without the perimeter creds, useful for
     triggering devauth login independently.
3. **Re-login:** `DISPLAY=:0 hc login dev`. If Cognito prompts, the
   script auto-fills the service creds; the operator completes OTP. Auto-
   closes on the post-login devauth dashboard.
4. **Cookie expiry watch.** Same ~2-week TTL on
   `devauth.myscheme.gov.in._session`. The Cognito perimeter cookie
   refreshes silently on every run while the service creds remain valid.

## UMANG mirror (separate auth tenant)

Despite spec language calling it a "shared DigiLocker SSO session", UMANG
is operationally a **separate auth tenant**.

1. **Own OAuth ingress at `myauth.umangapp.in`.** Workspace bounces use
   `redirect_uri=https://myauth.umangapp.in/digilocker/signin/callback`,
   *not* `auth.myscheme.gov.in`. Browsers correctly isolate cookies, so
   the prod `_session` cookie cannot be presented to UMANG.
2. **Same OAuth client_id as prod** (`JN4A657B18`, `state=myscheme`,
   `app_name=bXlTY2hlbWU=`), but DigiLocker still presents the OTP form
   rather than a consent-skip — cross-domain DigiLocker session reuse
   doesn't work in practice.
3. **`myapp.umangapp.in` uses a different callback host**:
   `redirect_uri=https://myapp.umangapp.in/api/auth/digilocker/callback`
   (matches the prod main-portal pattern). CMS/Forms paths go through
   `myauth.umangapp.in` instead.
4. **Re-login:** `DISPLAY=:0 hc login umang`. Operator clicks "Already a
   user? → Meri Pehchaan", completes OTP, script auto-closes on the
   post-login dashboard.
5. **Cookie expiry watch.** Same ~2-week TTL. Re-run `hc login umang`
   when `hc check umang` starts reporting DEGRADED OAuth bounces.
6. **Public surfaces don't require this login.** `myapp.umangapp.in/`
   landing and `/search` are public; only Sign-In click + CMS/Forms
   workspace routes need the UMANG-side session.
