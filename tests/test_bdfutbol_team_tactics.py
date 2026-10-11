"""Offline checks for the spatial markers embedded in saved team pages."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.teams.tactics import (
    TacticalLayoutError,
    extract_tactical_positions,
)

ROOT = Path(__file__).resolve().parents[1]
CAPTURES = {
    49: ROOT / "data/exports/bdfutbol/teams/2026-27/49/team01a-group2-49-source-evidence",
    48: ROOT / "data/exports/bdfutbol/teams/2026-27/48/20261011T123240.190812Z-8f307d1c",
}


def _read_records(capture_dir: Path, file_name: str) -> list[dict[str, object]]:
    document = json.loads((capture_dir / "normalized" / file_name).read_text(encoding="utf-8"))
    return document["records"]


def _snapshot(capture_dir: Path) -> str:
    path = capture_dir / "raw/alignment.html"
    if not path.exists():
        path = capture_dir / "raw/alignment.html.gz"
        return gzip.decompress(path.read_bytes()).decode("utf-8")
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("team_id", [49, 48])
def test_real_tactical_nodes_link_exactly_to_the_published_starters(team_id: int) -> None:
    capture_dir = CAPTURES[team_id]
    players = _read_records(capture_dir, "players.json")
    memberships = _read_records(capture_dir, "memberships.json")
    roster_ids = {int(record["player_id"]) for record in players}
    starter_ids = {
        int(record["player_id"])
        for record in memberships
        if record["squad_group_label"] == "Titulares"
    }

    positions = extract_tactical_positions(
        _snapshot(capture_dir),
        roster_player_ids=roster_ids,
        starter_player_ids=starter_ids,
    )

    assert len(positions) == 11
    assert {position.player_id for position in positions} == starter_ids
    assert len({position.player_id for position in positions}) == len(positions)
    assert all(0 <= position.horizontal <= 1 for position in positions)
    assert all(0 <= position.vertical <= 1 for position in positions)
    assert all(position.slot <= position.line_size for position in positions)
    assert positions[0].line == "goalkeeper"
    assert positions[0].source_dom_id == "d_por"
    assert [position.line for position in positions] == [
        "goalkeeper",
        *(["defense"] * (4 if team_id == 48 else 3)),
        *(["midfield"] * (2 if team_id == 48 else 4)),
        *(["attack"] * (4 if team_id == 48 else 3)),
    ]


def test_source_slot_data_can_render_partial_coverage_without_filling_empty_slots() -> None:
    html = """<div id="alineacio"><div id="tactica"><div id="js">
      <div id="d_por"><a href="../j/j101.html">Keeper</a></div>
      <div id="d_def13"><a href="../j/j102.html">Defender 1</a></div>
      <div id="d_def33"><a href="../j/j103.html">Defender 3</a></div>
    </div></div></div>"""

    positions = extract_tactical_positions(
        html,
        roster_player_ids={101, 102, 103},
        starter_player_ids={101, 102, 103},
    )

    assert [position.player_id for position in positions] == [101, 102, 103]
    assert [(position.slot, position.line_size) for position in positions[1:]] == [(1, 3), (3, 3)]
    assert positions[1].vertical < positions[2].vertical
    assert len(positions) == 3


@pytest.mark.parametrize(
    ("html", "roster_ids", "starter_ids"),
    [
        ("<div id='alineacio'></div>", {1}, {1}),
        ("<div id='alineacio'><div id='tactica'><div id='js'></div></div></div>", {1}, {1}),
        (
            "<div id='alineacio'><div id='tactica'><div id='js'>"
            "<div id='d_def13'><a href='../j/j1.html'>A</a></div>"
            "</div></div></div>",
            {1},
            set(),
        ),
        (
            "<div id='alineacio'><div id='tactica'><div id='js'>"
            "<div id='d_def41'><a href='../j/j1.html'>A</a></div>"
            "</div></div></div>",
            {1},
            {1},
        ),
    ],
)
def test_missing_or_unverifiable_positions_are_rejected_without_fabrication(
    html: str, roster_ids: set[int], starter_ids: set[int]
) -> None:
    with pytest.raises(TacticalLayoutError):
        extract_tactical_positions(
            html,
            roster_player_ids=roster_ids,
            starter_player_ids=starter_ids,
        )


def test_repeated_player_or_source_slot_is_rejected() -> None:
    html = """<div id="alineacio"><div id="tactica"><div id="js">
      <div id="d_def13"><a href="../j/j101.html">One</a></div>
      <div id="d_def13"><a href="../j/j102.html">Two</a></div>
    </div></div></div>"""

    with pytest.raises(TacticalLayoutError, match="duplicada"):
        extract_tactical_positions(
            html,
            roster_player_ids={101, 102},
            starter_player_ids={101, 102},
        )
