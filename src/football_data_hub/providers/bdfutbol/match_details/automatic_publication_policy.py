"""Strict, versioned automatic publication policy for the local update button.

This policy is deliberately not a human approval. Its receipt schema, actor,
validation evidence and audit events are distinct from the campaign's human
approval flow. Parser warnings that indicate an uncertain sporting fact keep a
document pending; only two known informational absences are non-blocking.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

POLICY_ID = "football-data-hub.strict-match-details"
POLICY_VERSION = "1"
# Explicitly unresolved discovery from earlier MATCH work; never candidate for
# the automatic route until its block is resolved through the established path.
BLOCKED_SOURCE_MATCH_IDS = frozenset({"272582"})
NON_BLOCKING_WARNINGS = frozenset(
    {
        "campaign_discovery_remains_unpromoted_pending_independent_review",
        "ephemerides_not_observed",
    }
)
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
) -> str:
    """Hash the exact, ordered candidates covered by one global update job."""

    body = {
        "schema_version": "football_data_hub.match_detail_update_candidate_set.v1",
        "update_job_id": update_job_id,
        "policy_id": POLICY_ID,
        "policy_version": POLICY_VERSION,
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


def automatic_publication_decision(validation: Any) -> tuple[bool, str | None]:
    """Return whether validation evidence satisfies this exact policy version."""

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
    blocking_warnings = sorted(set(warnings) - NON_BLOCKING_WARNINGS)
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
