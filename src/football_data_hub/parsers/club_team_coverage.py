"""Coverage and field inventories for parsed BDFutbol club/team pages."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from football_data_hub.providers.bdfutbol.club_team import (
    expected_views_for_club,
    expected_views_for_team,
)

_TEAM_PRIMARY_TABLES = {
    "team_alignment": "taulaplantilla",
    "team_roster": "c3p1",
    "team_statistics": "c3p0",
}
_CLUB_PRIMARY_TABLES = {
    "club_players": "llista",
    "club_coaches": "llista",
}
_INTERPRETED_HEADERS_BY_VIEW = {
    "team_alignment": {"#", "Dorsal", "Apodo", "Apodo y Nombre", "Nombre", "Fecha", "Lugar de nacimiento", "Provincia", "Pos", "Posición"},
    "team_roster": {"#", "Dorsal", "Apodo", "Apodo y Nombre", "Nombre", "Fecha", "Lugar de nacimiento", "Provincia", "Pos", "Posición"},
    "team_statistics": {"Apodo", "Nombre", "PJ", "Partidos Jugados"},
    "club_players": {"Apodo y Nombre", "Apodo", "Nombre"},
    "club_coaches": {"Apodo y Nombre", "Apodo", "Nombre"},
    "club_matches": {"Temporada", "Competición", "PJ", "PG", "PE", "PP", "GF", "GC"},
    "club_rivals": {"Nombre"},
}
_PENDING_BY_VIEW = {
    "club_profile": ["selector Tabla/Listado, selector de competición y comparación de clubes"],
    "club_statistics": ["pestañas internas y filtros por competición/categoría no activados"],
    "club_players": ["filtros de competición, posición y país no aplicados"],
    "club_coaches": ["filtros de competición y país no aplicados"],
    "club_matches": ["filtros de temporada, competición, rival y resultado no aplicados"],
    "club_rivals": ["filtros por temporada, competición y demarcación no aplicados"],
    "team_alignment": ["vista de alineación comprobada como HTML; no se recorrieron filtros de temporada"],
    "team_roster": ["se procesó 2026-27; temporadas históricas disponibles quedan fuera del alcance del piloto"],
    "team_statistics": ["se procesó 2026-27 / Liga; temporadas históricas disponibles quedan fuera del piloto"],
    "team_tracking": ["opciones Partidos/Tarjetas/Goles/Todo inventariadas; no seleccionadas"],
    "team_transfers": ["temporadas alternativas no seleccionadas"],
    "team_matches": ["vista de progreso/records capturada; filtros o temporadas alternativas no probados"],
}
_CAPTURE_RUN_DIRECTORY = re.compile(r"^\d{8}T\d{6}(?:\.\d+)?Z?$")


def _page_key(page: dict[str, Any]) -> tuple[str, str, str]:
    return str(page["entity_type"]), str(page["entity_id"]), str(page["view"])


def _headers(table: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for row in table.get("rows", []):
        if row.get("kind") == "header":
            result = [str(cell.get("text") or "") for cell in row.get("cells", [])]
            break
    return result


def _relation_counts(page: dict[str, Any]) -> dict[str, int]:
    counts = Counter(str(item["entity_type"]) for item in page.get("relationships", []))
    return dict(sorted(counts.items()))


def _evidence_status(page: dict[str, Any]) -> str:
    directory = str(page.get("source", {}).get("snapshot_directory") or "")
    parts = Path(directory).parts
    direct_capture_path = any(
        part in {"hito_1d_club_team", "hito_1d_a2_interactions"}
        for part in parts
    )
    direct_capture_path = direct_capture_path or any(
        part == "bdfutbol"
        and index + 1 < len(parts)
        and _CAPTURE_RUN_DIRECTORY.fullmatch(parts[index + 1])
        for index, part in enumerate(parts)
    )
    return "VERIFIED" if direct_capture_path else "ARTIFACT_ONLY"


def _linked_ids(page: dict[str, Any], table_id: str, entity_type: str) -> set[str]:
    return {
        str(item["entity_id"])
        for item in page.get("relationships", [])
        if item.get("source_table_id") == table_id and item.get("entity_type") == entity_type
    }


def _is_section_spanning_row(row: dict[str, Any], table: dict[str, Any]) -> bool:
    cells = row.get("cells", [])
    if row.get("row_role") != "data" or len(cells) != 1:
        return False
    cell = cells[0]
    return (
        not cell.get("links")
        and int(cell.get("column_span", 1)) >= int(table.get("column_count") or 1)
    )


def _sports_data_rows(table: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row for row in table.get("rows", [])
        if row.get("kind") == "data"
        and row.get("row_role") not in {"total", "subtotal"}
        and not _is_section_spanning_row(row, table)
    ]


def _view_reconciled(page: dict[str, Any]) -> bool:
    """Validate only views whose source rows can be reconciled deterministically."""
    view = str(page.get("view"))
    tables = page.get("tables", [])
    team_data = page.get("team_data", {})
    if view in {"team_alignment", "team_roster"}:
        table_id = "taulaplantilla" if view == "team_alignment" else "c3p1"
        table = next((item for item in tables if item.get("table_id") == table_id), None)
        records = team_data.get("roster_rows", [])
        record_ids = [str(item["player_id"]) for item in records]
        if (
            table is None
            or len(_sports_data_rows(table)) != len(records)
            or len(record_ids) != len(set(record_ids))
            or set(record_ids) != _linked_ids(page, table_id, "player")
        ):
            return False
        if view == "team_roster":
            coach_table = next((item for item in tables if item.get("table_id") == "taulaentrenadors"), None)
            coach_ids = {str(item["coach_id"]) for item in team_data.get("coach_rows", [])}
            if (
                coach_table is None
                or len(_sports_data_rows(coach_table)) != len(team_data.get("coach_rows", []))
                or coach_ids != _linked_ids(page, "taulaentrenadors", "coach")
            ):
                return False
        return bool(record_ids)

    if view == "team_statistics":
        table = next((item for item in tables if item.get("table_id") == "c3p0"), None)
        records = team_data.get("player_statistics", [])
        totals = team_data.get("statistics_totals", [])
        record_ids = [str(item["player_id"]) for item in records]
        return bool(
            table
            and records
            and totals
            and not team_data.get("statistics_unparsed_rows")
            and table.get("data_row_count") == len(records) + len(totals)
            and len(record_ids) == len(set(record_ids))
            and set(record_ids) == _linked_ids(page, "c3p0", "player")
        )

    if view in {"club_players", "club_coaches"}:
        table = next((item for item in tables if item.get("table_id") == "llista"), None)
        entity_type = "player" if view == "club_players" else "coach"
        linked_ids = _linked_ids(page, "llista", entity_type)
        return bool(table and _sports_data_rows(table) and len(_sports_data_rows(table)) == len(linked_ids))

    if view == "club_rivals":
        expected = (("t5", "player"), ("t6", "coach"), ("t7", "club"))
        for table_id, entity_type in expected:
            table = next((item for item in tables if item.get("table_id") == table_id), None)
            linked_ids = _linked_ids(page, table_id, entity_type)
            if not table or len(_sports_data_rows(table)) != len(linked_ids) or not linked_ids:
                return False
        return True
    return False


def _field_catalog(page: dict[str, Any]) -> dict[str, Any]:
    tables = []
    fields = []
    for table in page.get("tables", []):
        headers = _headers(table)
        fields.extend(header for header in headers if header)
        tables.append({
            "table_index": table.get("table_index"),
            "table_id": table.get("table_id"),
            "classes": table.get("classes", []),
            "caption": table.get("caption"),
            "section_heading": table.get("section_heading"),
            "headers": headers,
            "row_count": table.get("row_count", 0),
            "data_row_count": table.get("data_row_count", 0),
        })
    controls = page.get("controls", {})
    return {
        "tables": tables,
        "fields_observed": list(dict.fromkeys(fields)),
        "filters": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "label": item.get("label"),
                "option_count": len(item.get("options", [])),
                "options": item.get("options", []),
            }
            for item in controls.get("selects", [])
        ],
        "column_controls": controls.get("checkboxes", []),
        "tabs": controls.get("tabs", []),
        "forms": controls.get("forms", []),
        "media": {
            "image_count": len(page.get("images", [])),
            "graphics_count": len(page.get("graphics", [])),
            "gallery_candidates": page.get("galleries", []),
        },
        "related_entity_counts": _relation_counts(page),
    }


def _table(page: dict[str, Any] | None, table_id: str) -> dict[str, Any] | None:
    if page is None:
        return None
    return next((item for item in page.get("tables", []) if item.get("table_id") == table_id), None)


def _value_at(table: dict[str, Any], row: dict[str, Any], header: str) -> str | None:
    headers = table.get("header_cells") or _headers(table)
    target = next((index for index, name in enumerate(headers) if str(name).casefold() == header.casefold()), None)
    if target is None:
        return None
    for cell in row.get("cells", []):
        start = int(cell.get("column_index", 0))
        span = int(cell.get("column_span", 1))
        if start <= target < start + span:
            return str(cell.get("text") or "") if start == target else None
    return None


def _validated_filtered_match_variant(
    page: dict[str, Any],
    canonical_page: dict[str, Any] | None,
    filters: dict[str, str],
) -> dict[str, Any] | None:
    """Check one current-season match variant against its aggregate row and IDs."""
    if page.get("view") != "club_matches":
        return None
    if filters.get("cat") != "1rf" or filters.get("temp") != "2026-27":
        return None
    if set(filters) - {"cat", "temp", "pgep"}:
        return None
    outcome_filter = filters.get("pgep")
    expected_column = {"pg": "PG", "pe": "PE", "pp": "PP", None: "PJ"}.get(outcome_filter)
    if expected_column is None:
        return None
    filtered = _table(page, "tpartits")
    aggregate = _table(canonical_page, "t1")
    if filtered is None or aggregate is None:
        return None
    aggregate_rows = [row for row in aggregate.get("rows", []) if row.get("kind") == "data"]
    season_row = next((row for row in aggregate_rows if _value_at(aggregate, row, "Temporada") == filters["temp"]), None)
    if season_row is None:
        return None
    expected_raw = _value_at(aggregate, season_row, expected_column)
    try:
        expected_count = int(str(expected_raw))
    except (TypeError, ValueError):
        return None
    match_rows = [row for row in filtered.get("rows", []) if row.get("row_role") == "data"]
    filter_match = all(
        _value_at(filtered, row, "Temporada") == filters["temp"]
        and _value_at(filtered, row, "Competición") == filters["cat"]
        for row in match_rows
    )
    row_ids = {
        int(occurrence["source_row_index"]): str(item["entity_id"])
        for item in page.get("relationships", [])
        if item.get("entity_type") == "match"
        for occurrence in item.get("occurrences", [])
        if occurrence.get("source_table_id") == "tpartits"
        and occurrence.get("source_row_index") is not None
    }
    scored: list[tuple[dict[str, Any], int, int, str | None]] = []
    for row in match_rows:
        try:
            goals_for = int(str(_value_at(filtered, row, "GF")))
            goals_against = int(str(_value_at(filtered, row, "GC")))
        except (TypeError, ValueError):
            continue
        outcome = "pg" if goals_for > goals_against else "pe" if goals_for == goals_against else "pp"
        scored.append((row, goals_for, goals_against, outcome))
    outcome_count = len(scored) if outcome_filter is None else sum(
        item[3] == outcome_filter for item in scored
    )
    rows_match_outcome = all(
        item[3] == outcome_filter for item in scored
    ) if outcome_filter else len(scored) == outcome_count
    scored_ids = [row_ids.get(int(row["row_index"])) for row, _, _, _ in scored]
    unique_scored_ids = [match_id for match_id in scored_ids if match_id is not None]
    validated = (
        outcome_count == expected_count
        and filter_match
        and rows_match_outcome
        and len(unique_scored_ids) == len(scored)
        and len(set(unique_scored_ids)) == len(unique_scored_ids)
    )
    return {
        "validated": validated,
        "result_filter": outcome_filter or "all",
        "aggregate_column": expected_column,
        "aggregate_expected": expected_count,
        "filtered_match_rows": len(match_rows),
        "played_match_rows": len(scored),
        "scheduled_or_unscored_rows": len(match_rows) - len(scored),
        "matched_outcome_rows": outcome_count,
        "all_rows_match_query": filter_match,
        "all_rows_match_result_filter": rows_match_outcome,
        "match_ids": unique_scored_ids,
        "match_ids_unique": len(unique_scored_ids) == len(set(unique_scored_ids)),
        "all_played_rows_have_match_ids": len(unique_scored_ids) == len(scored),
        "total_rows": sum(row.get("row_role") == "total" for row in filtered.get("rows", [])),
        "basis": f"tpartits {outcome_filter or 'sin pgep'} frente a {expected_column} de t1 para 2026-27",
    }


def _table_integrity(table: dict[str, Any]) -> dict[str, Any]:
    rows = table.get("rows", [])
    data_rows = [row for row in rows if row.get("kind") == "data"]
    inconsistent = []
    section_spanning_rows = []
    omissions: dict[str, dict[str, Any]] = {}
    headers = table.get("header_cells") or _headers(table)
    for row in rows:
        alignment = row.get("column_alignment", {})
        if alignment.get("overflow_column_count", 0):
            if _is_section_spanning_row(row, table):
                section_spanning_rows.append(row.get("row_index"))
            else:
                inconsistent.append(row.get("row_index"))
        missing = alignment.get("missing_trailing_column_indexes", [])
        if missing:
            omissions[str(row.get("row_index"))] = {
                "column_indexes": missing,
                "headers": [headers[index] if index < len(headers) else None for index in missing],
                "status": alignment.get("status"),
            }
    matches_counts = (
        table.get("row_count") == len(rows)
        and table.get("data_row_count") == len(data_rows)
        and not inconsistent
    )
    return {
        "status": "VALIDATED" if matches_counts else "MISMATCH",
        "html_parser_rows": len(rows),
        "reported_rows": table.get("row_count"),
        "data_rows": len(data_rows),
        "reported_data_rows": table.get("data_row_count"),
        "headers": headers,
        "header_count": len(headers),
        "row_indexes_with_overflow": inconsistent,
        "section_spanning_row_indexes": section_spanning_rows,
        "source_column_omissions": omissions,
        "raw_cell_values_preserved": all(
            isinstance(cell.get("text"), str)
            for row in rows for cell in row.get("cells", [])
        ),
    }


def _page_integrity(page: dict[str, Any]) -> dict[str, Any]:
    tables = page.get("tables", [])
    table_checks = {
        str(table.get("table_id") or f"table_{table.get('table_index')}"): _table_integrity(table)
        for table in tables
    }
    team_data = page.get("team_data", {})
    typed_rows = (
        team_data.get("roster_rows", [])
        or team_data.get("player_statistics", [])
        or team_data.get("coach_rows", [])
    )
    observed_headers = list(dict.fromkeys(
        header
        for check in table_checks.values()
        for header in check["headers"]
        if header
    ))
    mapped_headers = {header.casefold() for header in _INTERPRETED_HEADERS_BY_VIEW.get(str(page.get("view")), set())}
    raw_only_headers = [header for header in observed_headers if header.casefold() not in mapped_headers]
    table_status = (
        "NOT_VALIDATED_NO_TABLES"
        if not table_checks
        else "VALIDATED"
        if all(item["status"] == "VALIDATED" for item in table_checks.values())
        else "MISMATCH"
    )
    return {
        "table_status": table_status,
        "tables": table_checks,
        "interpreted_record_fields": sorted({
            key
            for row in typed_rows
            for key in row
            if key not in {"raw_cells", "statistics_cells"}
        }),
        "structured_source_headers": [header for header in observed_headers if header.casefold() in mapped_headers],
        "raw_only_headers": raw_only_headers,
        "unparsed_statistics_rows": len(team_data.get("statistics_unparsed_rows", [])),
        "relationship_counts": _relation_counts(page),
        "relationships_reconciled": _view_reconciled(page),
    }


def _entity_pending_interactions(entity_views: list[dict[str, Any]]) -> list[dict[str, str]]:
    pending = []
    for view in entity_views:
        for item in view.get("pending", []):
            pending.append({"view": str(view["view"]), "item": str(item)})
    return pending


def _interaction_variant_coverage(
    variant_pages: list[dict[str, Any]],
    parsed_by_key: dict[tuple[str, str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    variants = []
    for page in variant_pages:
        variant = page.get("view_variant", {})
        filters = variant.get("filter_parameters") or parse_qs(urlsplit(str(page.get("url", ""))).query)
        filters = {str(key): str(value[-1] if isinstance(value, list) else value) for key, value in filters.items()}
        source = page.get("source", {})
        validation = _validated_filtered_match_variant(
            page,
            parsed_by_key.get((str(page.get("entity_type")), str(page.get("entity_id")), str(page.get("view")))),
            filters,
        )
        table = _table(page, "tpartits") if page.get("view") == "club_matches" else None
        records = (
            sum(row.get("row_role") == "data" for row in table.get("rows", []))
            if table
            else sum(
                row.get("row_role") == "data"
                for item in page.get("tables", [])
                for row in item.get("rows", [])
            )
        )
        parsed = source.get("access_status") == "VALID" and bool(page.get("tables"))
        status = "VALIDATED" if parsed and validation and validation.get("validated") else "PARSED" if parsed else "DISCOVERED"
        complete = status == "VALIDATED"
        variants.append({
            "entity_type": page.get("entity_type"),
            "entity_id": page.get("entity_id"),
            "view": page.get("view"),
            "variant_id": variant.get("variant_id"),
            "scope": variant.get("scope"),
            "filter_parameters": filters,
            "status": status,
            "coverage_status": "COMPLETE" if complete else "INCOMPLETE",
            "access_status": source.get("access_status"),
            "evidence_status": "VERIFIED" if "hito_1d_a2_interactions" in str(source.get("snapshot_directory", "")) else "ARTIFACT_ONLY",
            "url": page.get("url"),
            "snapshot_sha256": source.get("rendered_html_sha256"),
            "snapshot_directory": source.get("snapshot_directory"),
            "records_observed": records,
            "validation": validation,
            "pending": [] if complete else ["No se pudo contrastar la variante con un agregado fuente o las filas no coinciden."],
        })
    return variants


def _member_counts(parsed_by_key: dict[tuple[str, str, str], dict[str, Any]], team_id: str) -> dict[str, Any]:
    roster = parsed_by_key.get(("team_season", team_id, "team_roster"), {})
    stats = parsed_by_key.get(("team_season", team_id, "team_statistics"), {})
    roster_rows = roster.get("team_data", {}).get("roster_rows", [])
    stat_rows = stats.get("team_data", {}).get("player_statistics", [])
    roster_ids = [str(row.get("player_id")) for row in roster_rows]
    stat_ids = [str(row.get("player_id")) for row in stat_rows]
    return {
        "roster_rows": len(roster_rows),
        "roster_unique_player_ids": len(set(roster_ids)),
        "roster_duplicate_player_ids": sorted(
            player_id for player_id, count in Counter(roster_ids).items() if count > 1
        ),
        "statistics_rows": len(stat_rows),
        "statistics_unique_player_ids": len(set(stat_ids)),
        "statistics_duplicate_player_ids": sorted(
            player_id for player_id, count in Counter(stat_ids).items() if count > 1
        ),
        "roster_ids_without_statistics": sorted(set(roster_ids) - set(stat_ids)),
        "statistics_ids_without_roster": sorted(set(stat_ids) - set(roster_ids)),
        "zero_appearance_player_ids": sorted(
            str(row["player_id"]) for row in stat_rows if row.get("zero_appearances") is True
        ),
        "appearance_value_unknown_player_ids": sorted(
            str(row["player_id"]) for row in stat_rows if row.get("appearances") is None
        ),
        "coach_rows": len(roster.get("team_data", {}).get("coach_rows", [])),
        "coach_ids": sorted({
            str(row["coach_id"]) for row in roster.get("team_data", {}).get("coach_rows", [])
        }),
    }


def build_club_team_coverage(
    parsed_pages: list[dict[str, Any]],
    *,
    team_season_ids: list[str] | None = None,
    variant_pages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Report exact view-level states; incomplete filters never become COMPLETE."""
    parsed_by_key = {_page_key(page): page for page in parsed_pages}
    teams = sorted(set(team_season_ids or [
        str(page["entity_id"]) for page in parsed_pages if page["entity_type"] == "team_season"
    ]))
    team_clubs: dict[str, str] = {}
    for team_id in teams:
        base = parsed_by_key.get(("team_season", team_id, "team_alignment"), {})
        if base.get("club_id"):
            team_clubs[team_id] = str(base["club_id"])
    clubs = sorted(set(team_clubs.values()) | {
        str(page["entity_id"]) for page in parsed_pages if page["entity_type"] == "club"
    })

    rows: list[dict[str, Any]] = []
    for entity_type, entity_ids, expected_views in (
        ("team_season", teams, expected_views_for_team()),
        ("club", clubs, expected_views_for_club()),
    ):
        for entity_id in entity_ids:
            for view in expected_views:
                page = parsed_by_key.get((entity_type, entity_id, view))
                if page is None:
                    rows.append({
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "view": view,
                        "status": "DISCOVERED",
                        "coverage_status": "INCOMPLETE",
                        "access_status": None,
                        "table_integrity_status": "NOT_CAPTURED",
                        "table_integrity": {},
                        "interpreted_record_fields": [],
                        "structured_source_headers": [],
                        "raw_only_headers": [],
                        "source_column_omissions": {},
                        "url": None,
                        "records_observed": 0,
                        "reason": "La vista está identificada en la navegación del proveedor, pero no hay snapshot de este piloto.",
                        "pending": _PENDING_BY_VIEW[view],
                    })
                    continue

                source = page.get("source", {})
                table_id = _TEAM_PRIMARY_TABLES.get(view) or _CLUB_PRIMARY_TABLES.get(view)
                if view == "club_rivals":
                    expected_tables = {"t5", "t6", "t7"}
                    primary_tables = [table for table in page.get("tables", []) if table.get("table_id") in expected_tables]
                    records = sum(table.get("data_row_count", 0) for table in primary_tables)
                elif view == "club_profile":
                    primary_tables = page.get("tables", [])
                    records = sum(table.get("data_row_count", 0) for table in primary_tables)
                elif view == "club_statistics":
                    primary_tables = page.get("tables", [])
                    records = sum(table.get("data_row_count", 0) for table in primary_tables)
                elif view == "club_matches":
                    primary_tables = page.get("tables", [])
                    records = sum(table.get("data_row_count", 0) for table in primary_tables)
                elif view == "team_statistics":
                    primary_tables = [table for table in page.get("tables", []) if table.get("table_id") == table_id]
                    records = len(page.get("team_data", {}).get("player_statistics", []))
                elif entity_type == "team_season" and view in {"team_roster", "team_alignment"}:
                    primary_tables = [table for table in page.get("tables", []) if table.get("table_id") == table_id]
                    records = len(page.get("team_data", {}).get("roster_rows", []))
                else:
                    primary_tables = page.get("tables", [])
                    records = sum(table.get("data_row_count", 0) for table in primary_tables)

                parsed_ok = not page.get("diagnostics") and source.get("access_status") == "VALID"
                if table_id and view not in {"club_profile", "club_statistics", "club_matches"}:
                    parsed_ok = parsed_ok and bool(primary_tables)
                status = "VALIDATED" if parsed_ok and _view_reconciled(page) else "PARSED"
                integrity = _page_integrity(page)
                coverage_status = "INCOMPLETE"
                if entity_type == "team_season" and view in {"team_roster", "team_statistics"}:
                    counts = _member_counts(parsed_by_key, entity_id)
                    if (
                        status == "VALIDATED"
                        and counts["roster_rows"] > 0
                        and counts["statistics_rows"] > 0
                        and counts["roster_rows"] == counts["roster_unique_player_ids"]
                        and counts["statistics_rows"] == counts["statistics_unique_player_ids"]
                        and not counts["roster_ids_without_statistics"]
                        and not counts["statistics_ids_without_roster"]
                    ):
                        coverage_status = "COMPLETE"
                rows.append({
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "view": view,
                    "status": status,
                    "coverage_status": coverage_status,
                    "access_status": source.get("access_status"),
                    "table_integrity_status": integrity["table_status"],
                    "table_integrity": integrity["tables"],
                    "interpreted_record_fields": integrity["interpreted_record_fields"],
                    "structured_source_headers": integrity["structured_source_headers"],
                    "raw_only_headers": integrity["raw_only_headers"],
                    "source_column_omissions": {
                        table_id: check["source_column_omissions"]
                        for table_id, check in integrity["tables"].items()
                        if check["source_column_omissions"]
                    },
                    "unparsed_statistics_rows": integrity["unparsed_statistics_rows"],
                    "relationship_counts": integrity["relationship_counts"],
                    "relationships_reconciled": integrity["relationships_reconciled"],
                    "evidence_status": _evidence_status(page),
                    "url": page.get("url"),
                    "snapshot_sha256": source.get("rendered_html_sha256"),
                    "snapshot_directory": source.get("snapshot_directory"),
                    "primary_table_ids": [item.get("table_id") for item in primary_tables],
                    "records_observed": records,
                    "reason": (
                        "La tabla y sus IDs enlazados se reconciliaron dentro de esta vista; "
                        "la interpretación tipada cubre solo el alcance documentado de esta vista."
                        if coverage_status == "COMPLETE"
                        else "Las filas raw se conservaron; quedan campos, filtros o variantes por interpretar."
                        if status == "VALIDATED"
                        else "Snapshot válido y parseado; todavía no se reconciliaron todas las filas primarias con sus IDs."
                    ),
                    "pending": _PENDING_BY_VIEW[view],
                })

    team_records = {team_id: _member_counts(parsed_by_key, team_id) for team_id in teams}
    interaction_variants = _interaction_variant_coverage(variant_pages or [], parsed_by_key)
    match_result_coverage = _match_result_coverage(interaction_variants, clubs)
    match_result_by_club = {item["club_id"]: item for item in match_result_coverage}
    for row in rows:
        if row["entity_type"] != "club" or row["view"] != "club_matches" or row["status"] == "DISCOVERED":
            continue
        scope = match_result_by_club.get(str(row["entity_id"]))
        if scope and scope["status"] == "COMPLETE":
            row["pending"] = [
                "Filtros de temporadas históricas, rival y nacionalidad fuera de 1rf/2026-27 no explorados."
            ]
        elif scope and scope["observed_result_views"]:
            row["pending"] = [
                "Faltan variantes 1rf/2026-27 de resultado: "
                + ", ".join(scope["missing_result_views"]),
                "Filtros de temporadas históricas, rival y nacionalidad no explorados.",
            ]
    unique_players = {
        str(row["player_id"])
        for page in parsed_pages
        if page.get("entity_type") == "team_season" and page.get("view") == "team_roster"
        for row in page.get("team_data", {}).get("roster_rows", [])
    }
    unique_coaches = {
        str(row["coach_id"])
        for page in parsed_pages
        if page.get("entity_type") == "team_season" and page.get("view") == "team_roster"
        for row in page.get("team_data", {}).get("coach_rows", [])
    }
    status_counts = Counter(row["status"] for row in rows)
    entity_coverage = []
    for entity_type, entity_ids, expected_views in (
        ("team_season", teams, expected_views_for_team()),
        ("club", clubs, expected_views_for_club()),
    ):
        for entity_id in entity_ids:
            entity_views = [
                row for row in rows
                if row["entity_type"] == entity_type and row["entity_id"] == entity_id
            ]
            captured = sum(row["status"] != "DISCOVERED" for row in entity_views)
            valid = sum(row["access_status"] == "VALID" for row in entity_views)
            structurally_validated = sum(row.get("table_integrity_status") == "VALIDATED" for row in entity_views)
            capture_complete = captured == len(expected_views) and valid == len(expected_views)
            pending_interactions = _entity_pending_interactions(entity_views)
            fully_interpreted = all(row["coverage_status"] == "COMPLETE" for row in entity_views)
            entity_status = (
                "COMPLETE"
                if capture_complete and fully_interpreted and not pending_interactions
                else "BASE_CAPTURED"
                if capture_complete
                else "INCOMPLETE"
            )
            entity_coverage.append({
                "entity_type": entity_type,
                "entity_id": entity_id,
                "club_id": team_clubs.get(entity_id) if entity_type == "team_season" else None,
                "views_expected": len(expected_views),
                "views_captured": captured,
                "views_access_valid": valid,
                "views_structurally_validated": structurally_validated,
                "base_capture_status": "COMPLETE" if capture_complete else "PARTIAL",
                "interpretation_status": "COMPLETE_WITHIN_SCOPE" if fully_interpreted and not pending_interactions else "PARTIAL_RAW_PRESERVED",
                "status": entity_status,
                "pending_views": [
                    row["view"] for row in entity_views if row["status"] == "DISCOVERED"
                ],
                "pending_interpretation_views": [
                    row["view"] for row in entity_views if row["coverage_status"] != "COMPLETE"
                ],
                "pending_interactions": pending_interactions,
                "reason": (
                    "Las vistas base están capturadas; persisten interpretaciones, campos raw-only o interacciones pendientes."
                    if entity_status == "BASE_CAPTURED"
                    else "Faltan snapshots base válidos para cerrar la captura de esta entidad."
                ),
            })
    return {
        "schema_version": "football_data_hub.bdfutbol.club_team_coverage.v3",
        "scope": {
            "team_season_ids": teams,
            "club_ids": clubs,
            "team_season_views_expected": list(expected_views_for_team()),
            "club_views_expected": list(expected_views_for_club()),
        },
        "summary": {
            "views_expected": len(rows),
            "views_captured": sum(row["status"] != "DISCOVERED" for row in rows),
            "views_validated": sum(row["status"] == "VALIDATED" for row in rows),
            "views_complete": sum(row["coverage_status"] == "COMPLETE" for row in rows),
            "interaction_variants_observed": len(interaction_variants),
            "interaction_variants_complete": sum(row["coverage_status"] == "COMPLETE" for row in interaction_variants),
            "match_result_scopes_complete": sum(item["status"] == "COMPLETE" for item in match_result_coverage),
            "entities_complete": sum(item["status"] == "COMPLETE" for item in entity_coverage),
            "entities_base_captured": sum(item["base_capture_status"] == "COMPLETE" for item in entity_coverage),
            "entities_incomplete": sum(item["status"] != "COMPLETE" for item in entity_coverage),
            "pipeline_states": dict(sorted(status_counts.items())),
            "team_player_memberships": sum(item["roster_rows"] for item in team_records.values()),
            "unique_team_player_ids": len(unique_players),
            "unique_team_coach_ids": len(unique_coaches),
        },
        "team_membership_checks": team_records,
        "entity_coverage": entity_coverage,
        "match_result_coverage": match_result_coverage,
        "views": rows,
        "interaction_variants": interaction_variants,
        "resources": [
            {
                "entity_type": page["entity_type"],
                "entity_id": page["entity_id"],
                "view": page["view"],
                "url": page["url"],
                "title": page.get("title"),
                "evidence_status": next((row["evidence_status"] for row in rows if row.get("url") == page["url"]), "ARTIFACT_ONLY"),
                "access_status": page.get("source", {}).get("access_status"),
                "http_status": page.get("source", {}).get("http_status"),
                "snapshot_sha256": page.get("source", {}).get("rendered_html_sha256"),
                "snapshot_directory": page.get("source", {}).get("snapshot_directory"),
                "observed_structure": page.get("structure"),
                "field_inventory": _field_catalog(page),
                "relationship_counts": _relation_counts(page),
                "diagnostics": page.get("diagnostics", []),
            }
            for page in parsed_pages
        ],
        "definitions": {
            "DISCOVERED": "Se conoce la URL/vista; no hay snapshot procesado para este piloto.",
            "CAPTURED": "La respuesta raw fue capturada y validada por BDFutbolAccess.",
            "PARSED": "El HTML fue interpretado por el parser offline.",
            "VALIDATED": "Hash/HTTP y estructura extraída fueron comprobados.",
            "COMPLETE": "Todos los campos/registros de la vista están reconciliados; no implica que la entidad completa esté cerrada.",
            "INCOMPLETE": "Quedan secciones, filtros o variantes conocidos por inspeccionar.",
            "BASE_CAPTURED": "Todas las vistas base esperadas tienen snapshots VALID; campos raw-only e interacciones siguen separados.",
            "RAW_CAPTURED": "La estructura HTML/tabla y sus valores de celda se preservaron; no implica interpretación semántica.",
            "BLOCKED": "BDFutbolAccess devolvió un desafío o bloqueo; no se interpreta como contenido deportivo.",
        },
    }


def _match_result_coverage(
    variants: list[dict[str, Any]], club_ids: list[str]
) -> list[dict[str, Any]]:
    """Require all-results plus each outcome and reconcile unique played match IDs."""
    expected_filters = {"all", "pg", "pe", "pp"}
    result = []
    for club_id in club_ids:
        observed = {}
        for variant in variants:
            if variant.get("entity_type") != "club" or variant.get("entity_id") != club_id:
                continue
            filters = variant.get("filter_parameters", {})
            if filters.get("cat") != "1rf" or filters.get("temp") != "2026-27":
                continue
            result_filter = str(filters.get("pgep") or "all")
            if result_filter in expected_filters:
                observed[result_filter] = variant
        ids_by_filter = {
            name: set((variant.get("validation") or {}).get("match_ids", []))
            for name, variant in observed.items()
        }
        combined = [match_id for name in ("pg", "pe", "pp") for match_id in ids_by_filter.get(name, set())]
        duplicate_ids = sorted({match_id for match_id in combined if combined.count(match_id) > 1})
        outcomes_union = set(combined)
        all_ids = ids_by_filter.get("all", set())
        expected_counts = {
            name: (observed.get(name, {}).get("validation") or {}).get("aggregate_expected")
            for name in ("pg", "pe", "pp", "all")
        }
        outcomes_sum = (
            sum(expected_counts[name] for name in ("pg", "pe", "pp"))
            if all(isinstance(expected_counts[name], int) for name in ("pg", "pe", "pp"))
            else None
        )
        all_variants_valid = all(
            name in observed and observed[name].get("coverage_status") == "COMPLETE"
            for name in expected_filters
        )
        reconciled = bool(
            all_variants_valid
            and not duplicate_ids
            and outcomes_union == all_ids
            and outcomes_sum == expected_counts["all"] == len(all_ids)
        )
        result.append({
            "club_id": club_id,
            "scope": f"club={club_id};cat=1rf;temp=2026-27;result=all,pg,pe,pp",
            "status": "COMPLETE" if reconciled else "INCOMPLETE",
            "expected_result_views": sorted(expected_filters),
            "observed_result_views": sorted(observed),
            "missing_result_views": sorted(expected_filters - set(observed)),
            "aggregate_counts": expected_counts,
            "outcome_match_ids": {name: sorted(ids_by_filter.get(name, set())) for name in ("pg", "pe", "pp")},
            "all_result_match_ids": sorted(all_ids),
            "duplicate_ids_across_outcomes": duplicate_ids,
            "outcome_union_equals_all_view": bool(all_variants_valid and outcomes_union == all_ids),
            "reason": "El conjunto de victorias/empates/derrotas se reconcilia con PJ y la vista general." if reconciled else "Faltan variantes o la unión de IDs/resultados no coincide con los agregados.",
        })
    return result
