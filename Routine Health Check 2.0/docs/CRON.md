# Cron tiers

Two scheduled tiers, both invoked via `hc monitor`. Designed so that a
flat-busy 15-minute schedule never spams the inbox, while a real outage
still surfaces within the next sweep window.

## Tier 1 — Liveness monitor

```
*/15 * * * * /usr/bin/env hc monitor liveness >> /var/log/hc/liveness.log 2>&1
```

- Runs the 20-URL HTTP sweep only (no Playwright, no auth, ~10 s).
- State stored in `artifacts/liveness_state.json`.
- Emails **only** when a URL goes DOWN, or when a previously-DOWN URL
  recovers. SLOW is recorded but never emailed.

## Tier 2 — Scheduled full sweep

```
0 10,14,18 * * * HC_NONINTERACTIVE=1 /usr/bin/env hc monitor sweep >> /var/log/hc/sweep.log 2>&1
```

- Runs `hc sweep` in non-interactive mode (no headed OTP pop-ups) and
  rebuilds `dashboard.html`.
- State stored in `artifacts/sweep_state.json`.
- Emails **only** when a check or URL is DOWN — or once when the last
  DOWN clears. DEGRADED scripts and SLOW URLs show on the dashboard but
  never trigger mail.

## Suppressions

- **Mass-down suppression.** If *every* URL reports DOWN in one cycle,
  that's the monitoring host's own network/DNS failing — not a real
  mass outage. The alert is suppressed and the good baseline state is
  preserved (so the eventual recovery doesn't fire a false "all
  recovered").
- **Auth expiry is not an outage.** When an OTP session lapses (~2-week
  TTL), the affected checks are marked **`AUTH_EXPIRED`** (not DOWN)
  and are **never** emailed. They show amber on the dashboard. Re-login
  with `DISPLAY=:0 hc login {prod|dev|umang}` to clear them.

## `HC_NONINTERACTIVE=1`

Set by `hc monitor sweep` automatically. Makes `master.main()` skip the
headed OTP-login pop-ups (cron can't complete an OTP). Expired sessions
then surface as DEGRADED checks plus an "auth session expired" line in
the alert email naming the tenant and the re-login command.

## Box availability caveat

Cron only fires while the monitoring host is powered on; scheduled
coverage has gaps whenever the machine is off. True 24/7 needs an always-on
host.

## Migration from v1

v1's cron currently runs:

```
*/15  * * * * cd "/path/to/Health Check" && /usr/bin/python3 liveness_monitor.py >> _hc_artifacts/liveness_monitor.log 2>&1
0 10,14,18 * * * cd "/path/to/Health Check" && HC_NONINTERACTIVE=1 /usr/bin/python3 scheduled_sweep.py >> _hc_artifacts/scheduled_sweep.log 2>&1
```

To switch to v2: keep v1 running until you've confirmed v2 with at least
one successful `hc sweep`, then replace the two crontab lines with the
`hc monitor liveness` / `hc monitor sweep` entries above. v2 keeps the
same SMTP config (`config/alert_config.json`, byte-identical copy) so
nothing changes about how alerts are sent.
