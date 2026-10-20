"""Load the independent STAT-01 capture and bind it to active Results data."""

from __future__ import annotations

import hashlib
import json
import copy
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from football_data_hub.domain.classification.models import MatchResult, Team
from football_data_hub.providers.bdfutbol.classification.match_io import load_match_dataset
from football_data_hub.domain.statistics.engine import (
    STATISTICS_ENGINE_VERSION,
    calculate_competition_statistics,
)
from football_data_hub.domain.statistics.models import CompetitionContext
from football_data_hub_api.config import (
    ApiSettings,
    DEFAULT_GROUP2_STATISTICS_CAPTURE,
    PROJECT_ROOT,
)
from football_data_hub_api.dataset import DatasetBundle
from football_data_hub_api.schemas import (
    CompetitionStatisticsResponse,
    StatisticsBootstrapResponse,
    StatisticsCaptureMetadata,
    StatisticsPenalties,
    StatisticsReconciliation,
    StatisticsRecords,
)

STATISTICS_BOOTSTRAP_SCHEMA_VERSION = 1


class StatisticsDatasetLoadError(ValueError):
    """Raised when STAT-01 does not match a valid active Results capture."""


@dataclass(frozen=True, slots=True)
class StatisticsDatasetBundle:
    bootstrap: StatisticsBootstrapResponse
    etag: str

    @property
    def api_etag(self) -> str:
        """The statistics schema version is already part of the bundle ETag."""

        return self.etag


def load_statistics_dataset(
    settings: ApiSettings, active_dataset: DatasetBundle | None
) -> StatisticsDatasetBundle:
    """Validate hashes, provenance and the pure-engine result once at startup."""

    if active_dataset is None:
        raise StatisticsDatasetLoadError("Resultados no está disponible para validar Estadísticas")
    root = settings.statistics_root or (PROJECT_ROOT / DEFAULT_GROUP2_STATISTICS_CAPTURE).resolve()
    paths = {
        "capture": root / "metadata/capture.json",
        "derived": root / "normalized/derived_statistics.json",
        "exclusive": root / "normalized/exclusive_statistics.json",
        "validation": root / "validation/results.json",
        "reconciliation": root / "validation/reconciliation.json",
        "source_html": root / "raw/source.html",
        "chart_data": root / "raw/chart_data_provider.json",
        "access": root / "raw/access.json",
    }
    files = {name: _read_bytes(path) for name, path in paths.items()}
    decoded = {
        name: _decode_json(files[name], paths[name])
        for name in (
            "capture",
            "derived",
            "exclusive",
            "validation",
            "reconciliation",
            "access",
        )
    }
    capture = decoded["capture"]
    derived = decoded["derived"]
    exclusive = decoded["exclusive"]
    validation = decoded["validation"]
    reconciliation = decoded["reconciliation"]
    active = active_dataset.bootstrap
    active_match_bytes = _read_bytes(settings.matches_path)
    active_match_sha256 = hashlib.sha256(active_match_bytes).hexdigest()
    source_match_path = _resolve_match_reference(match_reference_path=capture.get("match_dataset", {}).get("path"), settings=settings)
    source_match_bytes = _read_bytes(source_match_path)
    source_reference = capture.get("match_dataset")
    if not isinstance(source_reference, dict) or hashlib.sha256(source_match_bytes).hexdigest() != source_reference.get("sha256"):
        raise StatisticsDatasetLoadError(
            "El catálogo original de Resultados de STAT-01 no coincide con su hash; "
            "es una versión distinta de Resultados"
        )
    try:
        source_metadata, source_teams, source_matches = load_match_dataset(source_match_path)
        source_report = calculate_competition_statistics(
            source_teams,
            source_matches,
            CompetitionContext(
                competition=active.metadata.competition,
                season=active.metadata.season,
                group=active.metadata.group,
            ),
        )
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise StatisticsDatasetLoadError("No se pudo validar el catálogo original de Resultados de STAT-01") from exc

    _validate_capture(
        capture,
        derived,
        exclusive,
        validation,
        decoded["access"],
        files,
        active,
        source_match_sha256=hashlib.sha256(source_match_bytes).hexdigest(),
        source_metadata=source_metadata,
        source_teams=source_teams,
        source_matches=source_matches,
        reconciliation=reconciliation,
    )
    _validate_derived_against_report(derived, source_report)
    source_bundle = type("SourceMatches", (), {"teams": source_teams, "matches": source_matches})()
    _validate_reconciliation(reconciliation, source_report, source_bundle)
    report = _calculate_active_statistics(active, derived)

    match_reference = capture["match_dataset"]
    capture_id = str(capture["capture_id"])
    dataset_version = hashlib.sha256(
        b"".join(name.encode("utf-8") + b"\0" + files[name] for name in sorted(files))
        + active_match_bytes
    ).hexdigest()[:16]
    try:
        metadata = StatisticsCaptureMetadata(
            source=capture["source"],
            url=capture["final_url"],
            competition=capture["competition"],
            season=capture["season"],
            group=capture["group"],
            section="statistics",
            capture_id=capture_id,
            captured_at=_parse_datetime(capture["captured_at_utc"]),
            extractor_version=capture["extractor_version"],
            dataset_version=f"{capture_id}-{dataset_version}",
            source_snapshot_sha256=capture["source_html_sha256"],
            chart_data_provider_sha256=capture["chart_data_provider_sha256"],
            match_dataset_path=match_reference["path"],
            match_dataset_sha256=match_reference["sha256"],
            match_dataset_capture_id=match_reference["source_capture_id"],
            match_dataset_captured_at=_parse_datetime(match_reference["source_captured_at_utc"]),
            active_match_capture_id=active.metadata.capture_id,
            active_match_captured_at=active.metadata.captured_at,
        )
        statistics_payload = json.loads(json.dumps(asdict(report.statistics), ensure_ascii=False))
        context = statistics_payload.pop("context")
        statistics = CompetitionStatisticsResponse.model_validate({**statistics_payload, **context})
        penalties_payload = exclusive["items"]["penalties"]
        penalties = StatisticsPenalties.model_validate(
            {
                **penalties_payload,
                "source_url": exclusive["items"]["penalties"].get("source_url")
                or capture["requested_url"],
            }
        )
        records = StatisticsRecords.model_validate(
            json.loads(json.dumps(asdict(report.records), ensure_ascii=False))
        )
        reconciliation_payload = _rebase_reconciliation(
            reconciliation,
            report,
            active,
            source_capture_id=str(match_reference["source_capture_id"]),
            source_match_sha256=str(match_reference["sha256"]),
            active_match_sha256=active_match_sha256,
        )
        reconciliation_payload.pop("schema_version", None)
        reconciliation_payload["statistics_captured_at_utc"] = _parse_datetime(
            reconciliation_payload["statistics_captured_at_utc"]
        )
        reconciliation_payload["match_dataset_captured_at_utc"] = _parse_datetime(
            reconciliation_payload["match_dataset_captured_at_utc"]
        )
        reconciliation_response = StatisticsReconciliation.model_validate(reconciliation_payload)
    except (KeyError, TypeError, ValidationError, ValueError) as exc:
        raise StatisticsDatasetLoadError(
            "Los artefactos de Estadísticas no cumplen el contrato público"
        ) from exc

    if penalties.penalties_awarded != penalties.penalties_scored + penalties.penalties_missed:
        raise StatisticsDatasetLoadError("Los penaltis no cumplen la suma marcados + fallados")
    limitations = _limitations(derived.get("methodology"), reconciliation_payload)
    if (
        match_reference.get("source_capture_id") != active.metadata.capture_id
        or match_reference.get("sha256") != active_match_sha256
    ):
        limitations.extend([
            "Los agregados deportivos, récords y rachas se recalculan desde Resultados activos.",
            "Penaltis y el gráfico publicado de BDFutbol conservan la fecha de su captura original.",
        ])
    bootstrap = StatisticsBootstrapResponse(
        metadata=metadata,
        statistics=statistics,
        penalties=penalties,
        records=records,
        reconciliation=reconciliation_response,
        methodology=derived.get("methodology", {}),
        limitations=limitations,
    )
    etag = f'"statistics-v{STATISTICS_BOOTSTRAP_SCHEMA_VERSION}-{metadata.dataset_version}"'
    return StatisticsDatasetBundle(bootstrap=bootstrap, etag=etag)


def _validate_capture(
    capture: dict[str, Any],
    derived: dict[str, Any],
    exclusive: dict[str, Any],
    validation: dict[str, Any],
    access: dict[str, Any],
    files: dict[str, bytes],
    active: Any,
    *,
    source_match_sha256: str,
    source_metadata: dict[str, Any],
    source_teams: tuple[Team, ...],
    source_matches: tuple[MatchResult, ...],
    reconciliation: dict[str, Any],
) -> None:
    if (
        capture.get("schema_version") != 1
        or capture.get("source") != "BDFutbol"
        or capture.get("competition") != active.metadata.competition
        or capture.get("season") != active.metadata.season
        or capture.get("season") != "2026-27"
        or capture.get("group") != active.metadata.group
        or not capture.get("capture_id")
    ):
        raise StatisticsDatasetLoadError(
            f"La captura no corresponde a Primera Federación Grupo {active.metadata.group}"
        )
    if capture.get("final_url") != capture.get("requested_url"):
        raise StatisticsDatasetLoadError("La URL final de Estadísticas no coincide con la solicitada")
    if capture.get("source_html_sha256") != hashlib.sha256(files["source_html"]).hexdigest():
        raise StatisticsDatasetLoadError("El hash del HTML original de Estadísticas no coincide")
    if capture.get("chart_data_provider_sha256") != hashlib.sha256(files["chart_data"]).hexdigest():
        raise StatisticsDatasetLoadError("El hash del gráfico original no coincide")
    # MULTI-01 exports the original access report directly; earlier REF/STAT
    # exports wrapped the report under "access". Validate both known layouts.
    access_data = access.get("access", access)
    if (
        not isinstance(access_data, dict)
        or access_data.get("status") != "VALID"
        or access.get("http_status") != 200
        or access.get("capture_id") != capture.get("capture_id")
        or access.get("captured_at_utc") != capture.get("captured_at_utc")
        or access.get("requested_url") != capture.get("requested_url")
        or access.get("final_url") != capture.get("final_url")
        or access.get("html_valid") is not True
        or access.get("chart_valid") is not True
        or access.get("source_snapshot_sha256") != capture.get("source_html_sha256")
        or access.get("chart_snapshot_sha256") != capture.get("chart_data_provider_sha256")
    ):
        raise StatisticsDatasetLoadError("La captura no acredita contenido deportivo válido")
    if validation.get("valid") is not True:
        raise StatisticsDatasetLoadError("La captura STAT-01 no superó la validación registrada")
    source_validation = validation.get("statistics_source")
    match_validation = validation.get("match_dataset")
    if (
        not isinstance(source_validation, dict)
        or source_validation.get("valid") is not True
        or source_validation.get("issues") != []
        or not isinstance(match_validation, dict)
        or match_validation.get("valid") is not True
    ):
        raise StatisticsDatasetLoadError("La captura STAT-01 contiene un bloque de validación fallido")

    match_reference = capture.get("match_dataset")
    derived_reference = derived.get("match_dataset")
    if not isinstance(match_reference, dict) or derived_reference != match_reference:
        raise StatisticsDatasetLoadError("La captura y los datos derivados no comparten la referencia de Resultados")
    if (
        match_reference.get("sha256") != source_match_sha256
        or match_reference.get("source_capture_id") != source_metadata.get("source_capture_id")
        or match_reference.get("source_captured_at_utc") != source_metadata.get("source_captured_at_utc")
        or derived.get("algorithm") != "football_data_hub.domain.statistics.engine"
        or derived.get("algorithm_version") != STATISTICS_ENGINE_VERSION
    ):
        raise StatisticsDatasetLoadError("Estadísticas referencia una versión distinta de Resultados")
    if exclusive.get("schema_version") != 1 or any(
        exclusive.get(key) != capture.get(key)
        for key in ("source", "capture_id", "captured_at_utc", "competition", "season", "group")
    ):
        raise StatisticsDatasetLoadError("Los penaltis pertenecen a otra captura")
    for key in ("statistics_capture_id", "statistics_captured_at_utc"):
        expected = capture.get("capture_id" if key.endswith("id") else "captured_at_utc")
        if reconciliation.get(key) != expected:
            raise StatisticsDatasetLoadError("La reconciliación pertenece a otra captura de Estadísticas")
    if (
        reconciliation.get("match_dataset_capture_id") != match_reference.get("source_capture_id")
        or reconciliation.get("match_dataset_captured_at_utc") != match_reference.get("source_captured_at_utc")
        or reconciliation.get("match_data_alignment", {}).get("status") != "identical"
    ):
        raise StatisticsDatasetLoadError("La reconciliación no confirma la referencia activa de partidos")
    counts = match_reference.get("counts")
    source_status_counts = {
        "played": sum(match.status == "played" for match in source_matches),
        "unplayed": sum(match.status == "unplayed" for match in source_matches),
        "incomplete": sum(match.status == "incomplete" for match in source_matches),
    }
    if (
        not isinstance(counts, dict)
        or counts.get("teams") != len(source_teams)
        or counts.get("matches") != len(source_matches)
        or any(counts.get(key) != value for key, value in source_status_counts.items())
    ):
        raise StatisticsDatasetLoadError("Los recuentos de Resultados no coinciden con la referencia de origen")
    validation_counts = match_validation.get("counts", {})
    if (
        validation_counts.get("teams") != len(source_teams)
        or validation_counts.get("matches") != len(source_matches)
        or any(validation_counts.get(key) != value for key, value in source_status_counts.items())
    ):
        raise StatisticsDatasetLoadError("El informe de validación no corresponde a Resultados de origen")
    source_summary = source_validation.get("summary", {})
    if (
        source_summary.get("season") != capture.get("season")
        or source_summary.get("group") != capture.get("group")
        or source_summary.get("source_matches") != source_status_counts["played"]
        or source_summary.get("source_records") != len(reconciliation.get("published_match_records", []))
        or source_summary.get("source_streaks") != len(reconciliation.get("published_streaks", []))
        or source_summary.get("chart_rounds") != len(derived.get("statistics", {}).get("rounds", []))
    ):
        raise StatisticsDatasetLoadError("El resumen de validación no coincide con los artefactos de Estadísticas")
    team_ids = {team.team_id for team in source_teams}
    if len(team_ids) != 20 or any(
        item.home_team_id not in team_ids or item.away_team_id not in team_ids
        for item in source_matches
    ):
        raise StatisticsDatasetLoadError("El dataset de origen no contiene referencias de equipo válidas")
def _validate_derived_against_report(derived: dict[str, Any], report: Any) -> None:
    calculated_statistics = json.loads(json.dumps(asdict(report.statistics), ensure_ascii=False))
    calculated_records = json.loads(json.dumps(asdict(report.records), ensure_ascii=False))
    if calculated_statistics != derived.get("statistics") or calculated_records != derived.get("records"):
        raise StatisticsDatasetLoadError("Los valores derivados no coinciden con el catálogo de Resultados de su captura")


def _calculate_active_statistics(active: Any, derived: dict[str, Any]) -> Any:
    try:
        teams = [Team(team_id=item.team_id, name=item.name, team_url=item.team_url, crest_url=item.crest_url) for item in active.teams]
        matches = [MatchResult(**item.model_dump()) for item in active.matches]
        context_data = derived["statistics"]["context"]
        report = calculate_competition_statistics(
            teams,
            matches,
            CompetitionContext(
                competition=context_data["competition"],
                season=context_data["season"],
                group=context_data["group"],
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StatisticsDatasetLoadError("No se pudo verificar STAT-01 con el motor local") from exc
    return report


def _resolve_match_reference(match_reference_path: Any, *, settings: ApiSettings) -> Path:
    if not isinstance(match_reference_path, str) or not match_reference_path:
        raise StatisticsDatasetLoadError("STAT-01 no declara la ruta de su catálogo original de Resultados")
    candidate = Path(match_reference_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    project_candidate = (PROJECT_ROOT / candidate).resolve()
    if project_candidate.is_file():
        return project_candidate
    # Historical exports can be moved together with their source snapshot.
    # Resolve only a path whose file still exists; never substitute the active
    # catalog for a missing historical source.
    return project_candidate


def _rebase_reconciliation(
    original: dict[str, Any], report: Any, active: Any, *, source_capture_id: str,
    source_match_sha256: str, active_match_sha256: str
) -> dict[str, Any]:
    payload = copy.deepcopy(original)
    stale = (
        source_capture_id != active.metadata.capture_id
        or source_match_sha256 != active_match_sha256
    )
    payload["capture_windows_differ"] = stale
    payload["temporal_comparison_status"] = (
        "source_capture_older_than_active_results" if stale else "same_match_records_verified"
    )
    alignment = dict(payload.get("match_data_alignment", {}))
    alignment.update({
        "status": "source_capture_older_than_active_results" if stale else "identical",
        "active_capture_id": active.metadata.capture_id,
        "active_match_count": len(active.matches),
        "source_match_capture_id": source_capture_id,
    })
    payload["match_data_alignment"] = alignment
    round_by_day = {item.matchday: item for item in report.statistics.rounds}
    for item in payload.get("round_series", []):
        current = round_by_day.get(item.get("matchday"))
        if current is None:
            continue
        statistic = item.get("statistic")
        calculated = getattr(current, statistic, None)
        item["calculated"] = calculated
        item["difference_published_minus_calculated"] = (
            item.get("published") - calculated
            if item.get("published") is not None and calculated is not None else None
        )
        item["played_matches"] = current.played_matches
        item["scheduled_matches"] = current.scheduled_matches
        item["coverage"] = current.coverage
        item["status"] = "different_capture_windows" if stale else (
            "match" if item.get("difference_published_minus_calculated") == 0 else "difference"
        )
        if stale:
            item["cause"] = "La serie publicada y Resultados activos proceden de capturas distintas."
    field_by_stat = {
        "teams": "team_count", "played_matches": "played_matches", "home_wins": "home_wins",
        "away_wins": "away_wins", "draws": "draws", "goals": "goals",
        "goals_per_match": "goals_per_match", "yellow_cards": "yellow_cards",
        "yellow_cards_per_match": "yellow_cards_per_match", "red_cards": "red_cards",
        "red_cards_per_match_vs_expulsions_per_match": "red_cards_per_match",
    }
    for item in payload.get("metrics", []):
        field = field_by_stat.get(item.get("statistic"))
        if field is None:
            continue
        calculated = getattr(report.statistics, field)
        published = item.get("published")
        item["calculated"] = calculated
        item["difference_published_minus_calculated"] = (
            published - calculated if published is not None and calculated is not None else None
        )
        item["status"] = "different_capture_windows" if stale else (
            "match" if item.get("difference_published_minus_calculated") == 0 else "difference"
        )
        if stale:
            item["cause"] = "La estadística publicada y Resultados activos proceden de capturas distintas."
    if stale:
        for section in ("published_match_records", "published_streaks"):
            for item in payload.get(section, []):
                item["status"] = "historical_source_capture"
    metrics = payload.get("metrics", [])
    round_series = payload.get("round_series", [])
    payload.setdefault("summary", {}).update({
        "metric_count": len(metrics),
        "metric_matches": sum(item.get("status") == "match" for item in metrics),
        "metric_differences": sum(item.get("status") == "difference" for item in metrics),
        "round_series_differences": sum(item.get("status") == "difference" for item in round_series),
    })
    return payload


def _validate_reconciliation(reconciliation: dict[str, Any], report: Any, active: Any) -> None:
    summary = reconciliation.get("summary", {})
    metrics = reconciliation.get("metrics", [])
    round_series = reconciliation.get("round_series", [])
    if summary.get("metric_count") != len(metrics):
        raise StatisticsDatasetLoadError("El resumen de reconciliación no coincide con sus métricas")
    if summary.get("round_series_differences") != sum(
        item.get("status") == "difference" for item in round_series
    ):
        raise StatisticsDatasetLoadError("El recuento de diferencias por jornada no coincide")
    calculated_fields = {
        "teams": "team_count",
        "played_matches": "played_matches",
        "home_wins": "home_wins",
        "away_wins": "away_wins",
        "draws": "draws",
        "goals": "goals",
        "goals_per_match": "goals_per_match",
        "yellow_cards": "yellow_cards",
        "yellow_cards_per_match": "yellow_cards_per_match",
        "red_cards": "red_cards",
        "red_cards_per_match_vs_expulsions_per_match": "red_cards_per_match",
    }
    for metric in metrics:
        field_name = calculated_fields.get(metric.get("statistic"))
        if field_name is not None and metric.get("calculated") != getattr(report.statistics, field_name):
            # The source compares per-match card values after rounding.
            if not (
                field_name.endswith("_per_match")
                and metric.get("calculated") is not None
                and round(metric["calculated"], 2) == round(getattr(report.statistics, field_name), 2)
            ):
                raise StatisticsDatasetLoadError("Una métrica de reconciliación no coincide con el motor")

    rounds_by_day = {item.matchday: item for item in report.statistics.rounds}
    expected_round_checks = len(rounds_by_day) * 3
    if len(round_series) != expected_round_checks:
        raise StatisticsDatasetLoadError("La reconciliación no cubre las tres series de cada jornada")
    for item in round_series:
        round_stats = rounds_by_day.get(item.get("matchday"))
        if round_stats is None:
            raise StatisticsDatasetLoadError("La reconciliación referencia una jornada inexistente")
        statistic = item.get("statistic")
        if statistic not in {"goals", "yellow_cards", "red_cards"}:
            raise StatisticsDatasetLoadError("La reconciliación contiene una serie no reconocida")
        if (
            item.get("calculated") != getattr(round_stats, statistic)
            or item.get("played_matches") != round_stats.played_matches
            or item.get("scheduled_matches") != round_stats.scheduled_matches
            or item.get("coverage") != round_stats.coverage
        ):
            raise StatisticsDatasetLoadError("La serie de reconciliación no coincide con la cobertura calculada")

    team_ids = {team.team_id for team in active.teams}
    match_ids = {match.match_id for match in active.matches}
    for record in reconciliation.get("published_match_records", []):
        if (
            record.get("match_id") not in match_ids
            or record.get("home_team_id") not in team_ids
            or record.get("away_team_id") not in team_ids
            or any(match_id not in match_ids for match_id in record.get("calculated_match_ids", []))
        ):
            raise StatisticsDatasetLoadError("Un récord publicado referencia un partido o equipo desconocido")
    for streak in reconciliation.get("published_streaks", []):
        if (
            streak.get("resolved_team_id") not in team_ids
            or any(team_id not in team_ids for team_id in streak.get("calculated_tied_team_ids", []))
            or any(
                match_id not in match_ids
                for match_ids_for_team in streak.get("calculated_match_ids", [])
                for match_id in match_ids_for_team
            )
        ):
            raise StatisticsDatasetLoadError("Una racha publicada referencia un equipo o partido desconocido")


def _limitations(methodology: Any, reconciliation: dict[str, Any]) -> list[str]:
    result = []
    if isinstance(methodology, dict):
        postponed = methodology.get("streak_gap_policy")
        if isinstance(postponed, str) and "unverified" in postponed:
            result.append("La continuidad de rachas ante aplazamientos no está verificada.")
        result.append("Las tarjetas rojas coinciden numéricamente con «Expulsiones»; la equivalencia conceptual queda pendiente.")
    if reconciliation.get("summary", {}).get("round_series_differences", 0):
        result.append("La serie publicada presenta diferencias con los valores derivados desde Resultados.")
    return result


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise StatisticsDatasetLoadError(f"No se pudo leer un archivo STAT-01: {path.name}") from exc


def _decode_json(raw: bytes, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StatisticsDatasetLoadError(f"El archivo {path.name} no contiene JSON válido") from exc
    if not isinstance(value, dict):
        raise StatisticsDatasetLoadError(f"El archivo {path.name} debe contener un objeto JSON")
    return value


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)
