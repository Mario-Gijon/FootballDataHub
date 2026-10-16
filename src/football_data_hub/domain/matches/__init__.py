"""Contratos de dominio para fichas individuales de partidos."""

from .details import (
    FieldEvidence,
    MatchDetail,
    MatchDetailIdentity,
    MatchDetailValidation,
    MatchDiscrepancy,
    MatchEvent,
    MatchPlayerAppearance,
    MatchScore,
    MatchTeam,
    match_detail_from_payload,
    parse_literal_minute,
    validate_match_detail_contract,
)

__all__ = [
    "FieldEvidence",
    "MatchDetail",
    "MatchDetailIdentity",
    "MatchDetailValidation",
    "MatchDiscrepancy",
    "MatchEvent",
    "MatchPlayerAppearance",
    "MatchScore",
    "MatchTeam",
    "match_detail_from_payload",
    "parse_literal_minute",
    "validate_match_detail_contract",
]
