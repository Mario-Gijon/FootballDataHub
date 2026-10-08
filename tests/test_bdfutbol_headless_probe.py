"""Offline, deterministic tests for the Hito -1 acquisition probe.

The real BDFutbol experiment is run separately on the user's machine; no
external requests are made by this test file.
"""
from __future__ import annotations

from email.message import Message
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from urllib.error import URLError
from urllib.request import Request

import pytest


PROBE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe_bdfutbol_headless.py"
spec = importlib.util.spec_from_file_location("probe_bdfutbol_headless", PROBE_SCRIPT)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_four_default_targets_are_known_bdfutbol_urls():
    assert len(probe.TARGETS) == 4
    assert all(probe.is_allowed_url(url) for url in probe.TARGETS.values())
    assert probe.TARGETS["team_real_jaen_2026_27"].endswith("t2026-2749.html")


@pytest.mark.parametrize("url", [
    "https://evil.example/es/j/j209629.html",
    "http://www.bdfutbol.com/es/j/j209629.html",
    "https://www.bdfutbol.com.evil.example/es/j/j209629.html",
    "file:///etc/passwd",
    "https://www.bdfutbol.com:8443/es/j/j209629.html",
    "https://admin:secret@www.bdfutbol.com/es/j/j209629.html",
])
def test_rejects_untrusted_origins(url):
    assert not probe.is_allowed_url(url)


def test_accepts_user_named_target():
    assert probe.parse_target("morillas=https://www.bdfutbol.com/es/j/j209629.html") == (
        "morillas", "https://www.bdfutbol.com/es/j/j209629.html"
    )


def test_rejects_duplicate_target_names():
    args = probe.build_parser().parse_args([
        "--url", "same=https://www.bdfutbol.com/es/e/e49.html",
        "--url", "same=https://www.bdfutbol.com/es/j/j209629.html",
    ])
    with pytest.raises(ValueError, match="repetido"):
        probe.build_targets(args)


def test_redacts_session_and_auth_query_and_fragments():
    url = "https://www.bdfutbol.com/es/e/e49.html?id=49&access_token=abc&session_id=xyz#private"
    redacted = probe.redact_url(url)
    assert "abc" not in redacted and "xyz" not in redacted and "#private" not in redacted
    assert "id=49" in redacted


@pytest.mark.parametrize("status,html,title,expected", [
    (200, "<html><body><h1>Jugador</h1>" + "A" * 350 + "</body></html>", "Morillas", "CONTENT_RECEIVED"),
    (200, "<h1>Just a moment...</h1>" + "x" * 400, "Just a moment...", "CHALLENGE_REQUIRED"),
    (403, "<h1>Access denied</h1>" + "x" * 400, "", "ACCESS_DENIED_OR_RATE_LIMITED"),
    (429, "<h1>Too Many Requests</h1>" + "x" * 400, "", "ACCESS_DENIED_OR_RATE_LIMITED"),
    (200, "<p>hello</p>", "", "INCONCLUSIVE"),
    (502, "<h1>Server error</h1>" + "x" * 400, "", "HTTP_ERROR"),
])
def test_classifies_response_semantically(status, html, title, expected):
    assert probe.classify_response(status, html, title) == expected


def test_html_summary():
    content = "<html><head><title>Real Jaén</title></head><body><h1>Equipo</h1><table></table><img src='x'><a href='x'>Link</a></body></html>"
    summary = probe.summarize_html(content)
    assert summary == {"title": "Real Jaén", "tables": 1, "links": 1, "images": 1, "headings": 1}


def test_same_origin_redirect_handler_blocks_foreign_hosts():
    req = Request("https://www.bdfutbol.com/es/j/j209629.html")
    with pytest.raises(URLError, match="fuera del origen"):
        probe.SameOriginRedirects().redirect_request(req, None, 302, "Found", {}, "https://example.com/")


def test_safe_actions_never_submit_or_navigate_to_other_pages():
    page = "https://www.bdfutbol.com/es/j/j209629.html"
    assert probe.safe_action({"kind": "tab", "tag": "a", "label": "Estadísticas",
                              "href": page + "?p=stats", "page_url": page}) is None
    assert probe.safe_action({"kind": "tab", "tag": "a", "label": "Estadísticas",
                              "href": page + "#stats", "page_url": page}) == ("click", "")
    assert probe.safe_action({"kind": "tab", "tag": "button", "label": "Enviar formulario"}) is None
    assert probe.safe_action({"kind": "other", "tag": "button", "label": "Comprar"}) is None
    assert probe.safe_action({"kind": "accordion", "tag": "button", "label": "Abrir",
                              "button_type": "submit", "form_method": "get"}) is None
    assert probe.safe_action({"kind": "gallery", "tag": "button", "label": "Siguiente foto"}) == ("click", "")


def test_pick_actions_samples_controls_without_bulk_clicks():
    controls = ([{"id": f"a{i}", "kind": "gallery", "tag": "button", "label": "Siguiente"} for i in range(10)]
                + [{"id": "s", "kind": "select", "tag": "select", "label": "Temporadas",
                    "options": [{"value": "", "text": "Elige"}, {"value": "2026-27", "text": "2026-27"}]}])
    selected = probe.pick_actions(controls, 5)
    assert len(selected) == 4
    assert sum(x["kind"] == "gallery" for x in selected) == 3
    assert sum(x["kind"] == "select" for x in selected) == 1
    assert probe.pick_actions(controls, 0) == []  # explicit zero means no interaction


class FakeHttpResponse:
    def __init__(self, *, status: int = 200) -> None:
        self.status = status
        self.headers = Message()
        self.headers.add_header("Content-Type", "text/html; charset=utf-8")

    def geturl(self) -> str:
        return "https://www.bdfutbol.com/es/e/e49.html"

    def read(self, limit: int) -> bytes:
        return ("<html><title>Jaén</title><h1>Jaén</h1>" + "x" * 500 + "</html>").encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def test_http_probe_writes_original_html_and_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "build_opener", lambda *args: SimpleNamespace(open=lambda *args, **kwargs: FakeHttpResponse()))
    result = probe.http_probe("club", "https://www.bdfutbol.com/es/e/e49.html", tmp_path, 1.0)
    assert result["verdict"] == "CONTENT_RECEIVED"
    assert result["evidence"]["saved"] is True
    assert (tmp_path / "http.html").exists()
    assert json.loads((tmp_path / "http.json").read_text())["status_code"] == 200


class FakeLocator:
    def __init__(self, page):
        self.page = page

    def count(self):
        return 1

    def is_visible(self):
        return True

    def click(self, **kwargs):
        self.page.did_click = True


class FakePage:
    def __init__(self):
        self.url = "https://www.bdfutbol.com/es/j/j209629.html"
        self.did_click = False
        self.listeners = {}

    def on(self, name, fn):
        self.listeners[name] = fn

    def goto(self, url, **kwargs):
        self.url = url
        return SimpleNamespace(status=200)

    def wait_for_timeout(self, ms):
        pass

    def title(self):
        return "Morillas"

    def content(self):
        return "<html><head><title>Morillas</title></head><body><h1>Morillas</h1>" + ("clicked" if self.did_click else "initial") + "x" * 450 + "</body></html>"

    def evaluate(self, _js):
        return {"url": self.url, "title": "Morillas", "controls": [
            {"id": "fdhp-1", "kind": "gallery", "tag": "button", "label": "Siguiente foto"}
        ], "counts": {"links": 5, "images": 2, "tables": 1}}

    def locator(self, selector):
        return FakeLocator(self)


class FakeContext:
    def __init__(self):
        self.page = FakePage()
        self.closed = False

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self):
        self.context = FakeContext()

    def new_context(self, **kwargs):
        return self.context


def test_headless_probe_clicks_one_gallery_control_and_preserves_snapshots(tmp_path):
    browser = FakeBrowser()
    args = SimpleNamespace(timeout_ms=5_000, settle_ms=0, max_actions=1, screenshots=False)
    result = probe.headless_probe("player", "https://www.bdfutbol.com/es/j/j209629.html", tmp_path, args, browser)
    assert result["verdict"] == "CONTENT_RECEIVED"
    assert result["actions"][0]["status"] == "EXECUTED"
    assert result["actions"][0]["changed_dom"] is True
    assert (tmp_path / "inventory_initial.json").exists()
    assert (tmp_path / "after_action_01.html").exists()
    assert browser.context.closed


def test_direct_cli_help_does_not_require_browser_or_network():
    run = subprocess.run([sys.executable, str(PROBE_SCRIPT), "--help"],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert "--max-actions" in run.stdout
    assert "--mode" in run.stdout


def test_main_http_creates_run_scoped_summary_offline(tmp_path, monkeypatch):
    def fake_http(name, url, folder, _timeout):
        return {"target": name, "verdict": "CONTENT_RECEIVED"}

    monkeypatch.setattr(probe, "http_probe", fake_http)
    status = probe.main(["--mode", "http", "--output", str(tmp_path),
                         "--url", "demo=https://www.bdfutbol.com/es/e/e49.html",
                         "--max-actions", "0"])
    assert status == 0
    runs = list(tmp_path.iterdir())
    assert len(runs) == 1
    summary = json.loads((runs[0] / "summary.json").read_text(encoding="utf-8"))
    assert summary["target_count"] == 1
    assert summary["targets"][0]["http"]["verdict"] == "CONTENT_RECEIVED"
