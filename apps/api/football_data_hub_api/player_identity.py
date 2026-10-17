"""Conservative identity and club-evidence projections for player details."""

from __future__ import annotations

from datetime import date, datetime
import math
import re
from typing import Any

from football_data_hub_api.schemas import (
    PlayerClubMovementResponse,
    PlayerClubReferenceResponse,
    PlayerIdentityConflictResponse,
    PlayerIdentityResponse,
    PlayerTransferEvidenceResponse,
)

_PROFILE_FIELDS = {
    "display_name": "display_name_raw",
    "full_name": "full_name_raw",
    "birth_date": "birth_date_iso",
    "birth_place": "birth_place_raw",
    "country_of_birth": "country_of_birth_raw",
    "nationality": "nationality_raw",
    "position_name": "position_raw",
}
_UNIT_VALUE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(cm|kg)\s*$", re.IGNORECASE)


def project_player_identity(
    inventory_player: dict[str, Any],
    compact_document: dict[str, Any] | None,
    *,
    inventory_sha256: str,
) -> PlayerIdentityResponse:
    views = compact_document.get("views", {}) if isinstance(compact_document, dict) else {}
    profile_view = views.get("profile", {}) if isinstance(views, dict) else {}
    profile = profile_view.get("profile", {}) if isinstance(profile_view, dict) else {}
    profile = profile if isinstance(profile, dict) else {}
    sources = compact_document.get("view_sources", {}) if isinstance(compact_document, dict) else {}
    profile_source = sources.get("profile", {}) if isinstance(sources, dict) else {}
    profile_source = profile_source if isinstance(profile_source, dict) else {}

    fields: dict[str, Any] = {}
    field_sources: dict[str, str] = {}
    conflicts: list[PlayerIdentityConflictResponse] = []
    inventory_values = {
        "display_name": inventory_player.get("display_name"),
        "full_name": inventory_player.get("full_name"),
        "birth_date": inventory_player.get("birth_date"),
        "age_years": inventory_player.get("age_years"),
        "birth_place": inventory_player.get("birthplace"),
        "birthplace_province": inventory_player.get("birthplace_province"),
        "country_of_birth": inventory_player.get("country_of_birth"),
        "nationality": inventory_player.get("nationality"),
        "position_name": inventory_player.get("position_name"),
    }
    raw_birth_place = profile.get("birth_place_raw")
    profile_birth_place, profile_birthplace_province = _split_birth_place(raw_birth_place)
    individual_values = {
        field: profile.get(profile_field)
        for field, profile_field in _PROFILE_FIELDS.items()
    }
    individual_values["birth_place"] = profile_birth_place or individual_values.get("birth_place")
    individual_values["birthplace_province"] = profile_birthplace_province
    individual_values["age_years"] = profile.get("age_as_displayed_years")

    for field, inventory_value in inventory_values.items():
        individual_value = individual_values.get(field)
        value, source = _prefer_inventory_value(
            field, inventory_value, individual_value
        )
        fields[field] = value
        field_sources[field] = source
        if _present(inventory_value) and _present(individual_value) and not _equivalent(
            field, inventory_value, individual_value, inventory_values
        ):
            conflicts.append(PlayerIdentityConflictResponse(
                field=field,
                inventory_value=_as_display_value(inventory_value),
                individual_profile_value=_as_display_value(individual_value),
                selected_source="inventory",
            ))
    field_sources["birth_place_raw"] = (
        "individual_profile" if _present(raw_birth_place) else "unavailable"
    )

    height_raw = profile.get("height_raw")
    height_cm = profile.get("height_cm")
    if not _positive_finite_number(height_cm):
        height_cm = _parse_exact_unit(height_raw, "cm")
    weight_raw = profile.get("weight_raw")
    weight_kg = profile.get("weight_kg")
    if not _positive_finite_number(weight_kg):
        weight_kg = _parse_exact_unit(weight_raw, "kg")

    fields["height_cm"] = height_cm
    fields["height_raw"] = height_raw if isinstance(height_raw, str) else None
    field_sources["height_cm"] = "individual_profile" if height_cm is not None else "unavailable"
    field_sources["height_raw"] = "individual_profile" if _present(height_raw) else "unavailable"
    fields["weight_kg"] = weight_kg
    fields["weight_raw"] = weight_raw if isinstance(weight_raw, str) else None
    field_sources["weight_kg"] = "individual_profile" if weight_kg is not None else "unavailable"
    field_sources["weight_raw"] = "individual_profile" if _present(weight_raw) else "unavailable"

    # The inventory stores the locality and province separately, while the
    # individual profile keeps the source wording intact in birth_place_raw.
    # Do not turn country of birth into nationality.
    return PlayerIdentityResponse(
        display_name=fields["display_name"],
        full_name=fields["full_name"],
        birth_date=fields["birth_date"],
        age_years=fields["age_years"],
        birth_place=fields["birth_place"],
        birth_place_raw=raw_birth_place if isinstance(raw_birth_place, str) else None,
        birthplace_province=fields["birthplace_province"],
        country_of_birth=fields["country_of_birth"],
        nationality=fields["nationality"],
        position_name=fields["position_name"],
        height_cm=height_cm,
        height_raw=fields["height_raw"],
        weight_kg=weight_kg,
        weight_raw=fields["weight_raw"],
        field_sources=field_sources,
        inventory_sha256=inventory_sha256,
        individual_profile_source_url=profile_source.get("requested_url"),
        individual_profile_captured_at=_parse_datetime(profile_source.get("captured_at_utc")),
        individual_profile_sha256=profile_source.get("html_sha256"),
        conflicts=conflicts,
    )


def derive_player_club_reference(
    memberships: list[dict[str, Any]],
    transfers: list[dict[str, Any]],
) -> PlayerClubReferenceResponse:
    observations = [
        membership
        for membership in memberships
        if _valid_membership(membership)
    ]
    if not observations:
        return PlayerClubReferenceResponse(
            status="not_confirmed",
            team_id=None,
            team_name=None,
            group=None,
            observed_at=None,
            reason="no_membership_observed",
        )

    dated = [
        (parsed, membership)
        for membership in observations
        if (parsed := _membership_time(membership)) is not None
    ]
    if not dated:
        unique = {(item["team_id"], item["group"]) for item in observations}
        if len(unique) != 1 or any(_transfer_leaves_any(transfers, unique)):
            return _not_confirmed("membership_order_unavailable")
        membership = observations[0]
        return _observed_membership(membership, None)

    latest_time = max(item[0] for item in dated)
    latest = [membership for observed_at, membership in dated if observed_at == latest_time]
    latest_keys = {(item["team_id"], item["group"]) for item in latest}
    if len(latest_keys) != 1:
        return _not_confirmed("multiple_latest_memberships")
    membership = latest[0]
    if any(
        _membership_time(item) is None
        and (item["team_id"], item["group"]) not in latest_keys
        for item in observations
    ):
        return _not_confirmed("membership_order_unavailable")
    if _transfer_leaves_team_at_or_after(transfers, membership["team_id"], latest_time):
        return _not_confirmed("later_or_simultaneous_outgoing_movement")
    return _observed_membership(membership, latest_time)


def derive_last_observed_movement(
    transfers: list[dict[str, Any]],
    team_associations: list[dict[str, Any]],
) -> tuple[PlayerClubMovementResponse | None, str]:
    association_by_id: dict[int, list[dict[str, Any]]] = {}
    for association in team_associations:
        if not isinstance(association, dict):
            continue
        if type(association.get("team_id")) is int:
            association_by_id.setdefault(association["team_id"], []).append(association)

    candidates: dict[tuple[int, int], dict[str, Any]] = {}
    for item in transfers:
        record = item.get("record") if isinstance(item, dict) else None
        source_ref = item.get("source_ref") if isinstance(item, dict) else None
        if not isinstance(record, dict) or record.get("season") != "2026-27":
            continue
        source_id = record.get("other_team_id") if record.get("direction") == "incoming" else record.get("team_id")
        destination_id = record.get("team_id") if record.get("direction") == "incoming" else record.get("other_team_id")
        if (
            record.get("direction") not in {"incoming", "outgoing"}
            or type(source_id) is not int or source_id <= 0
            or type(destination_id) is not int or destination_id <= 0
            or source_id == destination_id
        ):
            continue
        transfer_date = _parse_date(record.get("transfer_date"))
        observed_at = _parse_datetime(
            source_ref.get("captured_at_utc") if isinstance(source_ref, dict) else None
        )
        key = (source_id, destination_id)
        candidate = candidates.setdefault(key, {
            "source_id": source_id,
            "destination_id": destination_id,
            "transfer_dates": set(),
            "evidence": [],
            "latest_observed_at": None,
            "source_names": set(),
            "destination_names": set(),
            "source_groups": set(),
            "destination_groups": set(),
        })
        if transfer_date is not None:
            candidate["transfer_dates"].add(transfer_date)
        if observed_at and (candidate["latest_observed_at"] is None or observed_at > candidate["latest_observed_at"]):
            candidate["latest_observed_at"] = observed_at
        candidate["evidence"].append(_transfer_evidence(record, source_ref))
        if record.get("direction") == "incoming":
            _add_if_nonempty(candidate["source_names"], record.get("other_team_name"))
            _add_if_nonempty(candidate["destination_names"], _team_name(record, source_ref))
            _add_group(candidate["destination_groups"], record.get("group"))
        else:
            _add_if_nonempty(candidate["source_names"], _team_name(record, source_ref))
            _add_if_nonempty(candidate["destination_names"], record.get("other_team_name"))
            _add_group(candidate["source_groups"], record.get("group"))

    if not candidates:
        return None, "none"

    if any(len(candidate["transfer_dates"]) > 1 for candidate in candidates.values()):
        return None, "ambiguous"
    for candidate in candidates.values():
        candidate["transfer_date"] = next(iter(candidate["transfer_dates"]), None)

    if len(candidates) == 1:
        candidate = next(iter(candidates.values()))
    else:
        all_have_dates = all(item["transfer_date"] is not None for item in candidates.values())
        all_have_observation_times = all(item["latest_observed_at"] is not None for item in candidates.values())
        if all_have_dates:
            latest_date = max(item["transfer_date"] for item in candidates.values())
            latest = [item for item in candidates.values() if item["transfer_date"] == latest_date]
        elif all_have_observation_times:
            latest_time = max(item["latest_observed_at"] for item in candidates.values())
            latest = [item for item in candidates.values() if item["latest_observed_at"] == latest_time]
        else:
            return None, "ambiguous"
        if len(latest) != 1:
            return None, "ambiguous"
        candidate = latest[0]

    source_team = _association_for_team(association_by_id, candidate["source_id"])
    destination_team = _association_for_team(association_by_id, candidate["destination_id"])
    source_group = source_team.get("group") if source_team else _unique_value(candidate["source_groups"])
    destination_group = destination_team.get("group") if destination_team else _unique_value(candidate["destination_groups"])
    source_name = source_team.get("team_name") if source_team else _unique_value(candidate["source_names"])
    destination_name = destination_team.get("team_name") if destination_team else _unique_value(candidate["destination_names"])
    if not isinstance(source_name, str) or not isinstance(destination_name, str):
        return None, "ambiguous"
    if (source_team is None and len(candidate["source_names"]) > 1) or (
        destination_team is None and len(candidate["destination_names"]) > 1
    ) or (source_team is None and len(candidate["source_groups"]) > 1) or (
        destination_team is None and len(candidate["destination_groups"]) > 1
    ):
        return None, "ambiguous"

    evidence = []
    seen_evidence: set[tuple[Any, ...]] = set()
    for ref in sorted(candidate["evidence"], key=lambda item: (
        item.capture_id or "", item.source_record_index if item.source_record_index is not None else -1,
        item.direction, item.team_id,
    )):
        key = (ref.capture_id, ref.source_record_index, ref.direction, ref.team_id)
        if key not in seen_evidence:
            seen_evidence.add(key)
            evidence.append(ref)
    return PlayerClubMovementResponse(
        from_team_id=candidate["source_id"],
        from_team_name=source_name,
        from_group=source_group,
        to_team_id=candidate["destination_id"],
        to_team_name=destination_name,
        to_group=destination_group,
        season="2026-27",
        transfer_date=candidate["transfer_date"],
        observed_at=candidate["latest_observed_at"],
        evidence_count=len(evidence),
        evidence=evidence,
    ), "identified"


def _transfer_evidence(record: dict[str, Any], source_ref: Any) -> PlayerTransferEvidenceResponse:
    source_ref = source_ref if isinstance(source_ref, dict) else {}
    return PlayerTransferEvidenceResponse(
        capture_id=source_ref.get("capture_id"),
        captured_at=_parse_datetime(source_ref.get("captured_at_utc")),
        source_sha256=source_ref.get("sha256"),
        source_record_index=source_ref.get("record_index") if type(source_ref.get("record_index")) is int else None,
        team_id=record["team_id"],
        group=record.get("group") if record.get("group") in {"I", "II"} else None,
        direction=record["direction"],
    )


def _valid_membership(item: dict[str, Any]) -> bool:
    return (
        item.get("season") == "2026-27"
        and type(item.get("team_id")) is int
        and item["team_id"] > 0
        and item.get("group") in {"I", "II"}
        and isinstance(item.get("team_name"), str)
        and bool(item["team_name"].strip())
    )


def _membership_time(item: dict[str, Any]) -> datetime | None:
    source_ref = item.get("source_ref")
    source_ref = source_ref if isinstance(source_ref, dict) else {}
    return _parse_datetime(source_ref.get("captured_at_utc") or item.get("captured_at_utc"))


def _transfer_leaves_any(transfers: list[dict[str, Any]], teams: set[tuple[int, str]]) -> bool:
    for item in transfers:
        record = item.get("record") if isinstance(item, dict) else None
        if not isinstance(record, dict) or record.get("season") != "2026-27":
            continue
        if record.get("direction") == "outgoing" and (
            record.get("team_id"), record.get("group")
        ) in teams:
            return True
        if record.get("direction") == "incoming" and (
            record.get("other_team_id"), _team_group_from_record(record, teams)
        ) in teams:
            return True
    return False


def _transfer_leaves_team_at_or_after(
    transfers: list[dict[str, Any]], team_id: int, membership_time: datetime
) -> bool:
    for item in transfers:
        record = item.get("record") if isinstance(item, dict) else None
        if not isinstance(record, dict) or record.get("season") != "2026-27":
            continue
        is_outgoing = record.get("direction") == "outgoing" and record.get("team_id") == team_id
        is_incoming_from_team = record.get("direction") == "incoming" and record.get("other_team_id") == team_id
        if not (is_outgoing or is_incoming_from_team):
            continue
        source_ref = item.get("source_ref")
        source_ref = source_ref if isinstance(source_ref, dict) else {}
        observed_at = _parse_datetime(source_ref.get("captured_at_utc"))
        transfer_date = _parse_date(record.get("transfer_date"))
        if observed_at is None or observed_at >= membership_time:
            return True
        if transfer_date is not None and transfer_date >= membership_time.date():
            return True
    return False


def _observed_membership(
    membership: dict[str, Any], observed_at: datetime | None
) -> PlayerClubReferenceResponse:
    return PlayerClubReferenceResponse(
        status="observed",
        team_id=membership["team_id"],
        team_name=membership["team_name"],
        group=membership["group"],
        observed_at=observed_at,
        reason="latest_unique_membership_observation",
    )


def _not_confirmed(reason: str) -> PlayerClubReferenceResponse:
    return PlayerClubReferenceResponse(
        status="not_confirmed",
        team_id=None,
        team_name=None,
        group=None,
        observed_at=None,
        reason=reason,
    )


def _association_for_team(
    associations: dict[int, list[dict[str, Any]]], team_id: int
) -> dict[str, Any] | None:
    values = associations.get(team_id, [])
    return values[0] if len(values) == 1 else None


def _team_name(record: dict[str, Any], source_ref: Any) -> str | None:
    if isinstance(source_ref, dict) and isinstance(source_ref.get("team_name"), str):
        return source_ref["team_name"]
    return record.get("team_name") if isinstance(record.get("team_name"), str) else None


def _team_group_from_record(record: dict[str, Any], teams: set[tuple[int, str]]) -> str | None:
    team_id = record.get("other_team_id")
    groups = {group for observed_team_id, group in teams if observed_team_id == team_id}
    return next(iter(groups)) if len(groups) == 1 else None


def _split_birth_place(value: Any) -> tuple[str | None, str | None]:
    if not isinstance(value, str) or not value.strip():
        return None, None
    match = re.fullmatch(r"\s*(.*?)\s*\(\s*(.*?)\s*\)\s*", value)
    if match and match.group(1).strip() and match.group(2).strip():
        return match.group(1).strip(), match.group(2).strip()
    return value.strip(), None


def _positive_finite_number(value: Any) -> bool:
    if type(value) not in (int, float) or value <= 0:
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _add_if_nonempty(values: set[str], value: Any) -> None:
    if isinstance(value, str) and value.strip():
        values.add(value.strip())


def _add_group(values: set[str], value: Any) -> None:
    if value in {"I", "II"}:
        values.add(value)


def _unique_value(values: set[Any]) -> Any:
    return next(iter(values)) if len(values) == 1 else None


def _prefer_inventory_value(
    field: str, inventory_value: Any, individual_value: Any
) -> tuple[Any, str]:
    if _present(inventory_value):
        return _normalize_inventory_value(field, inventory_value), "inventory"
    if _present(individual_value):
        return _normalize_individual_value(field, individual_value), "individual_profile"
    return None, "unavailable"


def _normalize_inventory_value(field: str, value: Any) -> Any:
    if field == "birth_date":
        return _parse_date(value)
    return value


def _normalize_individual_value(field: str, value: Any) -> Any:
    if field == "birth_date":
        return _parse_date(value)
    if field in {"display_name", "full_name", "birth_place", "country_of_birth", "nationality", "position_name"}:
        return value.strip() if isinstance(value, str) else value
    return value


def _equivalent(
    field: str,
    inventory_value: Any,
    individual_value: Any,
    inventory_values: dict[str, Any],
) -> bool:
    if field == "birth_place" and isinstance(individual_value, str):
        match = re.fullmatch(r"\s*(.*?)\s*\(\s*(.*?)\s*\)\s*", individual_value)
        if match:
            return (
                _normalize_text(inventory_value) == _normalize_text(match.group(1))
                and _normalize_text(inventory_values.get("birthplace_province"))
                == _normalize_text(match.group(2))
            )
    left = _normalize_inventory_value(field, inventory_value)
    right = _normalize_individual_value(field, individual_value)
    if isinstance(left, str) and isinstance(right, str):
        return _normalize_text(left) == _normalize_text(right)
    return left == right


def _parse_exact_unit(value: Any, unit: str) -> int | float | None:
    if not isinstance(value, str):
        return None
    match = _UNIT_VALUE.fullmatch(value)
    if not match or match.group(2).casefold() != unit.casefold():
        return None
    number = float(match.group(1).replace(",", "."))
    if number <= 0:
        return None
    return int(number) if number.is_integer() else number


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _present(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def _as_display_value(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _normalize_text(value: Any) -> str:
    return " ".join(value.casefold().split()) if isinstance(value, str) else ""
