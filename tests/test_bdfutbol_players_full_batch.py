from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path

import pytest

from scripts import sync_all_bdfutbol_players_full as batch


def _args(**overrides):
    values = dict(
        season="2026-27",
        ids_file=None,
        player_ids=None,
        start_at=None,
        limit=None,
        skip_valid=False,
        parse_after_sync=False,
        between_players_seconds=0.0,
        attempts_per_resource=2,
        challenge_wait_seconds=12.0,
        resource_wait_seconds=15.0,
        retry_delay_seconds=0.0,
        between_resources_seconds=0.0,
        timeout_ms=45_000,
        settle_ms=0,
        browser="auto",
        profile="/tmp/profile",
        show_resources=False,
    )
    values.update(overrides)
    return argparse.Namespace(**values)


def test_load_player_ids_preserves_order_and_deduplicates(tmp_path: Path):
    path = tmp_path / "ids.json"
    path.write_text("[9, 3, 9, 12]", encoding="utf-8")

    assert batch.load_player_ids(path) == (9, 3, 12)


def test_load_player_ids_rejects_non_list(tmp_path: Path):
    path = tmp_path / "ids.json"
    path.write_text('{"ids": [1]}', encoding="utf-8")

    with pytest.raises(ValueError):
        batch.load_player_ids(path)


def test_resolve_ids_file_uses_latest_team_batch(tmp_path: Path):
    base = (
        tmp_path
        / "data/raw/bdfutbol/batch_team_seasons_2026-27"
    )
    older = base / "20261001T000000Z"
    newer = base / "20261007T151507Z"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    (older / "unique_player_ids.json").write_text("[1]", encoding="utf-8")
    (newer / "unique_player_ids.json").write_text("[2]", encoding="utf-8")

    resolved = batch.resolve_ids_file(
        project_root=tmp_path,
        season="2026-27",
        requested=None,
    )

    assert resolved == (newer / "unique_player_ids.json").resolve()


def test_select_player_ids_start_limit_and_explicit():
    source = (10, 20, 30, 40, 50)

    assert batch.select_player_ids(
        source,
        explicit_ids=None,
        start_at=30,
        limit=2,
    ) == (30, 40)

    assert batch.select_player_ids(
        source,
        explicit_ids=[50, 20, 50],
        start_at=None,
        limit=None,
    ) == (50, 20)


def test_select_player_ids_rejects_missing_explicit_id():
    with pytest.raises(ValueError):
        batch.select_player_ids(
            (1, 2, 3),
            explicit_ids=[4],
            start_at=None,
            limit=None,
        )


def test_latest_valid_player_run_requires_valid_summary(tmp_path: Path):
    root = tmp_path / "data/raw/bdfutbol/player_full_7"
    run = root / "run1"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(
        json.dumps({"player_id": 7, "required_failed": 0}),
        encoding="utf-8",
    )
    (root / "latest_valid.json").write_text(
        json.dumps({"run_directory": str(run)}),
        encoding="utf-8",
    )

    assert batch.resolve_latest_valid_player_run(
        project_root=tmp_path,
        player_id=7,
    ) == run.resolve()


def test_latest_valid_player_run_rejects_failed_summary(tmp_path: Path):
    root = tmp_path / "data/raw/bdfutbol/player_full_7"
    run = root / "run1"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(
        json.dumps({"player_id": 7, "required_failed": 1}),
        encoding="utf-8",
    )
    (root / "latest_valid.json").write_text(
        json.dumps({"run_directory": str(run)}),
        encoding="utf-8",
    )

    assert batch.resolve_latest_valid_player_run(
        project_root=tmp_path,
        player_id=7,
    ) is None


def test_player_args_maps_batch_timing_settings():
    args = _args(
        attempts_per_resource=3,
        resource_wait_seconds=9.5,
        between_resources_seconds=0.4,
    )

    child = batch._player_args(args, player_id=99)

    assert child.player_id == 99
    assert child.attempts_per_resource == 3
    assert child.resource_wait_seconds == 9.5
    assert child.between_resources_seconds == 0.4


def test_batch_counts_separate_skip_failure_and_parse_failure():
    results = [
        batch.BatchPlayerResult(1, batch.STATUS_VALID),
        batch.BatchPlayerResult(2, batch.STATUS_SKIPPED_VALID),
        batch.BatchPlayerResult(3, batch.STATUS_FAILED),
        batch.BatchPlayerResult(
            4,
            batch.STATUS_VALID,
            parse_status=batch.STATUS_PARSE_FAILED,
        ),
    ]

    assert batch._batch_counts(results) == {
        "processed": 4,
        "valid": 2,
        "skipped_valid": 1,
        "failed": 1,
        "parse_failed": 1,
    }


def test_checkpoint_records_next_player(tmp_path: Path):
    path = tmp_path / "checkpoint.json"
    batch._write_checkpoint(
        path=path,
        batch_run_id="batch1",
        season="2026-27",
        ids_file=tmp_path / "ids.json",
        selected_ids=(10, 20, 30),
        results=[batch.BatchPlayerResult(10, batch.STATUS_VALID)],
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["processed_count"] == 1
    assert payload["next_player_id"] == 20
    assert payload["processed_player_ids"] == [10]


def test_sync_player_failure_is_returned_not_raised(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        batch.player_sync,
        "_run_id",
        lambda: "run1",
    )
    monkeypatch.setattr(
        batch.player_sync,
        "build_resource_specs",
        lambda player_id: (object(),),
    )

    def boom(**kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(batch.player_sync, "_capture_resource", boom)

    result = batch.sync_player_in_context(
        context=object(),
        project_root=tmp_path,
        batch_args=_args(),
        player_id=42,
        batch_run_id="batch1",
    )

    assert result.status == batch.STATUS_FAILED
    assert "synthetic failure" in (result.error or "")
    assert (
        tmp_path
        / "data/raw/bdfutbol/player_full_42/run1/summary.json"
    ).is_file()


def test_validate_args_rejects_negative_delay():
    with pytest.raises(ValueError):
        batch._validate_args(_args(between_players_seconds=-1.0))



def test_batch_module_bootstraps_repository_import_roots() -> None:
    import sys

    assert str(batch.PROJECT_ROOT) in sys.path
    assert str(batch.SRC_ROOT) in sys.path


def test_batch_source_has_no_stale_playwright_cm_name() -> None:
    source = Path(batch.__file__).read_text(encoding="utf-8")
    assert "playwright_cm" not in source


def test_batch_script_help_runs_as_direct_file() -> None:
    import os
    import subprocess
    import sys

    project_root = Path(batch.__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")

    proc = subprocess.run(
        [
            sys.executable,
            str(Path(batch.__file__).resolve()),
            "--help",
        ],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    assert "--season" in proc.stdout
    assert "--parse-after-sync" in proc.stdout
