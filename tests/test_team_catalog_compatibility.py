"""Historical catalog matching rules shared by team-profile API datasets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from football_data_hub_api.team_catalog_compatibility import (
    TeamCatalogCompatibilityError,
    verify_team_catalog_compatibility,
)


def _write_catalog(path: Path, *, capture_id: str, matches: list[dict]) -> Path:
    teams = [
        {
            "team_id": team_id,
            "name": f"Equipo {team_id}",
            "team_url": f"https://www.bdfutbol.com/es/t/t2026-27{team_id}.html",
        }
        for team_id in range(1, 21)
    ]
    payload = {
        "schema_version": 1,
        "metadata": {
            "group": "I",
            "season": "2026-27",
            "source_capture_id": capture_id,
            "source_captured_at_utc": f"2026-10-{10 if capture_id == 'source' else 13:02d}T10:00:00+00:00",
        },
        "teams": teams,
        "matches": matches,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _match(
    match_id: str = "m1",
    *,
    home: int = 1,
    away: int = 2,
    goals: tuple[int | None, int | None] = (None, None),
    status: str = "unplayed",
) -> dict:
    return {
        "match_id": match_id,
        "matchday": 1,
        "home_team_id": home,
        "away_team_id": away,
        "home_goals": goals[0],
        "away_goals": goals[1],
        "status": status,
    }


def _capture(source_path: Path, *, source_matches: list[dict]) -> dict:
    raw = source_path.read_bytes()
    return {
        "related_team_catalog": {
            "path": str(source_path),
            "group": "I",
            "season": "2026-27",
            "source_capture_id": "source",
            "source_captured_at_utc": "2026-10-10T10:00:00+00:00",
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    }


def test_historical_catalog_allows_results_to_advance(tmp_path: Path) -> None:
    old = [_match()]
    source = _write_catalog(tmp_path / "source.json", capture_id="source", matches=old)
    active = _write_catalog(
        tmp_path / "active.json",
        capture_id="active",
        matches=[_match(goals=(2, 1), status="played"), _match("m2", home=3, away=4)],
    )

    comparison = verify_team_catalog_compatibility(
        _capture(source, source_matches=old),
        matches_path=active,
        group="I",
        season="2026-27",
        active_capture_id="active",
    )

    assert comparison["compatible"] is True
    assert comparison["match_ids_added"] == ["m2"]
    assert comparison["status_changes"] == [
        {"match_id": "m1", "source_status": "unplayed", "active_status": "played"}
    ]
    assert comparison["score_changes"][0]["active_score"] == [2, 1]


@pytest.mark.parametrize(
    ("active_matches", "expected_fragment"),
    [
        ([], "faltan partidos"),
        ([_match(home=2, away=1)], "conflictos de identidad"),
    ],
)
def test_historical_catalog_rejects_missing_or_reassigned_matches(
    tmp_path: Path,
    active_matches: list[dict],
    expected_fragment: str,
) -> None:
    source = _write_catalog(tmp_path / "source.json", capture_id="source", matches=[_match()])
    active = _write_catalog(tmp_path / "active.json", capture_id="active", matches=active_matches)

    with pytest.raises(TeamCatalogCompatibilityError, match=expected_fragment):
        verify_team_catalog_compatibility(
            _capture(source, source_matches=[_match()]),
            matches_path=active,
            group="I",
            season="2026-27",
            active_capture_id="active",
        )


def test_historical_catalog_hash_tampering_is_rejected(tmp_path: Path) -> None:
    source = _write_catalog(tmp_path / "source.json", capture_id="source", matches=[_match()])
    active = _write_catalog(tmp_path / "active.json", capture_id="active", matches=[_match()])
    metadata = _capture(source, source_matches=[_match()])
    metadata["related_team_catalog"]["sha256"] = "0" * 64

    with pytest.raises(TeamCatalogCompatibilityError, match="sha256"):
        verify_team_catalog_compatibility(
            metadata,
            matches_path=active,
            group="I",
            season="2026-27",
            active_capture_id="active",
        )
