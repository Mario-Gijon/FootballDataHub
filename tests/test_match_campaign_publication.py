from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import football_data_hub_api.match_details_dataset as match_details_dataset
from football_data_hub_api.match_details_dataset import (
    CAMPAIGN_DRAFT_SCHEMA,
    MatchDetailsLoadError,
    build_campaign_approval_receipt,
    campaign_approval_confirmation,
    publish_campaign_match_detail_draft,
    write_immutable_publication_json,
    _campaign_draft_matches_revalidated_evidence,
    _campaign_published_document_matches_revalidated_evidence,
    _validate_campaign_observation_against_match,
)


def _draft() -> dict:
    value = {
        "schema_version": CAMPAIGN_DRAFT_SCHEMA,
        "publication_id": "campaign-272525-abcdef0123456789",
        "source_kind": "campaign_discovery",
        "internal_id": "pf-2026-27-group-ii-bdfutbol-272525",
        "source_match_id": "272525",
        "inventory_id": "match-detail-inventory-test0000000000",
        "source_generation_id": "match-00-test-generation",
        "source_generation_manifest_sha256": "c" * 64,
        "source_capture_id": "capture-II",
        "season": "2026-27",
        "competition": "Primera Federación",
        "group": "II",
        "matchday": 1,
        "source_match_date": "2026-08-31",
        "home_team_id": 204,
        "away_team_id": 61,
        "home_team_name": "Teruel",
        "away_team_name": "Real Madrid Castilla",
        "campaign_id": "match-detail-sample-campaign-67fdc4b4fac66b82",
        "artifact_id": "discovery-20261018T112656Z-4543b211",
        "navigation_attempt_id": "attempt-test-001",
        "artifact_manifest_sha256": "d" * 64,
        "source_html_sha256": "a" * 64,
        "details_sha256": "",
        "capture_promotion_enabled": False,
        "promotion_eligible": False,
        "access_status": "VALID",
        "semantic_valid": True,
        "details": {"source_html_sha256": "a" * 64, "home_goals": 0, "away_goals": 0},
    }
    canonical = json.dumps(value["details"], sort_keys=True, separators=(",", ":")).encode()
    value["details_sha256"] = hashlib.sha256(canonical).hexdigest()
    return value


def _approval_args(draft: dict) -> dict:
    return {
        "approved_by": "test reviewer",
        "confirm_internal_id": draft["internal_id"],
        "confirm_source_html_sha256": draft["source_html_sha256"],
        "confirm_details_sha256": draft["details_sha256"],
        "confirm_action": campaign_approval_confirmation(draft),
        "approved_at_utc": datetime(2026, 10, 18, 12, tzinfo=timezone.utc),
    }


def test_campaign_approval_is_bound_to_match_html_and_public_document() -> None:
    draft = _draft()
    receipt = build_campaign_approval_receipt(draft, **_approval_args(draft))

    assert receipt["publication_status"] == "approved"
    assert receipt["internal_id"] == draft["internal_id"]
    assert receipt["source_html_sha256"] == draft["source_html_sha256"]
    assert receipt["details_sha256"] == draft["details_sha256"]
    assert receipt["approval_confirmation"] == campaign_approval_confirmation(draft)
    assert receipt["approved_by"] == "test reviewer"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confirm_internal_id", "pf-2026-27-group-ii-bdfutbol-272582"),
        ("confirm_source_html_sha256", "c" * 64),
        ("confirm_details_sha256", "d" * 64),
        ("confirm_action", "APPROVE-SOMETHING-ELSE"),
        ("approved_by", "  "),
    ],
)
def test_campaign_approval_rejects_missing_or_contradictory_confirmation(field: str, value: str) -> None:
    draft = _draft()
    values = _approval_args(draft)
    values[field] = value

    with pytest.raises(MatchDetailsLoadError, match="aprobación"):
        build_campaign_approval_receipt(draft, **values)


def test_campaign_approval_rejects_modified_draft_content() -> None:
    draft = _draft()
    draft["details"]["home_goals"] = 1

    with pytest.raises(MatchDetailsLoadError, match="aprobación"):
        build_campaign_approval_receipt(draft, **_approval_args(draft))


def test_derived_drafts_are_immutable_and_never_overwrite(tmp_path) -> None:
    path = tmp_path / "draft.json"
    value = {"status": "prepared", "source_html_sha256": "a" * 64}

    assert write_immutable_publication_json(path, value) == path
    with pytest.raises(MatchDetailsLoadError, match="No se sobrescribe"):
        write_immutable_publication_json(path, {"status": "different"})


def test_derived_draft_rejects_symlink_before_creating_any_output(tmp_path) -> None:
    outside = tmp_path / "outside"
    link = tmp_path / "linked-output"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(MatchDetailsLoadError, match="symlinks"):
        write_immutable_publication_json(link / "nested" / "draft.json", {"status": "prepared"})

    assert not outside.exists()


def test_campaign_observation_with_invalid_semantics_cannot_be_published() -> None:
    observation = SimpleNamespace(
        source=SimpleNamespace(),
        context=SimpleNamespace(),
        validation=SimpleNamespace(semantic_valid=False),
    )
    with pytest.raises(MatchDetailsLoadError, match="validación semántica"):
        _validate_campaign_observation_against_match(
            observation,
            {},
            SimpleNamespace(match=SimpleNamespace()),
        )


def _event_details() -> dict:
    return {
        "source_html_sha256": "a" * 64,
        "home_goals": 1,
        "away_goals": 0,
        "events": [
            {
                "event_kind": "goal",
                "minute": "54",
                "team_id": 204,
                "player_id": 123,
                "is_own_goal": False,
                "source_description": None,
            }
        ],
    }


def _rehashed_draft(value: dict) -> dict:
    value["details_sha256"] = hashlib.sha256(
        json.dumps(value["details"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return value


def test_campaign_revalidation_allows_only_legacy_nullable_event_metadata_drift() -> None:
    saved = _draft()
    saved["details"] = _event_details()
    _rehashed_draft(saved)
    rebuilt = json.loads(json.dumps(saved))
    rebuilt["details"]["events"][0].pop("source_description")
    rebuilt["details"]["events"][0]["is_own_goal"] = None
    _rehashed_draft(rebuilt)

    assert _campaign_draft_matches_revalidated_evidence(saved, rebuilt)


@pytest.mark.parametrize(
    ("mutate", "description"),
    [
        (lambda value: value["details"].update(home_goals=2), "score change"),
        (lambda value: value["details"]["events"][0].update(minute="55"), "event minute change"),
        (lambda value: value["details"]["events"][0].update(event_kind="own_goal", is_own_goal=True), "event kind change"),
        (lambda value: value["details"]["events"][0].update(is_own_goal=True), "own-goal flag change"),
        (lambda value: value["details"]["events"][0].update(source_description="changed"), "description change"),
        (lambda value: value.update(source_html_sha256="b" * 64), "source identity change"),
    ],
)
def test_campaign_revalidation_rejects_sports_or_source_changes(mutate, description: str) -> None:
    saved = _draft()
    saved["details"] = _event_details()
    _rehashed_draft(saved)
    rebuilt = json.loads(json.dumps(saved))
    mutate(rebuilt)
    _rehashed_draft(rebuilt)

    assert not _campaign_draft_matches_revalidated_evidence(saved, rebuilt), description


def test_campaign_revalidation_rejects_corrupt_draft_hash() -> None:
    saved = _draft()
    saved["details"] = _event_details()
    _rehashed_draft(saved)
    rebuilt = json.loads(json.dumps(saved))
    rebuilt["details"]["events"][0].pop("source_description")
    rebuilt["details"]["events"][0]["is_own_goal"] = None
    _rehashed_draft(rebuilt)
    saved["details"]["home_goals"] = 2

    assert not _campaign_draft_matches_revalidated_evidence(saved, rebuilt)


def test_campaign_package_read_revalidation_accepts_legacy_nullable_fields() -> None:
    saved_details = _event_details()
    rebuilt = _draft()
    rebuilt["details"] = json.loads(json.dumps(saved_details))
    rebuilt["details"]["events"][0].pop("source_description")
    rebuilt["details"]["events"][0]["is_own_goal"] = None
    _rehashed_draft(rebuilt)
    saved_details_sha = hashlib.sha256(
        json.dumps(saved_details, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    document = SimpleNamespace(model_dump=lambda **_kwargs: json.loads(json.dumps(saved_details)))

    assert _campaign_published_document_matches_revalidated_evidence(
        document, saved_details, saved_details_sha, rebuilt
    )

    changed = json.loads(json.dumps(saved_details))
    changed["events"][0]["minute"] = "55"
    changed_sha = hashlib.sha256(
        json.dumps(changed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    changed_document = SimpleNamespace(model_dump=lambda **_kwargs: json.loads(json.dumps(changed)))
    assert not _campaign_published_document_matches_revalidated_evidence(
        changed_document, changed, changed_sha, rebuilt
    )


def test_campaign_publication_preserves_the_exact_reviewed_legacy_document(tmp_path, monkeypatch) -> None:
    saved = _draft()
    saved["details"] = _event_details()
    _rehashed_draft(saved)
    rebuilt = json.loads(json.dumps(saved))
    rebuilt["details"]["events"][0].pop("source_description")
    rebuilt["details"]["events"][0]["is_own_goal"] = None
    _rehashed_draft(rebuilt)
    receipt = build_campaign_approval_receipt(saved, **_approval_args(saved))

    monkeypatch.setattr(match_details_dataset, "build_campaign_publication_draft", lambda **_kwargs: rebuilt)
    loader_calls = 0

    def fail_then_load(*_args, **_kwargs):
        nonlocal loader_calls
        loader_calls += 1
        if loader_calls == 1:
            raise MatchDetailsLoadError("simulated read-back interruption")
        return {saved["internal_id"]: object()}

    monkeypatch.setattr(match_details_dataset, "load_published_match_details", fail_then_load)
    with pytest.raises(MatchDetailsLoadError, match="simulated read-back interruption"):
        publish_campaign_match_detail_draft(
            saved,
            approval_receipt=receipt,
            published_root=tmp_path / "published",
            store_root=tmp_path / "source-store",
            generation_root=tmp_path / "generation",
            data_root=tmp_path / "data",
            match_bundle=SimpleNamespace(),
            player_ids=set(),
        )
    index_path = tmp_path / "published" / "index.json"
    assert not index_path.exists()
    orphan = tmp_path / "published" / "packages" / saved["publication_id"]
    assert json.loads((orphan / "details.json").read_text()) == saved["details"]

    result = publish_campaign_match_detail_draft(
        saved,
        approval_receipt=receipt,
        published_root=tmp_path / "published",
        store_root=tmp_path / "source-store",
        generation_root=tmp_path / "generation",
        data_root=tmp_path / "data",
        match_bundle=SimpleNamespace(),
        player_ids=set(),
    )

    assert result["internal_id"] == saved["internal_id"]
    package = tmp_path / "published" / "packages" / saved["publication_id"]
    assert json.loads((package / "details.json").read_text()) == saved["details"]
    assert json.loads((package / "approval.json").read_text()) == receipt
    manifest = json.loads((package / "manifest.json").read_text())
    assert manifest["details_sha256"] == saved["details_sha256"]
