"""Offline tests for player identity and club-evidence projections."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from itertools import permutations

import pytest

from football_data_hub_api.player_identity import (
    derive_last_observed_movement,
    derive_player_club_reference,
    project_player_identity,
)


def _profile(**overrides: object) -> dict:
    profile = {
        "display_name_raw": "Manu Pedreño",
        "full_name_raw": "Antonio Manuel Moñino Pedreño",
        "birth_date_iso": "2000-10-09",
        "age_as_displayed_years": 26,
        "birth_place_raw": "Los Garres ( Murcia )",
        "country_of_birth_raw": "España",
        "nationality_raw": None,
        "position_raw": "Central",
        "height_cm": 190,
        "height_raw": "190 cm",
        "weight_raw": "81 kg",
    }
    profile.update(overrides)
    return profile


def _compact(profile: dict | None = None) -> dict:
    return {
        "views": {"profile": {"profile": profile or _profile()}},
        "view_sources": {"profile": {
            "requested_url": "https://www.bdfutbol.com/es/j/j23751.html",
            "captured_at_utc": "2026-10-14T13:39:25.641724Z",
            "html_sha256": "a" * 64,
        }},
    }


def _inventory(**overrides: object) -> dict:
    record = {
        "player_id": 23751,
        "display_name": "Manu Pedreño",
        "full_name": "Antonio Manuel Moñino Pedreño",
        "birth_date": "2000-10-09",
        "age_years": 26,
        "birthplace": "Los Garres",
        "birthplace_province": "Murcia",
        "nationality": None,
        "position_name": None,
    }
    record.update(overrides)
    return record


def _membership(team_id: int, name: str, group: str, captured: str) -> dict:
    return {
        "season": "2026-27",
        "team_id": team_id,
        "team_name": name,
        "group": group,
        "source_ref": {"captured_at_utc": captured},
    }


def _transfer(
    direction: str,
    team_id: int,
    team_name: str,
    group: str,
    other_id: int,
    other_name: str,
    capture_id: str,
    captured: str,
) -> dict:
    return {
        "record": {
            "season": "2026-27",
            "direction": direction,
            "team_id": team_id,
            "team_name": team_name,
            "group": group,
            "other_team_id": other_id,
            "other_team_name": other_name,
            "transfer_date": None,
        },
        "source_ref": {
            "capture_id": capture_id,
            "captured_at_utc": captured,
            "group": group,
            "team_id": team_id,
            "team_name": team_name,
            "sha256": "b" * 64,
            "record_index": 4,
        },
    }


def test_individual_profile_fills_inventory_gaps_without_becoming_nationality() -> None:
    inventory = _inventory()
    original = deepcopy(inventory)

    identity = project_player_identity(inventory, _compact(), inventory_sha256="c" * 64)

    assert identity.display_name == "Manu Pedreño"
    assert identity.full_name == "Antonio Manuel Moñino Pedreño"
    assert identity.birth_date == date(2000, 10, 9)
    assert identity.birth_place == "Los Garres"
    assert identity.birth_place_raw == "Los Garres ( Murcia )"
    assert identity.birthplace_province == "Murcia"
    assert identity.country_of_birth == "España"
    assert identity.nationality is None
    assert identity.position_name == "Central"
    assert identity.height_cm == 190
    assert identity.weight_kg == 81
    assert identity.height_raw == "190 cm"
    assert identity.weight_raw == "81 kg"
    assert identity.field_sources["position_name"] == "individual_profile"
    assert identity.field_sources["birth_place_raw"] == "individual_profile"
    assert identity.inventory_sha256 == "c" * 64
    assert identity.individual_profile_sha256 == "a" * 64
    assert inventory == original


def test_individual_profile_value_wins_and_conflict_is_preserved() -> None:
    identity = project_player_identity(
        _inventory(display_name="Nombre del inventario"),
        _compact(_profile(display_name_raw="Nombre de ficha")),
        inventory_sha256="c" * 64,
    )

    assert identity.display_name == "Nombre de ficha"
    assert identity.field_sources["display_name"] == "individual_profile"
    assert [(item.field, item.inventory_value, item.individual_profile_value) for item in identity.conflicts] == [
        ("display_name", "Nombre del inventario", "Nombre de ficha")
    ]
    assert identity.conflicts[0].selected_source == "individual_profile"


def test_profile_empty_field_falls_back_to_inventory() -> None:
    identity = project_player_identity(
        _inventory(display_name="Nombre de inventario", position_name="Centrocampista"),
        _compact(_profile(position_raw="")),
        inventory_sha256="c" * 64,
    )

    assert identity.position_name == "Centrocampista"
    assert identity.field_sources["position_name"] == "inventory"


@pytest.mark.parametrize(
    ("height_raw", "weight_raw"),
    [("1.90 m", "81"), ("190", "180 lb"), ("190 cm approx", "81 kg (source)")],
)
def test_ambiguous_units_are_not_converted(height_raw: str, weight_raw: str) -> None:
    identity = project_player_identity(
        _inventory(),
        _compact(_profile(height_cm=None, height_raw=height_raw, weight_raw=weight_raw)),
        inventory_sha256="c" * 64,
    )

    assert identity.height_cm is None
    assert identity.weight_kg is None
    assert identity.height_raw == height_raw
    assert identity.weight_raw == weight_raw


def test_non_finite_numeric_measurement_falls_back_to_exact_source_text() -> None:
    identity = project_player_identity(
        _inventory(),
        _compact(_profile(height_cm=float("nan"), height_raw="190 cm")),
        inventory_sha256="c" * 64,
    )

    assert identity.height_cm == 190


def test_missing_compact_uses_inventory_and_keeps_unavailable_fields_null() -> None:
    identity = project_player_identity(
        _inventory(display_name="Inventario", position_name="Central"),
        None,
        inventory_sha256="c" * 64,
    )

    assert identity.display_name == "Inventario"
    assert identity.position_name == "Central"
    assert identity.height_cm is None
    assert identity.weight_kg is None
    assert identity.country_of_birth is None
    assert identity.nationality is None
    assert identity.field_sources["height_cm"] == "unavailable"


def test_only_unique_recent_membership_is_observed_as_club_reference() -> None:
    memberships = [
        _membership(178, "UD Logroñés", "I", "2026-10-12T16:03:01+00:00"),
        _membership(414, "UD Ibiza", "II", "2026-10-13T16:48:36+00:00"),
    ]

    result = derive_player_club_reference(memberships, [])

    assert result.status == "observed"
    assert (result.team_id, result.team_name, result.group) == (414, "UD Ibiza", "II")


def test_same_capture_outgoing_reference_prevents_current_club_claim() -> None:
    timestamp = "2026-10-13T16:48:36.725160+00:00"
    membership = [_membership(414, "UD Ibiza", "II", timestamp)]
    outgoing = [_transfer(
        "outgoing", 414, "UD Ibiza", "II", 178, "UD Logroñés",
        "ibiza-capture", timestamp,
    )]

    result = derive_player_club_reference(membership, outgoing)

    assert result.status == "not_confirmed"
    assert result.team_id is None
    assert result.reason == "later_or_simultaneous_outgoing_movement"


def test_transfer_only_player_has_no_invented_club_reference() -> None:
    transfer = _transfer(
        "incoming", 178, "UD Logroñés", "I", 414, "UD Ibiza",
        "logrones-capture", "2026-10-12T16:03:01+00:00",
    )

    result = derive_player_club_reference([], [transfer])

    assert result.status == "not_confirmed"
    assert result.team_id is None
    assert result.reason == "no_membership_observed"


def test_tied_latest_memberships_remain_unconfirmed() -> None:
    timestamp = "2026-10-13T16:48:36+00:00"
    result = derive_player_club_reference([
        _membership(178, "UD Logroñés", "I", timestamp),
        _membership(414, "UD Ibiza", "II", timestamp),
    ], [])

    assert result.status == "not_confirmed"
    assert result.reason == "multiple_latest_memberships"


def test_manu_transfer_pair_is_resolved_by_team_ids_not_array_order() -> None:
    timestamp_a = "2026-10-12T16:03:01.180645+00:00"
    timestamp_b = "2026-10-13T16:48:36.725160+00:00"
    incoming = _transfer(
        "incoming", 178, "UD Logroñés", "I", 414, "UD Ibiza", "logrones", timestamp_a
    )
    outgoing = _transfer(
        "outgoing", 414, "UD Ibiza", "II", 178, "UD Logroñés", "ibiza", timestamp_b
    )
    associations = [
        {"team_id": 178, "team_name": "UD Logroñés", "group": "I"},
        {"team_id": 414, "team_name": "UD Ibiza", "group": "II"},
    ]

    for ordered in permutations([incoming, outgoing]):
        movement, resolution = derive_last_observed_movement(list(ordered), associations)
        assert resolution == "identified"
        assert movement is not None
        assert (movement.from_team_id, movement.from_team_name, movement.from_group) == (414, "UD Ibiza", "II")
        assert (movement.to_team_id, movement.to_team_name, movement.to_group) == (178, "UD Logroñés", "I")
        assert movement.transfer_date is None
        assert movement.observed_at.isoformat() == timestamp_b
        assert movement.evidence_count == 2
        assert [item.capture_id for item in movement.evidence] == ["ibiza", "logrones"]


def test_conflicting_fallback_team_names_make_movement_ambiguous() -> None:
    incoming = _transfer(
        "incoming", 178, "UD Logroñés", "I", 414, "UD Ibiza", "one",
        "2026-10-12T16:03:01+00:00",
    )
    outgoing = _transfer(
        "outgoing", 414, "Ibiza distinto", "II", 178, "Logroñés distinto", "two",
        "2026-10-13T16:48:36+00:00",
    )

    movement, resolution = derive_last_observed_movement([incoming, outgoing], [])

    assert movement is None
    assert resolution == "ambiguous"


def test_unordered_multiple_movements_are_ambiguous_not_array_ordered() -> None:
    first = _transfer("outgoing", 414, "UD Ibiza", "II", 178, "UD Logroñés", "one", "")
    second = _transfer("outgoing", 178, "UD Logroñés", "I", 49, "Real Jaén", "two", "")
    for ordered in permutations([first, second]):
        movement, resolution = derive_last_observed_movement(list(ordered), [])
        assert movement is None
        assert resolution == "ambiguous"


def test_malformed_transfer_rows_do_not_crash_club_projection() -> None:
    result = derive_player_club_reference(
        [_membership(49, "Real Jaén", "II", "2026-10-12T12:00:00+00:00")],
        [None, "invalid", {}, {"record": None}],  # type: ignore[list-item]
    )

    assert result.status == "observed"
    assert result.team_id == 49
