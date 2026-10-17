from __future__ import annotations

import hashlib
import json

import pytest

from football_data_hub.providers.bdfutbol.match_details.campaign import (
    HUMAN_AUTHORIZATION_CONFIRMATION,
    HUMAN_REVIEW_CONFIRMATION,
    MatchCampaignAuthorizationError,
    MatchCampaignError,
    MatchCampaignIntegrityError,
    MatchCampaignLocked,
    MatchDetailCampaignLedger,
    SimulatedAccessResponse,
    SimulatedMatchAccessAdapter,
)


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _plan():
    """Canonical shape only; no score, match date, or real page data is fabricated."""

    generation_id = "match-00-4ad1d610507e425d"
    generation_sha = "00166887b13413e3e6a5344fa1c64d52db8d38800f3ef9f282237584b3e65fbf"
    inventory_id = "match-detail-inventory-8cf339654c80c0ef"
    inventory_sha = "9be747311ff237235b21e27c064d486d4ce990c3278d9020bae816968aabac08"
    inventory_manifest_sha = "e31b4ad341c87634b8f1cc032e02acae40d7de94f5a0de9e23a0a58ee3056b2b"
    ids = (
        ("272525", "II"),
        ("272517", "II"),
        ("272577", "II"),
        ("272524", "II"),
        ("269411", "I"),
    )
    candidates = []
    for source_id, group in ids:
        candidates.append(
            {
                "source_match_id": source_id,
                "internal_id": f"pf-2026-27-group-{group.lower()}-bdfutbol-{source_id}",
                "group": group,
                "source_match_url": f"https://www.bdfutbol.com/es/p/p.php?id={source_id}",
                "source_generation_id": generation_id,
                "source_generation_manifest_sha256": generation_sha,
                "source_capture_id": f"synthetic-capture-{group.lower()}",
                "source_snapshot_sha256": "a" * 64,
                "source_matches_sha256": "b" * 64,
            }
        )
    basis = {
        "inventory_id": inventory_id,
        "inventory_sha256": inventory_sha,
        "source_generation_id": generation_id,
        "source_generation_manifest_sha256": generation_sha,
        "selected_internal_ids": [item["internal_id"] for item in candidates],
    }
    campaign_id = "match-detail-sample-campaign-" + _sha(_canonical(basis))[:16]
    diagnostic = {
        "source_match_id": "272582",
        "internal_id": "pf-2026-27-group-ii-bdfutbol-272582",
        "http_status": 200,
        "error_code": "IDENTITY_OR_CONTENT_UNVERIFIED",
        "navigation_attempt_id": "synthetic-original-attempt-reference",
        "stop_acquisition": True,
    }
    plan = {
        "schema_version": "football_data_hub.match_detail_sampling_plan.v1",
        "mode": "offline_read_only_sample_plan",
        "http_enabled": False,
        "browser_started": False,
        "navigation_enabled": False,
        "promotion_enabled": False,
        "status": "BLOCKED",
        "source": {
            "competition": "Primera Federación",
            "season": "2026-27",
            "generation_id": generation_id,
            "generation_manifest_sha256": generation_sha,
            "generation_sources": {"I": {}, "II": {}},
            "inventory_id": inventory_id,
            "inventory_sha256": inventory_sha,
            "inventory_manifest_sha256": inventory_manifest_sha,
            "record_count": 760,
        },
        "selection_policy": {"maximum_candidates": 5},
        "candidates": candidates,
        "campaign": {
            "campaign_id": campaign_id,
            "campaign_basis": basis,
            "is_authorization": False,
            "authorization_status": "NOT_AUTHORIZED",
            "requires_explicit_review_of_legacy_stop": True,
            "legacy_pilot_stop": {
                "checkpoint_status": "stopped",
                "checkpoint_revision": 4,
                "checkpoint_sha256": "d129476f2caebe1a9876fefe3a86cf6facf7254c96262a1ee4996855713e06f0",
                "active_stop": True,
                "diagnostic": diagnostic,
                "checkpoint_modified": False,
            },
        },
        "blocked_reasons": ["legacy_match_store_active_stop_requires_explicit_review"],
    }
    plan["campaign_digest"] = _sha(_canonical(plan))
    return plan


def _plan_ids(plan):
    first = plan["candidates"][0]
    return first["internal_id"], first["source_match_url"]


def _add_review(ledger, plan, *, decision="scope_to_original_pilot"):
    """Seed an explicitly synthetic review record for state-machine unit tests."""

    import football_data_hub.providers.bdfutbol.match_details.campaign as module

    reference = plan["campaign"]["legacy_pilot_stop"]
    diagnostic = reference["diagnostic"]
    spec = module._campaign_spec(plan)
    campaign_dir = ledger.initialize(plan)
    evidence = {
        "evidence_schema": "football_data_hub.match_detail_legacy_stop_evidence.v1",
        "inventory_id": spec["source"]["inventory_id"],
        "generation_id": spec["source"]["generation_id"],
        "generation_manifest_sha256": spec["source"]["generation_manifest_sha256"],
        "source_match_id": "272582",
        "internal_id": "pf-2026-27-group-ii-bdfutbol-272582",
        "original_attempt_id": diagnostic["navigation_attempt_id"],
        "checkpoint_sha256": reference["checkpoint_sha256"],
        "checkpoint_revision": reference["checkpoint_revision"],
        "diagnostic_sha256": _sha(_canonical(diagnostic)),
        # Synthetically shaped like the durable artifact reference; no real
        # artifact is read or modified by these state-machine tests.
        "artifact_id": "20000101T000000.000000Z-00000000",
        "artifact_relative_path": (
            f"diagnostics/{spec['source']['inventory_id']}/"
            "20000101T000000.000000Z-00000000"
        ),
        "artifact_manifest_sha256": "c" * 64,
        "source_html_sha256": "d" * 64,
        "parser_version": "synthetic-test-only",
        "semantic_valid": True,
        "promotion_eligible": False,
    }
    payload = {
        "schema_version": module.CAMPAIGN_REVIEW_SCHEMA,
        "campaign_id": spec["campaign_id"],
        "legacy_stop_reference": spec["legacy_stop_review_reference"],
        "decision": decision,
        "reviewer": "offline synthetic reviewer",
        "reviewed_at_utc": "2026-10-17T10:00:00Z",
        "human_confirmation": HUMAN_REVIEW_CONFIRMATION,
        "evidence_verification": evidence,
        "authorizes_any_navigation": False,
    }
    review_id = "legacy-stop-review-" + _sha(_canonical(payload))[:16]
    review = {**payload, "review_id": review_id}
    review_raw = _canonical(review)
    manifest = {
        "schema_version": module.CAMPAIGN_REVIEW_MANIFEST_SCHEMA,
        "review_id": review_id,
        "review_sha256": _sha(review_raw),
        "campaign_id": spec["campaign_id"],
    }
    target = campaign_dir / "reviews/legacy-stop" / review_id
    if target.exists():
        raise MatchCampaignAuthorizationError("Ya existe una revisión histórica")
    target.mkdir(parents=True)
    (target / "review.json").write_bytes(review_raw)
    (target / "manifest.json").write_bytes(_canonical(manifest))
    return review_id


def _authorize(ledger, plan, review_id):
    import football_data_hub.providers.bdfutbol.match_details.campaign as module

    internal_id, url = _plan_ids(plan)
    spec = module._campaign_spec(plan)
    campaign_dir = ledger.initialize(plan)
    preflight = ledger.preflight(plan)
    if preflight["blocked_reasons"]:
        raise MatchCampaignAuthorizationError(
            f"La campaña está bloqueada: {preflight['blocked_reasons']}"
        )
    reviews = ledger._read_reviews(campaign_dir, spec)
    matching = [item for item in reviews if item["review_id"] == review_id]
    if len(matching) != 1 or matching[0]["decision"] != "scope_to_original_pilot":
        raise MatchCampaignAuthorizationError("Falta revisión histórica de prueba")
    if ledger._read_events(
        ledger._candidate_dir(campaign_dir, internal_id), spec["campaign_id"], internal_id
    ):
        raise MatchCampaignAuthorizationError("El candidato ya se consumió")
    authorization_id = "match-detail-authorization-synthetic"
    with ledger.exclusive_lock():
        ledger._append_event_locked(
            campaign_dir,
            spec,
            internal_id,
            {
                "event_type": "AUTHORIZED",
                "authorization": {
                    "authorization_id": authorization_id,
                    "campaign_id": spec["campaign_id"],
                    "inventory_id": spec["source"]["inventory_id"],
                    "inventory_sha256": spec["source"]["inventory_sha256"],
                    "inventory_manifest_sha256": spec["source"]["inventory_manifest_sha256"],
                    "source_generation_id": spec["source"]["generation_id"],
                    "source_generation_manifest_sha256": spec["source"]["generation_manifest_sha256"],
                    "internal_id": internal_id,
                    "source_match_id": "272525",
                    "source_match_url": url,
                    "review_id": review_id,
                    "reviewer": "offline synthetic authorizer",
                    "authorized_at_utc": "2026-10-17T10:01:00Z",
                    "maximum_navigations": 1,
                    "automatic_retries": 0,
                    "capture_promotion_enabled": False,
                    "human_confirmation": HUMAN_AUTHORIZATION_CONFIRMATION,
                },
            },
        )
    return authorization_id


def _response(
    url,
    *,
    status=200,
    final_url=None,
    html=b"<html><body>synthetic fixture</body></html>",
    **kwargs,
):
    return SimulatedAccessResponse(
        final_url=final_url or url, http_status=status, html=html, **kwargs
    )


def test_preflight_is_read_only_and_first_canonical_candidate_is_not_authorized(tmp_path):
    plan = _plan()
    root = tmp_path / "campaigns"
    ledger = MatchDetailCampaignLedger(root)
    before = list(root.iterdir()) if root.exists() else None

    result = ledger.preflight(plan)

    assert result["status"] == "BLOCKED"
    assert result["blocked_reasons"] == ["LEGACY_STOP_REVIEW_REQUIRED"]
    assert result["candidates"][0]["source_match_id"] == "272525"
    assert result["candidates"][0]["state"] == "NOT_AUTHORIZED"
    assert result["navigation_enabled"] is False
    assert result["real_access_adapter_enabled"] is False
    assert not root.exists()
    assert before is None


def test_campaign_operations_never_modify_the_historical_checkpoint(tmp_path):
    plan = _plan()
    legacy_checkpoint = tmp_path / "legacy-match-01b" / "states" / "checkpoint.json"
    legacy_checkpoint.parent.mkdir(parents=True)
    original = b'{"inventory_id":"historical","status":"stopped","revision":4}\n'
    legacy_checkpoint.write_bytes(original)
    reference = plan["campaign"]["legacy_pilot_stop"]
    reference["checkpoint_sha256"] = _sha(original)
    plan["campaign_digest"] = _sha(
        _canonical({key: value for key, value in plan.items() if key != "campaign_digest"})
    )
    ledger = MatchDetailCampaignLedger(tmp_path / "campaigns")
    ledger.initialize(plan)
    review_id = _add_review(ledger, plan)
    _authorize(ledger, plan, review_id)
    internal_id, url = _plan_ids(plan)
    ledger.run_simulated_candidate(
        plan,
        internal_id=internal_id,
        adapter=SimulatedMatchAccessAdapter(_response(url)),
    )
    assert legacy_checkpoint.read_bytes() == original


def test_plan_tampering_or_noncanonical_selection_is_rejected(tmp_path):
    plan = _plan()
    plan["candidates"][0]["source_match_url"] += "&other=1"
    ledger = MatchDetailCampaignLedger(tmp_path / "campaigns")
    with pytest.raises(MatchCampaignError):
        ledger.preflight(plan)


def test_historical_review_api_does_not_accept_caller_supplied_bytes_and_hashes(tmp_path):
    plan = _plan()
    ledger = MatchDetailCampaignLedger(tmp_path / "campaigns")
    with pytest.raises(TypeError):
        ledger.append_legacy_stop_review(
            plan,
            reviewer="reviewer",
            decision="scope_to_original_pilot",
            checkpoint_sha256="0" * 64,
            original_attempt_id="caller-supplied",
            original_diagnostic_sha256="1" * 64,
            semantic_evidence_reference="fixture://evidence",
            semantic_evidence_sha256="c" * 64,
            semantic_evidence_bytes=b"caller supplied evidence",
            confirmation=HUMAN_REVIEW_CONFIRMATION,
        )
    assert not (tmp_path / "campaigns").exists()


def test_plan_and_campaign_identity_are_immutable_and_review_is_append_only(tmp_path):
    plan = _plan()
    ledger = MatchDetailCampaignLedger(tmp_path / "campaigns")
    first = ledger.initialize(plan)
    assert ledger.initialize(plan) == first
    review_id = _add_review(ledger, plan)
    review_path = first / "reviews/legacy-stop" / review_id / "review.json"
    review_bytes = review_path.read_bytes()
    with pytest.raises(MatchCampaignAuthorizationError, match="Ya existe"):
        _add_review(ledger, plan)
    assert review_path.read_bytes() == review_bytes
    assert json.loads((first / "campaign.json").read_text())["campaign_id"] == plan["campaign"]["campaign_id"]


def test_authorization_contract_is_exact_and_candidate_defaults_remain_unapproved(tmp_path):
    plan = _plan()
    ledger = MatchDetailCampaignLedger(tmp_path / "campaigns")
    with pytest.raises(MatchCampaignAuthorizationError):
        _authorize(ledger, plan, "missing-review")
    review_id = _add_review(ledger, plan)
    authorization_id = _authorize(ledger, plan, review_id)
    report = ledger.preflight(plan)
    assert report["candidates"][0]["state"] == "AUTHORIZED"
    assert all(item["state"] == "NOT_AUTHORIZED" for item in report["candidates"][1:])
    assert authorization_id.startswith("match-detail-authorization-")
    events = next((tmp_path / "campaigns" / plan["campaign"]["campaign_id"] / "candidates" / plan["candidates"][0]["internal_id"] / "events").glob("*.json"))
    auth = json.loads(events.read_text())["payload"]["authorization"]
    assert auth["maximum_navigations"] == 1
    assert auth["automatic_retries"] == 0
    assert auth["capture_promotion_enabled"] is False


def test_simulated_272525_http_200_unexpected_content_is_discovery_only(tmp_path):
    plan = _plan()
    ledger = MatchDetailCampaignLedger(tmp_path / "campaigns")
    review_id = _add_review(ledger, plan)
    _authorize(ledger, plan, review_id)
    internal_id, url = _plan_ids(plan)
    # Fixture has no claimed BDFutbol identity or sporting facts.
    adapter = SimulatedMatchAccessAdapter(
        _response(
            url,
            html=b"<html><head><title>synthetic mismatch</title></head><body>unrelated fixture</body></html>",
            access_classification="unexpected_content",
        )
    )

    result = ledger.run_simulated_candidate(plan, internal_id=internal_id, adapter=adapter)

    assert result["status"] == "DISCOVERY_REVIEW_REQUIRED"
    assert result["capture_promoted"] is False
    assert adapter.calls == [url]
    report = ledger.preflight(plan)
    assert report["candidates"][0]["state"] == "DISCOVERY_REVIEW_REQUIRED"
    assert report["candidates"][0]["navigation_count"] == 1
    artifact_path = tmp_path / "campaigns" / plan["campaign"]["campaign_id"] / result["artifact"]["artifact_relative_path"]
    metadata = json.loads((artifact_path / "metadata.json").read_text())
    assert metadata["semantic_identity_verified"] is False
    assert metadata["capture_promoted"] is False
    assert _sha((artifact_path / "source.html").read_bytes()) == result["artifact"]["source_html_sha256"]
    assert not (tmp_path / "campaigns" / "captures").exists()


@pytest.mark.parametrize(
    ("kwargs", "expected_code"),
    [
        ({"status": 403}, "HTTP_403"),
        ({"status": 429}, "HTTP_429"),
        ({"status": 503}, "HTTP_503"),
        ({"status": 200, "challenge_detected": True}, "CHALLENGE_REQUIRED"),
        ({"status": 200, "denial_detected": True}, "ACCESS_DENIED"),
        ({"status": 200, "final_url": "https://example.invalid/redirect"}, "UNEXPECTED_URL"),
        ({"status": None}, "HTTP_UNKNOWN"),
        ({"status": 200, "html": b""}, "DOCUMENT_OR_STRUCTURE_ERROR"),
    ],
)
def test_simulated_security_failures_stop_and_consume_authorization(tmp_path, kwargs, expected_code):
    plan = _plan()
    ledger = MatchDetailCampaignLedger(tmp_path / "campaigns")
    review_id = _add_review(ledger, plan)
    _authorize(ledger, plan, review_id)
    internal_id, url = _plan_ids(plan)
    response_kwargs = dict(kwargs)
    final_url = response_kwargs.pop("final_url", url)
    adapter = SimulatedMatchAccessAdapter(
        _response(url, final_url=final_url, **response_kwargs)
    )

    result = ledger.run_simulated_candidate(plan, internal_id=internal_id, adapter=adapter)

    assert result["status"] == "STOPPED"
    assert result["error_code"] == expected_code
    assert adapter.calls == [url]
    assert ledger.preflight(plan)["candidates"][0]["state"] == "STOPPED"
    assert ledger.preflight(plan)["candidates"][0]["authorization_consumed"] is True
    assert all(
        item["state"] == "NOT_AUTHORIZED"
        for item in ledger.preflight(plan)["candidates"][1:]
    )
    with pytest.raises(MatchCampaignAuthorizationError):
        _authorize(ledger, plan, review_id)


def test_simulated_timeout_is_recorded_without_http_and_cannot_be_retried(tmp_path):
    plan = _plan()
    ledger = MatchDetailCampaignLedger(tmp_path / "campaigns")
    review_id = _add_review(ledger, plan)
    _authorize(ledger, plan, review_id)
    internal_id, url = _plan_ids(plan)
    adapter = SimulatedMatchAccessAdapter(error=TimeoutError("synthetic timeout"))

    result = ledger.run_simulated_candidate(plan, internal_id=internal_id, adapter=adapter)

    assert result["error_code"] == "SIMULATED_ACCESS_ERROR"
    assert adapter.calls == [url]
    events = sorted((tmp_path / "campaigns" / plan["campaign"]["campaign_id"] / "candidates" / internal_id / "events").glob("*.json"))
    stopped = json.loads(events[-1].read_text())["payload"]
    assert stopped["error_type"] == "TimeoutError"
    assert stopped["http_status"] is None
    assert ledger.preflight(plan)["candidates"][0]["state"] == "STOPPED"


def test_expected_http_200_is_still_diagnostic_only_and_duplicate_attempt_is_rejected(tmp_path):
    plan = _plan()
    ledger = MatchDetailCampaignLedger(tmp_path / "campaigns")
    review_id = _add_review(ledger, plan)
    _authorize(ledger, plan, review_id)
    internal_id, url = _plan_ids(plan)
    adapter = SimulatedMatchAccessAdapter(
        _response(url, access_classification="expected_content")
    )
    result = ledger.run_simulated_candidate(plan, internal_id=internal_id, adapter=adapter)
    assert result["status"] == "DISCOVERY_REVIEW_REQUIRED"
    assert adapter.calls == [url]
    second = SimulatedMatchAccessAdapter(_response(url))
    with pytest.raises(MatchCampaignAuthorizationError):
        ledger.run_simulated_candidate(plan, internal_id=internal_id, adapter=second)
    assert second.calls == []


def test_abrupt_interruption_is_durable_and_new_process_cannot_navigate_again(tmp_path):
    class Abrupt(BaseException):
        pass

    plan = _plan()
    root = tmp_path / "campaigns"
    ledger = MatchDetailCampaignLedger(root)
    review_id = _add_review(ledger, plan)
    _authorize(ledger, plan, review_id)
    internal_id, url = _plan_ids(plan)
    first = SimulatedMatchAccessAdapter(error=Abrupt("simulated process death"))
    with pytest.raises(Abrupt):
        ledger.run_simulated_candidate(plan, internal_id=internal_id, adapter=first)
    assert first.calls == [url]

    resumed = MatchDetailCampaignLedger(root).preflight(plan)
    assert resumed["candidates"][0]["state"] == "INTERRUPTED_REQUIRES_REVIEW"
    second = SimulatedMatchAccessAdapter(_response(url))
    with pytest.raises(MatchCampaignAuthorizationError):
        MatchDetailCampaignLedger(root).run_simulated_candidate(
            plan, internal_id=internal_id, adapter=second
        )
    assert second.calls == []


def test_storage_failure_before_durable_reservation_never_calls_adapter(tmp_path, monkeypatch):
    import football_data_hub.providers.bdfutbol.match_details.campaign as module

    plan = _plan()
    root = tmp_path / "campaigns"
    ledger = MatchDetailCampaignLedger(root)
    review_id = _add_review(ledger, plan)
    _authorize(ledger, plan, review_id)
    internal_id, url = _plan_ids(plan)
    adapter = SimulatedMatchAccessAdapter(_response(url))
    original = module._atomic_create

    def fail_started(path, raw):
        if b'"event_type": "STARTED"' in raw:
            raise OSError("synthetic disk write failure")
        return original(path, raw)

    monkeypatch.setattr(module, "_atomic_create", fail_started)
    with pytest.raises(OSError, match="disk write"):
        ledger.run_simulated_candidate(plan, internal_id=internal_id, adapter=adapter)
    assert adapter.calls == []
    assert ledger.preflight(plan)["candidates"][0]["state"] == "AUTHORIZED"


def test_failure_after_reservation_commit_is_fail_closed(tmp_path, monkeypatch):
    import football_data_hub.providers.bdfutbol.match_details.campaign as module

    class Abrupt(BaseException):
        pass

    plan = _plan()
    root = tmp_path / "campaigns"
    ledger = MatchDetailCampaignLedger(root)
    review_id = _add_review(ledger, plan)
    _authorize(ledger, plan, review_id)
    internal_id, url = _plan_ids(plan)
    adapter = SimulatedMatchAccessAdapter(_response(url))
    original = module._atomic_create

    def commit_then_stop(path, raw):
        original(path, raw)
        if b'"event_type": "STARTED"' in raw:
            raise Abrupt("crash after durable reservation")

    monkeypatch.setattr(module, "_atomic_create", commit_then_stop)
    with pytest.raises(Abrupt):
        ledger.run_simulated_candidate(plan, internal_id=internal_id, adapter=adapter)
    assert adapter.calls == []
    assert MatchDetailCampaignLedger(root).preflight(plan)["candidates"][0]["state"] == "INTERRUPTED_REQUIRES_REVIEW"


def test_artifact_write_failure_records_stop_and_leaves_unreferenced_file_fail_closed(tmp_path, monkeypatch):
    plan = _plan()
    root = tmp_path / "campaigns"
    ledger = MatchDetailCampaignLedger(root)
    review_id = _add_review(ledger, plan)
    _authorize(ledger, plan, review_id)
    internal_id, url = _plan_ids(plan)
    adapter = SimulatedMatchAccessAdapter(_response(url))
    original = ledger._store_discovery_artifact_locked

    def fail_after_staging(*args, **kwargs):
        result = original(*args, **kwargs)
        raise OSError(f"simulated failure after artifact commit: {result['artifact_id']}")

    monkeypatch.setattr(ledger, "_store_discovery_artifact_locked", fail_after_staging)
    result = ledger.run_simulated_candidate(plan, internal_id=internal_id, adapter=adapter)
    assert result["error_code"] == "DISCOVERY_STORAGE_ERROR"
    with pytest.raises(MatchCampaignIntegrityError, match="huérfano"):
        ledger.preflight(plan)


def test_campaign_and_event_corruption_and_orphans_are_detected(tmp_path):
    plan = _plan()
    root = tmp_path / "campaigns"
    ledger = MatchDetailCampaignLedger(root)
    ledger.initialize(plan)
    campaign_dir = root / plan["campaign"]["campaign_id"]
    (campaign_dir / "unreferenced.json").write_text("{}\n")
    with pytest.raises(MatchCampaignIntegrityError, match="huérfanos"):
        ledger.preflight(plan)


def test_concurrent_campaign_lock_blocks_second_process_object(tmp_path):
    plan = _plan()
    first = MatchDetailCampaignLedger(tmp_path / "campaigns")
    second = MatchDetailCampaignLedger(tmp_path / "campaigns")
    first.initialize(plan)
    with first.exclusive_lock():
        with pytest.raises(MatchCampaignLocked):
            with second.exclusive_lock():
                pass


def test_campaign_decision_to_block_prevents_any_candidate_authorization(tmp_path):
    plan = _plan()
    ledger = MatchDetailCampaignLedger(tmp_path / "campaigns")
    review_id = _add_review(ledger, plan, decision="block_entire_campaign")
    with pytest.raises(MatchCampaignAuthorizationError):
        _authorize(ledger, plan, review_id)
    result = ledger.preflight(plan)
    assert result["status"] == "BLOCKED"
    assert "LEGACY_REVIEW_BLOCKS_CAMPAIGN" in result["blocked_reasons"]


def test_non_simulated_adapter_is_rejected_before_reservation_or_open(tmp_path):
    class LooksLikeAccess:
        def __init__(self):
            self.calls = []

        def open(self, url):
            self.calls.append(url)

    plan = _plan()
    ledger = MatchDetailCampaignLedger(tmp_path / "campaigns")
    review_id = _add_review(ledger, plan)
    _authorize(ledger, plan, review_id)
    fake = LooksLikeAccess()
    with pytest.raises(MatchCampaignAuthorizationError, match="solo simulación"):
        ledger.run_simulated_candidate(
            plan, internal_id=_plan_ids(plan)[0], adapter=fake  # type: ignore[arg-type]
        )
    assert fake.calls == []
