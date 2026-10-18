from __future__ import annotations

import copy
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.match_details.campaign import (
    MatchCampaignAuthorizationError,
)
from football_data_hub.providers.bdfutbol.match_details.campaign_operations import (
    CampaignOperationsError,
    load_operation_report,
)
from football_data_hub.providers.bdfutbol.match_details.operational_campaign import (
    AUTHORIZE_CONFIRMATION,
    PLAYER_IDLE_CONFIRMATION,
)
from football_data_hub.providers.bdfutbol.match_details.supervised_acquisition import (
    SESSION_CONFIRMATION,
    authorize_reviewed_candidates,
    run_authorized_batch,
)
from football_data_hub.providers.bdfutbol.match_details.campaign import (
    SimulatedAccessResponse,
    SimulatedMatchAccessAdapter,
)


def _candidate(index: int, state: str = "AUTHORIZED") -> dict:
    match_id = str(300000 + index)
    return {
        "internal_id": f"pf-2026-27-group-i-bdfutbol-{match_id}",
        "source_match_id": match_id,
        "group": "I" if index % 2 == 0 else "II",
        "matchday": index % 8 + 1,
        "source_match_url": f"https://www.bdfutbol.com/es/p/p.php?id={match_id}",
        "source_generation_id": "match-00-supervised-fixture",
        "source_match_date": "2026-10-10",
        "home_team_name": f"Local {index}",
        "away_team_name": f"Visitante {index}",
        "reference_result": {"home_goals": 1, "away_goals": 0},
        "campaign_id": "match-detail-campaign-v2-abcdef0123456789",
        "state": state,
        "authorization_id": f"authorization-{index}" if state == "AUTHORIZED" else None,
    }


class _Ledger:
    def __init__(self, root: Path, candidates: list[dict]):
        self.root = root / "campaigns"
        self.root.mkdir(parents=True)
        self.rows = {row["internal_id"]: copy.deepcopy(row) for row in candidates}
        self.events = {
            row["internal_id"]: ([{
                "event_type": "AUTHORIZED",
                "authorization": {
                    "authorization_id": row["authorization_id"],
                    "source_match_url": row["source_match_url"],
                    "operator": "reviewer",
                },
            }] if row["state"] == "AUTHORIZED" else [])
            for row in candidates
        }
        self.authorization_calls = []

    def preflight(self, campaign_id):
        return {"campaign_id": campaign_id, "candidates": [copy.deepcopy(row) for row in self.rows.values()]}

    def candidate_events(self, _campaign_id, internal_id):
        return copy.deepcopy(self.events[internal_id])

    def authorize(self, *, campaign_id, internal_id, confirmed_url, operator, confirmation, current_status, **_kwargs):
        assert confirmation == AUTHORIZE_CONFIRMATION
        assert confirmed_url == self.rows[internal_id]["source_match_url"]
        assert current_status["source_match_url"] == confirmed_url
        assert self.rows[internal_id]["state"] == "NOT_AUTHORIZED"
        auth_id = f"new-authorization-{len(self.authorization_calls)}"
        self.authorization_calls.append((internal_id, confirmed_url, operator))
        self.rows[internal_id]["state"] = "AUTHORIZED"
        self.rows[internal_id]["authorization_id"] = auth_id
        self.events[internal_id] = [{
            "event_type": "AUTHORIZED",
            "authorization": {"authorization_id": auth_id, "source_match_url": confirmed_url, "operator": operator},
        }]
        return auth_id


def _snapshot(candidates: list[dict]):
    report = {"matches": [
        {
            **row,
            "detail_status": "authorized_not_executed" if row["state"] == "AUTHORIZED" else "included_in_existing_campaign",
            "campaign": {"campaign_id": row["campaign_id"], "campaign_version": 2, "state": row["state"]},
        }
        for row in candidates
    ]}
    return report, {"published_ids": set(), "captured_ids": set(), "blocked_ids": set()}


def _run(ledger, capture_root, candidates, execute_candidate, *, limit=20):
    return run_authorized_batch(
        ledger=ledger,
        campaign_id=candidates[0]["campaign_id"],
        data_root=capture_root.parent,
        player_capture_root=capture_root,
        operator="operator-test",
        limit=limit,
        confirmation=SESSION_CONFIRMATION,
        player_idle_confirmation=PLAYER_IDLE_CONFIRMATION,
        refresh_snapshot=lambda: _snapshot(list(ledger.rows.values())),
        execute_candidate=execute_candidate,
    )


def test_review_session_requires_individual_url_and_token_for_each_authorization(tmp_path):
    candidates = [_candidate(index, "NOT_AUTHORIZED") for index in range(20)]
    ledger = _Ledger(tmp_path / "data" / "matches" / "details", candidates)
    report, context = _snapshot(candidates)
    inputs = iter([
        candidates[0]["source_match_url"], AUTHORIZE_CONFIRMATION,
        "https://wrong.example/",
        candidates[2]["source_match_url"], "wrong token",
        *([""] * 17),
    ])
    result = authorize_reviewed_candidates(
        ledger=ledger,
        campaign_id=candidates[0]["campaign_id"],
        data_root=tmp_path / "data",
        status_report=report,
        context=context,
        operator="operator-test",
        input_fn=lambda _prompt: next(inputs),
        output_fn=lambda _line: None,
    )
    assert result["status"] == "COMPLETED"
    assert result["authorization_created"] == 1
    assert result["skipped_count"] == 19
    assert len(ledger.authorization_calls) == 1
    assert ledger.authorization_calls[0] == (
        candidates[0]["internal_id"], candidates[0]["source_match_url"], "operator-test"
    )
    persisted = load_operation_report(Path(result["report_path"]))
    assert persisted["browser_started"] is False
    assert persisted["navigation_enabled"] is False


def test_executor_is_sequential_and_only_consumes_authorized_candidates(tmp_path):
    candidates = [_candidate(index, "AUTHORIZED" if index < 10 else "NOT_AUTHORIZED") for index in range(20)]
    ledger = _Ledger(tmp_path / "data" / "matches" / "details", candidates)
    capture_root = tmp_path / "data" / "team-captures"
    capture_root.mkdir(parents=True)
    opened = []

    def execute(candidate, auth_id, current, context):
        adapter = SimulatedMatchAccessAdapter(SimulatedAccessResponse(
            final_url=candidate["source_match_url"], http_status=200,
            html=b"<html><body>simulated valid page</body></html>",
            page_title="Fixture", access_classification="VALID",
        ))
        response = adapter.open(candidate["source_match_url"])
        assert auth_id == candidate["authorization_id"]
        assert current["source_match_url"] == candidate["source_match_url"]
        assert context["blocked_ids"] == set()
        opened.append(candidate["internal_id"])
        ledger.rows[candidate["internal_id"]]["state"] = "DISCOVERY_REVIEW_REQUIRED"
        ledger.events[candidate["internal_id"]].append({"event_type": "STARTED"})
        return {"status": "DISCOVERY_REVIEW_REQUIRED", "attempt_id": f"attempt-{len(opened)}", "http_status": response.http_status}

    result = _run(ledger, capture_root, candidates, execute, limit=5)
    assert result["status"] == "COMPLETED"
    assert result["selected_authorized_count"] == 5
    assert result["captured_this_session"] == 5
    assert result["campaign_progress"]["captured"] == 5
    assert result["campaign_progress"]["authorized"] == 5
    expected_first = sorted(
        candidates[:10],
        key=lambda row: (row["group"], row["matchday"], int(row["source_match_id"])),
    )[:5]
    assert opened == [candidate["internal_id"] for candidate in expected_first]
    assert all(ledger.rows[candidate["internal_id"]]["state"] == "NOT_AUTHORIZED" for candidate in candidates[10:])
    second = _run(ledger, capture_root, candidates, execute, limit=20)
    assert second["selected_authorized_count"] == 5
    assert len(opened) == 10
    assert len(set(opened)) == 10


def test_execution_checkpoint_is_durable_before_simulated_navigation(tmp_path):
    candidates = [_candidate(index) for index in range(20)]
    ledger = _Ledger(tmp_path / "data" / "matches" / "details", candidates)
    capture_root = tmp_path / "data" / "team-captures"
    capture_root.mkdir(parents=True)
    opened = []

    def report_progress(event):
        if event["event"] != "candidate_starting":
            return
        reports = list(
            (ledger.root.parent / "operations" / "reports" / candidates[0]["campaign_id"])
            .glob("acquisition-*.json")
        )
        assert len(reports) == 1
        saved = load_operation_report(reports[0])
        row = next(item for item in saved["candidates"] if item["internal_id"] == event["internal_id"])
        assert row["status"] == "EXECUTION_PENDING"
        assert row["authorization_id"] == event["authorization_id"]

    def execute(candidate, _auth_id, _current, _context):
        adapter = SimulatedMatchAccessAdapter(SimulatedAccessResponse(
            final_url=candidate["source_match_url"], http_status=200,
            html=b"<html><body>valid test fixture</body></html>",
            page_title="Simulated match", access_classification="VALID",
        ))
        response = adapter.open(candidate["source_match_url"])
        opened.append(candidate["internal_id"])
        ledger.rows[candidate["internal_id"]]["state"] = "DISCOVERY_REVIEW_REQUIRED"
        ledger.events[candidate["internal_id"]].append({"event_type": "STARTED"})
        return {"status": "DISCOVERY_REVIEW_REQUIRED", "attempt_id": "simulated", "http_status": response.http_status}

    result = run_authorized_batch(
        ledger=ledger,
        campaign_id=candidates[0]["campaign_id"],
        data_root=tmp_path / "data",
        player_capture_root=capture_root,
        operator="operator-test",
        limit=1,
        confirmation=SESSION_CONFIRMATION,
        player_idle_confirmation=PLAYER_IDLE_CONFIRMATION,
        refresh_snapshot=lambda: _snapshot(candidates),
        execute_candidate=execute,
        progress_callback=report_progress,
    )
    assert result["status"] == "COMPLETED"
    assert opened == [candidates[0]["internal_id"]]
    assert result["browser_start_requested"] is True
    assert result["navigation_requests"] == 1


def test_access_restriction_stops_session_and_requires_manual_review_before_next_run(tmp_path):
    candidates = [_candidate(index) for index in range(20)]
    ledger = _Ledger(tmp_path / "data" / "matches" / "details", candidates)
    capture_root = tmp_path / "data" / "team-captures"
    capture_root.mkdir(parents=True)
    opened = []

    def denied(candidate, *_args):
        adapter = SimulatedMatchAccessAdapter(SimulatedAccessResponse(
            final_url=candidate["source_match_url"], http_status=403,
            html=b"denied", page_title="Denied", access_classification="ACCESS_DENIED",
            denial_detected=True,
        ))
        adapter.open(candidate["source_match_url"])
        opened.append(candidate["internal_id"])
        ledger.rows[candidate["internal_id"]]["state"] = "STOPPED"
        ledger.events[candidate["internal_id"]].append({"event_type": "STARTED"})
        return {"status": "STOPPED", "error_code": "HTTP_403", "attempt_id": "attempt-denied"}

    result = _run(ledger, capture_root, candidates, denied)
    assert result["status"] == "BLOCKED_MANUAL_REVIEW"
    assert result["stop_acquisition"] is True
    assert result["access_failure_count"] == 1
    assert opened == [candidates[0]["internal_id"]]
    with pytest.raises(CampaignOperationsError, match="parada previa"):
        _run(ledger, capture_root, candidates, denied)
    assert len(opened) == 1


def test_existing_stopped_candidate_blocks_other_authorizations(tmp_path):
    candidates = [_candidate(0, "STOPPED"), _candidate(1, "AUTHORIZED")]
    ledger = _Ledger(tmp_path / "data" / "matches" / "details", candidates)
    capture_root = tmp_path / "data" / "team-captures"
    capture_root.mkdir(parents=True)
    opened = []
    result = _run(
        ledger, capture_root, candidates,
        lambda *args: opened.append(args), limit=2,
    )
    assert result["status"] == "BLOCKED_PRECONDITION"
    assert "revisión humana" in result["diagnostic"]
    assert opened == []
    assert ledger.rows[candidates[1]["internal_id"]]["state"] == "AUTHORIZED"


def test_interruption_leaves_started_candidate_unrepeatable_and_resumes_other_authorizations(tmp_path):
    candidates = [_candidate(index) for index in range(20)]
    ledger = _Ledger(tmp_path / "data" / "matches" / "details", candidates)
    capture_root = tmp_path / "data" / "team-captures"
    capture_root.mkdir(parents=True)
    opened = []

    def interrupt_first(candidate, *_args):
        adapter = SimulatedMatchAccessAdapter(SimulatedAccessResponse(
            final_url=candidate["source_match_url"], http_status=200,
            html=b"simulated", page_title="Fixture", access_classification="VALID",
        ))
        adapter.open(candidate["source_match_url"])
        opened.append(candidate["internal_id"])
        ledger.rows[candidate["internal_id"]]["state"] = "INTERRUPTED_REQUIRES_REVIEW"
        ledger.events[candidate["internal_id"]].append({"event_type": "STARTED"})
        raise KeyboardInterrupt

    first = _run(ledger, capture_root, candidates, interrupt_first, limit=3)
    assert first["status"] == "INTERRUPTED"
    assert first["candidates"][0]["status"] == "INTERRUPTED"

    def complete(candidate, *_args):
        adapter = SimulatedMatchAccessAdapter(SimulatedAccessResponse(
            final_url=candidate["source_match_url"], http_status=200,
            html=b"simulated", page_title="Fixture", access_classification="VALID",
        ))
        response = adapter.open(candidate["source_match_url"])
        opened.append(candidate["internal_id"])
        ledger.rows[candidate["internal_id"]]["state"] = "DISCOVERY_REVIEW_REQUIRED"
        ledger.events[candidate["internal_id"]].append({"event_type": "STARTED"})
        return {"status": "DISCOVERY_REVIEW_REQUIRED", "attempt_id": f"attempt-{len(opened)}", "http_status": response.http_status}

    resumed = _run(ledger, capture_root, candidates, complete, limit=20)
    assert resumed["status"] == "COMPLETED"
    assert resumed["selected_authorized_count"] == 19
    assert candidates[0]["internal_id"] not in opened[1:]
    assert len(opened) == 20


def test_player_acquisition_lock_blocks_match_navigation_before_any_attempt(tmp_path):
    from football_data_hub.providers.bdfutbol.players.batch import PlayerBatchLock

    candidates = [_candidate(index) for index in range(2)]
    ledger = _Ledger(tmp_path / "data" / "matches" / "details", candidates)
    capture_root = tmp_path / "data" / "team-captures"
    capture_root.mkdir(parents=True)
    opened = []
    with PlayerBatchLock(capture_root):
        report = _run(
            ledger,
            capture_root,
            candidates,
            lambda *args: opened.append(args),
            limit=2,
        )
    assert report["status"] == "BLOCKED_PRECONDITION"
    assert not opened
    assert all(row["state"] == "AUTHORIZED" for row in ledger.rows.values())


def test_session_confirmation_is_required_before_work(tmp_path):
    candidates = [_candidate(0)]
    ledger = _Ledger(tmp_path / "data" / "matches" / "details", candidates)
    capture_root = tmp_path / "data" / "team-captures"
    capture_root.mkdir(parents=True)
    with pytest.raises(MatchCampaignAuthorizationError, match="confirmación humana"):
        run_authorized_batch(
            ledger=ledger,
            campaign_id=candidates[0]["campaign_id"],
            data_root=tmp_path / "data",
            player_capture_root=capture_root,
            operator="operator-test",
            limit=1,
            confirmation="",
            player_idle_confirmation=PLAYER_IDLE_CONFIRMATION,
            refresh_snapshot=lambda: _snapshot(candidates),
            execute_candidate=lambda *_args: pytest.fail("no debe navegar"),
        )
