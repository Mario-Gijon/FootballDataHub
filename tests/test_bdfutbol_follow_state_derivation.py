from __future__ import annotations

from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import re

import pytest
from bs4 import BeautifulSoup

from football_data_hub.providers.bdfutbol.context import get_competition_context
from football_data_hub.providers.bdfutbol.teams.catalog import load_team_catalog
from football_data_hub.providers.bdfutbol.teams.follow_states import (
    FollowStateDerivationError,
    derive_follow_states,
)
from football_data_hub.providers.bdfutbol.teams.parser import parse_team_profile_pages
from football_data_hub.providers.bdfutbol.teams.validation import validate_team_profile


ROOT = Path(__file__).resolve().parents[1]
JAEN_CAPTURE = ROOT / "data/exports/bdfutbol/teams/2026-27/49/team01a-group2-49-source-evidence"
RACING_CAPTURE = ROOT / "data/exports/bdfutbol/teams/2026-27/48/20261011T123240.190812Z-8f307d1c"
GROUP2_CATALOG = ROOT / "data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json"


def _read_html(path: Path) -> str:
    raw = path.read_bytes()
    return gzip.decompress(raw).decode("utf-8") if path.suffix == ".gz" else raw.decode("utf-8")


def _matrix_signature(html: str) -> list[tuple[str, str, tuple[str, ...], str]]:
    soup = BeautifulSoup(html, "html.parser")
    signature = []
    for row in soup.select("#taula-seguiment tr")[1:]:
        player = row.select_one('a[href*="/j/j"]')
        assert player is not None
        player_id = re.search(r"/j/j(\d+)\.html", player["href"]).group(1)
        for cell in row.select("td")[1:]:
            wrapper = cell.select_one(".segdiv")
            match_link = cell.select_one('a[href*="p.php?id="]')
            assert wrapper is not None and match_link is not None
            match_id = re.search(r"p\.php\?id=(\d+)", match_link["href"]).group(1)
            classes = tuple(sorted(set(wrapper.get("class", [])) - {"segdiv"}))
            signature.append((player_id, match_id, classes, match_link.get_text(strip=True)))
    return signature


def test_jaen_embedded_matrices_reconstruct_all_follow_states_offline() -> None:
    capture = json.loads((JAEN_CAPTURE / "metadata/capture.json").read_text(encoding="utf-8"))
    source_html = _read_html(JAEN_CAPTURE / capture["source_snapshots"]["follow"]["path"])
    derived = derive_follow_states(source_html)

    assert derived.player_count == 25
    assert derived.matchdays == (1, 2, 3, 4, 5, 6)
    assert len(derived.match_ids) == 6
    assert derived.html_by_state.keys() == {"p", "t", "go", "tot"}
    assert derived.html_by_state["p"] == source_html
    assert derived.source_sha256 == capture["source_snapshots"]["follow"]["sha256"]

    context = get_competition_context(group=2)
    teams, matches, catalog_reference = load_team_catalog(GROUP2_CATALOG, competition=context)
    team = next(item for item in teams if int(item["team_id"]) == 49)
    views = {
        name: _read_html(JAEN_CAPTURE / evidence["path"])
        for name, evidence in capture["source_snapshots"].items()
    }
    parsed = parse_team_profile_pages(
        views,
        team_catalog_record=team,
        competition_context=context,
        follow_state_html=derived.html_by_state,
    )
    validation = validate_team_profile(
        parsed,
        catalog_record=team,
        group_team_catalog=teams,
        known_matches=matches,
        requested_views=tuple(capture["requested_views"]),
    )

    assert validation["valid"] is True
    assert parsed.follow_states_captured == ("go", "p", "t", "tot")
    assert len(parsed.players) == 25
    assert len(parsed.player_match_minutes) == 25 * 6
    assert len({(row.player_id, row.match_id) for row in parsed.player_match_minutes}) == 150
    assert all(row.match_id in {str(match["match_id"]) for match in matches} for row in parsed.player_match_minutes)
    assert all(row.team_id == 49 and row.group == "II" and row.season == "2026-27" for row in parsed.player_match_minutes)

    totals = Counter()
    by_player: dict[tuple[int, str], int] = defaultdict(int)
    for metric in parsed.player_match_metrics:
        totals[metric.metric] += metric.value
        by_player[(metric.player_id, metric.metric)] += metric.value
        assert metric.team_id == 49 and metric.group == "II" and metric.season == "2026-27"
        assert metric.match_id in {str(match["match_id"]) for match in matches}
        assert matches_by_id(matches)[metric.match_id]["matchday"] == metric.matchday

    stats = json.loads((JAEN_CAPTURE / "normalized/player_statistics.json").read_text(encoding="utf-8"))["records"]
    assert totals == {"yellow_cards": 15, "red_cards": 2, "goals": 8}
    for record in stats:
        assert by_player[(record["player_id"], "yellow_cards")] == record["yellow_cards"]
        assert by_player[(record["player_id"], "red_cards")] == record["red_cards"]
        assert by_player[(record["player_id"], "goals")] == record["goals"]
    assert any(row.raw_value == "tg1 tg2" and row.value == 2 for row in parsed.player_match_metrics)
    assert all(row.raw_value == "tv" and row.metric == "red_cards" for row in parsed.player_match_metrics if row.metric == "red_cards")
    assert any(row.value == 0 for row in parsed.player_match_minutes)
    assert all(row.source_state == ("go" if row.metric == "goals" else "t") for row in parsed.player_match_metrics)


def test_derivation_matches_captured_racing_dom_for_t_go_and_tot() -> None:
    source_html = _read_html(RACING_CAPTURE / "raw/follow.html.gz")
    derived = derive_follow_states(source_html)
    for state in ("t", "go", "tot"):
        captured_html = _read_html(RACING_CAPTURE / f"raw/follow_states/{state}.html.gz")
        assert _matrix_signature(derived.html_by_state[state]) == _matrix_signature(captured_html)


def test_derivation_rejects_mismatched_match_ids_in_the_visible_table() -> None:
    source_html = _read_html(JAEN_CAPTURE / "raw/follow.html")
    tampered = source_html.replace("p.php?id=272523", "p.php?id=999999", 1)
    with pytest.raises(FollowStateDerivationError, match="no coincide con el enlace de partido"):
        derive_follow_states(tampered)


def matches_by_id(matches: list[dict]) -> dict[str, dict]:
    return {str(match["match_id"]): match for match in matches}
