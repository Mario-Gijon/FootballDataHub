from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
from bs4 import BeautifulSoup

from football_data_hub.core.browser_session import BrowserInfo, PageVisit
from football_data_hub.providers.bdfutbol.context import get_competition_context
from football_data_hub.providers.bdfutbol.teams import acquisition as team_acquisition
from football_data_hub.providers.bdfutbol.teams.acquisition import (
    TeamAcquisitionBundle,
    TeamAcquisitionStopped,
)
from football_data_hub.providers.bdfutbol.teams.catalog import load_team_catalog
from football_data_hub.providers.bdfutbol.teams.export import export_team_capture
from football_data_hub.providers.bdfutbol.teams.parser import (
    TeamProfileParseError,
    parse_team_profile_pages,
    resolve_team_view_urls,
)
from football_data_hub.providers.bdfutbol.teams.validation import (
    validate_team_catalogs,
    validate_team_profile,
)

ROOT = Path(__file__).resolve().parents[1]
GROUP_CATALOGS = {
    1: ROOT / "data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f/normalized/matches.json",
    2: ROOT / "data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json",
}
PROFILE_RUNS = {
    1: ROOT / "data/exports/bdfutbol/teams/2026-27/48/team01a-group1-48-source-evidence",
    2: ROOT / "data/exports/bdfutbol/teams/2026-27/49/team01a-group2-49-source-evidence",
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_pilot(group: int, team_id: int):
    context = get_competition_context(group=group)
    team_payload = _read_json(GROUP_CATALOGS[group])
    record = next(item for item in team_payload["teams"] if item["team_id"] == team_id)
    run = PROFILE_RUNS[group]
    capture = _read_json(run / "metadata/capture.json")
    views = {
        view: (run / "raw" / f"{view}.html").read_text(encoding="utf-8")
        for view in capture["requested_views"]
    }
    parsed = parse_team_profile_pages(
        views,
        team_catalog_record=record,
        competition_context=context,
    )
    validation = validate_team_profile(
        parsed,
        catalog_record=record,
        group_team_catalog=team_payload["teams"],
        known_matches=team_payload["matches"],
        requested_views=tuple(capture["requested_views"]),
    )
    return context, team_payload, record, run, capture, views, parsed, validation


@pytest.fixture(scope="module")
def jaen():
    return _load_pilot(2, 49)


@pytest.fixture(scope="module")
def racing():
    return _load_pilot(1, 48)


def test_catalogs_contain_40_distinct_source_team_ids():
    catalogs = {}
    for group, path in GROUP_CATALOGS.items():
        context = get_competition_context(group=group)
        teams, _, reference = load_team_catalog(path, competition=context)
        catalogs[group] = (teams, reference)
        assert len(teams) == 20
        assert len({item["team_id"] for item in teams}) == 20
    result = validate_team_catalogs(catalogs, season="2026-27")
    assert result["valid"] is True
    assert result["summary"]["teams_total"] == 40
    assert result["summary"]["unique_team_ids"] == 40
    assert result["team_ids_by_group"]["II"] == [17, 18, 39, 40, 49, 55, 61, 67, 79, 89, 94, 107, 119, 140, 176, 204, 227, 414, 482, 488]


def test_view_links_are_resolved_from_real_team_page(jaen):
    _, _, record, _, _, views, *_ = jaen
    urls = resolve_team_view_urls(views["alignment"], record["team_url"])
    assert urls["alignment"] == record["team_url"]
    assert urls["squad"].endswith("?t=plantilla")
    assert urls["statistics"].endswith("?t=lista")
    assert urls["follow"].endswith("?t=seg")
    assert urls["transfers"].endswith("?t=altas")
    assert urls["matches"].endswith("?tab=partits")


def test_jaen_normalizes_team_coach_squad_stats_and_references(jaen):
    context, payload, record, run, capture, _, parsed, validation = jaen
    assert parsed.identity.team_id == 49
    assert parsed.identity.name == record["name"]
    assert parsed.identity.team_url == record["team_url"]
    assert parsed.season.group == "II"
    assert parsed.season.season == "2026-27"
    assert len(parsed.season.coaches) == 1
    assert parsed.season.coaches[0].coach_id == 1835
    assert len(parsed.players) == len(parsed.memberships) == 25
    assert len(parsed.player_statistics) == 25
    assert len(parsed.player_match_minutes) == 150
    assert len(parsed.transfers) == 34
    assert all(item.player_id > 0 and item.player_display_name and item.player_profile_url for item in parsed.transfers)
    assert len(parsed.group_team_ids_from_profile) == 20
    assert len(parsed.team_match_ids_from_profile) == 6
    assert set(parsed.team_match_ids_from_profile) <= {str(item["match_id"]) for item in payload["matches"]}
    assert validation["valid"] is True
    assert capture["access_by_view"]["alignment"]["status"] == "VALID"
    assert capture["source_snapshots"]["alignment"]["http_status"] == 200
    assert (run / "raw/alignment.html").is_file()


def test_roster_groups_and_nulls_are_preserved(jaen):
    *_, parsed, _ = jaen
    group_counts = {label: sum(item.squad_group_label == label for item in parsed.memberships) for label in ("Titulares", "Suplentes")}
    assert group_counts == {"Titulares": 11, "Suplentes": 14}
    assert any(item.value is None and item.raw_value == "" for item in parsed.player_match_minutes)
    salvi = next(item for item in parsed.player_statistics if item.player_id == 19269)
    assert salvi.matches_played == 0
    assert salvi.minutes_played == 0
    assert salvi.goals == 0


def test_group1_pilot_uses_same_parser_and_catalog_identity(racing):
    context, payload, record, _, capture, _, parsed, validation = racing
    assert record["team_id"] == 48
    assert parsed.identity.name == "Racing de Ferrol"
    assert parsed.identity.team_url == "https://www.bdfutbol.com/es/t/t2026-2748.html"
    assert parsed.season.group == "I"
    assert len(parsed.players) == len(parsed.player_statistics) == 25
    assert len(parsed.season.coaches) == 1
    assert parsed.season.coaches[0].coach_id == 400293
    assert parsed.player_match_minutes == ()
    assert "follow" not in capture["requested_views"]
    assert validation["valid"] is True
    assert len(parsed.group_team_ids_from_profile) == len(payload["teams"]) == 20


def test_player_and_match_relationships_use_ids_not_names(jaen):
    _, payload, _, _, _, _, parsed, _ = jaen
    player_ids = {item.player_id for item in parsed.players}
    assert len(player_ids) == len(parsed.players)
    matches = {str(item["match_id"]) for item in payload["matches"]}
    assert set(parsed.team_match_ids_from_profile) <= matches
    top_path = ROOT / "data/exports/bdfutbol/group2_top/20261010T155145.195266Z-c5b031a6/normalized/players.json"
    top = _read_json(top_path)
    top_ids = {item["player_id"] for item in top["records"]}
    assert player_ids.intersection(top_ids)
    assert player_ids - top_ids  # Destacados is a partial list, not a roster authority.


def test_snapshot_metadata_and_sha256_are_reproducible(jaen, racing):
    for pilot in (jaen, racing):
        _, _, _, run, capture, _, _, _ = pilot
        metadata = _read_json(run / "metadata/capture.json")
        access = _read_json(run / "raw/access.json")
        assert metadata["team_id"] in {48, 49}
        assert metadata["group"] in {"I", "II"}
        assert set(metadata["requested_views"]) == set(metadata["source_snapshots"])
        assert access["views"] == metadata["access_by_view"]
        for view, evidence in metadata["source_snapshots"].items():
            html = (run / evidence["path"]).read_bytes()
            assert hashlib.sha256(html).hexdigest() == evidence["sha256"]
            assert evidence["access_status"] == "VALID"
        assert capture["extractor_version"]


def test_export_json_can_be_read_back_and_capture_is_create_only(racing, tmp_path):
    context, _, record, run, capture, views, parsed, validation = racing
    source_access = _read_json(run / "raw/access.json")
    bundle = TeamAcquisitionBundle(
        capture_id="test-team-profile-export",
        captured_at_utc=capture["captured_at_utc"],
        requested_views=tuple(capture["requested_views"]),
        raw_views=views,
        view_urls=capture["view_urls"],
        access_by_view=capture["access_by_view"],
        page_titles={view: row["title"] for view, row in capture["source_snapshots"].items()},
        browser=capture["browser"],
        team_catalog_reference=capture["related_team_catalog"],
        parsed=parsed,
        validation=validation,
        competition=context,
    )
    paths = export_team_capture(
        tmp_path,
        bundle,
        profile_dir=None,
        capture_timestamp_basis="offline source evidence",
    )
    payload = _read_json(paths["players"])
    assert payload["metadata"]["team_id"] == 48
    assert len(payload["records"]) == 25
    assert _read_json(paths["team_season"])["record"]["group"] == "I"
    assert _read_json(paths["raw_access"])["views"] == source_access["views"]
    assert paths["run_directory"].is_dir()
    players_before = paths["players"].read_bytes()
    with pytest.raises(FileExistsError):
        export_team_capture(
            tmp_path,
            bundle,
            profile_dir=None,
            capture_timestamp_basis="offline source evidence",
        )
    assert paths["players"].read_bytes() == players_before


def test_parser_rejects_wrong_catalog_identity_and_invalid_html(jaen):
    context, _, record, _, _, views, *_ = jaen
    wrong_record = {**record, "team_url": "https://www.bdfutbol.com/es/t/t2026-2748.html"}
    with pytest.raises(TeamProfileParseError, match="no coincide"):
        parse_team_profile_pages(views, team_catalog_record=wrong_record, competition_context=context)
    with pytest.raises(TeamProfileParseError, match="no contiene"):
        parse_team_profile_pages(
            {"alignment": "<html><title>challenge</title><body>Just a moment</body></html>"},
            team_catalog_record=record,
            competition_context=context,
        )


class _FakeDocument:
    def __init__(self, url: str, html: str, status: int = 200):
        self.url = url
        self._html = html
        self.response_status = status
        self._soup = BeautifulSoup(html, "html.parser")

    def title(self):
        return self._soup.title.get_text(" ", strip=True) if self._soup.title else ""

    def html(self):
        return self._html

    def text(self, selector: str):
        item = self._soup.select_one(selector)
        return item.get_text(" ", strip=True) if item else ""

    def exists(self, selector: str):
        return self._soup.select_one(selector) is not None

    def wait(self, milliseconds: int):
        return None

    def close(self):
        return None


class _FakeSession:
    def __init__(self, pages: dict[str, tuple[str, int]]):
        self.pages = pages
        self.opened_urls: list[str] = []
        self.info = BrowserInfo(
            backend="seleniumbase-pure-cdp",
            browser_name="Chromium",
            browser_executable="/usr/bin/chromium",
            browser_version="fixture",
            automation_version="fixture",
            display=":99",
            uses_xvfb=True,
            xvfb_external=True,
        )

    def open_page(self, url: str):
        self.opened_urls.append(url)
        html, status = self.pages[url]
        document = _FakeDocument(url, html, status)
        return PageVisit(document=document, requested_url=url, initial_response_status=status)


class _FakeSessionManager:
    def __init__(self, session: _FakeSession):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *_args):
        return None


def test_acquisition_orchestration_uses_pure_cdp_access_contract(jaen, monkeypatch, tmp_path):
    context, payload, record, _, _, views, _, _ = jaen
    urls = resolve_team_view_urls(views["alignment"], record["team_url"])
    pages = {urls[view]: (html, 200) for view, html in views.items()}
    fake_session = _FakeSession(pages)
    monkeypatch.setattr(
        team_acquisition,
        "BrowserSessionManager",
        lambda *_args, **_kwargs: _FakeSessionManager(fake_session),
    )
    result = team_acquisition.acquire_team_profile(
        team_catalog_record=record,
        team_catalog_reference={"path": "fixture", "sha256": "fixture"},
        group_team_catalog=payload["teams"],
        known_matches=payload["matches"],
        competition=context,
        profile_dir=tmp_path / "profile",
        requested_views=("alignment", "statistics"),
    )
    assert fake_session.opened_urls == [urls["alignment"], urls["statistics"]]
    assert result.parsed.identity.team_id == 49
    assert result.validation["valid"] is True
    assert result.browser["backend"] == "seleniumbase-pure-cdp"


def test_acquisition_stops_on_challenge_without_retry(jaen, monkeypatch, tmp_path):
    context, payload, record, _, _, _, _, _ = jaen
    challenge = '<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>'
    fake_session = _FakeSession({record["team_url"]: (challenge, 403)})
    monkeypatch.setattr(
        team_acquisition,
        "BrowserSessionManager",
        lambda *_args, **_kwargs: _FakeSessionManager(fake_session),
    )
    with pytest.raises(TeamAcquisitionStopped) as stopped:
        team_acquisition.acquire_team_profile(
            team_catalog_record=record,
            team_catalog_reference={"path": "fixture", "sha256": "fixture"},
            group_team_catalog=payload["teams"],
            known_matches=payload["matches"],
            competition=context,
            profile_dir=tmp_path / "profile",
            requested_views=("alignment", "statistics"),
        )
    assert str(stopped.value.assessment.status) == "CHALLENGE_REQUIRED"
    assert fake_session.opened_urls == [record["team_url"]]
