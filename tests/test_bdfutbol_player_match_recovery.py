from __future__ import annotations

import hashlib
import json
from pathlib import Path

from football_data_hub.providers.bdfutbol.players.capture_store import PlayerCaptureStore
from football_data_hub.providers.bdfutbol.players.acquisition import acquire_player_views
from football_data_hub.providers.bdfutbol.players.catalog import (
    build_player_acquisition_progress,
    find_valid_base_snapshot,
)
from football_data_hub.providers.bdfutbol.players.export import build_player_capture_export
from football_data_hub.providers.bdfutbol.players.models import PlayerMatchesPage
from football_data_hub.providers.bdfutbol.players.parsers import parse_player_html


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
    html = '<html><title>Test Player | BDFutbol</title><h1>Test Player</h1></html>'
    store.save_snapshot(
        player_id=12345, view="profile", requested_url=url, final_url=url,
        http_status=200, page_title="Test Player", html=html,
        browser={"backend": "test"},
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
    source_store.save_snapshot(
        player_id=12345, view="profile", requested_url=url, final_url=url,
        http_status=200, page_title="Test Player", html=html,
        browser={"backend": "test"},
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
