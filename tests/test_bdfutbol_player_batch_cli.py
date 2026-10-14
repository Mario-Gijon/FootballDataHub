from __future__ import annotations

import json
from pathlib import Path

import acquire_bdfutbol_players as batch_cli
from football_data_hub.providers.bdfutbol.players.acquisition import PLAYER_VIEWS, PlayerAcquisitionStopped


def test_profile_process_check_ignores_command_lines_that_only_mention_chromium_profile(tmp_path: Path) -> None:
    profile = tmp_path / "chromium-profile"
    proc = tmp_path / "proc"
    false_positive = proc / "2"
    false_positive.mkdir(parents=True)
    (false_positive / "cmdline").write_bytes(
        f"/usr/bin/python\0scripts/acquire_bdfutbol_players.py\0--profile\0{profile}\0".encode()
    )
    matching = proc / "99"
    matching.mkdir()
    (matching / "cmdline").write_bytes(
        f"/usr/bin/chromium\0--user-data-dir={profile}\0about:blank\0".encode()
    )
    other = proc / "100"
    other.mkdir()
    (other / "cmdline").write_bytes(
        f"/usr/bin/chromium\0--user-data-dir={tmp_path / 'other'}\0".encode()
    )
    assert batch_cli._matching_profile_processes(profile, proc) == [99]


def _plan_and_progress() -> tuple[dict, dict, dict[int, str]]:
    summary = {
        "inventory_players": 1,
        "roster_players": 1,
        "transfer_only_players": 0,
        "players_with_all_base_views": 0,
        "captured_valid_base_views": 0,
        "base_view_navigations_pending": 1,
    }
    progress = {
        "players": [{"player_id": 501, "status": "PENDING"}],
        "pending_views": [{"player_id": 501, "view": "profile"}],
        "summary": summary,
    }
    return {"status": "READY_FOR_EXPLICIT_EXECUTION"}, progress, {501: "roster"}


def test_mass_cli_checkpoints_ctrl_c_and_resumes_same_capture_without_replanning_navigation(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    capture_root = tmp_path / "captures"
    status_path = tmp_path / "status.json"
    progress_path = tmp_path / "progress.json"
    monkeypatch.setattr(batch_cli, "_make_plan", lambda **_: _plan_and_progress())
    monkeypatch.setattr(batch_cli, "_load_compact_sample", lambda _root: ({"generation_id": "test"}, [{"bytes": 1000}], None))
    calls: list[dict] = []

    def interrupt(**kwargs: dict) -> None:
        calls.append(kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(batch_cli, "acquire_player_views", interrupt)
    interrupted_code = batch_cli.main([
        "--execute",
        "--capture-root", str(capture_root),
        "--progress-output", str(progress_path),
        "--status-file", str(status_path),
    ])
    assert interrupted_code == 130
    interrupted = json.loads(status_path.read_text(encoding="utf-8"))
    capture_id = interrupted["capture_id"]
    assert interrupted["status"] == "interrupted"
    assert (capture_root / capture_id / "manifest.json").is_file()

    def resume_without_browser(**kwargs: dict) -> dict:
        calls.append(kwargs)
        assert kwargs["capture_id"] == capture_id
        assert kwargs["progress_index"]["pending_views"] == [
            {"player_id": 501, "view": "profile"}
        ]
        return {
            "capture_id": capture_id,
            "capture_dir": str(capture_root / capture_id),
            "snapshot_count": 0,
            "navigation_count": 0,
            "verified_navigation_count_total": 0,
            "status": "complete",
            "filter_variants": 0,
            "reused_snapshot_count": 0,
        }

    monkeypatch.setattr(batch_cli, "acquire_player_views", resume_without_browser)
    monkeypatch.setattr(batch_cli, "EXPECTED_INVENTORY_PLAYERS", 1)
    complete_progress = {
        "summary": {
            "inventory_players": 1,
            "players_with_all_base_views": 1,
            "players_pending": 0,
            "base_view_navigations_pending": 0,
            "captured_valid_base_views": 4,
            "players_with_access_errors": 0,
            "blocked_base_views": 0,
        },
        "players": [{
            "player_id": 501,
            "status": "COMPLETE_BASE_VIEWS",
            "views_pending": [],
            "view_snapshots": {
                view: {
                    "http_status": 200,
                    "access_status": "VALID",
                    "parse_validation": {"status": "VALID"},
                    "html_sha256": f"{index:064x}",
                }
                for index, view in enumerate(PLAYER_VIEWS, 1)
            },
        }],
        "corrupt_manifests": [],
    }
    monkeypatch.setattr(
        batch_cli,
        "build_player_acquisition_progress",
        lambda **_: complete_progress,
    )
    resumed_code = batch_cli.main([
        "--execute",
        "--resume", capture_id,
        "--capture-root", str(capture_root),
        "--progress-output", str(progress_path),
        "--status-file", str(status_path),
    ])
    resumed = json.loads(status_path.read_text(encoding="utf-8"))
    assert resumed_code == 0
    assert resumed["status"] == "complete"
    assert resumed["capture_id"] == capture_id
    assert len(calls) == 2
    capsys.readouterr()


def test_mass_cli_http_404_persists_diagnostic_and_resumable_capture_state(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    capture_root = tmp_path / "captures"
    status_path = tmp_path / "status.json"
    progress_path = tmp_path / "progress.json"
    monkeypatch.setattr(batch_cli, "_make_plan", lambda **_: _plan_and_progress())
    monkeypatch.setattr(batch_cli, "_load_compact_sample", lambda _root: ({"generation_id": "test"}, [{"bytes": 1000}], None))
    diagnostic = {
        "error_code": "HTTP_404_STOPPED",
        "policy": "STOP_ON_UNVERIFIED_HTTP_ERROR",
        "player_id": 501,
        "view": "profile",
        "requested_url": "https://www.bdfutbol.com/es/j/j501.html",
        "http_status": 404,
        "recorded_at_utc": "2026-10-14T12:00:00Z",
        "stop_acquisition": True,
    }

    def stop_on_404(**_kwargs):
        raise PlayerAcquisitionStopped(
            501, "profile", "HTTP_ERROR (404)", "HTTP 404", diagnostic=diagnostic,
        )

    monkeypatch.setattr(batch_cli, "acquire_player_views", stop_on_404)
    monkeypatch.setattr(
        batch_cli,
        "build_player_acquisition_progress",
        lambda **_: _plan_and_progress()[1],
    )
    code = batch_cli.main([
        "--execute", "--capture-root", str(capture_root),
        "--progress-output", str(progress_path), "--status-file", str(status_path),
    ])
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert code == 1
    assert status["status"] == "stopped"
    assert status["last_error"]["diagnostic"]["http_status"] == 404
    assert status["last_error"]["diagnostic"]["player_id"] == 501
    assert status["last_error"]["diagnostic"]["view"] == "profile"
    capture_id = status["capture_id"]
    manifest = json.loads((capture_root / capture_id / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "in_progress"
    assert capture_id
    capsys.readouterr()


def test_cli_does_not_report_complete_from_a_complete_capture_id_with_incomplete_global_progress(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    capture_root = tmp_path / "captures"
    status_path = tmp_path / "status.json"
    progress_path = tmp_path / "progress.json"
    monkeypatch.setattr(batch_cli, "_make_plan", lambda **_: _plan_and_progress())
    monkeypatch.setattr(batch_cli, "_load_compact_sample", lambda _root: ({"generation_id": "test"}, [{"bytes": 1000}], None))
    monkeypatch.setattr(batch_cli, "EXPECTED_INVENTORY_PLAYERS", 1)
    monkeypatch.setattr(batch_cli, "acquire_player_views", lambda **_: {"status": "complete"})
    incomplete = {
        "summary": {
            "inventory_players": 1,
            "players_with_all_base_views": 0,
            "players_pending": 1,
            "base_view_navigations_pending": 1,
            "captured_valid_base_views": 3,
            "players_with_access_errors": 0,
            "blocked_base_views": 0,
        },
        "players": [{
            "player_id": 501,
            "status": "PARTIAL_CHECKPOINT",
            "views_pending": ["rivals"],
            "view_snapshots": {
                view: {
                    "http_status": 200,
                    "access_status": "VALID",
                    "parse_validation": {"status": "VALID"},
                    "html_sha256": f"{index:064x}",
                } if view != "rivals" else None
                for index, view in enumerate(PLAYER_VIEWS, 1)
            },
        }],
        "corrupt_manifests": [],
    }
    monkeypatch.setattr(batch_cli, "build_player_acquisition_progress", lambda **_: incomplete)
    code = batch_cli.main([
        "--execute", "--capture-root", str(capture_root),
        "--progress-output", str(progress_path), "--status-file", str(status_path),
    ])
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert code == 1
    assert status["status"] == "stopped"
    assert status["final_validation"]["valid"] is False
    assert status["last_error"]["error_code"] == "GLOBAL_COMPLETENESS_VALIDATION_FAILED"
    capsys.readouterr()
