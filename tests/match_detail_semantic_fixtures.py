"""Small synthetic pages for offline semantic-parser unit tests only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

MATCH_ID = "272582"
MATCH_URL = f"https://www.bdfutbol.com/es/p/p.php?id={MATCH_ID}"
DISCOVERY_ID = "20261016T120000.000000Z-1234abcd"
INVENTORY_ID = "match-detail-inventory-1234567890abcdef"
GENERATION_ID = "match-00-test-generation"
SOURCE_CAPTURE_ID = "20261014T100000.000000Z-12345678"


def expected_match() -> dict[str, Any]:
    return {
        "internal_id": "pf-2026-27-group-ii-bdfutbol-272582",
        "source_match_id": MATCH_ID,
        "season": "2026-27",
        "competition": "Primera Federación",
        "group": "II",
        "matchday": 7,
        "home_team_id": 49,
        "away_team_id": 94,
        "source_match_date": "2026-10-10",
        "reference_result": {"home_goals": 1, "away_goals": 1},
        "source_match_url": MATCH_URL,
        "source_generation_id": GENERATION_ID,
        "source_capture_id": SOURCE_CAPTURE_ID,
    }


def _team_anchor(team_id: int, name: str, crest: str) -> str:
    return (
        f'<span class="col partit-equip"><a href="../e/e{team_id}.html">{name}</a>'
        f'<img src="../../i/eg/{crest}.png" alt=""></span>'
    )


def _score_header(*, mobile: bool = False) -> str:
    hidden = "d-block d-md-none" if mobile else "d-none d-md-block"
    return (
        f'<span class="{hidden}"><span class="row mt-3 mb-2">'
        f'{_team_anchor(49, "Jaén", "49p")}'
        '<span class="col-auto resultat-partit">1</span>'
        '<span class="col-auto resultat-partit">1</span>'
        f'{_team_anchor(94, "Villarreal B", "94")}'
        "</span></span>"
    )


def _metadata_field(label: str, value: str, href: str | None = None) -> str:
    content = f'<a href="{href}">{value}</a>' if href else value
    return (
        '<div class="text-left"><div class="f14">'
        f"{label}</div><div class=\"f13 font-weight-bold\">{content}</div></div>"
    )


def _metadata_row(mobile: bool = False) -> str:
    classes = "row pt-1 pb-2" + (" d-none d-md-block" if not mobile else " d-block d-md-none")
    return (
        f'<div class="{classes}">'
        + _metadata_field("Competición", "1ª RFEF", "../t/t2026-271rf2.html")
        + _metadata_field("Jornada", "Jornada 7", "../t/t2026-271rf2.html?tab=results&amp;jornada=7")
        + _metadata_field("Estadio", "La Victoria (Jaén)", "../s/100355.html")
        + _metadata_field("Fecha", "Sábado 10/10/2026 (18:45)")
        + "</div>"
    )


def _player_row(
    player_id: int,
    name: str,
    number: int,
    events: tuple[tuple[str, str, str], ...] = (),
) -> str:
    event_cells = [[], []]
    for icon, title, minute in events:
        cell_index = 0 if icon in {"Surt", "Entra"} else 1
        event_cells[cell_index].append(
            f'<div class="cosa"><div class="{icon}" title="{title}"></div>{minute}</div>'
        )
    return (
        "<tr>"
        f'<td class="shirt">{number}</td>'
        f'<td><img class="mini-foto-jugador" src="../../i/m/{player_id}.png" alt=""></td>'
        '<td><div class="pais espanya"></div></td>'
        f'<td><a href="../j/j{player_id}.html">{name}</a></td>'
        f"<td>{''.join(event_cells[0])}</td><td>{''.join(event_cells[1])}</td>"
        "</tr>"
    )


def _roster_table(
    rows: list[tuple[int, str, tuple[tuple[str, str, str], ...]]],
    *,
    starters: bool,
) -> str:
    hidden = '<tr style="display: none"><td></td></tr>'
    content = "".join(
        _player_row(player_id, name, index + 1, events)
        for index, (player_id, name, events) in enumerate(rows)
    )
    return f'<table class="taula_estil text-left"><tbody>{hidden}{content}</tbody></table>'


def _coach_table(coach_id: int, name: str) -> str:
    return (
        '<table class="taula_estil text-left"><tbody>'
        '<tr style="display: none"><td></td></tr>'
        f'<tr class="entren"><td><img class="mini-foto-jugador" src="../../i/lm/{coach_id}.png"></td>'
        f'<td><div class="pais espanya"></div></td><td><a href="../l/l{coach_id}.html">{name}</a></td><td></td></tr>'
        "</tbody></table>"
    )


def match_html(
    *,
    noise_tables: int = 0,
    include_substitutes: bool = True,
    include_coaches: bool = True,
    include_ephemeris: bool = True,
) -> bytes:
    """Build explicitly synthetic HTML; it contains no copied BDFutbol page."""

    home_starters = [
        (1001, "Home Scorer", (("GP", "Gol de Penalty", "90+1"),)),
        (1002, "Home Exit", (("Surt", "Sale", "66"), ("TG", "Tarjeta Amarilla", "45"))),
        (1003, "Home Exit Two", (("Surt", "Sale", "66"),)),
    ] + [(1000 + index, f"Home Player {index}", ()) for index in range(4, 12)]
    away_starters = [
        (2001, "Away Scorer", (("G", "Gol", "6"),)),
        (2002, "Away Exit", (("Surt", "Sale", "66"), ("TG", "Tarjeta Amarilla", "90+1"))),
    ] + [(2000 + index, f"Away Player {index}", ()) for index in range(3, 12)]
    home_subs = [
        (1101, "Home Substitute", (("Entra", "Entra", "66"),)),
        (1102, "Home Substitute Two", (("Entra", "Entra", "66"),)),
    ]
    away_subs = [(2101, "Away Substitute", (("Entra", "Entra", "66"),))]
    noisy = "".join("<table><tr><td>generic site table</td></tr></table>" for _ in range(noise_tables))
    competition_home = (
        '<div class="col-6 col-sm f14"><div class="text-right">'
        '<div class="text-blanc"><span>1-1</span> <a href="../j/j1001.html">Home Scorer</a> 90+1\' (pen)</div>'
        "</div></div>"
    )
    competition_away = (
        '<div class="col-6 col-sm f14"><div class="text-left">'
        '<div class="text-blanc"><span>0-1</span> <a href="../j/j2001.html">Away Scorer</a> 6\'</div>'
        "</div></div>"
    )
    event_row = (
        '<div class="row pt-1 pt-md-3 pb-2 text-center mb-0 mb-md-4">'
        + competition_home
        + '<div class="col-sm-auto font-blanc f13"><a href="../r/r601083.html">'
        '<img src="../../img/icons/whistle-white.png">Referee</a></div>'
        + competition_away
        + "</div>"
    )
    table_row = (
        '<div class="row pt-3 pb-2" style="overflow: auto">'
        '<div class="col-md-12 mb-3"></div>'
        f'<div class="col-6">{_roster_table(home_starters, starters=True)}</div>'
        f'<div class="col-6">{_roster_table(away_starters, starters=True)}</div>'
    )
    if include_substitutes:
        table_row += (
            '<div class="col-md-12"><h2>Suplentes</h2></div>'
            f'<div class="col-6">{_roster_table(home_subs, starters=False)}</div>'
            f'<div class="col-6">{_roster_table(away_subs, starters=False)}</div>'
        )
    if include_coaches:
        table_row += (
            '<div class="col-md-12"><h2>Entrenadores</h2></div>'
            f'<div class="col-6">{_coach_table(1835, "Manolo Herrero")}</div>'
            f'<div class="col-6">{_coach_table(510, "Albelda")}</div>'
        )
    table_row += "</div>"
    ephemeris = (
        '<div class="mt-2 mb-2"><h2>Efemérides</h2></div>'
        '<div class="pb-4"><div class="alert">Gol #1 de '
        '<a href="../j/j2001.html">Away Scorer</a> en 1ª RFEF</div></div>'
        if include_ephemeris
        else ""
    )
    document = (
        '<!doctype html><html><head><title>Jaén - Villarreal B (1 - 1) 10/10/2026 | BDFutbol</title>'
        f'<link rel="canonical" href="{MATCH_URL}"></head><body>{noisy}'
        '<div class="hero hero-partit">'
        + _metadata_row()
        + '<h1 class="m-0">'
        + _score_header()
        + _score_header(mobile=True)
        + "</h1>"
        + event_row
        + _metadata_row(mobile=True)
        + "</div>"
        + '<div class="container"><div class="row"><div>Histórico</div></div>'
        + table_row
        + "</div>"
        + ephemeris
        + '<form><input type="hidden" name="codi" value="272582"></form>'
        "</body></html>"
    )
    return document.encode()


def metadata_for(html: bytes) -> dict[str, Any]:
    return {
        "schema_version": "football_data_hub.match_detail_discovery_artifact.v1",
        "artifact_type": "discovery_only_unverified",
        "access_status": "INVALID_CONTENT",
        "captured_at_utc": "2026-10-16T16:39:42.935135Z",
        "competition": "Primera Federación",
        "discovery_id": DISCOVERY_ID,
        "discovery_sha256": "",
        "final_url": MATCH_URL,
        "group": "II",
        "http_status": 200,
        "internal_id": "pf-2026-27-group-ii-bdfutbol-272582",
        "inventory_id": INVENTORY_ID,
        "matchday": 7,
        "page_title": "Jaén - Villarreal B (1 - 1) 10/10/2026 | BDFutbol",
        "promotion_eligible": False,
        "requested_url": MATCH_URL,
        "season": "2026-27",
        "source_capture_id": SOURCE_CAPTURE_ID,
        "source_generation_id": GENERATION_ID,
        "source_html_bytes": len(html),
        "source_html_sha256": hashlib.sha256(html).hexdigest(),
        "source_match_id": MATCH_ID,
    }


def saved_artifact(root: Path, html: bytes | None = None) -> Path:
    raw_html = html if html is not None else match_html()
    artifact = root / DISCOVERY_ID
    (artifact / "raw").mkdir(parents=True)
    discovery = json.dumps({"semantic_mapping_confirmed": False}).encode()
    metadata = metadata_for(raw_html)
    metadata["discovery_sha256"] = hashlib.sha256(discovery).hexdigest()
    files = {
        "discovery.json": discovery,
        "metadata.json": json.dumps(metadata, sort_keys=True).encode() + b"\n",
        "raw/source.html": raw_html,
    }
    (artifact / "discovery.json").write_bytes(files["discovery.json"])
    (artifact / "metadata.json").write_bytes(files["metadata.json"])
    (artifact / "raw/source.html").write_bytes(files["raw/source.html"])
    manifest = {
        "schema_version": "football_data_hub.match_detail_discovery_manifest.v1",
        "artifact_type": "discovery_only_unverified",
        "discovery_id": DISCOVERY_ID,
        "inventory_id": INVENTORY_ID,
        "files": {
            name: {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            for name, content in files.items()
        },
    }
    (artifact / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    return artifact
