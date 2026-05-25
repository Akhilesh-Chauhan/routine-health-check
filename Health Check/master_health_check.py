"""Master health-check orchestrator — runs every check script in this directory
sequentially and produces a single consolidated JSON + Markdown summary.

Run from the project directory:
    python3 master_health_check.py
"""
import json
import os
import re
import subprocess
import sys
import time
import concurrent.futures
from datetime import datetime, timezone, timedelta
from urllib import request as urlreq, error as urlerr

HERE = os.path.dirname(os.path.abspath(__file__))
IST  = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Monitored URLs come from url_registry.json — the single source of truth,
# organised by project. Add a new API/URL by editing that file. The loader
# flattens it to a list of {label, url, project, environment} entries.
# ---------------------------------------------------------------------------
def _load_url_registry():
    path = os.path.join(HERE, "url_registry.json")
    try:
        with open(path) as f:
            reg = json.load(f)
    except Exception as e:
        print(f"[warn] could not load url_registry.json: {e}", flush=True)
        return []
    entries = []
    for proj in reg.get("projects", []):
        pname = proj.get("name", "Other")
        for u in proj.get("urls", []):
            entries.append({
                "label": u.get("label", u.get("url", "")),
                "url": u["url"],
                "project": pname,
                "environment": u.get("environment", "production"),
            })
    return entries


LIVENESS_URLS = _load_url_registry()

# (group label, script filename, default timeout seconds)
SCRIPTS = [
    ("Public — myscheme.gov.in E2E", "healthcheck_myscheme.py",       240),
    ("Public — aistore marketplace",  "aistore_check.py",              120),
    ("Public — rules engine",         "rules_engine_check.py",         180),
    ("Public — docs portal",          "docs_portal_check.py",          180),
    ("Public — 6 standalone bots",    "chatbot_endpoints_check.py",    600),
    ("Prod auth precheck",            "auth_precheck.py",               60),
    ("Prod — govai workspace",        "govai_workspace_check.py",      180),
    ("Prod — cms workspace",          "cms_workspace_check.py",        180),
    ("Prod — forms workspace",        "forms_workspace_check.py",      180),
    ("Dev environment full sweep",    "dev_environment_check.py",      600),
    ("UMANG integration",             "umang_integration_check.py",    600),
]

# ---------------------------------------------------------------------------
# Auth handling — OTP login runs FIRST (preflight), and any authenticated
# route that bounces to a sign-in surface triggers a re-login + one retry
# instead of being reported as DOWN.
# ---------------------------------------------------------------------------
# Each auth tenant: persistent profile dir, an auth-landing URL to probe for a
# live session, and the headed manual-login script to pop up when it is missing.
TENANTS = {
    "prod":  {"profile": "_browser_profile",
              "probe":   "https://auth.myscheme.gov.in/",
              "login":   "manual_login.py"},
    "dev":   {"profile": "_dev_browser_profile",
              "probe":   "https://devauth.myscheme.gov.in/",
              "login":   "dev_manual_login.py"},
    "umang": {"profile": "_umang_browser_profile",
              "probe":   "https://myauth.umangapp.in/",
              "login":   "umang_manual_login.py"},
}

# Which check script belongs to which auth tenant (for reactive re-login).
SCRIPT_TENANT = {
    "auth_precheck.py":           "prod",
    "govai_workspace_check.py":   "prod",
    "cms_workspace_check.py":     "prod",
    "forms_workspace_check.py":   "prod",
    "dev_environment_check.py":   "dev",
    "umang_integration_check.py": "umang",
}

# Body text that means "this is a sign-in surface — not logged in".
LOGGED_OUT_SIGNALS = [
    "already a user", "new user? sign up", "enter mobile", "send otp",
    "enter otp", "sign in to your account", "security pin",
]
# Body text that means a live session IS present — the post-login platform
# picker ("Welcome <name>! / Please choose a platform to continue / Sign Out").
AUTHED_SIGNALS = [
    "please choose a platform to continue", "sign out",
]
# Hosts / path fragments that mean a URL is a sign-in surface, not a workspace.
SIGNIN_HOSTS = [
    "digilocker.meripehchaan.gov.in", "consent.digilocker.gov.in",
    "myauth.umangapp.in", "/oidc/v1/auth",
]


def probe_auth(tenant):
    """Headless probe of a tenant's auth landing.
    Returns 'AUTHED' | 'LOGGED_OUT' | 'ERROR: ...'."""
    cfg = TENANTS[tenant]
    profile = os.path.join(HERE, cfg["profile"])
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return f"ERROR: playwright unavailable ({e})"
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                profile, headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
                viewport={"width": 1366, "height": 900},
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(cfg["probe"], wait_until="domcontentloaded", timeout=30_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10_000)
                except Exception:
                    pass
                # The auth landing is a SPA: it can briefly flash the sign-in
                # surface before the session check resolves into the post-login
                # "Welcome <name>! / Please choose a platform to continue" page.
                # Poll until a definitive signal appears — a positive (logged-in)
                # signal is authoritative and wins over a transient sign-in flash.
                authed = False
                logged_out = False
                for _ in range(7):
                    time.sleep(2)
                    url = (page.url or "").lower()
                    body = (page.evaluate(
                        "() => (document.body && document.body.innerText) || ''") or "")[:4000].lower()
                    if any(s in body for s in AUTHED_SIGNALS):
                        authed = True
                        break
                    logged_out = ("digilocker" in url
                                  or any(s in body for s in LOGGED_OUT_SIGNALS))
            finally:
                ctx.close()
        if authed:
            return "AUTHED"
        return "LOGGED_OUT" if logged_out else "AUTHED"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


def run_login(tenant, reason=""):
    """Pop up the tenant's headed manual-login script. Blocks until the operator
    completes the OTP login (script auto-closes on success) or it times out."""
    cfg = TENANTS[tenant]
    login = os.path.join(HERE, cfg["login"])
    if os.environ.get("HC_NONINTERACTIVE"):
        # Unattended (cron) run — never pop up a headed browser nobody can see.
        print(f"[AUTH] {tenant.upper()} needs a manual OTP login {reason} — skipped "
              f"(HC_NONINTERACTIVE set). Run interactively: "
              f"DISPLAY=:0 python3 {cfg['login']}", flush=True)
        return False
    print("\n" + "!" * 78, flush=True)
    print(f"[AUTH] {tenant.upper()} needs a manual OTP login. {reason}".rstrip(), flush=True)
    print(f"[AUTH] Opening {cfg['login']} — a Chromium window will appear on the display.", flush=True)
    print(f"[AUTH] >>> Complete the MeriPehchaan / DigiLocker OTP login in that window. <<<", flush=True)
    print(f"[AUTH] The window auto-closes once login is detected (up to ~10 min).", flush=True)
    print("!" * 78, flush=True)
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    try:
        proc = subprocess.run(["python3", login], cwd=HERE, env=env,
                              timeout=780, capture_output=True, text=True)
        ok = proc.returncode == 0
        print(f"[AUTH] {tenant} login script exited "
              f"({'ok' if ok else 'code ' + str(proc.returncode)}).", flush=True)
        return ok
    except subprocess.TimeoutExpired:
        print(f"[AUTH] {tenant} login timed out — no OTP completed.", flush=True)
        return False
    except Exception as e:
        print(f"[AUTH] {tenant} login error: {type(e).__name__}: {e}", flush=True)
        return False


def detect_bounce(payload):
    """True only if a *failed* authenticated route landed on a sign-in surface.

    Deliberate 'Sign In click' test steps (which are supposed to reach DigiLocker)
    and any UP step are ignored — only a DEGRADED/DOWN workspace route that ends
    on a sign-in host counts as a real auth bounce worth re-logging in for."""
    if not payload:
        return False

    def is_bounced_step(d):
        if str(d.get("verdict", "")).upper() not in ("DEGRADED", "DOWN"):
            return False
        name = str(d.get("name", "")).lower()
        if "sign in" in name or "signin" in name:    # step is meant to hit sign-in
            return False
        final_url = str(d.get("final_url") or "").lower()
        detail = str(d.get("detail") or "").lower()
        if any(h in final_url for h in SIGNIN_HOSTS):
            return True
        return "bounced to" in detail and "sign-in" in detail

    def walk(o):
        if isinstance(o, dict):
            return is_bounced_step(o) or any(walk(v) for v in o.values())
        if isinstance(o, list):
            return any(walk(v) for v in o)
        return False

    return walk(payload)


def auth_preflight():
    """STEP 0 — before any checks run, make sure every auth tenant has a live
    session. Pop up a manual OTP login for any tenant that is logged out."""
    print("\n=== STEP 0: Auth preflight (OTP login first) ===", flush=True)
    status = {}
    for tenant in ("prod", "dev", "umang"):
        st = probe_auth(tenant)
        print(f"  [{tenant:5s}] session: {st}", flush=True)
        if st == "LOGGED_OUT":
            run_login(tenant, reason="(preflight — no active session)")
            st = probe_auth(tenant)
            print(f"  [{tenant:5s}] after login: {st}", flush=True)
        status[tenant] = st
    return status


def hit_url(entry):
    """One-shot GET liveness check via urllib (10s timeout). `entry` is a
    {label,url,project,environment} dict from the URL registry."""
    meta = {"label": entry["label"], "url": entry["url"],
            "project": entry.get("project", "Other"),
            "environment": entry.get("environment", "production")}
    t0 = time.perf_counter()
    try:
        req = urlreq.Request(entry["url"], headers={"User-Agent": "healthcheck/1.0"})
        with urlreq.urlopen(req, timeout=10) as resp:
            code = resp.status
        ms = (time.perf_counter() - t0)*1000
        verdict = "UP" if code < 400 and ms < 4000 else ("SLOW" if code < 400 else "DOWN")
        return {**meta, "status": verdict, "http": code, "ms": round(ms,1), "err": None}
    except urlerr.HTTPError as e:
        ms = (time.perf_counter() - t0)*1000
        return {**meta, "status": "DOWN", "http": e.code, "ms": round(ms,1), "err": str(e)}
    except Exception as e:
        ms = (time.perf_counter() - t0)*1000
        return {**meta, "status": "DOWN", "http": None, "ms": round(ms,1),
                "err": f"{type(e).__name__}: {e}"}

def liveness_sweep():
    """Run the public liveness sweep in parallel batches of 5."""
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(hit_url, e) for e in LIVENESS_URLS]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())
    order = {e["url"]: i for i, e in enumerate(LIVENESS_URLS)}
    results.sort(key=lambda r: order.get(r["url"], 999))  # preserve registry order
    counts = {"UP":0,"SLOW":0,"DOWN":0}
    for r in results: counts[r["status"]] = counts.get(r["status"],0)+1
    return {"results": results, "counts": counts}

def extract_json_payload(stdout):
    """Find the last JSON object in stdout text. Returns None if not parseable."""
    # Find the last `{` that starts a balanced JSON object up to the last `}`.
    last_close = stdout.rfind("}")
    if last_close < 0:
        return None
    depth = 0
    start = None
    for i in range(last_close, -1, -1):
        ch = stdout[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            depth -= 1
            if depth == 0:
                start = i
                break
    if start is None:
        return None
    try:
        return json.loads(stdout[start:last_close+1])
    except Exception:
        return None

def run_script(label, filename, timeout_s):
    path = os.path.join(HERE, filename)
    if not os.path.exists(path):
        return {"label": label, "filename": filename, "verdict": "MISSING",
                "detail": "Script not found", "duration_s": 0.0}
    t0 = time.perf_counter()
    print(f"\n[run] {label}  ({filename}, timeout={timeout_s}s)", flush=True)
    try:
        proc = subprocess.run(
            ["python3", path], cwd=HERE,
            capture_output=True, text=True, timeout=timeout_s,
        )
        elapsed = round(time.perf_counter() - t0, 1)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        payload = extract_json_payload(stdout)
        result = {
            "label": label, "filename": filename,
            "duration_s": elapsed, "exit_code": proc.returncode,
            "payload": payload, "stderr_tail": stderr[-400:] if stderr else "",
        }
        # Decide verdict by inspecting payload fields when present
        verdict = None
        if payload:
            if "overall" in payload:
                verdict = str(payload["overall"])
            elif "verdict" in payload:
                verdict = str(payload["verdict"])
            elif "bots" in payload:
                # chatbot_endpoints_check style
                bot_verdicts = [b.get("verdict","?") for b in payload.get("bots",[])]
                if all(v == "UP" for v in bot_verdicts): verdict = "HEALTHY"
                elif any(v == "DOWN" for v in bot_verdicts): verdict = "DEGRADED (some bots DOWN)"
                else: verdict = "DEGRADED"
            elif "steps" in payload:
                step_verdicts = [s.get("verdict","?") for s in payload.get("steps",[])]
                if all(v == "UP" for v in step_verdicts): verdict = "HEALTHY"
                elif any(v == "DOWN" for v in step_verdicts): verdict = "DOWN"
                else: verdict = "DEGRADED"
        if verdict is None:
            verdict = "PASSED" if proc.returncode == 0 else "FAILED"
        result["verdict"] = verdict
        print(f"[done] {label}  -> {verdict}  ({elapsed}s)", flush=True)
        return result
    except subprocess.TimeoutExpired:
        elapsed = round(time.perf_counter() - t0, 1)
        print(f"[TIMEOUT] {label} exceeded {timeout_s}s", flush=True)
        return {"label": label, "filename": filename,
                "duration_s": elapsed, "exit_code": None,
                "verdict": "TIMEOUT", "detail": f"Exceeded {timeout_s}s"}
    except Exception as e:
        elapsed = round(time.perf_counter() - t0, 1)
        return {"label": label, "filename": filename,
                "duration_s": elapsed, "exit_code": None,
                "verdict": "ERROR", "detail": f"{type(e).__name__}: {e}"}

def severity_emoji(v):
    if v is None: return "?"
    s = v.upper()
    if "HEALTHY" in s or s in ("UP","PASSED"): return "✅"
    if "AUTH_EXPIRED" in s: return "🔑"
    if "TIMEOUT" in s or "ERROR" in s or "MISSING" in s: return "❌"
    if "DOWN" in s and "DEGRADED" not in s: return "❌"
    if "DEGRADED" in s: return "⚠️"
    if "DOWN" in s: return "❌"
    return "•"

def main():
    started = datetime.now(IST)
    overall = {"started_ist": started.isoformat(timespec="seconds"),
               "auth_preflight": None, "liveness": None, "scripts": []}

    # 0) Auth preflight — OTP logins happen FIRST, before any checks run.
    overall["auth_preflight"] = auth_preflight()

    # 1) Public liveness sweep
    print(f"\n=== STEP 1: {len(LIVENESS_URLS)}-URL liveness sweep ===", flush=True)
    overall["liveness"] = liveness_sweep()
    print(f"Liveness counts: {overall['liveness']['counts']}", flush=True)

    # 2) Functional scripts (sequential). If an authenticated check bounces to a
    #    sign-in surface, re-login and retry once instead of reporting DOWN.
    print("\n=== STEP 2: Functional checks ===", flush=True)
    relogged = set()
    for label, fn, to in SCRIPTS:
        result = run_script(label, fn, to)
        tenant = SCRIPT_TENANT.get(fn)
        if tenant and detect_bounce(result.get("payload")):
            # Bounced to a sign-in surface. The first time a given tenant
            # bounces, attempt a re-login and one retry.
            if tenant not in relogged:
                relogged.add(tenant)
                print(f"[AUTH] {label} bounced to a sign-in surface — "
                      f"attempting re-login.", flush=True)
                run_login(tenant, reason=f"({label} bounced mid-sweep)")
                result = run_script(label, fn, to)
                result["auth_relogin"] = True
            # Still bouncing => the OTP session is expired. That is an auth
            # problem, NOT a service outage — mark AUTH_EXPIRED, never DOWN.
            # (Applies to every script of the tenant, not just the first.)
            if detect_bounce(result.get("payload")):
                result["verdict"] = "AUTH_EXPIRED (sign-in required — not a service outage)"
                result["auth_expired"] = True
                print(f"[AUTH] {label} — session expired; marked AUTH_EXPIRED "
                      f"(not DOWN, not emailed).", flush=True)
            else:
                print(f"[AUTH] {label} recovered after re-login.", flush=True)
        overall["scripts"].append(result)

    overall["ended_ist"] = datetime.now(IST).isoformat(timespec="seconds")
    overall["total_duration_s"] = round((datetime.now(IST)-started).total_seconds(),1)

    # Persist the consolidated JSON
    out_json = os.path.join(HERE, "_hc_artifacts", "master_report.json")
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, "w") as f:
        json.dump(overall, f, indent=2)

    # Print a markdown summary
    print("\n" + "="*78)
    print("CONSOLIDATED HEALTH CHECK REPORT")
    print("="*78)
    print(f"Started: {overall['started_ist']}  |  Ended: {overall['ended_ist']}  |  Total: {overall['total_duration_s']}s")
    print(f"\n--- Auth preflight (OTP login) ---")
    for t, s in (overall.get("auth_preflight") or {}).items():
        flag = "✅" if s == "AUTHED" else "❌"
        print(f"  {flag} {t:6s} {s}")
    print(f"\n--- {len(LIVENESS_URLS)}-URL liveness ---")
    c = overall["liveness"]["counts"]
    print(f"  UP: {c.get('UP',0)} | SLOW: {c.get('SLOW',0)} | DOWN: {c.get('DOWN',0)}")
    for r in overall["liveness"]["results"]:
        flag = "✅" if r["status"] == "UP" else ("⚠️" if r["status"]=="SLOW" else "❌")
        env = "dev" if str(r.get("environment","")).startswith("dev") else "prod"
        print(f"  {flag} {r.get('project','?')[:18]:18s} {env:4s} {r['label']:24s} "
              f"HTTP {str(r['http']):4} {r['ms']:>7.1f} ms  {r['err'] or ''}")
    print(f"\n--- Functional scripts ---")
    for s in overall["scripts"]:
        flag = severity_emoji(s.get("verdict"))
        print(f"  {flag} {s['label']:35s} {s.get('verdict','?'):<45s} ({s.get('duration_s','?')}s)")
    print(f"\nConsolidated JSON: {out_json}")

if __name__ == "__main__":
    main()
