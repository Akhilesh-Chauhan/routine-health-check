"""Per-URL custom headers in the liveness sweep + ${ENV} placeholder resolution.

Added so authenticated liveness targets (e.g. UMANG prod APIs that require an
x-api-key) can be probed by the header-free HTTP sweep without baking secrets
into the committed registry.
"""
import json
from contextlib import contextmanager

from health_check.orchestration import master


def _write_registry(tmp_path, projects):
    p = tmp_path / "url_registry.json"
    p.write_text(json.dumps({"projects": projects}))
    return p


def test_load_registry_passes_headers_through(tmp_path, monkeypatch):
    reg = _write_registry(tmp_path, [
        {"name": "X", "urls": [
            {"label": "plain", "url": "https://a.example/"},
            {"label": "withhdr", "url": "https://b.example/",
             "headers": {"x-api-key": "literal123"}},
        ]},
    ])
    monkeypatch.setattr(master.paths, "URL_REGISTRY", reg)

    entries = master._load_url_registry()
    by_label = {e["label"]: e for e in entries}

    # absent headers -> no header key (back-compat: behaves exactly as before)
    assert "headers" not in by_label["plain"] or by_label["plain"]["headers"] == {}
    assert by_label["withhdr"]["headers"]["x-api-key"] == "literal123"


def test_load_registry_resolves_env_placeholders(tmp_path, monkeypatch):
    monkeypatch.setenv("UMANG_FACETS_KEY", "secret-from-env")
    reg = _write_registry(tmp_path, [
        {"name": "UMANG Production", "urls": [
            {"label": "facets", "url": "https://api.example/facets",
             "environment": "production",
             "headers": {"x-api-key": "${UMANG_FACETS_KEY}",
                         "origin": "https://web.umang.gov.in"}},
        ]},
    ])
    monkeypatch.setattr(master.paths, "URL_REGISTRY", reg)

    entry = master._load_url_registry()[0]
    assert entry["headers"]["x-api-key"] == "secret-from-env"
    # non-placeholder values pass through untouched
    assert entry["headers"]["origin"] == "https://web.umang.gov.in"


def test_hit_url_sends_custom_headers(monkeypatch):
    captured = {}

    @contextmanager
    def fake_urlopen(req, timeout=10):
        captured["headers"] = dict(req.headers)
        captured["url"] = req.full_url

        class _Resp:
            status = 200
        yield _Resp()

    monkeypatch.setattr(master.urlreq, "urlopen", fake_urlopen)

    entry = {"label": "facets", "url": "https://api.example/facets",
             "project": "UMANG Production", "environment": "production",
             "headers": {"x-api-key": "secret-from-env",
                         "origin": "https://web.umang.gov.in"}}
    out = master.hit_url(entry)

    assert out["status"] == "UP"
    assert out["http"] == 200
    # urllib title-cases header names
    assert captured["headers"].get("X-api-key") == "secret-from-env"
    assert captured["headers"].get("Origin") == "https://web.umang.gov.in"
    # default User-Agent still present
    assert "User-agent" in captured["headers"]


def test_hit_url_without_headers_still_works(monkeypatch):
    captured = {}

    @contextmanager
    def fake_urlopen(req, timeout=10):
        captured["headers"] = dict(req.headers)

        class _Resp:
            status = 200
        yield _Resp()

    monkeypatch.setattr(master.urlreq, "urlopen", fake_urlopen)

    entry = {"label": "page", "url": "https://web.example/",
             "project": "UMANG Production", "environment": "production"}
    out = master.hit_url(entry)

    assert out["status"] == "UP"
    assert captured["headers"].get("User-agent") == "healthcheck/1.0"
