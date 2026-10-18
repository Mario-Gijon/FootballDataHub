"""Opt-in offline validation of the real 272525 campaign artifact and preview."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import urllib.request
from collections import Counter
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.match_details.campaign_artifact import (
    CampaignArtifactError,
    parse_campaign_saved_artifact,
)
from football_data_hub.providers.bdfutbol.match_details.inventory import (
    build_match_detail_inventory,
    load_verified_match_generation,
)
from football_data_hub_api.match_details_dataset import load_local_discovery_preview
from football_data_hub_api.match_results_dataset import (
    build_match_page,
    load_match_results_dataset,
)
from football_data_hub_api.player_dataset import load_player_directory

pytestmark = pytest.mark.skipif(
    os.environ.get("FDH_MATCH_01C_D2_INTEGRATION") != "1",
    reason="Opt-in offline local captures; set FDH_MATCH_01C_D2_INTEGRATION=1",
)

GENERATION_ID = "match-00-4ad1d610507e425d"
INVENTORY_ID = "match-detail-inventory-8cf339654c80c0ef"
CAMPAIGN_ID = "match-detail-sample-campaign-67fdc4b4fac66b82"
CAMPAIGN_ARTIFACT_ID = "discovery-20261018T112656Z-4543b211"
CAMPAIGN_MATCH_ID = "pf-2026-27-group-ii-bdfutbol-272525"
LEGACY_MATCH_ID = "pf-2026-27-group-ii-bdfutbol-272582"
CAMPAIGN_HTML_SHA256 = "9649b77712f8f259dd4cc413ebc90c26305069a7cb96ab8829fed3aff4b01113"


def _hash_paths(paths: list[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for root in paths:
        if root.is_file():
            result[str(root)] = hashlib.sha256(root.read_bytes()).hexdigest()
        elif root.is_dir():
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    result[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _generation_source_paths(data_root: Path, generation_root: Path) -> list[Path]:
    manifest = json.loads((generation_root / "manifest.json").read_text(encoding="utf-8"))
    paths = [generation_root]
    for source in manifest["source_captures"]:
        for key in ("capture_metadata", "source_html", "normalized_matches"):
            paths.append(data_root / source["files"][key]["path"])
    return paths


def _campaign_artifact(data_root: Path) -> Path:
    return (
        data_root
        / "matches/details/campaigns"
        / CAMPAIGN_ID
        / "candidates"
        / CAMPAIGN_MATCH_ID
        / "artifacts"
        / CAMPAIGN_ARTIFACT_ID
    )


def test_real_272525_campaign_and_272582_legacy_previews_are_valid_and_read_only(
    monkeypatch,
):
    def forbidden(*args, **kwargs):
        raise AssertionError("D2 artifact validation must not perform network I/O")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)

    data_root = Path(
        os.environ.get("FDH_MATCH_01C_D2_DATA_ROOT", Path.home() / "FootballDataHub-data")
    ).expanduser()
    generation_root = data_root / "matches/generations" / GENERATION_ID
    inventory_root = data_root / "matches/details/inventories" / INVENTORY_ID
    campaign_root = data_root / "matches/details/campaigns" / CAMPAIGN_ID
    artifact = _campaign_artifact(data_root)
    legacy_artifact = (
        data_root
        / "matches/details/diagnostics"
        / INVENTORY_ID
        / "20261016T163942.933046Z-eb9b59e1"
    )
    player_inputs = [
        data_root / "players/inventory-2026-27",
        data_root / "players/compact-2026-27",
        data_root / "team-captures",
        data_root / "published/team_profiles_2026-27.json",
    ]
    if not all(
        path.exists()
        for path in [generation_root, inventory_root, campaign_root, artifact, legacy_artifact, *player_inputs]
    ):
        pytest.skip("Faltan capturas locales; no se descargan ni se regeneran")

    source_paths = [
        *_generation_source_paths(data_root, generation_root),
        inventory_root,
        campaign_root,
        legacy_artifact,
        player_inputs[0],
        player_inputs[3],
    ]
    before = _hash_paths(source_paths)

    generation = load_verified_match_generation(generation_root, data_root=data_root)
    inventory = build_match_detail_inventory(generation)
    expected_campaign = next(
        item for item in inventory["matches"] if item["internal_id"] == CAMPAIGN_MATCH_ID
    )
    assert inventory["inventory_id"] == INVENTORY_ID
    observation = parse_campaign_saved_artifact(
        artifact,
        expected_match=expected_campaign,
        verified_generation=generation,
        data_root=data_root,
    )
    assert observation.source.source_match_id == "272525"
    assert observation.source.source_html_sha256 == CAMPAIGN_HTML_SHA256
    assert observation.validation.semantic_valid is True
    assert observation.validation.promotion_eligible is False
    assert observation.source.promotion_eligible is False
    assert observation.score.home_goals == observation.score.away_goals == 0
    assert observation.match_date.value == "2026-08-31"
    assert observation.context.matchday.value == 1
    assert observation.context.competition.value == "Primera Federación"
    assert observation.home.team.team_id == 204
    assert observation.away.team.team_id == 61
    assert len(observation.home.starters or ()) == 11
    assert len(observation.away.starters or ()) == 11
    assert len(observation.home.substitutes or ()) == 7
    assert len(observation.away.substitutes or ()) == 10
    assert observation.home.coach is not None
    assert observation.away.coach is not None
    assert sum(event.event_type == "substitution_in" for event in observation.events) == 9
    assert sum(event.event_type == "substitution_out" for event in observation.events) == 9
    assert sum(event.event_type == "yellow_card" for event in observation.events) == 4
    assert sum(event.event_type == "red_card" for event in observation.events) == 1
    assert sum(event.event_type == "missed_penalty" for event in observation.events) == 1
    assert not any(event.event_type in {"goal", "penalty_goal"} for event in observation.events)
    assert all(event.minute_literal is not None for event in observation.events)
    assert any(
        check.check == "unknown_event_icons_rejected" and check.passed
        for check in observation.validation.checks
    )
    assert any(
        event.event_type == "missed_penalty"
        and event.player_name == "Rachad"
        and event.minute_literal == "43"
        for event in observation.events
    )
    assert any(
        event.event_type == "red_card"
        and event.player_name == "Belevonis"
        and event.minute_literal == "90"
        for event in observation.events
    )

    player_directory = load_player_directory(
        inventory_root=player_inputs[0],
        compact_root=player_inputs[1],
        team_captures_root=player_inputs[2],
        published_index_path=player_inputs[3],
    )
    assert player_directory.metadata.complete_individual_profile_count == 1708
    player_ids = set(player_directory.players_by_id)
    match_bundle = load_match_results_dataset(generation_root, data_root=data_root)
    public_page = build_match_page(match_bundle, CAMPAIGN_MATCH_ID)
    assert public_page is not None
    assert public_page.detail_status == "not_available"
    assert public_page.details is None

    campaign_preview = load_local_discovery_preview(
        artifact,
        internal_id=CAMPAIGN_MATCH_ID,
        generation_root=generation_root,
        data_root=data_root,
        match_bundle=match_bundle,
        player_ids=player_ids,
    )
    assert campaign_preview.detail_status == "preview_only"
    assert campaign_preview.details is not None
    assert campaign_preview.details.validation_status == "valid"
    assert campaign_preview.match.home_goals == campaign_preview.match.away_goals == 0
    assert campaign_preview.match.home_team.name == "Teruel"
    assert campaign_preview.match.away_team.name == "Real Madrid Castilla"
    campaign_players = [
        *campaign_preview.details.home.starters,
        *campaign_preview.details.home.substitutes,
        *campaign_preview.details.away.starters,
        *campaign_preview.details.away.substitutes,
    ]
    identified_campaign_players = [item for item in campaign_players if item.player_id is not None]
    assert len(identified_campaign_players) == 39
    assert all(item.player_profile_available for item in identified_campaign_players)
    campaign_event_counts = Counter(
        item.event_kind for item in campaign_preview.details.events or []
    )
    assert campaign_event_counts == {
        "substitution_in": 9,
        "substitution_out": 9,
        "yellow_card": 4,
        "missed_penalty": 1,
        "red_card": 1,
    }

    legacy_preview = load_local_discovery_preview(
        legacy_artifact,
        internal_id=LEGACY_MATCH_ID,
        generation_root=generation_root,
        data_root=data_root,
        match_bundle=match_bundle,
        player_ids=player_ids,
    )
    assert legacy_preview.detail_status == "preview_only"
    assert legacy_preview.details is not None
    assert legacy_preview.details.validation_status == "valid"
    assert legacy_preview.match.home_goals == legacy_preview.match.away_goals == 3
    assert Counter(item.event_kind for item in legacy_preview.details.events or []) == {
        "substitution_in": 10,
        "substitution_out": 10,
        "yellow_card": 7,
        "goal": 4,
        "penalty": 2,
    }
    assert before == _hash_paths(source_paths)


def test_campaign_artifact_hash_and_identity_fail_closed_in_temporary_copy(tmp_path):
    data_root = Path(
        os.environ.get("FDH_MATCH_01C_D2_DATA_ROOT", Path.home() / "FootballDataHub-data")
    ).expanduser()
    generation_root = data_root / "matches/generations" / GENERATION_ID
    inventory_root = data_root / "matches/details/inventories" / INVENTORY_ID
    source_campaign = data_root / "matches/details/campaigns" / CAMPAIGN_ID
    source_artifact = _campaign_artifact(data_root)
    if not all(path.is_dir() for path in (generation_root, inventory_root, source_campaign, source_artifact)):
        pytest.skip("Faltan capturas locales; no se descargan ni se regeneran")

    generation = load_verified_match_generation(generation_root, data_root=data_root)
    expected = next(
        item
        for item in build_match_detail_inventory(generation)["matches"]
        if item["internal_id"] == CAMPAIGN_MATCH_ID
    )
    temporary_root = tmp_path / "data"
    copied_campaigns = temporary_root / "matches/details/campaigns"
    copied_campaigns.mkdir(parents=True)
    shutil.copytree(source_campaign, copied_campaigns / CAMPAIGN_ID)
    copied_inventories = temporary_root / "matches/details/inventories"
    copied_inventories.mkdir(parents=True)
    shutil.copytree(inventory_root, copied_inventories / INVENTORY_ID)
    copied_artifact = _campaign_artifact(temporary_root)

    html_path = copied_artifact / "source.html"
    html_path.write_bytes(html_path.read_bytes() + b" ")
    with pytest.raises(CampaignArtifactError, match="source.html"):
        parse_campaign_saved_artifact(
            copied_artifact,
            expected_match=expected,
            verified_generation=generation,
            data_root=temporary_root,
        )

    shutil.rmtree(copied_campaigns / CAMPAIGN_ID)
    shutil.copytree(source_campaign, copied_campaigns / CAMPAIGN_ID)
    incorrect_identity = dict(expected, source_match_id="272582")
    with pytest.raises(CampaignArtifactError, match="Identidad del candidato"):
        parse_campaign_saved_artifact(
            copied_artifact,
            expected_match=incorrect_identity,
            verified_generation=generation,
            data_root=temporary_root,
        )
