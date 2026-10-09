"""Captura y carga validada de snapshots de las páginas de competición."""

from __future__ import annotations

import hashlib
import gzip
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from football_data_hub.providers.bdfutbol.competition import COMPETITION_URLS


class InvalidCompetitionSnapshot(ValueError):
    """El directorio no contiene un snapshot íntegro y validado."""


class InvalidCompetitionExport(ValueError):
    """El export local no cumple integridad, esquema o calidad mínima."""


@dataclass(frozen=True, slots=True)
class CompetitionSnapshot:
    group: str
    directory: Path
    html: str
    metadata: dict[str, Any]
    sha256: str


class CompetitionAccessStopped(RuntimeError):
    """La navegación de competición terminó sin acceso semántico válido."""

    def __init__(self, group: str, assessment: Any) -> None:
        self.group = group
        self.assessment = assessment
        super().__init__(f"Grupo {group}: acceso detenido con estado {assessment.status.value}")


def _timestamp_order(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _read_json(path: Path) -> dict[str, Any]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise InvalidCompetitionExport(f"Se esperaba un objeto JSON: {path}")
    return value


def _validate_competition_export(metadata_path: Path) -> dict[str, Any]:
    from football_data_hub.parsers.match_status import assess_match_status

    export_directory = metadata_path.parent
    metadata = _read_json(metadata_path)
    extraction_key = metadata.get("extraction_key")
    if not isinstance(extraction_key, str) or not extraction_key:
        raise InvalidCompetitionExport(f"Falta extraction_key en {metadata_path}")
    if not export_directory.name.startswith(f"snapshot-{extraction_key}-parser-"):
        raise InvalidCompetitionExport(f"La ruta no corresponde a extraction_key en {metadata_path}")
    if metadata.get("schema_version") != "football_data_hub.competition_export.v1":
        raise InvalidCompetitionExport(f"Schema no compatible en {metadata_path}")
    if metadata.get("season") != "2026/27" or not metadata.get("parser_version"):
        raise InvalidCompetitionExport(f"Temporada o versión de parser incompatible en {metadata_path}")

    source_snapshots = metadata.get("source_snapshots")
    if not isinstance(source_snapshots, dict):
        raise InvalidCompetitionExport(f"Falta source_snapshots en {metadata_path}")
    group_items: dict[str, list[dict[str, Any]]] = {}
    source_details: dict[str, dict[str, Any]] = {}
    status_counts: dict[str, dict[str, int]] = {}
    all_ids: list[str] = []
    for group in ("I", "II"):
        source = source_snapshots.get(group)
        if not isinstance(source, dict):
            raise InvalidCompetitionExport(f"Falta snapshot del Grupo {group}: {metadata_path}")
        if (
            source.get("access_status") != "VALID"
            or source.get("http_status") != 200
            or source.get("requested_url") != COMPETITION_URLS[group]
            or source.get("final_url") != COMPETITION_URLS[group]
            or not source.get("snapshot_sha256")
            or _timestamp_order(source.get("captured_at_utc")) is None
        ):
            raise InvalidCompetitionExport(f"Procedencia inválida del Grupo {group}: {metadata_path}")
        raw_directory = Path(str(source.get("path") or "")).expanduser()
        if not raw_directory.is_absolute():
            raw_directory = (Path.cwd() / raw_directory).resolve()
        raw_html_path = raw_directory / "rendered.html"
        raw_metadata_path = raw_directory / "metadata.json"
        if not raw_html_path.is_file() or not raw_metadata_path.is_file():
            raise InvalidCompetitionExport(f"Raw ausente para Grupo {group}: {raw_directory}")
        raw_metadata = _read_json(raw_metadata_path)
        raw_sha = hashlib.sha256(raw_html_path.read_bytes()).hexdigest()
        if (
            raw_sha != source.get("snapshot_sha256")
            or raw_sha != raw_metadata.get("rendered_html_sha256")
            or raw_metadata.get("access_status") != "VALID"
            or raw_metadata.get("http_status") != 200
            or raw_metadata.get("requested_url") != COMPETITION_URLS[group]
            or raw_metadata.get("final_url") != COMPETITION_URLS[group]
            or raw_metadata.get("captured_at_utc") != source.get("captured_at_utc")
        ):
            raise InvalidCompetitionExport(f"Integridad raw fallida para Grupo {group}: {raw_directory}")

        suffix = group.lower()
        plain_path = export_directory / f"matches_group_{suffix}.json"
        compressed_path = plain_path.with_name(f"{plain_path.name}.gz")
        data_path = plain_path if plain_path.is_file() else compressed_path
        if not data_path.is_file():
            raise InvalidCompetitionExport(f"Falta matches_group_{suffix}.json[.gz] en {export_directory}")
        payload = _read_json(data_path)
        if (
            payload.get("schema_version") != metadata["schema_version"]
            or payload.get("parser_version") != metadata["parser_version"]
            or payload.get("extraction_key") != extraction_key
            or payload.get("season") != metadata["season"]
            or payload.get("group") != group
        ):
            raise InvalidCompetitionExport(f"Metadata de Grupo {group} incompatible en {data_path}")
        payload_sources = payload.get("source_snapshots")
        payload_source = payload_sources.get(group) if isinstance(payload_sources, dict) else None
        if not isinstance(payload_source, dict) or any(
            payload_source.get(field) != source.get(field)
            for field in ("path", "snapshot_sha256", "captured_at_utc", "requested_url", "final_url")
        ):
            raise InvalidCompetitionExport(f"Procedencia de export/raw no coincide para Grupo {group}")
        items = payload.get("items")
        if not isinstance(items, list) or len(items) != 380:
            raise InvalidCompetitionExport(f"El Grupo {group} no tiene exactamente 380 fixtures")

        enriched = []
        states: dict[str, int] = {"played": 0, "scheduled": 0, "unresolved": 0, "inconsistent": 0}
        group_ids = []
        for item in items:
            if not isinstance(item, dict) or item.get("group") != group:
                raise InvalidCompetitionExport(f"Fixture de otro grupo o inválido en {data_path}")
            assessment = assess_match_status(item, captured_at_utc=source["captured_at_utc"])
            state = str(assessment["state"])
            states[state] += 1
            match_id = item.get("match_id")
            if match_id is not None and str(match_id).strip():
                group_ids.append(str(match_id))
                all_ids.append(str(match_id))
            enriched.append({
                **item,
                "fixture_status": state,
                "match_state": state,
                "match_state_issues": assessment["issues"],
                "match_state_evidence": assessment["evidence"],
                "_captured_at_utc": source["captured_at_utc"],
                "_snapshot_sha256": source["snapshot_sha256"],
                "_competition_extraction_key": extraction_key,
                "_competition_export_schema_version": metadata["schema_version"],
                "_competition_parser_version": metadata["parser_version"],
                "_competition_snapshot_directory": raw_directory.as_posix(),
                "_competition_source_validated": True,
                "_competition_code_raw": "1rf",
            })
        if len(group_ids) != len(set(group_ids)):
            raise InvalidCompetitionExport(f"IDs de partido duplicados en Grupo {group}: {data_path}")
        if states["inconsistent"]:
            raise InvalidCompetitionExport(
                f"El Grupo {group} contiene {states['inconsistent']} fixtures inconsistentes"
            )
        group_items[group] = enriched
        status_counts[group] = states
        source_details[group] = {
            "url": source["final_url"],
            "captured_at_utc": source["captured_at_utc"],
            "snapshot_sha256": source["snapshot_sha256"],
            "snapshot_directory": raw_directory.as_posix(),
            "fixture_count": len(items),
        }
    if len(all_ids) != len(set(all_ids)):
        raise InvalidCompetitionExport("IDs de partido duplicados entre grupos")

    return {
        "metadata": metadata,
        "export_directory": export_directory.resolve().as_posix(),
        "extraction_key": extraction_key,
        "groups": group_items,
        "source_details": source_details,
        "status_counts": status_counts,
        "captured_at_order": min(
            _timestamp_order(item["captured_at_utc"]) for item in source_details.values()
        ),
    }


_CROSS_EXTRACTION_FIELDS = (
    "match_id", "group", "season", "date", "round", "home_team_season_id", "away_team_season_id",
    "home_team_name", "away_team_name", "home_goals", "away_goals", "referee_id", "stadium_id",
)


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    timestamps = [
        _timestamp_order(value.get("captured_at_utc"))
        for value in candidate["source_details"].values()
    ]
    valid_timestamps = [value for value in timestamps if value is not None]
    return {
        "extraction_key": candidate["extraction_key"],
        "export_directory": candidate["export_directory"],
        "schema_version": candidate["metadata"].get("schema_version"),
        "parser_version": candidate["metadata"].get("parser_version"),
        "season": candidate["metadata"].get("season"),
        "fixtures_loaded": sum(len(items) for items in candidate["groups"].values()),
        "status_counts": candidate["status_counts"],
        "group_capture_timestamps_utc": {
            group: value.get("captured_at_utc")
            for group, value in candidate["source_details"].items()
        },
        "group_capture_span_seconds": (
            round(max(valid_timestamps) - min(valid_timestamps), 3)
            if len(valid_timestamps) > 1 else 0.0
        ),
        "sources": candidate["source_details"],
    }


def _semantic_conflicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Compare all fixtures, including scheduled rows without a published match ID."""

    def identity(item: dict[str, Any]) -> tuple[str, ...] | None:
        group = str(item.get("group") or "").strip()
        season = str(item.get("season") or "").replace("-", "/").strip()
        home_id = str(item.get("home_team_season_id") or "").strip()
        away_id = str(item.get("away_team_season_id") or "").strip()
        if group and season and home_id and away_id:
            # These stable sides identify a league fixture even when its match ID
            # has not been published. Round and date remain compared fields.
            return ("fixture", group, season, home_id, away_id)
        match_id = str(item.get("match_id") or "").strip()
        if match_id:
            return ("match_id", match_id)
        return None

    def index(candidate: dict[str, Any]) -> tuple[dict[tuple[str, ...], list[dict[str, Any]]], int]:
        rows: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        unidentifiable = 0
        for items in candidate["groups"].values():
            for item in items:
                key = identity(item)
                if key is None:
                    unidentifiable += 1
                else:
                    rows.setdefault(key, []).append(item)
        return rows, unidentifiable

    left_index, left_unidentifiable = index(left)
    right_index, right_unidentifiable = index(right)
    left_keys, right_keys = set(left_index), set(right_index)
    only_left = sorted(left_keys - right_keys)
    only_right = sorted(right_keys - left_keys)
    details = []
    field_counts: dict[str, int] = {}
    duplicate_identity_count = 0
    for key in sorted(left_keys & right_keys):
        left_rows, right_rows = left_index[key], right_index[key]
        if len(left_rows) != 1 or len(right_rows) != 1:
            duplicate_identity_count += 1
            details.append({
                "fixture_identity": list(key),
                "fields": ["duplicate_fixture_identity"],
                "left_row_count": len(left_rows),
                "right_row_count": len(right_rows),
            })
            field_counts["duplicate_fixture_identity"] = field_counts.get(
                "duplicate_fixture_identity", 0,
            ) + 1
            continue
        a, b = left_rows[0], right_rows[0]
        fields = []
        for name in _CROSS_EXTRACTION_FIELDS:
            a_value, b_value = a.get(name), b.get(name)
            if name == "season":
                a_value = str(a_value or "").replace("-", "/")
                b_value = str(b_value or "").replace("-", "/")
            if a_value != b_value:
                fields.append(name)
                field_counts[name] = field_counts.get(name, 0) + 1
        if a.get("match_state") != b.get("match_state"):
            fields.append("normalized_match_state")
            field_counts["normalized_match_state"] = field_counts.get("normalized_match_state", 0) + 1
        if fields:
            details.append({
                "fixture_identity": list(key),
                "match_id": a.get("match_id") or b.get("match_id"),
                "fields": fields,
            })
    for key in only_left:
        details.append({"fixture_identity": list(key), "fields": ["fixture_missing_from_right"]})
    for key in only_right:
        details.append({"fixture_identity": list(key), "fields": ["fixture_missing_from_left"]})
    unidentifiable_count = left_unidentifiable + right_unidentifiable
    if unidentifiable_count:
        field_counts["unidentifiable_fixture"] = unidentifiable_count
    source_pair = {
        left["extraction_key"]: _candidate_summary(left)["sources"],
        right["extraction_key"]: _candidate_summary(right)["sources"],
    }
    return {
        "left_extraction_key": left["extraction_key"],
        "right_extraction_key": right["extraction_key"],
        "fixtures_only_in_left": [list(key) for key in only_left],
        "fixtures_only_in_right": [list(key) for key in only_right],
        "compared_fixtures": len(left_keys & right_keys),
        "unidentifiable_fixture_count": {
            "left": left_unidentifiable,
            "right": right_unidentifiable,
        },
        "duplicate_fixture_identity_count": duplicate_identity_count,
        "conflicting_match_count": len(details) + unidentifiable_count,
        "different_fields_by_count": dict(sorted(field_counts.items())),
        "conflicts": details,
        "sources": source_pair,
    }


def _independent_comparison(
    candidate: dict[str, Any], evidence: dict[str, Any],
) -> dict[str, Any]:
    """Compare Hito 1B played fixtures with verified club-page P observations."""
    expected = {
        str(item["match_id"]): item for item in evidence.get("items", [])
        if item.get("match_id") is not None
    }
    actual = {
        str(item["match_id"]): item
        for rows in candidate["groups"].values() for item in rows
        if item.get("match_id") is not None and item.get("match_state") == "played"
    }
    details = []
    for match_id in sorted(expected.keys() | actual.keys()):
        if match_id not in expected or match_id not in actual:
            details.append({
                "match_id": match_id,
                "fields": ["match_id"],
                "status": "MISSING_OR_EXTRA",
                "club_page_sources": expected.get(match_id, {}).get("source_observations", []),
                "competition_source": {
                    "captured_at_utc": actual.get(match_id, {}).get("_captured_at_utc"),
                    "snapshot_sha256": actual.get(match_id, {}).get("_snapshot_sha256"),
                    "snapshot_directory": actual.get(match_id, {}).get("_competition_snapshot_directory"),
                } if match_id in actual else None,
            })
            continue
        source, fixture = expected[match_id], actual[match_id]
        pairs = {
            "season": (str(source.get("season") or "").replace("-", "/"), str(fixture.get("season") or "").replace("-", "/")),
            "competition_code": (source.get("competition_code"), fixture.get("_competition_code_raw")),
            "date": (source.get("date"), fixture.get("date")),
            "home_team_season_id": (source.get("home_team_season_id"), fixture.get("home_team_season_id")),
            "away_team_season_id": (source.get("away_team_season_id"), fixture.get("away_team_season_id")),
            "home_team_name": (str(source.get("home_team_name") or "").casefold(), str(fixture.get("home_team_name") or "").casefold()),
            "away_team_name": (str(source.get("away_team_name") or "").casefold(), str(fixture.get("away_team_name") or "").casefold()),
            "home_goals": (source.get("home_goals"), fixture.get("home_goals")),
            "away_goals": (source.get("away_goals"), fixture.get("away_goals")),
        }
        if source.get("referee_id") is not None and fixture.get("referee_id") is not None:
            pairs["referee_id"] = (str(source["referee_id"]).removeprefix("r"), str(fixture["referee_id"]).removeprefix("r"))
        if source.get("round") is not None and fixture.get("round") is not None:
            pairs["round"] = (source.get("round"), fixture.get("round"))
        differences = [name for name, (a, b) in pairs.items() if a != b]
        if differences:
            details.append({
                "match_id": match_id,
                "fields": differences,
                "status": "DIFFERENT",
                "club_page_sources": source.get("source_observations", []),
                "competition_source": {
                    "captured_at_utc": fixture.get("_captured_at_utc"),
                    "snapshot_sha256": fixture.get("_snapshot_sha256"),
                    "snapshot_directory": fixture.get("_competition_snapshot_directory"),
                },
            })
    evidence_source = evidence.get("source", {})
    return {
        "status": "MATCHED" if not details and expected else "DIFFERENT",
        "evidence_match_count": len(expected),
        "candidate_played_match_count": len(actual),
        "matched_count": len(expected) - len(details),
        "differences": details,
        "evidence_source": evidence_source,
    }


def load_competition_export(
    root: Path, *, extraction_key: str | None = None,
    independent_match_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select one compatible local Hito 1B export, validating its raw lineage.

    Automatic selection requires complete raw lineage. Equivalent sources are
    ordered by capture time; conflicting sources require verified independent
    match evidence or remain explicitly ambiguous.
    """
    root = root.expanduser().resolve()
    metadata_paths = sorted(root.glob("snapshot-*/dataset_metadata.json"))
    if not metadata_paths:
        if extraction_key:
            raise InvalidCompetitionExport(f"No hay exports Hito 1B en {root}")
        return {
            "matches": None,
            "selection": {
                "selection_status": "NO_COMPATIBLE_EXPORT",
                "selection_mode": "explicit" if extraction_key else "automatic_integrity_and_coherence",
                "requested_extraction_key": extraction_key,
            },
        }

    valid: list[dict[str, Any]] = []
    invalid_reasons: dict[str, str] = {}
    for metadata_path in metadata_paths:
        try:
            candidate = _validate_competition_export(metadata_path)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            try:
                key = str(_read_json(metadata_path).get("extraction_key") or metadata_path.parent.name)
            except (OSError, ValueError, TypeError, AttributeError):
                key = metadata_path.parent.name
            invalid_reasons[key] = f"{type(exc).__name__}: {exc}"
            continue
        valid.append(candidate)

    if extraction_key:
        selected = next((item for item in valid if item["extraction_key"] == extraction_key), None)
        if selected is None:
            reason = invalid_reasons.get(extraction_key, "la clave no existe").strip()
            raise InvalidCompetitionExport(f"No se puede seleccionar {extraction_key}: {reason}")
        selection_mode = "explicit"
        selection_reason = "Selección explícita por extraction_key; se validaron esquema, datos y raw asociado."
    else:
        if not valid:
            return {
                "matches": None,
                "selection": {
                    "selection_status": "NO_COMPATIBLE_EXPORT",
                    "selection_mode": "automatic_integrity_and_coherence",
                    "selection_criteria": [
                        "schema/temporada compatibles",
                        "dos grupos completos de 380 filas",
                        "raw VALID/HTTP 200 con SHA coincidente",
                        "IDs únicos y ningún estado inconsistente",
                        "fecha de captura más reciente entre fuentes válidas",
                    ],
                    "rejected_candidates": invalid_reasons,
                },
            }
        candidate_conflicts = [
            _semantic_conflicts(left, right)
            for index, left in enumerate(valid)
            for right in valid[index + 1:]
        ]
        for item in valid:
            if independent_match_evidence and independent_match_evidence.get("status") == "VALIDATED":
                item["independent_comparison"] = _independent_comparison(item, independent_match_evidence)
        if len(valid) == 1:
            selected = valid[0]
            selection_mode = "automatic_single_valid_source"
            selection_reason = "Única extracción completa con integridad y procedencia raw verificadas."
        elif candidate_conflicts and all(item["conflicting_match_count"] == 0 for item in candidate_conflicts):
            selected = max(valid, key=lambda item: (item["captured_at_order"], item["extraction_key"]))
            selection_mode = "automatic_equivalent_sources_then_recency"
            selection_reason = (
                "Las extracciones completas coinciden en IDs y campos deportivos comparables; "
                "se eligió la más reciente y se conservó el inventario de fuentes equivalentes."
            )
        elif independent_match_evidence and independent_match_evidence.get("status") == "VALIDATED":
            corroborated = [
                item for item in valid
                if item.get("independent_comparison", {}).get("status") == "MATCHED"
            ]
            if len(corroborated) == 1:
                selected = corroborated[0]
                selection_mode = "automatic_independently_corroborated"
                selection_reason = (
                    "La fuente coincide campo a campo con la evidencia local validada de P en páginas de clubes; "
                    "las extracciones restantes no superan ese contraste."
                )
            else:
                selected = None
                selection_mode = "automatic_conflict_review"
                selection_reason = "La evidencia independiente no identifica una única extracción coherente."
        else:
            selected = None
            selection_mode = "automatic_conflict_review"
            selection_reason = (
                "Hay diferencias deportivas entre extracciones válidas y no se proporcionó evidencia "
                "independiente validada que permita ordenarlas."
            )

        if selected is None:
            return {
                "matches": None,
                "selection": {
                    "selection_status": "AMBIGUOUS_VALID_SOURCES",
                    "selection_mode": selection_mode,
                    "selection_reason": selection_reason,
                    "selection_criteria": [
                        "esquema, temporada y dos grupos completos",
                        "HTTP VALID, SHA-256 y lineage raw por grupo",
                        "comparación de IDs y campos deportivos normalizados entre extracciones",
                        "fecha de captura usada solo después de resolver coherencia deportiva",
                        "evidencia independiente local solo cuando está validada y su cobertura es explícita",
                    ],
                    "valid_candidates": [
                        {**_candidate_summary(item), "independent_comparison": item.get("independent_comparison")}
                        for item in valid
                    ],
                    "candidate_conflicts": candidate_conflicts,
                    "independent_evidence": independent_match_evidence.get("source") if independent_match_evidence else None,
                    "rejected_candidates": invalid_reasons,
                },
            }

    matches = [item for group in ("I", "II") for item in selected["groups"][group]]
    metadata = selected["metadata"]
    return {
        "matches": matches,
        "selection": {
            "selection_status": "SELECTED",
            "selection_mode": selection_mode,
            "selected_extraction_key": selected["extraction_key"],
            "export_directory": selected["export_directory"],
            "schema_version": metadata["schema_version"],
            "parser_version": metadata["parser_version"],
            "season": metadata["season"],
            "selection_reason": selection_reason,
            "selection_criteria": [
                "schema/temporada compatibles",
                "dos grupos completos de 380 filas",
                "raw VALID/HTTP 200 con SHA coincidente entre export y metadata raw",
                "IDs de partido únicos, score/goles coherentes y ningún registro inconsistente",
                "comparación semántica entre fuentes antes de usar recencia",
                "fecha de captura por grupo preservada; ambos grupos proceden de una sola extracción",
            ],
            "groups": selected["source_details"],
            "normalized_state_counts": selected["status_counts"],
            "fixtures_loaded": len(matches),
            "selected_source": _candidate_summary(selected),
            "discarded_valid_sources": [
                {
                    **_candidate_summary(item),
                    "reason": (
                        "Extracción explícitamente descartada en favor de la clave solicitada."
                        if extraction_key else "Fuente semánticamente equivalente con captura anterior."
                    ),
                }
                for item in valid if item["extraction_key"] != selected["extraction_key"]
            ],
            "candidate_conflicts": candidate_conflicts if not extraction_key else [
                _semantic_conflicts(selected, item) for item in valid if item is not selected
            ],
            "independent_comparison": selected.get("independent_comparison"),
            "independent_evidence": independent_match_evidence.get("source") if independent_match_evidence else None,
            "rejected_candidates": invalid_reasons,
        },
    }


def load_competition_snapshot(directory: Path, expected_group: str) -> CompetitionSnapshot:
    """Lee offline un snapshot válido, comprobando URL, status, tamaño y hash."""
    if expected_group not in COMPETITION_URLS:
        raise ValueError(f"Grupo fuera del alcance: {expected_group}")
    directory = directory.expanduser().resolve()
    metadata_path = directory / "metadata.json"
    html_path = directory / "rendered.html"
    if (directory / "INCOMPLETE").exists():
        raise InvalidCompetitionSnapshot(f"Snapshot marcado INCOMPLETE: {directory}")
    if not metadata_path.is_file() or not html_path.is_file():
        raise InvalidCompetitionSnapshot(f"Faltan metadata.json o rendered.html en {directory}")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        html_bytes = html_path.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidCompetitionSnapshot(f"No se pudo leer el snapshot: {directory}") from exc
    if not isinstance(metadata, dict):
        raise InvalidCompetitionSnapshot(f"metadata.json debe contener un objeto: {directory}")

    requested_url = metadata.get("requested_url")
    final_url = metadata.get("final_url")
    if metadata.get("access_status") != "VALID":
        raise InvalidCompetitionSnapshot(
            f"El snapshot no está validado como VALID: {metadata.get('access_status')}"
        )
    if requested_url != COMPETITION_URLS[expected_group] or final_url != requested_url:
        raise InvalidCompetitionSnapshot(
            f"URL del snapshot no corresponde al Grupo {expected_group}: {requested_url} -> {final_url}"
        )
    if not isinstance(metadata.get("http_status"), int) or not 200 <= metadata["http_status"] < 300:
        raise InvalidCompetitionSnapshot(f"HTTP no válido en metadata: {metadata.get('http_status')}")

    digest = hashlib.sha256(html_bytes).hexdigest()
    if metadata.get("rendered_html_sha256") != digest:
        raise InvalidCompetitionSnapshot(f"El SHA-256 del HTML no coincide: {directory}")
    if metadata.get("rendered_html_bytes") != len(html_bytes):
        raise InvalidCompetitionSnapshot(f"El tamaño del HTML no coincide con metadata: {directory}")
    try:
        html = html_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCompetitionSnapshot(f"El HTML no es UTF-8: {directory}") from exc
    return CompetitionSnapshot(expected_group, directory, html, metadata, digest)


def capture_competition_snapshots(
    *,
    raw_root: Path,
    profile_dir: Path,
    browser: str = "brave",
    settle_ms: int = 1000,
) -> dict[str, Path]:
    """Captura Grupo I y II en orden, deteniéndose ante cualquier acceso no válido.

    La sesión usa únicamente BrowserSessionManager + BDFutbolAccess. No conserva
    cookies/credenciales y no intenta resolver Cloudflare ni otros desafíos.
    """
    from football_data_hub.core.browser_runtime import BrowserRuntimeConfig
    from football_data_hub.core.browser_session import BrowserSessionManager
    from football_data_hub.providers.bdfutbol.access import BDFutbolAccess
    from football_data_hub.providers.bdfutbol.discovery import capture_dom_snapshot, timestamp_utc

    run_dir = raw_root.expanduser().resolve() / timestamp_utc()
    config = BrowserRuntimeConfig(profile_dir=profile_dir, browser=browser)
    captured: dict[str, Path] = {}
    markers = {"I": ("Clasificación", "Grupo I", "2026-27"),
               "II": ("Clasificación", "Grupo II", "2026-27")}
    with BrowserSessionManager(config) as session:
        access = BDFutbolAccess(session)
        for group in ("I", "II"):
            with access.open(
                COMPETITION_URLS[group],
                required_markers=markers[group],
                settle_ms=settle_ms,
            ) as result:
                assessment = result.assessment
                if assessment.status.value != "VALID" or result.visit is None:
                    raise CompetitionAccessStopped(group, assessment)
                output_dir = run_dir / f"group_{group.lower()}"
                capture_dom_snapshot(
                    page=result.visit.page,
                    assessment=assessment,
                    output_dir=output_dir,
                    screenshot=False,
                )
                captured[group] = output_dir
    return captured
