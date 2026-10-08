from __future__ import annotations

import json
from pathlib import Path

from scripts import analyze_bdfutbol_team_full as audit


def test_resolve_latest_run(tmp_path: Path) -> None:
    base = (
        tmp_path
        / "data/raw/bdfutbol/team_full_2026-27_49"
    )
    (base / "20261001T000000.000000Z").mkdir(parents=True)
    newest = base / "20261007T000000.000000Z"
    newest.mkdir()

    assert audit.resolve_run_dir(
        project_root=tmp_path,
        season="2026-27",
        team_id=49,
        run_dir=None,
    ) == newest.resolve()


def test_prefer_valid_attempt(tmp_path: Path) -> None:
    resource = tmp_path / "season_roster"
    a1 = resource / "attempt_01"
    a2 = resource / "attempt_02"
    a1.mkdir(parents=True)
    a2.mkdir()

    (a1 / "metadata.json").write_text(
        json.dumps({"status": "VALID"}),
        encoding="utf-8",
    )
    (a2 / "metadata.json").write_text(
        json.dumps({"status": "INVALID_CONTENT"}),
        encoding="utf-8",
    )

    assert audit._resource_attempt_dir(resource) == a1


def test_table_inventory_extracts_headers_and_samples() -> None:
    tables = [
        {
            "index": 0,
            "rows": [
                {
                    "cells": [
                        {"tag": "th", "text": "PJ"},
                        {"tag": "th", "text": "G"},
                    ]
                },
                {
                    "cells": [
                        {"tag": "td", "text": "6"},
                        {"tag": "td", "text": "4"},
                    ]
                },
            ],
        }
    ]

    result = audit._table_inventory(
        tables,
        sample_rows=2,
    )

    assert result[0]["headers"] == ["PJ", "G"]
    assert result[0]["row_count"] == 2
    assert result[0]["sample_rows"] == [
        ["PJ", "G"],
        ["6", "4"],
    ]


def test_link_inventory_groups_query_signatures() -> None:
    result = audit._links_inventory(
        [
            "https://www.bdfutbol.com/es/t/t2026-2749.html?t=seg",
            "https://www.bdfutbol.com/es/t/t2026-2749.html?t=lista",
            "https://www.bdfutbol.com/es/t/t2026-2749.html?tab=partits",
        ],
        max_links=10,
    )

    signatures = {
        item["signature"]: item["count"]
        for item in result["signatures"]
    }

    assert signatures[
        "/es/t/t2026-2749.html?t"
    ] == 2
    assert signatures[
        "/es/t/t2026-2749.html?tab"
    ] == 1


def test_master_inventory_merges_fields_and_headers() -> None:
    resources = [
        {
            "status": "VALID",
            "headings": [{"text": "Jugadores"}],
            "tables": [{"headers": ["PJ", "G"]}],
            "field_hints": {
                "player_stats": ["pj", "g"],
            },
            "selects": [
                {
                    "name": "tipo",
                    "options": [
                        {"text": "Partidos"},
                        {"text": "Tarjetas"},
                    ],
                }
            ],
        },
        {
            "status": "VALID",
            "headings": [{"text": "Altas"}],
            "tables": [{"headers": ["Equipo origen"]}],
            "field_hints": {
                "transfers": ["altas", "equipo origen"],
            },
            "selects": [],
        },
    ]

    master = audit.build_master_inventory(resources)

    assert master["resource_count"] == 2
    assert master["valid_resources"] == 2
    assert master["field_hints"]["player_stats"] == ["g", "pj"]
    assert master["field_hints"]["transfers"] == [
        "altas",
        "equipo origen",
    ]
    assert master["select_options"]["tipo"] == [
        "Partidos",
        "Tarjetas",
    ]
