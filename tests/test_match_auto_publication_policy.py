from __future__ import annotations

import uuid

import pytest

from football_data_hub.providers.bdfutbol.match_details.automatic_publication_policy import (
    BLOCKED_SOURCE_MATCH_IDS,
    POLICY_ID,
    POLICY_VERSION,
    REQUIRED_CHECKS,
    automatic_publication_decision,
    candidate_set_sha256,
)
from football_data_hub.providers.bdfutbol.match_details.campaign import MatchCampaignIntegrityError
from football_data_hub.providers.bdfutbol.match_details.operational_campaign import (
    AUTO_UPDATE_AUTHORIZATION_SCHEMA,
    OperationalMatchCampaignLedger,
)


def _validation() -> dict:
    return {
        "semantic_valid": True,
        "errors": [],
        "warnings": ["campaign_discovery_remains_unpromoted_pending_independent_review"],
        "checks": [{"check": name, "passed": True, "detail": "verified"} for name in sorted(REQUIRED_CHECKS)],
    }


def _candidate(source_match_id: str = "272590") -> dict:
    return {
        "internal_id": f"pf-2026-27-group-ii-bdfutbol-{source_match_id}",
        "source_match_id": source_match_id,
        "source_match_url": f"https://www.bdfutbol.com/es/p/p.php?id={source_match_id}",
        "group": "II",
        "matchday": 8,
        "reference_result": {"home_goals": 1, "away_goals": 0},
        "matchday_date": "2026-10-18",
    }


def _authorization_payload(candidate_set: str, candidate: dict) -> tuple[dict, dict]:
    campaign_id = "match-detail-campaign-v2-0123456789abcdef"
    generation_id = "match-00-test-generation"
    generation_sha = "a" * 64
    update_job_id = str(uuid.uuid4())
    candidate_record = {**candidate, "source_generation_id": generation_id}
    expected_digest = candidate_set_sha256(
        update_job_id=update_job_id,
        campaign_id=campaign_id,
        source_generation_id=generation_id,
        source_generation_manifest_sha256=generation_sha,
        candidates=[candidate_record],
    )
    auth_id = "match-detail-update-authorization-v1-" + uuid.uuid4().hex
    campaign = {
        "campaign_id": campaign_id,
        "proposal_sha256": "b" * 64,
        "source": {"generation_id": generation_id, "generation_manifest_sha256": generation_sha},
        "candidates": [candidate_record],
    }
    event = {
        "event_type": "AUTO_POLICY_AUTHORIZED",
        "campaign_id": campaign_id,
        "internal_id": candidate["internal_id"],
        "authorization": {
            "schema_version": AUTO_UPDATE_AUTHORIZATION_SCHEMA,
            "authorization_mode": "competition_update_auto_policy",
            "authorization_id": auth_id,
            "update_job_id": update_job_id,
            "candidate_set_sha256": candidate_set or expected_digest,
            "campaign_id": campaign_id,
            "proposal_sha256": campaign["proposal_sha256"],
            "source_generation_id": generation_id,
            "source_generation_manifest_sha256": generation_sha,
            "internal_id": candidate["internal_id"],
            "source_match_id": candidate["source_match_id"],
            "source_match_url": candidate["source_match_url"],
            "authorized_at_utc": "2026-10-20T10:00:00Z",
            "maximum_navigations": 1,
            "automatic_retries": 0,
            "capture_promotion_enabled": False,
            "human_approval": False,
        },
    }
    return campaign, event


def test_strict_policy_allows_only_complete_validation_with_known_informational_warnings() -> None:
    assert automatic_publication_decision(_validation()) == (True, None)

    warning = _validation()
    warning["warnings"].append("lineup_event_unresolved")
    assert automatic_publication_decision(warning)[0] is False

    missing_check = _validation()
    missing_check["checks"] = [check for check in missing_check["checks"] if check["check"] != "score_matches_catalog"]
    assert "required_validation_checks_missing" in automatic_publication_decision(missing_check)[1]

    invalid = _validation()
    invalid["errors"].append("score_catalog_mismatch")
    assert automatic_publication_decision(invalid)[0] is False


def test_candidate_set_hash_is_bound_to_job_identity_and_exact_candidates() -> None:
    row = _candidate()
    common = {
        "campaign_id": "match-detail-campaign-v2-0123456789abcdef",
        "source_generation_id": "generation-a",
        "source_generation_manifest_sha256": "a" * 64,
        "candidates": [row],
    }
    first = candidate_set_sha256(update_job_id=str(uuid.uuid4()), **common)
    second = candidate_set_sha256(update_job_id=str(uuid.uuid4()), **common)
    changed = candidate_set_sha256(
        update_job_id=str(uuid.uuid4()), **{**common, "candidates": [{**row, "reference_result": {"home_goals": 2, "away_goals": 0}}]}
    )
    assert first != second
    assert first != changed


def test_ledger_rejects_candidate_set_tampering_and_the_blocked_match() -> None:
    candidate = _candidate()
    campaign, event = _authorization_payload("f" * 64, candidate)
    with pytest.raises(MatchCampaignIntegrityError):
        OperationalMatchCampaignLedger._validate_event_payload(
            event, campaign, candidate["internal_id"], []
        )

    blocked = _candidate(next(iter(BLOCKED_SOURCE_MATCH_IDS)))
    blocked_campaign, blocked_event = _authorization_payload("", blocked)
    with pytest.raises(MatchCampaignIntegrityError):
        OperationalMatchCampaignLedger._validate_event_payload(
            blocked_event, blocked_campaign, blocked["internal_id"], []
        )


def test_policy_version_and_identity_are_explicit() -> None:
    assert POLICY_ID == "football-data-hub.strict-match-details"
    assert POLICY_VERSION == "1"
