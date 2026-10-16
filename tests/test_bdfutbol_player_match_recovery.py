from __future__ import annotations

import hashlib
import json
import gzip
from pathlib import Path

import pytest

import football_data_hub.providers.bdfutbol.players.catalog as player_catalog
from football_data_hub.providers.bdfutbol.players.capture_store import PlayerCaptureStore
from football_data_hub.providers.bdfutbol.players.acquisition import acquire_player_views
from football_data_hub.providers.bdfutbol.players.catalog import (
    build_player_acquisition_progress,
    find_valid_base_snapshot,
)
from football_data_hub.providers.bdfutbol.players.export import build_player_capture_export
from football_data_hub.providers.bdfutbol.players.models import PlayerMatchesPage
from football_data_hub.providers.bdfutbol.players.parsers import parse_player_html
from football_data_hub.providers.bdfutbol.players.html_parser import PLAYER_PARSER_VERSION


def _p_row(
    match_id: int,
    *,
    category: str = "1rf",
    flags: tuple[int, int, int] = (1, 0, 0),
    summoned: int = 0,
) -> list[object]:
    return [
        2025, category, "", "01/09/2025", 1, "Jaén", 1, 0, match_id,
        *flags, 90, summoned, 0, 0, 0, 0, "Rival FC", 49, 55,
        "1", 0, 0, "Jornada 1", "1", "2025-26",
    ]


def _matches_html(player_id: int, p_rows: list[list[object]], *, rendered: bool = False) -> str:
    title = "Test Player, Test Full Name | BDFutbol"
    identity = (
        f"<title>{title}</title><h1>Test Player</h1>"
        f'<a href="/es/j/j{player_id}.html">Perfil</a>'
    )
    summaries = "".join(
        f'<table id="{table_id}" class="taula_estil"><tr><th>Comp</th><th>PJ</th></tr>'
        "<tr><td>1ª RFEF</td><td>1</td></tr></table>"
        for table_id in ("t2", "t1", "t55", "t5")
    )
    if rendered:
        table = (
            '<table id="tpartits" class="taula_estil"><thead><tr>'
            '<th data-colid="data">Fecha</th><th data-colid="e1">Local</th>'
            '<th data-colid="res">Marcador</th><th data-colid="e2">Visitante</th>'
            "</tr></thead><tbody><tr><td>01/09/2025</td><td>Jaén</td>"
            '<td><a href="/es/p/p.php?id=271000">1 0</a></td><td>Rival FC</td>'
            "</tr><tr><td></td><td>Total 1</td><td></td><td></td></tr></tbody></table>"
        )
    else:
        table = (
            '<table id="tpartits" class="taula_estil"><thead><tr>'
            "<th>Fecha</th><th>Local</th><th>Resultado</th><th>Visitante</th>"
            "</tr></thead><tbody></tbody></table>"
        )
    raw_p = json.dumps(p_rows, separators=(",", ":"))
    return (
        f"<html><head>{identity}</head><body>{summaries}{table}"
        f"<script>window.P={raw_p};</script></body></html>"
    )


def _catalog_profile_html() -> str:
    return (
        "<html><head><title>Test Player, Test Full Name | BDFutbol</title>"
        "</head><body><h1>Test Player</h1>"
        '<table class="taula_estil traject"><thead><tr><th>Temp</th><th>Equipo</th>'
        "<th>País</th><th>Div</th><th>Edad</th><th>PJ</th></tr></thead><tbody>"
        "<tr><td>2026-27</td><td>Test FC</td><td>España</td><td>1ªRf</td>"
        "<td>20</td><td>0</td></tr></tbody></table></body></html>"
    )


def _metadata(
    html: str,
    url: str,
    *,
    snapshot_kind: str = "BASE_VIEW",
    filter_parameters: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "player_id": 12345,
        "view": "matches",
        "access_status": "VALID",
        "http_status": 200,
        "requested_url": url,
        "final_url": url,
        "captured_at_utc": "2026-10-14T10:00:00Z",
        "html_sha256": hashlib.sha256(html.encode()).hexdigest(),
        "filter_parameters": filter_parameters or {},
        "snapshot_kind": snapshot_kind,
        "is_base_view_snapshot": snapshot_kind == "BASE_VIEW",
    }


def test_window_p_base_snapshot_yields_match_records_and_keeps_nonparticipation() -> None:
    url = "https://www.bdfutbol.com/es/p/j12345.html"
    rows = [
        _p_row(271000, flags=(1, 0, 0)),
        _p_row(271001, flags=(0, 0, 0), summoned=1),
    ]
    html = _matches_html(12345, rows)
    page = parse_player_html(
        html,
        _metadata(html, url),
        expected_player_id=12345,
        expected_names=("Test Player",),
    )
    assert isinstance(page, PlayerMatchesPage)
    assert page.individual_matches_source == "WINDOW_P"
    assert page.window_p_parse_status == "PARSED_27_FIELD_TUPLES"
    assert page.window_p_record_count == 2
    assert page.detail_coverage.endswith("BASE_TPARTITS_HEADER_ONLY")
    appeared, called_up = page.individual_matches
    assert appeared["match_id"] == "271000"
    assert appeared["player_appearance_status"] == "APPEARED_PER_SOURCE_FLAGS"
    assert appeared["source_values_raw"] == rows[0]
    assert appeared["player_team_side_raw"] == "home"
    assert called_up["player_appearance_status"] == "NO_APPEARANCE_PER_SOURCE_FLAGS"
    assert called_up["player_summoned_status"] == "SUMMONED_WITHOUT_APPEARANCE_PER_SOURCE_FLAG"
    assert called_up["minutes"] == 90  # Minutes alone do not override the source flags.
    assert page.exhaustiveness_status == "SNAPSHOT_SCOPE_ONLY_NOT_CERTIFIED_COMPLETE"


def test_cat_url_variant_uses_rendered_table_subset_not_all_embedded_p_rows() -> None:
    url = "https://www.bdfutbol.com/es/p/j12345.html?cat=1rf"
    html = _matches_html(12345, [_p_row(271000), _p_row(271002)], rendered=True)
    page = parse_player_html(
        html,
        _metadata(html, url, snapshot_kind="URL_VARIANT", filter_parameters={"cat": "1rf"}),
        expected_player_id=12345,
        expected_names=("Test Player",),
    )
    assert isinstance(page, PlayerMatchesPage)
    assert page.filtered_view
    assert page.filter_parameters == {"cat": "1rf"}
    assert page.individual_matches_source == "TPARTITS"
    assert page.window_p_record_count == 2
    assert [row["match_id"] for row in page.individual_matches] == ["271000"]
    assert page.coverage["match_detail_scope"] == "TPARTITS_RENDERED_ROWS_NOT_CERTIFIED_COMPLETE"
    fixture_table = next(table for table in page.tables if table["table_id"] == "tpartits")
    assert fixture_table["total_row_count"] == 1


def test_unrecognized_window_p_tuple_width_does_not_create_fixtures() -> None:
    url = "https://www.bdfutbol.com/es/p/j12345.html"
    html = _matches_html(12345, [[1, "unknown-width"]])
    page = parse_player_html(
        html,
        _metadata(html, url),
        expected_player_id=12345,
        expected_names=("Test Player",),
    )
    assert isinstance(page, PlayerMatchesPage)
    assert page.individual_matches == []
    assert page.window_p_parse_status == "UNSUPPORTED_TUPLE_WIDTH"


def test_export_deduplicates_player_match_across_base_and_url_variant(tmp_path: Path) -> None:
    store = PlayerCaptureStore(tmp_path / "captures", capture_id="match-dedupe")
    base_url = "https://www.bdfutbol.com/es/p/j12345.html"
    variant_url = f"{base_url}?cat=1rf"
    p_rows = [_p_row(271000)]
    base_html = _matches_html(12345, p_rows)
    store.save_snapshot(
        player_id=12345, view="matches", requested_url=base_url, final_url=base_url,
        http_status=200, page_title="Test Player", html=base_html,
        browser={"backend": "test"},
    )
    variant_html = _matches_html(12345, p_rows, rendered=True)
    store.save_snapshot(
        player_id=12345, view="matches", requested_url=variant_url, final_url=variant_url,
        http_status=200, page_title="Test Player", html=variant_html,
        browser={"backend": "test"}, snapshot_kind="URL_VARIANT",
        filter_parameters={"cat": "1rf"},
    )
    store.mark_complete()
    inventory = tmp_path / "players.json"
    inventory.write_text(json.dumps({"records": [{
        "player_id": 12345,
        "display_name": "Test Player",
        "full_name": "Test Full Name",
    }]}), encoding="utf-8")
    result = build_player_capture_export(
        capture_dir=store.run_dir,
        inventory_path=inventory,
        derivation_id="dedupe-test",
    )
    destination = store.run_dir / "normalized/derivations/dedupe-test/individual_matches.json"
    matches = json.loads(destination.read_text(encoding="utf-8"))
    assert result["individual_match_source_record_count"] == 2
    assert result["individual_match_record_count"] == 1
    assert matches["deduplication"]["duplicate_records_across_snapshots"] == 1
    row = next(item for item in matches["records"] if item["match_id"] == "271000")
    assert row["source_record_count"] == 2
    assert len(row["sources"]) == 2
    assert matches["completeness_status"] == "SNAPSHOTS_ONLY_NOT_CERTIFIED_COMPLETE"


def test_catalog_reconciles_reusable_views_and_cohorts_atomically(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    store = PlayerCaptureStore(root, capture_id="catalog-run")
    url = "https://www.bdfutbol.com/es/j/j12345.html"
    html = _catalog_profile_html()
    saved = store.save_snapshot(
        player_id=12345, view="profile", requested_url=url, final_url=url,
        http_status=200, page_title="Test Player", html=html,
        browser={"backend": "test"},
    )
    parse_player_html(html, saved, expected_player_id=12345, expected_names=("Test Player",))
    store.record_snapshot_validation(
        saved["snapshot_id"], status="VALID", parser_version=PLAYER_PARSER_VERSION,
    )
    store.mark_complete()
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"records": [
        {"player_id": 12345, "display_name": "Test Player", "membership_count": 1, "groups": ["II"]},
        {"player_id": 54321, "display_name": "Transfer Only", "membership_count": 0, "groups": ["I"]},
    ]}), encoding="utf-8")
    output = root / "acquisition-progress-2026-27.json"
    progress = build_player_acquisition_progress(
        inventory_path=inventory,
        capture_root=root,
        output_path=output,
    )
    assert progress["summary"] == {
        "inventory_players": 2,
        "roster_players": 1,
        "transfer_only_players": 1,
        "players_with_all_base_views": 0,
        "roster_players_with_all_base_views": 0,
        "transfer_only_players_with_all_base_views": 0,
        "players_pending": 2,
        "base_view_navigations_pending": 7,
        "captured_valid_base_views": 1,
        "players_with_access_errors": 0,
        "blocked_base_views": 0,
        "retryable_navigation_errors": 0,
    }
    assert progress["pending_player_ids"] == [12345, 54321]
    assert find_valid_base_snapshot(
        root, player_id=12345, view="profile", expected_names=("Test Player",),
    ) is not None
    assert find_valid_base_snapshot(
        root, player_id=12345, view="profile", expected_names=("Wrong Player",),
    ) is None
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["summary"] == progress["summary"]
    assert saved["inventory"]["sha256"] == hashlib.sha256(inventory.read_bytes()).hexdigest()


def test_progress_allows_disk_pause_resume_but_keeps_http_404_unresolved(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"records": [
        {"player_id": 501, "display_name": "Player 501", "membership_count": 1},
    ]}), encoding="utf-8")
    disk_run = PlayerCaptureStore(root, capture_id="disk-low")
    disk_run.record_diagnostic({
        "error_code": "DISK_SPACE_LOW",
        "player_id": 501,
        "view": "profile",
        "requested_url": "https://www.bdfutbol.com/es/j/j501.html",
        "stop_acquisition": True,
    })
    progress = build_player_acquisition_progress(inventory_path=inventory, capture_root=root)
    assert progress["summary"]["players_with_access_errors"] == 0
    assert progress["summary"]["players_pending"] == 1

    http_run = PlayerCaptureStore(root, capture_id="http-404")
    http_run.record_diagnostic({
        "error_code": "HTTP_404_STOPPED",
        "access_status": "HTTP_ERROR",
        "http_status": 404,
        "player_id": 501,
        "view": "profile",
        "requested_url": "https://www.bdfutbol.com/es/j/j501.html",
        "stop_acquisition": True,
    })
    progress = build_player_acquisition_progress(inventory_path=inventory, capture_root=root)
    assert progress["summary"]["players_with_access_errors"] == 1
    assert progress["summary"]["blocked_base_views"] == 1
    assert progress["retryable_navigation_errors"] == []


def test_progress_coalesces_timeout_event_and_diagnostic_for_one_explicit_retry(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"records": [{
        "player_id": 27659, "display_name": "Player Timeout", "membership_count": 1,
    }]}), encoding="utf-8")
    run = PlayerCaptureStore(root, capture_id="timeout-run")
    event = {
        "player_id": 27659,
        "view": "rivals",
        "requested_url": "https://www.bdfutbol.com/es/p/jr27659.html",
        "final_url": None,
        "http_status": None,
        "access_status": "NAVIGATION_ERROR",
        "reason": "TimeoutError: navigation timed out",
        "captured_at_utc": "2026-10-16T09:02:10.478628Z",
        "navigation_purpose": "base_view_capture",
    }
    run.record_navigation(event)
    run.record_diagnostic({
        **event,
        "error_code": "NAVIGATION_ERROR",
        "failure_stage": "access_assessment",
        "classification": "unverified_http_or_content_error",
        "policy": "STOP_ON_UNVERIFIED_HTTP_ERROR",
        "stop_acquisition": True,
    })
    progress = build_player_acquisition_progress(
        inventory_path=inventory, capture_root=root,
    )
    assert progress["summary"]["players_with_access_errors"] == 1
    assert progress["summary"]["retryable_navigation_errors"] == 1
    assert len(progress["players"][0]["access_issues"]["rivals"]) == 1
    assert progress["retryable_navigation_errors"][0]["capture_id"] == "timeout-run"
    assert progress["pending_views"] == [
        {"player_id": 27659, "view": view}
        for view in ("profile", "statistics", "matches", "rivals")
    ]


@pytest.mark.parametrize(
    ("status", "http_status", "error_code", "reason", "extra"),
    [
        ("HTTP_ERROR", 403, "HTTP_403_STOPPED", "HTTP 403", {}),
        ("HTTP_ERROR", 429, "HTTP_429_STOPPED", "HTTP 429", {}),
        ("STRUCTURE_ERROR", 200, "STRUCTURE_ERROR", "missing table", {}),
        ("CHALLENGE_REQUIRED", 200, "CHALLENGE_REQUIRED", "challenge", {}),
        ("NAVIGATION_ERROR", None, "NAVIGATION_ERROR", "TimeoutError: timeout", {"missing_selectors": ["h1"]}),
        ("NAVIGATION_ERROR", None, "NAVIGATION_ERROR", "RuntimeError: connection closed", {}),
    ],
)
def test_only_unconfirmed_timeout_without_structural_or_access_evidence_is_retryable(
    tmp_path: Path,
    status: str,
    http_status: int | None,
    error_code: str,
    reason: str,
    extra: dict,
) -> None:
    root = tmp_path / "captures"
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"records": [{
        "player_id": 501, "display_name": "Player 501", "membership_count": 1,
    }]}), encoding="utf-8")
    run = PlayerCaptureStore(root, capture_id="blocked-run")
    run.record_diagnostic({
        "player_id": 501, "view": "rivals",
        "requested_url": "https://www.bdfutbol.com/es/p/jr501.html",
        "final_url": None, "http_status": http_status, "access_status": status,
        "reason": reason, "captured_at_utc": "2026-10-16T10:00:00Z",
        "error_code": error_code, "failure_stage": "access_assessment",
        "classification": "unverified_http_or_content_error",
        "policy": "STOP_ON_UNVERIFIED_HTTP_ERROR", "stop_acquisition": True,
        **extra,
    })
    progress = build_player_acquisition_progress(inventory_path=inventory, capture_root=root)
    assert progress["retryable_navigation_errors"] == []


def test_second_timeout_attempt_is_not_eligible_for_another_retry(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"records": [{
        "player_id": 501, "display_name": "Player 501", "membership_count": 1,
    }]}), encoding="utf-8")
    for capture_id, timestamp in (
        ("first-timeout", "2026-10-16T10:00:00Z"),
        ("second-timeout", "2026-10-16T10:05:00Z"),
    ):
        run = PlayerCaptureStore(root, capture_id=capture_id)
        run.record_diagnostic({
            "player_id": 501, "view": "rivals",
            "requested_url": "https://www.bdfutbol.com/es/p/jr501.html",
            "final_url": None, "http_status": None, "access_status": "NAVIGATION_ERROR",
            "reason": "TimeoutError: navigation timed out", "captured_at_utc": timestamp,
            "error_code": "NAVIGATION_ERROR", "failure_stage": "access_assessment",
            "classification": "unverified_http_or_content_error",
            "policy": "STOP_ON_UNVERIFIED_HTTP_ERROR", "stop_acquisition": True,
        })
    progress = build_player_acquisition_progress(inventory_path=inventory, capture_root=root)
    assert progress["summary"]["retryable_navigation_errors"] == 2


def test_valid_snapshot_reconciliation_is_idempotent_and_reports_progress(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "captures"
    run = PlayerCaptureStore(root, capture_id="speed-run")
    url = "https://www.bdfutbol.com/es/j/j12345.html"
    html = _catalog_profile_html()
    for _ in range(12):
        saved = run.save_snapshot(
            player_id=12345, view="profile", requested_url=url, final_url=url,
            http_status=200, page_title="Test Player", html=html,
            browser={"backend": "fixture"},
        )
        parse_player_html(html, saved, expected_player_id=12345, expected_names=("Test Player",))
        run.record_snapshot_validation(
            saved["snapshot_id"], status="VALID", parser_version=PLAYER_PARSER_VERSION,
        )
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"records": [{
        "player_id": 12345, "display_name": "Test Player", "membership_count": 1,
    }]}), encoding="utf-8")
    inventory_raw = inventory.read_bytes()
    run.record_inventory_source({
        "path": str(inventory), "sha256": hashlib.sha256(inventory_raw).hexdigest(),
        "season": "2026-27",
    })
    monkeypatch.setattr(
        player_catalog,
        "parse_player_html",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("valid parser proof was reparsed")),
    )
    events: list[dict] = []
    first = build_player_acquisition_progress(
        inventory_path=inventory, capture_root=root, progress_callback=events.append,
    )
    second = build_player_acquisition_progress(inventory_path=inventory, capture_root=root)
    assert first["summary"] == second["summary"]
    assert first["players"][0]["view_snapshots"] == second["players"][0]["view_snapshots"]
    assert events[0]["phase"] == "manifest_scan_started"
    assert events[-1]["phase"] == "manifest_complete"
    assert events[-1]["snapshots_processed"] == 12
    assert events[-1]["snapshots_verified"] == 12


def test_corrupted_raw_snapshot_is_not_reused_or_hidden_by_parser_proof(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    run = PlayerCaptureStore(root, capture_id="corrupt-run")
    url = "https://www.bdfutbol.com/es/j/j12345.html"
    html = _catalog_profile_html()
    saved = run.save_snapshot(
        player_id=12345, view="profile", requested_url=url, final_url=url,
        http_status=200, page_title="Test Player", html=html,
        browser={"backend": "fixture"},
    )
    parse_player_html(html, saved, expected_player_id=12345, expected_names=("Test Player",))
    run.record_snapshot_validation(
        saved["snapshot_id"], status="VALID", parser_version=PLAYER_PARSER_VERSION,
    )
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"records": [{
        "player_id": 12345, "display_name": "Test Player", "membership_count": 1,
    }]}), encoding="utf-8")
    before = build_player_acquisition_progress(inventory_path=inventory, capture_root=root)
    raw_path = run.run_dir / run.manifest["snapshots"][0]["raw_path"]
    damaged_html = gzip.decompress(raw_path.read_bytes()).replace(b"Test Player", b"Other Player")
    raw_path.write_bytes(gzip.compress(damaged_html, mtime=0))
    after = build_player_acquisition_progress(inventory_path=inventory, capture_root=root)
    assert before["summary"]["captured_valid_base_views"] == 1
    assert after["summary"]["captured_valid_base_views"] == 0
    assert {"player_id": 12345, "view": "profile"} in after["pending_views"]
    raw_path.write_bytes(b"\x1f\x8b")
    truncated = build_player_acquisition_progress(inventory_path=inventory, capture_root=root)
    assert truncated["summary"]["captured_valid_base_views"] == 0


def test_changed_inventory_invalidates_prior_identity_proof(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    run = PlayerCaptureStore(root, capture_id="inventory-change")
    url = "https://www.bdfutbol.com/es/j/j12345.html"
    html = _catalog_profile_html()
    saved = run.save_snapshot(
        player_id=12345, view="profile", requested_url=url, final_url=url,
        http_status=200, page_title="Test Player", html=html,
        browser={"backend": "fixture"},
    )
    parse_player_html(html, saved, expected_player_id=12345, expected_names=("Test Player",))
    run.record_snapshot_validation(
        saved["snapshot_id"], status="VALID", parser_version=PLAYER_PARSER_VERSION,
    )
    inventory = tmp_path / "inventory.json"
    original = {"records": [{
        "player_id": 12345, "display_name": "Test Player", "membership_count": 1,
    }]}
    inventory.write_text(json.dumps(original), encoding="utf-8")
    original_raw = inventory.read_bytes()
    run.record_inventory_source({
        "path": str(inventory), "sha256": hashlib.sha256(original_raw).hexdigest(),
        "season": "2026-27",
    })
    valid = build_player_acquisition_progress(inventory_path=inventory, capture_root=root)
    assert valid["summary"]["captured_valid_base_views"] == 1

    inventory.write_text(json.dumps({"records": [{
        "player_id": 12345, "display_name": "Different Player", "membership_count": 1,
    }]}), encoding="utf-8")
    changed = build_player_acquisition_progress(inventory_path=inventory, capture_root=root)
    assert changed["summary"]["captured_valid_base_views"] == 0
    assert {"player_id": 12345, "view": "profile"} in changed["pending_views"]


def test_capture_store_uses_manifest_indexes_for_exact_snapshot_lookup(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    run = PlayerCaptureStore(root, capture_id="indexed-run")
    target_id = 0
    target_url = ""
    for player_id in range(100, 140):
        url = f"https://www.bdfutbol.com/es/j/j{player_id}.html"
        html = f"<html><head><title>Player {player_id}</title></head><body>page</body></html>"
        run.save_snapshot(
            player_id=player_id, view="profile", requested_url=url, final_url=url,
            http_status=200, page_title=f"Player {player_id}", html=html,
            browser={"backend": "fixture"},
        )
        target_id, target_url = player_id, url

    class ManifestScanForbidden(list):
        def __iter__(self):
            raise AssertionError("lookup iterated the full manifest snapshot list")

    run.manifest["snapshots"] = ManifestScanForbidden()
    assert run.has_valid_base_snapshot(
        player_id=target_id, view="profile", requested_url=target_url,
    )


def test_reused_snapshot_checkpoint_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    run = PlayerCaptureStore(tmp_path / "captures", capture_id="reuse-index")
    reference = {
        "capture_id": "source-run", "snapshot_id": "source-snapshot",
        "player_id": 12345, "view": "profile", "html_sha256": "a" * 64,
    }
    checkpoints: list[bool] = []
    monkeypatch.setattr(run, "_checkpoint", lambda: checkpoints.append(True))
    run.record_reused_snapshot(reference)
    run.record_reused_snapshot(reference)
    assert len(run.manifest["reused_snapshots"]) == 1
    assert len(checkpoints) == 1


def test_acquisition_reuses_verified_snapshot_from_another_run_without_browser(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    root = tmp_path / "captures"
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"metadata": {"season": "2026-27"}, "records": [{
        "player_id": 12345,
        "display_name": "Test Player",
        "full_name": "Test Full Name",
        "membership_count": 1,
        "groups": ["II"],
    }]}), encoding="utf-8")
    source_store = PlayerCaptureStore(root, capture_id="existing-run")
    url = "https://www.bdfutbol.com/es/j/j12345.html"
    html = '<html><title>Test Player | BDFutbol</title><h1>Test Player</h1></html>'
    source_snapshot = source_store.save_snapshot(
        player_id=12345, view="profile", requested_url=url, final_url=url,
        http_status=200, page_title="Test Player", html=html,
        browser={"backend": "test"},
    )
    source_store.record_snapshot_validation(
        source_snapshot["snapshot_id"], status="VALID", parser_version="test-parser",
    )
    source_store.mark_complete()

    import football_data_hub.providers.bdfutbol.players.acquisition as acquisition

    def browser_must_not_start(*args: object, **kwargs: object) -> None:
        raise AssertionError("No se debía iniciar el navegador para una captura reutilizable")

    monkeypatch.setattr(acquisition, "BrowserSessionManager", browser_must_not_start)
    result = acquire_player_views(
        player_ids=[12345],
        inventory_path=inventory,
        capture_root=root,
        profile_dir=tmp_path / "profile",
        capture_id="reuse-run",
        views=("profile",),
        explore_filters=False,
    )
    assert result["navigation_count"] == 0
    assert result["reused_snapshot_count"] == 1
    manifest = json.loads((root / "reuse-run/manifest.json").read_text(encoding="utf-8"))
    assert manifest["reused_snapshots"][0]["capture_id"] == "existing-run"
    assert manifest["reused_snapshots"][0]["html_sha256"] == hashlib.sha256(html.encode()).hexdigest()


def test_failed_player_cli_returns_nonzero(tmp_path: Path, monkeypatch: object, capsys: object) -> None:
    from acquire_bdfutbol_player_pilot import main
    from football_data_hub.providers.bdfutbol.players.acquisition import PlayerAcquisitionStopped

    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"metadata": {"season": "2026-27"}, "records": [{
        "player_id": 12345,
        "display_name": "Test Player",
        "membership_count": 0,
        "groups": [],
    }]}), encoding="utf-8")
    import acquire_bdfutbol_player_pilot as cli

    monkeypatch.setattr(cli, "load_inventory_players", lambda path, ids: {
        12345: {"player_id": 12345, "display_name": "Test Player"},
    })

    def fail_acquisition(**kwargs: object) -> None:
        raise PlayerAcquisitionStopped(12345, "profile", "DENIED", "BDFutbol denegó el acceso")

    monkeypatch.setattr(cli, "acquire_player_views", fail_acquisition)
    exit_code = main([
        "--player-id", "12345", "--inventory", str(inventory),
        "--output-root", str(tmp_path / "captures"),
        "--progress-output", str(tmp_path / "progress.json"),
        "--no-filter-exploration",
    ])
    assert exit_code == 1
    assert '"access_status": "DENIED"' in capsys.readouterr().err
