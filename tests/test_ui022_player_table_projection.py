"""Semantic projection tests for BDFutbol player tables."""

from __future__ import annotations

import pytest

from football_data_hub_api.player_dataset import (
    PlayerDatasetLoadError,
    _project_historical_match,
    _project_table,
)


def test_projection_uses_verified_marker_columns_and_grouped_headers() -> None:
    table = {
        "table_role": "career_trajectory",
        "columns": [
            {"header_original": "Temp", "source_index": 0},
            {"header_original": "", "classes_raw": ["colTrofeu"], "source_index": 1},
            {"header_original": "", "classes_raw": ["colComps"], "source_index": 2},
            {"header_original": "G", "group_header_raw": "Rival", "source_index": 3},
            {"header_original": "PJ", "header_title_raw": "Partidos", "source_index": 4},
        ],
        "records": [{
            "column_values": [["2025-26", None, None], ["Ascenso", None, None], ["Copa del Rey", None, None], [2, 2, None], [14, 14, None]],
        }],
    }

    projected = _project_table(table)

    assert [column.label for column in projected.columns] == [
        "Temporada", "Ascenso o descenso", "Otras competiciones", "Rival · G", "Partidos",
    ]
    assert [column.source_index for column in projected.columns] == [0, 1, 2, 3, 4]
    assert [cell.raw_value for cell in projected.rows[0].cells] == [
        "2025-26", "Ascenso", "Copa del Rey", 2, 14,
    ]


def test_projection_keeps_source_tooltip_as_display_heading() -> None:
    projected = _project_table({
        "table_role": "match_summary_by_season",
        "columns": [
            {"header_original": "PJ", "header_title_raw": "Partidos", "source_index": 0},
            {"header_original": "P%", "header_title_raw": None, "source_index": 1},
        ],
        "records": [],
    })

    assert [column.label for column in projected.columns] == ["Partidos", "P%"]


def test_statistics_matrix_first_column_is_named_by_its_row_values() -> None:
    projected = _project_table({
        "table_role": "statistics_by_competition",
        "columns": [{"header_original": "Tipo", "source_index": 0}],
        "records": [{"metric_label_raw": "Goles", "column_values": [["Goles", None, None]]}],
    })

    assert projected.columns[0].label == "Estadística"


def test_projection_rejects_an_uninterpreted_blank_column_instead_of_dropping_it() -> None:
    with pytest.raises(PlayerDatasetLoadError, match="sin significado verificado"):
        _project_table({
            "table_role": "career_trajectory",
            "columns": [{"header_original": "", "classes_raw": ["unrecognized-column"], "source_index": 7}],
            "records": [{"column_values": [["dato", None, None]]}],
        })


def test_projection_preserves_aligned_career_summary_row_metadata() -> None:
    projected = _project_table({
        "table_role": "career_totals",
        "columns": [
            {"header_original": label, "source_index": index}
            for index, label in enumerate(("Temp", "Equipo", "País", "Logro", "Div", "Edad", "PJ", "Min"))
        ],
        "records": [{
            "row_role": "total",
            "summary_label_raw": "Total",
            "summary_label_column_index": 4,
            "summary_label_span": 6,
            "column_values": [
                ["", None, "MISSING_OR_PLACEHOLDER"],
                ["", None, "MISSING_OR_PLACEHOLDER"],
                ["", None, "MISSING_OR_PLACEHOLDER"],
                ["", None, "MISSING_OR_PLACEHOLDER"],
                ["Total", None, "RAW_ONLY"],
                ["", None, "MISSING_OR_PLACEHOLDER"],
                ["100", 100, "INTEGER_NORMALIZED"],
                ["7846", 7846, "INTEGER_NORMALIZED"],
            ],
        }],
    })

    row = projected.rows[0]
    assert row.source_fields["summary_label_raw"] == "Total"
    assert row.source_fields["summary_label_span"] == 6
    assert [cell.raw_value for cell in row.cells][6:] == ["100", "7846"]


def test_rival_projection_adds_internal_player_link_only_when_id_url_and_inventory_agree() -> None:
    players = {
        23751: {"profile_url": "https://www.bdfutbol.com/es/j/j23751.html"},
    }
    projected = _project_table({
        "table_role": "opponent_player_statistics",
        "columns": [{"header_original": "Jugador", "source_index": 0}],
        "records": [
            {
                "rival_kind": "player", "rival_id": "j23751",
                "rival_url": "https://www.bdfutbol.com/es/j/j23751.html",
                "rival_name_raw": "Manu Pedreño", "column_values": [["Manu Pedreño", None, None]],
            },
            {
                "rival_kind": "player", "rival_id": "j23751",
                "rival_url": "https://www.bdfutbol.com/es/j/j99999.html",
                "rival_name_raw": "Contradictorio", "column_values": [["Contradictorio", None, None]],
            },
            {
                "rival_kind": "coach", "rival_id": "j23751",
                "rival_url": "https://www.bdfutbol.com/es/j/j23751.html",
                "rival_name_raw": "No es futbolista", "column_values": [["No es futbolista", None, None]],
            },
            {
                "rival_kind": "player", "rival_id": "j77777",
                "rival_url": "https://www.bdfutbol.com/es/j/j77777.html",
                "rival_name_raw": "No está inventariado", "column_values": [["No está inventariado", None, None]],
            },
        ],
    }, players)

    assert [row.internal_player_id for row in projected.rows] == [23751, None, None, None]


def test_historical_match_projection_preserves_only_positive_numeric_club_ids() -> None:
    projected = _project_historical_match({
        "match_id": "m-1", "home_club_id_raw": "49", "away_club_id_raw": "e48",
    })
    assert projected["home_team_id"] == 49
    assert projected["away_team_id"] is None
