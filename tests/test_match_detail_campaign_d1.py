from __future__ import annotations

import json
from pathlib import Path

import pytest

from football_data_hub.core.browser_session import PageVisit
from football_data_hub.providers.bdfutbol.match_details.campaign import (
    MatchCampaignAuthorizationError,
    MatchDetailCampaignLedger,
)
from football_data_hub.providers.bdfutbol.match_details.real_acquisition import (
    REAL_EXECUTION_CONFIRMATION,
    RealDiscoveryResponse,
    run_authorized_real_candidate,
)
from tests.test_match_detail_campaign import _add_review, _authorize, _plan, _plan_ids


def _prepare(tmp_path, monkeypatch):
    import football_data_hub.providers.bdfutbol.match_details.real_acquisition as real

    plan = _plan()
    ledger = MatchDetailCampaignLedger(tmp_path / "campaigns")
    review_id = _add_review(ledger, plan)
    authorization_id = _authorize(ledger, plan, review_id)
    candidate_id, url = _plan_ids(plan)
    review_dir = (
        ledger.root
        / plan["campaign"]["campaign_id"]
        / "reviews/legacy-stop"
        / review_id
    )
    evidence = json.loads((review_dir / "review.json").read_text())["evidence_verification"]
    monkeypatch.setattr(real, "verify_historical_stop_evidence", lambda *a, **k: evidence)
    monkeypatch.setattr(real, "_store_checkpoint_is_unchanged", lambda *a: None)
    monkeypatch.setattr(real, "load_verified_match_generation", lambda *a, **k: object())
    monkeypatch.setattr(real, "build_match_detail_inventory", lambda _: {"inventory_id": plan["source"]["inventory_id"], "matches": []})
    monkeypatch.setattr(
        real.MatchDetailStore,
        "reconcile",
        lambda self, inventory: {"integrity_blocked": False},
    )
    data_root = tmp_path / "FootballDataHub-data"
    data_root.mkdir()
    return real, plan, ledger, candidate_id, url, authorization_id, data_root


def _run(tmp_path, real, plan, ledger, candidate_id, url, authorization_id, data_root):
    return run_authorized_real_candidate(
        plan=plan,
        ledger=ledger,
        internal_id=candidate_id,
        authorization_id=authorization_id,
        confirmed_url=url,
        data_root=data_root,
        generation_root=tmp_path / "generation",
        inventory_dir=tmp_path / "inventory",
        store_root=tmp_path / "match-store",
        profile_dir=data_root / "browser-profiles" / "match-detail-272525",
        confirmation=REAL_EXECUTION_CONFIRMATION,
        player_browser_idle_confirmation="PLAYER_BROWSER_IDLE_CONFIRMED",
    )


def test_real_executor_persists_started_before_its_single_access_call(tmp_path, monkeypatch):
    real, plan, ledger, candidate_id, url, authorization_id, data_root = _prepare(tmp_path, monkeypatch)
    calls = []

    def one_access(config, *, url, session_factory):
        calls.append(url)
        spec = real._campaign_spec(plan)
        campaign_dir = ledger.root / spec["campaign_id"]
        events = ledger._read_events(
            ledger._candidate_dir(campaign_dir, candidate_id),
            spec["campaign_id"],
            candidate_id,
        )
        assert events[-1]["event_type"] == "STARTED"
        assert events[-1]["requested_url"] == url
        assert events[-1]["maximum_navigations"] == 1
        return RealDiscoveryResponse(
            final_url=url,
            http_status=200,
            html=b"<html><body>Unverified BDFutbol page</body></html>",
            page_title="Unverified fixture",
            access_classification="INVALID_CONTENT",
        )

    monkeypatch.setattr(real, "_open_real_once", one_access)
    result = _run(tmp_path, real, plan, ledger, candidate_id, url, authorization_id, data_root)

    assert calls == [url]
    assert result.status == "DISCOVERY_REVIEW_REQUIRED"
    assert result.capture_promoted is False
    assert result.artifact is not None
    preflight = ledger.preflight(plan)
    assert preflight["candidates"][0]["navigation_count"] == 1
    assert preflight["candidates"][0]["capture_promoted"] is False


@pytest.mark.parametrize(
    ("status", "final_suffix", "classification", "challenge", "expected"),
    [
        (403, None, "HTTP_ERROR", False, "HTTP_403"),
        (429, None, "HTTP_ERROR", False, "HTTP_429"),
        (500, None, "HTTP_ERROR", False, "HTTP_500"),
        (200, None, "CHALLENGE_REQUIRED", True, "CHALLENGE_REQUIRED"),
        (200, "?redirect=1", "INVALID_URL", False, "INVALID_URL"),
        (None, None, "HTTP_ERROR", False, "HTTP_UNKNOWN"),
    ],
)
def test_real_executor_stops_on_access_failure_without_artifact_or_retry(
    tmp_path, monkeypatch, status, final_suffix, classification, challenge, expected
):
    real, plan, ledger, candidate_id, url, authorization_id, data_root = _prepare(tmp_path, monkeypatch)
    calls = []

    def one_access(config, *, url, session_factory):
        calls.append(url)
        return RealDiscoveryResponse(
            final_url=url + final_suffix if final_suffix else url,
            http_status=status,
            html=b"<html><body>diagnostic-only</body></html>",
            page_title="fixture",
            access_classification=classification,
            challenge_detected=challenge,
        )

    monkeypatch.setattr(real, "_open_real_once", one_access)
    result = _run(tmp_path, real, plan, ledger, candidate_id, url, authorization_id, data_root)

    assert calls == [url]
    assert result.status == "STOPPED"
    assert result.error_code == expected
    assert result.artifact is None
    state = ledger.preflight(plan)["candidates"][0]
    assert state["navigation_count"] == 1
    assert state["capture_promoted"] is False


def test_real_timeout_consumes_authorization_and_does_not_retry(tmp_path, monkeypatch):
    real, plan, ledger, candidate_id, url, authorization_id, data_root = _prepare(tmp_path, monkeypatch)
    calls = []

    def timeout_once(config, *, url, session_factory):
        calls.append(url)
        raise TimeoutError("simulated navigation timeout")

    monkeypatch.setattr(real, "_open_real_once", timeout_once)
    result = _run(tmp_path, real, plan, ledger, candidate_id, url, authorization_id, data_root)

    assert calls == [url]
    assert result.status == "STOPPED"
    assert result.error_code == "BROWSER_OR_NAVIGATION_ERROR"
    with pytest.raises(MatchCampaignAuthorizationError):
        _run(tmp_path, real, plan, ledger, candidate_id, url, authorization_id, data_root)
    assert calls == [url]


def test_abrupt_interruption_after_reservation_leaves_candidate_nonrepeatable(tmp_path, monkeypatch):
    real, plan, ledger, candidate_id, url, authorization_id, data_root = _prepare(tmp_path, monkeypatch)
    calls = []

    class AbruptInterruption(BaseException):
        pass

    def interrupted(config, *, url, session_factory):
        calls.append(url)
        raise AbruptInterruption("simulated hard interruption")

    monkeypatch.setattr(real, "_open_real_once", interrupted)
    with pytest.raises(AbruptInterruption):
        _run(tmp_path, real, plan, ledger, candidate_id, url, authorization_id, data_root)
    state = ledger.preflight(plan)["candidates"][0]
    assert state["state"] == "INTERRUPTED_REQUIRES_REVIEW"
    with pytest.raises(MatchCampaignAuthorizationError):
        _run(tmp_path, real, plan, ledger, candidate_id, url, authorization_id, data_root)
    assert calls == [url]


def test_real_authorization_requires_exact_review_url_and_revalidated_evidence(
    tmp_path, monkeypatch
):
    import football_data_hub.providers.bdfutbol.match_details.historical_review as review_module

    plan = _plan()
    ledger = MatchDetailCampaignLedger(tmp_path / "campaigns")
    review_id = _add_review(ledger, plan)
    internal_id, url = _plan_ids(plan)
    review_path = (
        ledger.root
        / plan["campaign"]["campaign_id"]
        / "reviews/legacy-stop"
        / review_id
        / "review.json"
    )
    evidence = json.loads(review_path.read_text())["evidence_verification"]
    monkeypatch.setattr(
        review_module, "verify_historical_stop_evidence", lambda *a, **k: evidence
    )
    common = {
        "plan": plan,
        "internal_id": internal_id,
        "reviewer": "offline synthetic authorizer",
        "review_id": review_id,
        "data_root": tmp_path,
        "generation_root": tmp_path / "generation",
        "inventory_dir": tmp_path / "inventory",
        "store_root": tmp_path / "match-store",
        "confirmation": "AUTHORIZE_ONE_DISCOVERY_NAVIGATION",
        "authorized_at_utc": "2026-10-17T10:02:00Z",
    }
    with pytest.raises(MatchCampaignAuthorizationError, match="URL no pertenece"):
        ledger.authorize_candidate(**common, confirmed_url=url + "?unexpected=1")
    authorization_id = ledger.authorize_candidate(**common, confirmed_url=url)

    report = ledger.preflight(plan)
    assert authorization_id.startswith("match-detail-authorization-")
    assert report["candidates"][0]["state"] == "AUTHORIZED"


def test_candidate_and_confirmed_url_are_bound_before_profile_or_navigation(tmp_path, monkeypatch):
    real, plan, ledger, candidate_id, url, authorization_id, data_root = _prepare(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(real, "_open_real_once", lambda *a, **k: calls.append(k["url"]))
    with pytest.raises(MatchCampaignAuthorizationError, match="URL confirmada"):
        _run(
            tmp_path, real, plan, ledger, candidate_id, url + "?other=1",
            authorization_id, data_root,
        )
    assert calls == []


def test_real_adapter_uses_existing_session_and_reads_one_dom_without_browser_start():
    import football_data_hub.providers.bdfutbol.match_details.real_acquisition as real

    class Document:
        url = "https://www.bdfutbol.com/es/p/p.php?id=272525"

        def title(self):
            return "fixture title"

        def text(self, selector):
            assert selector == "body"
            return "BDFutbol"

        def texts(self, selector):
            return []

        def exists(self, selector):
            return selector == "body"

        def html(self):
            return "<html><body>BDFutbol</body></html>"

        def wait(self, milliseconds):
            assert milliseconds >= 0

        def close(self):
            pass

    class Session:
        def __init__(self, config):
            self.config = config
            self.calls = []
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.closed = True

        def open_page(self, url):
            self.calls.append(url)
            return PageVisit(Document(), url, 200)

    sessions = []

    def factory(config):
        session = Session(config)
        sessions.append(session)
        return session

    from football_data_hub.core.browser_runtime import BrowserRuntimeConfig

    config = BrowserRuntimeConfig(
        profile_dir=Path("/tmp/fdh-d1-profile-not-started"),
        backend="seleniumbase-pure-cdp",
        browser="chromium",
        use_xvfb=True,
        start_url="about:blank",
    )
    result = real._open_real_once(
        config,
        url="https://www.bdfutbol.com/es/p/p.php?id=272525",
        session_factory=factory,
    )

    assert len(sessions) == 1
    assert sessions[0].calls == ["https://www.bdfutbol.com/es/p/p.php?id=272525"]
    assert sessions[0].closed is True
    assert result.http_status == 200
    assert result.access_classification == "VALID"
    assert result.html == b"<html><body>BDFutbol</body></html>"
