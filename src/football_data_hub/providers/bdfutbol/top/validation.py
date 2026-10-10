"""Validaciones de consistencia semántica de una captura de Destacados."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from typing import Any

from .models import ParsedTop


def validate_top_data(parsed: ParsedTop) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    warnings = list(parsed.warnings)
    expected_categories = {
        "goals", "minutes", "yellow_cards", "red_cards", "youngest", "oldest"
    }
    category_counts = Counter(record.category for record in parsed.rankings)
    if set(category_counts) != expected_categories:
        issues.append({"code": "ranking_categories", "message": "Faltan categorías o hay categorías inesperadas."})
    for category in expected_categories:
        records = sorted(
            (record for record in parsed.rankings if record.category == category),
            key=lambda record: record.rank,
        )
        ranks = [record.rank for record in records]
        if ranks != list(range(1, len(records) + 1)):
            issues.append({"code": "rank_sequence", "message": f"{category}: posiciones no consecutivas."})
        if len({record.player_id for record in records}) != len(records):
            issues.append({"code": "ranking_duplicate", "message": f"{category}: jugador duplicado."})
        if any(record.metric_value < 0 for record in records):
            issues.append({"code": "negative_metric", "message": f"{category}: métrica negativa."})
    player_ids = {player.player_id for player in parsed.players}
    players_by_id = {player.player_id: player for player in parsed.players}
    if len(player_ids) != len(parsed.players):
        issues.append({"code": "player_catalog_duplicate", "message": "El catálogo de jugadores contiene IDs duplicados."})
    referenced_ids = {record.player_id for record in parsed.rankings}
    referenced_ids.update(record.player_id for record in parsed.foreigners)
    if referenced_ids.difference(player_ids):
        issues.append({"code": "orphan_player", "message": "Hay registros sin jugador normalizado."})
    conflict_ids = {conflict.player_id for conflict in parsed.affiliation_conflicts}
    for player in parsed.players:
        if player.team_id is None:
            if player.player_id not in conflict_ids:
                issues.append({"code": "unresolved_team", "message": f"player_id={player.player_id} no tiene team_id verificado ni conflicto documentado."})
            elif any(value is not None for value in (player.team_name, player.team_url, player.crest_url)):
                issues.append({"code": "ambiguous_team_fields", "message": f"player_id={player.player_id} conserva datos de equipo aunque su afiliación es ambigua."})
    if conflict_ids.difference(player_ids):
        issues.append({"code": "orphan_affiliation_conflict", "message": "Un conflicto de afiliación referencia un jugador desconocido."})
    if any(
        len(conflict.affiliations) < 2
        or len({item.team_id for item in conflict.affiliations}) != len(conflict.affiliations)
        for conflict in parsed.affiliation_conflicts
    ):
        issues.append({"code": "invalid_affiliation_conflict", "message": "Un conflicto de afiliación no contiene IDs de equipo distintos."})
    if len({record.player_id for record in parsed.foreigners}) != len(parsed.foreigners):
        issues.append({"code": "foreign_duplicate", "message": "La tabla de extranjeros contiene IDs duplicados."})
    country_codes = [code for code, _ in parsed.foreigners_summary.country_options]
    if not country_codes or country_codes[0] != "":
        issues.append({"code": "foreign_country_options", "message": "La lista de nacionalidades no comienza con Todos."})
    if len(country_codes) != len(set(country_codes)):
        issues.append({"code": "foreign_country_options_duplicate", "message": "La lista de nacionalidades repite códigos."})
    if parsed.foreigners_summary.source_percentage is not None and not 0 <= parsed.foreigners_summary.source_percentage <= 100:
        issues.append({"code": "foreign_percentage", "message": "El porcentaje de extranjeros está fuera del rango 0–100."})
    if parsed.foreigners_summary.denominator_count is not None and parsed.foreigners_summary.denominator_count < parsed.foreigners_summary.source_count:
        issues.append({"code": "foreign_denominator", "message": "El denominador de extranjeros es inferior al numerador."})
    country_code_set = set(country_codes)
    if any(
        (players_by_id.get(record.player_id) is None)
        or (
            players_by_id[record.player_id].nationality_code
            and players_by_id[record.player_id].nationality_code not in country_code_set
        )
        for record in parsed.foreigners
    ):
        issues.append({"code": "foreign_country_missing", "message": "Un jugador extranjero no aparece en las opciones de nacionalidad."})
    progress_by_category = Counter(series.category for series in parsed.progress)
    expected_progress = {
        "goals": category_counts.get("goals", 0),
        "minutes": category_counts.get("minutes", 0),
        "yellow_cards": category_counts.get("yellow_cards", 0),
        "red_cards": category_counts.get("red_cards", 0),
    }
    if {category: progress_by_category.get(category, 0) for category in expected_progress} != expected_progress:
        issues.append({"code": "progress_coverage", "message": "Las series no cubren todas las filas con gráfico."})
    for series in parsed.progress:
        if not series.points:
            issues.append({"code": "progress_empty", "message": f"Serie vacía para player_id={series.player_id}."})
            continue
        if tuple(point.matchday for point in series.points) != parsed.chart_matchdays:
            issues.append({"code": "progress_matchdays", "message": f"Jornadas incoherentes para player_id={series.player_id}."})
        values = [point.value for point in series.points]
        if any(value is not None and value < 0 for value in values):
            issues.append({"code": "negative_progress", "message": f"Valor negativo en player_id={series.player_id}."})
        observed = [value for value in values if value is not None]
        if any(current < previous for previous, current in zip(observed, observed[1:])):
            issues.append({"code": "progress_not_cumulative", "message": f"Serie no acumulativa para player_id={series.player_id}."})
        ranking = next(
            (record for record in parsed.rankings if record.category == series.category and record.player_id == series.player_id),
            None,
        )
        if ranking is None or series.points[-1].value != ranking.metric_value:
            issues.append({"code": "progress_total_mismatch", "message": f"La serie no termina en el valor del ranking para player_id={series.player_id}."})
    for foreign in parsed.foreigners:
        for field_name, value in asdict(foreign).items():
            if field_name != "player_id" and value is not None and value < 0:
                issues.append({"code": "negative_foreign_stat", "message": f"{field_name} negativo en player_id={foreign.player_id}."})
                break
    return {
        "valid": not issues,
        "summary": {
            "categories": len(category_counts),
            "ranking_records": len(parsed.rankings),
            "players": len(parsed.players),
            "progress_series": len(parsed.progress),
            "progress_points": sum(len(series.points) for series in parsed.progress),
            "foreign_players": len(parsed.foreigners),
            "foreign_country_options": len(parsed.foreigners_summary.country_options),
            "chart_matchdays": list(parsed.chart_matchdays),
            "affiliation_conflicts": len(parsed.affiliation_conflicts),
        },
        "category_counts": dict(category_counts),
        "issues": issues,
        "warnings": list(dict.fromkeys(warnings)),
    }
