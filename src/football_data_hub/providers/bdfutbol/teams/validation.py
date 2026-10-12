"""Structural and cross-dataset checks for team-profile captures."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
import re
from typing import Any

from .models import TeamProfileData

SEMANTIC_VALIDATION_VERSION = 2


def validate_team_catalogs(
    catalogs: dict[int, tuple[list[dict[str, Any]], dict[str, Any]]],
    *,
    season: str,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    warnings: list[str] = []
    all_ids: list[int] = []
    group_summaries: dict[str, int] = {}
    for group, (teams, reference) in sorted(catalogs.items()):
        expected_group = "I" if group == 1 else "II"
        if len(teams) != 20:
            issues.append({"code": "team_catalog_count", "message": f"Grupo {expected_group}: se esperaban 20 equipos, encontrados {len(teams)}."})
        ids = [int(record["team_id"]) for record in teams]
        if len(ids) != len(set(ids)):
            issues.append({"code": "duplicate_team_id", "message": f"Grupo {expected_group}: team_id repetido."})
        for record in teams:
            team_id = int(record["team_id"])
            url = str(record.get("team_url") or "")
            if not record.get("name") or not url or not record.get("crest_url"):
                warnings.append(f"team_id={team_id}: el catálogo tiene un campo institucional ausente")
            from .parser import team_id_from_url

            if team_id_from_url(url) != team_id:
                issues.append({"code": "catalog_url_id", "message": f"Grupo {expected_group}: team_url no coincide con team_id={team_id}."})
            if record.get("team_id") is None:
                issues.append({"code": "catalog_missing_team_id", "message": f"Grupo {expected_group}: falta team_id."})
        if reference.get("season") not in {None, season}:
            issues.append({"code": "catalog_season", "message": f"Grupo {expected_group}: catálogo de otra temporada."})
        if reference.get("group") not in {None, expected_group}:
            issues.append({"code": "catalog_group", "message": f"Catálogo indicado como Grupo {reference.get('group')}, se esperaba {expected_group}."})
        all_ids.extend(ids)
        group_summaries[expected_group] = len(ids)
    duplicates = sorted(team_id for team_id, count in Counter(all_ids).items() if count > 1)
    if duplicates:
        issues.append({"code": "cross_group_team_id_collision", "message": f"IDs repetidos entre grupos: {duplicates}."})
    return {
        "valid": not issues,
        "summary": {"season": season, "teams_total": len(all_ids), "teams_by_group": group_summaries, "unique_team_ids": len(set(all_ids))},
        "issues": issues,
        "warnings": warnings,
        "team_ids_by_group": {
            ("I" if group == 1 else "II"): sorted(int(item["team_id"]) for item in teams)
            for group, (teams, _) in sorted(catalogs.items())
        },
    }


def validate_team_profile(
    data: TeamProfileData,
    *,
    catalog_record: dict[str, Any],
    group_team_catalog: list[dict[str, Any]],
    known_matches: list[dict[str, Any]],
    requested_views: tuple[str, ...],
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    warnings = list(data.warnings)
    team_id = int(catalog_record["team_id"])
    if data.identity.team_id != team_id or data.season.team_id != team_id:
        issues.append({"code": "team_identity", "message": "El team_id normalizado no coincide con el catálogo."})
    for key in ("name", "team_url", "crest_url"):
        if getattr(data.identity, key) != catalog_record.get(key):
            issues.append({"code": "catalog_identity_mismatch", "message": f"El campo {key} no conserva el valor del catálogo."})
    if data.season.season not in {"2026-27"} or data.season.competition_scope != "Liga":
        issues.append({"code": "season_scope", "message": "La ficha no corresponde al alcance Liga 2026/27."})

    player_ids = [item.player_id for item in data.players]
    if not player_ids or len(player_ids) != len(set(player_ids)):
        issues.append({"code": "player_identity", "message": "No hay jugadores identificables o hay player_id duplicados."})
    player_id_set = set(player_ids)
    membership_ids = [item.player_id for item in data.memberships]
    if len(membership_ids) != len(set(membership_ids)):
        issues.append({"code": "membership_duplicate", "message": "Hay más de una pertenencia para un mismo jugador y equipo-temporada."})
    if set(membership_ids) - player_id_set:
        issues.append({"code": "orphan_membership", "message": "Hay pertenencias sin identidad de jugador."})
    if any(item.team_id != team_id or item.season != data.season.season for item in data.memberships):
        issues.append({"code": "membership_scope", "message": "Una pertenencia usa otro equipo o temporada."})

    statistic_ids = [item.player_id for item in data.player_statistics]
    if len(statistic_ids) != len(set(statistic_ids)) or set(statistic_ids) - player_id_set:
        issues.append({"code": "statistics_identity", "message": "Las estadísticas repiten o no identifican jugadores de las vistas de plantilla."})
    for item in data.player_statistics:
        if item.team_id != team_id or item.season != data.season.season or item.group != data.season.group:
            issues.append({"code": "statistics_scope", "message": f"Estadística fuera del ámbito para player_id={item.player_id}."})
        numeric = [value for key, value in asdict(item).items() if key not in {"player_id", "team_id", "season", "competition", "group", "source_view"}]
        if any(value is not None and value < 0 for value in numeric):
            issues.append({"code": "negative_player_stat", "message": f"Estadística negativa para player_id={item.player_id}."})

    match_ids = {str(item.get("match_id")) for item in known_matches if item.get("match_id") is not None}
    profile_match_ids = set(data.team_match_ids_from_profile)
    if len(profile_match_ids) != len(data.team_match_ids_from_profile):
        issues.append({"code": "duplicate_profile_match", "message": "La vista Partidos repite un match_id."})
    unknown_match_ids = sorted(profile_match_ids - match_ids)
    if unknown_match_ids:
        issues.append({"code": "unknown_profile_match", "message": f"La vista Partidos refiere encuentros no presentes en el catálogo: {unknown_match_ids[:10]}."})
    follow_ids = {item.match_id for item in data.player_match_minutes}
    unknown_follow_ids = sorted(follow_ids - match_ids)
    if unknown_follow_ids:
        issues.append({"code": "unknown_follow_match", "message": f"Seguimiento refiere encuentros sin match_id del grupo: {unknown_follow_ids[:10]}."})
    if any(item.player_id not in player_id_set for item in data.player_match_minutes):
        issues.append({"code": "orphan_follow_player", "message": "Seguimiento refiere un jugador no identificado en las vistas de plantilla."})
    if any(item.value is not None and item.value < 0 for item in data.player_match_minutes):
        issues.append({"code": "negative_match_minutes", "message": "Seguimiento contiene minutos negativos."})

    metric_keys = [(item.player_id, item.match_id, item.metric) for item in data.player_match_metrics]
    if len(metric_keys) != len(set(metric_keys)):
        issues.append({"code": "duplicate_follow_metric", "message": "Seguimiento repite jugador, partido y métrica."})
    metric_match_ids = {item.match_id for item in data.player_match_metrics}
    if metric_match_ids - match_ids:
        issues.append({"code": "unknown_follow_metric_match", "message": "Una métrica de Seguimiento refiere un match_id ajeno al catálogo."})
    if any(item.player_id not in player_id_set for item in data.player_match_metrics):
        issues.append({"code": "orphan_follow_metric_player", "message": "Una métrica de Seguimiento refiere un jugador sin identidad."})
    for item in data.player_match_metrics:
        if item.team_id != team_id or item.season != data.season.season or item.group != data.season.group:
            issues.append({"code": "follow_metric_scope", "message": f"Métrica fuera del ámbito para player_id={item.player_id}."})
        if item.value < 0:
            issues.append({"code": "negative_follow_metric", "message": f"Métrica negativa para player_id={item.player_id}."})
        if (item.metric, item.source_state) not in {
            ("yellow_cards", "t"),
            ("red_cards", "t"),
            ("goals", "go"),
        }:
            issues.append({"code": "follow_metric_state", "message": f"Estado {item.source_state} no respalda {item.metric}."})
    follow_metric_totals = Counter()
    for item in data.player_match_metrics:
        follow_metric_totals[item.metric] += item.value
    source_metric_totals = {
        "yellow_cards": sum(item.yellow_cards or 0 for item in data.player_statistics),
        "red_cards": sum(item.red_cards or 0 for item in data.player_statistics),
        "goals": sum(item.goals or 0 for item in data.player_statistics),
    }
    for metric in ("yellow_cards", "red_cards", "goals"):
        state = "go" if metric == "goals" else "t"
        if state in data.follow_states_captured and follow_metric_totals[metric] != source_metric_totals[metric]:
            warnings.append(
                f"Seguimiento estado {state}: suma observada de {metric}={follow_metric_totals[metric]} "
                f"frente a Estadísticas={source_metric_totals[metric]}; se conservan ambas fuentes."
            )

    if "t" in data.follow_states_captured:
        observed_cards: dict[tuple[int, str], int] = defaultdict(int)
        for item in data.player_match_metrics:
            if item.source_state == "t" and item.metric in {"yellow_cards", "red_cards"}:
                observed_cards[(item.player_id, item.metric)] += item.value
        for stat in data.player_statistics:
            for metric, source_value in (
                ("yellow_cards", stat.yellow_cards),
                ("red_cards", stat.red_cards),
            ):
                if source_value is not None and observed_cards[(stat.player_id, metric)] != source_value:
                    issues.append({
                        "code": "follow_card_statistics_mismatch",
                        "message": (
                            f"Seguimiento {metric} no coincide con Estadísticas para "
                            f"player_id={stat.player_id}: {observed_cards[(stat.player_id, metric)]} "
                            f"frente a {source_value}."
                        ),
                    })

    expected_team_ids = {int(item["team_id"]) for item in group_team_catalog}
    profile_team_ids = set(data.group_team_ids_from_profile)
    if "alignment" in requested_views and expected_team_ids != profile_team_ids:
        issues.append({"code": "group_team_catalog_mismatch", "message": "La lista de equipos de #classific no coincide con el catálogo del grupo."})

    minute_totals: dict[int, int] = defaultdict(int)
    minute_record_counts: Counter[int] = Counter()
    for item in data.player_match_minutes:
        minute_record_counts[item.player_id] += 1
        if item.value is not None:
            minute_totals[item.player_id] += item.value
    matchday_count = len({item.matchday for item in data.player_match_minutes})
    for stat in data.player_statistics:
        if matchday_count and minute_record_counts[stat.player_id] == matchday_count and stat.minutes_played is not None:
            if minute_totals[stat.player_id] != stat.minutes_played:
                warnings.append(
                    f"player_id={stat.player_id}: minutos por jornada suman "
                    f"{minute_totals[stat.player_id]} frente a {stat.minutes_played} en Estadísticas; "
                    "se conservan ambos valores de origen"
                )
    if "matches" in requested_views and profile_match_ids:
        warnings.append(
            "Los match_id de la ficha se usan como referencias al dataset existente; "
            "no se exportan copias de partidos"
        )

    if "transfers" in requested_views:
        from urllib.parse import urlsplit

        from .parser import team_id_from_url

        sections_by_direction = {item.direction: item for item in data.transfer_sections}
        if len(data.transfer_sections) != 2 or set(sections_by_direction) != {"incoming", "outgoing"}:
            issues.append({"code": "transfer_sections", "message": "No se ha demostrado por separado Altas y Bajas."})
        transfer_keys = [(item.direction, item.player_id) for item in data.transfers]
        if len(transfer_keys) != len(set(transfer_keys)):
            issues.append({"code": "transfer_duplicate", "message": "Hay IDs de jugador duplicados dentro de la misma dirección."})
        counts = Counter(item.direction for item in data.transfers)
        expected_headings = {"incoming": "Altas", "outgoing": "Bajas"}
        expected_columns = {"incoming": "Equipo origen", "outgoing": "Equipo destino"}
        for direction in ("incoming", "outgoing"):
            section = sections_by_direction.get(direction)
            if section is None:
                continue
            expected_status = "verified_with_rows" if section.row_count else "verified_empty"
            if (
                section.source_heading != expected_headings[direction]
                or section.source_team_column != expected_columns[direction]
                or section.status != expected_status
                or section.row_count != counts[direction]
            ):
                issues.append({"code": "transfer_section_mismatch", "message": f"Estado o recuento incoherente para {expected_headings[direction]}."})
        for item in data.transfers:
            if (
                item.team_id != team_id
                or item.season != data.season.season
                or item.group != data.season.group
                or item.competition != data.season.competition
            ):
                issues.append({"code": "transfer_scope", "message": f"Movimiento fuera de ámbito para player_id={item.player_id}."})
            if item.direction not in expected_headings or item.source_heading != expected_headings.get(item.direction):
                issues.append({"code": "transfer_direction_heading", "message": f"Dirección y encabezado no coinciden para player_id={item.player_id}."})
            player_match = re.search(r"(?:^|/)j/j(\d+)\.html$", urlsplit(item.player_profile_url).path)
            if item.player_id <= 0 or not item.player_display_name or not player_match or int(player_match.group(1)) != item.player_id:
                issues.append({"code": "transfer_player_identity", "message": f"Identidad de jugador incoherente para player_id={item.player_id}."})
            for field_name, value in (("player_profile_url", item.player_profile_url), ("player_photo_url", item.player_photo_url), ("other_team_url", item.other_team_url)):
                if value is None:
                    continue
                parsed_url = urlsplit(value)
                if parsed_url.scheme != "https" or parsed_url.hostname not in {"bdfutbol.com", "www.bdfutbol.com"}:
                    issues.append({"code": "transfer_url", "message": f"{field_name} no es una URL de BDFutbol para player_id={item.player_id}."})
            if item.other_team_url and team_id_from_url(item.other_team_url) != item.other_team_id:
                issues.append({"code": "transfer_related_team", "message": f"ID y URL del otro equipo no coinciden para player_id={item.player_id}."})
            if item.other_team_id is not None and not item.other_team_url:
                issues.append({"code": "transfer_related_team_url", "message": f"Falta URL para other_team_id={item.other_team_id}."})
    return {
        "valid": not issues,
        "semantic_version": SEMANTIC_VALIDATION_VERSION,
        "summary": {
            "team_id": team_id,
            "players": len(data.players),
            "memberships": len(data.memberships),
            "coaches": len(data.season.coaches),
            "player_statistics": len(data.player_statistics),
            "player_match_minutes": len(data.player_match_minutes),
            "player_match_metrics": len(data.player_match_metrics),
            "follow_states_captured": list(data.follow_states_captured),
            "transfers": len(data.transfers),
            "transfer_sections": {item.direction: {"status": item.status, "rows": item.row_count} for item in data.transfer_sections},
            "profile_match_references": len(profile_match_ids),
            "catalog_teams_in_profile": len(profile_team_ids),
            "requested_views": list(requested_views),
        },
        "issues": issues,
        "warnings": list(dict.fromkeys(warnings)),
        "cross_references": {
            "team_ids_match_catalog": expected_team_ids == profile_team_ids if "alignment" in requested_views else None,
            "profile_match_ids_in_group_results": not unknown_match_ids if "matches" in requested_views else None,
            "follow_match_ids_in_group_results": not unknown_follow_ids if "follow" in requested_views else None,
            "follow_metric_match_ids_in_group_results": not (metric_match_ids - match_ids) if data.player_match_metrics else None,
            "duplicate_match_records_exported": False,
        },
    }
