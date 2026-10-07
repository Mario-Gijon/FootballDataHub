from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import sync_all_bdfutbol_team_seasons as batch


def _standing(team_id: int, name: str) -> object:
    return SimpleNamespace(
        team=SimpleNamespace(provider_id=team_id),
        team_name=name,
    )


def test_discovery_reads_both_competition_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = {
        "competition_2026-27_1rf_group1": tmp_path / "g1.html",
        "competition_2026-27_1rf_group2": tmp_path / "g2.html",
    }
    pages["competition_2026-27_1rf_group1"].write_text(
        "group1",
        encoding="utf-8",
    )
    pages["competition_2026-27_1rf_group2"].write_text(
        "group2",
        encoding="utf-8",
    )

    def fake_resolve(project_root: Path, name: str) -> Path:
        return pages[name]

    def fake_parse(
        html: str,
        url: str,
        *,
        expected_team_count: int | None = None,
        expected_fixture_count: int | None = None,
    ) -> object:
        assert expected_team_count == 2
        assert expected_fixture_count == 6
        group = 1 if html == "group1" else 2
        rows = (
            (_standing(10, "A"), _standing(11, "B"))
            if group == 1
            else (_standing(20, "C"), _standing(21, "D"))
        )
        return SimpleNamespace(
            context=SimpleNamespace(
                group=group,
                season="2026-27",
                competition_code="1rf",
            ),
            standings=rows,
        )

    monkeypatch.setattr(
        batch,
        "resolve_latest_valid_snapshot",
        fake_resolve,
    )
    monkeypatch.setattr(
        batch,
        "parse_competition",
        fake_parse,
    )

    targets = batch.discover_team_targets(
        project_root=tmp_path,
        season="2026-27",
        competition="1rf",
        expected_teams_per_group=2,
        expected_fixtures_per_group=6,
    )

    assert [(item.team_id, item.group) for item in targets] == [
        (10, 1),
        (11, 1),
        (20, 2),
        (21, 2),
    ]


def test_discovery_rejects_duplicate_team_ids_between_groups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = tmp_path / "competition.html"
    page.write_text("x", encoding="utf-8")

    monkeypatch.setattr(
        batch,
        "resolve_latest_valid_snapshot",
        lambda *args, **kwargs: page,
    )

    calls = {"count": 0}

    def fake_parse(*args: object, **kwargs: object) -> object:
        calls["count"] += 1
        group = calls["count"]
        return SimpleNamespace(
            context=SimpleNamespace(
                group=group,
                season="2026-27",
                competition_code="1rf",
            ),
            standings=(
                _standing(49, "Jaén"),
            ),
        )

    monkeypatch.setattr(
        batch,
        "parse_competition",
        fake_parse,
    )

    with pytest.raises(ValueError, match="duplicados"):
        batch.discover_team_targets(
            project_root=tmp_path,
            season="2026-27",
            competition="1rf",
            expected_teams_per_group=1,
            expected_fixtures_per_group=1,
        )


def test_batch_summary_counts_players_and_unique_ids(
    tmp_path: Path,
) -> None:
    targets = (
        batch.TeamTarget(49, "Jaén", 2),
        batch.TeamTarget(39, "Zaragoza", 2),
        batch.TeamTarget(72, "Bilbao Athletic", 1),
    )
    results = (
        batch.TeamResult(
            team_id=49,
            team_name="Jaén",
            group=2,
            status=batch.team_sync.STATUS_VALID,
            url="u49",
            squad_count=2,
            player_ids=(1, 2),
        ),
        batch.TeamResult(
            team_id=39,
            team_name="Zaragoza",
            group=2,
            status=batch.team_sync.STATUS_VALID,
            url="u39",
            squad_count=2,
            player_ids=(2, 3),
        ),
        batch.TeamResult(
            team_id=72,
            team_name="Bilbao Athletic",
            group=1,
            status=batch.team_sync.STATUS_INVALID,
            url="u72",
            error="fixture",
        ),
    )

    summary = batch._write_batch_summary(
        batch_dir=tmp_path,
        season="2026-27",
        competition="1rf",
        targets=targets,
        results=results,
    )

    assert summary["requested_teams"] == 3
    assert summary["valid"] == 2
    assert summary["failed"] == 1
    assert summary["players_total"] == 4
    assert summary["unique_player_ids"] == 3
    assert summary["unique_player_id_values"] == [1, 2, 3]

    stored = json.loads(
        (tmp_path / "summary.json").read_text(encoding="utf-8")
    )
    assert stored["unique_player_ids"] == 3

    unique = json.loads(
        (tmp_path / "unique_player_ids.json").read_text(
            encoding="utf-8"
        )
    )
    assert unique == [1, 2, 3]


def test_run_keeps_partial_success_and_returns_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = (
        batch.TeamTarget(49, "Jaén", 2),
        batch.TeamTarget(72, "Bilbao Athletic", 1),
    )

    monkeypatch.setattr(
        batch,
        "discover_team_targets",
        lambda **kwargs: targets,
    )

    def fake_batch_session(**kwargs: object) -> tuple[batch.TeamResult, ...]:
        return (
            batch.TeamResult(
                team_id=49,
                team_name="Jaén",
                group=2,
                status=batch.team_sync.STATUS_VALID,
                url="u49",
                squad_count=25,
                player_ids=(1, 2, 3),
                snapshot_directory="snapshot49",
                attempts=1,
            ),
            batch.TeamResult(
                team_id=72,
                team_name="Bilbao Athletic",
                group=1,
                status=batch.team_sync.STATUS_INVALID,
                url="u72",
                error="No se encontraron jugadores",
                attempts=2,
            ),
        )

    monkeypatch.setattr(
        batch,
        "run_batch_session",
        fake_batch_session,
    )

    args = batch.parse_args(["--season", "2026-27"])
    assert batch.run(args, project_root=tmp_path) == 1

    batch_root = (
        tmp_path
        / "data/raw/bdfutbol/batch_team_seasons_2026-27"
    )
    summaries = list(batch_root.glob("*/summary.json"))
    assert len(summaries) == 1

    payload = json.loads(
        summaries[0].read_text(encoding="utf-8")
    )
    assert payload["valid"] == 1
    assert payload["failed"] == 1
    assert payload["players_total"] == 25
    assert payload["unique_player_ids"] == 3


def test_run_returns_zero_when_every_team_is_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = (
        batch.TeamTarget(49, "Jaén", 2),
        batch.TeamTarget(39, "Zaragoza", 2),
    )

    monkeypatch.setattr(
        batch,
        "discover_team_targets",
        lambda **kwargs: targets,
    )
    monkeypatch.setattr(
        batch,
        "run_batch_session",
        lambda **kwargs: (
            batch.TeamResult(
                team_id=49,
                team_name="Jaén",
                group=2,
                status=batch.team_sync.STATUS_VALID,
                url="u49",
                squad_count=25,
                player_ids=(1, 2),
            ),
            batch.TeamResult(
                team_id=39,
                team_name="Zaragoza",
                group=2,
                status=batch.team_sync.STATUS_VALID,
                url="u39",
                squad_count=27,
                player_ids=(3, 4),
            ),
        ),
    )

    args = batch.parse_args(["--season", "2026-27"])
    assert batch.run(args, project_root=tmp_path) == 0
