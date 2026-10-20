from __future__ import annotations

import dataclasses
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from football_data_hub.providers.bdfutbol.match_details import (
    operational_campaign as operational,
)
from football_data_hub.providers.bdfutbol.match_details.campaign import (
    MatchCampaignAuthorizationError,
    MatchCampaignIntegrityError,
    SimulatedAccessResponse,
    SimulatedMatchAccessAdapter,
    review_completion_confirmation,
)
from football_data_hub.providers.bdfutbol.match_details.inventory import (
    build_match_detail_inventory,
)
from football_data_hub.providers.bdfutbol.match_details.scalable_campaigns import (
    build_match_campaign_inventory,
    build_match_campaign_proposal,
    classify_match_campaign_inventory,
    write_match_campaign_proposal,
)
from football_data_hub.providers.bdfutbol.match_details.semantic_parser import PARSER_VERSION
from football_data_hub_api import match_details_dataset as api_details
from football_data_hub_api.schemas import MatchPublishedDetailsResponse
from tests.match_detail_fixtures import make_verified_generation


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def _fixture(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "data"
    generation_id = "match-00-testgeneration"
    generation_root = data_root / "matches/generations" / generation_id
    generation_root.mkdir(parents=True)
    verified = make_verified_generation()
    verified = dataclasses.replace(
        verified,
        manifest_path=generation_root / "manifest.json",
        data_root=data_root,
    )
    for capture in verified.manifest_payload["source_captures"]:
        capture["source_snapshot_sha256"] = "a" * 64
        capture["files"]["source_html"]["sha256"] = "b" * 64
        capture["files"]["normalized_matches"]["sha256"] = "c" * 64
    for group in ("I", "II"):
        for team in verified.matches_payload["groups"][group]["teams"]:
            team["name"] = f"Equipo {team['team_id']}"
    # Third played fixture makes this a variable-size, cross-group proposal.
    verified.matches_payload["groups"]["I"]["matches"].append(
        {
            "internal_id": "pf-2026-27-group-i-bdfutbol-269411",
            "source_match_id": "269411",
            "status": "played",
            "source_match_url": "https://www.bdfutbol.com/es/p/p.php?id=269411",
            "home_team_id": 102,
            "away_team_id": 103,
            "matchday": 2,
            "source_match_date": "2026-09-02",
            "matchday_date": "2026-09-02",
            "home_goals": 1,
            "away_goals": 1,
        }
    )
    monkeypatch.setattr(
        operational, "load_verified_match_generation", lambda *_a, **_kw: verified
    )

    campaign_inventory = build_match_campaign_inventory(verified)
    report = classify_match_campaign_inventory(campaign_inventory)
    plan = build_match_campaign_proposal(report, groups=("I", "II"), limit=3)
    assert plan["candidate_count"] == 3
    proposal_root = tmp_path / "proposals"
    proposal_dir = write_match_campaign_proposal(proposal_root, plan)

    detail_inventory = build_match_detail_inventory(verified)
    store_root = data_root / "matches/details"
    ledger = operational.OperationalMatchCampaignLedger(store_root / "campaigns")
    return SimpleNamespace(
        data_root=data_root,
        generation_root=generation_root,
        verified=verified,
        plan=plan,
        proposal_dir=proposal_dir,
        inventory=detail_inventory,
        store_root=store_root,
        ledger=ledger,
        candidate=plan["candidates"][0],
    )


def _initialize(fixture):
    return fixture.ledger.initialize(
        proposal_dir=fixture.proposal_dir,
        generation_root=fixture.generation_root,
        data_root=fixture.data_root,
    )


def _current_status(fixture, state="NOT_AUTHORIZED"):
    candidate = fixture.candidate
    row = {
        **candidate,
        "detail_status": "included_in_existing_campaign"
        if state == "NOT_AUTHORIZED"
        else "authorized_not_executed",
        "campaign": {
            "campaign_id": fixture.plan["campaign_id"],
            "campaign_version": 2,
            "state": state,
        },
    }
    return row


def _authorize(fixture):
    return fixture.ledger.authorize(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        confirmed_url=fixture.candidate["source_match_url"],
        operator="offline-test-operator",
        confirmation=operational.AUTHORIZE_CONFIRMATION,
        current_status=_current_status(fixture),
        data_root=fixture.data_root,
    )


def _execute(fixture, adapter):
    authorization_id = fixture.ledger.candidate_events(
        fixture.plan["campaign_id"], fixture.candidate["internal_id"]
    )[0]["authorization"]["authorization_id"]
    return fixture.ledger.execute_simulated(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        authorization_id=authorization_id,
        confirmed_url=fixture.candidate["source_match_url"],
        adapter=adapter,
        store_root=fixture.store_root,
        store_inventory=fixture.inventory,
        current_status=_current_status(fixture, "AUTHORIZED"),
        published=False,
        captured=False,
        blocked=False,
    )


def test_v2_initialization_is_immutable_idempotent_and_never_authorizes(
    tmp_path, monkeypatch
):
    fixture = _fixture(tmp_path, monkeypatch)
    first = _initialize(fixture)
    second = _initialize(fixture)
    assert first["status"] == "CAMPAIGN_INITIALIZED_NOT_AUTHORIZED"
    assert second["status"] == "CAMPAIGN_ALREADY_INITIALIZED"
    preflight = fixture.ledger.preflight(fixture.plan["campaign_id"])
    assert preflight["candidate_count"] == 3
    assert preflight["candidate_states"] == {"NOT_AUTHORIZED": 3}
    assert preflight["http_enabled"] is False
    assert preflight["browser_started"] is False
    assert all(item["navigation_count"] == 0 for item in preflight["candidates"])


def test_v2_individual_authorization_can_be_bound_to_one_campaign_confirmation(
    tmp_path, monkeypatch
):
    fixture = _fixture(tmp_path, monkeypatch)
    _initialize(fixture)
    candidate = fixture.candidate
    confirmation_id = "campaign-authorization-" + "f" * 32
    candidate_set_sha256 = "a" * 64

    authorization_id = fixture.ledger.authorize(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=candidate["internal_id"],
        confirmed_url=candidate["source_match_url"],
        operator="offline-test-operator",
        confirmation=operational.AUTHORIZE_CONFIRMATION,
        current_status=_current_status(fixture),
        campaign_authorization_id=confirmation_id,
        campaign_candidate_set_sha256=candidate_set_sha256,
        data_root=fixture.data_root,
    )
    event = fixture.ledger.candidate_events(
        fixture.plan["campaign_id"], candidate["internal_id"]
    )[0]

    assert event["event_type"] == "AUTHORIZED"
    assert event["authorization"]["authorization_id"] == authorization_id
    assert event["authorization"]["campaign_authorization_id"] == confirmation_id
    assert event["authorization"]["campaign_candidate_set_sha256"] == candidate_set_sha256
    assert fixture.ledger.preflight(fixture.plan["campaign_id"])["candidate_states"] == {
        "AUTHORIZED": 1,
        "NOT_AUTHORIZED": 2,
    }


def test_v2_campaign_authorization_rejects_incomplete_campaign_reference(
    tmp_path, monkeypatch
):
    fixture = _fixture(tmp_path, monkeypatch)
    _initialize(fixture)
    candidate = fixture.candidate

    with pytest.raises(MatchCampaignAuthorizationError, match="ID y hash completos"):
        fixture.ledger.authorize(
            campaign_id=fixture.plan["campaign_id"],
            internal_id=candidate["internal_id"],
            confirmed_url=candidate["source_match_url"],
            operator="offline-test-operator",
            confirmation=operational.AUTHORIZE_CONFIRMATION,
            current_status=_current_status(fixture),
            campaign_authorization_id="campaign-authorization-" + "e" * 32,
            campaign_candidate_set_sha256="invalid",
            data_root=fixture.data_root,
        )

    assert fixture.ledger.preflight(fixture.plan["campaign_id"])["candidate_states"] == {
        "NOT_AUTHORIZED": 3,
    }


def test_v2_rejects_tampered_proposal_and_campaign_manifest(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    plan_path = fixture.proposal_dir / "plan.json"
    plan_path.write_bytes(plan_path.read_bytes().replace(b"269400", b"269401"))
    with pytest.raises(ValueError, match="Hash|contrato|coincide"):
        _initialize(fixture)

    fixture = _fixture(tmp_path / "second", monkeypatch)
    _initialize(fixture)
    manifest_path = fixture.ledger.root / fixture.plan["campaign_id"] / "manifest.json"
    manifest_path.write_bytes(_canonical({"schema_version": "tampered"}))
    with pytest.raises(MatchCampaignIntegrityError):
        fixture.ledger.preflight(fixture.plan["campaign_id"])

    fixture = _fixture(tmp_path / "inventory", monkeypatch)
    _initialize(fixture)
    inventory_path = (
        fixture.store_root
        / "inventories"
        / fixture.inventory["inventory_id"]
        / "inventory.json"
    )
    inventory_path.write_bytes(inventory_path.read_bytes() + b" ")
    with pytest.raises(MatchCampaignIntegrityError):
        fixture.ledger.preflight(fixture.plan["campaign_id"])


def test_v2_campaign_membership_rejects_duplicate_candidate_in_another_campaign(
    tmp_path, monkeypatch
):
    fixture = _fixture(tmp_path, monkeypatch)
    _initialize(fixture)
    from football_data_hub.providers.bdfutbol.match_details.scalable_campaigns import (
        build_match_campaign_inventory,
        build_match_campaign_proposal,
        classify_match_campaign_inventory,
        write_match_campaign_proposal,
    )

    second_plan = build_match_campaign_proposal(
        classify_match_campaign_inventory(
            build_match_campaign_inventory(fixture.verified)
        ),
        groups=("I", "II"),
        limit=2,
    )
    second_dir = write_match_campaign_proposal(
        tmp_path / "other-proposals", second_plan
    )
    with pytest.raises(MatchCampaignAuthorizationError, match="gestionados"):
        fixture.ledger.initialize(
            proposal_dir=second_dir,
            generation_root=fixture.generation_root,
            data_root=fixture.data_root,
        )


def _successor_proposal(fixture, output_root):
    inventory = build_match_campaign_inventory(fixture.verified)
    target_id = fixture.candidate["internal_id"]
    report = classify_match_campaign_inventory(
        inventory,
        campaign_states={
            target_id: {
                "campaign_id": fixture.plan["campaign_id"],
                "campaigns": [fixture.plan["campaign_id"]],
                "campaign_version": 2,
                "state": "NOT_AUTHORIZED",
                "authorization_consumed": False,
                "navigation_count": 0,
                "blocked_reasons": [],
            }
        },
    )
    plan = build_match_campaign_proposal(report, internal_ids=[target_id])
    proposal_dir = write_match_campaign_proposal(output_root, plan)
    return plan, proposal_dir


def test_unstarted_v2_membership_can_be_superseded_auditably(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    _initialize(fixture)
    old_dir = fixture.ledger.root / fixture.plan["campaign_id"]
    old_campaign_bytes = (old_dir / "campaign.json").read_bytes()
    old_manifest_bytes = (old_dir / "manifest.json").read_bytes()
    successor, proposal_dir = _successor_proposal(
        fixture, tmp_path / "successor-proposals"
    )

    result = fixture.ledger.initialize(
        proposal_dir=proposal_dir,
        generation_root=fixture.generation_root,
        data_root=fixture.data_root,
    )
    assert result["status"] == "CAMPAIGN_INITIALIZED_NOT_AUTHORIZED"
    assert result["campaign_id"] == successor["campaign_id"]
    assert (old_dir / "campaign.json").read_bytes() == old_campaign_bytes
    assert (old_dir / "manifest.json").read_bytes() == old_manifest_bytes

    from football_data_hub.providers.bdfutbol.match_details.scalable_campaign_cli import (
        _read_campaign_states,
    )

    states, _summaries = _read_campaign_states(fixture.store_root / "campaigns")
    state = states[fixture.candidate["internal_id"]]
    assert state["campaign_id"] == successor["campaign_id"]
    assert state["state"] == "NOT_AUTHORIZED"
    assert state["campaigns"] == [successor["campaign_id"]]
    assert state["superseded_campaign_ids"] == [fixture.plan["campaign_id"]]

    current_report = classify_match_campaign_inventory(
        build_match_campaign_inventory(fixture.verified), campaign_states=states
    )
    from football_data_hub.providers.bdfutbol.match_details.supervised_acquisition import (
        build_campaign_run_plan,
    )

    run_plan = build_campaign_run_plan(
        fixture.ledger,
        successor["campaign_id"],
        status_report=current_report,
        context={"published_ids": set(), "captured_ids": set(), "blocked_ids": set()},
    )
    assert run_plan["candidate_count"] == 1
    assert run_plan["candidates"][0]["superseded_campaign_ids"] == [
        fixture.plan["campaign_id"]
    ]


def test_authorized_prior_membership_cannot_be_superseded(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    _initialize(fixture)
    _authorize(fixture)
    _successor, proposal_dir = _successor_proposal(
        fixture, tmp_path / "successor-proposals"
    )
    with pytest.raises(MatchCampaignAuthorizationError, match="inició|transferencia"):
        fixture.ledger.initialize(
            proposal_dir=proposal_dir,
            generation_root=fixture.generation_root,
            data_root=fixture.data_root,
        )


@pytest.mark.parametrize("changed_field", ["status", "home_team_id", "home_goals"])
def test_v2_initialization_rejects_nonplayed_or_conflicting_candidate_source(
    tmp_path, monkeypatch, changed_field
):
    fixture = _fixture(tmp_path, monkeypatch)
    changed = copy.deepcopy(fixture.verified)
    row = next(
        item
        for item in changed.matches_payload["groups"]["I"]["matches"]
        if item["source_match_id"] == fixture.candidate["source_match_id"]
    )
    if changed_field == "status":
        row["status"] = "unplayed"
        row["home_goals"] = row["away_goals"] = None
    elif changed_field == "home_team_id":
        row["home_team_id"] = 104
    else:
        row["home_goals"] = 4
    monkeypatch.setattr(operational, "load_verified_match_generation", lambda *_a, **_kw: changed)
    with pytest.raises(MatchCampaignIntegrityError, match="Candidato contradictorio"):
        _initialize(fixture)


def test_v2_authorization_is_individual_and_consumed_once(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    _initialize(fixture)
    with pytest.raises(MatchCampaignAuthorizationError):
        fixture.ledger.execute_real(
            campaign_id=fixture.plan["campaign_id"],
            internal_id=fixture.candidate["internal_id"],
            authorization_id="not-authorized",
            confirmed_url=fixture.candidate["source_match_url"],
            data_root=fixture.data_root,
            profile_dir=fixture.data_root
            / "browser-profiles"
            / f"match-detail-v2-{fixture.candidate['source_match_id']}",
            confirmation=operational.EXECUTE_CONFIRMATION,
            player_browser_idle_confirmation=operational.PLAYER_IDLE_CONFIRMATION,
            store_root=fixture.store_root,
            store_inventory=fixture.inventory,
            current_status=_current_status(fixture),
            published=False,
            captured=False,
            blocked=False,
            access_runner=lambda *_a, **_kw: pytest.fail(
                "browser adapter must not be invoked in this offline test"
            ),
        )
    with pytest.raises(MatchCampaignAuthorizationError):
        fixture.ledger.authorize(
            campaign_id=fixture.plan["campaign_id"],
            internal_id=fixture.candidate["internal_id"],
            confirmed_url="https://www.bdfutbol.com/es/p/p.php?id=00000",
            operator="offline-test-operator",
            confirmation=operational.AUTHORIZE_CONFIRMATION,
            current_status=_current_status(fixture),
            data_root=fixture.data_root,
        )
    authorization_id = _authorize(fixture)
    assert authorization_id.startswith("match-detail-authorization-v2-")
    with pytest.raises(MatchCampaignAuthorizationError):
        _authorize(fixture)
    assert (
        fixture.ledger.preflight(fixture.plan["campaign_id"])["candidate_states"][
            "AUTHORIZED"
        ]
        == 1
    )


def test_simulated_acquisition_writes_one_immutable_artifact_and_blocks_second_navigation(
    tmp_path, monkeypatch
):
    fixture = _fixture(tmp_path, monkeypatch)
    _initialize(fixture)
    _authorize(fixture)

    class StartObservedAdapter(SimulatedMatchAccessAdapter):
        def open(self, url):
            events = fixture.ledger.candidate_events(
                fixture.plan["campaign_id"], fixture.candidate["internal_id"]
            )
            assert [event["event_type"] for event in events] == ["AUTHORIZED", "STARTED"]
            return super().open(url)

    adapter = StartObservedAdapter(
        SimulatedAccessResponse(
            final_url=fixture.candidate["source_match_url"],
            http_status=200,
            html=b"<!doctype html><html><head><title>Fixture match</title></head><body>Fixture</body></html>",
            page_title="Fixture match",
            access_classification="VALID",
        )
    )
    result = _execute(fixture, adapter)
    assert result["status"] == "DISCOVERY_REVIEW_REQUIRED"
    assert adapter.calls == [fixture.candidate["source_match_url"]]
    artifact = fixture.ledger.preflight(fixture.plan["campaign_id"])["candidates"][0][
        "artifact"
    ]
    assert artifact["artifact_id"]
    assert (
        fixture.ledger.candidate_events(
            fixture.plan["campaign_id"], fixture.candidate["internal_id"]
        )[-1]["event_type"]
        == "DISCOVERY_REVIEW_REQUIRED"
    )
    _, scoped_report, _ = fixture.ledger.inspect_artifact_evidence(
        fixture.ledger.root / fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
    )
    assert scoped_report["candidate_count"] == 3
    assert len(scoped_report["candidates"]) == 1
    assert scoped_report["candidates"][0]["acquisition_state"] == "DISCOVERY_REVIEW_REQUIRED"
    assert scoped_report["candidates"][0]["navigation_count"] == 1
    import football_data_hub.providers.bdfutbol.match_details.campaign_artifact as campaign_artifact

    parser_result = object()
    monkeypatch.setattr(
        operational.OperationalMatchCampaignLedger,
        "preflight",
        lambda *_args, **_kwargs: pytest.fail(
            "artifact inspection must not scan unrelated campaign candidates"
        ),
    )
    monkeypatch.setattr(
        campaign_artifact,
        "parse_match_detail_html",
        lambda *_args, **_kwargs: parser_result,
    )
    parsed = campaign_artifact.parse_campaign_saved_artifact(
        fixture.ledger.root
        / fixture.plan["campaign_id"]
        / artifact["artifact_relative_path"],
        expected_match=next(
            row
            for row in fixture.inventory["matches"]
            if row["internal_id"] == fixture.candidate["internal_id"]
        ),
        verified_generation=fixture.verified,
        data_root=fixture.data_root,
    )
    assert parsed is parser_result
    with pytest.raises(MatchCampaignAuthorizationError):
        _execute(fixture, SimulatedMatchAccessAdapter(adapter.response))


def test_abrupt_interruption_stays_blocked_and_access_denial_stops(
    tmp_path, monkeypatch
):
    fixture = _fixture(tmp_path, monkeypatch)
    _initialize(fixture)
    _authorize(fixture)
    interrupted = SimulatedMatchAccessAdapter(error=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        _execute(fixture, interrupted)
    state = fixture.ledger.preflight(fixture.plan["campaign_id"])["candidates"][0][
        "state"
    ]
    assert state == "INTERRUPTED_REQUIRES_REVIEW"
    retry = SimulatedMatchAccessAdapter(
        SimulatedAccessResponse(
            final_url=fixture.candidate["source_match_url"],
            http_status=200,
            html=b"<html><body>Never fetched</body></html>",
            access_classification="VALID",
        )
    )
    with pytest.raises(MatchCampaignAuthorizationError):
        _execute(fixture, retry)
    assert retry.calls == []

    second = _fixture(tmp_path / "denied", monkeypatch)
    _initialize(second)
    _authorize(second)
    denial = SimulatedMatchAccessAdapter(
        SimulatedAccessResponse(
            final_url=second.candidate["source_match_url"],
            http_status=403,
            html=b"forbidden",
            access_classification="ACCESS_DENIED",
            denial_detected=True,
        )
    )
    result = _execute(second, denial)
    assert result["status"] == "STOPPED"
    assert denial.calls == [second.candidate["source_match_url"]]
    assert (
        second.ledger.preflight(second.plan["campaign_id"])["candidates"][0]["state"]
        == "STOPPED"
    )


def test_simulated_challenge_stops_and_consumes_the_single_authorization(
    tmp_path, monkeypatch
):
    fixture = _fixture(tmp_path, monkeypatch)
    _initialize(fixture)
    _authorize(fixture)
    adapter = SimulatedMatchAccessAdapter(
        SimulatedAccessResponse(
            final_url=fixture.candidate["source_match_url"],
            http_status=200,
            html=b"challenge content",
            access_classification="CHALLENGE_REQUIRED",
            challenge_detected=True,
        )
    )
    result = _execute(fixture, adapter)
    assert result["status"] == "STOPPED"
    assert result["error_code"] == "CONTENT_NOT_VERIFIED"
    assert len(adapter.calls) == 1
    with pytest.raises(MatchCampaignAuthorizationError):
        _execute(fixture, SimulatedMatchAccessAdapter(adapter.response))


@dataclasses.dataclass
class _FakeValidation:
    semantic_valid: bool = True
    parser_version: str = "offline-test-parser"
    checks: list = dataclasses.field(default_factory=list)
    errors: list = dataclasses.field(default_factory=list)
    warnings: list = dataclasses.field(default_factory=list)


def _valid_draft(fixture, artifact_event):
    details_document = MatchPublishedDetailsResponse.model_validate(
        {
            "publication_status": "approved",
            "validation_status": "valid",
            "source": "BDFutbol",
            "internal_id": fixture.candidate["internal_id"],
            "source_match_id": fixture.candidate["source_match_id"],
            "source_generation_id": fixture.verified.generation_id,
            "source_capture_id": "capture-I",
            "source_html_sha256": artifact_event["artifact"]["source_html_sha256"],
            "match_date": fixture.candidate["source_match_date"],
            "home_team_id": fixture.candidate["home_team_id"],
            "away_team_id": fixture.candidate["away_team_id"],
            "home_goals": 0,
            "away_goals": 0,
            "home": {
                "team_id": fixture.candidate["home_team_id"],
                "coach": None,
                "starters": None,
                "substitutes": None,
            },
            "away": {
                "team_id": fixture.candidate["away_team_id"],
                "coach": None,
                "starters": None,
                "substitutes": None,
            },
            "events": [],
        }
    ).model_dump(mode="json", exclude_unset=True)
    details = {
        **details_document,
    }
    draft = {
        "schema_version": api_details.CAMPAIGN_DRAFT_SCHEMA,
        "publication_id": "campaign-offline-" + fixture.candidate["source_match_id"],
        "source_kind": "campaign_discovery",
        "internal_id": fixture.candidate["internal_id"],
        "source_match_id": fixture.candidate["source_match_id"],
        "inventory_id": fixture.ledger._read_campaign(
            fixture.ledger.root / fixture.plan["campaign_id"]
        )[0]["source"]["inventory_id"],
        "source_generation_id": fixture.verified.generation_id,
        "source_generation_manifest_sha256": fixture.verified.manifest_sha256,
        "source_capture_id": "capture-I",
        "season": "2026-27",
        "competition": "Primera Federación",
        "group": fixture.candidate["group"],
        "matchday": fixture.candidate["matchday"],
        "source_match_date": fixture.candidate["source_match_date"],
        "home_team_id": fixture.candidate["home_team_id"],
        "away_team_id": fixture.candidate["away_team_id"],
        "home_team_name": fixture.candidate["home_team_name"],
        "away_team_name": fixture.candidate["away_team_name"],
        "campaign_id": fixture.plan["campaign_id"],
        "artifact_id": artifact_event["artifact"]["artifact_id"],
        "navigation_attempt_id": artifact_event["attempt_id"],
        "artifact_manifest_sha256": artifact_event["artifact"]["manifest_sha256"],
        "source_html_sha256": artifact_event["artifact"]["source_html_sha256"],
        "capture_promotion_enabled": False,
        "promotion_eligible": False,
        "access_status": "VALID",
        "semantic_valid": True,
        "details": details,
    }
    draft["details_sha256"] = api_details._sha256(api_details._canonical_json(details))
    return draft


def _publication_verification_fixture(tmp_path, monkeypatch):
    internal_id = "pf-2026-27-group-i-bdfutbol-269408"
    publication_id = "campaign-269408-testhash"
    details = MatchPublishedDetailsResponse.model_validate(
        {
            "publication_status": "approved",
            "validation_status": "valid",
            "source": "BDFutbol",
            "internal_id": internal_id,
            "source_match_id": "269408",
            "source_generation_id": "match-00-testgeneration",
            "source_capture_id": "capture-I",
            "source_html_sha256": "a" * 64,
            "match_date": None,
            "home_team_id": 81,
            "away_team_id": 58,
            "home_goals": 0,
            "away_goals": 1,
            "home": {"team_id": 81, "coach": None, "starters": None, "substitutes": None},
            "away": {"team_id": 58, "coach": None, "starters": None, "substitutes": None},
            "events": [],
        }
    )
    details_payload = details.model_dump(mode="json", exclude_unset=True)
    details_raw = api_details._canonical_json(details_payload)
    details_sha = _sha(details_raw)
    approval_receipt = {
        "internal_id": internal_id,
        "publication_id": publication_id,
        "details_sha256": details_sha,
        "approved_by": "synthetic review",
        "approval_confirmation": "APPROVE-269408-test",
        "source_html_sha256": "a" * 64,
    }
    approval_raw = api_details._canonical_json(approval_receipt)
    review_receipt_path = (
        tmp_path
        / "matches/details/review/v2"
        / "match-detail-campaign-v2-06aa2259b14b95a7"
        / "269408-approval.json"
    )
    review_receipt_path.parent.mkdir(parents=True, exist_ok=True)
    review_receipt_path.write_bytes(approval_raw)
    manifest = {
        "schema_version": api_details.CAMPAIGN_PACKAGE_SCHEMA,
        "publication_id": publication_id,
        "internal_id": internal_id,
        "source_match_id": "269408",
        "details_sha256": details_sha,
        "approval_sha256": _sha(approval_raw),
    }
    manifest_raw = api_details._canonical_json(manifest)
    published_root = tmp_path / "published"
    package = published_root / "packages" / publication_id
    package.mkdir(parents=True)
    (package / "manifest.json").write_bytes(manifest_raw)
    (package / "details.json").write_bytes(details_raw)
    (package / "approval.json").write_bytes(approval_raw)
    index = {
        "schema_version": api_details.INDEX_SCHEMA,
        "publications": [
            {
                "internal_id": internal_id,
                "publication_id": publication_id,
                "package_path": f"packages/{publication_id}",
                "manifest_sha256": _sha(manifest_raw),
            }
        ],
    }
    index_path = published_root / "index.json"
    index_path.write_bytes(api_details._canonical_json(index))

    approved_event = {
        "event_type": "DOCUMENT_APPROVED",
        "internal_id": internal_id,
        "details_sha256": details_sha,
        "approval_sha256": _sha(approval_raw),
        "approval_path": review_receipt_path.relative_to(tmp_path).as_posix(),
        "approved_by": "synthetic review",
        "approval_confirmation": "APPROVE-269408-test",
        "source_html_sha256": "a" * 64,
    }
    published_event = {
        "event_type": "PUBLISHED",
        "internal_id": internal_id,
        "publication_id": publication_id,
        "details_sha256": details_sha,
        "publication_manifest_sha256": _sha(manifest_raw),
    }
    events = [approved_event, published_event]
    ledger = operational.OperationalMatchCampaignLedger(tmp_path / "campaigns")
    monkeypatch.setattr(
        ledger, "_events", lambda *_args: (tmp_path, {}, events)
    )
    monkeypatch.setattr(
        ledger,
        "_publication_inputs",
        lambda **_kwargs: (tmp_path, tmp_path, SimpleNamespace(), set()),
    )
    monkeypatch.setattr(
        api_details,
        "load_published_match_details",
        lambda *_args, **_kwargs: {internal_id: details},
    )
    kwargs = {
        "campaign_id": "match-detail-campaign-v2-06aa2259b14b95a7",
        "internal_id": internal_id,
        "data_root": tmp_path,
        "generation_root": tmp_path,
        "published_root": published_root,
        "store_root": tmp_path,
        "player_inventory_root": tmp_path,
        "player_compact_root": tmp_path,
        "player_team_captures_root": tmp_path,
        "player_published_index_path": tmp_path / "players.json",
    }
    return SimpleNamespace(
        ledger=ledger,
        kwargs=kwargs,
        internal_id=internal_id,
        publication_id=publication_id,
        details_sha=details_sha,
        package=package,
        index_path=index_path,
        manifest=manifest,
        events=events,
    )


def test_verify_publication_uses_manifest_with_real_response_source_literal(
    tmp_path, monkeypatch
):
    fixture = _publication_verification_fixture(tmp_path, monkeypatch)
    paths = [fixture.index_path, *fixture.package.iterdir()]
    before = {path: path.read_bytes() for path in paths}

    result = fixture.ledger.verify_publication(**fixture.kwargs)

    assert result["status"] == "PUBLISHED_VERIFIED"
    assert result["publication_id"] == fixture.publication_id
    assert result["details_sha256"] == fixture.details_sha
    assert before == {path: path.read_bytes() for path in paths}


@pytest.mark.parametrize(
    "mismatch",
    [
        "index_manifest_sha",
        "ledger_manifest_sha",
        "manifest_details_sha",
        "published_details_sha",
        "approved_details_sha",
        "manifest_identity",
        "publication_id",
        "missing_package",
        "missing_manifest",
        "corrupt_manifest",
    ],
)
def test_verify_publication_rejects_mismatched_or_incomplete_package(
    tmp_path, monkeypatch, mismatch
):
    fixture = _publication_verification_fixture(tmp_path, monkeypatch)
    manifest_path = fixture.package / "manifest.json"
    index = json.loads(fixture.index_path.read_bytes())
    row = index["publications"][0]
    manifest = dict(fixture.manifest)
    published = fixture.events[-1]
    approved = fixture.events[0]

    if mismatch == "index_manifest_sha":
        row["manifest_sha256"] = "b" * 64
        fixture.index_path.write_bytes(api_details._canonical_json(index))
    elif mismatch == "ledger_manifest_sha":
        published["publication_manifest_sha256"] = "b" * 64
    elif mismatch == "manifest_details_sha":
        manifest["details_sha256"] = "b" * 64
        raw = api_details._canonical_json(manifest)
        manifest_path.write_bytes(raw)
        row["manifest_sha256"] = _sha(raw)
        fixture.index_path.write_bytes(api_details._canonical_json(index))
        published["publication_manifest_sha256"] = _sha(raw)
    elif mismatch == "published_details_sha":
        published["details_sha256"] = "b" * 64
    elif mismatch == "approved_details_sha":
        approved["details_sha256"] = "b" * 64
    elif mismatch == "manifest_identity":
        manifest["internal_id"] = "pf-2026-27-group-i-bdfutbol-269411"
        raw = api_details._canonical_json(manifest)
        manifest_path.write_bytes(raw)
        row["manifest_sha256"] = _sha(raw)
        fixture.index_path.write_bytes(api_details._canonical_json(index))
        published["publication_manifest_sha256"] = _sha(raw)
    elif mismatch == "publication_id":
        row["publication_id"] = "campaign-269408-other"
        row["package_path"] = "packages/campaign-269408-other"
        fixture.index_path.write_bytes(api_details._canonical_json(index))
    elif mismatch == "missing_package":
        import shutil

        shutil.rmtree(fixture.package)
    elif mismatch == "missing_manifest":
        manifest_path.unlink()
    elif mismatch == "corrupt_manifest":
        manifest_path.write_bytes(b"{not-json")
        raw = manifest_path.read_bytes()
        row["manifest_sha256"] = _sha(raw)
        fixture.index_path.write_bytes(api_details._canonical_json(index))
        published["publication_manifest_sha256"] = _sha(raw)

    with pytest.raises(MatchCampaignIntegrityError):
        fixture.ledger.verify_publication(**fixture.kwargs)


def test_v2_offline_pipeline_reaches_review_completion_with_human_approval(
    tmp_path, monkeypatch
):
    fixture = _fixture(tmp_path, monkeypatch)
    _initialize(fixture)
    _authorize(fixture)
    _execute(
        fixture,
        SimulatedMatchAccessAdapter(
            SimulatedAccessResponse(
                final_url=fixture.candidate["source_match_url"],
                http_status=200,
                html=b"<html><head><title>Fixture</title></head><body>Fixture</body></html>",
                page_title="Fixture",
                access_classification="VALID",
            )
        ),
    )

    import football_data_hub.providers.bdfutbol.match_details.campaign_artifact as artifacts

    monkeypatch.setattr(
        artifacts,
        "parse_campaign_saved_artifact",
        lambda *_a, **_kw: SimpleNamespace(
            validation=_FakeValidation(),
            source=SimpleNamespace(parser_version="offline-test-parser"),
        ),
    )
    validated = fixture.ledger.validate_offline_artifact(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        data_root=fixture.data_root,
    )
    assert validated["status"] == "VALIDATED"
    events = fixture.ledger.candidate_events(
        fixture.plan["campaign_id"], fixture.candidate["internal_id"]
    )
    discovery = next(
        item for item in events if item["event_type"] == "DISCOVERY_REVIEW_REQUIRED"
    )
    draft = _valid_draft(fixture, discovery)

    def build_draft(
        *, internal_id, campaign_id, artifact_id, generation_root, data_root,
        match_bundle, player_ids
    ):
        assert internal_id == fixture.candidate["internal_id"]
        assert campaign_id == fixture.plan["campaign_id"]
        assert artifact_id == discovery["artifact"]["artifact_id"]
        return draft

    monkeypatch.setattr(
        api_details, "build_campaign_publication_draft", build_draft
    )
    monkeypatch.setattr(
        fixture.ledger,
        "_publication_inputs",
        lambda **_kw: (
            fixture.data_root,
            fixture.generation_root,
            SimpleNamespace(),
            set(),
        ),
    )
    prepared = fixture.ledger.prepare_draft(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        data_root=fixture.data_root,
        generation_root=fixture.generation_root,
        player_inventory_root=tmp_path,
        player_compact_root=tmp_path,
        player_team_captures_root=tmp_path,
        player_published_index_path=tmp_path / "players.json",
    )
    assert prepared["status"] == "DRAFT_PREPARED"
    repeated_preparation = fixture.ledger.prepare_draft(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        data_root=fixture.data_root,
        generation_root=fixture.generation_root,
        player_inventory_root=tmp_path,
        player_compact_root=tmp_path,
        player_team_captures_root=tmp_path,
        player_published_index_path=tmp_path / "players.json",
    )
    assert repeated_preparation["draft_sha256"] == prepared["draft_sha256"]

    draft_path = (
        fixture.data_root
        / next(
            item
            for item in fixture.ledger.candidate_events(
                fixture.plan["campaign_id"], fixture.candidate["internal_id"]
            )
            if item["event_type"] == "DRAFT_PREPARED"
        )["draft_path"]
    )
    original_draft_bytes = draft_path.read_bytes()
    draft_path.write_bytes(
        original_draft_bytes.replace(
            b'"semantic_valid":true', b'"semantic_valid":false'
        )
    )
    with pytest.raises(MatchCampaignIntegrityError, match="borrador|Borrador"):
        fixture.ledger.candidate_events(
            fixture.plan["campaign_id"], fixture.candidate["internal_id"]
        )
    draft_path.write_bytes(original_draft_bytes)
    with pytest.raises(MatchCampaignAuthorizationError):
        fixture.ledger.publish(
            campaign_id=fixture.plan["campaign_id"],
            internal_id=fixture.candidate["internal_id"],
            data_root=fixture.data_root,
            generation_root=fixture.generation_root,
            published_root=fixture.store_root / "published",
            store_root=fixture.store_root,
            player_inventory_root=tmp_path,
            player_compact_root=tmp_path,
            player_team_captures_root=tmp_path,
            player_published_index_path=tmp_path / "players.json",
        )

    approval = api_details.build_campaign_approval_receipt(
        draft,
        approved_by="synthetic reviewer",
        confirm_internal_id=draft["internal_id"],
        confirm_source_html_sha256=draft["source_html_sha256"],
        confirm_details_sha256=draft["details_sha256"],
        confirm_action=api_details.campaign_approval_confirmation(draft),
    )
    draft_path = (
        fixture.data_root
        / next(
            item
            for item in fixture.ledger.candidate_events(
                fixture.plan["campaign_id"], fixture.candidate["internal_id"]
            )
            if item["event_type"] == "DRAFT_PREPARED"
        )["draft_path"]
    )
    receipt_path = draft_path.with_name(
        draft_path.name.removesuffix("-draft.json") + "-approval.json"
    )
    with pytest.raises(api_details.MatchDetailsLoadError):
        fixture.ledger.approve_draft(
            campaign_id=fixture.plan["campaign_id"],
            internal_id=fixture.candidate["internal_id"],
            draft_path=draft_path,
            approved_by="synthetic reviewer",
            confirm_internal_id="pf-2026-27-group-ii-bdfutbol-272582",
            confirm_source_html_sha256=draft["source_html_sha256"],
            confirm_details_sha256=draft["details_sha256"],
            confirm_action=api_details.campaign_approval_confirmation(draft),
            data_root=fixture.data_root,
        )
    monkeypatch.setattr(
        api_details,
        "build_campaign_approval_receipt",
        lambda *_a, **_kw: approval,
    )
    approved = fixture.ledger.approve_draft(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        draft_path=draft_path,
        approved_by="synthetic reviewer",
        confirm_internal_id=draft["internal_id"],
        confirm_source_html_sha256=draft["source_html_sha256"],
        confirm_details_sha256=draft["details_sha256"],
        confirm_action=api_details.campaign_approval_confirmation(draft),
        data_root=fixture.data_root,
    )
    assert approved["status"] == "DOCUMENT_APPROVED"
    assert receipt_path.is_file()
    repeated_approval = fixture.ledger.approve_draft(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        draft_path=draft_path,
        approved_by="synthetic reviewer",
        confirm_internal_id=draft["internal_id"],
        confirm_source_html_sha256=draft["source_html_sha256"],
        confirm_details_sha256=draft["details_sha256"],
        confirm_action=api_details.campaign_approval_confirmation(draft),
        data_root=fixture.data_root,
    )
    assert repeated_approval["status"] == "DOCUMENT_ALREADY_APPROVED"

    published_root = fixture.store_root / "published"

    def fake_publish(_draft, **_kwargs):
        package = published_root / "packages" / draft["publication_id"]
        package.mkdir(parents=True)
        details_raw = api_details._canonical_json(draft["details"])
        approval_raw = (
            fixture.data_root / approved["approval_path"]
        ).read_bytes()
        manifest = {
            "schema_version": api_details.CAMPAIGN_PACKAGE_SCHEMA,
            "publication_id": draft["publication_id"],
            "internal_id": draft["internal_id"],
            "source_match_id": draft["source_match_id"],
            "details_sha256": draft["details_sha256"],
            "approval_sha256": _sha(approval_raw),
        }
        manifest_raw = api_details._canonical_json(manifest)
        manifest_path = (
            published_root / "packages" / draft["publication_id"] / "manifest.json"
        )
        manifest_path.write_bytes(manifest_raw)
        (package / "details.json").write_bytes(details_raw)
        (package / "approval.json").write_bytes(approval_raw)
        (published_root / "index.json").write_text(
            json.dumps(
                {
                    "schema_version": api_details.INDEX_SCHEMA,
                    "publications": [
                        {
                            "internal_id": draft["internal_id"],
                            "publication_id": draft["publication_id"],
                            "package_path": f"packages/{draft['publication_id']}",
                            "manifest_sha256": _sha(manifest_raw),
                        }
                    ],
                },
                sort_keys=True,
            )
        )
        return {"publication_id": draft["publication_id"]}

    loaded_doc = MatchPublishedDetailsResponse.model_validate(draft["details"])
    monkeypatch.setattr(
        api_details, "publish_campaign_match_detail_draft", fake_publish
    )
    monkeypatch.setattr(
        api_details,
        "load_published_match_details",
        lambda *_a, **_kw: {draft["internal_id"]: loaded_doc},
    )
    published = fixture.ledger.publish(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        data_root=fixture.data_root,
        generation_root=fixture.generation_root,
        published_root=published_root,
        store_root=fixture.store_root,
        player_inventory_root=tmp_path,
        player_compact_root=tmp_path,
        player_team_captures_root=tmp_path,
        player_published_index_path=tmp_path / "players.json",
    )
    assert published["status"] == "PUBLISHED"
    package = published_root / "packages" / draft["publication_id"]
    event_dir = (
        fixture.ledger.root
        / fixture.plan["campaign_id"]
        / "candidates"
        / fixture.candidate["internal_id"]
        / "events"
    )
    verification_paths = [
        published_root / "index.json",
        *package.iterdir(),
        *event_dir.iterdir(),
    ]
    verification_bytes = {
        path: path.read_bytes() for path in verification_paths
    }
    verification = fixture.ledger.verify_publication(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        data_root=fixture.data_root,
        generation_root=fixture.generation_root,
        published_root=published_root,
        store_root=fixture.store_root,
        player_inventory_root=tmp_path,
        player_compact_root=tmp_path,
        player_team_captures_root=tmp_path,
        player_published_index_path=tmp_path / "players.json",
    )
    assert verification["status"] == "PUBLISHED_VERIFIED"
    assert verification_bytes == {
        path: path.read_bytes() for path in verification_paths
    }
    confirmation = review_completion_confirmation(
        draft["source_match_id"], draft["source_html_sha256"], draft["details_sha256"]
    )
    closed = fixture.ledger.complete_review(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        reviewer="synthetic reviewer",
        confirmation=confirmation,
        data_root=fixture.data_root,
        generation_root=fixture.generation_root,
        published_root=published_root,
        store_root=fixture.store_root,
        player_inventory_root=tmp_path,
        player_compact_root=tmp_path,
        player_team_captures_root=tmp_path,
        player_published_index_path=tmp_path / "players.json",
    )
    assert closed["status"] == "REVIEW_COMPLETED"
    assert (
        fixture.ledger.preflight(fixture.plan["campaign_id"])["candidate_states"][
            "REVIEW_COMPLETED"
        ]
        == 1
    )

    from football_data_hub.providers.bdfutbol.match_details.scalable_campaign_cli import (
        _read_campaign_states,
    )

    campaign_states, _summaries = _read_campaign_states(fixture.ledger.root)
    refreshed = classify_match_campaign_inventory(
        build_match_campaign_inventory(fixture.verified),
        published_ids={fixture.candidate["internal_id"]},
        campaign_states=campaign_states,
    )
    final_row = next(
        row
        for row in refreshed["matches"]
        if row["internal_id"] == fixture.candidate["internal_id"]
    )
    assert final_row["detail_status"] == "review_completed"


def test_offline_batch_uses_v2_parser_and_is_idempotent(tmp_path, monkeypatch):
    from football_data_hub.providers.bdfutbol.match_details.campaign_operations import run_offline_batch

    fixture = _fixture(tmp_path, monkeypatch)
    _initialize(fixture)
    _authorize(fixture)
    _execute(
        fixture,
        SimulatedMatchAccessAdapter(
            SimulatedAccessResponse(
                final_url=fixture.candidate["source_match_url"],
                http_status=200,
                html=b"<html><head><title>Offline fixture</title></head><body>stored</body></html>",
                page_title="Offline fixture",
                access_classification="VALID",
            )
        ),
    )
    import football_data_hub.providers.bdfutbol.match_details.campaign_artifact as artifacts

    monkeypatch.setattr(
        artifacts,
        "parse_campaign_saved_artifact",
        lambda *_a, **_kw: SimpleNamespace(
            validation=_FakeValidation(),
            source=SimpleNamespace(parser_version="offline-test-parser"),
        ),
    )
    discovery = next(
        event for event in fixture.ledger.candidate_events(
            fixture.plan["campaign_id"], fixture.candidate["internal_id"]
        ) if event["event_type"] == "DISCOVERY_REVIEW_REQUIRED"
    )
    monkeypatch.setattr(
        api_details, "build_campaign_publication_draft",
        lambda **_kwargs: _valid_draft(fixture, discovery),
    )
    monkeypatch.setattr(
        fixture.ledger,
        "_publication_inputs",
        lambda **_kwargs: (fixture.data_root, fixture.generation_root, SimpleNamespace(), set()),
    )
    kwargs = {
        "ledger": fixture.ledger,
        "campaign_id": fixture.plan["campaign_id"],
        "data_root": fixture.data_root,
        "player_inventory_root": tmp_path,
        "player_compact_root": tmp_path,
        "player_team_captures_root": tmp_path,
        "player_published_index_path": tmp_path / "players.json",
    }
    first = run_offline_batch(**kwargs)
    assert first["status"] == "COMPLETED"
    assert first["prepared_count"] == 1
    events_after_first = fixture.ledger.candidate_events(
        fixture.plan["campaign_id"], fixture.candidate["internal_id"]
    )
    assert [event["event_type"] for event in events_after_first][-2:] == ["VALIDATED", "DRAFT_PREPARED"]

    second = run_offline_batch(**kwargs)
    assert second["status"] == "COMPLETED"
    assert second["prepared_count"] == 0
    events_after_second = fixture.ledger.candidate_events(
        fixture.plan["campaign_id"], fixture.candidate["internal_id"]
    )
    assert [event["event_sha256"] for event in events_after_second] == [
        event["event_sha256"] for event in events_after_first
    ]


@pytest.mark.parametrize(
    ("extra_warning", "expected_published_count"),
    [(None, 1), ("lineup_event_unresolved", 0)],
)
def test_global_update_policy_publishes_only_strictly_validated_authorized_capture(
    tmp_path, monkeypatch, extra_warning, expected_published_count
):
    import uuid

    from football_data_hub.providers.bdfutbol.match_details.automatic_publication_policy import (
        REQUIRED_CHECKS,
        candidate_set_sha256,
    )
    from football_data_hub.providers.bdfutbol.match_details.campaign_operations import (
        run_offline_batch,
    )
    from football_data_hub.providers.bdfutbol.match_details.real_acquisition import (
        RealDiscoveryResponse,
    )
    from football_data_hub.providers.bdfutbol.match_details.semantic_parser import (
        ValidationCheck,
    )

    fixture = _fixture(tmp_path, monkeypatch)
    _initialize(fixture)
    campaign, _manifest, _plan = fixture.ledger._read_campaign(
        fixture.ledger.root / fixture.plan["campaign_id"]
    )
    update_job_id = str(uuid.uuid4())
    candidate_digest = candidate_set_sha256(
        update_job_id=update_job_id,
        campaign_id=fixture.plan["campaign_id"],
        source_generation_id=campaign["source"]["generation_id"],
        source_generation_manifest_sha256=campaign["source"][
            "generation_manifest_sha256"
        ],
        candidates=campaign["candidates"],
    )
    initial_status = _current_status(fixture)
    initial_status["campaign"].update(
        campaign_version=2, authorization_consumed=False, navigation_count=0
    )
    authorization_id = fixture.ledger.authorize_for_competition_update(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        confirmed_url=fixture.candidate["source_match_url"],
        update_job_id=update_job_id,
        candidate_set_sha256=candidate_digest,
        current_status=initial_status,
        published=False,
        captured=False,
        blocked=False,
        data_root=fixture.data_root,
    )
    accesses = []

    def access_once(config, *, url, session_factory):
        accesses.append((config.backend, url))
        return RealDiscoveryResponse(
            final_url=url,
            http_status=200,
            html=b"<!doctype html><html><head><title>Offline fixture</title></head><body>stored</body></html>",
            page_title="Offline fixture",
            access_classification="VALID",
            captured_at_utc="2026-10-20T10:00:00Z",
        )

    acquired = fixture.ledger.execute_for_competition_update(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        authorization_id=authorization_id,
        confirmed_url=fixture.candidate["source_match_url"],
        update_job_id=update_job_id,
        data_root=fixture.data_root,
        profile_dir=fixture.data_root
        / "browser-profiles"
        / f"match-detail-v2-{fixture.candidate['source_match_id']}",
        store_root=fixture.store_root,
        store_inventory=fixture.inventory,
        current_status=_current_status(fixture, "AUTO_POLICY_AUTHORIZED"),
        published=False,
        captured=False,
        blocked=False,
        access_runner=access_once,
    )
    assert acquired["status"] == "DISCOVERY_REVIEW_REQUIRED"
    assert accesses == [("seleniumbase-pure-cdp", fixture.candidate["source_match_url"])]

    checks = [ValidationCheck(name, True, "offline verified") for name in sorted(REQUIRED_CHECKS)]
    warnings = ["campaign_discovery_remains_unpromoted_pending_independent_review"]
    if extra_warning:
        warnings.append(extra_warning)
    validation = _FakeValidation(checks=checks, warnings=warnings)
    import football_data_hub.providers.bdfutbol.match_details.campaign_artifact as artifacts

    monkeypatch.setattr(
        artifacts,
        "parse_campaign_saved_artifact",
        lambda *_a, **_kw: SimpleNamespace(
            validation=validation,
            source=SimpleNamespace(parser_version="offline-test-parser"),
        ),
    )
    discovery = next(
        event
        for event in fixture.ledger.candidate_events(
            fixture.plan["campaign_id"], fixture.candidate["internal_id"]
        )
        if event["event_type"] == "DISCOVERY_REVIEW_REQUIRED"
    )
    draft = _valid_draft(fixture, discovery)
    monkeypatch.setattr(
        api_details,
        "build_campaign_publication_draft",
        lambda **_kwargs: draft,
    )
    monkeypatch.setattr(
        fixture.ledger,
        "_publication_inputs",
        lambda **_kwargs: (
            fixture.data_root,
            fixture.generation_root,
            SimpleNamespace(),
            set(),
        ),
    )
    loaded_document = MatchPublishedDetailsResponse.model_validate(draft["details"])
    monkeypatch.setattr(
        api_details,
        "load_published_match_details",
        lambda *_a, **_kw: {fixture.candidate["internal_id"]: loaded_document},
    )
    result = run_offline_batch(
        ledger=fixture.ledger,
        campaign_id=fixture.plan["campaign_id"],
        data_root=fixture.data_root,
        player_inventory_root=tmp_path,
        player_compact_root=tmp_path,
        player_team_captures_root=tmp_path,
        player_published_index_path=tmp_path / "players.json",
        auto_publish_policy=True,
        published_root=fixture.store_root / "published",
    )

    assert result["status"] == "COMPLETED", json.dumps(result, ensure_ascii=False, indent=2)
    assert result["published_count"] == expected_published_count, result
    assert accesses == [("seleniumbase-pure-cdp", fixture.candidate["source_match_url"])]
    events = fixture.ledger.candidate_events(
        fixture.plan["campaign_id"], fixture.candidate["internal_id"]
    )
    event_types = [event["event_type"] for event in events]
    if expected_published_count == 0:
        assert result["policy_pending_count"] == 1
        assert result["candidates"][0]["status"] == "PENDING_POLICY_REVIEW"
        assert "AUTO_POLICY_APPROVED" not in event_types
        assert not (fixture.store_root / "published" / "index.json").exists()
        return

    assert result["policy_pending_count"] == 0
    assert result["candidates"][0]["status"] == "PUBLISHED_VERIFIED"
    assert event_types[-2:] == [
        "AUTO_POLICY_APPROVED",
        "PUBLISHED",
    ]
    assert "DOCUMENT_APPROVED" not in event_types
    assert "REVIEW_COMPLETED" not in event_types
    receipt = json.loads(
        (fixture.store_root / "published" / "packages" / draft["publication_id"] / "approval.json").read_bytes()
    )
    assert receipt["approval_mode"] == "automatic_policy"
    assert receipt["update_job_id"] == update_job_id
    verified = fixture.ledger.verify_publication(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        data_root=fixture.data_root,
        generation_root=fixture.generation_root,
        published_root=fixture.store_root / "published",
        store_root=fixture.store_root,
        player_inventory_root=tmp_path,
        player_compact_root=tmp_path,
        player_team_captures_root=tmp_path,
        player_published_index_path=tmp_path / "players.json",
    )
    assert verified["status"] == "PUBLISHED_VERIFIED"


def test_offline_validation_rechecks_state_before_appending_after_concurrent_change(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    _initialize(fixture)
    _authorize(fixture)
    _execute(
        fixture,
        SimulatedMatchAccessAdapter(
            SimulatedAccessResponse(
                final_url=fixture.candidate["source_match_url"], http_status=200,
                html=b"<html><body>stored</body></html>", page_title="Fixture",
                access_classification="VALID",
            )
        ),
    )
    import football_data_hub.providers.bdfutbol.match_details.campaign_artifact as artifacts

    def concurrent_parser(*_args, **_kwargs):
        # A second validator commits while the first is parsing, before the
        # first validator reacquires the campaign lock.
        directory, campaign, events = fixture.ledger._events(
            fixture.plan["campaign_id"], fixture.candidate["internal_id"]
        )
        discovery = next(event for event in events if event["event_type"] == "DISCOVERY_REVIEW_REQUIRED")
        concurrent = {
            "event_type": "VALIDATED",
            "campaign_id": fixture.plan["campaign_id"],
            "internal_id": fixture.candidate["internal_id"],
            "semantic_valid": True,
            "source_html_sha256": discovery["artifact"]["source_html_sha256"],
            "evidence_sha256": "a" * 64,
        }
        fixture.ledger._append(directory, campaign, fixture.candidate["internal_id"], concurrent)
        return SimpleNamespace(validation=_FakeValidation(), source=SimpleNamespace(parser_version="offline-test-parser"))

    monkeypatch.setattr(artifacts, "parse_campaign_saved_artifact", concurrent_parser)
    with pytest.raises(MatchCampaignAuthorizationError, match="cambió durante la validación"):
        fixture.ledger.validate_offline_artifact(
            campaign_id=fixture.plan["campaign_id"],
            internal_id=fixture.candidate["internal_id"],
            data_root=fixture.data_root,
        )
    events = fixture.ledger.candidate_events(fixture.plan["campaign_id"], fixture.candidate["internal_id"])
    assert sum(event["event_type"] == "VALIDATED" for event in events) == 1


def test_v2_failed_validation_can_be_revalidated_without_recapture(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    _initialize(fixture)
    _authorize(fixture)
    _execute(
        fixture,
        SimulatedMatchAccessAdapter(
            SimulatedAccessResponse(
                final_url=fixture.candidate["source_match_url"],
                http_status=200,
                html=b"<html><head><title>Saved fixture</title></head><body>Saved</body></html>",
                page_title="Saved fixture",
                access_classification="VALID",
            )
        ),
    )
    import football_data_hub.providers.bdfutbol.match_details.campaign_artifact as artifacts

    parser_versions = []

    def parsed(semantic_valid, *, parser_version):
        parser_versions.append(parser_version)
        return SimpleNamespace(
            validation=_FakeValidation(
                semantic_valid=semantic_valid,
                parser_version=parser_version,
                errors=() if semantic_valid else ("unknown_event_icon:TG2",),
            ),
            source=SimpleNamespace(parser_version=parser_version),
        )

    monkeypatch.setattr(
        artifacts,
        "parse_campaign_saved_artifact",
        lambda *_a, **kwargs: parsed(False, parser_version=kwargs["parser_version"]),
    )
    initial = fixture.ledger.validate_offline_artifact(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        data_root=fixture.data_root,
    )
    assert initial["status"] == "VALIDATION_FAILED"
    assert initial["parser_version"] == PARSER_VERSION

    events_before = fixture.ledger.candidate_events(
        fixture.plan["campaign_id"], fixture.candidate["internal_id"]
    )
    original_failure = events_before[-1]
    discovery = next(
        event for event in events_before if event["event_type"] == "DISCOVERY_REVIEW_REQUIRED"
    )
    artifact_dir = (
        fixture.ledger.root
        / fixture.plan["campaign_id"]
        / discovery["artifact"]["artifact_relative_path"]
    )
    artifact_before = {
        path.name: path.read_bytes()
        for path in artifact_dir.iterdir()
        if path.is_file()
    }

    with pytest.raises(MatchCampaignAuthorizationError, match="operador y confirmación"):
        fixture.ledger.revalidate_failed_artifact(
            campaign_id=fixture.plan["campaign_id"],
            internal_id=fixture.candidate["internal_id"],
            data_root=fixture.data_root,
            operator="",
            confirmation="wrong",
        )
    other_candidate = next(
        item
        for item in fixture.plan["candidates"]
        if item["internal_id"] != fixture.candidate["internal_id"]
    )
    with pytest.raises(MatchCampaignAuthorizationError):
        fixture.ledger.revalidate_failed_artifact(
            campaign_id=fixture.plan["campaign_id"],
            internal_id=other_candidate["internal_id"],
            data_root=fixture.data_root,
            operator="offline-test-operator",
            confirmation=operational.REVALIDATE_CONFIRMATION,
        )

    failed_again = fixture.ledger.revalidate_failed_artifact(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        data_root=fixture.data_root,
        operator="offline-test-operator",
        confirmation=operational.REVALIDATE_CONFIRMATION,
    )
    assert failed_again["status"] == "REVALIDATION_FAILED"
    assert failed_again["parser_version"] == PARSER_VERSION
    assert fixture.ledger.candidate(fixture.plan["campaign_id"], fixture.candidate["internal_id"])["state"] == "REVALIDATION_FAILED"
    from football_data_hub.providers.bdfutbol.match_details.scalable_campaign_cli import (
        _read_campaign_states,
    )

    campaign_states, _ = _read_campaign_states(fixture.ledger.root)
    failed_row = next(
        row
        for row in classify_match_campaign_inventory(
            build_match_campaign_inventory(fixture.verified),
            campaign_states=campaign_states,
        )["matches"]
        if row["internal_id"] == fixture.candidate["internal_id"]
    )
    assert failed_row["detail_status"] == "blocked_requires_human_review"
    with pytest.raises(MatchCampaignAuthorizationError, match="REVALIDATION_FAILED"):
        fixture.ledger.prepare_draft(
            campaign_id=fixture.plan["campaign_id"],
            internal_id=fixture.candidate["internal_id"],
            data_root=fixture.data_root,
            generation_root=fixture.generation_root,
            player_inventory_root=tmp_path,
            player_compact_root=tmp_path,
            player_team_captures_root=tmp_path,
            player_published_index_path=tmp_path / "players.json",
        )

    monkeypatch.setattr(
        artifacts,
        "parse_campaign_saved_artifact",
        lambda *_a, **kwargs: parsed(True, parser_version=kwargs["parser_version"]),
    )
    revalidated = fixture.ledger.revalidate_failed_artifact(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        data_root=fixture.data_root,
        operator="offline-test-operator",
        confirmation=operational.REVALIDATE_CONFIRMATION,
    )
    assert revalidated["status"] == "REVALIDATED"
    assert revalidated["parser_version"] == PARSER_VERSION
    events_after = fixture.ledger.candidate_events(
        fixture.plan["campaign_id"], fixture.candidate["internal_id"]
    )
    assert next(event for event in events_after if event["event_type"] == "VALIDATION_FAILED") == original_failure
    assert [event["event_type"] for event in events_after][-3:] == [
        "VALIDATION_FAILED", "REVALIDATION_FAILED", "REVALIDATED"
    ]
    assert artifact_before == {
        path.name: path.read_bytes()
        for path in artifact_dir.iterdir()
        if path.is_file()
    }
    candidate_status = fixture.ledger.candidate(
        fixture.plan["campaign_id"], fixture.candidate["internal_id"]
    )
    assert candidate_status["state"] == "REVALIDATED"
    assert candidate_status["authorization_consumed"] is True
    assert candidate_status["navigation_count"] == 1
    assert parser_versions == [PARSER_VERSION] * 3
    campaign_states, _ = _read_campaign_states(fixture.ledger.root)
    revalidated_row = next(
        row
        for row in classify_match_campaign_inventory(
            build_match_campaign_inventory(fixture.verified),
            campaign_states=campaign_states,
        )["matches"]
        if row["internal_id"] == fixture.candidate["internal_id"]
    )
    assert revalidated_row["detail_status"] == "validated_pending_approval"

    retry = SimulatedMatchAccessAdapter(
        SimulatedAccessResponse(
            final_url=fixture.candidate["source_match_url"],
            http_status=200,
            html=b"must not navigate",
            access_classification="VALID",
        )
    )
    with pytest.raises(MatchCampaignAuthorizationError):
        _execute(fixture, retry)
    assert retry.calls == []

    draft = _valid_draft(fixture, discovery)
    monkeypatch.setattr(api_details, "build_campaign_publication_draft", lambda **_kw: draft)
    monkeypatch.setattr(
        fixture.ledger,
        "_publication_inputs",
        lambda **_kw: (fixture.data_root, fixture.generation_root, SimpleNamespace(), set()),
    )
    prepared = fixture.ledger.prepare_draft(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        data_root=fixture.data_root,
        generation_root=fixture.generation_root,
        player_inventory_root=tmp_path,
        player_compact_root=tmp_path,
        player_team_captures_root=tmp_path,
        player_published_index_path=tmp_path / "players.json",
    )
    assert prepared["status"] == "DRAFT_PREPARED"
    with pytest.raises(MatchCampaignAuthorizationError, match="sin aprobación humana"):
        fixture.ledger.publish(
            campaign_id=fixture.plan["campaign_id"],
            internal_id=fixture.candidate["internal_id"],
            data_root=fixture.data_root,
            generation_root=fixture.generation_root,
            published_root=fixture.store_root / "published",
            store_root=fixture.store_root,
            player_inventory_root=tmp_path,
            player_compact_root=tmp_path,
            player_team_captures_root=tmp_path,
            player_published_index_path=tmp_path / "players.json",
        )


@pytest.mark.parametrize("mode", ["stopped", "interrupted"])
def test_offline_revalidation_never_unlocks_access_or_interruption(
    tmp_path, monkeypatch, mode
):
    fixture = _fixture(tmp_path, monkeypatch)
    _initialize(fixture)
    _authorize(fixture)
    if mode == "stopped":
        response = SimulatedAccessResponse(
            final_url=fixture.candidate["source_match_url"],
            http_status=403,
            html=b"denied",
            access_classification="ACCESS_DENIED",
            denial_detected=True,
        )
        assert _execute(fixture, SimulatedMatchAccessAdapter(response))["status"] == "STOPPED"
    else:
        with pytest.raises(KeyboardInterrupt):
            _execute(fixture, SimulatedMatchAccessAdapter(error=KeyboardInterrupt()))

    import football_data_hub.providers.bdfutbol.match_details.campaign_artifact as artifacts

    monkeypatch.setattr(
        artifacts,
        "parse_campaign_saved_artifact",
        lambda *_a, **_kw: pytest.fail("Un estado de acceso no se revalida"),
    )
    with pytest.raises(MatchCampaignAuthorizationError):
        fixture.ledger.revalidate_failed_artifact(
            campaign_id=fixture.plan["campaign_id"],
            internal_id=fixture.candidate["internal_id"],
            data_root=fixture.data_root,
            operator="offline-test-operator",
            confirmation=operational.REVALIDATE_CONFIRMATION,
        )


def test_revalidation_rejects_corrupt_saved_artifact_without_appending(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    _initialize(fixture)
    _authorize(fixture)
    _execute(
        fixture,
        SimulatedMatchAccessAdapter(
            SimulatedAccessResponse(
                final_url=fixture.candidate["source_match_url"],
                http_status=200,
                html=b"<html><head><title>Saved fixture</title></head><body>Saved</body></html>",
                page_title="Saved fixture",
                access_classification="VALID",
            )
        ),
    )
    import football_data_hub.providers.bdfutbol.match_details.campaign_artifact as artifacts

    monkeypatch.setattr(
        artifacts,
        "parse_campaign_saved_artifact",
        lambda *_a, **kwargs: SimpleNamespace(
            validation=_FakeValidation(semantic_valid=False),
            source=SimpleNamespace(parser_version=kwargs["parser_version"]),
        ),
    )
    assert fixture.ledger.validate_offline_artifact(
        campaign_id=fixture.plan["campaign_id"],
        internal_id=fixture.candidate["internal_id"],
        data_root=fixture.data_root,
    )["status"] == "VALIDATION_FAILED"
    events_before = fixture.ledger.candidate_events(
        fixture.plan["campaign_id"], fixture.candidate["internal_id"]
    )
    discovery = next(
        event for event in events_before if event["event_type"] == "DISCOVERY_REVIEW_REQUIRED"
    )
    html_path = (
        fixture.ledger.root
        / fixture.plan["campaign_id"]
        / discovery["artifact"]["artifact_relative_path"]
        / "source.html"
    )
    html_path.write_bytes(html_path.read_bytes() + b"tampered")
    event_dir = (
        fixture.ledger.root
        / fixture.plan["campaign_id"]
        / "candidates"
        / fixture.candidate["internal_id"]
        / "events"
    )
    event_names_before = sorted(path.name for path in event_dir.iterdir())
    with pytest.raises(MatchCampaignIntegrityError, match="Hash inválido|no coincide"):
        fixture.ledger.revalidate_failed_artifact(
            campaign_id=fixture.plan["campaign_id"],
            internal_id=fixture.candidate["internal_id"],
            data_root=fixture.data_root,
            operator="offline-test-operator",
            confirmation=operational.REVALIDATE_CONFIRMATION,
        )
    assert sorted(path.name for path in event_dir.iterdir()) == event_names_before


def test_v2_artifact_sequence_accepts_offline_revalidation_but_v1_stays_unchanged():
    from football_data_hub.providers.bdfutbol.match_details.campaign_artifact import (
        CampaignArtifactError,
        _validate_discovery_event_sequence,
    )

    def events(*types):
        return [{"event_type": event_type} for event_type in (
            "AUTHORIZED", "STARTED", "DISCOVERY_REVIEW_REQUIRED", *types
        )]

    _validate_discovery_event_sequence(
        events(
            "VALIDATION_FAILED",
            "REVALIDATION_FAILED",
            "REVALIDATED",
            "DRAFT_PREPARED",
            "DOCUMENT_APPROVED",
            "PUBLISHED",
        ),
        operational_v2=True,
    )
    with pytest.raises(CampaignArtifactError):
        _validate_discovery_event_sequence(
            events("VALIDATION_FAILED", "DRAFT_PREPARED"), operational_v2=True
        )
    with pytest.raises(CampaignArtifactError):
        _validate_discovery_event_sequence(
            events("VALIDATION_FAILED"), operational_v2=False
        )
