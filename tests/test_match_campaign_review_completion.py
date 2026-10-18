from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from football_data_hub.providers.bdfutbol.match_details.campaign import (
    HUMAN_AUTHORIZATION_CONFIRMATION,
    MatchCampaignAuthorizationError,
    MatchCampaignIntegrityError,
    MatchDetailCampaignLedger,
    SimulatedAccessResponse,
    SimulatedMatchAccessAdapter,
    _campaign_spec,
    review_completion_confirmation,
)
from football_data_hub.providers.bdfutbol.match_details.review_completion import (
    complete_published_discovery_review,
)
from tests.test_match_detail_campaign import _add_review, _authorize, _plan, _plan_ids


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _tree_hashes(root):
    return {
        path.relative_to(root).as_posix(): _sha(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _prepare(tmp_path, monkeypatch, *, published=True, approval_match_id=None):
    import football_data_hub.providers.bdfutbol.match_details.review_completion as completion

    data_root = tmp_path / "FootballDataHub-data"
    details_root = data_root / "matches" / "details"
    campaign_root = details_root / "campaigns"
    published_root = details_root / "published"
    generation_root = data_root / "matches" / "generations" / "generation-fixture"
    player_paths = [
        data_root / "players/inventory-2026-27",
        data_root / "players/compact-2026-27",
        data_root / "team-captures",
    ]
    player_index = data_root / "published/team_profiles_2026-27.json"
    for path in [generation_root, *player_paths, published_root]:
        path.mkdir(parents=True, exist_ok=True)
    player_index.parent.mkdir(parents=True, exist_ok=True)
    player_index.write_bytes(_canonical({"schema_version": "test"}))
    (published_root / ".publication.lock").touch()

    plan = _plan()
    ledger = MatchDetailCampaignLedger(campaign_root)
    review_id = _add_review(ledger, plan)
    _authorize(ledger, plan, review_id)
    internal_id, url = _plan_ids(plan)
    result = ledger.run_simulated_candidate(
        plan,
        internal_id=internal_id,
        adapter=SimulatedMatchAccessAdapter(
            SimulatedAccessResponse(
                final_url=url,
                http_status=200,
                html=b"<html><body>test discovery artifact</body></html>",
                page_title="synthetic fixture",
                access_classification="VALID",
            )
        ),
    )
    assert result["status"] == "DISCOVERY_REVIEW_REQUIRED"
    spec = _campaign_spec(plan)
    candidate = spec["candidates"][0]
    events = ledger._read_events(
        ledger._candidate_dir(ledger._campaign_dir(spec), internal_id),
        spec["campaign_id"],
        internal_id,
    )
    start = events[1]
    discovery = events[2]
    artifact = discovery["artifact"]

    details = {"publication_status": "approved", "fixture": "offline-only"}
    details_sha = _sha(_canonical(details))
    publication_id = "campaign-272525-offline-fixture"
    manifest = {
        "schema_version": "football_data_hub.match_detail_campaign_publication.v1",
        "publication_id": publication_id,
        "internal_id": internal_id,
        "source_match_id": candidate["source_match_id"],
        "group": candidate["group"],
        "source_capture_id": candidate["source_capture_id"],
        "campaign_id": spec["campaign_id"],
        "inventory_id": spec["source"]["inventory_id"],
        "source_generation_id": spec["source"]["generation_id"],
        "source_generation_manifest_sha256": spec["source"]["generation_manifest_sha256"],
        "navigation_attempt_id": start["attempt_id"],
        "artifact_id": artifact["artifact_id"],
        "artifact_manifest_sha256": artifact["manifest_sha256"],
        "source_html_sha256": artifact["source_html_sha256"],
        "details_sha256": details_sha,
    }
    approval = {
        "schema_version": "football_data_hub.match_detail_campaign_approval.v1",
        "publication_status": "approved",
        "approved_by": "pytest fixture; not a human approval",
        **{key: value for key, value in manifest.items() if key != "schema_version"},
    }
    approval_raw = _canonical(approval)
    manifest["approval_sha256"] = _sha(approval_raw)
    package = published_root / "packages" / publication_id
    package.mkdir(parents=True)
    manifest_raw = _canonical(manifest)
    (package / "manifest.json").write_bytes(manifest_raw)
    (package / "approval.json").write_bytes(approval_raw)
    (package / "details.json").write_bytes(_canonical(details))
    if published:
        index = {
            "schema_version": "football_data_hub.match_detail_publication_index.v1",
            "publications": [
                {
                    "internal_id": internal_id,
                    "publication_id": publication_id,
                    "package_path": f"packages/{publication_id}",
                    "manifest_sha256": _sha(manifest_raw),
                }
            ],
        }
        (published_root / "index.json").write_bytes(_canonical(index))
    else:
        (published_root / "index.json").write_bytes(
            _canonical(
                {
                    "schema_version": "football_data_hub.match_detail_publication_index.v1",
                    "publications": [],
                }
            )
        )
    if approval_match_id is not None:
        approval["internal_id"] = approval_match_id
        approval_raw = _canonical(approval)
        manifest["approval_sha256"] = _sha(approval_raw)
        manifest_raw = _canonical(manifest)
        (package / "approval.json").write_bytes(approval_raw)
        (package / "manifest.json").write_bytes(manifest_raw)
        if published:
            index["publications"][0]["manifest_sha256"] = _sha(manifest_raw)
            (published_root / "index.json").write_bytes(_canonical(index))

    class Document:
        publication_status = "approved"

        @staticmethod
        def model_dump(*, mode):
            assert mode == "json"
            return details

    monkeypatch.setattr(completion, "load_match_results_dataset", lambda *a, **k: object())
    monkeypatch.setattr(
        completion,
        "load_player_directory",
        lambda **kwargs: SimpleNamespace(players_by_id={}),
    )
    monkeypatch.setattr(
        completion,
        "load_published_match_details",
        lambda *a, **k: {internal_id: Document()} if published else {},
    )
    arguments = {
        "plan": plan,
        "ledger": ledger,
        "internal_id": internal_id,
        "reviewer": "offline operator fixture",
        "confirmation": review_completion_confirmation(
            candidate["source_match_id"], artifact["source_html_sha256"], details_sha
        ),
        "data_root": data_root,
        "generation_root": generation_root,
        "published_root": published_root,
        "player_inventory_root": player_paths[0],
        "player_compact_root": player_paths[1],
        "player_team_captures_root": player_paths[2],
        "player_published_index_path": player_index,
    }
    return arguments, published_root, ledger, plan, internal_id, details_sha


def test_published_review_closes_append_only_and_preflight_allows_next_candidate(tmp_path, monkeypatch):
    args, published_root, ledger, plan, internal_id, details_sha = _prepare(tmp_path, monkeypatch)
    spec = _campaign_spec(plan)
    candidate_dir = ledger._candidate_dir(ledger._campaign_dir(spec), internal_id)
    campaign_dir = ledger._campaign_dir(spec)
    campaign_before = _tree_hashes(campaign_dir)
    publication_before = _tree_hashes(published_root)

    result = complete_published_discovery_review(**args)
    assert result["status"] == "REVIEW_COMPLETED"
    assert result["idempotent"] is False
    report = ledger.preflight(plan)
    candidate = report["candidates"][0]
    assert report["status"] == "READY_FOR_FUTURE_HUMAN_AUTHORIZATION"
    assert report["blocked_reasons"] == []
    assert candidate["state"] == "REVIEW_COMPLETED"
    assert candidate["acquisition_state"] == "DISCOVERY_REVIEW_REQUIRED"
    assert candidate["review_status"] == "completed"
    assert candidate["navigation_count"] == 1
    assert all(item["state"] == "NOT_AUTHORIZED" for item in report["candidates"][1:])

    events = ledger._read_events(candidate_dir, spec["campaign_id"], internal_id)
    assert [event["event_type"] for event in events] == [
        "AUTHORIZED", "STARTED", "DISCOVERY_REVIEW_REQUIRED", "REVIEW_COMPLETED"
    ]
    assert events[2]["event_type"] == "DISCOVERY_REVIEW_REQUIRED"
    assert events[3]["publication_evidence"]["details_sha256"] == details_sha
    campaign_after = _tree_hashes(campaign_dir)
    assert all(campaign_after[path] == digest for path, digest in campaign_before.items())
    new_campaign_files = set(campaign_after) - set(campaign_before)
    assert len(new_campaign_files) == 1
    assert next(iter(new_campaign_files)).startswith(
        f"candidates/{internal_id}/events/000004-"
    )
    assert _tree_hashes(published_root) == publication_before

    # The discovery artifact reader accepts both its original acquisition
    # sequence and that same sequence followed by the new operational event.
    import football_data_hub.providers.bdfutbol.match_details.campaign_artifact as artifact_reader

    artifact_reader._validate_discovery_event_sequence(events[:3])
    artifact_reader._validate_discovery_event_sequence(events)
    with pytest.raises(artifact_reader.CampaignArtifactError, match="secuencia"):
        artifact_reader._validate_discovery_event_sequence(events + [{"event_type": "AUTHORIZED"}])

    after_first = sorted(path.name for path in (candidate_dir / "events").glob("*.json"))
    repeated = complete_published_discovery_review(**args)
    after_second = sorted(path.name for path in (candidate_dir / "events").glob("*.json"))
    assert repeated["status"] == "REVIEW_ALREADY_COMPLETED"
    assert repeated["idempotent"] is True
    assert after_second == after_first
    assert len(after_second) == 4
    review_id = ledger.preflight(plan)["historical_review"]["review_id"]
    with pytest.raises(MatchCampaignAuthorizationError, match="consumió"):
        _authorize(ledger, plan, review_id)

    # The completed first candidate unblocks campaign preflight, but does not
    # authorize or navigate the next one. A separate explicit authorization is
    # still required and is exercised only against this temporary ledger.
    import football_data_hub.providers.bdfutbol.match_details.historical_review as review_module

    review = ledger._read_reviews(campaign_dir, spec)[0]
    monkeypatch.setattr(
        review_module,
        "verify_historical_stop_evidence",
        lambda *a, **k: review["evidence_verification"],
    )
    second = plan["candidates"][1]
    inventory_dir = args["data_root"] / "matches/details/inventories" / spec["source"]["inventory_id"]
    inventory_dir.mkdir(parents=True, exist_ok=True)
    authorization_id = ledger.authorize_candidate(
        plan,
        internal_id=second["internal_id"],
        reviewer="offline second-candidate authorizer",
        review_id=review_id,
        confirmed_url=second["source_match_url"],
        data_root=args["data_root"],
        generation_root=args["generation_root"],
        inventory_dir=inventory_dir,
        store_root=args["data_root"] / "matches/details",
        confirmation=HUMAN_AUTHORIZATION_CONFIRMATION,
    )
    assert authorization_id.startswith("match-detail-authorization-")
    resumed = ledger.preflight(plan)
    assert resumed["status"] == "READY_FOR_FUTURE_HUMAN_AUTHORIZATION"
    assert resumed["candidates"][1]["state"] == "AUTHORIZED"
    assert resumed["candidates"][1]["navigation_count"] == 0


def test_acquired_but_unpublished_candidate_cannot_close(tmp_path, monkeypatch):
    args, _, ledger, plan, _, _ = _prepare(tmp_path, monkeypatch, published=False)
    with pytest.raises(MatchCampaignAuthorizationError, match="publicación activa aprobada"):
        complete_published_discovery_review(**args)
    assert ledger.preflight(plan)["candidates"][0]["state"] == "DISCOVERY_REVIEW_REQUIRED"


def test_corrupt_discovery_evidence_blocks_review_closure(tmp_path, monkeypatch):
    args, _, ledger, plan, internal_id, _ = _prepare(tmp_path, monkeypatch)
    spec = _campaign_spec(plan)
    events = ledger._read_events(ledger._candidate_dir(ledger._campaign_dir(spec), internal_id), spec["campaign_id"], internal_id)
    artifact_dir = ledger._candidate_dir(ledger._campaign_dir(spec), internal_id) / events[2]["artifact"]["artifact_relative_path"].removeprefix(f"candidates/{internal_id}/")
    (artifact_dir / "source.html").write_bytes(b"tampered")
    with pytest.raises(MatchCampaignIntegrityError):
        complete_published_discovery_review(**args)


def test_approval_for_another_match_and_wrong_confirmation_are_rejected(tmp_path, monkeypatch):
    args, _, ledger, plan, internal_id, _ = _prepare(
        tmp_path, monkeypatch, approval_match_id="pf-2026-27-group-ii-bdfutbol-272517"
    )
    with pytest.raises(MatchCampaignIntegrityError, match="no coincide"):
        complete_published_discovery_review(**args)
    assert ledger.preflight(plan)["candidates"][0]["state"] == "DISCOVERY_REVIEW_REQUIRED"

    args, _, ledger, plan, _, _ = _prepare(tmp_path / "wrong-confirm", monkeypatch)
    args["confirmation"] = "COMPLETE-REVIEW-272525-wrong-wrong"
    with pytest.raises(MatchCampaignAuthorizationError, match="confirmación"):
        complete_published_discovery_review(**args)
    assert ledger.preflight(plan)["candidates"][0]["state"] == "DISCOVERY_REVIEW_REQUIRED"


def test_publication_without_approved_receipt_is_an_incomplete_review(tmp_path, monkeypatch):
    args, published_root, ledger, plan, internal_id, _ = _prepare(tmp_path, monkeypatch)
    index = json.loads((published_root / "index.json").read_text())
    entry = index["publications"][0]
    package = published_root / entry["package_path"]
    approval = json.loads((package / "approval.json").read_text())
    approval["publication_status"] = "pending"
    approval_raw = _canonical(approval)
    (package / "approval.json").write_bytes(approval_raw)
    manifest = json.loads((package / "manifest.json").read_text())
    manifest["approval_sha256"] = _sha(approval_raw)
    manifest_raw = _canonical(manifest)
    (package / "manifest.json").write_bytes(manifest_raw)
    entry["manifest_sha256"] = _sha(manifest_raw)
    (published_root / "index.json").write_bytes(_canonical(index))

    with pytest.raises(MatchCampaignIntegrityError, match="no coincide"):
        complete_published_discovery_review(**args)
    assert ledger.preflight(plan)["candidates"][0]["state"] == "DISCOVERY_REVIEW_REQUIRED"


def test_incomplete_review_cannot_close_even_if_other_candidate_is_unpublished(tmp_path, monkeypatch):
    import football_data_hub.providers.bdfutbol.match_details.campaign as campaign_module

    args, _, ledger, plan, internal_id, _ = _prepare(tmp_path, monkeypatch)
    spec = campaign_module._campaign_spec(plan)
    candidate_dir = ledger._candidate_dir(ledger._campaign_dir(spec), internal_id)
    event_paths = sorted((candidate_dir / "events").glob("*.json"))
    event_paths[-1].unlink()
    with pytest.raises(MatchCampaignIntegrityError):
        complete_published_discovery_review(**args)
