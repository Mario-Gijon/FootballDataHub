"""Semantic projection tests for BDFutbol player tables."""

from __future__ import annotations

import pytest

from football_data_hub_api.player_dataset import PlayerDatasetLoadError, _project_table


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
