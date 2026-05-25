"""`hc` — single CLI entry point for the suite.

Subcommands:
    hc sweep                    full master health check
    hc dashboard [--report P]   rebuild dashboard.html
    hc liveness                 URL liveness sweep (HTTP only, no Playwright)
    hc login {prod|dev|umang}   headed OTP login for one tenant
    hc check <name>             run one functional check
    hc monitor {liveness|sweep} cron entry points
    hc alerts {selfcheck|test}  SMTP self-check / send-test
"""
from __future__ import annotations

import argparse
import importlib
import sys

from health_check import logging as hc_logging
from health_check import paths

# `hc check <name>` → module path. Names match the user-visible suffix from v1.
CHECKS = {
    "myscheme":  "health_check.checks.public.myscheme",
    "aistore":   "health_check.checks.public.aistore",
    "rules":     "health_check.checks.public.rules_engine",
    "docs":      "health_check.checks.public.docs_portal",
    "chatbots":  "health_check.checks.public.chatbots",
    "auth":      "health_check.checks.prod.auth_precheck",
    "govai":     "health_check.checks.prod.govai",
    "cms":       "health_check.checks.prod.cms",
    "forms":     "health_check.checks.prod.forms",
    "devenv":    "health_check.checks.dev.environment",
    "umang":     "health_check.checks.umang.integration",
}

LOGIN_MODULES = {
    "prod":  "health_check.auth.prod_login",
    "dev":   "health_check.auth.dev_login",
    "umang": "health_check.auth.umang_login",
}


def _call_main(module_path: str, *args) -> int:
    mod = importlib.import_module(module_path)
    fn = getattr(mod, "main")
    rv = fn(*args) if args else fn()
    return int(rv) if isinstance(rv, int) else 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hc", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sweep", help="full master health check")
    sub.add_parser("liveness", help="URL liveness sweep (HTTP only)")

    sp_dash = sub.add_parser("dashboard", help="rebuild dashboard.html")
    sp_dash.add_argument("--report", help="path to master_report.json")
    sp_dash.add_argument("--out", help="path to write dashboard.html")

    sp_login = sub.add_parser("login", help="headed OTP login for one tenant")
    sp_login.add_argument("tenant", choices=sorted(LOGIN_MODULES))

    sp_check = sub.add_parser("check", help="run one functional check")
    sp_check.add_argument("name", choices=sorted(CHECKS))

    sp_mon = sub.add_parser("monitor", help="cron entry points")
    sp_mon.add_argument("tier", choices=["liveness", "sweep"])

    sp_alert = sub.add_parser("alerts", help="SMTP self-check / send-test")
    sp_alert.add_argument("action", choices=["selfcheck", "test"])

    return p


def main(argv: list[str] | None = None) -> int:
    paths.ensure_runtime_dirs()
    hc_logging.setup()
    args = _build_parser().parse_args(argv)

    if args.cmd == "sweep":
        return _call_main("health_check.orchestration.master")
    if args.cmd == "liveness":
        return _call_main("health_check.orchestration.liveness_monitor")
    if args.cmd == "dashboard":
        forwarded = []
        if args.report:
            forwarded += ["--report", args.report]
        if args.out:
            forwarded += ["--out", args.out]
        return _call_main("health_check.orchestration.dashboard", forwarded)
    if args.cmd == "login":
        return _call_main(LOGIN_MODULES[args.tenant])
    if args.cmd == "check":
        return _call_main(CHECKS[args.name])
    if args.cmd == "monitor":
        if args.tier == "liveness":
            return _call_main("health_check.orchestration.liveness_monitor")
        return _call_main("health_check.orchestration.scheduled_sweep")
    if args.cmd == "alerts":
        from health_check.orchestration import alerts as a
        if args.action == "selfcheck":
            ok, msg = a.smtp_selfcheck()
            print(("[ok] " if ok else "[fail] ") + msg)
            return 0 if ok else 1
        ok = a.send_email(
            "Test alert — please ignore",
            "<h2>myScheme Health Check — test alert</h2>"
            "<p>This confirms email alerting is wired up correctly.</p>",
            "myScheme Health Check test alert — email alerting is wired up correctly.",
        )
        return 0 if ok else 1

    return 2   # unreachable: argparse already enforces a subcommand


if __name__ == "__main__":
    sys.exit(main())
