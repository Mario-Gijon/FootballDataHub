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
            or table.get("data_row_count") != len(records)
            or len(record_ids) != len(set(record_ids))
            or set(record_ids) != _linked_ids(page, table_id, "player")
        ):
            return False
        if view == "team_roster":
            coach_table = next((item for item in tables if item.get("table_id") == "taulaentrenadors"), None)
            coach_ids = {str(item["coach_id"]) for item in team_data.get("coach_rows", [])}
            if (
                coach_table is None
                or coach_table.get("data_row_count") != len(team_data.get("coach_rows", []))
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
        return bool(table and table.get("data_row_count") and table["data_row_count"] == len(linked_ids))

    if view == "club_rivals":
        expected = (("t5", "player"), ("t6", "coach"), ("t7", "club"))
        for table_id, entity_type in expected:
            table = next((item for item in tables if item.get("table_id") == table_id), None)
            linked_ids = _linked_ids(page, table_id, entity_type)
            if not table or table.get("data_row_count") != len(linked_ids) or not linked_ids:
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
    """Cross-check one explicit current-season results filter against the club total table."""
    expected_filters = {"cat": "1rf", "temp": "2026-27", "pgep": "pg"}
    if page.get("view") != "club_matches" or filters != expected_filters:
        return None
    filtered = _table(page, "tpartits")
    aggregate = _table(canonical_page, "t1")
    if filtered is None or aggregate is None:
        return None
    aggregate_rows = [row for row in aggregate.get("rows", []) if row.get("kind") == "data"]
    season_row = next((row for row in aggregate_rows if _value_at(aggregate, row, "Temporada") == filters["temp"]), None)
    if season_row is None:
        return None
    expected_wins_raw = _value_at(aggregate, season_row, "PG")
    try:
        expected_wins = int(str(expected_wins_raw))
    except (TypeError, ValueError):
        return None
    match_rows = [row for row in filtered.get("rows", []) if row.get("row_role") == "data"]
    filter_match = all(
        _value_at(filtered, row, "Temporada") == filters["temp"]
        and _value_at(filtered, row, "Competición") == filters["cat"]
        for row in match_rows
    )
    validated = bool(match_rows) and len(match_rows) == expected_wins and filter_match
    return {
        "validated": validated,
        "aggregate_wins": expected_wins,
        "filtered_match_rows": len(match_rows),
        "all_rows_match_query": filter_match,
        "total_rows": sum(row.get("row_role") == "total" for row in filtered.get("rows", [])),
        "basis": "tpartits filas de 1rf/2026-27 frente a PG de t1 para 2026-27",
    }


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
                    "evidence_status": _evidence_status(page),
                    "url": page.get("url"),
                    "snapshot_sha256": source.get("rendered_html_sha256"),
                    "snapshot_directory": source.get("snapshot_directory"),
                    "primary_table_ids": [item.get("table_id") for item in primary_tables],
                    "records_observed": records,
                    "reason": (
                        "La tabla y sus IDs enlazados se reconciliaron dentro de esta vista; "
                        "la entidad sigue INCOMPLETE mientras falten otras vistas."
                        if coverage_status == "COMPLETE"
                        else "Las filas primarias y sus IDs enlazados se reconciliaron; quedan filtros o variantes por comprobar."
                        if status == "VALIDATED"
                        else "Snapshot válido y parseado; todavía no se reconciliaron todas las filas primarias con sus IDs."
                    ),
                    "pending": _PENDING_BY_VIEW[view],
                })

    team_records = {team_id: _member_counts(parsed_by_key, team_id) for team_id in teams}
    interaction_variants = _interaction_variant_coverage(variant_pages or [], parsed_by_key)
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
    return {
        "schema_version": "football_data_hub.bdfutbol.club_team_coverage.v1",
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
            "entities_incomplete": len(teams) + len(clubs),
            "pipeline_states": dict(sorted(status_counts.items())),
            "team_player_memberships": sum(item["roster_rows"] for item in team_records.values()),
            "unique_team_player_ids": len(unique_players),
            "unique_team_coach_ids": len(unique_coaches),
        },
        "team_membership_checks": team_records,
        "entity_coverage": [
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "club_id": team_clubs.get(entity_id) if entity_type == "team_season" else None,
                "views_expected": len(expected_views),
                "views_captured": sum(
                    row["entity_type"] == entity_type and row["entity_id"] == entity_id and row["status"] != "DISCOVERED"
                    for row in rows
                ),
                "status": "INCOMPLETE",
                "pending_views": [
                    row["view"] for row in rows
                    if row["entity_type"] == entity_type and row["entity_id"] == entity_id and row["status"] == "DISCOVERED"
                ],
                "reason": "Quedan filtros, variantes o vistas relacionadas pendientes; no se declara COMPLETE.",
            }
            for entity_type, entity_ids, expected_views in (
                ("team_season", teams, expected_views_for_team()),
                ("club", clubs, expected_views_for_club()),
            )
            for entity_id in entity_ids
        ],
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
            "BLOCKED": "BDFutbolAccess devolvió un desafío o bloqueo; no se interpreta como contenido deportivo.",
        },
    }
