from __future__ import annotations

import hashlib
from datetime import date
from types import SimpleNamespace

import pytest

from football_data_hub.providers.bdfutbol.match_details.scalable_campaigns import (
    ScalableCampaignError,
    build_incremental_match_detail_report,
    build_match_campaign_inventory,
    build_match_campaign_proposal,
    classify_match_campaign_inventory,
    load_match_campaign_proposals,
    write_match_campaign_proposal,
)


def _verified(*, generation_id="match-00-test-generation", records=None):
    groups = {}
    captures = []
    for index, group in enumerate(("I", "II")):
        teams = [{"team_id": index * 100 + number + 1, "name": f"Equipo {group} {number + 1}"} for number in range(20)]
        matches = (records or {}).get(group, [
            _match(group, "10001" if group == "I" else "20001", "played", 1, teams[0]["team_id"], teams[1]["team_id"]),
            _match(group, "10002" if group == "I" else "20002", "played", 3, teams[2]["team_id"], teams[3]["team_id"], url=None),
            _match(group, "10003" if group == "I" else "20003", "unplayed", 4, teams[4]["team_id"], teams[5]["team_id"]),
        ])
        groups[group] = {"group": group, "teams": teams, "matches": matches}
        captures.append({
            "group": group,
            "capture_id": f"capture-{group}",
            "captured_at_utc": "2026-10-14T10:00:00Z",
            "source_snapshot_sha256": "a" * 64,
            "files": {
                "source_html": {"sha256": "b" * 64},
                "normalized_matches": {"sha256": "c" * 64},
            },
        })
    return SimpleNamespace(
        generation_id=generation_id,
        manifest_sha256=hashlib.sha256(generation_id.encode()).hexdigest(),
        matches_payload={"groups": groups},
        manifest_payload={"source_captures": captures},
    )


def _match(group, source_id, status, matchday, home, away, *, url="default"):
    return {
        "internal_id": f"pf-2026-27-group-{group.lower()}-bdfutbol-{source_id}",
        "source_match_id": source_id,
        "status": status,
        "matchday": matchday,
        "matchday_date": f"2026-09-{matchday + 1:02d}",
        "source_match_date": f"2026-09-{matchday + 1:02d}" if status == "played" else None,
        "home_team_id": home,
        "away_team_id": away,
        "home_goals": 2 if status == "played" else None,
        "away_goals": 1 if status == "played" else None,
        "source_match_url": (
            f"https://www.bdfutbol.com/es/p/p.php?id={source_id}"
            if url == "default" else url
        ),
    }


def _status(*, generation_id="match-00-test-generation", states=None, **kwargs):
    inventory = build_match_campaign_inventory(_verified(generation_id=generation_id))
    return classify_match_campaign_inventory(inventory, campaign_states=states or {}, **kwargs)


def test_complete_inventory_includes_played_unplayed_and_url_missing_fixtures():
    inventory = build_match_campaign_inventory(_verified())
    assert inventory["counts"] == {
        "fixtures": 6,
        "groups": {"I": 3, "II": 3},
        "played": 4,
        "unplayed": 2,
        "incomplete": 0,
        "played_with_explicit_url": 2,
        "played_without_explicit_url": 2,
    }
    assert inventory["matches"][0]["source_generation_manifest_sha256"]
    assert inventory["matches"][0]["source_capture_id"] == "capture-I"


def test_inventory_rejects_duplicate_source_ids_and_contradictory_team_identity():
    duplicate = _verified(records={
        "I": [
            _match("I", "12345", "played", 1, 1, 2),
            _match("I", "12345", "played", 2, 3, 4),
        ],
        "II": [_match("II", "22345", "played", 1, 101, 102)],
    })
    with pytest.raises(ScalableCampaignError, match="duplicada"):
        build_match_campaign_inventory(duplicate)

    mismatch = _verified(records={
        "I": [_match("I", "12345", "played", 1, 999, 2)],
        "II": [_match("II", "22345", "played", 1, 101, 102)],
    })
    with pytest.raises(ScalableCampaignError, match="equipos"):
        build_match_campaign_inventory(mismatch)


def test_proposal_filters_by_group_matchday_and_limit_in_stable_order():
    report = _status()
    both = build_match_campaign_proposal(report, groups=("I", "II"), limit=10)
    assert [candidate["source_match_id"] for candidate in both["candidates"]] == ["10001", "20001"]
    assert both["candidate_count"] == 2
    assert both["authorization"]["is_authorization"] is False
    assert both["authorization"]["navigation_enabled"] is False
    only_ii = build_match_campaign_proposal(report, groups=("II",), matchday_from=1, matchday_to=2)
    assert [candidate["source_match_id"] for candidate in only_ii["candidates"]] == ["20001"]


def test_proposal_excludes_published_managed_consumed_blocked_and_unverified_url():
    inventory = build_match_campaign_inventory(_verified())
    rows = inventory["matches"]
    ids = {row["source_match_id"]: row["internal_id"] for row in rows}
    state_report = classify_match_campaign_inventory(
        inventory,
        published_ids={ids["10001"]},
        campaign_states={
            ids["20001"]: {"campaign_id": "old-campaign", "state": "AUTHORIZED", "authorization_consumed": False},
            ids["10002"]: {"campaign_id": "old-campaign", "state": "DISCOVERY_REVIEW_REQUIRED", "authorization_consumed": True},
        },
        blocked_reasons={ids["20002"]: ["HTTP_403"]},
    )
    proposal = build_match_campaign_proposal(state_report, limit=10)
    assert proposal["candidate_count"] == 0
    by_id = {row["source_match_id"]: row["detail_status"] for row in state_report["matches"]}
    assert by_id["10001"] == "published_approved"
    assert by_id["20001"] == "authorized_not_executed"
    assert by_id["10002"] == "captured_pending_validation"
    assert by_id["20002"] == "blocked_requires_human_review"
    assert by_id["10003"] == "unplayed"


def test_lifecycle_distinguishes_capture_validation_approval_publication_and_review():
    inventory = build_match_campaign_inventory(_verified())
    records = inventory["matches"]
    for record in records:
        if record["source_match_id"] in {"10003", "20003"}:
            record["status"] = "played"
            record["reference_result"] = {"home_goals": 0, "away_goals": 0}
            record["source_match_url"] = "https://www.bdfutbol.com/es/p/p.php?id=10003"
    ids = {row["source_match_id"]: row["internal_id"] for row in records}
    report = classify_match_campaign_inventory(
        inventory,
        published_ids={ids["10001"]},
        campaign_states={
            ids["10001"]: {"campaign_id": "c", "state": "REVIEW_COMPLETED"},
            ids["20001"]: {"campaign_id": "c", "state": "DISCOVERY_REVIEW_REQUIRED"},
            ids["10002"]: {"campaign_id": "c", "state": "AUTHORIZED"},
        },
        validated_pending_approval_ids={ids["20002"]},
        approved_pending_publication_ids={ids["10003"]},
        captured_ids={ids["20003"]},
    )
    states = {row["source_match_id"]: row["detail_status"] for row in report["matches"]}
    assert states == {
        "10001": "review_completed",
        "20001": "captured_pending_validation",
        "10002": "authorized_not_executed",
        "20002": "validated_pending_approval",
        "10003": "approved_pending_publication",
        "20003": "captured_pending_validation",
    }
    assert report["http_enabled"] is False and report["authorization_created"] is False


def test_newly_played_fixture_becomes_candidate_only_with_verified_url():
    generation = _verified(records={
        "I": [_match("I", "12345", "played", 1, 1, 2)],
        "II": [_match("II", "22345", "played", 1, 101, 102)],
    })
    inventory = build_match_campaign_inventory(generation)
    report = classify_match_campaign_inventory(inventory)
    assert build_match_campaign_proposal(report)["candidate_count"] == 2
    changed = _verified(records={
        "I": [_match("I", "12345", "played", 1, 1, 2, url=None)],
        "II": [_match("II", "22345", "played", 1, 101, 102)],
    })
    report = classify_match_campaign_inventory(build_match_campaign_inventory(changed))
    statuses = {row["source_match_id"]: row["detail_status"] for row in report["matches"]}
    assert statuses["12345"] == "played_without_verified_url"
    assert build_match_campaign_proposal(report)["candidate_count"] == 1


def test_incremental_diff_identifies_newly_played_matches_without_revisiting_old_ones():
    inventory = build_match_campaign_inventory(_verified(records={
        "I": [_match("I", "12345", "played", 1, 1, 2)],
        "II": [_match("II", "22345", "played", 1, 101, 102)],
    }))
    current_status = classify_match_campaign_inventory(inventory)

    def bundle(generation_id, played):
        fixtures = []
        for group, source_id, home, away in (("I", "12345", 1, 2), ("II", "22345", 101, 102)):
            fixtures.append(SimpleNamespace(
                internal_id=f"pf-2026-27-group-{group.lower()}-bdfutbol-{source_id}",
                source_match_id=source_id,
                group=group,
                matchday=1,
                matchday_date=date(2026, 9, 2),
                source_match_date=date(2026, 9, 2) if played else None,
                kickoff_time_local=None,
                home_team_id=home,
                away_team_id=away,
                home_goals=2 if played else None,
                away_goals=1 if played else None,
                status="played" if played else "unplayed",
                source_match_url=f"https://www.bdfutbol.com/es/p/p.php?id={source_id}",
                stadium_id=None,
                stadium_name=None,
                stadium_url=None,
                referee_id=None,
                referee_name=None,
                referee_url=None,
            ))
        return SimpleNamespace(bootstrap=SimpleNamespace(
            metadata=SimpleNamespace(generation_id=generation_id, generation_sha256="d" * 64),
            groups={"I": SimpleNamespace(matches=fixtures[:1]), "II": SimpleNamespace(matches=fixtures[1:])},
        ))

    incremental = build_incremental_match_detail_report(
        bundle("generation-old", False),
        bundle("generation-new", True),
        current_status,
    )
    assert incremental["newly_played_count"] == 2
    assert incremental["newly_played_missing_details_count"] == 2
    assert {item["source_match_id"] for item in incremental["newly_played"]} == {"12345", "22345"}


def test_campaign_identity_is_versioned_by_generation_and_selection():
    report_a = _status(generation_id="generation-a")
    report_b = _status(generation_id="generation-b")
    plan_a = build_match_campaign_proposal(report_a, limit=1)
    plan_a_again = build_match_campaign_proposal(report_a, limit=1)
    plan_b = build_match_campaign_proposal(report_b, limit=1)
    assert plan_a["proposal_id"] == plan_a_again["proposal_id"]
    assert plan_a["proposal_id"] != plan_b["proposal_id"]
    assert plan_a["source"]["generation_id"] == "generation-a"


def test_proposal_write_is_atomic_immutable_idempotent_and_hash_checked(tmp_path):
    plan = build_match_campaign_proposal(_status(), limit=1)
    target = write_match_campaign_proposal(tmp_path / "proposals", plan)
    assert write_match_campaign_proposal(tmp_path / "proposals", plan) == target
    loaded = load_match_campaign_proposals(tmp_path / "proposals")
    assert loaded == [plan]

    manifest = target / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ScalableCampaignError, match="Hashes|contrato"):
        load_match_campaign_proposals(tmp_path / "proposals")


def test_interrupted_partial_plan_is_not_silently_replaced(tmp_path):
    plan = build_match_campaign_proposal(_status(), limit=1)
    plans_root = tmp_path / "proposals" / "plans"
    target = plans_root / plan["proposal_id"]
    target.mkdir(parents=True)
    (target / "plan.json").write_text("partial", encoding="utf-8")
    with pytest.raises(ScalableCampaignError):
        write_match_campaign_proposal(tmp_path / "proposals", plan)
    assert (target / "plan.json").read_text(encoding="utf-8") == "partial"


def test_failure_before_atomic_install_leaves_no_partial_target_and_can_be_retried(tmp_path, monkeypatch):
    import football_data_hub.providers.bdfutbol.match_details.scalable_campaigns as module

    plan = build_match_campaign_proposal(_status(), limit=1)
    original_rename = module.os.rename

    def interrupted(*_args, **_kwargs):
        raise OSError("simulated stop before directory installation")

    monkeypatch.setattr(module.os, "rename", interrupted)
    with pytest.raises(OSError, match="simulated stop"):
        write_match_campaign_proposal(tmp_path / "proposals", plan)
    plans_root = tmp_path / "proposals" / "plans"
    assert not (plans_root / plan["proposal_id"]).exists()
    assert list(plans_root.iterdir()) == []

    monkeypatch.setattr(module.os, "rename", original_rename)
    assert write_match_campaign_proposal(tmp_path / "proposals", plan).is_dir()


def test_proposal_writer_rejects_dangling_symlink_instead_of_replacing_it(tmp_path):
    plan = build_match_campaign_proposal(_status(), limit=1)
    plans_root = tmp_path / "proposals" / "plans"
    plans_root.mkdir(parents=True)
    target = plans_root / plan["proposal_id"]
    target.symlink_to(tmp_path / "missing-target")
    with pytest.raises(ScalableCampaignError, match="symlink"):
        write_match_campaign_proposal(tmp_path / "proposals", plan)
    assert target.is_symlink()


def test_candidate_without_source_url_is_never_added_to_proposal():
    report = _status()
    proposal = build_match_campaign_proposal(report, groups=("I",), matchday_from=3, matchday_to=3)
    assert proposal["candidate_count"] == 0
    with pytest.raises(ScalableCampaignError, match="jornada"):
        build_match_campaign_proposal(report, matchday_from=5, matchday_to=2)
