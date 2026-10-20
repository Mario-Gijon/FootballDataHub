"""Strict, versioned automatic publication policy for the local update button.

This policy is deliberately not a human approval. Its receipt schema, actor,
validation evidence and audit events are distinct from the campaign's human
approval flow. Parser warnings that indicate an uncertain sporting fact keep a
document pending. Policy v2 permits one narrow uncertainty: when TG2 is
observed and bound to the source HTML, absence of a direct-red marker remains
``not_observed`` rather than being interpreted as a contradiction or proof
that no direct red card occurred. Policy v1 remains unchanged for old receipts.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

POLICY_ID = "football-data-hub.strict-match-details"
POLICY_VERSION = "2"
SUPPORTED_POLICY_VERSIONS = frozenset({"1", POLICY_VERSION})
RECOVERY_POLICY_ID = "football-data-hub.strict-match-details-offline-recovery"
RECOVERY_POLICY_VERSION = "1"
LEGACY_RECOVERY_WARNING = "source_artifact_remains_INVALID_CONTENT_and_discovery_only"
SECOND_YELLOW_UNCERTAINTY_WARNING = "direct_red_card_absence_not_asserted_second_yellow_present"
NON_BLOCKING_WARNINGS = frozenset(
    {
        "campaign_discovery_remains_unpromoted_pending_independent_review",
        "ephemerides_not_observed",
    }
)
_SECOND_YELLOW_RED_EVIDENCE_REFERENCE = "direct-red markers absent; second-yellow dismissal observed"
REQUIRED_CHECKS = frozenset(
    {
        "canonical_matches_catalog_url_and_id",
        "hidden_codi_matches_catalog_id",
        "score_matches_catalog",
        "title_matches_teams_score_date",
        "competition_label_is_primera_federacion",
        "competition_link_matches_catalog_season",
        "matchday_text_and_link_match_catalog",
        "date_matches_catalog",
        "goal_summary_count_matches_score",
        "goal_score_progression_is_chronologically_consistent",
        "all_event_icons_recognized",
        "critical_evidence_is_resolved",
        "two_distinct_team_ids_match_catalog",
        "eleven_starters_each",
        "roster_player_ids_are_unique",
        "unknown_event_icons_rejected",
        "source_not_promotable",
    }
)


def candidate_set_sha256(
    *,
    update_job_id: str,
    campaign_id: str,
    source_generation_id: str,
    source_generation_manifest_sha256: str,
    candidates: list[dict[str, Any]],
    policy_version: str = POLICY_VERSION,
) -> str:
    """Hash the exact, ordered candidates covered by one global update job."""

    if policy_version not in SUPPORTED_POLICY_VERSIONS:
        raise ValueError("unsupported_automatic_publication_policy_version")

    body = {
        "schema_version": "football_data_hub.match_detail_update_candidate_set.v1",
        "update_job_id": update_job_id,
        "policy_id": POLICY_ID,
        "policy_version": policy_version,
        "campaign_id": campaign_id,
        "source_generation_id": source_generation_id,
        "source_generation_manifest_sha256": source_generation_manifest_sha256,
        "candidates": [
            {
                "internal_id": item["internal_id"],
                "source_match_id": item["source_match_id"],
                "source_match_url": item["source_match_url"],
                "group": item["group"],
                "matchday": item["matchday"],
                "reference_result": item["reference_result"],
            }
            for item in candidates
        ],
        "maximum_navigations_per_candidate": 1,
        "automatic_retries": 0,
    }
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def automatic_policy_validation_envelope(
    observation: Any,
    *,
    policy_version: str = POLICY_VERSION,
    parser_version_override: str | None = None,
) -> dict[str, Any]:
    """Build the exact, source-bound validation envelope used in policy receipts.

    Version 2 carries the two evidence records needed to interpret the specific
    red-card uncertainty warning. Other validations retain the v1 envelope shape
    so existing automatic publications remain reproducible.
    """

    from dataclasses import asdict

    validation = json.loads(json.dumps(asdict(observation.validation), ensure_ascii=False))
    parser_version = parser_version_override or getattr(observation.source, "parser_version", None)
    if not isinstance(parser_version, str) or not parser_version:
        raise ValueError("La observación no conserva la versión del parser")
    validation["parser_version"] = parser_version
    if (
        policy_version == POLICY_VERSION
        and SECOND_YELLOW_UNCERTAINTY_WARNING in validation.get("warnings", [])
    ):
        if parser_version != getattr(observation.source, "parser_version", None):
            raise ValueError("La evidencia TG2 debe conservar la versión del parser que la generó")
        evidence = []
        for item in getattr(observation, "evidence", ()):
            if getattr(item, "field_path", None) in {"events.red_cards", "events.second_yellows"}:
                evidence.append(asdict(item))
        source_hash = getattr(observation.source, "source_html_sha256", None)
        if (
            isinstance(source_hash, str)
            and len(source_hash) == 64
            and all(char in "0123456789abcdef" for char in source_hash)
            and len(evidence) == 2
        ):
            validation["source_html_sha256"] = source_hash
            validation["semantic_evidence"] = evidence
    return validation


def _second_yellow_uncertainty_is_supported(validation: dict[str, Any]) -> bool:
    evidence = validation.get("semantic_evidence")
    source_hash = validation.get("source_html_sha256")
    parser_version = validation.get("parser_version")
    if (
        not isinstance(evidence, list)
        or not isinstance(source_hash, str)
        or len(source_hash) != 64
        or any(char not in "0123456789abcdef" for char in source_hash)
        or not isinstance(parser_version, str)
        or not parser_version
    ):
        return False
    red_rows = [row for row in evidence if isinstance(row, dict) and row.get("field_path") == "events.red_cards"]
    second_yellow_rows = [row for row in evidence if isinstance(row, dict) and row.get("field_path") == "events.second_yellows"]
    if len(red_rows) != 1 or len(second_yellow_rows) != 1:
        return False
    red, second_yellow = red_rows[0], second_yellow_rows[0]
    if (
        red.get("state") != "not_observed"
        or red.get("source_reference") != _SECOND_YELLOW_RED_EVIDENCE_REFERENCE
        or not isinstance(red.get("raw_value"), str)
        or not red["raw_value"].strip()
        or red.get("normalized_value") is not None
        or second_yellow.get("state") != "observed"
        or second_yellow.get("source_reference") != "recognized lineup/substitute event cells; icon=TG2; title='Doble Tarjeta Amarilla'"
        or not isinstance(second_yellow.get("raw_value"), str)
        or not second_yellow["raw_value"].strip()
        or type(second_yellow.get("normalized_value")) is not int
        or second_yellow["normalized_value"] < 1
    ):
        return False
    return all(
        row.get("source_html_sha256") == source_hash
        and row.get("parser_version") == parser_version
        for row in (red, second_yellow)
    )


def automatic_publication_decision(
    validation: Any, *, policy_version: str = POLICY_VERSION
) -> tuple[bool, str | None]:
    """Return whether validation evidence satisfies this exact policy version."""

    if policy_version not in SUPPORTED_POLICY_VERSIONS:
        return False, "unsupported_automatic_publication_policy_version"
    if not isinstance(validation, dict) or validation.get("semantic_valid") is not True:
        return False, "semantic_validation_not_valid"
    errors = validation.get("errors")
    warnings = validation.get("warnings")
    checks = validation.get("checks")
    if not isinstance(errors, list) or errors:
        return False, "validation_errors_present_or_malformed"
    if not isinstance(warnings, list) or any(
        not isinstance(item, str) for item in warnings
    ):
        return False, "validation_warnings_malformed"
    non_blocking = set(NON_BLOCKING_WARNINGS)
    if SECOND_YELLOW_UNCERTAINTY_WARNING in warnings:
        if warnings.count(SECOND_YELLOW_UNCERTAINTY_WARNING) != 1:
            return False, "direct_red_card_uncertainty_warning_duplicated"
        if policy_version == POLICY_VERSION:
            if not _second_yellow_uncertainty_is_supported(validation):
                return False, "direct_red_card_uncertainty_lacks_source_bound_second_yellow_evidence"
            non_blocking.add(SECOND_YELLOW_UNCERTAINTY_WARNING)
    blocking_warnings = sorted(set(warnings) - non_blocking)
    if blocking_warnings:
        return False, "blocking_validation_warnings:" + ",".join(blocking_warnings)
    if not isinstance(checks, list) or not checks:
        return False, "validation_checks_missing"
    names: set[str] = set()
    for check in checks:
        if not isinstance(check, dict) or check.get("passed") is not True:
            return False, "failed_or_malformed_validation_check"
        # SemanticValidation serializes the domain field as ``check``. Keep
        # ``name`` accepted only for older/local policy fixtures, but always
        # evaluate the persisted real parser contract correctly.
        name = check.get("check", check.get("name"))
        if not isinstance(name, str) or not name:
            return False, "unnamed_validation_check"
        names.add(name)
    missing = REQUIRED_CHECKS - names
    if missing:
        return False, "required_validation_checks_missing:" + ",".join(sorted(missing))
    return True, None


def legacy_recovery_publication_decision(validation: Any) -> tuple[bool, str | None]:
    """Apply the same 17 checks to the one verified offline recovery case.

    The old INVALID_CONTENT warning is allowed only here because a separate
    recovery verifier binds the original diagnostic, checkpoint, HTML and
    generation hashes. No other warning is relaxed.
    """

    if not isinstance(validation, dict):
        return False, "semantic_validation_not_valid"
    warnings = validation.get("warnings")
    if not isinstance(warnings, list) or LEGACY_RECOVERY_WARNING not in warnings:
        return False, "expected_legacy_recovery_warning_missing"
    if warnings.count(LEGACY_RECOVERY_WARNING) != 1:
        return False, "legacy_recovery_warning_duplicated"
    adjusted = dict(validation)
    adjusted["warnings"] = [item for item in warnings if item != LEGACY_RECOVERY_WARNING]
    return automatic_publication_decision(adjusted, policy_version=POLICY_VERSION)
