"""Scheduled full-sweep wrapper — the heavy tier of the suite.

Runs master_health_check.py in non-interactive mode (no OTP pop-ups),
regenerates dashboard.html, then emails ONLY when a check or URL is DOWN
— or once when the last DOWN clears. SLOW and DEGRADED states show on the
dashboard but never trigger mail. Intended for a few-times-a-day cron.

Cron usage:
    0 10,14,18 * * * cd "<dir>" && HC_NONINTERACTIVE=1 /usr/bin/python3 scheduled_sweep.py >> _hc_artifacts/scheduled_sweep.log 2>&1
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

from alerts import send_email

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(HERE, "_hc_artifacts", "master_report.json")
STATE = os.path.join(HERE, "_hc_artifacts", "sweep_state.json")
IST = timezone(timedelta(hours=5, minutes=30))

LOGIN_SCRIPT = {"prod": "manual_login.py", "dev": "dev_manual_login.py",
                "umang": "umang_manual_login.py"}


def _run(script, extra_env=None, timeout=2400):
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    try:
        subprocess.run([sys.executable, os.path.join(HERE, script)],
                       cwd=HERE, env=env, timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        print(f"[sweep] {script} timed out after {timeout}s", flush=True)
        return False
    except Exception as e:
        print(f"[sweep] {script} failed: {type(e).__name__}: {e}", flush=True)
        return False


def _classify(verdict):
    s = str(verdict or "").upper()
    if "HEALTHY" in s or s in ("UP", "PASS", "PASSED"):
        return "ok"
    if "AUTH_EXPIRED" in s:
        return "auth"        # expired sign-in session — NOT a service outage
    if "DEGRADED" in s:
        return "degraded"
    return "down"   # DOWN / TIMEOUT / ERROR / MISSING / unknown


def _prev_healthy():
    try:
        with open(STATE) as f:
            return json.load(f).get("healthy")
    except Exception:
        return None


def _save_healthy(h, now):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        json.dump({"healthy": h, "ts": now}, f, indent=2)


def _send_sweep_alert(now, rep, down_scripts):
    script_rows = "".join(
        f"<tr><td>{s.get('label','?')}</td><td><b>{s.get('verdict','?')}</b></td>"
        f"<td>{s.get('duration_s','?')}s</td></tr>" for s in down_scripts)
    down_urls = [r for r in rep.get("liveness", {}).get("results", [])
                 if r.get("status") == "DOWN"]
    url_rows = "".join(
        f"<tr><td>{r.get('project','?')}</td><td><code>{r.get('url','')}</code></td>"
        f"<td>HTTP {r.get('http') or '&mdash;'}</td><td>{r.get('err') or ''}</td></tr>"
        for r in down_urls)
    parts = ["<h2>Health sweep &mdash; service(s) DOWN</h2>",
             f"<p>Run at {now} IST.</p>"]
    if down_scripts:
        parts.append("<h3>Functional checks DOWN</h3>"
                     "<table border='1' cellpadding='6' cellspacing='0'>"
                     "<tr><th>Check</th><th>Verdict</th><th>Duration</th></tr>"
                     + script_rows + "</table>")
    if down_urls:
        parts.append("<h3>URLs DOWN</h3>"
                     "<table border='1' cellpadding='6' cellspacing='0'>"
                     "<tr><th>Project</th><th>URL</th><th>HTTP</th><th>Error</th></tr>"
                     + url_rows + "</table>")
    auth = rep.get("auth_preflight") or {}
    expired = [t for t, st in auth.items() if str(st).upper() != "AUTHED"]
    if expired:
        items = "".join(
            f"<li><b>{t}</b> &mdash; <code>DISPLAY=:0 python3 "
            f"{LOGIN_SCRIPT.get(t, '?')}</code></li>" for t in expired)
        parts.append(f"<p>Note &mdash; auth session expired for: {', '.join(expired)} "
                     f"(re-login to clear the AUTH_EXPIRED checks):</p><ul>{items}</ul>")
    parts.append(f"<p>Dashboard: <code>file://{os.path.join(HERE, 'dashboard.html')}</code></p>")
    n = len(down_scripts) + len(down_urls)
    send_email(f"{n} service(s) DOWN", "".join(parts),
               f"Health sweep found {n} service(s) DOWN at {now} IST")


def main():
    now = datetime.now(IST).isoformat(timespec="seconds")
    print(f"[{now}] scheduled full sweep starting (non-interactive)…", flush=True)
    _run("master_health_check.py", {"HC_NONINTERACTIVE": "1"})
    _run("generate_dashboard.py", timeout=300)

    try:
        with open(REPORT) as f:
            rep = json.load(f)
    except Exception as e:
        send_email("Full sweep — report unreadable",
                   f"<p>scheduled_sweep could not read master_report.json: {e}</p>",
                   f"scheduled_sweep could not read master_report.json: {e}")
        return

    # All URLs down at once => the monitoring host lost network, not a real
    # mass outage. Suppress the alert and leave the recovery state untouched.
    live = rep.get("liveness", {}).get("counts", {})
    total_urls = len(rep.get("liveness", {}).get("results", []))
    down_urls = live.get("DOWN", 0)
    if total_urls > 1 and down_urls == total_urls:
        print(f"[{now}] ALL {total_urls} URLs DOWN — monitoring-host network "
              f"failure; no alert, state preserved.", flush=True)
        return

    # Email only about DOWN — DEGRADED scripts and SLOW URLs show on the
    # dashboard but never trigger mail.
    down_scripts = [s for s in rep.get("scripts", [])
                    if _classify(s.get("verdict")) == "down"]
    all_clear = not down_scripts and down_urls == 0

    print(f"[{now}] sweep done — {'NOTHING DOWN' if all_clear else 'DOWN DETECTED'} "
          f"({len(down_scripts)} script(s) DOWN, {down_urls} URL(s) DOWN)", flush=True)

    was_clear = _prev_healthy()
    if not all_clear:
        _send_sweep_alert(now, rep, down_scripts)
    elif was_clear is False:
        send_email("Full sweep — recovered",
                   f"<h2>&#9989; Nothing is DOWN anymore</h2>"
                   f"<p>Run at {now} IST — all previously-down checks and URLs "
                   f"are back up.</p>",
                   f"All down checks recovered as of {now} IST")
    _save_healthy(all_clear, now)


if __name__ == "__main__":
    main()
