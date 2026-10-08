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


def load_competition_export(
    root: Path, *, extraction_key: str | None = None
) -> dict[str, Any]:
    """Select one compatible local Hito 1B export, validating its raw lineage.

    Without an explicit key, the newest quality-valid whole extraction is
    selected. Result-label counts never participate in ranking.
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
                "selection_mode": "explicit" if extraction_key else "automatic_quality_then_recency",
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
                    "selection_mode": "automatic_quality_then_recency",
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
        selected = max(valid, key=lambda item: (item["captured_at_order"], item["extraction_key"]))
        selection_mode = "automatic_quality_then_recency"
        selection_reason = (
            "Elegida la extracción válida más reciente tras comprobar calidad e integridad; "
            "el número de etiquetas result_status=played no interviene en la selección."
        )

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
                "fecha de captura por grupo preservada; ambos grupos proceden de una sola extracción",
            ],
            "groups": selected["source_details"],
            "normalized_state_counts": selected["status_counts"],
            "fixtures_loaded": len(matches),
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
