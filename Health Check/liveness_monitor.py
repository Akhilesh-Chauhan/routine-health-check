"""Lightweight liveness monitor — the near-real-time tier of the suite.

Runs the URL liveness sweep (plain HTTP, no browser, no auth) and emails
ONLY when a URL goes DOWN, or when a previously-DOWN URL recovers. SLOW
responses (and every other state) are recorded but never emailed — so a
frequent cron schedule (every ~15 min) never spams the inbox.

Cron usage:
    */15 * * * * cd "<dir>" && /usr/bin/python3 liveness_monitor.py >> _hc_artifacts/liveness_monitor.log 2>&1
"""
import json
import os
from datetime import datetime, timezone, timedelta

import master_health_check as m          # reuse liveness_sweep() / LIVENESS_URLS
from alerts import send_email

HERE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(HERE, "_hc_artifacts")
STATE = os.path.join(ART, "liveness_state.json")
LATEST = os.path.join(ART, "liveness_latest.json")
IST = timezone(timedelta(hours=5, minutes=30))


def _load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


def _row(r):
    return (f"<tr><td>{r.get('label','')}</td>"
            f"<td><code>{r.get('url','')}</code></td>"
            f"<td><b>{r.get('status','')}</b></td>"
            f"<td>HTTP {r.get('http') or '&mdash;'}</td>"
            f"<td>{r.get('ms','?')} ms</td>"
            f"<td>{r.get('err') or ''}</td></tr>")


def _send_change_alert(now, problems, recoveries, counts):
    bits = []
    if problems:
        bits.append(f"{len(problems)} DOWN")
    if recoveries:
        bits.append(f"{len(recoveries)} recovered")
    subject = "Liveness — " + ", ".join(bits)
    html = [f"<h2>Liveness alert</h2>"
            f"<p>Checked: {now} IST<br>"
            f"Totals — UP {counts.get('UP',0)} &middot; SLOW {counts.get('SLOW',0)} "
            f"&middot; DOWN {counts.get('DOWN',0)}</p>"]
    if problems:
        html.append("<h3>&#128308; Now DOWN</h3>"
                    "<table border='1' cellpadding='6' cellspacing='0'>"
                    + "".join(_row(r) for r in problems) + "</table>")
    if recoveries:
        html.append("<h3>&#128994; Recovered (was DOWN)</h3>"
                    "<table border='1' cellpadding='6' cellspacing='0'>"
                    + "".join(_row(r) for r in recoveries) + "</table>")
    send_email(subject, "".join(html), subject + f" (checked {now} IST)")


def main():
    now = datetime.now(IST).isoformat(timespec="seconds")
    sweep = m.liveness_sweep()
    results = sweep["results"]
    counts = sweep["counts"]
    cur = {r["url"]: r["status"] for r in results}
    prev = _load_state()

    # All URLs down at once => the monitoring host lost network/DNS, not a
    # real mass outage. Suppress, and keep the previous good baseline so the
    # eventual recovery does not fire a false "all recovered" alert.
    total = len(results)
    if total > 1 and counts.get("DOWN", 0) == total:
        print(f"[{now}] ALL {total} URLs DOWN — treating as a monitoring-host "
              f"network failure: no alert, baseline state preserved.", flush=True)
        _save(LATEST, {"checked_ist": now, **sweep})
        return

    # Email only about DOWN — SLOW (and every other state) is recorded but
    # never alerted on.
    problems, recoveries = [], []
    for r in results:
        was = prev.get(r["url"])
        if r["status"] == "DOWN" and was != "DOWN":
            problems.append(r)
        elif r["status"] != "DOWN" and was == "DOWN":
            recoveries.append(r)

    print(f"[{now}] liveness UP={counts.get('UP',0)} SLOW={counts.get('SLOW',0)} "
          f"DOWN={counts.get('DOWN',0)} | new_down={len(problems)} "
          f"recovered={len(recoveries)}", flush=True)

    _save(LATEST, {"checked_ist": now, **sweep})
    if problems or recoveries:
        _send_change_alert(now, problems, recoveries, counts)
    _save(STATE, cur)


if __name__ == "__main__":
    main()
