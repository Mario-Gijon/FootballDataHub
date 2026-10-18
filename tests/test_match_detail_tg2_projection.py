from __future__ import annotations

from types import SimpleNamespace

from football_data_hub.providers.bdfutbol.match_details.semantic_parser import (
    parse_match_detail_html,
)
from football_data_hub_api.match_details_dataset import build_discovery_preview
from tests.match_detail_semantic_fixtures import (
    DISCOVERY_ID,
    INVENTORY_ID,
    expected_match,
    match_html,
    metadata_for,
)


def test_second_yellow_is_projected_as_its_own_api_event_kind():
    html = match_html().replace(
        b'class="TG" title="Tarjeta Amarilla"',
        b'class="TG2" title="Doble Tarjeta Amarilla"',
        1,
    )
    expected = expected_match()
    observation = parse_match_detail_html(
        html,
        expected_match=expected,
        metadata=metadata_for(html),
        discovery_id=DISCOVERY_ID,
        inventory_id=INVENTORY_ID,
    )
    match_page = SimpleNamespace(
        match=SimpleNamespace(
            internal_id=expected["internal_id"],
            source_match_id=expected["source_match_id"],
            home_team=SimpleNamespace(team_id=expected["home_team_id"]),
            away_team=SimpleNamespace(team_id=expected["away_team_id"]),
            home_goals=1,
            away_goals=1,
        ),
        metadata=SimpleNamespace(
            generation_id=expected["source_generation_id"],
            source_capture_id=expected["source_capture_id"],
        ),
    )

    response = build_discovery_preview(
        observation, match_page=match_page, player_ids=set()
    )

    second_yellow = next(
        event for event in response.events or [] if event.event_kind == "second_yellow"
    )
    assert second_yellow.player_id == 1002
    assert second_yellow.minute == "45"
