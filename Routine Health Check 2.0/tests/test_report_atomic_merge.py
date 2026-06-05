"""Phase 4: the report merge must be a single-writer, atomic read-modify-write.

Many `hc check <name>` runs (and a full sweep) can race to merge into the one
`master_report.json`. Without a lock, concurrent read-modify-write loses updates
(or yields invalid JSON) — the status-churn source this gate closes.
"""
import json, threading

from health_check import paths
from health_check.orchestration import master


def test_concurrent_merges_are_atomic(monkeypatch, tmp_path):
    rep = tmp_path / "master_report.json"
    rep.write_text(json.dumps({"scripts": []}))
    monkeypatch.setattr(paths, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(paths, "MASTER_REPORT", rep)
    mods = [f"health_check.checks.public.bot{i}" for i in range(20)]

    def merge(m):
        master.merge_script_result(m, json.dumps({"bots": [{"verdict": "UP"}]}), 0, 1.0)

    ts = [threading.Thread(target=merge, args=(m,)) for m in mods]
    [t.start() for t in ts]
    [t.join() for t in ts]
    scripts = json.loads(rep.read_text())["scripts"]
    assert len({s["filename"] for s in scripts}) == 20  # no lost updates, valid JSON
