"""Política de parada para futuras capturas de detalle; no realiza navegación."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from football_data_hub.domain.matches.details import (
    MatchDetail,
    MatchDetailValidation,
    MatchDiscrepancy,
    validate_match_detail_contract,
)

REQUIRED_STRUCTURE_EVIDENCE = frozenset(
    {"match_detail_root", "source_match_id", "home_team", "away_team"}
)

REQUIRED_SOURCE_EVIDENCE = {
    "structure.match_detail_root": None,
    "identity.source_match_id": "source_match_id",
    "home_team.team_id": "home_team_id",
    "away_team.team_id": "away_team_id",
}


def validate_promotion_evidence(
    calendar_record: dict[str, Any],
    detail: MatchDetail,
    source_html: bytes,
    *,
    parser_version: str,
) -> tuple[str, ...]:
    """Exige observaciones concretas ligadas a los bytes que se van a guardar.

    Los flags de MatchDetailValidation describen el resultado del futuro parser,
    pero no bastan para promocionar un snapshot. Cada campo requerido debe tener
    una referencia de origen, un valor observado presente en el HTML, su hash y
    la versión del parser que lo extrajo. MATCH-01B deberá verificar que esas
    referencias y valores representan realmente la ficha.
    """

    if not isinstance(parser_version, str) or not parser_version.strip():
        return ("parser-version-missing",)
    source_hash = hashlib.sha256(source_html).hexdigest()
    by_path: dict[str, list] = {}
    for item in detail.field_evidence:
        if item.field_path in REQUIRED_SOURCE_EVIDENCE:
            by_path.setdefault(item.field_path, []).append(item)

    errors: list[str] = []
    for field_path, record_key in REQUIRED_SOURCE_EVIDENCE.items():
        items = by_path.get(field_path, [])
        if len(items) != 1:
            errors.append(f"{field_path}:expected-one-evidence-record")
            continue
        item = items[0]
        if item.state != "observed":
            errors.append(f"{field_path}:not-observed")
        if not isinstance(item.source_reference, str) or not item.source_reference.strip():
            errors.append(f"{field_path}:missing-source-reference")
        if not isinstance(item.raw_value, str) or not item.raw_value:
            errors.append(f"{field_path}:missing-raw-value")
        elif item.raw_value.encode("utf-8") not in source_html:
            errors.append(f"{field_path}:raw-value-not-in-source-html")
        if item.source_html_sha256 != source_hash:
            errors.append(f"{field_path}:source-html-hash-mismatch")
        if item.parser_version != parser_version:
            errors.append(f"{field_path}:parser-version-mismatch")
        if record_key is not None and item.raw_value != str(calendar_record.get(record_key)):
            errors.append(f"{field_path}:raw-value-does-not-match-inventory")
    return tuple(errors)


@dataclass(frozen=True, slots=True)
class CaptureDecision:
    accepted: bool
    stop_acquisition: bool
    code: str
    message: str
    discrepancies: tuple[MatchDiscrepancy, ...] = ()


def compare_calendar_observation(
    calendar_record: dict[str, Any], detail: MatchDetail
) -> tuple[MatchDiscrepancy, ...]:
    """Registra cambios observados sin reemplazar datos del calendario."""

    discrepancies: list[MatchDiscrepancy] = []
    date_value = calendar_record.get("source_match_date")
    if date_value is not None and detail.match_date is not None and date_value != detail.match_date:
        discrepancies.append(
            MatchDiscrepancy(
                field_path="match_date",
                calendar_value=date_value,
                detail_value=detail.match_date,
                calendar_reference="MATCH-00 source_match_date",
                detail_reference=detail.source_url,
            )
        )
    reference = calendar_record.get("reference_result") or {}
    for side, field in (("home", "home_goals"), ("away", "away_goals")):
        calendar_value = reference.get(field)
        detail_value = getattr(detail.score, field)
        if calendar_value is not None and detail_value is not None and calendar_value != detail_value:
            discrepancies.append(
                MatchDiscrepancy(
                    field_path=f"score.{field}",
                    calendar_value=calendar_value,
                    detail_value=detail_value,
                    calendar_reference="MATCH-00 reference_result",
                    detail_reference=detail.source_url,
                )
            )
    for field, calendar_field in (
        ("stadium_id", "stadium_id"),
        ("referee_id", "referee_id"),
    ):
        calendar_value = calendar_record.get(calendar_field)
        detail_value = getattr(detail, field)
        if calendar_value is not None and detail_value is not None and str(calendar_value) != str(detail_value):
            discrepancies.append(
                MatchDiscrepancy(
                    field_path=field,
                    calendar_value=str(calendar_value),
                    detail_value=str(detail_value),
                    calendar_reference="MATCH-00 source record",
                    detail_reference=detail.source_url,
                )
            )
    return tuple(discrepancies)


def assess_capture(
    calendar_record: dict[str, Any],
    detail: MatchDetail,
    validation: MatchDetailValidation,
) -> CaptureDecision:
    """Solo acepta 200, URL esperada, identidad y evidencia estructural verificadas."""

    if validation.challenge_detected:
        return CaptureDecision(False, True, "CHALLENGE_REQUIRED", "Se observó un desafío")
    if validation.denial_detected:
        return CaptureDecision(False, True, "ACCESS_DENIED", "Se observó una denegación")
    if validation.http_status != 200:
        code = f"HTTP_{validation.http_status}" if validation.http_status is not None else "HTTP_UNKNOWN"
        return CaptureDecision(
            False,
            True,
            code,
            "La política exige detenerse ante cualquier respuesta distinta de HTTP 200 verificado",
        )
    if validation.schema_version != "football_data_hub.match_detail_validation.v1":
        return CaptureDecision(
            False,
            True,
            "VALIDATION_SCHEMA_INVALID",
            "Versión del contrato de validación desconocida",
        )
    expected_url = calendar_record.get("source_match_url")
    if validation.requested_url != expected_url or validation.final_url != expected_url:
        return CaptureDecision(
            False, True, "UNEXPECTED_URL", "La URL solicitada/final no coincide con la ficha esperada"
        )
    model_errors = validate_match_detail_contract(detail)
    if model_errors:
        return CaptureDecision(
            False,
            True,
            "MODEL_INVALID",
            f"El modelo tipado incumple su contrato: {', '.join(model_errors)}",
        )
    expected_identity = {
        "internal_id": calendar_record.get("internal_id"),
        "source_match_id": calendar_record.get("source_match_id"),
        "season": calendar_record.get("season"),
        "competition": calendar_record.get("competition"),
        "group": calendar_record.get("group"),
        "matchday": calendar_record.get("matchday"),
        "home_team_id": calendar_record.get("home_team_id"),
        "away_team_id": calendar_record.get("away_team_id"),
    }
    observed_identity = {
        "internal_id": detail.identity.internal_id,
        "source_match_id": detail.identity.source_match_id,
        "season": detail.identity.season,
        "competition": detail.identity.competition,
        "group": detail.identity.group,
        "matchday": detail.identity.matchday,
        "home_team_id": detail.identity.home_team_id,
        "away_team_id": detail.identity.away_team_id,
    }
    if (
        not validation.identity_verified
        or expected_identity != observed_identity
        or detail.home_team.team_id != calendar_record.get("home_team_id")
        or detail.away_team.team_id != calendar_record.get("away_team_id")
        or detail.source != "BDFutbol"
        or detail.source_url != expected_url
        or detail.source_generation_id != calendar_record.get("source_generation_id")
        or detail.source_capture_id != calendar_record.get("source_capture_id")
    ):
        return CaptureDecision(
            False, True, "IDENTITY_MISMATCH", "La identidad de partido o equipos no coincide"
        )
    evidence = {
        item.strip().lower()
        for item in validation.structural_evidence
        if isinstance(item, str) and item.strip()
    }
    if not REQUIRED_STRUCTURE_EVIDENCE.issubset(evidence):
        return CaptureDecision(
            False, True, "STRUCTURE_UNVERIFIED", "No hay evidencia estructural suficiente"
        )
    if not validation.valid:
        return CaptureDecision(
            False, True, "STRUCTURE_INVALID", "La validación estructural del detalle no es válida"
        )
    discrepancies = compare_calendar_observation(calendar_record, detail)
    return CaptureDecision(
        True,
        False,
        "VALID",
        "Captura validada; discrepancias de observación preservadas",
        discrepancies,
    )
