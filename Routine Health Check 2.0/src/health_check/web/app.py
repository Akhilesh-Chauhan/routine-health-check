"""Flask app for the `hc serve` control panel."""
from __future__ import annotations

import json
import webbrowser
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
)

from health_check import paths
from health_check.orchestration import dashboard as _dashboard
from health_check.reporting import theme as _theme, fonts as _fonts
from health_check.reporting.verdicts import classify as classify_verdict, js_classifier
from health_check.web import projects, runner as runner_mod
from health_check.web.runner import (
    JobStep,
    runner,
    step_check,
    step_dashboard,
    step_liveness,
    step_login,
    step_sweep,
    stream_lines,
)


def _same_origin(request) -> bool:
    """Lightweight CSRF guard for state-changing POSTs (D10).

    The control panel is a localhost tool. A browser attaches Origin (and
    usually Referer) on cross-site requests; if either is present its host
    must equal the panel's own Host. Requests with no Origin/Referer (curl,
    the panel's own same-origin fetch in some browsers) are allowed — CSRF is
    a browser-only attack and a non-browser client isn't being tricked.
    """
    host = (request.host or "").split(":")[0].lower()
    for header in ("Origin", "Referer"):
        val = request.headers.get(header)
        if not val:
            continue
        h = (urlparse(val).hostname or "").lower()
        if h and h != host:
            return False
    return True


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            projects=projects.load_projects(),
            env_names=list(projects.ENV_CHECKS.keys()),
            check_names=list(projects.all_check_names()),
            check_groups=projects.CHECK_GROUPS,
            # Luminous Glass shared assets (one source: reporting/theme.py + verdicts.py).
            font_face=_fonts.font_face_css(),
            design_tokens=_theme.DESIGN_TOKENS_CSS,
            svg_sprite=_theme.SVG_SPRITE,
            theme_toggle=_theme.THEME_TOGGLE_BUTTON,
            theme_boot_js=_theme.THEME_BOOT_JS,
            js_classifier=js_classifier("classifyVerdict"),
        )

    @app.post("/run")
    def run():
        """Body: {kind: 'sweep'|'env'|'project'|'check'|'liveness'|'login'|'dashboard', name?: str, mode?: 'liveness'|'functional'|'all'}."""
        if not _same_origin(request):
            return jsonify({"error": "cross-origin request rejected"}), 403
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "request body must be a JSON object"}), 400
        kind = payload.get("kind")
        name = payload.get("name")
        mode = payload.get("mode", "all")

        title, steps = _plan(kind, name, mode)
        if not steps:
            return jsonify({"error": f"unknown job kind={kind} name={name}"}), 400

        job = runner.submit(title, steps)
        return jsonify({"job_id": job.id, "title": job.title})

    @app.post("/cancel/<job_id>")
    def cancel(job_id):
        """Cancel a running or queued job (D11): kills the current step's
        process tree and runs no further steps."""
        if not _same_origin(request):
            return jsonify({"error": "cross-origin request rejected"}), 403
        if not runner.cancel(job_id):
            abort(404)
        return jsonify({"cancelled": job_id})

    @app.get("/events/<job_id>")
    def events(job_id):
        job = runner.get(job_id)
        if not job:
            abort(404)
        return Response(stream_lines(job), mimetype="text/event-stream")

    @app.get("/status/<job_id>")
    def status(job_id):
        job = runner.get(job_id)
        if not job:
            abort(404)
        return jsonify({
            "id": job.id,
            "title": job.title,
            "state": job.state,
            "started_at": job.started_at,
            "ended_at": job.ended_at,
            "overall_exit": job.overall_exit,
            # Fine-grained progress (sweep emits one unit per service); None
            # for jobs that don't, so the panel falls back to step segments.
            "progress": job.progress,
            "steps": [
                {"label": s.label, "exit_code": s.exit_code, "duration_s": s.duration_s}
                for s in job.steps
            ],
        })

    @app.get("/status")
    def status_all():
        return jsonify({
            "current": runner.current_id(),
            "jobs": [
                {"id": j.id, "title": j.title, "state": j.state}
                for j in runner.list_jobs()[-20:]
            ],
        })

    @app.get("/history")
    def history():
        """Recent jobs with timing — fuels the History view."""
        out = []
        for j in runner.list_jobs()[-50:]:
            out.append({
                "id": j.id,
                "title": j.title,
                "state": j.state,
                "started_at": j.started_at,
                "ended_at": j.ended_at,
                "duration_s": (j.ended_at - j.started_at) if (j.started_at and j.ended_at) else None,
                "overall_exit": j.overall_exit,
                "steps": [
                    {"label": s.label, "exit_code": s.exit_code, "duration_s": s.duration_s}
                    for s in j.steps
                ],
            })
        out.reverse()  # newest first
        return jsonify({"jobs": out})

    @app.get("/dashboard")
    def dashboard():
        """Serve dashboard.html (rebuilt by `hc dashboard`).

        `hc dashboard` writes it to project root by default; tolerate
        the artifacts/ location too in case that ever changes.
        """
        for candidate_dir in (paths.ROOT, paths.ARTIFACTS_DIR):
            if (candidate_dir / "dashboard.html").exists():
                return send_from_directory(str(candidate_dir), "dashboard.html")
        return ("Dashboard not yet built — run a sweep + `hc dashboard`.", 404)

    @app.get("/report")
    def report():
        rep = paths.ARTIFACTS_DIR / "master_report.json"
        if not rep.exists():
            return jsonify({"error": "no master_report.json yet"}), 404
        try:
            body = rep.read_text()
        except OSError as e:
            # Mid-sweep the writer may briefly hold the file; report a
            # transient 503 rather than a 500 stack trace.
            return jsonify({"error": f"could not read report: {e}"}), 503
        return Response(body, mimetype="application/json")

    @app.get("/verdicts")
    def verdicts():
        """Roll up master_report.json into:
          • a leaf-check summary (the *actual* operations performed),
          • per-check verdicts (one per `hc check` name),
          • per-project verdicts (one per url_registry project),
          • liveness counts (HTTP-only probe, kept as a SEPARATE signal).

        Liveness is reported alongside but never added into the functional
        alarm counts — a SLOW URL is informational, not an outage; a DOWN
        URL caused by an outage is already reflected as DOWN leaf checks
        inside the affected scripts, so adding it again would double-count.
        """
        rep_path = paths.ARTIFACTS_DIR / "master_report.json"
        if not rep_path.exists():
            return jsonify({"available": False})
        try:
            data = json.loads(rep_path.read_text())
        except (OSError, ValueError) as e:
            # Unreadable / partially-written report -> transient 503, not 500.
            return jsonify({"error": f"could not read report: {e}"}), 503

        # Fold in the freshest HTTP liveness probe so the overview's liveness
        # signal matches the dashboard (which does the same), rather than the
        # older probe frozen into the sweep report.
        live_path = paths.ARTIFACTS_DIR / "liveness_latest.json"
        if live_path.exists():
            try:
                _dashboard._apply_fresh_liveness(data, json.loads(live_path.read_text()))
            except (OSError, ValueError):
                pass

        # ---- per-check verdicts (the 11 functional checks) ----
        check_verdicts: dict[str, str] = {}
        for row in data.get("scripts", []):
            mod = row.get("filename", "")
            name = mod.rsplit(".", 1)[-1] if mod else ""
            alias = {
                "rules_engine": "rules", "docs_portal": "docs",
                "chatbots": "chatbots", "myscheme": "myscheme",
                "aistore": "aistore", "auth_precheck": "auth",
                "govai": "govai", "cms": "cms", "forms": "forms",
                "environment": "devenv", "integration": "umang",
            }.get(name, name)
            if alias:
                check_verdicts[alias] = (row.get("verdict") or "").split(" ")[0]

        # ---- leaf-check rollup (mirrors the dashboard) ----
        def _walk_leaves(script: dict) -> list[str]:
            p = (script.get("payload") or {})
            fb = script.get("verdict")
            if isinstance(p.get("domains"), list):
                return [(c.get("verdict") or fb)
                        for d in p["domains"] for c in (d.get("checks") or [])]
            if isinstance(p.get("bots"), list):
                return [(b.get("verdict") or fb) for b in p["bots"]]
            if isinstance(p.get("steps"), list):
                return [(s.get("verdict") or fb) for s in p["steps"]]
            return [fb]

        # Verdict bucketing comes from the one canonical classifier (D13),
        # shared with master.py and the dashboard template.
        leaf_counts = {"up": 0, "warn": 0, "down": 0, "unknown": 0, "total": 0}
        for s in data.get("scripts", []):
            for v in _walk_leaves(s):
                leaf_counts["total"] += 1
                leaf_counts[classify_verdict(v)] += 1

        # ---- per-project verdicts ----
        # Aggregate liveness rows + functional checks per project, then
        # compute a single "worst" verdict. SLOW is informational only —
        # it never trumps a real functional verdict (so a SLOW URL probe
        # for cms.myscheme.gov.in does NOT make the CMS project tile yellow
        # when the functional CMS check is UP).
        project_rollup: dict[str, dict] = {}
        for row in data.get("liveness", {}).get("results", []):
            pname = row.get("project")
            if not pname:
                continue
            slot = project_rollup.setdefault(pname, {"liveness": [], "checks": []})
            slot["liveness"].append(row.get("status"))

        # Per-URL leaf verdicts, so a project tile can reflect ITS OWN surface
        # rather than a shared check's aggregate. This keeps the panel in sync
        # with the dashboard: the five chatbot projects all map to the single
        # `chatbots` check whose aggregate is DEGRADED when ANY one bot is down
        # — without this, one bad bot would paint all five tiles degraded even
        # though the dashboard (which reads each bot's own verdict) shows them UP.
        def _norm_url(u: str | None) -> str:
            return (u or "").rstrip("/").lower()

        leaf_by_url: dict[str, str] = {}
        for s in data.get("scripts", []):
            pl = s.get("payload") or {}
            seqs = []
            if isinstance(pl.get("bots"), list):
                seqs.append(pl["bots"])
            if isinstance(pl.get("steps"), list):
                seqs.append(pl["steps"])
            if isinstance(pl.get("domains"), list):
                seqs += [d["checks"] for d in pl["domains"] if isinstance(d.get("checks"), list)]
            for seq in seqs:
                for leaf in seq:
                    if not isinstance(leaf, dict):
                        continue
                    verd = leaf.get("verdict") or leaf.get("status")
                    for key in ("url", "final_url"):
                        u = _norm_url(leaf.get(key))
                        if u and verd:
                            leaf_by_url.setdefault(u, verd)

        # A check shared by >1 project (today: `chatbots`) must NOT stamp its
        # aggregate onto each tile — resolve each project to its own URL's leaf.
        shared_checks = {c for c, n in Counter(
            c for cs in projects.PROJECT_CHECKS.values() for c in cs).items() if n > 1}

        for p in projects.load_projects():
            slot = project_rollup.setdefault(p.name, {"liveness": [], "checks": []})
            for c in p.check_names:
                if c in shared_checks:
                    matched = [leaf_by_url[_norm_url(u.get("url"))]
                               for u in p.urls if _norm_url(u.get("url")) in leaf_by_url]
                    if matched:
                        slot["checks"].extend(matched)
                        continue   # this project's own surface(s) — done
                v = check_verdicts.get(c)
                if v:
                    slot["checks"].append(v)

        def _worst(verdicts: list[str]) -> str:
            # SLOW is dropped unless it's the only signal we have.
            real = [v for v in verdicts if v and v.upper() != "SLOW"]
            if not real:
                return "SLOW" if any((v or "").upper() == "SLOW" for v in verdicts) else "UNKNOWN"
            order = ["DOWN", "FAILED", "TIMEOUT", "ERROR",
                     "DEGRADED", "AUTH_EXPIRED",
                     "KNOWN-ISSUE", "UP", "HEALTHY"]
            ups = {v.upper(): v for v in real if v}
            for o in order:
                if o in ups: return ups[o]
            return real[0]

        project_verdicts: dict[str, str] = {}
        for name, slot in project_rollup.items():
            project_verdicts[name] = _worst(slot["liveness"] + slot["checks"])

        # ---- liveness — parallel signal, NOT merged into functional counts ----
        live_counts = data.get("liveness", {}).get("counts", {})

        return jsonify({
            "available": True,
            "started_ist": data.get("started_ist"),
            "ended_ist": data.get("ended_ist"),
            "total_duration_s": data.get("total_duration_s"),
            "auth_preflight": data.get("auth_preflight", {}),
            # Authoritative summary — use this for badges and headline counts.
            "summary": {
                "up":    leaf_counts["up"],
                "warn":  leaf_counts["warn"],
                "down":  leaf_counts["down"],
                "total": leaf_counts["total"],
            },
            # HTTP-only probe, shown as a separate informational chip
            "liveness_counts": live_counts,
            "projects": project_verdicts,
            "checks": check_verdicts,
        })

    return app


def _plan(kind: str, name: str | None, mode: str) -> tuple[str, list[JobStep]]:
    """Translate a UI request into a (title, [JobStep,...]) plan."""
    if kind == "sweep":
        return ("Complete sweep + dashboard refresh",
                [step_sweep(), step_dashboard()])

    if kind == "liveness":
        return ("Liveness sweep (HTTP only)", [step_liveness()])

    if kind == "dashboard":
        return ("Rebuild dashboard", [step_dashboard()])

    if kind == "env":
        checks = projects.env_checks(name or "")
        if not checks:
            return ("", [])
        return (f"{name} env sweep", [step_check(c) for c in checks])

    if kind == "check":
        if name not in set(projects.all_check_names()):
            return ("", [])
        return (f"Check: {name}", [step_check(name)])

    if kind == "project":
        # Resolve project → checks via the registry mapping. A liveness-only
        # project (e.g. UMANG Production) has no functional checks but is still
        # monitored by the HTTP sweep, so it can run liveness even with an empty
        # mapping — only the functional path requires proj_checks.
        proj_checks = projects.PROJECT_CHECKS.get(name or "") or []
        steps: list[JobStep] = []
        if mode in ("liveness", "all"):
            # Project-scoped liveness — for now we run the global liveness
            # (cheap, covers everything). A per-project filter could come later.
            steps.append(step_liveness())
        if mode in ("functional", "all"):
            steps.extend(step_check(c) for c in proj_checks)
        if not steps:
            return ("", [])
        return (f"Project: {name} ({mode})", steps)

    if kind == "login":
        if name not in ("prod", "dev", "umang"):
            return ("", [])
        return (f"OTP login: {name}", [step_login(name)])

    return ("", [])


def _is_loopback(host: str) -> bool:
    import ipaddress
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def serve(host: str = "127.0.0.1", port: int = 5050, open_browser: bool = True) -> None:
    app = create_app()
    url = f"http://{host}:{port}/"
    if not _is_loopback(host):
        print(f"[serve] WARNING: binding to non-loopback host {host!r}. The "
              f"control panel runs the Werkzeug development server and can "
              f"trigger checks/logins — do NOT expose it on an untrusted "
              f"network. Bind to 127.0.0.1 unless you really mean to.")
    print(f"[serve] hc control panel: {url}")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    # threaded=True so SSE long-poll connections don't block other requests.
    app.run(host=host, port=port, threaded=True, debug=False, use_reloader=False)


def main(argv: list[str] | None = None) -> int:
    """Entry point called from cli.py."""
    import argparse
    p = argparse.ArgumentParser(prog="hc serve", description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5050)
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args(argv)
    serve(host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
