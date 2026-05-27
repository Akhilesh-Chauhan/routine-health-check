"""Flask app for the `hc serve` control panel."""
from __future__ import annotations

import json
import webbrowser
from pathlib import Path

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
        )

    @app.post("/run")
    def run():
        """Body: {kind: 'sweep'|'env'|'project'|'check'|'liveness'|'login'|'dashboard', name?: str, mode?: 'liveness'|'functional'|'all'}."""
        payload = request.get_json(force=True) or {}
        kind = payload.get("kind")
        name = payload.get("name")
        mode = payload.get("mode", "all")

        title, steps = _plan(kind, name, mode)
        if not steps:
            return jsonify({"error": f"unknown job kind={kind} name={name}"}), 400

        job = runner.submit(title, steps)
        return jsonify({"job_id": job.id, "title": job.title})

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
        return Response(rep.read_text(), mimetype="application/json")

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
        data = json.loads(rep_path.read_text())

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

        def _classify(v: str | None) -> str:
            if not v: return "unknown"
            s = str(v).upper()
            if "HEALTHY" in s or s in ("UP", "PASS", "PASSED"): return "up"
            if "AUTH_EXPIRED" in s or "DEGRADED" in s:           return "warn"
            if ("DOWN" in s or "FAIL" in s
                or s in ("TIMEOUT", "ERROR", "MISSING")):        return "down"
            return "unknown"

        leaf_counts = {"up": 0, "warn": 0, "down": 0, "unknown": 0, "total": 0}
        for s in data.get("scripts", []):
            for v in _walk_leaves(s):
                leaf_counts["total"] += 1
                leaf_counts[_classify(v)] += 1

        # ---- per-project verdicts ----
        # Aggregate liveness rows + functional checks per project, then
        # compute a single "worst" verdict. SLOW is informational only —
        # it never trumps a real functional verdict (so a SLOW URL probe
        # for cms.myscheme.gov.in does NOT make the CMS project tile yellow
        # when the functional CMS check is HEALTHY).
        project_rollup: dict[str, dict] = {}
        for row in data.get("liveness", {}).get("results", []):
            pname = row.get("project")
            if not pname:
                continue
            slot = project_rollup.setdefault(pname, {"liveness": [], "checks": []})
            slot["liveness"].append(row.get("status"))

        for p in projects.load_projects():
            slot = project_rollup.setdefault(p.name, {"liveness": [], "checks": []})
            for c in p.check_names:
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
        # Resolve project → checks via the registry mapping.
        proj_checks = projects.PROJECT_CHECKS.get(name or "")
        if not proj_checks:
            return ("", [])
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


def serve(host: str = "127.0.0.1", port: int = 5050, open_browser: bool = True) -> None:
    app = create_app()
    url = f"http://{host}:{port}/"
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
