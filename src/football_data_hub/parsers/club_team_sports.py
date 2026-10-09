"""Consolidated sports records derived from captured club/team pages."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

from football_data_hub.parsers.match_status import assess_match_status, normalized_match_state

_INTEGER = re.compile(r"^\d+$")
_SCORE = re.compile(r"^(\d+)\s+(\d+)$")
_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def _table(page: dict[str, Any], table_id: str) -> dict[str, Any] | None:
    return next((item for item in page.get("tables", []) if item.get("table_id") == table_id), None)


def _headers(table: dict[str, Any] | None) -> list[str]:
    if table is None:
        return []
    headers = table.get("header_cells")
    if isinstance(headers, list):
        return [str(value or "") for value in headers]
    for row in table.get("rows", []):
        if row.get("kind") == "header":
            return [str(cell.get("text") or "") for cell in row.get("cells", [])]
    return []


def _row_values(row: dict[str, Any], width: int) -> list[str | None]:
    values: list[str | None] = [None] * width
    for fallback, cell in enumerate(row.get("cells", [])):
        try:
            start = int(cell.get("column_index", fallback))
            span = max(1, int(cell.get("column_span", cell.get("colspan") or 1)))
        except (TypeError, ValueError):
            start, span = fallback, 1
        if 0 <= start < width:
            values[start] = str(cell.get("text") or "")
            for index in range(start + 1, min(start + span, width)):
                values[index] = None
    return values


def _integer(raw: str | None) -> int | None:
    value = (raw or "").strip()
    return int(value) if _INTEGER.fullmatch(value) else None


def _normalized_name(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    return "".join(character for character in text.casefold() if character.isalnum())


def _timestamp(page: dict[str, Any]) -> str | None:
    source = page.get("source", {})
    value = source.get("captured_at_utc")
    return str(value) if value else None


def _source(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": page.get("url"),
        "snapshot_directory": page.get("source", {}).get("snapshot_directory"),
        "snapshot_sha256": page.get("source", {}).get("rendered_html_sha256"),
        "captured_at_utc": _timestamp(page),
    }


def _relationship_ids(page: dict[str, Any], table_id: str, entity_type: str) -> dict[int, str]:
    result: dict[int, str] = {}
    for relation in page.get("relationships", []):
        if relation.get("entity_type") != entity_type:
            continue
        occurrences = relation.get("occurrences") or [relation]
        for occurrence in occurrences:
            if occurrence.get("source_table_id") == table_id and occurrence.get("source_row_index") is not None:
                result[int(occurrence["source_row_index"])] = str(relation.get("entity_id"))
    return result


def _field_index(headers: list[str], name: str) -> int | None:
    target = name.casefold()
    return next((index for index, header in enumerate(headers) if header.casefold() == target), None)


def _value(headers: list[str], values: list[str | None], name: str) -> str | None:
    index = _field_index(headers, name)
    return values[index] if index is not None and index < len(values) else None


def _team_maps(pages: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, str]]:
    team_by_club: dict[str, str] = {}
    name_by_team: dict[str, str] = {}
    for page in pages:
        if page.get("entity_type") != "team_season" or page.get("view") != "team_alignment":
            continue
        team_id = str(page.get("entity_id"))
        club_id = page.get("club_id")
        if club_id:
            team_by_club[str(club_id)] = team_id
        for relation in page.get("relationships", []):
            if relation.get("entity_type") == "club" and relation.get("entity_id") == club_id:
                if relation.get("name"):
                    name_by_team[team_id] = str(relation["name"])
                    break
    return team_by_club, name_by_team


def _player_statistics(pages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    by_membership: dict[str, dict[str, Any]] = {}
    for page in pages:
        if page.get("entity_type") != "team_season" or page.get("view") != "team_statistics":
            continue
        table = _table(page, "c3p0")
        headers = _headers(table)
        if not table:
            continue
        player_by_row = {
            int(item["source_row_index"]): item
            for item in page.get("team_data", {}).get("player_statistics", [])
            if item.get("source_row_index") is not None and item.get("player_id")
        }
        source = _source(page)
        for row in table.get("rows", []):
            if row.get("kind") != "data" or "total" in row.get("classes", []):
                continue
            identity = player_by_row.get(int(row.get("row_index", -1)))
            if identity is None:
                continue
            values = _row_values(row, len(headers))
            columns = []
            for index, header in enumerate(headers):
                raw = values[index] if index < len(values) else None
                number = _integer(raw)
                if raw is None or raw.strip() in {"", "-", "—"}:
                    value_status = "MISSING_OR_PLACEHOLDER"
                elif number is not None:
                    value_status = "INTEGER_NORMALIZED"
                else:
                    value_status = "RAW_ONLY"
                columns.append({
                    "column_index": index,
                    "header_original": header,
                    "raw_value": raw,
                    "normalized_integer": number,
                    "value_status": value_status,
                    "interpretation_status": "HEADER_LABEL_ONLY" if header in {"#", "Apodo", "Pos"} else "PENDING_INTERPRETATION",
                })
            by_name = {column["header_original"]: column for column in columns if column["header_original"]}
            appearances = by_name.get("PJ", {}).get("normalized_integer")
            record = {
                "team_season_id": str(page["entity_id"]),
                "player_id": str(identity["player_id"]),
                "player_url": identity.get("player_url"),
                "source_row_index": row.get("row_index"),
                "headers_original": headers,
                "columns": columns,
                "appearances_raw": by_name.get("PJ", {}).get("raw_value"),
                "appearances": appearances,
                "zero_appearances": appearances == 0 if appearances is not None else None,
                **source,
            }
            records.append(record)
            by_membership[f"{page['entity_id']}:{identity['player_id']}"] = record
    return records, by_membership


def _rosters_and_coaches(
    pages: list[dict[str, Any]], stats_by_membership: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rosters: list[dict[str, Any]] = []
    coaches: list[dict[str, Any]] = []
    roster_by_team: dict[str, dict[str, Any]] = {}
    for page in pages:
        if page.get("entity_type") != "team_season" or page.get("view") != "team_roster":
            continue
        team_id = str(page["entity_id"])
        source = _source(page)
        player_rows = []
        for item in page.get("team_data", {}).get("roster_rows", []):
            membership = f"{team_id}:{item['player_id']}"
            stat = stats_by_membership.get(membership)
            roster = {
                "team_season_id": team_id,
                "club_id": page.get("club_id"),
                "player_id": str(item["player_id"]),
                "player_url": item.get("player_url"),
                "name_raw": item.get("name_raw"),
                "shirt_number_raw": item.get("shirt_number_raw"),
                "position_raw": item.get("position_raw"),
                "birth_date_raw": item.get("birth_date_raw"),
                "birth_place_raw": item.get("birth_place_raw"),
                "birth_province_raw": item.get("birth_province_raw"),
                "statistics_present": stat is not None,
                "appearances_raw": stat.get("appearances_raw") if stat else None,
                "appearances": stat.get("appearances") if stat else None,
                "zero_appearances": stat.get("zero_appearances") if stat else None,
                "source_row_index": item.get("source_row_index"),
                **source,
            }
            rosters.append(roster)
            player_rows.append(roster)
        coach_rows = []
        for item in page.get("team_data", {}).get("coach_rows", []):
            values = [cell.get("text") for cell in item.get("raw_cells", [])]
            coach = {
                "team_season_id": team_id,
                "club_id": page.get("club_id"),
                "coach_id": str(item["coach_id"]),
                "coach_url": item.get("coach_url"),
                "name_raw": item.get("name_raw"),
                "birth_date_raw": values[3] if len(values) > 3 else None,
                "birth_place_raw": values[4] if len(values) > 4 else None,
                "birth_province_raw": values[5] if len(values) > 5 else None,
                "source_row_index": item.get("source_row_index"),
                **source,
            }
            coaches.append(coach)
            coach_rows.append(coach)
        roster_by_team[team_id] = {"players": player_rows, "coaches": coach_rows, "source": source}
    return rosters, coaches, roster_by_team


def _movement_references(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for page in pages:
        if page.get("entity_type") != "team_season" or page.get("view") != "team_transfers":
            continue
        for relation in page.get("relationships", []):
            if relation.get("entity_type") not in {"player", "team_season", "club"}:
                continue
            result.append({
                "team_season_id": str(page["entity_id"]),
                "entity_type": relation.get("entity_type"),
                "entity_id": str(relation.get("entity_id")),
                "name_raw": relation.get("name"),
                "url": relation.get("url"),
                "source_table_id": relation.get("source_table_id"),
                "source_row_index": relation.get("source_row_index"),
                "occurrences": relation.get("occurrences", []),
                **_source(page),
            })
    return result


def _aggregate_for_club(page: dict[str, Any]) -> dict[str, int | None] | None:
    table = _table(page, "t1")
    headers = _headers(table)
    if table is None:
        return None
    for row in table.get("rows", []):
        if row.get("kind") != "data":
            continue
        values = _row_values(row, len(headers))
        if _value(headers, values, "Temporada") != "2026-27":
            continue
        return {name: _integer(_value(headers, values, name)) for name in ("PJ", "PG", "PE", "PP", "GF", "GC")}
    return None


def _match_observations(
    pages: list[dict[str, Any]], team_by_club: dict[str, str], name_by_team: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    observations: list[dict[str, Any]] = []
    aggregates: dict[str, dict[str, Any]] = {}
    for page in pages:
        if page.get("entity_type") != "club" or page.get("view") != "club_matches":
            continue
        club_id = str(page["entity_id"])
        table = _table(page, "tpartits")
        headers = _headers(table)
        if table is None:
            continue
        url = str(page.get("url", ""))
        query = parse_qs(urlsplit(url).query)
        if url_has_match_filters(url):
            variant_aggregate = _aggregate_for_club(page)
            if variant_aggregate:
                aggregates[club_id] = {**variant_aggregate, "_source": _source(page)}
        elif query:
            # Outcome-filter pages are redundant evidence; the no-pgep view is primary.
            continue
        else:
            aggregates[club_id] = {**(_aggregate_for_club(page) or {}), "_source": _source(page)}
            continue
        aggregates.setdefault(club_id, {})
        match_ids = _relationship_ids(page, "tpartits", "match")
        source = _source(page)
        for row in table.get("rows", []):
            if row.get("kind") != "data" or row.get("row_role") in {"total", "subtotal"}:
                continue
            values = _row_values(row, len(headers))
            score = _value(headers, values, "")
            score_match = _SCORE.fullmatch((score or "").strip())
            # BDFutbol leaves the score in the unnamed column between Local and Visitante.
            if score_match is None and len(values) > 6:
                score_match = _SCORE.fullmatch((values[6] or "").strip())
                score = values[6]
            date_match = _DATE.fullmatch((_value(headers, values, "Fecha") or "").strip())
            date_iso = None
            if date_match:
                day, month, year = date_match.groups()
                date_iso = f"{year}-{month}-{day}"
            home_name = _value(headers, values, "Local")
            away_name = _value(headers, values, "Visitante")
            match_id = match_ids.get(int(row.get("row_index", -1)))
            gf = _integer(_value(headers, values, "GF"))
            gc = _integer(_value(headers, values, "GC"))
            record = {
                "match_id": match_id,
                "match_url": f"https://www.bdfutbol.com/es/p/p.php?id={match_id}" if match_id else None,
                "group": None,
                "source_club_id": club_id,
                "source_team_season_id": team_by_club.get(club_id),
                "home_team_name_raw": home_name,
                "away_team_name_raw": away_name,
                "date_raw": _value(headers, values, "Fecha"),
                "date": date_iso,
                "season_raw": _value(headers, values, "Temporada"),
                "competition_raw": _value(headers, values, "Competición"),
                "round_raw": _value(headers, values, "Tipo"),
                "score_raw": score,
                "home_goals": int(score_match.group(1)) if score_match else None,
                "away_goals": int(score_match.group(2)) if score_match else None,
                "source_club_goals_for": gf,
                "source_club_goals_against": gc,
                "source_club_yellow_cards": _integer(_value(headers, values, "TA")),
                "source_club_red_cards": _integer(_value(headers, values, "TR")),
                "row_role": row.get("row_role"),
                "source_row_index": row.get("row_index"),
                "result_status": "PLAYED" if score_match else "UNSCORED",
                "source_club_name": name_by_team.get(team_by_club.get(club_id, "")),
                **source,
            }
            assessment = assess_match_status(record)
            record["fixture_status"] = assessment["state"]
            record["match_state"] = assessment["state"]
            record["match_state_issues"] = assessment["issues"]
            record["match_state_evidence"] = assessment["evidence"]
            observations.append(record)
    return observations, aggregates


def url_has_match_filters(url: str) -> bool:
    from urllib.parse import parse_qs, urlsplit

    params = parse_qs(urlsplit(url).query)
    return params.get("cat") == ["1rf"] and params.get("temp") == ["2026-27"] and "pgep" not in params


def _outcome(record: dict[str, Any], team_id: str | None, competition: dict[str, Any] | None) -> str | None:
    if record.get("source_club_goals_for") is None or record.get("source_club_goals_against") is None:
        return None
    if competition and team_id in {competition.get("home_team_season_id"), competition.get("away_team_season_id")}:
        gf = record["source_club_goals_for"]
        ga = record["source_club_goals_against"]
    else:
        home = _normalized_name(record.get("home_team_name_raw"))
        away = _normalized_name(record.get("away_team_name_raw"))
        current = _normalized_name(record.get("source_club_name"))
        if current not in {home, away}:
            return None
        if current == home:
            gf, ga = record.get("home_goals"), record.get("away_goals")
        else:
            gf, ga = record.get("away_goals"), record.get("home_goals")
        if gf is None or ga is None:
            return None
    return "PG" if gf > ga else "PE" if gf == ga else "PP"


def _parsed_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _consolidate_matches(
    observations: list[dict[str, Any]], competition_matches: list[dict[str, Any]],
    aggregates: dict[str, dict[str, Any]], team_by_club: dict[str, str],
    crosscheck_requested: bool, all_variant_clubs: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    comp_by_id = {str(item["match_id"]): item for item in competition_matches if item.get("match_id") is not None}
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incidents: list[dict[str, Any]] = []
    for observation in observations:
        if observation.get("match_id"):
            by_id[str(observation["match_id"])].append(observation)
        else:
            incidents.append({"code": "MATCH_ID_MISSING", "severity": "warning", "record": observation})

    unique_matches = []
    for match_id, items in sorted(by_id.items()):
        played = [item for item in items if normalized_match_state(item) == "played"]
        if not played:
            for item in items:
                if normalized_match_state(item) == "inconsistent":
                    incidents.append({
                        "code": "MATCH_STATUS_INCONSISTENT",
                        "severity": "error",
                        "match_id": match_id,
                        "issues": item.get("match_state_issues", []),
                        "record": item,
                    })
            continue
        selected = max(played, key=lambda item: item.get("captured_at_utc") or "")
        comp = comp_by_id.get(match_id)
        fields = ("date", "home_goals", "away_goals")
        differing_fields = []
        for left_index, left in enumerate(items):
            for right in items[left_index + 1:]:
                for field in fields + ("home_team_name_raw", "away_team_name_raw"):
                    left_value, right_value = left.get(field), right.get(field)
                    if field.endswith("_name_raw"):
                        left_value, right_value = _normalized_name(left_value), _normalized_name(right_value)
                    if left_value != right_value and field not in differing_fields:
                        differing_fields.append(field)
        if differing_fields:
            ordered_times = sorted({item.get("captured_at_utc") for item in items if item.get("captured_at_utc")})
            same_timestamp = len(ordered_times) <= 1
            incidents.append({
                "code": "MATCH_SOURCE_VALUES_DIFFER", 
                "severity": "error" if same_timestamp else "temporal_review",
                "match_id": match_id,
                "fields": differing_fields,
                "captured_at_utc": ordered_times,
                "explanation": "Mismo timestamp: discrepancia de fuente; timestamps distintos: conservar versiones sin atribuirlo al parser." if same_timestamp else "Las capturas tienen timestamps distintos; revisar como cambio temporal de fuente.",
            })
        record = {
            **selected,
            "source_club_ids": sorted({str(item["source_club_id"]) for item in items}),
            "source_team_season_ids": sorted({str(item["source_team_season_id"]) for item in items if item.get("source_team_season_id")}),
            "source_observation_count": len(items),
            "source_observations": [
                {key: item.get(key) for key in (
                    "source_club_id", "source_team_season_id", "date_raw", "date", "home_team_name_raw",
                    "away_team_name_raw", "score_raw", "home_goals", "away_goals", "source_club_goals_for",
                    "source_club_goals_against", "captured_at_utc", "snapshot_sha256", "source_row_index", "url",
                )}
                for item in sorted(items, key=lambda item: (item.get("captured_at_utc") or "", item.get("source_club_id") or ""))
            ],
            "competition_match_present": comp is not None,
            "competition_result_status": comp.get("result_status") if comp else None,
            "competition_group": comp.get("group") if comp else None,
            "competition_comparison": {},
            "differing_fields_between_club_sources": differing_fields,
        }
        if comp:
            record["group"] = comp.get("group")
            record["home_team_season_id"] = comp.get("home_team_season_id")
            record["away_team_season_id"] = comp.get("away_team_season_id")
            compared = {
                "date": (selected.get("date"), comp.get("date")),
                "home_goals": (selected.get("home_goals"), comp.get("home_goals")),
                "away_goals": (selected.get("away_goals"), comp.get("away_goals")),
                "home_team_name": (_normalized_name(selected.get("home_team_name_raw")), _normalized_name(comp.get("home_team_name"))),
                "away_team_name": (_normalized_name(selected.get("away_team_name_raw")), _normalized_name(comp.get("away_team_name"))),
            }
            differences = [field for field, pair in compared.items() if pair[0] != pair[1]]
            record["competition_comparison"] = {
                "match_id": match_id,
                "date_match": compared["date"][0] == compared["date"][1],
                "home_team_match": compared["home_team_name"][0] == compared["home_team_name"][1],
                "away_team_match": compared["away_team_name"][0] == compared["away_team_name"][1],
                "score_match": compared["home_goals"][0] == compared["home_goals"][1] and compared["away_goals"][0] == compared["away_goals"][1],
                "different_fields": differences,
                "competition_snapshot_at": comp.get("_captured_at_utc"),
            }
            if differences:
                comp_time = _parsed_timestamp(comp.get("_captured_at_utc"))
                club_time = _parsed_timestamp(selected.get("captured_at_utc"))
                temporal = bool(comp_time and club_time and comp_time != club_time)
                incidents.append({
                    "code": "MATCH_COMPETITION_CROSSCHECK_DIFFERENCE",
                    "severity": "temporal_review" if temporal else "error",
                    "match_id": match_id,
                    "fields": differences,
                    "club_snapshot_at": selected.get("captured_at_utc"),
                    "competition_snapshot_at": comp.get("_captured_at_utc"),
                    "explanation": "Snapshots tomados en momentos distintos; no clasificar automáticamente como error de parsing." if temporal else "Las fuentes discrepan y tienen timestamps equivalentes o ausentes.",
                })
        elif crosscheck_requested:
            incidents.append({"code": "MATCH_NOT_IN_COMPETITION_EXPORT", "severity": "error", "match_id": match_id})
        unique_matches.append(record)

    played_comp_ids = {
        str(item["match_id"]) for item in competition_matches
        if item.get("match_id") is not None and normalized_match_state(item) == "played"
    }
    observed_ids = set(by_id)
    unobserved_played_ids = sorted(played_comp_ids - observed_ids)
    all_clubs_captured = len(all_variant_clubs) == len(team_by_club)
    if unobserved_played_ids:
        incidents.append({
            "code": "PLAYED_COMPETITION_MATCHES_NOT_OBSERVED",
            "severity": "error" if all_clubs_captured else "warning",
            "count": len(unobserved_played_ids),
            "match_ids": unobserved_played_ids,
            "reason": "Hay clubes sin vista all capturada; las ausencias no se clasifican como fallo del parser." if not all_clubs_captured else "Todos los clubes tienen vista all y estos IDs no aparecen en sus partidos.",
        })

    clubs_in_scope = sorted(team_by_club)
    coverage = []
    outcomes_by_club: dict[str, Counter[str]] = defaultdict(Counter)
    for match in unique_matches:
        comp = comp_by_id.get(str(match["match_id"]))
        for club_id in match["source_club_ids"]:
            team_id = team_by_club.get(club_id)
            own_observation = next((
                item for item in by_id[str(match["match_id"])]
                if str(item.get("source_club_id")) == club_id
            ), match)
            outcome = _outcome(own_observation, team_id, comp)
            if outcome:
                outcomes_by_club[club_id][outcome] += 1
    for club_id in clubs_in_scope:
        team_id = team_by_club[club_id]
        own = [item for item in observations if item.get("source_club_id") == club_id]
        played_count = sum(normalized_match_state(item) == "played" for item in own)
        distinct_ids = {
            str(item["match_id"]) for item in own
            if item.get("match_id") and normalized_match_state(item) == "played"
        }
        expected = aggregates.get(club_id, {})
        outcomes = outcomes_by_club[club_id]
        has_all_variant = club_id in all_variant_clubs
        aggregate_source = expected.get("_source") or {}
        variant_timestamps = sorted({
            str(item["captured_at_utc"]) for item in own if item.get("captured_at_utc")
        })
        expected_competition_ids = {
            str(item["match_id"]) for item in competition_matches
            if normalized_match_state(item) == "played" and item.get("match_id") is not None
            and team_id in {item.get("home_team_season_id"), item.get("away_team_season_id")}
        }
        observed_competition_ids = distinct_ids
        comp_match_sets_equal = (
            observed_competition_ids == expected_competition_ids
            if competition_matches and has_all_variant else None
        )
        source_timestamps_differ = bool(
            aggregate_source.get("captured_at_utc") and variant_timestamps
            and aggregate_source.get("captured_at_utc") not in variant_timestamps
        )
        checks = {
            "played": expected.get("PJ") == len(distinct_ids) if has_all_variant and expected.get("PJ") is not None else None,
            "wins": expected.get("PG") == outcomes["PG"] if has_all_variant and expected.get("PG") is not None else None,
            "draws": expected.get("PE") == outcomes["PE"] if has_all_variant and expected.get("PE") is not None else None,
            "losses": expected.get("PP") == outcomes["PP"] if has_all_variant and expected.get("PP") is not None else None,
            "played_rows_have_unique_ids": len(distinct_ids) == played_count if has_all_variant else None,
        }
        coverage.append({
            "club_id": club_id,
            "team_season_id": team_id,
            "all_match_variant_captured": has_all_variant,
            "matches_played_observed": len(distinct_ids),
            "matches_unscored_observed": sum(normalized_match_state(item) != "played" for item in own),
            "match_rows_observed": len(own),
            "aggregate_expected": {key: expected.get(key) for key in ("PJ", "PG", "PE", "PP", "GF", "GC")},
            "aggregate_snapshot_captured_at_utc": aggregate_source.get("captured_at_utc"),
            "match_variant_snapshot_timestamps_utc": variant_timestamps,
            "outcomes_observed": {"PG": outcomes["PG"], "PE": outcomes["PE"], "PP": outcomes["PP"]},
            "competition_match_ids_expected": sorted(expected_competition_ids) if competition_matches else None,
            "competition_matches_expected": len(expected_competition_ids) if competition_matches else None,
            "competition_match_ids_observed": sorted(observed_competition_ids) if has_all_variant else None,
            "competition_match_sets_equal": comp_match_sets_equal,
            "checks": checks,
            "status": (
                "VALIDATED" if has_all_variant and all(value is True for value in checks.values())
                else "COMPETITION_CROSSCHECKED_SCOPE_DIFFERENCE"
                if has_all_variant and comp_match_sets_equal is True
                else "TEMPORAL_REVIEW"
                if has_all_variant and source_timestamps_differ
                else "INCOMPLETE"
            ),
        })
        if not has_all_variant:
            incidents.append({"code": "CLUB_MATCH_ALL_VARIANT_MISSING", "severity": "warning", "club_id": club_id, "team_season_id": team_id, "aggregate_expected": expected})
        if any(value is False for value in checks.values()):
            if comp_match_sets_equal is True:
                incidents.append({
                    "code": "CLUB_AGGREGATE_SCOPE_DIFFERENCE",
                    "severity": "warning",
                    "club_id": club_id,
                    "team_season_id": team_id,
                    "aggregate_expected": {key: expected.get(key) for key in ("PJ", "PG", "PE", "PP")},
                    "outcomes_observed": {"PJ": len(distinct_ids), "PG": outcomes["PG"], "PE": outcomes["PE"], "PP": outcomes["PP"]},
                    "aggregate_snapshot_captured_at_utc": aggregate_source.get("captured_at_utc"),
                    "match_variant_snapshot_timestamps_utc": variant_timestamps,
                    "competition_match_sets_equal": True,
                    "explanation": "El filtro all concuerda por ID con los partidos jugados del Hito 1B, pero los agregados PJ/PG/PE/PP de t1 tienen mayor alcance o una semántica no confirmada.",
                })
            elif source_timestamps_differ:
                incidents.append({
                    "code": "CLUB_MATCH_AGGREGATE_TEMPORAL_VARIANCE",
                    "severity": "temporal_review",
                    "club_id": club_id,
                    "team_season_id": team_id,
                    "checks": checks,
                    "aggregate_snapshot_captured_at_utc": aggregate_source.get("captured_at_utc"),
                    "match_variant_snapshot_timestamps_utc": variant_timestamps,
                    "explanation": "Las capturas del agregado y la vista filtrada tienen timestamps distintos; revisar como cambio temporal de fuente.",
                })
            else:
                incidents.append({"code": "CLUB_MATCH_AGGREGATE_MISMATCH", "severity": "error", "club_id": club_id, "checks": checks})
        if any(value is None for value in checks.values()):
            incidents.append({"code": "CLUB_AGGREGATE_UNAVAILABLE", "severity": "warning", "club_id": club_id, "checks": checks})
    return unique_matches, coverage, incidents, [
        {"match_id": match_id, "observation_count": len(items), "source_club_ids": sorted({str(item["source_club_id"]) for item in items})}
        for match_id, items in sorted(by_id.items()) if len(items) != 2
    ]


def _tracking_variants(
    pages: list[dict[str, Any]], competition_matches: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    result = []
    player_rows = []
    for page in pages:
        if page.get("entity_type") != "team_season" or page.get("view") != "team_tracking":
            continue
        table = _table(page, "taula-seguiment")
        if table is None:
            continue
        headers = _headers(table)
        occupancy = {header: 0 for header in headers}
        for row in table.get("rows", []):
            if row.get("kind") != "data":
                continue
            values = _row_values(row, len(headers))
            for index, header in enumerate(headers):
                if index and index < len(values) and values[index] not in {None, "", "-", "—"}:
                    occupancy[header] += 1
            cells = row.get("cells", [])
            player_link = next((link for cell in cells for link in cell.get("links", []) if "/j/" in str(link.get("url") or "")), None)
            player_id_match = re.search(r"/j/(j\d+)\.html$", str(player_link.get("url") or "")) if player_link else None
            columns = []
            for index, header in enumerate(headers):
                cell = next((item for item in cells if int(item.get("column_index", -1)) == index), None)
                match_link = next((link for link in (cell or {}).get("links", []) if "/p/p.php" in str(link.get("url") or "")), None)
                match_id_match = re.search(r"[?&]id=(\d+)", str(match_link.get("url") or "")) if match_link else None
                columns.append({
                    "column_index": index,
                    "header_original": header,
                    "raw_value": values[index] if index < len(values) else None,
                    "match_id": match_id_match.group(1) if match_id_match else None,
                    "match_url": match_link.get("url") if match_link else None,
                    "interpretation_status": "PENDING_INTERPRETATION" if header else "UNLABELED_PLAYER_COLUMN",
                })
            player_rows.append({
                "team_season_id": str(page["entity_id"]),
                "player_id": player_id_match.group(1) if player_id_match else None,
                "player_name_raw": values[0] if values else None,
                "source_row_index": row.get("row_index"),
                "columns": columns,
                **_source(page),
            })
        result.append({
            "team_season_id": str(page["entity_id"]),
            "headers_original": headers,
            "column_count": len(headers),
            "data_row_count": sum(row.get("kind") == "data" for row in table.get("rows", [])),
            "nonempty_cells_by_header": occupancy,
            "header_5_present": "5" in headers,
            "jornada_5_fixture": next(({
                "match_id": item.get("match_id"),
                "home_team_name": item.get("home_team_name"),
                "away_team_name": item.get("away_team_name"),
                "result_status": item.get("result_status"),
                "result_raw": item.get("result_raw"),
                "competition_snapshot_at": item.get("_captured_at_utc"),
            } for item in competition_matches if item.get("round") == 5 and str(page["entity_id"]) in {
                str(item.get("home_team_season_id")), str(item.get("away_team_season_id")),
            }), None),
            "source_table_id": table.get("table_id"),
            **_source(page),
        })
    return result, player_rows


_CLUB_MATCH_P_FIELD_MAP = {
    0: "season_start_year_raw",
    1: "competition_code_raw",
    3: "date_raw",
    4: "source_club_home_flag_raw",
    5: "home_team_name_raw",
    6: "home_goals_raw",
    7: "away_goals_raw",
    8: "match_id_raw",
    9: "away_team_name_raw",
    10: "home_club_id_raw",
    11: "away_club_id_raw",
    12: "source_club_result_code_raw",
    13: "referee_id_raw",
    14: "round_label_raw",
    15: "round_code_raw",
    16: "source_club_yellow_cards_raw",
    17: "source_club_red_cards_raw",
    18: "season_raw",
}


def _source_integer(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _integer(value)
    return None


def _embedded_date(value: Any) -> str | None:
    raw = str(value) if value is not None else ""
    match = _DATE.fullmatch(raw.strip())
    if match is None:
        return None
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def _embedded_club_matches(
    parsed_pages: list[dict[str, Any]],
    competition_matches: list[dict[str, Any]],
    team_by_club: dict[str, str],
) -> dict[str, Any]:
    """Normalize the source P tuples while retaining every club observation."""
    observations: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    incidents: list[dict[str, Any]] = []
    for page in sorted(parsed_pages, key=lambda item: (str(item.get("entity_id")), str(item.get("url")))):
        if page.get("entity_type") != "club" or page.get("view") != "club_matches":
            continue
        if urlsplit(str(page.get("url", ""))).query:
            # Filtered snapshots repeat the same page-wide P array; the canonical
            # no-query page is the single observation source for each club.
            continue
        source_data = page.get("club_data", {}).get("embedded_match_data", {})
        parse_status = source_data.get("parse_status", "NOT_PRESENT")
        source_records = source_data.get("records", [])
        club_id = str(page.get("entity_id"))
        club_number = club_id.removeprefix("e")
        team_season_id = team_by_club.get(club_id)
        source_page = _source(page)
        club_rows: list[dict[str, Any]] = []
        for item in source_records:
            raw_values = item.get("source_values_raw")
            if not isinstance(raw_values, list) or len(raw_values) != 19:
                incidents.append({
                    "code": "EMBEDDED_MATCH_UNSUPPORTED_TUPLE",
                    "severity": "error",
                    "club_id": club_id,
                    "source_record_index": item.get("source_record_index"),
                    **source_page,
                })
                continue
            match_id_value = _source_integer(raw_values[8])
            match_id = str(match_id_value) if match_id_value is not None and match_id_value > 0 else None
            home_club_number = str(raw_values[10]) if raw_values[10] is not None else None
            away_club_number = str(raw_values[11]) if raw_values[11] is not None else None
            home_club_id = f"e{home_club_number}" if home_club_number else None
            away_club_id = f"e{away_club_number}" if away_club_number else None
            home_goals = _source_integer(raw_values[6])
            away_goals = _source_integer(raw_values[7])
            source_is_home = (
                home_club_number == club_number
                if home_club_number == club_number or away_club_number == club_number
                else None
            )
            location_flag = _source_integer(raw_values[4])
            if source_is_home is None:
                incidents.append({
                    "code": "EMBEDDED_MATCH_SOURCE_CLUB_NOT_PARTICIPANT",
                    "severity": "error",
                    "club_id": club_id,
                    "match_id": match_id,
                    "source_record_index": item.get("source_record_index"),
                    **source_page,
                })
            elif location_flag != (1 if source_is_home else 0):
                incidents.append({
                    "code": "EMBEDDED_MATCH_HOME_FLAG_CONFLICT",
                    "severity": "warning",
                    "club_id": club_id,
                    "match_id": match_id,
                    "source_record_index": item.get("source_record_index"),
                    "source_flag_raw": location_flag,
                    "home_club_id_raw": home_club_number,
                    "away_club_id_raw": away_club_number,
                    **source_page,
                })
            if source_is_home is not None and home_goals is not None and away_goals is not None:
                home_result = 1 if home_goals > away_goals else -1 if home_goals < away_goals else 0
                result_from_club = home_result if source_is_home else -home_result
                result_status = (
                    "CONSISTENT_WITH_SCORE"
                    if _source_integer(raw_values[12]) == result_from_club
                    else "DIFFERS_FROM_SCORE"
                )
            else:
                result_from_club = None
                result_status = "NOT_COMPARABLE"
            row = {
                "match_id": match_id,
                "match_url": f"https://www.bdfutbol.com/es/p/p.php?id={match_id}" if match_id else None,
                "season_start_year_raw": raw_values[0],
                "season_raw": raw_values[18],
                "competition_code_raw": raw_values[1],
                "date_raw": raw_values[3],
                "date": _embedded_date(raw_values[3]),
                "source_club_home_flag_raw": raw_values[4],
                "source_club_is_home": source_is_home,
                "home_team_name_raw": raw_values[5],
                "home_goals_raw": raw_values[6],
                "home_goals": home_goals,
                "away_goals_raw": raw_values[7],
                "away_goals": away_goals,
                "away_team_name_raw": raw_values[9],
                "home_club_id_raw": raw_values[10],
                "home_club_id": home_club_id,
                "away_club_id_raw": raw_values[11],
                "away_club_id": away_club_id,
                "source_club_result_code_raw": raw_values[12],
                "source_club_result_from_score": result_from_club,
                "source_club_result_validation": result_status,
                "referee_id_raw": raw_values[13],
                "round_label_raw": raw_values[14],
                "round_code_raw": raw_values[15],
                "source_club_yellow_cards_raw": raw_values[16],
                "source_club_red_cards_raw": raw_values[17],
                "unmapped_values_raw": {"2": raw_values[2]},
                "source_club_id": club_id,
                "source_team_season_id": team_season_id,
                "source_kind": "club_match_window.P",
                "source_record_index": item.get("source_record_index"),
                "source_field_map": _CLUB_MATCH_P_FIELD_MAP,
                "source_values_raw": raw_values,
                **source_page,
            }
            club_rows.append(row)
            observations.append(row)
            if result_status == "DIFFERS_FROM_SCORE":
                incidents.append({
                    "code": "EMBEDDED_MATCH_RESULT_CODE_DIFFERS_FROM_SCORE",
                    "severity": "warning",
                    "club_id": club_id,
                    "match_id": match_id,
                    "source_record_index": item.get("source_record_index"),
                    "source_result_code_raw": raw_values[12],
                    "result_from_score": result_from_club,
                    **source_page,
                })
        coverage.append({
            "club_id": club_id,
            "team_season_id": team_season_id,
            "source_parse_status": parse_status,
            "source_records_reported": source_data.get("record_count", 0),
            "source_observations_parsed": len(club_rows),
            "unique_match_ids": len({row["match_id"] for row in club_rows if row.get("match_id")}),
            "records_without_match_id": sum(not row.get("match_id") for row in club_rows),
            "seasons_observed": sorted({str(row["season_raw"]) for row in club_rows if row.get("season_raw")}),
            "current_season_1rf_observations": sum(
                row.get("season_raw") == "2026-27" and row.get("competition_code_raw") == "1rf"
                for row in club_rows
            ),
            "url": source_page.get("url"),
            "snapshot_directory": source_page.get("snapshot_directory"),
            "snapshot_sha256": source_page.get("snapshot_sha256"),
            "captured_at_utc": source_page.get("captured_at_utc"),
        })

    observations.sort(key=lambda item: (
        str(item.get("match_id") or ""),
        str(item.get("source_club_id") or ""),
        int(item.get("source_record_index") or 0),
    ))
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        if row.get("match_id"):
            by_id[str(row["match_id"])].append(row)
    comparison_fields = (
        "season_raw", "competition_code_raw", "date", "home_team_name_raw", "home_goals",
        "away_goals", "away_team_name_raw", "home_club_id", "away_club_id", "referee_id_raw",
        "round_label_raw", "round_code_raw",
    )
    unique_matches: list[dict[str, Any]] = []
    duplicate_matches: list[dict[str, Any]] = []
    for match_id, rows in sorted(by_id.items()):
        selected = rows[0]
        different_fields = [
            field for field in comparison_fields
            if len({json.dumps(row.get(field), ensure_ascii=False, sort_keys=True) for row in rows}) > 1
        ]
        unique_matches.append({
            **selected,
            "source_observation_count": len(rows),
            "source_club_ids": sorted({str(row["source_club_id"]) for row in rows}),
            "differing_fields_between_club_sources": different_fields,
            "source_observations": [
                {
                    "source_club_id": row.get("source_club_id"),
                    "source_team_season_id": row.get("source_team_season_id"),
                    "source_record_index": row.get("source_record_index"),
                    "url": row.get("url"),
                    "snapshot_directory": row.get("snapshot_directory"),
                    "snapshot_sha256": row.get("snapshot_sha256"),
                    "captured_at_utc": row.get("captured_at_utc"),
                }
                for row in rows
            ],
        })
        if len(rows) > 1:
            duplicate_matches.append({
                "match_id": match_id,
                "observation_count": len(rows),
                "source_club_ids": sorted({str(row["source_club_id"]) for row in rows}),
                "differing_fields": different_fields,
                "source_observations": [
                    {
                        "source_club_id": row.get("source_club_id"),
                        "source_record_index": row.get("source_record_index"),
                        "snapshot_sha256": row.get("snapshot_sha256"),
                    }
                    for row in rows
                ],
            })
        if different_fields:
            incidents.append({
                "code": "EMBEDDED_MATCH_DUPLICATE_SOURCES_DIFFER",
                "severity": "warning",
                "match_id": match_id,
                "different_fields": different_fields,
                "source_club_ids": sorted({str(row["source_club_id"]) for row in rows}),
            })

    competition_by_id = {
        str(row["match_id"]): row
        for row in competition_matches
        if row.get("match_id") is not None
        and normalized_match_state(row) == "played"
        and str(row.get("season") or "").replace("-", "/") == "2026/27"
    }
    embedded_current = {
        str(row["match_id"]): row for row in unique_matches
        if row.get("match_id")
        and row.get("season_raw") == "2026-27"
        and row.get("competition_code_raw") == "1rf"
    }
    club_by_team = {team_id: club_id for club_id, team_id in team_by_club.items()}
    crosscheck_rows: list[dict[str, Any]] = []
    for match_id, competition in sorted(competition_by_id.items()):
        embedded = embedded_current.get(match_id)
        if embedded is None:
            crosscheck_rows.append({"match_id": match_id, "status": "NOT_OBSERVED"})
            continue
        checks = {
            "date_match": embedded.get("date") == competition.get("date"),
            "home_team_match": _normalized_name(embedded.get("home_team_name_raw"))
            == _normalized_name(competition.get("home_team_name")),
            "away_team_match": _normalized_name(embedded.get("away_team_name_raw"))
            == _normalized_name(competition.get("away_team_name")),
            "score_match": embedded.get("home_goals") == competition.get("home_goals")
            and embedded.get("away_goals") == competition.get("away_goals"),
            "home_club_match": embedded.get("home_club_id")
            == club_by_team.get(str(competition.get("home_team_season_id"))),
            "away_club_match": embedded.get("away_club_id")
            == club_by_team.get(str(competition.get("away_team_season_id"))),
        }
        crosscheck_rows.append({
            "match_id": match_id,
            "status": "MATCHED" if all(checks.values()) else "DIFFERENT",
            "checks": checks,
            "different_fields": [name for name, matched in checks.items() if not matched],
            "competition_snapshot_at": competition.get("_captured_at_utc"),
            "embedded_source_club_ids": embedded.get("source_club_ids", []),
        })
    observed_ids = set(embedded_current)
    expected_ids = set(competition_by_id)
    unmatched_embedded = sorted(observed_ids - expected_ids)
    missing_embedded = sorted(expected_ids - observed_ids)
    crosscheck = {
        "competition_export_played_matches": len(expected_ids),
        "embedded_current_season_1rf_unique_matches": len(observed_ids),
        "competition_match_ids_missing_from_embedded": missing_embedded,
        "embedded_match_ids_absent_from_competition": unmatched_embedded,
        "match_ids_equal": expected_ids == observed_ids,
        "matches_compared": len(crosscheck_rows) - len(missing_embedded),
        "matches_all_fields_equal": sum(row.get("status") == "MATCHED" for row in crosscheck_rows),
        "differences": [row for row in crosscheck_rows if row.get("status") != "MATCHED"],
    }
    for row in crosscheck["differences"]:
        incidents.append({
            "code": "EMBEDDED_MATCH_COMPETITION_CROSSCHECK_DIFFERENCE",
            "severity": "warning",
            **row,
        })
    return {
        "observations": observations,
        "matches": unique_matches,
        "duplicates": duplicate_matches,
        "coverage": coverage,
        "competition_crosscheck": crosscheck,
        "incidents": incidents,
        "summary": {
            "source_pages_parsed": sum(row.get("source_parse_status") == "PARSED_19_POSITION_TUPLES" for row in coverage),
            "source_pages_expected": len(coverage),
            "club_observations": len(observations),
            "unique_match_ids": len(unique_matches),
            "duplicate_observations": len(observations) - len(unique_matches),
            "matches_with_multiple_club_sources": len(duplicate_matches),
            "matches_without_id": sum(not row.get("match_id") for row in observations),
            "result_code_score_disagreements": sum(
                row.get("source_club_result_validation") == "DIFFERS_FROM_SCORE"
                for row in observations
            ),
            "duplicate_source_conflicts": sum(bool(row.get("differing_fields")) for row in duplicate_matches),
            "historical_seasons_observed": sorted({str(row["season_raw"]) for row in observations if row.get("season_raw")}),
            "current_season_1rf_observations": sum(
                row.get("season_raw") == "2026-27" and row.get("competition_code_raw") == "1rf"
                for row in observations
            ),
            **crosscheck,
        },
    }


def build_club_team_sports_data(
    parsed_pages: list[dict[str, Any]], competition_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Normalize club/team sports rows while keeping source values and provenance."""
    crosscheck_requested = competition_matches is not None
    competition_matches = competition_matches or []
    team_by_club, name_by_team = _team_maps(parsed_pages)
    statistics, stats_by_membership = _player_statistics(parsed_pages)
    rosters, coaches, roster_by_team = _rosters_and_coaches(parsed_pages, stats_by_membership)
    movements = _movement_references(parsed_pages)
    observations, aggregates = _match_observations(parsed_pages, team_by_club, name_by_team)
    embedded = _embedded_club_matches(parsed_pages, competition_matches, team_by_club)
    all_variant_clubs = {
        str(page.get("entity_id"))
        for page in parsed_pages
        if page.get("entity_type") == "club" and page.get("view") == "club_matches"
        and url_has_match_filters(str(page.get("url", "")))
    }
    matches, match_coverage, match_incidents, duplicate_matches = _consolidate_matches(
        observations, competition_matches, aggregates, team_by_club, crosscheck_requested, all_variant_clubs,
    )
    player_teams: dict[str, list[str]] = defaultdict(list)
    for row in rosters:
        player_teams[row["player_id"]].append(row["team_season_id"])
    duplicate_player_memberships = [
        {"player_id": player_id, "team_season_ids": sorted(team_ids)}
        for player_id, team_ids in sorted(player_teams.items()) if len(set(team_ids)) > 1
    ]
    multi_coach_teams = [
        {"team_season_id": team_id, "coach_ids": sorted({item["coach_id"] for item in item_data["coaches"]})}
        for team_id, item_data in sorted(roster_by_team.items())
        if len({item["coach_id"] for item in item_data["coaches"]}) > 1
    ]
    roster_coverage = []
    for team_id, team in sorted(roster_by_team.items()):
        roster_ids = {row["player_id"] for row in team["players"]}
        stat_rows = [item for item in statistics if item["team_season_id"] == team_id]
        stat_ids = {row["player_id"] for row in stat_rows}
        roster_coverage.append({
            "team_season_id": team_id,
            "roster_players": len(team["players"]),
            "statistics_players": len(stat_rows),
            "roster_without_statistics": sorted(roster_ids - stat_ids),
            "statistics_without_roster": sorted(stat_ids - roster_ids),
            "zero_appearance_players": sum(item.get("zero_appearances") is True for item in stat_rows),
            "all_statistics_columns_preserved": all(len(item["columns"]) == len(item["headers_original"]) for item in stat_rows),
        })
    tracking, tracking_rows = _tracking_variants(parsed_pages, competition_matches)
    track_issues = [
        {
            "code": "TEAM_TRACKING_HEADER_5_ABSENT",
            "severity": "warning",
            "team_season_id": item["team_season_id"],
            "headers_original": item["headers_original"],
            "jornada_5_fixture": item.get("jornada_5_fixture"),
            "explanation": (
                "No existe una columna de minutos para jornada 5 y el Hito 1B solo muestra el encuentro aplazado/sin resultado de esa jornada para este equipo; ausencia dependiente de los datos publicados."
                if item.get("jornada_5_fixture") and normalized_match_state(item["jornada_5_fixture"]) != "played"
                else "El DOM capturado no contiene la columna 5; se conserva como variante estructural sin inventar valores."
            ),
        }
        for item in tracking if not item["header_5_present"]
    ]
    incidents = [*match_incidents, *track_issues, *embedded["incidents"]]
    match_coverage = [
        {**item, "all_match_variant_captured": item["club_id"] in all_variant_clubs}
        for item in match_coverage
    ]
    for item in match_coverage:
        if not item["all_match_variant_captured"]:
            item["status"] = "INCOMPLETE"
    return {
        "schema_version": "football_data_hub.bdfutbol.club_team_sports.v2",
        "rosters": rosters,
        "player_statistics": statistics,
        "coaches_current": coaches,
        "movement_references": movements,
        "match_observations": observations,
        "matches_played": matches,
        "embedded_match_observations": embedded["observations"],
        "matches_from_embedded_data": embedded["matches"],
        "duplicate_embedded_matches": embedded["duplicates"],
        "embedded_match_coverage_by_club": embedded["coverage"],
        "embedded_match_competition_crosscheck": embedded["competition_crosscheck"],
        "coverage_by_club": match_coverage,
        "coverage_by_team": roster_coverage,
        "tracking_variants": tracking,
        "tracking_player_rows": tracking_rows,
        "duplicate_matches": duplicate_matches,
        "duplicate_player_memberships": duplicate_player_memberships,
        "multi_coach_teams": multi_coach_teams,
        "incidents": incidents,
        "summary": {
            "roster_memberships": len(rosters),
            "unique_player_ids": len(player_teams),
            "player_statistics_memberships": len(statistics),
            "player_statistics_distinct_ids": len({item["player_id"] for item in statistics}),
            "zero_appearance_player_rows": sum(item.get("zero_appearances") is True for item in statistics),
            "coach_memberships": len(coaches),
            "unique_coach_ids": len({item["coach_id"] for item in coaches}),
            "played_match_observations": sum(normalized_match_state(item) == "played" for item in observations),
            "unique_played_matches": len(matches),
            "played_matches_crosschecked": sum(item.get("competition_match_present") is True for item in matches),
            "clubs_match_validated": sum(item["status"] == "VALIDATED" for item in match_coverage),
            "clubs_match_competition_crosschecked_scope_difference": sum(item["status"] == "COMPETITION_CROSSCHECKED_SCOPE_DIFFERENCE" for item in match_coverage),
            "clubs_match_temporal_review": sum(item["status"] == "TEMPORAL_REVIEW" for item in match_coverage),
            "clubs_match_expected": len(match_coverage),
            "tracking_header_5_missing": sum(not item["header_5_present"] for item in tracking),
            "all_match_variants_captured": len(all_variant_clubs),
            "embedded_match_observations": embedded["summary"]["club_observations"],
            "embedded_unique_match_ids": embedded["summary"]["unique_match_ids"],
            "embedded_duplicate_observations": embedded["summary"]["duplicate_observations"],
            "embedded_result_code_score_disagreements": embedded["summary"]["result_code_score_disagreements"],
            "embedded_match_source_conflicts": embedded["summary"]["duplicate_source_conflicts"],
            "embedded_competition_played_matches_expected": embedded["summary"]["competition_export_played_matches"],
            "embedded_competition_played_matches_observed": embedded["summary"]["embedded_current_season_1rf_unique_matches"],
            "embedded_competition_match_ids_equal": embedded["summary"]["match_ids_equal"],
            "embedded_competition_matches_all_fields_equal": embedded["summary"]["matches_all_fields_equal"],
            "embedded_source_pages_parsed": embedded["summary"]["source_pages_parsed"],
            "embedded_source_pages_expected": embedded["summary"]["source_pages_expected"],
            "embedded_historical_seasons_observed": len(embedded["summary"]["historical_seasons_observed"]),
            "competition_played_matches_not_observed": len({
                str(item["match_id"]) for item in competition_matches
                if item.get("match_id") is not None and normalized_match_state(item) == "played"
            } - {str(item["match_id"]) for item in matches}),
        },
    }
