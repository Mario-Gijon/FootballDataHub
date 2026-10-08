"""Pruebas sin acceso a BDFutbol del Hito 0A."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from football_data_hub.providers.bdfutbol.access import AccessAssessment, AccessStatus
from football_data_hub.providers.bdfutbol.discovery import (
    DOM_INVENTORY_JS,
    InventoryLimits,
    assert_safe_token,
    capture_dom_snapshot,
    classify_link,
    summarize_inventory,
    write_json,
)


KEYS = (
    "links", "tables", "images", "sources", "selects", "buttons", "tabs", "panels",
    "details", "custom_controls", "collapsible_panels", "forms",
    "galleries", "charts", "scripts", "iframes", "xhr"
)


def example_inventory() -> dict:
    result = {key: {"total": 0, "truncated": False, "items": []} for key in KEYS}
    result.update({
        "document": {"url": "https://www.bdfutbol.com/es/j/j209629.html", "title": "Morillas"},
        "links": {"total": 4, "truncated": False, "items": [
            {"href": "https://www.bdfutbol.com/es/j/j209629.html?p=stats"},
            {"href": "https://www.bdfutbol.com/es/p/j209629.html"},
            {"href": "https://example.org/"},
            {"href": "javascript:void(0)"},
        ]},
        "tables": {"total": 58, "truncated": False, "items": [{"id": "t1", "row_count": 10}]},
        "images": {"total": 3, "truncated": False, "items": []},
        "selects": {"total": 1, "truncated": False, "items": [
            {"id": "teams", "option_count": 3, "options_truncated": False}
        ]},
        "gallery_triggers": [{"text": "Fotos (4)"}],
    })
    return result


@pytest.fixture
def valid_assessment() -> AccessAssessment:
    return AccessAssessment(
        status=AccessStatus.VALID,
        requested_url="https://www.bdfutbol.com/es/j/j209629.html",
        final_url="https://www.bdfutbol.com/es/j/j209629.html",
        http_status=200,
        page_title="Morillas - Futbolista | BDFutbol",
    )


class FakePage:
    def __init__(self, inventory: dict | None = None) -> None:
        self.inventory = inventory if inventory is not None else example_inventory()
        self.script: str | None = None
        self.options: dict | None = None
        self.screenshot_calls = 0
        self.screenshot_error: Exception | None = None

    def evaluate(self, script: str, options: dict) -> dict:
        self.script = script
        self.options = options
        return self.inventory

    def content(self) -> str:
        return "<html><body>Morillas</body></html>"

    def screenshot(self, *, path: str, full_page: bool, timeout: int) -> None:
        self.screenshot_calls += 1
        if self.screenshot_error:
            raise self.screenshot_error
        Path(path).write_bytes(b"fake screenshot")


@pytest.mark.parametrize("url,expected", [
    ("https://www.bdfutbol.com/es/j/j209629.html?p=stats", "/es/j/"),
    ("https://bdfutbol.com/es/p/j209629.html", "/es/p/"),
    ("https://www.bdfutbol.com/es/t/t2026-271rf1.html", "/es/t/"),
    ("https://www.bdfutbol.com/", "/"),
    ("https://evil-bdfutbol.com/es/j/test", "external"),
    ("https://another.test/a", "external"),
    ("javascript:alert(1)", "other_scheme"),
])
def test_classify_link(url: str, expected: str) -> None:
    assert classify_link(url) == expected


@pytest.mark.parametrize("token", ["morillas", "morillas_stats", "club-1", "a5"])
def test_safe_token(token: str) -> None:
    assert assert_safe_token(token) == token


@pytest.mark.parametrize("token", ["", "../tmp", "/tmp", "UPPER", "name with spaces", "a" * 65])
def test_unsafe_token(token: str) -> None:
    with pytest.raises(ValueError):
        assert_safe_token(token)


def test_limits_as_js_options() -> None:
    assert InventoryLimits(max_links=11, max_controls=12).as_js_options()["maxLinks"] == 11
    assert InventoryLimits(max_links=11, max_controls=12).as_js_options()["maxControls"] == 12


@pytest.mark.parametrize("limit", [0, -1, 10001])
def test_invalid_limits(limit: int) -> None:
    with pytest.raises(ValueError):
        InventoryLimits(max_links=limit)


def test_summary_refuses_complete() -> None:
    report = summarize_inventory(example_inventory())
    assert report["complete"] is False
    assert report["scope"] == "DOM_SNAPSHOT_ONLY"
    assert report["interaction_coverage"] == "NOT_TESTED"
    assert report["counts"]["tables"] == 58
    assert report["counts"]["images"] == 3
    assert report["counts"]["custom_controls"] == 0
    assert report["gallery_trigger_candidates"] == 1
    assert report["link_families_in_recorded_sample"]["/es/j/"] == 1
    assert report["link_families_in_recorded_sample"]["/es/p/"] == 1
    assert report["link_families_in_recorded_sample"]["external"] == 1


def test_summary_warns_truncation() -> None:
    inv = example_inventory()
    inv["links"]["truncated"] = True
    inv["selects"]["items"][0]["options_truncated"] = True
    summary = summarize_inventory(inv)
    assert "links" in summary["truncated_collections"]
    assert "teams" in summary["truncated_select_options"]
    assert len(summary["coverage_warnings"]) == 2


def test_malformed_inventory_rejected() -> None:
    inv = example_inventory()
    inv["buttons"] = []
    with pytest.raises(ValueError, match="buttons"):
        summarize_inventory(inv)


def test_dom_snapshot_writes_complete_files(tmp_path: Path, valid_assessment: AccessAssessment) -> None:
    page = FakePage()
    destination = tmp_path / "one"
    report = capture_dom_snapshot(page=page, assessment=valid_assessment, output_dir=destination)
    assert page.options is not None and page.options["maxOptions"] == 500
    assert page.script == DOM_INVENTORY_JS
    assert (destination / "rendered.html").read_text() == page.content()
    inventory = json.loads((destination / "inventory.json").read_text())
    assert inventory["tables"]["total"] == 58
    metadata = json.loads((destination / "metadata.json").read_text())
    assert metadata["rendered_html_sha256"] == hashlib.sha256(page.content().encode()).hexdigest()
    assert metadata["access_status"] == "VALID"
    assert report["inventory_summary"]["complete"] is False
    assert not (destination / "screenshot.png").exists()
    assert not (destination / "INCOMPLETE").exists()


def test_snapshot_with_screenshot(tmp_path: Path, valid_assessment: AccessAssessment) -> None:
    page = FakePage()
    capture_dom_snapshot(
        page=page, assessment=valid_assessment, output_dir=tmp_path / "run", screenshot=True
    )
    assert page.screenshot_calls == 1
    assert (tmp_path / "run" / "screenshot.png").exists()


def test_screenshot_failure_does_not_invalidate_raw(tmp_path: Path, valid_assessment: AccessAssessment) -> None:
    page = FakePage()
    page.screenshot_error = RuntimeError("test screenshot")
    capture_dom_snapshot(
        page=page, assessment=valid_assessment, output_dir=tmp_path / "run", screenshot=True
    )
    data = json.loads((tmp_path / "run" / "metadata.json").read_text())
    assert "test screenshot" in data["screenshot_error"]
    assert (tmp_path / "run" / "rendered.html").exists()


def test_no_overwrite(tmp_path: Path, valid_assessment: AccessAssessment) -> None:
    page = FakePage()
    destination = tmp_path / "run"
    capture_dom_snapshot(page=page, assessment=valid_assessment, output_dir=destination)
    with pytest.raises(FileExistsError):
        capture_dom_snapshot(page=page, assessment=valid_assessment, output_dir=destination)


def test_blocked_cannot_be_captured(tmp_path: Path, valid_assessment: AccessAssessment) -> None:
    blocked = AccessAssessment(
        status=AccessStatus.CHALLENGE_REQUIRED,
        requested_url=valid_assessment.requested_url,
        final_url=valid_assessment.final_url,
        http_status=403,
        page_title="Un momento…",
    )
    with pytest.raises(ValueError, match="bloqueado"):
        capture_dom_snapshot(page=FakePage(), assessment=blocked, output_dir=tmp_path / "not_created")
    assert not (tmp_path / "not_created").exists()


def test_snapshot_incomplete_marker_on_failure(tmp_path: Path, valid_assessment: AccessAssessment) -> None:
    page = FakePage()
    page.inventory["tables"] = []
    with pytest.raises(ValueError):
        capture_dom_snapshot(page=page, assessment=valid_assessment, output_dir=tmp_path / "bad")
    assert (tmp_path / "bad" / "INCOMPLETE").is_file()
    assert not (tmp_path / "bad" / "metadata.json").exists()


def test_write_json_utf8(tmp_path: Path) -> None:
    dest = tmp_path / "one" / "informe.json"
    write_json(dest, {"jugador": "Morillas", "texto": "España"})
    assert json.loads(dest.read_text(encoding="utf-8"))["texto"] == "España"
    assert list(dest.parent.glob(".*")) == []


def test_cli_default_target_and_opts() -> None:
    from discover_bdfutbol_page import parse_args
    args = parse_args([])
    assert args.target is None
    assert args.max_links == 1500
    assert args.screenshots is False


def test_cli_reject_unknown_target() -> None:
    from discover_bdfutbol_page import parse_args
    with pytest.raises(SystemExit):
        parse_args(["--target", "other"])


def test_cli_invalid_limits_fail_before_browser(tmp_path: Path) -> None:
    from discover_bdfutbol_page import parse_args, run
    args = parse_args(["--max-links", "0", "--raw-root", str(tmp_path / "raw")])
    with pytest.raises(ValueError):
        run(args)
    assert not (tmp_path / "raw").exists()


def test_cli_success_with_fake_browser(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, valid_assessment: AccessAssessment) -> None:
    import discover_bdfutbol_page as cli

    page = FakePage()
    calls = []
    class FakeSession:
        def __init__(self, config: object) -> None:
            calls.append("session")
        def __enter__(self):
            return self
        def __exit__(self, *_):
            calls.append("close")
    class FakeAccess:
        def __init__(self, session: FakeSession):
            pass
        def open(self, url: str, *, required_markers: tuple[str, ...], settle_ms: int):
            calls.append(url)
            return FakeVisit(valid_assessment, page)
    class FakeVisit:
        def __init__(self, assessment, page):
            self.assessment = assessment
            self.visit = SimpleNamespace(page=page)
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass

    monkeypatch.setattr(cli, "BrowserSessionManager", FakeSession)
    monkeypatch.setattr(cli, "BDFutbolAccess", FakeAccess)
    args = cli.parse_args([
        "--target", "morillas", "--target", "morillas",
        "--raw-root", str(tmp_path / "raw"),
        "--analysis-root", str(tmp_path / "analysis"),
    ])
    assert cli.run(args) == 0
    assert calls.count(cli.TARGETS["morillas"].url) == 1
    summaries = list((tmp_path / "analysis").glob("*/summary.json"))
    assert len(summaries) == 1
    summary = json.loads(summaries[0].read_text())
    assert summary["complete"] is False
    assert len(summary["results"]) == 1
    assert summary["results"][0]["summary"]["counts"]["tables"] == 58


def test_cli_blocked_stops_without_snapshot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import discover_bdfutbol_page as cli
    calls = []
    class FakeSession:
        def __init__(self, config): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
    class FakeAccess:
        def __init__(self, session): pass
        def open(self, url, *, required_markers, settle_ms):
            calls.append(url)
            blocked = AccessAssessment(
                AccessStatus.CHALLENGE_REQUIRED, url, url, 403, "Un momento…"
            )
            return SimpleNamespace(
                assessment=blocked, visit=None,
                __enter__=lambda _: _, __exit__=lambda *a: None,
            )
    class FakeVisit:
        def __init__(self, url):
            self.assessment = AccessAssessment(AccessStatus.CHALLENGE_REQUIRED,
                                               url, url, 403, "Un momento…")
            self.visit = None
        def __enter__(self): return self
        def __exit__(self, *_): pass
    def make_access(session):
        class FakeA:
            def open(self, url, *, required_markers, settle_ms):
                calls.append(url)
                return FakeVisit(url)
        return FakeA()
    monkeypatch.setattr(cli, "BrowserSessionManager", FakeSession)
    monkeypatch.setattr(cli, "BDFutbolAccess", make_access)
    args = cli.parse_args([
        "--target", "morillas", "--target", "morillas_stats",
        "--raw-root", str(tmp_path / "raw"),
        "--analysis-root", str(tmp_path / "analysis"),
    ])
    assert cli.run(args) == 4
    assert len(calls) == 1
    assert list((tmp_path / "raw").glob("*/*")) == []
    summary_files = list((tmp_path / "analysis").glob("*/summary.json"))
    assert len(summary_files) == 1
    summary = json.loads(summary_files[0].read_text())
    assert summary["results"][0]["assessment"]["status"] == "CHALLENGE_REQUIRED"


def test_dom_inventory_is_readonly_by_contract() -> None:
    # El script inventaría; los métodos de interacción se reservan al Hito 0B.
    assert "querySelectorAll" in DOM_INVENTORY_JS
    assert "getEntriesByType" in DOM_INVENTORY_JS
    for forbidden in (".click(", "dispatchEvent(", ".submit(", ".setAttribute(", "fetch("):
        assert forbidden not in DOM_INVENTORY_JS
