from __future__ import annotations

import hashlib
import socket
import urllib.request

import pytest

from football_data_hub.providers.bdfutbol.match_details.semantic_parser import (
    MatchDetailParserError,
    parse_match_detail_html,
    parse_saved_artifact,
)
from tests.match_detail_semantic_fixtures import (
    DISCOVERY_ID,
    INVENTORY_ID,
    expected_match,
    match_html,
    metadata_for,
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

    goals = [event for event in observation.events if event.event_type in {"goal", "penalty_goal"}]
    assert len(goals) == 2  # The header summary and lineup icons are reconciled, not duplicated.
    assert {(event.side, event.event_type, event.minute_literal) for event in goals} == {
        ("home", "penalty_goal", "90+1"),
        ("away", "goal", "6"),
    }
    assert all(event.minute_base is not None for event in goals)
    assert all(item.source_html_sha256 == observation.source.source_html_sha256 for item in observation.evidence)
    assert all(item.parser_version == observation.source.parser_version for item in observation.evidence)


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
