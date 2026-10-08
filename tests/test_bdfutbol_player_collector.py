from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from football_data_hub.collectors.bdfutbol_player import (
    PlayerAcquisitionStopped,
    build_player_acquisition_plan,
    capture_player_snapshots,
    player_view_url,
)
from football_data_hub.collectors import bdfutbol_player as player_collector
from football_data_hub.parsers.player_pages import PLAYER_VIEWS, discover_player_snapshots
from football_data_hub.providers.bdfutbol.access import AccessAssessment, AccessStatus
from scrape_bdfutbol_players import dry_run


def _assessment(url: str, status: AccessStatus = AccessStatus.VALID) -> AccessAssessment:
    return AccessAssessment(
        status=status,
        requested_url=url,
        final_url=url,
        http_status=200 if status is AccessStatus.VALID else 403,
        page_title="Synthetic offline response",
        reason=None if status is AccessStatus.VALID else "challenge simulated by test",
    )


def _write_valid_snapshot(directory: Path, url: str) -> None:
    directory.mkdir(parents=True)
    raw = b"<html><body>synthetic test snapshot</body></html>"
    (directory / "rendered.html").write_bytes(raw)
    (directory / "metadata.json").write_text(json.dumps({
        "requested_url": url,
        "final_url": url,
        "access_status": "VALID",
        "http_status": 200,
        "captured_at_utc": "2026-10-08T12:00:00+00:00",
        "rendered_html_bytes": len(raw),
        "rendered_html_sha256": hashlib.sha256(raw).hexdigest(),
    }), encoding="utf-8")


def _install_fake_browser(monkeypatch: pytest.MonkeyPatch, statuses: list[AccessStatus]) -> list[str]:
    from football_data_hub.core import browser_session
    from football_data_hub.providers.bdfutbol import access as access_module
    from football_data_hub.providers.bdfutbol import discovery

    calls: list[str] = []

    class Session:
        def __init__(self, _config: object) -> None:
            pass

        def __enter__(self) -> Session:
            return self

        def __exit__(self, *_: object) -> None:
            pass

    class VisitContext:
        def __init__(self, assessment: AccessAssessment) -> None:
            self.assessment = assessment
            self.visit = SimpleNamespace(page=object())

        def __enter__(self) -> VisitContext:
            return self

        def __exit__(self, *_: object) -> None:
            pass

    class Access:
        def __init__(self, _session: object) -> None:
            self.index = 0

        def open(self, url: str, **_kwargs: object) -> VisitContext:
            calls.append(url)
            status = statuses[self.index]
            self.index += 1
            return VisitContext(_assessment(url, status))

    def capture(*, assessment: AccessAssessment, output_dir: Path, **_kwargs: object) -> dict:
        _write_valid_snapshot(output_dir, assessment.requested_url)
        return {}

    monkeypatch.setattr(browser_session, "BrowserSessionManager", Session)
    monkeypatch.setattr(access_module, "BDFutbolAccess", Access)
    monkeypatch.setattr(discovery, "capture_dom_snapshot", capture)
    monkeypatch.setattr(player_collector, "capture_dom_snapshot", capture)
    return calls


def test_plan_is_deterministic_tracks_inferred_urls_and_filtered_variants() -> None:
    candidates = [
        {"player_id": "j20", "profile_url": player_view_url("j20", "profile"), "team_season_ids": ["t2"]},
        {"player_id": "j3", "profile_url": player_view_url("j3", "profile"), "team_season_ids": ["t1"]},
    ]
    filtered_url = f"{player_view_url('j3', 'matches')}?temp=2026-27&pgep=pg"
    raw = {("j3", "matches"): [{
        "usable": True,
        "is_base_view_snapshot": False,
        "url": filtered_url,
        "snapshot_directory": "filtered",
    }]}

    first = build_player_acquisition_plan(candidates, raw, batch_size=1)
    second = build_player_acquisition_plan(candidates, raw, batch_size=1)

    assert first == second
    assert [item["player_id"] for item in first["players"]] == ["j3", "j20"]
    assert first["batches"] == [
        {"batch": 1, "player_ids": ["j3"]},
        {"batch": 2, "player_ids": ["j20"]},
    ]
    profile = next(item for item in first["views"] if item["player_id"] == "j3" and item["view"] == "profile")
    matches = next(item for item in first["views"] if item["player_id"] == "j3" and item["view"] == "matches")
    assert profile["url_status"] == "VERIFIED_FROM_ROSTER"
    assert matches["url_status"] == "INFERRED_FROM_OBSERVED_ROUTE_PATTERN"
    assert matches["pending"] is True
    assert matches["filtered_variant_count"] == 1
    assert matches["acquisition_status"] == "BASE_VIEW_PENDING_FILTERED_VARIANT_EXISTS"


def test_dry_run_reads_local_rosters_and_never_starts_browser_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from football_data_hub.core import browser_session

    sports = tmp_path / "sports"
    sports.mkdir()
    with gzip.open(sports / "rosters.json.gz", "wt", encoding="utf-8") as stream:
        json.dump({"items": [{
            "player_id": "j123",
            "player_url": player_view_url("j123", "profile"),
            "team_season_id": "t2026-271",
            "club_id": "e1",
            "position_raw": "4",
            "zero_appearances": False,
        }]}, stream)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("dry-run no debe crear navegador")

    monkeypatch.setattr(browser_session, "BrowserSessionManager", forbidden)
    report = dry_run(raw_root=tmp_path / "raw", club_sports=sports, batch_size=3, refresh=False)

    assert report["browser_started"] is False
    assert report["network_requested"] is False
    assert report["view_count"] == len(PLAYER_VIEWS)
    assert report["views_pending"] == len(PLAYER_VIEWS)
    assert all(item["coverage_status"] == "PENDING_CAPTURE" for item in report["views"])


def test_existing_valid_snapshot_is_reused_without_starting_browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from football_data_hub.core import browser_session

    raw_root = tmp_path / "raw"
    for view in PLAYER_VIEWS:
        snapshot = raw_root / "previous" / "j123" / view
        _write_valid_snapshot(snapshot, player_view_url("j123", view))

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("el reúso no debe iniciar navegador")

    monkeypatch.setattr(browser_session, "BrowserSessionManager", forbidden)
    records = capture_player_snapshots(
        player_ids=["j123"], raw_root=raw_root, profile_dir=tmp_path / "profile",
    )

    profile = next(row for row in records if row["view"] == "profile")
    assert profile["status"] == "REUSED_VALID"
    assert profile["snapshot_directory"] == "previous/j123/profile"
    assert not list(raw_root.glob("20*"))


def test_refresh_writes_a_new_immutable_snapshot_and_keeps_previous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw_root = tmp_path / "raw"
    url = player_view_url("j123", "profile")
    previous = raw_root / "previous" / "j123" / "profile"
    _write_valid_snapshot(previous, url)
    old_html = (previous / "rendered.html").read_bytes()
    _install_fake_browser(monkeypatch, [AccessStatus.VALID] * len(PLAYER_VIEWS))

    records = capture_player_snapshots(
        player_ids=["j123"], raw_root=raw_root, profile_dir=tmp_path / "profile", refresh=True,
    )

    profile = next(row for row in records if row["view"] == "profile")
    assert profile["status"] == "CAPTURED_VALID"
    assert profile["snapshot_directory"] != "previous/j123/profile"
    assert (previous / "rendered.html").read_bytes() == old_html
    assert (raw_root / profile["snapshot_directory"] / "rendered.html").is_file()


def test_invalid_snapshot_is_not_reused_and_is_marked_for_revalidation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw_root = tmp_path / "raw"
    url = player_view_url("j123", "profile")
    invalid = raw_root / "previous" / "j123" / "profile"
    _write_valid_snapshot(invalid, url)
    (invalid / "rendered.html").write_text("changed", encoding="utf-8")
    candidate = {
        "player_id": "j123", "profile_url": url, "team_season_ids": [],
    }
    plan = build_player_acquisition_plan([candidate], discover_player_snapshots(raw_root))
    profile = next(item for item in plan["views"] if item["view"] == "profile")
    assert profile["acquisition_status"] == "REVALIDATION_REQUIRED"
    assert profile["snapshot_available"] is False

    calls = _install_fake_browser(monkeypatch, [AccessStatus.VALID] * len(PLAYER_VIEWS))
    records = capture_player_snapshots(
        player_ids=["j123"], raw_root=raw_root, profile_dir=tmp_path / "profile",
    )
    assert calls
    assert next(row for row in records if row["view"] == "profile")["status"] == "CAPTURED_VALID"
    assert (invalid / "rendered.html").read_text(encoding="utf-8") == "changed"


def test_challenge_stops_immediately_and_persists_attempt_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw_root = tmp_path / "raw"
    calls = _install_fake_browser(monkeypatch, [AccessStatus.CHALLENGE_REQUIRED])

    with pytest.raises(PlayerAcquisitionStopped) as exc_info:
        capture_player_snapshots(
            player_ids=["j123"], raw_root=raw_root, profile_dir=tmp_path / "profile",
        )

    assert exc_info.value.status == "CHALLENGE_REQUIRED"
    assert calls == [player_view_url("j123", "profile")]
    state_files = list(raw_root.glob("*/acquisition_state.json"))
    assert len(state_files) == 1
    state = json.loads(state_files[0].read_text(encoding="utf-8"))
    assert state["records"][0]["status"] == "CHALLENGE_REQUIRED"


def test_interruption_retains_prior_views_and_next_run_resumes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw_root = tmp_path / "raw"
    calls = _install_fake_browser(monkeypatch, [AccessStatus.VALID, AccessStatus.CHALLENGE_REQUIRED])

    with pytest.raises(PlayerAcquisitionStopped) as exc_info:
        capture_player_snapshots(
            player_ids=["j123"], raw_root=raw_root, profile_dir=tmp_path / "profile",
        )

    assert calls == [player_view_url("j123", "profile"), player_view_url("j123", "statistics")]
    retained = exc_info.value.records[0]
    assert retained["status"] == "CAPTURED_VALID"
    assert (raw_root / retained["snapshot_directory"] / "rendered.html").is_file()
    _install_fake_browser(monkeypatch, [AccessStatus.VALID] * 3)

    resumed = capture_player_snapshots(
        player_ids=["j123"], raw_root=raw_root, profile_dir=tmp_path / "profile",
    )

    assert resumed[0]["view"] == "profile"
    assert resumed[0]["status"] == "REUSED_VALID"
    assert [row["status"] for row in resumed[1:]] == ["CAPTURED_VALID"] * 3
