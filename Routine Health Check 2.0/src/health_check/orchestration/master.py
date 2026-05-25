"""Master health-check orchestrator — runs every check script sequentially
and produces a single consolidated JSON + Markdown summary.

STEP 0: auth-login preflight (OTP login is the FIRST thing).
STEP 1: URL liveness sweep (HTTP only).
STEP 2: functional checks; bounce-to-sign-in triggers one re-login + retry.

Invoke via `hc sweep` (preferred) or `python -m health_check.orchestration.master`.
"""
import concurrent.futures
import dataclasses
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib import request as urlreq, error as urlerr

from health_check import logging as hc_logging
from health_check import paths
from health_check.browser.context import launch_persistent_context
from health_check.reporting.models import (
    LivenessResult,
    LivenessSection,
    MasterReport,
    ScriptResult,
)

IST = timezone(timedelta(hours=5, minutes=30))
log = hc_logging.setup()


def _load_url_registry():
    try:
        with open(paths.URL_REGISTRY) as f:
            reg = json.load(f)
    except Exception as e:
        log.warning(f"could not load url_registry.json: {e}")
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

# (group label, module path, default timeout seconds). The orchestrator
# dispatches each check via `python -m <module>` so the package must be
# installed (pip install -e .) for the subprocesses to import correctly.
SCRIPTS = [
    ("Public — myscheme.gov.in E2E", "health_check.checks.public.myscheme",        240),
    ("Public — aistore marketplace",  "health_check.checks.public.aistore",         120),
    ("Public — rules engine",         "health_check.checks.public.rules_engine",    180),
    ("Public — docs portal",          "health_check.checks.public.docs_portal",     180),
    ("Public — 6 standalone bots",    "health_check.checks.public.chatbots",        600),
    ("Prod auth precheck",            "health_check.checks.prod.auth_precheck",      60),
    ("Prod — govai workspace",        "health_check.checks.prod.govai",             180),
    ("Prod — cms workspace",          "health_check.checks.prod.cms",               180),
    ("Prod — forms workspace",        "health_check.checks.prod.forms",             180),
    ("Dev environment full sweep",    "health_check.checks.dev.environment",        600),
    ("UMANG integration",             "health_check.checks.umang.integration",      600),
]

TENANTS = {
    "prod":  {"probe": "https://auth.myscheme.gov.in/",
              "login": "health_check.auth.prod_login"},
    "dev":   {"probe": "https://devauth.myscheme.gov.in/",
              "login": "health_check.auth.dev_login"},
    "umang": {"probe": "https://myauth.umangapp.in/",
              "login": "health_check.auth.umang_login"},
}

SCRIPT_TENANT = {
    "health_check.checks.prod.auth_precheck":   "prod",
    "health_check.checks.prod.govai":           "prod",
    "health_check.checks.prod.cms":             "prod",
    "health_check.checks.prod.forms":           "prod",
    "health_check.checks.dev.environment":      "dev",
    "health_check.checks.umang.integration":    "umang",
}

LOGGED_OUT_SIGNALS = [
    "already a user", "new user? sign up", "enter mobile", "send otp",
    "enter otp", "sign in to your account", "security pin",
]
AUTHED_SIGNALS = [
    "please choose a platform to continue", "sign out",
]
SIGNIN_HOSTS = [
    "digilocker.meripehchaan.gov.in", "consent.digilocker.gov.in",
    "myauth.umangapp.in", "/oidc/v1/auth",
]


def probe_auth(tenant):
    """Headless probe of a tenant's auth landing.
    Returns 'AUTHED' | 'LOGGED_OUT' | 'ERROR: ...'."""
    cfg = TENANTS[tenant]
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return f"ERROR: playwright unavailable ({e})"
    try:
        with sync_playwright() as p:
            ctx = launch_persistent_context(p, tenant, headless=True)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(cfg["probe"], wait_until="domcontentloaded", timeout=30_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10_000)
                except Exception:
                    pass
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
    cfg = TENANTS[tenant]
    if os.environ.get("HC_NONINTERACTIVE"):
        log.info(f"[AUTH] {tenant.upper()} needs a manual OTP login {reason} — "
                 f"skipped (HC_NONINTERACTIVE set). Run interactively: "
                 f"hc login {tenant}")
        return False
    log.info("\n" + "!" * 78)
    log.info(f"[AUTH] {tenant.upper()} needs a manual OTP login. {reason}".rstrip())
    log.info(f"[AUTH] Opening {cfg['login']} — a Chromium window will appear on the display.")
    log.info("[AUTH] >>> Complete the MeriPehchaan / DigiLocker OTP login in that window. <<<")
    log.info(f"[AUTH] The window auto-closes once login is detected (up to ~10 min).")
    log.info("!" * 78)
    env = dict(os.environ)
    env.setdefault("DISPLAY", ":0")
    try:
        proc = subprocess.run([sys.executable, "-m", cfg["login"]],
                              cwd=str(paths.ROOT), env=env,
                              timeout=780, capture_output=True, text=True)
        ok = proc.returncode == 0
        log.info(f"[AUTH] {tenant} login script exited "
                 f"({'ok' if ok else 'code ' + str(proc.returncode)}).")
        return ok
    except subprocess.TimeoutExpired:
        log.warning(f"[AUTH] {tenant} login timed out — no OTP completed.")
        return False
    except Exception as e:
        log.warning(f"[AUTH] {tenant} login error: {type(e).__name__}: {e}")
        return False


def detect_bounce(payload):
    """True only if a *failed* authenticated route landed on a sign-in surface."""
    if not payload:
        return False

    def is_bounced_step(d):
        if str(d.get("verdict", "")).upper() not in ("DEGRADED", "DOWN"):
            return False
        name = str(d.get("name", "")).lower()
        if "sign in" in name or "signin" in name:
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
    log.info("\n=== STEP 0: Auth preflight (OTP login first) ===")
    status = {}
    for tenant in ("prod", "dev", "umang"):
        st = probe_auth(tenant)
        log.info(f"  [{tenant:5s}] session: {st}")
        if st == "LOGGED_OUT":
            run_login(tenant, reason="(preflight — no active session)")
            st = probe_auth(tenant)
            log.info(f"  [{tenant:5s}] after login: {st}")
        status[tenant] = st
    return status


def hit_url(entry):
    meta = {"label": entry["label"], "url": entry["url"],
            "project": entry.get("project", "Other"),
            "environment": entry.get("environment", "production")}
    t0 = time.perf_counter()
    try:
        req = urlreq.Request(entry["url"], headers={"User-Agent": "healthcheck/1.0"})
        with urlreq.urlopen(req, timeout=10) as resp:
            code = resp.status
        ms = (time.perf_counter() - t0) * 1000
        verdict = "UP" if code < 400 and ms < 4000 else ("SLOW" if code < 400 else "DOWN")
        return {**meta, "status": verdict, "http": code, "ms": round(ms, 1), "err": None}
    except urlerr.HTTPError as e:
        ms = (time.perf_counter() - t0) * 1000
        return {**meta, "status": "DOWN", "http": e.code, "ms": round(ms, 1), "err": str(e)}
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        return {**meta, "status": "DOWN", "http": None, "ms": round(ms, 1),
                "err": f"{type(e).__name__}: {e}"}


def liveness_sweep():
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(hit_url, e) for e in LIVENESS_URLS]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())
    order = {e["url"]: i for i, e in enumerate(LIVENESS_URLS)}
    results.sort(key=lambda r: order.get(r["url"], 999))
    counts = {"UP": 0, "SLOW": 0, "DOWN": 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"results": results, "counts": counts}


def extract_json_payload(stdout):
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
        return json.loads(stdout[start:last_close + 1])
    except Exception:
        return None


def run_script(label, module, timeout_s):
    t0 = time.perf_counter()
    log.info(f"\n[run] {label}  ({module}, timeout={timeout_s}s)")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", module], cwd=str(paths.ROOT),
            capture_output=True, text=True, timeout=timeout_s,
        )
        elapsed = round(time.perf_counter() - t0, 1)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        payload = extract_json_payload(stdout)
        verdict = None
        if payload:
            if "overall" in payload:
                verdict = str(payload["overall"])
            elif "verdict" in payload:
                verdict = str(payload["verdict"])
            elif "bots" in payload:
                bot_verdicts = [b.get("verdict", "?") for b in payload.get("bots", [])]
                if all(v == "UP" for v in bot_verdicts):
                    verdict = "HEALTHY"
                elif any(v == "DOWN" for v in bot_verdicts):
                    verdict = "DEGRADED (some bots DOWN)"
                else:
                    verdict = "DEGRADED"
            elif "steps" in payload:
                step_verdicts = [s.get("verdict", "?") for s in payload.get("steps", [])]
                if all(v == "UP" for v in step_verdicts):
                    verdict = "HEALTHY"
                elif any(v == "DOWN" for v in step_verdicts):
                    verdict = "DOWN"
                else:
                    verdict = "DEGRADED"
        if verdict is None:
            verdict = "PASSED" if proc.returncode == 0 else "FAILED"
        result = ScriptResult(
            label=label, filename=module,
            duration_s=elapsed, exit_code=proc.returncode,
            verdict=verdict, payload=payload,
            stderr_tail=stderr[-400:] if stderr else "",
        )
        log.info(f"[done] {label}  -> {verdict}  ({elapsed}s)")
        return result
    except subprocess.TimeoutExpired:
        elapsed = round(time.perf_counter() - t0, 1)
        log.warning(f"[TIMEOUT] {label} exceeded {timeout_s}s")
        return ScriptResult(label=label, filename=module,
                            duration_s=elapsed, exit_code=None,
                            verdict="TIMEOUT", detail=f"Exceeded {timeout_s}s")
    except Exception as e:
        elapsed = round(time.perf_counter() - t0, 1)
        return ScriptResult(label=label, filename=module,
                            duration_s=elapsed, exit_code=None,
                            verdict="ERROR",
                            detail=f"{type(e).__name__}: {e}")


def severity_emoji(v):
    if v is None:
        return "?"
    s = v.upper()
    if "HEALTHY" in s or s in ("UP", "PASSED"):
        return "✅"
    if "AUTH_EXPIRED" in s:
        return "🔑"
    if "TIMEOUT" in s or "ERROR" in s or "MISSING" in s:
        return "❌"
    if "DOWN" in s and "DEGRADED" not in s:
        return "❌"
    if "DEGRADED" in s:
        return "⚠️"
    if "DOWN" in s:
        return "❌"
    return "•"


def main():
    paths.ensure_runtime_dirs()
    started = datetime.now(IST)

    auth_preflight_status = auth_preflight()

    log.info(f"\n=== STEP 1: {len(LIVENESS_URLS)}-URL liveness sweep ===")
    liveness = liveness_sweep()
    log.info(f"Liveness counts: {liveness['counts']}")

    log.info("\n=== STEP 2: Functional checks ===")
    script_results: list[ScriptResult] = []
    relogged = set()
    for label, module, to in SCRIPTS:
        result = run_script(label, module, to)
        tenant = SCRIPT_TENANT.get(module)
        if tenant and detect_bounce(result.payload):
            if tenant not in relogged:
                relogged.add(tenant)
                log.info(f"[AUTH] {label} bounced to a sign-in surface — "
                         f"attempting re-login.")
                run_login(tenant, reason=f"({label} bounced mid-sweep)")
                result = run_script(label, module, to)
                result.auth_relogin = True
            if detect_bounce(result.payload):
                result.verdict = "AUTH_EXPIRED (sign-in required — not a service outage)"
                result.auth_expired = True
                log.info(f"[AUTH] {label} — session expired; marked AUTH_EXPIRED "
                         f"(not DOWN, not emailed).")
            else:
                log.info(f"[AUTH] {label} recovered after re-login.")
        script_results.append(result)

    ended = datetime.now(IST)
    liveness_results = [LivenessResult(**r) for r in liveness["results"]]
    report = MasterReport(
        started_ist=started.isoformat(timespec="seconds"),
        ended_ist=ended.isoformat(timespec="seconds"),
        total_duration_s=round((ended - started).total_seconds(), 1),
        auth_preflight=auth_preflight_status,
        liveness=LivenessSection(results=liveness_results, counts=liveness["counts"]),
        scripts=script_results,
    )

    paths.MASTER_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with open(paths.MASTER_REPORT, "w") as f:
        json.dump(dataclasses.asdict(report), f, indent=2)

    # ---- Operator-facing markdown summary (stdout, NOT logger). ----
    overall = dataclasses.asdict(report)
    print("\n" + "=" * 78)
    print("CONSOLIDATED HEALTH CHECK REPORT")
    print("=" * 78)
    print(f"Started: {overall['started_ist']}  |  Ended: {overall['ended_ist']}"
          f"  |  Total: {overall['total_duration_s']}s")
    print(f"\n--- Auth preflight (OTP login) ---")
    for t, s in (overall.get("auth_preflight") or {}).items():
        flag = "✅" if s == "AUTHED" else "❌"
        print(f"  {flag} {t:6s} {s}")
    print(f"\n--- {len(LIVENESS_URLS)}-URL liveness ---")
    c = overall["liveness"]["counts"]
    print(f"  UP: {c.get('UP', 0)} | SLOW: {c.get('SLOW', 0)} | DOWN: {c.get('DOWN', 0)}")
    for r in overall["liveness"]["results"]:
        flag = "✅" if r["status"] == "UP" else ("⚠️" if r["status"] == "SLOW" else "❌")
        env = "dev" if str(r.get("environment", "")).startswith("dev") else "prod"
        print(f"  {flag} {r.get('project', '?')[:18]:18s} {env:4s} {r['label']:24s} "
              f"HTTP {str(r['http']):4} {r['ms']:>7.1f} ms  {r['err'] or ''}")
    print(f"\n--- Functional scripts ---")
    for s in overall["scripts"]:
        flag = severity_emoji(s.get("verdict"))
        print(f"  {flag} {s['label']:35s} {s.get('verdict', '?'):<45s} "
              f"({s.get('duration_s', '?')}s)")
    print(f"\nConsolidated JSON: {paths.MASTER_REPORT}")


if __name__ == "__main__":
    main()
