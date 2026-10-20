from __future__ import annotations

import uuid

import pytest

from football_data_hub.providers.bdfutbol.match_details.automatic_publication_policy import (
    LEGACY_RECOVERY_WARNING,
    POLICY_ID,
    POLICY_VERSION,
    REQUIRED_CHECKS,
    SECOND_YELLOW_UNCERTAINTY_WARNING,
    automatic_publication_decision,
    candidate_set_sha256,
    legacy_recovery_publication_decision,
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


def _second_yellow_evidence(validation: dict) -> dict:
    validation = dict(validation)
    validation["parser_version"] = "match-detail-semantic-test"
    validation["source_html_sha256"] = "a" * 64
    validation["warnings"] = [SECOND_YELLOW_UNCERTAINTY_WARNING]
    common = {
        "source_html_sha256": "a" * 64,
        "parser_version": "match-detail-semantic-test",
    }
    validation["semantic_evidence"] = [
        {
            **common,
            "field_path": "events.red_cards",
            "state": "not_observed",
            "source_reference": "direct-red markers absent; second-yellow dismissal observed",
            "raw_value": "83",
            "normalized_value": None,
        },
        {
            **common,
            "field_path": "events.second_yellows",
            "state": "observed",
            "source_reference": "recognized lineup/substitute event cells; icon=TG2; title='Doble Tarjeta Amarilla'",
            "raw_value": "player_id=58463; minute=83; text=83",
            "normalized_value": 1,
        },
    ]
    return validation


def test_v2_allows_only_source_bound_second_yellow_uncertainty_without_asserting_no_direct_red() -> None:
    validation = _second_yellow_evidence(_validation())
    assert automatic_publication_decision(validation, policy_version="2") == (True, None)
    assert automatic_publication_decision(validation, policy_version="1")[0] is False

    missing = dict(validation)
    missing.pop("semantic_evidence")
    assert automatic_publication_decision(missing, policy_version="2")[0] is False

    forged_absence = dict(validation)
    forged_absence["semantic_evidence"] = [
        {**validation["semantic_evidence"][0], "state": "explicitly_absent"},
        validation["semantic_evidence"][1],
    ]
    assert automatic_publication_decision(forged_absence, policy_version="2")[0] is False

    wrong_source = dict(validation)
    wrong_source["semantic_evidence"] = [
        {**validation["semantic_evidence"][0], "source_html_sha256": "b" * 64},
        validation["semantic_evidence"][1],
    ]
    assert automatic_publication_decision(wrong_source, policy_version="2")[0] is False

    unknown_icons = dict(validation)
    unknown_icons["checks"] = [
        {**check, "passed": False} if check["check"] == "all_event_icons_recognized" else check
        for check in validation["checks"]
    ]
    assert automatic_publication_decision(unknown_icons, policy_version="2")[0] is False


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


def test_ledger_rejects_candidate_set_tampering_without_id_specific_exclusions() -> None:
    candidate = _candidate()
    campaign, event = _authorization_payload("f" * 64, candidate)
    with pytest.raises(MatchCampaignIntegrityError):
        OperationalMatchCampaignLedger._validate_event_payload(
            event, campaign, candidate["internal_id"], []
        )

    recovered = _candidate("272582")
    recovered_campaign, recovered_event = _authorization_payload("", recovered)
    # The ID is no longer rejected by a permanent code list. The regular
    # candidate-set digest and current evidence-based review state still gate
    # authorization in the operational caller. This payload is structurally
    # valid; the caller still refuses it while the recovery state is pending.
    OperationalMatchCampaignLedger._validate_event_payload(
        recovered_event, recovered_campaign, recovered["internal_id"], []
    )


def test_policy_version_and_identity_are_explicit() -> None:
    assert POLICY_ID == "football-data-hub.strict-match-details"
    assert POLICY_VERSION == "2"


def test_offline_legacy_recovery_relaxes_only_the_historic_access_warning() -> None:
    validation = _validation()
    validation["warnings"] = [LEGACY_RECOVERY_WARNING]
    assert legacy_recovery_publication_decision(validation) == (True, None)

    validation["warnings"].append("lineup_event_unresolved")
    assert legacy_recovery_publication_decision(validation)[0] is False

    validation["warnings"] = [LEGACY_RECOVERY_WARNING, LEGACY_RECOVERY_WARNING]
    assert legacy_recovery_publication_decision(validation) == (
        False,
        "legacy_recovery_warning_duplicated",
    )

    validation["warnings"] = []
    assert legacy_recovery_publication_decision(validation) == (
        False,
        "expected_legacy_recovery_warning_missing",
    )
