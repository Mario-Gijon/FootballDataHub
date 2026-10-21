"""An invalid team tab is never silently promoted or fetched again unchanged."""

import hashlib
import json

import pytest

from football_data_hub_api import manual_updates
from football_data_hub.providers.bdfutbol.teams import catalog as team_catalog


def _checkpoint(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    old_catalog = data_root / "old-matches.json"
    catalog = {"teams": [{"team_id": 140, "name": "Antequera"}, {"team_id": 141, "name": "Rival"}], "matches": []}
    old_catalog.write_text(json.dumps(catalog), encoding="utf-8")
    current_catalog = data_root / "current-matches.json"
    current_catalog.write_text(json.dumps(catalog), encoding="utf-8")
    team_root = data_root / "teams" / "2026-27" / "140"
    evidence_path = team_root / "diagnostics" / "attempt" / "metadata" / "evidence.json"
    evidence_path.parent.mkdir(parents=True)
    evidence = {
        "source": "BDFutbol", "section": "team_profile_evidence_checkpoint",
        "season": "2026-27", "group": "II", "team_id": 140,
        "related_team_catalog": {
            "path": str(old_catalog), "group": "II", "season": "2026-27",
            "sha256": hashlib.sha256(old_catalog.read_bytes()).hexdigest(),
        },
        "failures": [{"kind": "invalid_content", "message": "squad: INVALID_CONTENT; HTTP=200"}],
    }
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    return data_root, old_catalog, current_catalog, team_root, evidence_path


def test_identical_catalog_skips_repeated_invalid_navigation(monkeypatch, tmp_path):
    data_root, _old, current, team_root, _evidence = _checkpoint(tmp_path)
    calls = []
    original_projection = manual_updates._sports_projection
    def projection(*args, **kwargs):
        calls.append((args, kwargs))
        return original_projection(*args, **kwargs)
    monkeypatch.setattr(manual_updates, "_sports_projection", projection)
    cache = {}
    for _ in range(2):
        assert manual_updates._unchanged_failed_team_checkpoint(
            team_root=team_root, team_id=140, group="II", current_catalog=current,
            data_root=data_root, comparison_cache=cache,
        )
    assert len(calls) == 2


def test_changed_team_catalog_allows_new_attempt(tmp_path):
    data_root, _old, current, team_root, _evidence = _checkpoint(tmp_path)
    payload = json.loads(current.read_text(encoding="utf-8"))
    payload["matches"].append({"match_id": "new", "home_team_id": 140, "away_team_id": 141, "status": "played", "home_goals": 1, "away_goals": 0})
    current.write_text(json.dumps(payload), encoding="utf-8")
    assert not manual_updates._unchanged_failed_team_checkpoint(
        team_root=team_root, team_id=140, group="II", current_catalog=current,
        data_root=data_root, comparison_cache={},
    )


def test_other_team_change_does_not_repeat_failed_team_navigation(tmp_path):
    data_root, _old, current, team_root, _evidence = _checkpoint(tmp_path)
    payload = json.loads(current.read_text(encoding="utf-8"))
    payload["teams"].append({"team_id": 142, "name": "Otro"})
    payload["matches"].append({"match_id": "new", "home_team_id": 141, "away_team_id": 142, "status": "played", "home_goals": 1, "away_goals": 0})
    current.write_text(json.dumps(payload), encoding="utf-8")
    assert manual_updates._unchanged_failed_team_checkpoint(
        team_root=team_root, team_id=140, group="II", current_catalog=current,
        data_root=data_root, comparison_cache={},
    )


def test_corrupt_catalog_or_identity_does_not_authorize_acquisition(tmp_path):
    data_root, old, current, team_root, evidence_path = _checkpoint(tmp_path)
    old.write_text("corrupted", encoding="utf-8")
    with pytest.raises(manual_updates.ManualUpdateError, match="no verificable"):
        manual_updates._unchanged_failed_team_checkpoint(
            team_root=team_root, team_id=140, group="II", current_catalog=current,
            data_root=data_root, comparison_cache={},
        )
    old.write_text(json.dumps({"teams": [{"team_id": 140, "name": "Antequera"}, {"team_id": 141, "name": "Rival"}], "matches": []}), encoding="utf-8")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["team_id"] = 141
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(manual_updates.ManualUpdateError, match="no verificable"):
        manual_updates._unchanged_failed_team_checkpoint(
            team_root=team_root, team_id=140, group="II", current_catalog=current,
            data_root=data_root, comparison_cache={},
        )


def test_referee_invalid_page_error_is_actionable():
    log = '$ python scrape_referees.py\n{"status": "INVALID_CONTENT", "http_status": 200}'
    assert "estructura deportiva" in manual_updates._friendly_process_failure(log, "code 4")


def test_full_competition_follow_scan_does_not_start_a_team_batch(monkeypatch, tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    index_path = data_root / "index.json"
    index_path.write_text(json.dumps({
        "schema_version": 1, "season": "2026-27",
        "profiles": {str(team_id): {} for team_id in range(1, 41)},
    }), encoding="utf-8")
    catalogs = {group: data_root / f"{group}.json" for group in ("I", "II")}
    for path in catalogs.values():
        path.write_text("{}", encoding="utf-8")

    def fake_catalog(_path, *, competition):
        group = competition.group_number
        ids = range(1, 21) if group == 1 else range(21, 41)
        teams = [{"team_id": team_id} for team_id in ids]
        matches = [] if group == 1 else [{
            "match_id": "new", "status": "played", "home_team_id": 39,
            "away_team_id": 40, "home_goals": 1, "away_goals": 0,
        }]
        return teams, matches, {}

    monkeypatch.setattr(team_catalog, "load_team_catalog", fake_catalog)
    monkeypatch.setattr(manual_updates, "_unchanged_failed_team_checkpoint", lambda **_: True)
    manager = object.__new__(manual_updates.ManualUpdateManager)
    manager.project_root = project_root
    manager.data_root = data_root
    manager.team_profiles_index = index_path
    manager.player_team_captures_root = data_root / "team-captures"
    manager._read_team_follow_profile = lambda _entry, *, team_id, **__: (
        data_root / str(team_id), set() if team_id in {39, 40} else {"new"}
    )
    manager._find_team_follow_candidate = lambda **_: None
    manager._command = lambda *_args, **_kwargs: pytest.fail("No team navigation expected")

    result = manager._update_team_follow(
        {"job_id": "offline"}, data_root / "unused.log",
        normalized=catalogs,
    )
    assert result["changed_team_count"] == 0
    assert result["unchanged_team_count"] == 38
    assert result["pending_team_count"] == 2
    assert {team_id for team_id, item in result["teams"].items() if item["status"] == "not_attempted"} == {"39", "40"}
    assert result["batch_manifest"] is None
