from __future__ import annotations

import hashlib
import socket
import urllib.request

import pytest
from bs4 import BeautifulSoup

from football_data_hub.providers.bdfutbol.match_details.semantic_parser import (
    MatchDetailParserError,
    _event_kind,
    _parse_date_and_kickoff,
    parse_match_detail_html,
    parse_saved_artifact,
)
from tests.match_detail_semantic_fixtures import (
    DISCOVERY_ID,
    INVENTORY_ID,
    expected_match,
    match_html,
    metadata_for,
    score_scenario_html,
    saved_artifact,
)


def _parse(html: bytes, expected: dict | None = None):
    return parse_match_detail_html(
        html,
        expected_match=expected or expected_match(),
        metadata=metadata_for(html),
        discovery_id=DISCOVERY_ID,
        inventory_id=INVENTORY_ID,
    )


def _replace_player_id(html: bytes, original: int, replacement: int) -> bytes:
    html = html.replace(
        f"j{original}.html".encode(), f"j{replacement}.html".encode(), 1
    )
    return html.replace(
        f"/m/{original}.png".encode(), f"/m/{replacement}.png".encode(), 1
    )


@pytest.mark.parametrize(
    ("raw", "expected_date", "expected_time", "expected_state", "expected_error"),
    [
        ("Sábado 29/08/2026 (19:15)", "2026-08-29", "19:15", "observed", None),
        ("Sábado 29/08/2026", "2026-08-29", None, "explicitly_absent", None),
        ("Sábado 29/08/2026 (25:90)", "2026-08-29", None, "unresolved", "kickoff_time_out_of_range"),
        ("Sábado 29/08/2026 (19:15) y 20:30", "2026-08-29", None, "unresolved", "kickoff_time_ambiguous"),
        ("Sábado 29/08/2026 (hora pendiente)", "2026-08-29", None, "unresolved", "kickoff_time_ambiguous"),
        ("Sábado 29/08/2026 (19:15 CET)", "2026-08-29", None, "unresolved", "kickoff_time_format_unrecognized"),
    ],
)
def test_kickoff_parser_preserves_date_and_classifies_optional_time(
    raw, expected_date, expected_time, expected_state, expected_error
):
    actual_date, actual_time, state, error = _parse_date_and_kickoff(raw)
    assert (actual_date, actual_time, state, error) == (
        expected_date, expected_time, expected_state, expected_error
    )


def test_semantic_match_date_remains_valid_when_source_has_no_kickoff_time():
    html = match_html().replace(
        b"S\xc3\xa1bado 10/10/2026 (18:45)",
        b"S\xc3\xa1bado 10/10/2026",
    )
    observation = _parse(html)
    assert observation.validation.semantic_valid is True
    assert observation.match_date.value == "2026-10-10"
    assert observation.kickoff_time_local.value is None
    assert observation.kickoff_time_local.state == "explicitly_absent"
    assert observation.kickoff_time_local.raw_value == "Sábado 10/10/2026"
    assert observation.timezone.state == "not_observed"


def test_parses_semantic_fixture_and_preserves_discovery_only_status():
    observation = _parse(match_html(noise_tables=64))

    assert observation.validation.semantic_valid is True
    assert observation.validation.errors == ()
    assert observation.validation.promotion_eligible is False
    assert observation.source.promotion_eligible is False
    assert observation.source.source_match_id == "272582"
    assert observation.source.discovery_id == DISCOVERY_ID
    assert observation.source.inventory_id == INVENTORY_ID
    assert observation.source.artifact_access_status == "INVALID_CONTENT"
    assert not hasattr(observation.source, "capture_id")
    assert observation.home.team.team_id == 49
    assert observation.away.team.team_id == 94
    assert observation.score.home_goals == observation.score.away_goals == 1
    assert observation.match_date.value == "2026-10-10"
    assert observation.kickoff_time_local.value == "18:45"
    assert observation.timezone.value is None
    assert observation.context.group.value == "II"
    assert observation.context.group.state == "not_observed"
    assert observation.context.group.origin == "match_catalog"
    assert len(observation.home.starters or ()) == 11
    assert len(observation.away.starters or ()) == 11
    assert len(observation.home.substitutes or ()) == 2
    assert len(observation.away.substitutes or ()) == 1
    assert observation.home.coach and observation.home.coach.name == "Manolo Herrero"
    assert observation.away.coach and observation.away.coach.name == "Albelda"
    assert observation.aggregate_statistics_state == "explicitly_absent"
    assert any(
        check.check == "goal_score_progression_is_chronologically_consistent"
        and check.passed
        for check in observation.validation.checks
    )

    goals = [event for event in observation.events if event.event_type in {"goal", "penalty_goal"}]
    assert len(goals) == 2  # The header summary and lineup icons are reconciled, not duplicated.
    assert {(event.side, event.event_type, event.minute_literal) for event in goals} == {
        ("home", "penalty_goal", "90+1"),
        ("away", "goal", "6"),
    }
    assert all(event.minute_base is not None for event in goals)
    assert all(item.source_html_sha256 == observation.source.source_html_sha256 for item in observation.evidence)
    assert all(item.parser_version == observation.source.parser_version for item in observation.evidence)


def test_own_goal_reconciles_credit_side_with_player_team_and_progression():
    soup = BeautifulSoup(match_html(), "html.parser")
    away_summary = soup.select_one(
        '.hero-partit .col-6.col-sm.f14 .text-left .text-blanc'
    )
    assert away_summary is not None
    away_summary.clear()
    score = soup.new_tag("span")
    score.string = "0-1"
    away_summary.append(score)
    scorer = soup.new_tag("a", href="../j/j1002.html")
    scorer.string = "Home Exit"
    away_summary.append(scorer)
    away_summary.append(" 6' (pp)")

    old_away_goal = soup.select_one(
        'div.container table.taula_estil a[href$="/j/j2001.html"]'
    )
    assert old_away_goal is not None
    old_away_goal.find_parent("tr").select_one('.cosa .G[title="Gol"]').find_parent("div", class_="cosa").decompose()
    home_scorer = soup.select_one(
        'div.container table.taula_estil a[href$="/j/j1002.html"]'
    )
    assert home_scorer is not None
    event_cell = home_scorer.find_parent("tr").find_all(["td", "th"], recursive=False)[-1]
    event = soup.new_tag("div", attrs={"class": "cosa"})
    event.append(soup.new_tag("div", attrs={"class": "GPP", "title": "Gol en propia puerta"}))
    event.append("6")
    event_cell.append(event)

    observation = _parse(str(soup).encode())

    assert observation.validation.semantic_valid is True, observation.validation.errors
    own_goal = next(item for item in observation.events if item.event_type == "own_goal")
    assert (own_goal.side, own_goal.team_id, own_goal.player_id, own_goal.minute_literal) == (
        "home", 49, 1002, "6"
    )
    assert own_goal.score_after_home == 0 and own_goal.score_after_away == 1
    assert any(
        item.check == "goal_score_progression_is_chronologically_consistent" and item.passed
        for item in observation.validation.checks
    )


def test_own_goal_with_incompatible_partial_score_is_rejected():
    # Build the same source shape as the accepted own-goal case, then make the
    # credited score contradict the scorer's own team and chronological result.
    soup = BeautifulSoup(match_html(), "html.parser")
    away_summary = soup.select_one('.hero-partit .col-6.col-sm.f14 .text-left .text-blanc')
    assert away_summary is not None
    away_summary.clear()
    score = soup.new_tag("span")
    score.string = "1-0"
    away_summary.append(score)
    scorer = soup.new_tag("a", href="../j/j1002.html")
    scorer.string = "Home Exit"
    away_summary.append(scorer)
    away_summary.append(" 6' (pp)")
    old_away_goal = soup.select_one('div.container table.taula_estil a[href$="/j/j2001.html"]')
    assert old_away_goal is not None
    icon = old_away_goal.find_parent("tr").select_one('.cosa .G[title="Gol"]')
    assert icon is not None
    icon.find_parent("div", class_="cosa").decompose()
    home_scorer = soup.select_one('div.container table.taula_estil a[href$="/j/j1002.html"]')
    assert home_scorer is not None
    event_cell = home_scorer.find_parent("tr").find_all(["td", "th"], recursive=False)[-1]
    event = soup.new_tag("div", attrs={"class": "cosa"})
    event.append(soup.new_tag("div", attrs={"class": "GPP", "title": "Gol en propia puerta"}))
    event.append("6")
    event_cell.append(event)

    observation = _parse(str(soup).encode())
    assert observation.validation.semantic_valid is False
    assert "goal_score_progression_invalid" in observation.validation.errors


def test_injury_icon_is_preserved_as_a_described_other_event():
    html = match_html().replace(
        b'class="TG" title="Tarjeta Amarilla"></div>45',
        b'class="L" title="Lesi\xc3\xb3n"></div>9',
        1,
    )
    observation = _parse(html)
    assert observation.validation.semantic_valid is True
    injury = next(item for item in observation.events if item.event_type == "other")
    assert injury.raw_icon_class == "L"
    assert injury.raw_icon_title == "Lesión"
    assert injury.minute_literal == "9"


def test_stadium_opaque_slug_is_preserved_without_numeric_coercion():
    html = match_html().replace(b"../s/100355.html", b"../s/39b.html")
    observation = _parse(html)
    assert observation.validation.semantic_valid is True
    assert observation.stadium_id.value == "39b"
    assert observation.stadium_url.value == "https://www.bdfutbol.com/es/s/39b.html"


def test_substitute_can_enter_then_leave_without_inventing_a_pair():
    soup = BeautifulSoup(match_html(), "html.parser")
    entered = soup.select_one('div.container table.taula_estil a[href$="/j/j1101.html"]')
    assert entered is not None
    event_cell = entered.find_parent("tr").find_all(["td", "th"], recursive=False)[-1]
    outgoing = soup.new_tag("div", attrs={"class": "cosa"})
    outgoing.append(soup.new_tag("div", attrs={"class": "Surt", "title": "Sale"}))
    outgoing.append("80")
    event_cell.append(outgoing)

    table = entered.find_parent("table")
    replacement = BeautifulSoup(
        '<tr><td>3</td><td><img class="mini-foto-jugador" src="../../i/m/1103.png"></td>'
        '<td><div class="pais espanya"></div></td><td><a href="../j/j1103.html">Replacement Sub</a></td>'
        '<td><div class="cosa"><div class="Entra" title="Entra"></div>80</div></td><td></td></tr>',
        "html.parser",
    ).tr
    assert table is not None and replacement is not None
    table.tbody.append(replacement)

    observation = _parse(str(soup).encode())
    assert observation.validation.semantic_valid is True, observation.validation.errors
    assert any(
        event.player_id == 1101 and event.event_type == "substitution_out" and event.minute_literal == "80"
        for event in observation.events
    )
    assert any(
        event.player_id == 1103 and event.event_type == "substitution_in" and event.minute_literal == "80"
        for event in observation.events
    )
    assert not any(hasattr(event, "related_player_id") for event in observation.events)


def test_substitute_out_without_incoming_marker_remains_rejected():
    soup = BeautifulSoup(match_html(), "html.parser")
    substitute = soup.select_one('div.container table.taula_estil a[href$="/j/j1102.html"]')
    assert substitute is not None
    row_cells = substitute.find_parent("tr").find_all(["td", "th"], recursive=False)
    row_cells[-2].clear()
    event_cell = row_cells[-1]
    outgoing = soup.new_tag("div", attrs={"class": "cosa"})
    outgoing.append(soup.new_tag("div", attrs={"class": "Surt", "title": "Sale"}))
    outgoing.append("80")
    event_cell.append(outgoing)
    observation = _parse(str(soup).encode())
    assert observation.validation.semantic_valid is False
    assert "substitute_has_outgoing_marker:home:1102" in observation.validation.errors


def test_reconciles_cards_and_simultaneous_substitution_events_without_pairing():
    observation = _parse(match_html())
    home_cards = [event for event in observation.events if event.side == "home" and event.event_type == "yellow_card"]
    away_cards = [event for event in observation.events if event.side == "away" and event.event_type == "yellow_card"]
    assert len(home_cards) == 1
    assert len(away_cards) == 1
    assert home_cards[0].minute_literal == "45"

    simultaneous = [
        event for event in observation.events
        if event.side == "home" and event.minute_literal == "66" and "substitution" in event.event_type
    ]
    assert len(simultaneous) == 4
    assert {event.event_type for event in simultaneous} == {"substitution_in", "substitution_out"}
    assert not any(hasattr(event, "related_player_id") for event in simultaneous)


def test_preserves_extra_time_minutes_and_recognizes_red_cards():
    html = match_html().replace(
        b'class="TG" title="Tarjeta Amarilla"></div>45',
        b'class="TG" title="Tarjeta Amarilla"></div>45+2',
        1,
    )
    html = html.replace(
        b'Home Player 4</a></td><td></td><td></td>',
        b'Home Player 4</a></td><td></td><td><div class="cosa"><div class="TR" title="Tarjeta Roja"></div>90</div></td>',
        1,
    )
    observation = _parse(html)

    yellow = next(event for event in observation.events if event.event_type == "yellow_card")
    red = next(event for event in observation.events if event.event_type == "red_card")
    assert (yellow.minute_literal, yellow.minute_base, yellow.minute_added) == ("45+2", 45, 2)
    assert (red.player_name, red.minute_literal) == ("Home Player 4", "90")
    assert not any(
        item.field_path == "events.red_cards" and item.state == "explicitly_absent"
        for item in observation.evidence
    )


def test_tg2_is_a_second_yellow_dismissal_not_a_yellow_or_direct_red_card():
    html = match_html().replace(
        b'class="TG" title="Tarjeta Amarilla"',
        b'class="TG2" title="Doble Tarjeta Amarilla"',
        1,
    )
    observation = _parse(html)

    assert observation.validation.semantic_valid is True
    event = next(
        item
        for item in observation.events
        if item.player_id == 1002 and item.event_type == "second_yellow"
    )
    assert event.event_type == "second_yellow"
    assert event.minute_literal == "45"
    assert event.raw_icon_class == "TG2"
    assert event.raw_icon_title == "Doble Tarjeta Amarilla"
    assert not any(item.event_type in {"yellow_card", "red_card"} for item in observation.events if item.player_id == 1002)
    red_evidence = next(item for item in observation.evidence if item.field_path == "events.red_cards")
    assert red_evidence.state == "not_observed"
    second_yellow_evidence = next(item for item in observation.evidence if item.field_path == "events.second_yellows")
    assert second_yellow_evidence.state == "observed"
    assert second_yellow_evidence.normalized_value == 1
    assert "icon=TG2" in second_yellow_evidence.source_reference
    assert "direct_red_card_absence_not_asserted_second_yellow_present" in observation.validation.warnings


def test_tg2_with_an_unverified_title_remains_a_blocking_unknown_icon():
    html = match_html().replace(
        b'class="TG" title="Tarjeta Amarilla"',
        b'class="TG2" title="Tarjeta Amarilla"',
        1,
    )
    observation = _parse(html)

    assert observation.validation.semantic_valid is False
    assert "unknown_event_icon:home:1002:TG2:Tarjeta Amarilla" in observation.validation.errors
    red_evidence = next(item for item in observation.evidence if item.field_path == "events.red_cards")
    assert red_evidence.state == "not_observed"


@pytest.mark.parametrize(
    ("icon", "expected"),
    [
        ('<div class="PF" title="Penalty Fallado"></div>', "missed_penalty"),
        ('<div class="TV" title="Expulsión"></div>', "red_card"),
        ('<div class="GPP" title="Gol en propia puerta"></div>', "own_goal"),
        ('<div class="L" title="Lesión"></div>', "other"),
    ],
)
def test_campaign_event_icons_keep_their_verified_semantics(icon, expected):
    node = BeautifulSoup(icon, "html.parser").div
    assert node is not None
    assert _event_kind(node) == expected


def test_goal_summary_and_icon_disagreement_is_not_repaired():
    html = match_html().replace(
        b'class="GP" title="Gol de Penalty"',
        b'class="G" title="Gol"',
        1,
    )
    observation = _parse(html)

    assert observation.validation.semantic_valid is False
    assert "goal_summary_and_lineup_markers_disagree" in observation.validation.errors
    assert sum(
        event.event_type in {"goal", "penalty_goal"} for event in observation.events
    ) == 2


def test_competition_label_mismatch_fails_even_when_season_link_is_correct():
    html = match_html().replace("1ª RFEF".encode(), "Copa Federación".encode())
    observation = _parse(html)

    assert observation.validation.semantic_valid is False
    assert observation.context.season.value == "2026-27"
    assert "competition_label_mismatch" in observation.validation.errors
    assert any(
        check.check == "competition_label_is_primera_federacion" and not check.passed
        for check in observation.validation.checks
    )
    assert any(
        error == "critical_evidence_unresolved:context.competition"
        for error in observation.validation.errors
    )


def test_unresolved_catalog_season_link_cannot_leave_validation_semantically_valid():
    html = match_html().replace(
        b"../t/t2026-271rf2.html", b"../t/t2025-261rf2.html"
    )
    observation = _parse(html)

    assert observation.context.season.state == "unresolved"
    assert observation.context.season.value is None
    assert observation.validation.semantic_valid is False
    assert "critical_evidence_unresolved:context.season" in observation.validation.errors


@pytest.mark.parametrize(
    ("needle", "replacement", "error_fragment", "evidence_fragment"),
    [
        (
            b'class="TG" title="Tarjeta Amarilla"></div>45',
            b'class="TG" title="Tarjeta Amarilla"></div>minuto desconocido',
            "recognized_event_missing_minute:yellow_card",
            "events.yellow_card",
        ),
        (
            b'class="Surt" title="Sale"></div>66',
            b'class="Surt" title="Sale"></div>sin minuto',
            "recognized_event_missing_minute:substitution_out",
            "events.substitution_out",
        ),
        (
            b'class="Entra" title="Entra"></div>66',
            b'class="Entra" title="Entra"></div>sin minuto',
            "recognized_event_missing_minute:substitution_in",
            "events.substitution_in",
        ),
        (
            b'class="GP" title="Gol de Penalty"></div>90+1',
            b'class="GP" title="Gol de Penalty"></div>sin minuto',
            "recognized_event_missing_minute:penalty_goal",
            "events.penalty_goal",
        ),
    ],
)
def test_recognized_roster_events_require_minutes_and_preserve_raw_text(
    needle, replacement, error_fragment, evidence_fragment
):
    observation = _parse(match_html().replace(needle, replacement, 1))

    assert observation.validation.semantic_valid is False
    assert any(error_fragment in error for error in observation.validation.errors)
    evidence = next(
        item for item in observation.evidence if item.field_path.startswith(evidence_fragment)
    )
    assert evidence.state == "unresolved"
    assert "sin minuto" in (evidence.raw_value or "") or "desconocido" in (
        evidence.raw_value or ""
    )


def test_goal_summary_without_minute_keeps_source_text_and_fails():
    html = match_html().replace(
        b"Home Scorer</a> 90+1' (pen)", b"Home Scorer</a> (pen)", 1
    )
    observation = _parse(html)

    assert observation.validation.semantic_valid is False
    assert "goal_minute_unverified:home:0" in observation.validation.errors
    evidence = next(
        item
        for item in observation.evidence
        if item.field_path == "events.goal[home.1001].minute"
    )
    assert evidence.state == "unresolved"
    assert "Home Scorer" in (evidence.raw_value or "")


def test_impossible_goal_partial_score_progression_fails():
    html = match_html().replace(
        b"<span>1-1</span> <a href=\"../j/j1001.html\">Home Scorer",
        b"<span>1-0</span> <a href=\"../j/j1001.html\">Home Scorer",
        1,
    )
    observation = _parse(html)

    assert observation.validation.semantic_valid is False
    assert "goal_score_progression_invalid" in observation.validation.errors
    assert any(
        check.check == "goal_score_progression_is_chronologically_consistent"
        and not check.passed
        for check in observation.validation.checks
    )


def test_equal_minute_goals_are_validated_across_possible_orders():
    html = match_html().replace(
        b"Home Scorer</a> 90+1' (pen)", b"Home Scorer</a> 6' (pen)", 1
    )
    html = html.replace(
        b'class="GP" title="Gol de Penalty"></div>90+1',
        b'class="GP" title="Gol de Penalty"></div>6',
        1,
    )
    observation = _parse(html)

    assert observation.validation.semantic_valid is True
    progression = next(
        check
        for check in observation.validation.checks
        if check.check == "goal_score_progression_is_chronologically_consistent"
    )
    assert progression.passed


@pytest.mark.parametrize(
    ("home_score", "away_score", "goals"),
    [
        (0, 0, []),
        (
            1,
            0,
            [
                {
                    "side": "home",
                    "player_id": 1001,
                    "minute": "90+1",
                    "after_home": 1,
                    "after_away": 0,
                    "penalty": True,
                }
            ],
        ),
        (
            0,
            3,
            [
                {"side": "away", "player_id": 2001, "minute": "6", "after_home": 0, "after_away": 1},
                {"side": "away", "player_id": 2001, "minute": "45+2", "after_home": 0, "after_away": 2},
                {"side": "away", "player_id": 2001, "minute": "90+1", "after_home": 0, "after_away": 3},
            ],
        ),
        (
            3,
            3,
            [
                {"side": "home", "player_id": 1001, "minute": "20", "after_home": 1, "after_away": 0},
                {"side": "away", "player_id": 2001, "minute": "45", "after_home": 1, "after_away": 1},
                {"side": "home", "player_id": 1001, "minute": "66", "after_home": 2, "after_away": 1},
                {"side": "away", "player_id": 2001, "minute": "66", "after_home": 2, "after_away": 2},
                {"side": "home", "player_id": 1001, "minute": "90+2", "after_home": 3, "after_away": 2},
                {"side": "away", "player_id": 2001, "minute": "90+2", "after_home": 3, "after_away": 3},
            ],
        ),
    ],
    ids=("0-0-no-goals", "1-0-penalty-added-time", "0-3-repeat-scorer", "3-3-same-minute"),
)
def test_synthetic_score_scenarios_are_reconciled_without_fabricating_goals(
    home_score, away_score, goals
):
    html, expected = score_scenario_html(home_score, away_score, goals)
    observation = _parse(html, expected)

    assert observation.validation.semantic_valid is True
    assert (observation.score.home_goals, observation.score.away_goals) == (
        home_score,
        away_score,
    )
    parsed_goals = [
        event
        for event in observation.events
        if event.event_type in {"goal", "penalty_goal"}
    ]
    assert len(parsed_goals) == len(goals)
    assert sum(event.side == "home" for event in parsed_goals) == home_score
    assert sum(event.side == "away" for event in parsed_goals) == away_score
    assert all(event.minute_base is not None for event in parsed_goals)
    if home_score == 0 and away_score == 0:
        assert parsed_goals == []
    if goals and goals[0].get("penalty"):
        assert parsed_goals[0].event_type == "penalty_goal"


def test_incomplete_goal_summary_is_not_treated_as_zero_or_repaired():
    html, expected = score_scenario_html(
        1,
        1,
        [
            {
                "side": "away",
                "player_id": 2001,
                "minute": "6",
                "after_home": 0,
                "after_away": 1,
            }
        ],
    )
    observation = _parse(html, expected)

    assert observation.score.home_goals == observation.score.away_goals == 1
    assert observation.validation.semantic_valid is False
    assert "goal_event_count_does_not_match_score" in observation.validation.errors
    assert "goal_score_progression_invalid" in observation.validation.errors


def test_missing_goal_summary_structure_fails_closed():
    soup = BeautifulSoup(match_html(), "html.parser")
    hero = soup.select_one("div.hero.hero-partit")
    assert hero is not None
    for column in hero.select("div.col-6.col-sm.f14"):
        column.decompose()

    with pytest.raises(MatchDetailParserError, match="resumen de goles"):
        _parse(str(soup).encode())


@pytest.mark.parametrize(
    ("html", "expected_error"),
    [
        (
            _replace_player_id(match_html(), 1004, 1001),
            "duplicate_player_id:starters:home:1001",
        ),
        (
            _replace_player_id(match_html(), 1102, 1101),
            "duplicate_player_id:substitutes:home:1101",
        ),
        (
            _replace_player_id(match_html(), 1101, 1001),
            "player_id_in_starters_and_substitutes:home:1001",
        ),
        (
            _replace_player_id(match_html(), 2004, 1001),
            "player_id_appears_for_both_teams:1001",
        ),
    ],
)
def test_duplicate_player_ids_in_eleven_row_rosters_are_rejected(html, expected_error):
    observation = _parse(html)

    assert len(observation.home.starters or ()) == 11
    assert observation.validation.semantic_valid is False
    assert expected_error in observation.validation.errors
    assert any(
        check.check == "roster_player_ids_are_unique" and not check.passed
        for check in observation.validation.checks
    )


def test_reordered_roster_columns_keep_player_number_and_events_associated():
    soup = BeautifulSoup(match_html(), "html.parser")
    data_row = soup.select_one(
        "div.container > div.row.pt-3.pb-2[style*=overflow]"
    )
    assert data_row is not None
    for table in data_row.select("table.taula_estil"):
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            if len(cells) != 6 or row.select_one('a[href*="/j/j"]') is None:
                continue
            reordered = [cells[3], cells[0], cells[5], cells[2], cells[1], cells[4]]
            for cell in cells:
                cell.extract()
            for cell in reordered:
                row.append(cell)

    observation = _parse(str(soup).encode())

    assert observation.validation.semantic_valid is True
    assert observation.home.starters[0].player_id == 1001
    assert observation.home.starters[0].shirt_number == 1
    assert any(event.player_id == 1001 and event.event_type == "penalty_goal" for event in observation.events)
    assert any(event.player_id == 1002 and event.event_type == "substitution_out" for event in observation.events)


def test_absent_shirt_number_is_preserved_as_null():
    soup = BeautifulSoup(match_html(), "html.parser")
    row = soup.select_one(
        'div.container table.taula_estil a[href$="/j/j1004.html"]'
    )
    assert row is not None
    player_row = row.find_parent("tr")
    assert player_row is not None
    cells = player_row.find_all(["th", "td"], recursive=False)
    cells[0].clear()

    observation = _parse(str(soup).encode())

    appearance = next(item for item in observation.home.starters if item.player_id == 1004)
    assert observation.validation.semantic_valid is True
    assert appearance.shirt_number is None


def test_hidden_roster_row_with_structural_content_is_not_ignored():
    soup = BeautifulSoup(match_html(), "html.parser")
    hidden_row = soup.select_one("table.taula_estil tr[style]")
    assert hidden_row is not None
    hidden_row["style"] = "color: transparent; display : none !important"
    cell = hidden_row.find("td")
    assert cell is not None
    link = soup.new_tag("a", href="../j/j9999.html")
    link.string = "Hidden Player"
    cell.append(link)

    observation = _parse(str(soup).encode())

    assert observation.validation.semantic_valid is False
    assert any(
        error.startswith("hidden_nonempty_roster_row:starter:home:")
        for error in observation.validation.errors
    )


def test_external_or_wrong_host_player_link_is_rejected():
    html = match_html().replace(
        b'href="../j/j1004.html"',
        b'href="https://not-bdfutbol.example/es/j/j1004.html"',
        1,
    )
    observation = _parse(html)

    assert observation.validation.semantic_valid is False
    assert "unknown_player_link:starter:home:4" in observation.validation.errors


def test_incomplete_starter_count_is_not_promoted_to_valid():
    soup = BeautifulSoup(match_html(), "html.parser")
    row = soup.select_one(
        'div.container table.taula_estil a[href$="/j/j1011.html"]'
    )
    assert row is not None
    row.find_parent("tr").decompose()

    observation = _parse(str(soup).encode())

    assert len(observation.home.starters) == 10
    assert observation.validation.semantic_valid is False
    assert "starter_count_not_11:home:10" in observation.validation.errors


def test_reordered_attributes_extra_classes_and_global_noise_remain_cosmetic():
    html = match_html(noise_tables=40).replace(
        b'<div class="hero hero-partit">',
        b'<div data-layout="responsive" class="extra hero-partit hero">',
        1,
    ).replace(
        b'<span class="col-auto resultat-partit">',
        b'<span data-kind="score" class="resultat-partit col-auto extra">',
        4,
    )
    observation = _parse(html)

    assert observation.validation.semantic_valid is True
    assert (observation.score.home_goals, observation.score.away_goals) == (1, 1)


@pytest.mark.parametrize(
    ("removed_event", "expected_counts"),
    [
        (b'<div class="Surt" title="Sale"></div>66', "in=2:out=1"),
        (b'<div class="Entra" title="Entra"></div>66', "in=1:out=2"),
    ],
)
def test_unbalanced_substitution_events_are_reported_without_pairing(
    removed_event, expected_counts
):
    html = match_html().replace(removed_event, b"", 1)
    observation = _parse(html)

    assert any(
        warning == f"substitution_event_balance_mismatch:home:{expected_counts}"
        for warning in observation.validation.warnings
    )
    assert not any(hasattr(event, "related_player_id") for event in observation.events)


def test_no_substitutions_is_distinct_from_an_unobserved_bench():
    soup = BeautifulSoup(match_html(), "html.parser")
    for icon in soup.select(".cosa > div.Surt, .cosa > div.Entra"):
        icon.parent.decompose()

    observation = _parse(str(soup).encode())

    assert observation.validation.semantic_valid is True
    assert observation.home.substitutes is not None
    assert observation.home.substitutes
    assert not any("substitution_" in event.event_type for event in observation.events)
    assert not any(
        warning.startswith("substitution_event_balance_mismatch:")
        for warning in observation.validation.warnings
    )


@pytest.mark.parametrize(("minute", "expected"), [("45", "45"), ("90+4", "90+4")])
def test_halftime_and_added_time_substitutions_preserve_literal_minutes(minute, expected):
    html = match_html().replace(b"></div>66</div>", f"></div>{minute}</div>".encode())
    observation = _parse(html)

    assert observation.validation.semantic_valid is True
    substitutions = [
        event
        for event in observation.events
        if event.event_type in {"substitution_in", "substitution_out"}
    ]
    assert substitutions
    assert {event.minute_literal for event in substitutions} == {expected}


def test_repeated_card_events_for_one_player_are_preserved():
    soup = BeautifulSoup(match_html(), "html.parser")
    row_link = soup.select_one(
        'div.container table.taula_estil a[href$="/j/j1002.html"]'
    )
    assert row_link is not None
    player_row = row_link.find_parent("tr")
    assert player_row is not None
    event_cell = player_row.find_all(["td", "th"], recursive=False)[-1]
    event = soup.new_tag("div", attrs={"class": "cosa"})
    event.append(soup.new_tag("div", attrs={"class": "TG", "title": "Tarjeta Amarilla"}))
    event.append("90+3")
    event_cell.append(event)

    observation = _parse(str(soup).encode())

    assert observation.validation.semantic_valid is True
    same_player_cards = [
        item
        for item in observation.events
        if item.player_id == 1002 and item.event_type == "yellow_card"
    ]
    assert [item.minute_literal for item in same_player_cards] == ["45", "90+3"]


def test_unknown_section_heading_fails_closed():
    html = match_html().replace(b"<h2>Suplentes</h2>", b"<h2>Reservas</h2>")
    observation = _parse(html)

    assert observation.validation.semantic_valid is False
    assert "unknown_section_heading:Reservas" in observation.validation.errors


def test_wrong_embedded_identity_is_reported_without_changing_artifact_state():
    html = match_html().replace(b'value="272582"', b'value="999999"')
    observation = _parse(html)

    assert observation.validation.semantic_valid is False
    assert "embedded_source_id_mismatch" in observation.validation.errors
    assert observation.source.artifact_access_status == "INVALID_CONTENT"
    assert observation.validation.promotion_eligible is False


def test_team_identity_must_match_catalog():
    expected = expected_match()
    expected["home_team_id"] = 48
    with pytest.raises(MatchDetailParserError, match="equipo home no coincide"):
        _parse(match_html(), expected)


def test_score_mismatch_is_a_validation_error_and_not_silently_repaired():
    expected = expected_match()
    expected["reference_result"] = {"home_goals": 2, "away_goals": 1}
    observation = _parse(match_html(), expected)

    assert observation.score.home_goals == 1
    assert observation.score.away_goals == 1
    assert observation.validation.semantic_valid is False
    assert "score_catalog_mismatch" in observation.validation.errors


def test_unknown_event_icon_fails_closed():
    html = match_html().replace(
        b'class="TG" title="Tarjeta Amarilla"',
        b'class="MYSTERY" title="Evento no documentado"',
        1,
    )
    observation = _parse(html)

    assert observation.validation.semantic_valid is False
    assert any(error.startswith("unknown_event_icon:") for error in observation.validation.errors)
    assert any(item.state == "unresolved" and item.normalized_value == "unknown" for item in observation.evidence)


@pytest.mark.parametrize(
    ("old_text", "new_text"),
    [
        (b"></div>45", b"></div>Evento 17"),
        (b"></div>45", b"></div>45+bad"),
    ],
)
def test_minute_parser_does_not_extract_numbers_from_unrecognized_text(old_text, new_text):
    html = match_html().replace(
        b'class="TG" title="Tarjeta Amarilla"' + old_text,
        b'class="TG" title="Tarjeta Amarilla"' + new_text,
        1,
    )
    observation = _parse(html)

    assert observation.validation.semantic_valid is False
    assert "recognized_event_missing_minute:yellow_card:home:1002" in observation.validation.errors
    evidence = next(
        item
        for item in observation.evidence
        if item.field_path.startswith("events.yellow_card[home.1002]")
    )
    assert evidence.state == "unresolved"
    assert "Evento 17" in (evidence.raw_value or "") or "45+bad" in (evidence.raw_value or "")


def test_recognized_icon_with_incompatible_title_fails_closed():
    html = match_html().replace(
        b'class="TG" title="Tarjeta Amarilla"',
        b'class="TG" title="Tarjeta Roja"',
        1,
    )
    observation = _parse(html)

    assert observation.validation.semantic_valid is False
    assert any(error.startswith("unknown_event_icon:home:1002") for error in observation.validation.errors)


def test_optional_bench_coach_and_ephemeris_sections_are_not_fabricated():
    html = match_html(
        include_substitutes=False,
        include_coaches=False,
        include_ephemeris=False,
    )
    observation = _parse(html)

    assert observation.validation.semantic_valid is True
    assert observation.home.substitutes is None
    assert observation.away.substitutes is None
    assert observation.home.coach is None
    assert observation.away.coach is None
    assert observation.additional_notes == ()
    assert "substitutes_section_not_observed" in observation.validation.warnings
    assert "coaches_section_not_observed" in observation.validation.warnings
    assert "ephemerides_not_observed" in observation.validation.warnings


def test_incomplete_or_corrupt_dom_is_rejected():
    with pytest.raises(MatchDetailParserError, match="hero.hero-partit"):
        _parse(b"<html><head><title>not a match</title></head><body></body></html>")


def test_malformed_score_is_rejected_instead_of_fabricating_zero():
    html = match_html().replace(
        b'<span class="col-auto resultat-partit">1</span>',
        b'<span class="col-auto resultat-partit">?</span>',
        1,
    )

    with pytest.raises(MatchDetailParserError, match="Marcador no numérico"):
        _parse(html)


def test_artifact_manifest_integrity_provenance_and_idempotence_are_read_only(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline semantic parsing must not open a network connection")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    artifact = saved_artifact(tmp_path)
    paths = [artifact / "raw/source.html", artifact / "discovery.json", artifact / "metadata.json", artifact / "manifest.json"]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}

    first = parse_saved_artifact(artifact, expected_match=expected_match())
    second = parse_saved_artifact(artifact, expected_match=expected_match())

    assert first == second
    assert first.validation.semantic_valid is True
    assert first.source.discovery_id == artifact.name
    assert first.source.source_capture_id == expected_match()["source_capture_id"]
    assert first.source.source_generation_id == expected_match()["source_generation_id"]
    assert first.source.promotion_eligible is False
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def test_corrupted_artifact_html_is_rejected_before_parsing(tmp_path):
    artifact = saved_artifact(tmp_path)
    with (artifact / "raw/source.html").open("ab") as stream:
        stream.write(b"<!-- changed -->")

    with pytest.raises(MatchDetailParserError, match="Hash/tamaño no coincide para raw/source.html"):
        parse_saved_artifact(artifact, expected_match=expected_match())


def test_artifact_context_mismatch_is_rejected(tmp_path):
    artifact = saved_artifact(tmp_path)
    expected = expected_match()
    expected["group"] = "I"

    with pytest.raises(MatchDetailParserError, match="Metadata/catalog mismatch: group"):
        parse_saved_artifact(artifact, expected_match=expected)
