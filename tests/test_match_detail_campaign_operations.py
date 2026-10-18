from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from football_data_hub.providers.bdfutbol.match_details.campaign import MatchCampaignIntegrityError
from football_data_hub.providers.bdfutbol.match_details import campaign_operations as operations


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _candidate(index: int, group: str, state: str) -> dict:
    source_id = str(270000 + index)
    return {
        "internal_id": f"pf-2026-27-group-{group.lower()}-bdfutbol-{source_id}",
        "source_match_id": source_id,
        "group": group,
        "matchday": index % 6 + 1,
        "competition": "Primera Federación",
        "season": "2026-27",
        "source_match_date": None,
        "matchday_date": "2026-10-10",
        "home_team_name": f"Local {index}",
        "home_team_id": 100 + index,
        "away_team_name": f"Visitante {index}",
        "away_team_id": 200 + index,
        "reference_result": {"home_goals": index % 4, "away_goals": (index + 1) % 4},
        "source_match_url": f"https://www.bdfutbol.com/es/p/p.php?id={source_id}",
        "source_generation_id": "match-00-test-generation",
        "source_generation_manifest_sha256": "f" * 64,
        "source_capture_id": "capture-test",
        "source_captured_at_utc": "2026-10-14T10:00:00Z",
        "source_snapshot_sha256": "d" * 64,
        "source_matches_sha256": "e" * 64,
        "campaign_id": "match-detail-campaign-v2-0123456789abcdef",
        "state": state,
        "artifact": {
            "artifact_id": f"discovery-test-{index}",
            "source_html_sha256": hashlib.sha256(f"html-{index}".encode()).hexdigest(),
        } if state in {"DISCOVERY_REVIEW_REQUIRED", "VALIDATED", "REVALIDATED", "DRAFT_PREPARED", "VALIDATION_FAILED"} else None,
    }


class _FakeLedger:
    def __init__(self, root: Path, candidates: list[dict]):
        self.root = root / "campaigns"
        self.root.mkdir(parents=True)
        self.states = {row["internal_id"]: row["state"] for row in candidates}
        self.rows = {row["internal_id"]: copy.deepcopy(row) for row in candidates}
        self.calls: list[tuple[str, str]] = []
        self.validate_outcomes = {}
        self.raise_after_validate_for: set[str] = set()
        self.validation_errors = set()
        self.lock = SimpleNamespace(
            exclusive_lock=lambda: operations._null_test_lock(),
            shared_lock=lambda: operations._null_test_lock(),
        )

    def preflight(self, campaign_id, *, acquire_lock=True):
        return {"campaign_id": campaign_id, "candidate_count": len(self.rows), "candidates": [
            {**copy.deepcopy(row), "state": self.states[key], "artifact": row.get("artifact")}
            for key, row in self.rows.items()
        ]}

    def candidate_events(self, campaign_id, internal_id):
        state = self.states[internal_id]
        return [{"event_type": state, "internal_id": internal_id}] if state != "NOT_AUTHORIZED" else []

    @staticmethod
    def _state(events):
        return events[-1]["event_type"] if events else "NOT_AUTHORIZED"

    def validate_offline_artifact(self, *, campaign_id, internal_id, data_root):
        self.calls.append(("validate", internal_id))
        outcome = self.validate_outcomes.get(internal_id, "VALIDATED")
        if internal_id in self.raise_after_validate_for:
            self.states[internal_id] = "VALIDATED"
            raise RuntimeError("interrupted after durable validation")
        self.states[internal_id] = outcome
        return {
            "status": outcome,
            "source_html_sha256": self.rows[internal_id]["artifact"]["source_html_sha256"],
            "evidence_sha256": hashlib.sha256((internal_id + outcome).encode()).hexdigest(),
            "diagnostic": "unknown event icon" if internal_id in self.validation_errors else None,
        }

    def prepare_draft(self, *, campaign_id, internal_id, **kwargs):
        self.calls.append(("prepare", internal_id))
        if self.states[internal_id] not in {"VALIDATED", "REVALIDATED", "DRAFT_PREPARED"}:
            raise ValueError("not validated")
        self.states[internal_id] = "DRAFT_PREPARED"
        return {"status": "DRAFT_PREPARED", "draft_sha256": hashlib.sha256(internal_id.encode()).hexdigest()}

    def generation_root(self, campaign_id, data_root):
        return Path(data_root)

    def candidate(self, campaign_id, internal_id):
        return {"internal_id": internal_id, "state": self.states[internal_id]}


@pytest.fixture
def _null_test_lock(monkeypatch):
    class Lock:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(operations, "_null_test_lock", Lock, raising=False)
    return Lock


def _mixed_candidates() -> list[dict]:
    states = [
        "DISCOVERY_REVIEW_REQUIRED",  # valid saved HTML
        "DISCOVERY_REVIEW_REQUIRED",  # malformed/invalid saved HTML
        "DISCOVERY_REVIEW_REQUIRED",  # unknown icon
        "DISCOVERY_REVIEW_REQUIRED",  # TG2 recognized by the official parser
        "DISCOVERY_REVIEW_REQUIRED",
        "VALIDATED",
        "REVALIDATED",
        "DRAFT_PREPARED",
        "VALIDATION_FAILED",
        "REVALIDATION_FAILED",
        "STOPPED",
        "INTERRUPTED_REQUIRES_REVIEW",
        "DOCUMENT_APPROVED",
        "PUBLISHED",
        "REVIEW_COMPLETED",
        "AUTHORIZED",
        "NOT_AUTHORIZED",
    ]
    return [_candidate(index + 1, "I" if index % 2 == 0 else "II", state) for index, state in enumerate(states)]


def test_offline_batch_handles_mixed_candidates_and_resumes_without_duplicate_effects(tmp_path, _null_test_lock):
    candidates = _mixed_candidates()
    ledger = _FakeLedger(tmp_path / "store", candidates)
    ledger.validate_outcomes[candidates[1]["internal_id"]] = "VALIDATION_FAILED"
    ledger.validate_outcomes[candidates[2]["internal_id"]] = "VALIDATION_FAILED"
    ledger.validation_errors.add(candidates[2]["internal_id"])
    ledger.raise_after_validate_for.add(candidates[4]["internal_id"])
    kwargs = {
        "ledger": ledger,
        "campaign_id": candidates[0]["campaign_id"],
        "data_root": tmp_path,
        "player_inventory_root": tmp_path,
        "player_compact_root": tmp_path,
        "player_team_captures_root": tmp_path,
        "player_published_index_path": tmp_path / "players.json",
    }

    first = operations.run_offline_batch(**kwargs)
    first_by_id = {item["internal_id"]: item for item in first["candidates"]}
    assert first["status"] == "COMPLETED_WITH_ERRORS"
    assert first["candidate_count"] == 17
    assert first_by_id[candidates[0]["internal_id"]]["status"] == "DRAFT_PREPARED"
    assert first_by_id[candidates[1]["internal_id"]]["status"] == "VALIDATION_FAILED"
    assert first_by_id[candidates[2]["internal_id"]]["status"] == "VALIDATION_FAILED"
    assert first_by_id[candidates[3]["internal_id"]]["status"] == "DRAFT_PREPARED"
    assert first_by_id[candidates[4]["internal_id"]]["status"] == "CANDIDATE_ERROR"
    assert ledger.states[candidates[4]["internal_id"]] == "VALIDATED"
    assert ledger.states[candidates[5]["internal_id"]] == "DRAFT_PREPARED"
    assert ledger.states[candidates[6]["internal_id"]] == "DRAFT_PREPARED"
    assert ledger.states[candidates[7]["internal_id"]] == "DRAFT_PREPARED"
    assert ledger.states[candidates[8]["internal_id"]] == "VALIDATION_FAILED"
    assert ledger.states[candidates[9]["internal_id"]] == "REVALIDATION_FAILED"
    assert ledger.states[candidates[10]["internal_id"]] == "STOPPED"
    assert ledger.states[candidates[11]["internal_id"]] == "INTERRUPTED_REQUIRES_REVIEW"
    assert ledger.states[candidates[12]["internal_id"]] == "DOCUMENT_APPROVED"
    assert ledger.states[candidates[13]["internal_id"]] == "PUBLISHED"
    assert ledger.states[candidates[14]["internal_id"]] == "REVIEW_COMPLETED"
    assert first["http_enabled"] is False and first["navigation_enabled"] is False
    assert operations.load_operation_report(Path(first["report_path"]))["run_id"] == first["run_id"]

    validate_before = sum(call[0] == "validate" for call in ledger.calls)
    second = operations.run_offline_batch(**kwargs)
    assert second["status"] == "COMPLETED"
    assert second["prepared_count"] == 1  # resumes from the durable VALIDATED state
    assert sum(call[0] == "validate" for call in ledger.calls) == validate_before
    assert ledger.calls.count(("prepare", candidates[4]["internal_id"])) == 1
    assert all(item["status"] == "PROTECTED_STATE_SKIPPED" for item in second["candidates"] if item["state_before"] in {"VALIDATION_FAILED", "REVALIDATION_FAILED", "STOPPED", "INTERRUPTED_REQUIRES_REVIEW", "DOCUMENT_APPROVED", "PUBLISHED", "REVIEW_COMPLETED", "AUTHORIZED", "NOT_AUTHORIZED"})
    calls_after_resume = list(ledger.calls)
    third = operations.run_offline_batch(**kwargs)
    assert third["status"] == "COMPLETED"
    assert third["prepared_count"] == 0
    assert ledger.calls == calls_after_resume


def test_batch_preflight_and_worklist_keep_exact_states_and_coverage(tmp_path, _null_test_lock):
    candidates = _mixed_candidates()
    ledger = _FakeLedger(tmp_path / "store", candidates)
    preflight = operations.build_batch_preflight(ledger, candidates[0]["campaign_id"])
    assert len(preflight["actions"]) == 17
    assert preflight["actions"][0]["action"] == "validate_saved_artifact_then_prepare_if_valid"
    assert preflight["actions"][9]["action"] == "manual_review_no_automatic_retry"
    assert preflight["actions"][12]["action"] == "explicit_publication_queue_only"

    rows = []
    for candidate in candidates:
        rows.append({
            **candidate,
            "detail_status": "captured_pending_validation" if candidate["state"] == "DISCOVERY_REVIEW_REQUIRED" else "played_pending_acquisition",
            "published_approved": candidate["state"] in {"PUBLISHED", "REVIEW_COMPLETED"},
            "campaign": {"campaign_id": candidate["campaign_id"], "state": candidate["state"]},
            "next_safe_operation": "validate_offline_artifact",
            "blocked_reasons": [],
        })
    report = operations.build_worklist({"source": {"generation_id": "fixture"}, "matches": rows})
    assert report["counts_by_exact_state"]["DISCOVERY_REVIEW_REQUIRED"] == 5
    assert report["coverage_by_group"]["I"]["metrics"]["registered"] == 9
    assert all(row["source_match_url"].startswith("https://") for row in report["matches"])
    assert report["matches"][0]["campaign_ids"] == [candidates[0]["campaign_id"]]
    assert report["navigation_enabled"] is False


def test_batch_fails_closed_on_campaign_integrity_and_lock_contention(tmp_path, _null_test_lock):
    candidates = _mixed_candidates()
    ledger = _FakeLedger(tmp_path / "store", candidates)
    ledger.preflight = lambda _campaign: (_ for _ in ()).throw(MatchCampaignIntegrityError("bad chain"))
    args = {
        "ledger": ledger,
        "campaign_id": candidates[0]["campaign_id"],
        "data_root": tmp_path,
        "player_inventory_root": tmp_path,
        "player_compact_root": tmp_path,
        "player_team_captures_root": tmp_path,
        "player_published_index_path": tmp_path / "players.json",
    }
    with pytest.raises(MatchCampaignIntegrityError):
        operations.run_offline_batch(**args)
    assert ledger.calls == []

    real_ledger_root = tmp_path / "actual-store" / "campaigns"
    real_ledger_root.mkdir(parents=True)
    ledger.root = real_ledger_root
    with operations._batch_lock(real_ledger_root.parent), pytest.raises(operations.CampaignOperationsError, match="otro lote"):
        with operations._batch_lock(real_ledger_root.parent):
            pass


def test_operation_report_hash_detects_tampering_and_atomic_writer_leaves_previous_run_readable(tmp_path, monkeypatch):
    report_root = tmp_path / "store" / "operations" / "reports" / "campaign"
    report = {"run_id": "test-run", "status": "RUNNING", "candidates": []}
    path = operations._write_report(report_root, report)
    assert operations.load_operation_report(path) == report
    before = path.read_bytes()
    report["status"] = "COMPLETED"
    original_replace = operations.os.replace
    monkeypatch.setattr(operations.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("interrupted rename")))
    with pytest.raises(OSError, match="interrupted"):
        operations._write_report(report_root, report)
    assert path.read_bytes() == before
    assert operations.load_operation_report(path)["status"] == "RUNNING"
    monkeypatch.setattr(operations.os, "replace", original_replace)


def test_publish_approved_requires_explicit_confirmation_and_never_completes_review(tmp_path, _null_test_lock):
    candidate = _candidate(1, "I", "DOCUMENT_APPROVED")
    ledger = _FakeLedger(tmp_path / "store", [candidate])
    common = {
        "ledger": ledger,
        "campaign_id": candidate["campaign_id"],
        "data_root": tmp_path,
        "generation_root": tmp_path,
        "published_root": tmp_path / "published",
        "store_root": tmp_path / "store",
        "player_inventory_root": tmp_path,
        "player_compact_root": tmp_path,
        "player_team_captures_root": tmp_path,
        "player_published_index_path": tmp_path / "players.json",
    }
    with pytest.raises(operations.CampaignOperationsError, match="confirmación"):
        operations.publish_approved_batch(**common, confirmation="")
    assert not hasattr(ledger, "publish")


def test_explicit_publication_queue_publishes_only_approved_and_never_closes_review(tmp_path, _null_test_lock):
    approved = _candidate(1, "I", "DOCUMENT_APPROVED")
    ready = _FakeLedger(tmp_path / "store", [approved])
    calls = []

    def publish(*, campaign_id, internal_id, **_kwargs):
        calls.append(("publish", internal_id))
        ready.states[internal_id] = "PUBLISHED"
        return {"status": "PUBLISHED", "internal_id": internal_id}

    def verify_publication(*, campaign_id, internal_id, **_kwargs):
        calls.append(("verify", internal_id))
        return {"status": "PUBLISHED_VERIFIED", "internal_id": internal_id}

    ready.publish = publish
    ready.verify_publication = verify_publication
    ready.complete_review = lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not complete review"))
    report = operations.publish_approved_batch(
        ledger=ready,
        campaign_id=approved["campaign_id"],
        confirmation=operations.PUBLISH_CONFIRMATION,
        data_root=tmp_path,
        generation_root=tmp_path,
        published_root=tmp_path / "published",
        store_root=tmp_path / "store",
        player_inventory_root=tmp_path,
        player_compact_root=tmp_path,
        player_team_captures_root=tmp_path,
        player_published_index_path=tmp_path / "players.json",
    )
    assert report["status"] == "COMPLETED"
    assert report["candidates"][0]["status"] == "PUBLISHED_VERIFIED"
    assert calls == [("publish", approved["internal_id"]), ("verify", approved["internal_id"])]
    assert report["human_approval_created"] is False
    assert report["review_completion_created"] is False


def test_publication_queue_lists_only_individually_approved_documents(tmp_path, _null_test_lock):
    approved = _candidate(1, "I", "DOCUMENT_APPROVED")
    pending = _candidate(2, "II", "DRAFT_PREPARED")
    ledger = _FakeLedger(tmp_path / "store", [approved, pending])

    def candidate_events(_campaign_id, internal_id):
        if internal_id == approved["internal_id"]:
            return [
                {"event_type": "DRAFT_PREPARED", "draft_sha256": "a" * 64, "details_sha256": "b" * 64},
                {"event_type": "DOCUMENT_APPROVED", "approved_by": "reviewer", "approval_sha256": "c" * 64},
            ]
        return [{"event_type": "DRAFT_PREPARED"}]

    ledger.candidate_events = candidate_events
    queue = operations.build_publication_queue(ledger, approved["campaign_id"])
    assert [item["internal_id"] for item in queue] == [approved["internal_id"]]
    assert queue[0]["next_operation"] == "publish_then_verify"
    assert queue[0]["approval_sha256"] == "c" * 64


def test_review_queue_exposes_readable_summary_and_hash_bound_artifact_paths(tmp_path, _null_test_lock):
    candidate = _candidate(1, "II", "DRAFT_PREPARED")
    ledger = _FakeLedger(tmp_path / "store", [candidate])
    draft_path = tmp_path / "draft.json"
    draft = {
        "internal_id": candidate["internal_id"],
        "semantic_valid": True,
        "source_html_sha256": "a" * 64,
        "details_sha256": "b" * 64,
        "details": {
            "home_goals": 2,
            "away_goals": 1,
            "match_date": None,
            "kickoff_time_local": None,
            "home": {"coach": None, "starters": [], "substitutes": []},
            "away": {"coach": None, "starters": [], "substitutes": []},
            "events": [],
        },
    }
    draft_path.write_bytes(_canonical(draft))
    artifact_dir = ledger.root / candidate["campaign_id"] / "candidates" / candidate["internal_id"] / "artifacts"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "source.html").write_text("<html>evidence</html>", encoding="utf-8")
    (artifact_dir / "manifest.json").write_text("{}", encoding="utf-8")
    ledger.preflight = lambda _campaign_id, **_kwargs: {"candidates": [{**candidate, "state": "DRAFT_PREPARED"}]}
    ledger.candidate_events = lambda _campaign_id, _internal_id: [
        {"event_type": "DISCOVERY_REVIEW_REQUIRED", "artifact": {"artifact_relative_path": f"candidates/{candidate['internal_id']}/artifacts/discovery-test-1"}},
        {"event_type": "VALIDATED", "validation": {"semantic_valid": True, "errors": [], "checks": [{"name": "identity", "status": "verified"}]}},
        {"event_type": "DRAFT_PREPARED", "draft_path": "draft.json", "draft_sha256": _sha(draft_path.read_bytes()), "details_sha256": "b" * 64},
    ]
    queue = operations.build_review_queue(ledger, candidate["campaign_id"], tmp_path)
    assert len(queue) == 1
    assert queue[0]["observed_result"] == {"home_goals": 2, "away_goals": 1}
    assert queue[0]["approval_pending"] is True
    assert queue[0]["draft_sha256"] == _sha(draft_path.read_bytes())
    assert queue[0]["warnings"] == []

    ledger.candidate_events = lambda _campaign_id, _internal_id: [
        {"event_type": "DISCOVERY_REVIEW_REQUIRED", "artifact": {"artifact_relative_path": "candidates/test/artifacts/discovery-test-1"}},
        {"event_type": "VALIDATED", "validation": {"semantic_valid": True, "errors": [], "checks": []}},
        {"event_type": "DRAFT_PREPARED", "draft_path": "../draft.json", "draft_sha256": _sha(draft_path.read_bytes()), "details_sha256": "b" * 64},
    ]
    with pytest.raises(MatchCampaignIntegrityError, match="relativa"):
        operations.build_review_queue(ledger, candidate["campaign_id"], tmp_path)


def test_proposal_sizes_are_deterministic_and_skip_reserved_or_blocked_rows():
    from football_data_hub.providers.bdfutbol.match_details.scalable_campaigns import build_match_campaign_proposal

    rows = []
    for index in range(55):
        candidate = _candidate(index + 1, "I" if index % 2 == 0 else "II", "NOT_AUTHORIZED")
        candidate.update({"detail_status": "played_pending_acquisition", "source_generation_manifest_sha256": "c" * 64,
                         "source_capture_id": "capture", "source_snapshot_sha256": "d" * 64,
                         "source_matches_sha256": "e" * 64})
        rows.append(candidate)
    rows[4]["detail_status"] = "published_approved"
    rows[5]["detail_status"] = "blocked_requires_human_review"
    base = {"source": {"generation_id": "match-00-test", "generation_manifest_sha256": "f" * 64}, "matches": rows}
    for limit in (10, 20, 30, 50):
        first = build_match_campaign_proposal(base, limit=limit)
        second = build_match_campaign_proposal(base, limit=limit)
        assert first["proposal_id"] == second["proposal_id"]
        assert first["candidate_count"] == limit
        assert all(row["detail_status"] == "played_pending_acquisition" for row in first["candidates"])


def test_operation_report_rejects_non_object_envelope(tmp_path):
    path = tmp_path / "report.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(operations.CampaignOperationsError, match="objeto"):
        operations.load_operation_report(path)


def test_review_index_accepts_v2_campaign_directory_and_rejects_unknown_entries(tmp_path):
    from football_data_hub.providers.bdfutbol.match_details.scalable_campaign_cli import _review_state_ids
    from football_data_hub.providers.bdfutbol.match_details.scalable_campaigns import ScalableCampaignError

    store_root = tmp_path / "matches" / "details"
    (store_root / "review" / "v2" / "match-detail-campaign-v2-0123456789abcdef").mkdir(parents=True)
    result = _review_state_ids(
        store_root=store_root,
        generation_root=tmp_path / "generation",
        data_root=tmp_path,
        bundle=SimpleNamespace(),
        player_ids=set(),
        published_ids=set(),
    )
    assert result == (set(), set(), {})

    (store_root / "review" / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(ScalableCampaignError, match="Entrada inesperada"):
        _review_state_ids(
            store_root=store_root,
            generation_root=tmp_path / "generation",
            data_root=tmp_path,
            bundle=SimpleNamespace(),
            player_ids=set(),
            published_ids=set(),
        )




def test_read_only_ledger_lock_uses_existing_file_and_never_creates_one(tmp_path):
    from football_data_hub.providers.bdfutbol.match_details.campaign import MatchDetailCampaignLedger
    from football_data_hub.providers.bdfutbol.match_details.campaign import MatchCampaignIntegrityError

    root = tmp_path / "campaigns"
    root.mkdir()
    ledger = MatchDetailCampaignLedger(root)
    with pytest.raises(MatchCampaignIntegrityError, match="Falta campaign-ledger.lock"):
        with ledger.shared_lock():
            pass
    assert not (root / "campaign-ledger.lock").exists()

    lock_path = root / "campaign-ledger.lock"
    lock_path.write_bytes(b"existing lock bytes")
    with ledger.shared_lock():
        assert lock_path.read_bytes() == b"existing lock bytes"
    assert lock_path.read_bytes() == b"existing lock bytes"
