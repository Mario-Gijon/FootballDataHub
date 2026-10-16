from __future__ import annotations

import hashlib
import json
import socket
import urllib.request
import pytest

from football_data_hub.providers.bdfutbol.match_details.inventory import (
    VerifiedGeneration,
    build_match_detail_inventory,
)
from football_data_hub.providers.bdfutbol.match_details.sampling_plan import (
    MatchSamplePlanError,
    _read_persisted_inventory,
    build_sample_plan_from_verified,
    select_sample_candidates,
    tree_sha256,
)
from football_data_hub.providers.bdfutbol.match_details.sample_cli import (
    _write_report_immutable,
)
from football_data_hub.providers.bdfutbol.match_details.store import MatchDetailStore
from tests.match_detail_fixtures import make_verified_generation


def _match(group: str, source_id: str, home: int, away: int, score: tuple[int, int]):
    return {
        "internal_id": f"pf-2026-27-group-{group.lower()}-bdfutbol-{source_id}",
        "source_match_id": source_id,
        "status": "played",
        "source_match_url": f"https://www.bdfutbol.com/es/p/p.php?id={source_id}",
        "home_team_id": home,
        "away_team_id": away,
        "matchday": 1,
        "source_match_date": "2026-08-29",
        "matchday_date": "2026-08-29",
        "home_goals": score[0],
        "away_goals": score[1],
    }


def _sampling_generation() -> VerifiedGeneration:
    verified = make_verified_generation()
    groups = verified.matches_payload["groups"]
    for group in ("I", "II"):
        teams = groups[group]["teams"]
        for team in teams:
            team["name"] = f"Team {team['team_id']}"
    group_i = groups["I"]
    group_i["matches"].append(_match("I", "269411", 100, 101, (1, 1)))
    group_ii = groups["II"]
    group_ii["matches"].extend(
        [
            _match("II", "272517", 200, 201, (1, 0)),
            _match("II", "272522", 202, 203, (3, 2)),
            _match("II", "272523", 204, 205, (0, 3)),
            _match("II", "272582", 206, 207, (3, 3)),
        ]
    )
    return verified


def _plan(tmp_path, verified=None, inventory=None):
    source = verified or _sampling_generation()
    source_inventory = inventory or build_match_detail_inventory(source)
    return build_sample_plan_from_verified(
        verified=source,
        inventory=source_inventory,
        store_root=tmp_path / "store",
        inventory_sha256="a" * 64,
        inventory_manifest_sha256="b" * 64,
    )


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _persist_inventory_snapshot(path, inventory):
    path.mkdir(parents=True)
    inventory_raw = _canonical(inventory)
    inventory_hash = hashlib.sha256(inventory_raw).hexdigest()
    manifest = {
        "schema_version": "football_data_hub.match_detail_inventory_manifest.v1",
        "inventory_id": inventory["inventory_id"],
        "inventory_sha256": inventory_hash,
        "record_count": len(inventory["matches"]),
        "source_generation": inventory["source_generation"],
    }
    (path / "inventory.json").write_bytes(inventory_raw)
    (path / "manifest.json").write_bytes(_canonical(manifest))


def test_selection_is_deterministic_and_covers_available_categories(tmp_path):
    verified = _sampling_generation()
    inventory = build_match_detail_inventory(verified)
    first = _plan(tmp_path, verified, inventory)
    second = _plan(tmp_path, verified, inventory)

    assert first == second
    assert [item["source_match_id"] for item in first["candidates"]] == [
        "272500",
        "272517",
        "272522",
        "272523",
        "269411",
    ]
    assert [item["selection_reason_code"] for item in first["candidates"]] == [
        "scoreless_draw_0_0",
        "one_goal_margin",
        "high_scoring",
        "asymmetric_score",
        "group_i",
    ]
    assert first["selection_policy"]["category_status"]["high_scoring"]["status"] == "SELECTED"


def test_candidates_are_inventory_bound_and_exclude_first_pilot(tmp_path):
    verified = _sampling_generation()
    inventory = build_match_detail_inventory(verified)
    candidates, _ = select_sample_candidates(verified, inventory)

    catalog_ids = {
        str(match["source_match_id"])
        for group in verified.matches_payload["groups"].values()
        for match in group["matches"]
    }
    inventory_ids = {record["source_match_id"] for record in inventory["matches"]}
    assert all(item["source_match_id"] in inventory_ids & catalog_ids for item in candidates)
    assert "272582" not in {item["source_match_id"] for item in candidates}
    assert len({item["internal_id"] for item in candidates}) == len(candidates)
    for item in candidates:
        assert item["source_match_url"].endswith(f"id={item['source_match_id']}")
        assert item["internal_id"].endswith(item["source_match_id"])
        assert item["home_team_id"] != item["away_team_id"]
        assert item["home_team_name"] and item["away_team_name"]


def test_catalog_data_controls_group_teams_and_scores(tmp_path):
    report = _plan(tmp_path)
    candidate = next(item for item in report["candidates"] if item["source_match_id"] == "272522")
    assert candidate["group"] == "II"
    assert candidate["home_team_id"] == 202
    assert candidate["home_team_name"] == "Team 202"
    assert candidate["away_team_id"] == 203
    assert candidate["home_goals"] == 3
    assert candidate["away_goals"] == 2
    assert candidate["source_match_date"] == "2026-08-29"
    assert "autogoles" in " ".join(candidate["unknown_features"])


def test_missing_score_categories_are_reported_without_invention(tmp_path):
    verified = make_verified_generation()
    for group in ("I", "II"):
        for team in verified.matches_payload["groups"][group]["teams"]:
            team["name"] = f"Team {team['team_id']}"
    inventory = build_match_detail_inventory(verified)
    report = _plan(tmp_path, verified, inventory)
    categories = report["selection_policy"]["category_status"]
    assert categories["one_goal_margin"]["status"] == "NO_CANDIDATE"
    assert categories["high_scoring"]["status"] == "NO_CANDIDATE"
    assert categories["asymmetric_score"]["status"] == "NO_CANDIDATE"
    assert len(report["candidates"]) == 2
    assert report["status"] == "BLOCKED"
    assert "fewer_than_three_verified_sample_candidates" in report["blocked_reasons"]


def test_missing_optional_category_does_not_invalidate_three_real_candidates(tmp_path):
    verified = make_verified_generation()
    for group in ("I", "II"):
        for team in verified.matches_payload["groups"][group]["teams"]:
            team["name"] = f"Team {team['team_id']}"
    verified.matches_payload["groups"]["I"]["matches"].append(
        _match("I", "269411", 100, 101, (1, 1))
    )
    inventory = build_match_detail_inventory(verified)

    report = _plan(tmp_path, verified, inventory)

    assert len(report["candidates"]) == 3
    assert report["status"] == "PLAN_ONLY_NOT_AUTHORIZED"
    assert report["selection_policy"]["category_status"]["high_scoring"]["status"] == (
        "NO_CANDIDATE"
    )


def test_altered_inventory_is_rejected_even_if_it_is_well_formed(tmp_path):
    verified = _sampling_generation()
    inventory = build_match_detail_inventory(verified)
    altered = json.loads(json.dumps(inventory))
    altered["matches"][0]["source_match_url"] = "https://example.invalid/match"

    with pytest.raises(MatchSamplePlanError, match="reconstrucción íntegra"):
        _plan(tmp_path, verified, altered)


def test_persisted_inventory_absent_corrupt_or_altered_is_rejected(tmp_path):
    verified = _sampling_generation()
    inventory = build_match_detail_inventory(verified)
    data_root = tmp_path / "data"
    data_root.mkdir()
    directory = data_root / "inventories" / inventory["inventory_id"]

    with pytest.raises(MatchSamplePlanError, match="Faltan"):
        _read_persisted_inventory(
            directory,
            data_root=data_root,
            expected_inventory=inventory,
        )

    _persist_inventory_snapshot(directory, inventory)
    original_raw = _canonical(inventory)
    persisted, inventory_hash, manifest_hash = _read_persisted_inventory(
        directory,
        data_root=data_root,
        expected_inventory=inventory,
    )
    assert persisted == inventory
    assert len(inventory_hash) == 64
    assert len(manifest_hash) == 64

    (directory / "inventory.json").write_bytes(b"not-json")
    with pytest.raises(MatchSamplePlanError, match="JSON válido"):
        _read_persisted_inventory(
            directory,
            data_root=data_root,
            expected_inventory=inventory,
        )

    (directory / "inventory.json").write_bytes(original_raw)
    altered = json.loads((directory / "inventory.json").read_text())
    altered["matches"][0]["source_match_id"] = "999999"
    (directory / "inventory.json").write_bytes(_canonical(altered))
    with pytest.raises(MatchSamplePlanError, match="alterado"):
        _read_persisted_inventory(
            directory,
            data_root=data_root,
            expected_inventory=inventory,
        )


def test_active_match_01b_stop_is_reported_and_checkpoint_is_unchanged(tmp_path):
    verified = _sampling_generation()
    inventory = build_match_detail_inventory(verified)
    store_root = tmp_path / "store"
    record = next(
        item for item in inventory["matches"] if item["source_match_id"] == "272582"
    )
    MatchDetailStore(store_root).record_diagnostic(
        inventory,
        internal_id=record["internal_id"],
        requested_url=record["source_match_url"],
        http_status=200,
        error_code="IDENTITY_OR_CONTENT_UNVERIFIED",
        diagnostic="Synthetic offline stop; no navigation performed by this test.",
    )
    before = tree_sha256(store_root)

    report = build_sample_plan_from_verified(
        verified=verified,
        inventory=inventory,
        store_root=store_root,
    )

    assert report["store"]["active_stop"] is True
    assert report["store"]["checkpoint_status"] == "stopped"
    assert report["campaign"]["legacy_pilot_stop"]["active_stop"] is True
    assert report["campaign"]["legacy_pilot_stop"]["checkpoint_modified"] is False
    assert all(
        item["requires_legacy_stop_review"]
        for item in report["campaign"]["per_match_authorization_scope"]
    )
    assert report["status"] == "BLOCKED"
    assert report["navigation_enabled"] is False
    assert tree_sha256(store_root) == before


def test_preparation_is_offline_non_promoting_and_does_not_write_store(
    monkeypatch, tmp_path
):
    def forbidden(*args, **kwargs):
        raise AssertionError("El planificador no debe abrir red ni promocionar capturas")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(MatchDetailStore, "store_valid_capture", forbidden)
    monkeypatch.setattr(MatchDetailStore, "begin_navigation_attempt", forbidden)
    monkeypatch.setattr(MatchDetailStore, "store_discovery_artifact", forbidden)

    verified = _sampling_generation()
    inventory = build_match_detail_inventory(verified)
    store_root = tmp_path / "store"
    before = tree_sha256(store_root)
    report = build_sample_plan_from_verified(
        verified=verified,
        inventory=inventory,
        store_root=store_root,
    )
    after = tree_sha256(store_root)

    assert report["http_enabled"] is False
    assert report["browser_started"] is False
    assert report["navigation_enabled"] is False
    assert report["promotion_enabled"] is False
    assert report["campaign"]["is_authorization"] is False
    assert all(
        scope["authorization_status"] == "NOT_AUTHORIZED"
        and scope["campaign_id"] == report["campaign"]["campaign_id"]
        and scope["inventory_id"] == report["source"]["inventory_id"]
        and scope["source_match_url"].endswith(f"id={scope['source_match_id']}")
        and scope["maximum_navigations"] == 1
        and scope["automatic_retries"] == 0
        and scope["capture_promotion_enabled"] is False
        for scope in report["campaign"]["per_match_authorization_scope"]
    )
    assert before is after is None


def test_optional_report_is_immutable_and_never_overwrites(tmp_path):
    target = tmp_path / "reports" / "plan.json"
    report = {"status": "PLAN_ONLY_NOT_AUTHORIZED", "navigation_enabled": False}

    assert _write_report_immutable(target, report) == target
    original = target.read_bytes()
    assert json.loads(original) == report
    with pytest.raises(MatchSamplePlanError, match="No se sobrescribe"):
        _write_report_immutable(target, {"status": "replacement"})
    assert target.read_bytes() == original
