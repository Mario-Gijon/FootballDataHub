"""Load and validate the independent BDFutbol referees capture at API startup."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import ValidationError

from football_data_hub_api.config import (
    ApiSettings,
    DEFAULT_GROUP2_REFEREES_CAPTURE,
    PROJECT_ROOT,
)
from football_data_hub_api.schemas import (
    RefereeAvailability,
    RefereeBootstrapResponse,
    RefereeGroupOption,
    RefereeMetadataResponse,
    RefereeRelatedMatchDataset,
    RefereeResponse,
    RefereeScope,
    RefereeScopeSummary,
    RefereeSeasonOption,
    RefereeStatisticsResponse,
)

REFEREES_BOOTSTRAP_SCHEMA_VERSION = 1
_SCOPES: tuple[RefereeScope, ...] = ("all", "group1", "group2")
_SCOPE_LABELS = {"all": "Todos", "group1": "Grupo I", "group2": "Grupo II"}
_REFEREE_ID = re.compile(r"^r\d+$")


class RefereeDatasetLoadError(ValueError):
    """Raised when REF-01 files cannot form a verified independent capture."""


@dataclass(frozen=True, slots=True)
class RefereeDatasetBundle:
    bootstrap: RefereeBootstrapResponse
    etag: str
    group_reference_errors: dict[str, str]

    @property
    def api_etag(self) -> str:
        """The referees schema version is already part of the bundle ETag."""

        return self.etag


def load_referee_dataset(
    settings: ApiSettings,
    *,
    group_match_sources: dict[str, tuple[Path, Path]] | None = None,
) -> RefereeDatasetBundle:
    """Read one REF-01 capture, verify provenance, then prepare the API contract."""

    root = settings.referees_root or (PROJECT_ROOT / DEFAULT_GROUP2_REFEREES_CAPTURE).resolve()
    paths = {
        "referees": root / "normalized/referees.json",
        "statistics": root / "normalized/statistics.json",
        "filter_options": root / "normalized/filter_options.json",
        "capture": root / "metadata/capture.json",
        "validation": root / "validation/results.json",
        "match_reference": root / "validation/match_reference.json",
        **{f"html_{scope}": root / f"raw/source_{scope}.html" for scope in _SCOPES},
    }
    raw_files = {name: _read_bytes(path) for name, path in paths.items()}
    decoded = {
        name: _decode_json(raw_files[name], paths[name])
        for name in (
            "referees",
            "statistics",
            "filter_options",
            "capture",
            "validation",
            "match_reference",
        )
    }
    capture = decoded["capture"]
    _validate_capture_metadata(decoded, raw_files)

    related_reference = capture.get("related_match_dataset")
    if not isinstance(related_reference, dict):
        raise RefereeDatasetLoadError("La captura no declara su dataset relacionado de Resultados")
    legacy_report = decoded["match_reference"]
    if legacy_report.get("reference_dataset") != related_reference:
        raise RefereeDatasetLoadError(
            "La referencia histórica de Grupo II no coincide entre metadatos e informe REF-01"
        )
    legacy_reference_status = legacy_report.get("status")
    if legacy_reference_status not in ("consistent", "discrepancies"):
        raise RefereeDatasetLoadError("El estado de la referencia histórica de Grupo II no es válido")

    match_sources = group_match_sources or {
        "II": (
            _related_matches_path(settings, related_reference),
            root / "validation/match_reference.json",
        )
    }
    if set(match_sources) - {"I", "II"} or not match_sources:
        raise RefereeDatasetLoadError("Las referencias de Resultados deben identificar Grupo I o Grupo II")

    referee_payload = decoded["referees"]
    statistics_payload = decoded["statistics"]
    _validate_payload_provenance(decoded)
    referees = _parse_referees(referee_payload)
    statistics = _parse_statistics(statistics_payload)
    referee_by_id = {item.referee_id: item for item in referees}
    _validate_statistics(statistics, referee_by_id, capture, decoded["validation"])
    group_options = _group_options(decoded["filter_options"], statistics)
    warnings_by_group: dict[str, list[str]] = {}
    related_match_metadata: dict[str, RefereeRelatedMatchDataset] = {}
    related_payloads: dict[str, tuple[dict[str, Any], bytes]] = {}
    group_reference_errors: dict[str, str] = {}
    for group, (matches_path, report_path) in match_sources.items():
        try:
            related_matches_bytes = _read_bytes(matches_path)
            related_matches = _decode_json(related_matches_bytes, matches_path)
            report = (
                decoded["match_reference"]
                if report_path.resolve() == paths["match_reference"].resolve()
                else _decode_json(_read_bytes(report_path), report_path)
            )
            related_matches_digest = hashlib.sha256(related_matches_bytes).hexdigest()
            reference = report.get("reference_dataset")
            if group == "II":
                reference = related_reference
                if report_path.resolve() != paths["match_reference"].resolve():
                    raise RefereeDatasetLoadError(
                        "La referencia de Grupo II debe pertenecer a la captura REF compartida"
                    )
            if not isinstance(reference, dict) or related_matches_digest != reference.get("sha256"):
                raise RefereeDatasetLoadError(
                    f"El hash de Resultados de Grupo {group} no coincide con su informe de referencia"
                )
            warnings_by_group[group] = _validate_match_references(
                related_matches,
                referee_by_id,
                statistics,
                report,
                reference,
                group_scope="group1" if group == "I" else "group2",
            )
            related_payloads[group] = (related_matches, related_matches_bytes)
            related_match_metadata[group] = RefereeRelatedMatchDataset(
                capture_id=str(reference["source_capture_id"]),
                captured_at=_parse_datetime(reference["source_captured_at_utc"]),
                sha256=related_matches_digest,
                reference_status=report["status"],
            )
        except (RefereeDatasetLoadError, KeyError, TypeError, ValueError, ValidationError) as exc:
            group_reference_errors[group] = str(exc)

    if not related_match_metadata:
        raise RefereeDatasetLoadError(
            "No se pudo verificar ninguna relación entre Árbitros y Resultados"
        )
    compatibility_warnings = [
        warning
        for group in sorted(match_sources)
        for warning in warnings_by_group.get(group, [])
    ]
    compatibility_warnings.extend(
        f"No se pudo verificar la referencia de partidos del Grupo {group}: {group_reference_errors[group]}"
        for group in sorted(group_reference_errors)
    )

    scope_summaries = _scope_summaries(statistics, group_options)
    source_hashes = {
        scope: str(capture["scope_captures"][scope]["source_snapshot_sha256"])
        for scope in _SCOPES
    }
    capture_id = str(capture["capture_id"])
    content_hash = hashlib.sha256(
        b"".join(
            name.encode("utf-8") + b"\0" + raw_files[name]
            for name in sorted(raw_files)
        )
        + b"".join(related_payloads[group][1] for group in sorted(related_payloads))
    ).hexdigest()[:16]
    try:
        metadata = RefereeMetadataResponse(
            source=capture["source"],
            url=capture["url"],
            competition=capture["competition"],
            season=capture["season"],
            group="I/II",
            section=capture["section"],
            capture_id=capture_id,
            captured_at=_parse_datetime(capture["captured_at_utc"]),
            extractor_version=capture["extractor_version"],
            dataset_version=f"{capture_id}-{content_hash}",
            source_snapshot_sha256=source_hashes,
            related_matches_path=str(related_reference["path"]),
            # Legacy fields describe the original, declared REF-01 → Grupo II
            # reference. `related_match_datasets` below contains only active
            # references that passed the current byte-hash and identity checks.
            related_matches_sha256=str(related_reference["sha256"]),
            related_matches_capture_id=str(related_reference["source_capture_id"]),
            related_matches_captured_at=_parse_datetime(
                related_reference["source_captured_at_utc"]
            ),
            match_reference_status=legacy_reference_status,
            related_match_datasets=dict(sorted(related_match_metadata.items())),
        )
        bootstrap = RefereeBootstrapResponse(
            metadata=metadata,
            availability=RefereeAvailability(
                catalog_referee_count=len(referees),
                statistics_record_count=len(statistics),
                scope_counts=scope_summaries,
            ),
            seasons=[
                RefereeSeasonOption(
                    season=capture["season"],
                    label=_season_label(capture["season"]),
                    available=True,
                )
            ],
            groups=group_options,
            referees=referees,
            statistics=statistics,
            coverage_note=(
                "Las tarjetas son las mostradas en los partidos dirigidos. "
                "La nacionalidad no está verificada en esta captura."
            ),
            compatibility_warnings=compatibility_warnings,
        )
    except (KeyError, TypeError, ValidationError, ValueError) as exc:
        raise RefereeDatasetLoadError("Los datos de Árbitros no cumplen el contrato público") from exc

    etag = f'"referees-v{REFEREES_BOOTSTRAP_SCHEMA_VERSION}-{metadata.dataset_version}"'
    return RefereeDatasetBundle(
        bootstrap=bootstrap,
        etag=etag,
        group_reference_errors=group_reference_errors,
    )


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise RefereeDatasetLoadError(
            f"No se pudo leer un archivo de Árbitros: {path.name}"
        ) from exc


def _decode_json(raw: bytes, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RefereeDatasetLoadError(
            f"El archivo {path.name} de Árbitros no contiene JSON válido"
        ) from exc
    if not isinstance(value, dict):
        raise RefereeDatasetLoadError(f"El archivo {path.name} debe contener un objeto JSON")
    return value


def _related_matches_path(settings: ApiSettings, reference: dict[str, Any]) -> Path:
    if settings.referees_related_matches_path is not None:
        return settings.referees_related_matches_path
    declared = reference.get("path")
    if not isinstance(declared, str) or not declared or Path(declared).is_absolute():
        raise RefereeDatasetLoadError(
            "La ruta del dataset relacionado debe ser relativa al proyecto o configurarse con FDH_GROUP2_REFEREES_MATCHES"
        )
    path = (PROJECT_ROOT / declared).resolve()
    if not path.is_relative_to(PROJECT_ROOT.resolve()):
        raise RefereeDatasetLoadError("La ruta del dataset relacionado sale del proyecto")
    return path


def _validate_capture_metadata(
    decoded: dict[str, dict[str, Any]], raw_files: dict[str, bytes]
) -> None:
    capture = decoded["capture"]
    validation = decoded["validation"]
    if (
        capture.get("source") != "BDFutbol"
        or capture.get("competition") != "Primera Federación"
        or capture.get("season") != "2026-27"
        or capture.get("group") != "II"
        or capture.get("section") != "referees"
        or not capture.get("capture_id")
    ):
        raise RefereeDatasetLoadError("La captura no es de Árbitros, Primera Federación Grupo II 2026/27")
    if validation.get("valid") is not True or validation.get("issues") != []:
        raise RefereeDatasetLoadError("La captura de Árbitros no superó su validación de origen")
    scope_captures = capture.get("scope_captures")
    if not isinstance(scope_captures, dict) or set(scope_captures) != set(_SCOPES):
        raise RefereeDatasetLoadError("La captura no contiene los tres ámbitos de árbitros")
    for scope in _SCOPES:
        item = scope_captures[scope]
        access = item.get("access") if isinstance(item, dict) else None
        if (
            not isinstance(item, dict)
            or item.get("scope") != scope
            or not isinstance(access, dict)
            or access.get("status") != "VALID"
            or access.get("http_status") != 200
        ):
            raise RefereeDatasetLoadError(f"El ámbito {scope} no acredita contenido deportivo válido")
        html_name = f"html_{scope}"
        if hashlib.sha256(raw_files[html_name]).hexdigest() != item.get("source_snapshot_sha256"):
            raise RefereeDatasetLoadError(f"El hash HTML del ámbito {scope} no coincide con la captura")
        if item.get("file") != f"raw/source_{scope}.html":
            raise RefereeDatasetLoadError(f"La ruta HTML del ámbito {scope} no coincide con la captura")
    scope_counts = capture.get("scope_counts")
    if not isinstance(scope_counts, dict) or set(scope_counts) != set(_SCOPES):
        raise RefereeDatasetLoadError("Los metadatos de captura no incluyen los recuentos de los tres ámbitos")


def _validate_payload_provenance(decoded: dict[str, dict[str, Any]]) -> None:
    capture = decoded["capture"]
    expected_fields = (
        "source",
        "url",
        "competition",
        "season",
        "group",
        "section",
        "capture_id",
        "captured_at_utc",
        "extractor_version",
        "related_match_dataset",
        "scope_counts",
    )
    for name in ("referees", "statistics", "filter_options"):
        payload = decoded[name]
        metadata = payload.get("metadata")
        if payload.get("schema_version") != 1 or not isinstance(metadata, dict):
            raise RefereeDatasetLoadError(f"{name}.json no cumple la versión de captura REF-01")
        if any(metadata.get(key) != capture.get(key) for key in expected_fields):
            raise RefereeDatasetLoadError(f"{name}.json pertenece a otra captura de Árbitros")


def _parse_referees(payload: dict[str, Any]) -> list[RefereeResponse]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise RefereeDatasetLoadError("referees.json no contiene records")
    result: list[RefereeResponse] = []
    try:
        for row in records:
            item = dict(row)
            raw_date = item.get("birth_date")
            item["birth_date"] = date.fromisoformat(raw_date) if raw_date is not None else None
            result.append(RefereeResponse.model_validate(item))
    except (TypeError, ValueError, ValidationError) as exc:
        raise RefereeDatasetLoadError("El catálogo contiene un árbitro con formato inválido") from exc
    ids = [item.referee_id for item in result]
    if len(ids) != len(set(ids)):
        raise RefereeDatasetLoadError("El catálogo repite referee_id")
    for item in result:
        if not _REFEREE_ID.fullmatch(item.referee_id) or _profile_id(item.profile_url) != item.referee_id:
            raise RefereeDatasetLoadError(f"El perfil no corresponde a {item.referee_id}")
        if not _is_bdfutbol_url(item.profile_url):
            raise RefereeDatasetLoadError(f"La URL de perfil de {item.referee_id} no es de BDFutbol")
        if item.photo_url is not None and not _is_bdfutbol_url(item.photo_url):
            raise RefereeDatasetLoadError(f"La URL de fotografía de {item.referee_id} no es de BDFutbol")
        if item.flag_url is not None and not _is_bdfutbol_url(item.flag_url):
            raise RefereeDatasetLoadError(f"La URL de bandera de {item.referee_id} no es de BDFutbol")
    return result


def _parse_statistics(payload: dict[str, Any]) -> list[RefereeStatisticsResponse]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise RefereeDatasetLoadError("statistics.json no contiene records")
    try:
        result = [RefereeStatisticsResponse.model_validate(item) for item in records]
    except (TypeError, ValidationError) as exc:
        raise RefereeDatasetLoadError("Una fila estadística de Árbitros es inválida") from exc
    return result


def _validate_statistics(
    statistics: list[RefereeStatisticsResponse],
    referees: dict[str, RefereeResponse],
    capture: dict[str, Any],
    validation: dict[str, Any],
) -> None:
    keys = [(item.referee_id, item.season, item.group_scope) for item in statistics]
    if len(keys) != len(set(keys)):
        raise RefereeDatasetLoadError("Hay estadísticas duplicadas por árbitro, temporada y grupo")
    by_scope: dict[str, dict[str, RefereeStatisticsResponse]] = {scope: {} for scope in _SCOPES}
    for item in statistics:
        if item.referee_id not in referees:
            raise RefereeDatasetLoadError(f"Las estadísticas referencian un ID ausente: {item.referee_id}")
        if item.season != capture["season"]:
            raise RefereeDatasetLoadError("Una fila estadística pertenece a otra temporada")
        if item.group_scope not in by_scope:
            raise RefereeDatasetLoadError("Una fila estadística contiene un ámbito desconocido")
        if item.published_order < 1:
            raise RefereeDatasetLoadError("published_order debe ser positivo")
        if any(
            value is not None and value < 0
            for value in (item.matches_officiated, item.yellow_cards, item.red_cards)
        ):
            raise RefereeDatasetLoadError("Una estadística de árbitro no puede ser negativa")
        if not _is_bdfutbol_url(item.source_page_url):
            raise RefereeDatasetLoadError("Una estadística referencia una URL de origen no válida")
        if item.statistics_url is not None and (
            not _is_bdfutbol_url(item.statistics_url)
            or f"/p/{item.referee_id}.html" not in urlsplit(item.statistics_url).path
        ):
            raise RefereeDatasetLoadError(
                f"La URL estadística no corresponde a {item.referee_id}"
            )
        by_scope[item.group_scope][item.referee_id] = item
    for scope, rows in by_scope.items():
        if not rows:
            raise RefereeDatasetLoadError(f"El ámbito {scope} está vacío")
        orders = [item.published_order for item in rows.values()]
        if len(orders) != len(set(orders)):
            raise RefereeDatasetLoadError(f"El ámbito {scope} repite published_order")
        if capture["scope_counts"].get(scope) != len(rows):
            raise RefereeDatasetLoadError(f"El recuento de {scope} no coincide con las estadísticas")

    summary = validation.get("summary", {})
    actual_scope_counts = {scope: len(rows) for scope, rows in by_scope.items()}
    if (
        summary.get("referees") != len(referees)
        or summary.get("statistics") != len(statistics)
        or summary.get("unique_ids") != len(referees)
        or summary.get("scope_counts") != actual_scope_counts
        or capture.get("referee_count") != len(referees)
        or capture.get("statistics_count") != len(statistics)
    ):
        raise RefereeDatasetLoadError("Los recuentos no coinciden con metadata/capture y validation/results")

    for referee_id, all_row in by_scope["all"].items():
        one = by_scope["group1"].get(referee_id)
        two = by_scope["group2"].get(referee_id)
        for field in ("matches_officiated", "yellow_cards", "red_cards"):
            total = getattr(all_row, field)
            values = [getattr(item, field) for item in (one, two) if item is not None]
            if total is None or any(value is None for value in values):
                continue
            if total != sum(values):
                raise RefereeDatasetLoadError(
                    f"El agregado Todos no coincide con los grupos ({referee_id}:{field})"
                )


def _group_options(
    payload: dict[str, Any], statistics: list[RefereeStatisticsResponse]
) -> list[RefereeGroupOption]:
    options = payload.get("group_options")
    if not isinstance(options, list):
        raise RefereeDatasetLoadError("filter_options.json no contiene group_options")
    count_by_scope: dict[str, int] = defaultdict(int)
    for row in statistics:
        count_by_scope[row.group_scope] += 1
    result: list[RefereeGroupOption] = []
    try:
        for item in options:
            scope = item["scope"]
            if scope not in _SCOPES:
                raise RefereeDatasetLoadError("Hay una opción de grupo no soportada")
            result.append(
                RefereeGroupOption(
                    group_scope=scope,
                    label=_SCOPE_LABELS[scope],
                    referee_count=count_by_scope[scope],
                )
            )
    except (KeyError, TypeError, ValidationError) as exc:
        raise RefereeDatasetLoadError("Las opciones de grupo están mal formadas") from exc
    if len(result) != len(_SCOPES) or {item.group_scope for item in result} != set(_SCOPES):
        raise RefereeDatasetLoadError("Las opciones de grupo están incompletas o duplicadas")
    return result


def _scope_summaries(
    statistics: list[RefereeStatisticsResponse],
    options: list[RefereeGroupOption],
) -> dict[RefereeScope, RefereeScopeSummary]:
    labels = {item.group_scope: item.label for item in options}
    result: dict[RefereeScope, RefereeScopeSummary] = {}
    for scope in _SCOPES:
        rows = [item for item in statistics if item.group_scope == scope]
        result[scope] = RefereeScopeSummary(
            group_scope=scope,
            label=labels[scope],
            referee_count=len(rows),
            matches_officiated=_complete_sum(rows, "matches_officiated"),
            yellow_cards=_complete_sum(rows, "yellow_cards"),
            red_cards=_complete_sum(rows, "red_cards"),
        )
    return result


def _complete_sum(rows: list[RefereeStatisticsResponse], field: str) -> int | None:
    values = [getattr(item, field) for item in rows]
    if not values or any(value is None for value in values):
        return None
    return sum(values)


def _validate_match_references(
    matches_payload: dict[str, Any],
    referees: dict[str, RefereeResponse],
    statistics: list[RefereeStatisticsResponse],
    report: dict[str, Any],
    related_reference: dict[str, Any],
    *,
    group_scope: Literal["group1", "group2"],
) -> list[str]:
    matches = matches_payload.get("matches")
    if not isinstance(matches, list):
        raise RefereeDatasetLoadError("El dataset relacionado no contiene partidos")
    reference = report.get("reference_dataset", {})
    metadata = matches_payload.get("metadata", {})
    if (
        reference.get("path") != related_reference.get("path")
        or reference.get("sha256") != related_reference.get("sha256")
        or related_reference.get("source_capture_id") != metadata.get("source_capture_id")
        or related_reference.get("source_captured_at_utc")
        != metadata.get("source_captured_at_utc")
        or reference.get("source_capture_id") != metadata.get("source_capture_id")
        or reference.get("source_captured_at_utc") != metadata.get("source_captured_at_utc")
        or report.get("method") != "exact referee_id; no name-based matching"
        or report.get("status") not in ("consistent", "discrepancies")
    ):
        raise RefereeDatasetLoadError("El informe de relación no corresponde al dataset de Resultados")

    if report.get("group_scope") not in (None, group_scope):
        raise RefereeDatasetLoadError("El informe de árbitros pertenece a otro grupo")
    scope_ids = {
        item.referee_id for item in statistics if item.group_scope == group_scope
    }
    played_ids = {
        str(match["referee_id"])
        for match in matches
        if match.get("status") == "played" and match.get("referee_id") is not None
    }
    matched_ids = played_ids & scope_ids
    if set(report.get("matched_referee_ids", [])) != matched_ids:
        raise RefereeDatasetLoadError(
            f"Los IDs enlazados de Árbitros y Resultados no coinciden para {group_scope}"
        )
    counts = report.get("counts", {})
    if (
        counts.get("source_matches") != len(matches)
        or counts.get("played_matches") != sum(match.get("status") == "played" for match in matches)
        or counts.get("unique_match_referee_ids") != len(played_ids)
        or counts.get("matched_referee_ids") != len(matched_ids)
    ):
        raise RefereeDatasetLoadError(
            f"Los recuentos de enlace no coinciden para {group_scope}"
        )
    warnings: list[str] = []
    for match in matches:
        referee_id = match.get("referee_id")
        if referee_id is None:
            continue
        referee_id = str(referee_id)
        if not _REFEREE_ID.fullmatch(referee_id):
            raise RefereeDatasetLoadError("Resultados contiene un referee_id con formato inválido")
        known = referees.get(referee_id)
        referee_url = match.get("referee_url")
        if known is None:
            warnings.append(
                f"Resultados relacionado referencia {referee_id}, ausente del catálogo de esta captura de Árbitros."
            )
            continue
        if referee_url:
            if _profile_id(str(referee_url)) != referee_id:
                raise RefereeDatasetLoadError(
                    f"La URL de árbitro del partido no coincide con referee_id {referee_id}"
                )
            if str(referee_url).rstrip("/") != known.profile_url.rstrip("/"):
                raise RefereeDatasetLoadError(
                    f"La ficha del partido y el catálogo discrepan para {referee_id}"
                )
        if match.get("status") == "played":
            if referee_id not in scope_ids:
                warnings.append(
                    f"El árbitro {referee_id} de Resultados no tiene fila de estadísticas de {group_scope} en esta captura."
                )

    differences = report.get("statistic_differences", [])
    if differences:
        warnings.append(
            "El informe REF-01 registra diferencias estadísticas frente a la captura relacionada de Resultados."
        )
    if report.get("identity_conflicts"):
        raise RefereeDatasetLoadError("El informe REF-01 registra conflictos de identidad con Resultados")
    if report.get("status") == "discrepancies" and not warnings:
        warnings.append("El informe REF-01 registra diferencias con Resultados; revise match_reference.json.")
    # Keep warning output stable even if many matches carry the same missing ID.
    return list(dict.fromkeys(warnings))


def _profile_id(url: str) -> str | None:
    match = re.search(r"/r/(r\d+)\.html(?:$|[?#])", url)
    return match.group(1) if match else None


def _is_bdfutbol_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname == "www.bdfutbol.com"


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _season_label(season: str) -> str:
    first, second = season.split("-", maxsplit=1)
    return f"{first}/{second}"
