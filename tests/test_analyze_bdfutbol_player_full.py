from __future__ import annotations

import json
from pathlib import Path

from scripts import analyze_bdfutbol_player_full as analyzer


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_resolve_run_chooses_latest_directory(tmp_path: Path) -> None:
    base = (
        tmp_path
        / "data/raw/bdfutbol/player_full_209629"
    )
    (base / "20260101T000000Z").mkdir(parents=True)
    latest = base / "20260102T000000Z"
    latest.mkdir()

    resolved = analyzer._resolve_run(
        project_root=tmp_path,
        player_id=209629,
        requested=None,
    )

    assert resolved == latest.resolve()


def test_select_attempt_prefers_latest_valid(tmp_path: Path) -> None:
    resource = tmp_path / "player_profile"

    a1 = resource / "attempt_01"
    a2 = resource / "attempt_02"
    a3 = resource / "attempt_03"

    _write_json(a1 / "metadata.json", {"status": "VALID"})
    _write_json(a2 / "metadata.json", {"status": "INVALID_CONTENT"})
    _write_json(a3 / "metadata.json", {"status": "VALID"})

    assert analyzer._select_attempt(resource) == a3


def test_navigation_table_is_not_semantic() -> None:
    table = {
        "class_name": "d-none d-md-block fons-blau-2 p-2",
        "headers": [],
        "row_count": 10,
        "max_columns": 10,
    }

    assert analyzer._is_semantic_table(table) is False


def test_stats_table_is_semantic() -> None:
    table = {
        "class_name": "sortable",
        "headers": ["TEMPORADA", "EQUIPO", "PJ", "MIN", "G"],
        "row_count": 15,
        "max_columns": 5,
    }

    assert analyzer._is_semantic_table(table) is True


def test_related_entities_extracts_ids() -> None:
    result = analyzer._related_entities(
        "https://www.bdfutbol.com/es/j/j209629.html",
        [
            "https://www.bdfutbol.com/es/e/e49.html",
            "/es/e/e18.html",
            "/es/s/100355.html",
            "/es/j/j209629.html",
        ],
    )

    assert result["team"]["ids"] == [18, 49]
    assert result["stadium"]["ids"] == [100355]
    assert result["player"]["ids"] == [209629]


def test_field_hints_detect_identity_and_matches() -> None:
    result = analyzer._field_hints(
        "Nombre completo Fecha de nacimiento Demarcación "
        "Partido Rival Resultado Ganados Empatados Perdidos"
    )

    assert "nombre completo" in result["identity"]
    assert "rival" in result["matches"]


def test_analyze_resource_reads_gallery(tmp_path: Path) -> None:
    resource = tmp_path / "player_profile"
    attempt = resource / "attempt_01"

    _write_json(
        attempt / "metadata.json",
        {
            "status": "VALID",
            "provenance": "bdfutbol",
            "requested_url": "https://www.bdfutbol.com/es/j/j1.html",
            "final_url": "https://www.bdfutbol.com/es/j/j1.html",
            "http_status_diagnostic": 200,
        },
    )
    _write_json(attempt / "assessment.json", {"accessible": True})
    _write_json(
        attempt / "tables.json",
        [
            {
                "index": 1,
                "id": "stats",
                "class_name": "sortable",
                "row_count": 2,
                "nonempty_row_count": 2,
                "max_columns": 3,
                "headers": ["TEMPORADA", "EQUIPO", "PJ"],
                "sample_rows": [
                    ["2026-27", "Jaén", "6"],
                    ["2025-26", "X", "30"],
                ],
            }
        ],
    )
    _write_json(attempt / "selects.json", [])
    _write_json(attempt / "forms.json", [])
    _write_json(
        attempt / "links.json",
        ["https://www.bdfutbol.com/es/e/e49.html"],
    )
    _write_json(attempt / "images.json", [{"src": "x"}])
    _write_json(
        attempt / "same_player_links.json",
        ["https://www.bdfutbol.com/es/j/j1.html"],
    )
    _write_json(
        attempt / "photo_gallery.json",
        {
            "declared_count": 2,
            "control_found": True,
            "status": "VALID",
        },
    )
    _write_json(
        attempt / "photo_gallery/images.json",
        [{"src": "a"}, {"src": "b"}],
    )
    _write_json(attempt / "photo_gallery/links.json", [])
    _write_json(attempt / "photo_gallery/tables.json", [])

    (attempt / "page.html").write_text(
        """
        <html>
          <head><title>Jugador Uno | BDFutbol</title></head>
          <body>
            <h1>Jugador Uno</h1>
            <h2>Trayectoria</h2>
            <div><strong>Nombre completo</strong> Test</div>
            <div><strong>Fecha de nacimiento</strong> 01/01/2000</div>
            <div><strong>Demarcación</strong> Defensa</div>
            <table id="stats">
              <tr><th>TEMPORADA</th><th>EQUIPO</th><th>PJ</th></tr>
              <tr>
                <td>2026-27</td>
                <td><a href="/es/e/e49.html">Jaén</a></td>
                <td>6</td>
              </tr>
              <tr><td>2025-26</td><td>X</td><td>30</td></tr>
            </table>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    result = analyzer.analyze_resource(
        resource,
        sample_rows=1,
    )

    assert result["status"] == "VALID"
    assert result["title"] == "Jugador Uno | BDFutbol"
    assert result["semantic_tables"][0]["headers"] == [
        "TEMPORADA", "EQUIPO", "PJ"
    ]
    assert result["semantic_tables"][0]["row_count"] == 3
    assert result["semantic_tables"][0]["sample_rows"] == [
        ["2026-27", "Jaén", "6"]
    ]
    assert result["photo_gallery"]["declared_count"] == 2
    assert result["photo_gallery_analysis"]["images_count"] == 2
    assert result["related_entities"]["team"]["ids"] == [49]


def test_master_inventory_merges_headers_and_links() -> None:
    resources = [
        {
            "status": "VALID",
            "headings": [{"text": "Trayectoria"}],
            "semantic_tables": [{"headers": ["PJ", "G"]}],
            "field_hints": {"stats": ["pj", "g"]},
            "same_player_links": ["https://x/a"],
            "related_entities": {
                "team": {"ids": [49, 18]}
            },
            "photo_gallery": {
                "declared_count": 0,
                "status": "EMPTY",
            },
            "resource": "player_profile",
        },
        {
            "status": "VALID",
            "headings": [{"text": "Trayectoria"}],
            "semantic_tables": [{"headers": ["PJ", "MIN"]}],
            "field_hints": {"stats": ["pj", "min"]},
            "same_player_links": ["https://x/a", "https://x/b"],
            "related_entities": {
                "team": {"ids": [49]}
            },
            "photo_gallery": None,
            "resource": "player_stats",
        },
    ]

    master = analyzer._master_inventory(resources)

    assert master["valid_resources"] == 2
    assert master["same_player_links"] == [
        "https://x/a",
        "https://x/b",
    ]
    assert master["related_entity_ids"]["team"] == [18, 49]
    assert master["unique_headings"][0] == {
        "text": "Trayectoria",
        "resource_count": 2,
    }


def test_dom_table_extracts_header_metadata_and_links() -> None:
    html = """
    <html><body>
      <h2>Trayectoria</h2>
      <table id="career">
        <tr>
          <th title="Partidos jugados">PJ</th>
          <th>EQUIPO</th>
        </tr>
        <tr>
          <td data-title="PJ">6</td>
          <td><a href="/es/e/e49.html">Jaén</a></td>
        </tr>
      </table>
    </body></html>
    """

    tables = analyzer._extract_dom_tables(
        html,
        base_url="https://www.bdfutbol.com/es/j/j209629.html",
        sample_rows=5,
    )

    assert len(tables) == 1
    table = tables[0]
    assert table["headers"] == ["PJ", "EQUIPO"]
    assert table["header_cells"][0]["title"] == "Partidos jugados"
    assert table["sample_rows"] == [["6", "Jaén"]]
    assert table["sample_rows_meta"][0][1]["links"][0]["href"] == (
        "https://www.bdfutbol.com/es/e/e49.html"
    )
    assert table["nearby_heading"] == "Trayectoria"


def test_identity_contexts_preserve_context_without_guessing() -> None:
    html = """
    <div class="field">
      <span>Nombre completo</span>
      <span>Jaime Morillas Giménez</span>
    </div>
    """

    contexts = analyzer._identity_contexts(html)

    assert contexts
    assert contexts[0]["label"] == "Nombre completo"
    assert "Jaime Morillas Giménez" in contexts[0]["context"]


def test_manager_comparison_detects_extra_seasons() -> None:
    canonical = {
        "resource": "player_matches",
        "body_text_chars": 100,
        "images_count": 10,
        "semantic_tables": [],
        "selects": [
            {
                "index": 5,
                "id": "temp",
                "all_options": [
                    "Todas", "2026-27", "2025-26", "2024-25"
                ],
            }
        ],
    }
    manager = {
        "resource": "player_matches_manager",
        "body_text_chars": 110,
        "images_count": 10,
        "semantic_tables": [],
        "selects": [
            {
                "index": 5,
                "id": "temp",
                "all_options": [
                    "Todas",
                    "2026-27",
                    "2025-26",
                    "2024-25",
                    "2023-24",
                    "2022-23",
                ],
            }
        ],
    }

    comparison = analyzer._compare_resource_pair(
        canonical,
        manager,
    )

    assert comparison is not None
    diff = comparison["select_differences"][0]
    assert diff["select"] == "id:temp"
    assert diff["only_manager"] == ["2023-24", "2022-23"]
