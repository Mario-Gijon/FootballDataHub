"""Offline source-quality audits used by the player discovery milestone."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

_SCORE = re.compile(r"^(\d+)\s+(\d+)$")
_CORE_MATCH_FIELDS = (
    "group", "round", "date", "date_raw", "home_team_name", "away_team_name",
    "home_team_season_id", "away_team_season_id", "home_goals", "away_goals",
    "result_raw", "match_url", "match_link_status", "stadium_id", "stadium_name",
    "referee_id", "referee_name",
)


def _read_json(path: Path) -> Any:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def _raw_integrity(source: dict[str, Any]) -> dict[str, Any]:
    raw_directory = Path(str(source.get("path") or ""))
    html_path = raw_directory / "rendered.html"
    metadata_path = raw_directory / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
    actual = hashlib.sha256(html_path.read_bytes()).hexdigest() if html_path.is_file() else None
    return {
        "source_path": raw_directory.as_posix(),
        "requested_url": source.get("requested_url"),
        "final_url": source.get("final_url"),
        "captured_at_utc": source.get("captured_at_utc"),
        "access_status": source.get("access_status"),
        "http_status": source.get("http_status"),
        "snapshot_sha256_metadata": source.get("snapshot_sha256"),
        "snapshot_sha256_actual": actual,
        "raw_hash_matches": bool(actual and actual == source.get("snapshot_sha256")),
        "metadata_hash_matches_raw": bool(actual and actual == metadata.get("rendered_html_sha256")),
        "raw_html_present": html_path.is_file(),
    }


def _canonical_result_status(item: dict[str, Any]) -> str:
    """Normalize versioned result-status vocabularies only with score evidence."""
    result_raw = str(item.get("result_raw") or "").strip()
    score = _SCORE.fullmatch(result_raw)
    numeric_goals = isinstance(item.get("home_goals"), int) and isinstance(item.get("away_goals"), int)
    has_id = item.get("match_id") is not None
    result_status = str(item.get("result_status") or "").casefold()
    fixture_status = str(item.get("fixture_status") or "").casefold()
    if has_id and score and numeric_goals and (
        result_status == "played" or fixture_status == "played" or result_status == "available"
    ):
        return "PLAYED"
    if fixture_status == "scheduled" or result_status in {"scheduled", "not_available"} or result_raw in {"—", "-", ""}:
        return "SCHEDULED_OR_UNSCORED"
    return "UNRESOLVED"


def _candidate_summary(export_directory: Path, metadata_path: Path) -> dict[str, Any]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    groups = []
    fixtures: list[dict[str, Any]] = []
    quality_checks = []
    for group, suffix in (("I", "i"), ("II", "ii")):
        payload_path = export_directory / f"matches_group_{suffix}.json"
        if not payload_path.exists():
            payload_path = payload_path.with_name(f"{payload_path.name}.gz")
        payload = _read_json(payload_path) if payload_path.exists() else {}
        items = payload.get("items", [])
        source = payload.get("source_snapshots", {}).get(group) or metadata.get("source_snapshots", {}).get(group) or {}
        integrity = _raw_integrity(source) if source else {"raw_hash_matches": False, "metadata_hash_matches_raw": False}
        statuses = Counter(_canonical_result_status(item) for item in items)
        non_null_ids = [str(item["match_id"]) for item in items if item.get("match_id") is not None]
        duplicate_ids = sorted(match_id for match_id, count in Counter(non_null_ids).items() if count > 1)
        score_without_id = sum(
            bool(_SCORE.fullmatch(str(item.get("result_raw") or ""))) and item.get("match_id") is None
            for item in items
        )
        groups.append({
            "group": group,
            "fixture_count": len(items),
            "expected_fixture_count": 380,
            "fixture_count_valid": len(items) == 380,
            "canonical_status_counts": dict(statuses),
            "match_id_count": len(non_null_ids),
            "unique_match_id_count": len(set(non_null_ids)),
            "duplicate_match_ids": duplicate_ids,
            "score_without_match_id_count": score_without_id,
            "source": integrity,
            "status_vocabulary": dict(Counter(str(item.get("result_status")) for item in items)),
            "fixture_status_vocabulary": dict(Counter(str(item.get("fixture_status")) for item in items)),
        })
        quality_checks.append(
            len(items) == 380
            and not duplicate_ids
            and score_without_id == 0
            and statuses.get("UNRESOLVED", 0) == 0
            and integrity.get("access_status") == "VALID"
            and integrity.get("http_status") == 200
            and integrity.get("raw_hash_matches") is True
            and integrity.get("metadata_hash_matches_raw") is True
        )
        fixtures.extend({**item, "_export_group": group} for item in items)
    non_null = [item for item in fixtures if item.get("match_id") is not None]
    return {
        "extraction_key": metadata.get("extraction_key"),
        "export_directory": export_directory.as_posix(),
        "parser_version": metadata.get("parser_version"),
        "schema_version": metadata.get("schema_version"),
        "source_capture_timestamps_utc": {
            group: (metadata.get("source_snapshots", {}).get(group) or {}).get("captured_at_utc")
            for group in ("I", "II")
        },
        "groups": groups,
        "fixture_count_total": len(fixtures),
        "canonical_played_count": sum(_canonical_result_status(item) == "PLAYED" for item in fixtures),
        "match_id_count": len(non_null),
        "unique_match_id_count": len({str(item["match_id"]) for item in non_null}),
        "quality_valid": len(groups) == 2 and all(quality_checks),
        "fixtures": fixtures,
    }


def audit_competition_exports(
    competition_root: Path,
    *,
    retained_extraction_key: str | None = None,
) -> dict[str, Any]:
    """Compare local Hito 1B exports using explicit integrity and content checks."""
    candidates = []
    for metadata_path in sorted(competition_root.glob("snapshot-*/dataset_metadata.json")):
        candidates.append(_candidate_summary(metadata_path.parent, metadata_path))
    by_key = {str(item.get("extraction_key")): item for item in candidates}
    comparison: dict[str, Any] = {
        "candidate_count": len(candidates),
        "selection_criteria": [
            "ambos grupos presentes y con 380 filas cada uno",
            "snapshot fuente VALID/HTTP 200 y SHA raw igual a metadata y export",
            "IDs de partido únicos, score crudo y goles numéricos coherentes",
            "resultado normalizado desde evidence fields, no por una sola etiqueta de estado",
            "coincidencia de contenido por ID entre extracciones y marcas temporales/procedencia",
        ],
        "candidates": [{key: value for key, value in item.items() if key != "fixtures"} for item in candidates],
        "cross_candidate_comparison": None,
        "retained_extraction_key": retained_extraction_key,
        "selection_reason": None,
    }
    if len(candidates) >= 2:
        left = candidates[0]
        right = candidates[1]
        left_index = {str(item["match_id"]): item for item in left["fixtures"] if item.get("match_id") is not None}
        right_index = {str(item["match_id"]): item for item in right["fixtures"] if item.get("match_id") is not None}
        common = left_index.keys() & right_index.keys()
        differences = []
        for match_id in sorted(common):
            for field in _CORE_MATCH_FIELDS:
                if left_index[match_id].get(field) != right_index[match_id].get(field):
                    differences.append({
                        "match_id": match_id,
                        "field": field,
                        "left": left_index[match_id].get(field),
                        "right": right_index[match_id].get(field),
                    })
        all_ids_equal = left_index.keys() == right_index.keys()
        statuses_left = Counter(str(item.get("result_status")) for item in left["fixtures"])
        statuses_right = Counter(str(item.get("result_status")) for item in right["fixtures"])
        fixture_statuses_right = Counter(str(item.get("fixture_status")) for item in right["fixtures"])
        comparison["cross_candidate_comparison"] = {
            "extraction_keys": [left["extraction_key"], right["extraction_key"]],
            "match_id_sets_equal": all_ids_equal,
            "common_match_ids": len(common),
            "core_field_difference_count": len(differences),
            "core_field_differences": differences[:100],
            "canonical_played_counts": [left["canonical_played_count"], right["canonical_played_count"]],
            "left_result_status_vocabulary": dict(statuses_left),
            "right_result_status_vocabulary": dict(statuses_right),
            "right_fixture_status_vocabulary": dict(fixture_statuses_right),
        }
    selected = by_key.get(retained_extraction_key or "")
    if selected and selected.get("quality_valid"):
        comparison["selection_reason"] = (
            "Se conserva la extracción enlazada explícitamente en el export B2 para preservar su procedencia. "
            "Los candidatos se comparan con estados normalizados e integridad raw; el número bruto de etiquetas "
            "result_status=played no determina la selección."
        )
    return comparison


def audit_caceres_scope(
    team_matches_snapshot: Path,
    club_matches_snapshot: Path,
    b2_sports_export: Path,
) -> dict[str, Any]:
    """Explain the local Cacereño PJ=8 vs 1ª RFEF six-match scope difference."""
    from bs4 import BeautifulSoup

    def read_valid_snapshot(directory: Path) -> tuple[dict[str, Any], BeautifulSoup, str]:
        metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        html = (directory / "rendered.html").read_text(encoding="utf-8")
        actual = hashlib.sha256(html.encode("utf-8")).hexdigest()
        if metadata.get("access_status") != "VALID" or metadata.get("http_status") != 200:
            raise ValueError(f"Snapshot fuente no válido: {directory}")
        if actual != metadata.get("rendered_html_sha256"):
            raise ValueError(f"Hash del snapshot no coincide: {directory}")
        return metadata, BeautifulSoup(html, "lxml"), actual

    team_metadata, team_soup, team_sha = read_valid_snapshot(team_matches_snapshot)
    club_metadata, club_soup, club_sha = read_valid_snapshot(club_matches_snapshot)
    results_table = team_soup.find("table", id="taula-resultats-plantilla")
    team_rows = []
    if results_table:
        for index, row in enumerate(results_table.find_all("tr")):
            if row.find_parent("table") is not results_table:
                continue
            cells = row.find_all(["th", "td"], recursive=False)
            values = [" ".join(cell.get_text(" ", strip=True).split()) for cell in cells]
            if index == 0 or len(values) < 8:
                continue
            score = next((value for value in values if _SCORE.fullmatch(value)), "")
            if not score:
                continue
            links = [anchor.get("href") for anchor in row.find_all("a", href=True)]
            match_url = next((url for url in links if "/p/p.php?id=" in url), None)
            match_id = parse_qs(urlsplit(match_url).query).get("id", [None])[-1] if match_url else None
            team_rows.append({
                "date_raw": values[0],
                "competition_raw": values[1],
                "round_raw": values[2],
                "home_team_raw": values[3],
                "score_raw": score,
                "away_team_raw": values[7],
                "match_id": match_id,
                "match_url": match_url,
                "source_row_index": index,
            })

    club_export = _read_json(b2_sports_export)
    coverage_rows = club_export.get("items", [])
    caceres_coverage = next((row for row in coverage_rows if row.get("club_id") == "e149"), {})
    variant_ids = sorted({
        str(match_id)
        for match_id in caceres_coverage.get("competition_match_ids_observed", [])
        if match_id
    })

    aggregate = None
    for table in club_export.get("items", []):
        if table.get("club_id") == "e149":
            aggregate = table.get("aggregate_expected")
            break

    raw_aggregate = None
    aggregate_table = club_soup.find("table", id="t1")
    if aggregate_table:
        rows = aggregate_table.find_all("tr")
        headers = [
            " ".join(cell.get_text(" ", strip=True).split())
            for cell in rows[0].find_all(["th", "td"], recursive=False)
        ] if rows else []
        for row in rows[1:]:
            values = [
                " ".join(cell.get_text(" ", strip=True).split())
                for cell in row.find_all(["th", "td"], recursive=False)
            ]
            if values and values[0] == "2026-27" and len(values) == len(headers):
                raw_aggregate = dict(zip(headers, values, strict=True))
                break
    raw_aggregate_matches_export = bool(raw_aggregate and aggregate) and all(
        raw_aggregate.get(field, "").isdigit()
        and int(raw_aggregate[field]) == aggregate.get(field)
        for field in ("PJ", "PG", "PE", "PP", "GF", "GC")
    )

    league_rows = [row for row in team_rows if row["competition_raw"].casefold() == "liga"]
    cup_rows = [row for row in team_rows if row["competition_raw"].casefold() == "copa federación"]
    explanation_supported = (
        len(team_rows) == 8
        and len(league_rows) == 6
        and len(cup_rows) == 2
        and aggregate and aggregate.get("PJ") == 8
        and raw_aggregate and raw_aggregate.get("PJ") == "8"
        and raw_aggregate_matches_export
        and len(variant_ids) == 6
    )
    return {
        "club_id": "e149",
        "team_season_id": "t2026-27149",
        "club_match_aggregate": aggregate,
        "raw_club_match_aggregate": raw_aggregate,
        "raw_aggregate_matches_b2_export": raw_aggregate_matches_export,
        "team_match_table": "taula-resultats-plantilla",
        "team_match_table_rows_played": team_rows,
        "team_match_table_rows_played_count": len(team_rows),
        "league_rows_count": len(league_rows),
        "cup_federation_rows_count": len(cup_rows),
        "cup_federation_rows": cup_rows,
        "b2_cat_1rf_match_ids": variant_ids,
        "league_match_ids_equal_to_b2_variant": sorted(
            str(row["match_id"]) for row in league_rows if row.get("match_id")
        ) == variant_ids,
        "status": "SCOPE_EXPLAINED_BY_TWO_COPA_FEDERACION_MATCHES" if explanation_supported else "SCOPE_DIFFERENCE_UNRESOLVED",
        "raw_sources": [
            {
                "snapshot_directory": team_matches_snapshot.as_posix(),
                "url": team_metadata.get("final_url"),
                "captured_at_utc": team_metadata.get("captured_at_utc"),
                "sha256": team_sha,
            },
            {
                "snapshot_directory": club_matches_snapshot.as_posix(),
                "url": club_metadata.get("final_url"),
                "captured_at_utc": club_metadata.get("captured_at_utc"),
                "sha256": club_sha,
            },
        ],
        "explanation": (
            "La tabla de temporada muestra 8 partidos jugados: 6 de Liga y 2 de Copa Federación. "
            "La variante de club con cat=1rf contiene los seis partidos de Liga; su filtro acota competición, "
            "aunque pgep esté ausente y por tanto incluya todos los resultados dentro de esa competición."
            if explanation_supported else None
        ),
        "coverage_record_status": caceres_coverage.get("status"),
    }
