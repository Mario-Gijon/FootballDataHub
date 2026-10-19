from __future__ import annotations

from types import SimpleNamespace

from bs4 import BeautifulSoup

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


def test_own_goal_and_source_event_description_survive_preview_projection():
    soup = BeautifulSoup(match_html(), "html.parser")
    away_summary = soup.select_one('.hero-partit .col-6.col-sm.f14 .text-left .text-blanc')
    assert away_summary is not None
    away_summary.clear()
    score = soup.new_tag("span")
    score.string = "0-1"
    away_summary.append(score)
    scorer = soup.new_tag("a", href="../j/j1002.html")
    scorer.string = "Home Exit"
    away_summary.append(scorer)
    away_summary.append(" 6' (pp)")
    prior_goal = soup.select_one('div.container table.taula_estil a[href$="/j/j2001.html"]')
    assert prior_goal is not None
    old_icon = prior_goal.find_parent("tr").select_one('.cosa .G[title="Gol"]')
    assert old_icon is not None
    old_icon.find_parent("div", class_="cosa").decompose()
    home_player = soup.select_one('div.container table.taula_estil a[href$="/j/j1002.html"]')
    assert home_player is not None
    home_event_cell = home_player.find_parent("tr").find_all(["td", "th"], recursive=False)[-1]
    own_goal = soup.new_tag("div", attrs={"class": "cosa"})
    own_goal.append(soup.new_tag("div", attrs={"class": "GPP", "title": "Gol en propia puerta"}))
    own_goal.append("6")
    home_event_cell.append(own_goal)
    injury = soup.new_tag("div", attrs={"class": "cosa"})
    injury.append(soup.new_tag("div", attrs={"class": "L", "title": "Lesión"}))
    injury.append("9")
    home_event_cell.append(injury)
    html = str(soup).encode()

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

    response = build_discovery_preview(observation, match_page=match_page, player_ids=set())
    own_goal_event = next(event for event in response.events or [] if event.event_kind == "own_goal")
    injury_event = next(event for event in response.events or [] if event.event_kind == "other")
    assert own_goal_event.team_id == expected["home_team_id"]
    assert own_goal_event.is_own_goal is True
    assert own_goal_event.score_after_home == 0 and own_goal_event.score_after_away == 1
    assert injury_event.source_description == "Lesión"
