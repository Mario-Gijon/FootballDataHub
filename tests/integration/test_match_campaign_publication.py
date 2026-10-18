"""Opt-in, offline MATCH-03 publication cycle against immutable local captures.

The only approval in this test is a temporary pytest fixture receipt. Nothing is
written to the real campaign, capture store, or public publication index.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient

from football_data_hub.providers.bdfutbol.match_details.campaign_publication_cli import (
    _summary,
)
from football_data_hub.providers.bdfutbol.match_details.campaign_artifact import (
    parse_campaign_saved_artifact,
)
from football_data_hub.providers.bdfutbol.match_details.inventory import (
    build_match_detail_inventory,
    load_verified_match_generation,
)
from football_data_hub_api.config import ApiSettings
from football_data_hub_api.main import create_app
from football_data_hub_api.match_details_dataset import (
    MatchDetailsLoadError,
    build_campaign_approval_receipt,
    build_campaign_publication_draft,
    campaign_approval_confirmation,
    load_published_match_details,
    publish_campaign_match_detail_draft,
    write_immutable_publication_json,
)
from football_data_hub_api.match_results_dataset import (
    build_match_page,
    load_match_results_dataset,
)
from football_data_hub_api.player_dataset import load_player_directory

pytestmark = pytest.mark.skipif(
    os.environ.get("FDH_MATCH_03_INTEGRATION") != "1",
    reason="Opt-in offline campaign publication test; set FDH_MATCH_03_INTEGRATION=1",
)

DATA_ROOT = Path(os.environ.get("FDH_MATCH_03_DATA_ROOT", Path.home() / "FootballDataHub-data")).expanduser()
GENERATION_ID = "match-00-4ad1d610507e425d"
INVENTORY_ID = "match-detail-inventory-8cf339654c80c0ef"
CAMPAIGN_ID = "match-detail-sample-campaign-67fdc4b4fac66b82"
ARTIFACT_ID = "discovery-20261018T112656Z-4543b211"
INTERNAL_ID = "pf-2026-27-group-ii-bdfutbol-272525"
LEGACY_INTERNAL_ID = "pf-2026-27-group-ii-bdfutbol-272582"


def _campaign_path(data_root: Path) -> Path:
    return (
        data_root / "matches/details/campaigns" / CAMPAIGN_ID / "candidates"
        / INTERNAL_ID / "artifacts" / ARTIFACT_ID
    )


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


def test_272525_campaign_publication_cycle_is_temporary_and_api_readable(tmp_path, monkeypatch):
    data_root = DATA_ROOT
    generation_root = data_root / "matches/generations" / GENERATION_ID
    inventory_root = data_root / "matches/details/inventories" / INVENTORY_ID
    campaign_root = data_root / "matches/details/campaigns" / CAMPAIGN_ID
    artifact = _campaign_path(data_root)
    player_inputs = [
        data_root / "players/inventory-2026-27",
        data_root / "players/compact-2026-27",
        data_root / "team-captures",
        data_root / "published/team_profiles_2026-27.json",
    ]
    if not all(path.exists() for path in [generation_root, inventory_root, campaign_root, artifact, *player_inputs]):
        pytest.skip("Faltan capturas locales; la prueba no descarga ni regenera fuentes")

    checkpoint = data_root / "matches/details/states" / f"{INVENTORY_ID}.json"
    original_public_index = data_root / "matches/details/published/index.json"
    source_paths = [
        generation_root,
        inventory_root,
        campaign_root,
        player_inputs[0] / "manifest.json",
        player_inputs[3],
        checkpoint,
        original_public_index,
    ]
    before = _hash_paths(source_paths)

    generation = load_verified_match_generation(generation_root, data_root=data_root)
    inventory = build_match_detail_inventory(generation)
    record = next(item for item in inventory["matches"] if item["internal_id"] == INTERNAL_ID)
    observation = parse_campaign_saved_artifact(
        artifact, expected_match=record, verified_generation=generation, data_root=data_root
    )
    assert observation.validation.semantic_valid is True
    assert observation.validation.promotion_eligible is False
    assert observation.source.promotion_eligible is False

    player_directory = load_player_directory(
        inventory_root=player_inputs[0],
        compact_root=player_inputs[1],
        team_captures_root=player_inputs[2],
        published_index_path=player_inputs[3],
    )
    player_ids = set(player_directory.players_by_id)
    match_bundle = load_match_results_dataset(generation_root, data_root=data_root)
    assert build_match_page(match_bundle, INTERNAL_ID).detail_status == "not_available"
    assert build_match_page(match_bundle, LEGACY_INTERNAL_ID).detail_status == "not_available"
    active_publications = load_published_match_details(
        data_root / "matches/details/published",
        store_root=data_root / "matches/details",
        generation_root=generation_root,
        data_root=data_root,
        match_bundle=match_bundle,
        player_ids=player_ids,
    )
    assert set(active_publications) == {INTERNAL_ID}
    assert LEGACY_INTERNAL_ID not in active_publications
    active_page = build_match_page(
        match_bundle, INTERNAL_ID, details=active_publications.get(INTERNAL_ID)
    )
    assert active_page.detail_status == "available"
    assert active_page.details is not None
    assert active_page.details.publication_status == "approved"
    assert build_match_page(match_bundle, LEGACY_INTERNAL_ID).detail_status == "not_available"

    published_root = tmp_path / "published"
    store_root = data_root / "matches/details"
    draft = build_campaign_publication_draft(
        internal_id=INTERNAL_ID,
        campaign_id=CAMPAIGN_ID,
        artifact_id=ARTIFACT_ID,
        generation_root=generation_root,
        data_root=data_root,
        match_bundle=match_bundle,
        player_ids=player_ids,
    )
    summary = _summary(draft)
    assert summary["status"] == "VALIDATED_NOT_PUBLISHED"
    assert summary["teams"] == [204, 61]
    assert summary["team_names"] == ["Teruel", "Real Madrid Castilla"]
    assert summary["score"] == [0, 0]
    assert summary["matchday"] == 1
    assert summary["starters"] == [11, 11]
    assert summary["substitutes"] == [7, 10]
    assert draft["capture_promotion_enabled"] is False
    assert draft["promotion_eligible"] is False

    # This fixture approval is deliberately isolated inside pytest tmp_path;
    # an unapproved/tampered attempt must leave the public index absent.
    with pytest.raises(MatchDetailsLoadError):
        publish_campaign_match_detail_draft(
            draft,
            approval_receipt={},
            published_root=published_root,
            store_root=store_root,
            generation_root=generation_root,
            data_root=data_root,
            match_bundle=match_bundle,
            player_ids=player_ids,
        )
    assert not (published_root / "index.json").exists()

    approval = build_campaign_approval_receipt(
        draft,
        approved_by="pytest isolated fixture (not a human approval)",
        confirm_internal_id=INTERNAL_ID,
        confirm_source_html_sha256=draft["source_html_sha256"],
        confirm_details_sha256=draft["details_sha256"],
        confirm_action=campaign_approval_confirmation(draft),
    )
    draft_path = write_immutable_publication_json(tmp_path / "drafts/draft.json", draft)
    approval_path = write_immutable_publication_json(tmp_path / "approvals/receipt.json", approval)
    assert json.loads(draft_path.read_text()) == draft
    assert json.loads(approval_path.read_text()) == approval

    tampered = json.loads(json.dumps(draft))
    tampered["details"]["home_goals"] = 1
    with pytest.raises(MatchDetailsLoadError, match="borrador"):
        publish_campaign_match_detail_draft(
            tampered,
            approval_receipt=approval,
            published_root=published_root,
            store_root=store_root,
            generation_root=generation_root,
            data_root=data_root,
            match_bundle=match_bundle,
            player_ids=player_ids,
        )

    published = publish_campaign_match_detail_draft(
        draft,
        approval_receipt=approval,
        published_root=published_root,
        store_root=store_root,
        generation_root=generation_root,
        data_root=data_root,
        match_bundle=match_bundle,
        player_ids=player_ids,
    )
    assert published["internal_id"] == INTERNAL_ID
    index_before_repeat = (published_root / "index.json").read_bytes()
    repeated = publish_campaign_match_detail_draft(
        draft,
        approval_receipt=approval,
        published_root=published_root,
        store_root=store_root,
        generation_root=generation_root,
        data_root=data_root,
        match_bundle=match_bundle,
        player_ids=player_ids,
    )
    assert repeated == published
    assert (published_root / "index.json").read_bytes() == index_before_repeat
    loaded = load_published_match_details(
        published_root,
        store_root=store_root,
        generation_root=generation_root,
        data_root=data_root,
        match_bundle=match_bundle,
        player_ids=player_ids,
    )
    details = loaded[INTERNAL_ID]
    assert details.publication_status == "approved"
    assert details.home.coach is not None and details.away.coach is not None
    assert len(details.home.starters or []) == len(details.away.starters or []) == 11
    assert len(details.home.substitutes or []) == 7
    assert len(details.away.substitutes or []) == 10
    assert Counter(event.event_kind for event in details.events or []) == {
        "substitution_in": 9,
        "substitution_out": 9,
        "yellow_card": 4,
        "missed_penalty": 1,
        "red_card": 1,
    }
    assert LEGACY_INTERNAL_ID not in loaded

    monkeypatch.setenv("FDH_LOCAL_DATA_ROOT", str(data_root))
    settings = replace(
        ApiSettings.from_env(),
        local_data_root=data_root,
        match_generation_root=generation_root,
        match_details_store_root=store_root,
        match_details_published_root=published_root,
    )
    app = create_app(settings)
    # Exercise the production FastAPI route without starting unrelated team,
    # referee, statistics and roster loaders in its application-wide lifespan.
    # The exact match dataset and publication loader were already verified above.
    app.state.match_results = match_bundle
    app.state.match_detail_documents = {}
    production_route = next(
        route for route in app.routes
        if getattr(route, "path", None) == "/api/v1/matches/{internal_id}"
    )
    test_api = FastAPI()

    @test_api.get("/api/v1/matches/{internal_id}", response_model=production_route.response_model)
    async def dispatch_match_page(internal_id: str, request: Request):
        # Call the production handler directly so unrelated synchronous handlers
        # do not enter the sandbox's restricted AnyIO worker-thread pool.
        production_scope = dict(request.scope)
        production_scope["app"] = app
        return production_route.endpoint(
            internal_id, Request(production_scope), Response()
        )

    async def request_pages():
        async with AsyncClient(transport=ASGITransport(app=test_api), base_url="http://football-data-hub.test") as client:
            published_response = await client.get(f"/api/v1/matches/{INTERNAL_ID}")
            legacy_response = await client.get(f"/api/v1/matches/{LEGACY_INTERNAL_ID}")
            return published_response, legacy_response

    unpublished_response, unpublished_legacy = asyncio.run(request_pages())
    assert unpublished_response.status_code == 200
    assert unpublished_response.json()["detail_status"] == "not_available"
    assert unpublished_response.json()["details"] is None
    assert unpublished_legacy.json()["detail_status"] == "not_available"

    app.state.match_detail_documents = loaded
    published_response, legacy_response = asyncio.run(request_pages())
    assert published_response.status_code == 200
    assert published_response.json()["detail_status"] == "available"
    assert len(published_response.json()["details"]["home"]["starters"]) == 11
    assert published_response.json()["details"]["home"]["coach"]["display_name"]
    assert legacy_response.status_code == 200
    assert legacy_response.json()["detail_status"] == "not_available"
    assert legacy_response.json()["details"] is None
    assert before == _hash_paths(source_paths)
