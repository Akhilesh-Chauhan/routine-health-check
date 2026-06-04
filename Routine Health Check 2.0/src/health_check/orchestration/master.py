"""Master health-check orchestrator — runs every check script sequentially
and produces a single consolidated JSON + Markdown summary.

STEP 0: auth-login preflight (OTP login is the FIRST thing).
STEP 1: URL liveness sweep (HTTP only).
STEP 2: functional checks; bounce-to-sign-in triggers one re-login + retry.

Invoke via `hc sweep` (preferred) or `python -m health_check.orchestration.master`.
"""
import concurrent.futures
import dataclasses
import functools
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
from health_check.reporting.verdicts import classify
from health_check.reporting.status import Verdict

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


@functools.lru_cache(maxsize=1)
def get_liveness_urls():
    """Liveness URL list, loaded on first use (not at import time).

    Importing master.py no longer reads url_registry.json off disk as a side
    effect — handy for tests and for tools that import the module without a
    config present. Cached so the sweep + the summary see the same list.
    """
    return _load_url_registry()


def _atomic_write_json(path, obj):
    """Write JSON to `path` atomically via a same-directory temp file +
    os.replace, so a concurrent reader (the web `/report` endpoint, the
    liveness monitor) can never observe a half-written report."""
    import tempfile
    target = str(path)
    d = os.path.dirname(target) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".master_report.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)   # atomic on POSIX + Windows
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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


def probe_verdict(authed, logged_out):
    """Decide the probe result from the two collected signals.

    D9 fix: the no-signal case (no positive AUTHED text seen, no logged-out
    fingerprint either) used to optimistically return AUTHED, so an expired
    session that simply didn't render a recognised sign-in surface was never
    re-logged-in. We now return UNKNOWN for that case — only a positive
    AUTHED signal yields AUTHED. May prompt OTP a little more often; that is
    the intended trade for not silently masking an expired session.
    """
    if authed:
        return "AUTHED"
    if logged_out:
        return "LOGGED_OUT"
    return "UNKNOWN"


def probe_auth(tenant):
    """Headless probe of a tenant's auth landing.
    Returns 'AUTHED' | 'LOGGED_OUT' | 'UNKNOWN' | 'ERROR: ...'."""
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
        return probe_verdict(authed, logged_out)
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
        # Re-login whenever we could NOT positively confirm a session
        # (LOGGED_OUT or the new UNKNOWN no-signal case) — but not on a probe
        # ERROR, where re-login wouldn't help.
        if st in ("LOGGED_OUT", "UNKNOWN"):
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


def liveness_sweep(on_progress=None):
    """Probe every liveness URL concurrently. If `on_progress` is given it is
    called once per URL as that probe completes — lets the web panel advance a
    fine-grained progress bar instead of treating the whole sweep as one step."""
    urls = get_liveness_urls()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(hit_url, e) for e in urls]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())
            if on_progress is not None:
                on_progress()
    order = {e["url"]: i for i, e in enumerate(urls)}
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


def derive_verdict(payload, returncode):
    """Roll a check's JSON payload up to a single script verdict. Shared by the
    sweep (run_script) and `hc check <name>` so both agree on the verdict."""
    if payload:
        if "overall" in payload:
            return str(payload["overall"])
        if "verdict" in payload:
            return str(payload["verdict"])
        if "bots" in payload:
            bot_verdicts = [b.get("verdict", "?") for b in payload.get("bots", [])]
            if all(v == Verdict.UP for v in bot_verdicts):
                return Verdict.UP
            if any(v == Verdict.DOWN for v in bot_verdicts):
                return "DEGRADED (some bots DOWN)"
            return Verdict.DEGRADED
        if "steps" in payload:
            step_verdicts = [s.get("verdict", "?") for s in payload.get("steps", [])]
            if all(v == Verdict.UP for v in step_verdicts):
                return Verdict.UP
            if any(v == Verdict.DOWN for v in step_verdicts):
                return Verdict.DOWN
            return Verdict.DEGRADED
    return Verdict.PASSED if returncode == 0 else "FAILED"


# module path -> human label, for entries merged outside a full sweep.
SCRIPT_LABELS = {module: label for label, module, _ in SCRIPTS}


def merge_script_result(module, stdout, returncode, duration_s):
    """Merge one check's result into master_report.json so the dashboard and
    the web overview reflect a single `hc check <name>` run — not only a full
    sweep. Replaces the matching script entry (by module path) in place;
    leaves the top-level sweep timestamps untouched (this isn't a full sweep).
    Returns the verdict written."""
    payload = extract_json_payload(stdout or "")
    verdict = derive_verdict(payload, returncode)
    entry = dataclasses.asdict(ScriptResult(
        label=SCRIPT_LABELS.get(module, module), filename=module,
        duration_s=duration_s, exit_code=returncode,
        verdict=verdict, payload=payload,
    ))
    try:
        data = json.loads(paths.MASTER_REPORT.read_text())
        if not isinstance(data, dict):
            data = None
    except (OSError, ValueError):
        data = None
    if data is None:
        data = {"started_ist": "", "ended_ist": "", "total_duration_s": 0.0,
                "auth_preflight": {}, "liveness": {"results": [], "counts": {}},
                "scripts": []}
    scripts = data.setdefault("scripts", [])
    for i, s in enumerate(scripts):
        if s.get("filename") == module:
            scripts[i] = entry
            break
    else:
        scripts.append(entry)
    data["last_partial_update_ist"] = datetime.now(IST).isoformat(timespec="seconds")
    paths.MASTER_REPORT.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(paths.MASTER_REPORT, data)
    return verdict


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
        verdict = derive_verdict(payload, proc.returncode)
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
    # Bucket via the one canonical classifier (D13); AUTH_EXPIRED is a warn
    # bucket but keeps its own key glyph in the operator summary.
    if "AUTH_EXPIRED" in str(v).upper():
        return "🔑"
    return {"up": "✅", "warn": "⚠️", "down": "❌"}.get(classify(v), "•")


def main():
    paths.ensure_runtime_dirs()
    started = datetime.now(IST)

    auth_preflight_status = auth_preflight()

    # Fine-grained progress for the web panel: one unit per liveness URL plus
    # one per functional check. Emitted as `[progress] done/total | label`
    # lines on stderr; the job runner parses these to drive a continuous
    # download-style bar instead of a coarse 2-step segment count.
    n_live = len(get_liveness_urls())
    progress_total = n_live + len(SCRIPTS)
    progress = {"done": 0}

    def _bump(label: str = "") -> None:
        progress["done"] += 1
        log.info(f"[progress] {progress['done']}/{progress_total} | {label}")

    log.info(f"[progress] 0/{progress_total} | starting")

    log.info(f"\n=== STEP 1: {n_live}-URL liveness sweep ===")
    liveness = liveness_sweep(on_progress=lambda: _bump("liveness probe"))
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
        _bump(label)

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
    _atomic_write_json(paths.MASTER_REPORT, dataclasses.asdict(report))

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
    print(f"\n--- {len(get_liveness_urls())}-URL liveness ---")
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
