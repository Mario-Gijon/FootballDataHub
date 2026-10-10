from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from acquire_bdfutbol_competition import run_groups_sequentially
from football_data_hub.domain.classification.validation import validate_match_set
from football_data_hub.domain.classification.results import (
    build_results_matrix,
    list_competition_results,
)
from football_data_hub.providers.bdfutbol.classification.match_io import load_match_dataset
from football_data_hub.providers.bdfutbol.context import get_competition_context
from football_data_hub.providers.bdfutbol.referees.parser import (
    merge_referee_pages,
    parse_referee_page,
)
from football_data_hub.providers.bdfutbol.referees.validation import (
    build_match_reference_report,
    validate_referee_data,
)
from football_data_hub.providers.bdfutbol.statistics.parser import (
    parse_statistics_page,
    validate_statistics_page_html,
)
from football_data_hub.providers.bdfutbol.statistics.validation import (
    validate_statistics,
)
from football_data_hub.providers.bdfutbol.top.cli import _load_team_catalog
from football_data_hub.providers.bdfutbol.top.parser import parse_top_page
from football_data_hub.providers.bdfutbol.top.validation import validate_top_data

ROOT = Path(__file__).resolve().parents[1]
G1_CLASSIFICATION = ROOT / (
    "data/exports/bdfutbol/group1_classification/"
    "20261010T202500.293648Z-b770724f"
)
G1_TOP = ROOT / "data/exports/bdfutbol/group1_top/20261010T202506.237287Z-c92b19fb"
G1_STATISTICS = ROOT / (
    "data/exports/bdfutbol/group1_statistics/20261010T202515.613199Z-6c6e0fd9"
)
G2_MATCHES = ROOT / (
    "data/exports/bdfutbol/group2_classification/"
    "derived-clas01b-20261010T102656Z/normalized/matches.json"
)
REFEREES = ROOT / (
    "data/exports/bdfutbol/group2_referees/"
    "20261010T171227.617128Z-4cfe71bc"
)


def test_competition_context_resolves_both_supported_group_urls() -> None:
    group1 = get_competition_context("2026-27", 1)
    group2 = get_competition_context("2026-27", 2)

    assert group1.base_url == "https://www.bdfutbol.com/es/t/t2026-271rf1.html"
    assert group1.section_url("statistics").endswith("t2026-271rf1.html?tab=stats")
    assert group1.bdfutbol_code == "1rf1"
    assert group2.base_url == "https://www.bdfutbol.com/es/t/t2026-271rf2.html"
    assert group2.group_key == "group2"
    assert group1.export_directory(Path("exports"), "top") == Path(
        "exports/group1_top"
    )
    with pytest.raises(ValueError):
        get_competition_context("2025-26", 1)


def test_group1_results_are_complete_and_group_scoped() -> None:
    matches_path = G1_CLASSIFICATION / "normalized/matches.json"
    metadata, teams, matches = load_match_dataset(matches_path)
    group1_team_ids = {team.team_id for team in teams}

    assert metadata["group"] == "I"
    assert metadata["season"] == "2026-27"
    assert len(group1_team_ids) == 20
    assert len(matches) == 380
    assert sum(match.status == "played" for match in matches) == 60
    assert sum(match.status == "unplayed" for match in matches) == 320
    assert validate_match_set(
        teams, matches, expected_teams=20, expected_rounds=38, fixtures_per_round=10
    )["valid"]

    _, group2_teams, _ = load_match_dataset(G2_MATCHES)
    assert group1_team_ids.isdisjoint({team.team_id for team in group2_teams})
    assert len(list_competition_results(teams, matches)) == 380
    matrix = build_results_matrix(teams, matches)
    assert len(matrix.rows) == 20
    assert all(len(row.cells) == 20 for row in matrix.rows)


def test_top_catalog_rejects_matches_from_another_group() -> None:
    with pytest.raises(ValueError, match="se requiere Grupo I"):
        _load_team_catalog(G2_MATCHES, competition=get_competition_context(group=1))


def test_group1_top_preserves_source_variations_without_inventing_affiliation() -> None:
    _, teams, _ = load_match_dataset(G1_CLASSIFICATION / "normalized/matches.json")
    group1_team_ids = {team.team_id for team in teams}
    html = (G1_TOP / "raw/source.html").read_text(encoding="utf-8")
    parsed = parse_top_page(
        html,
        team_catalog=[asdict(team) for team in teams],
        base_url=get_competition_context(group=1).section_url("top"),
    )
    validation = validate_top_data(parsed)

    assert validation["valid"] is True
    assert validation["summary"]["categories"] == 6
    assert all(
        player.team_id is None or player.team_id in group1_team_ids
        for player in parsed.players
    )
    assert len(parsed.players) == 180
    assert len(parsed.rankings) == 149
    assert len(parsed.progress) == 129
    assert sum(len(series.points) for series in parsed.progress) == 774
    assert parsed.category_source_counts["goals"] == 99
    assert parsed.foreigners_summary.source_count == 60
    assert len(parsed.foreigners) == 59
    assert any("no se ha completado la fila ausente" in item for item in validation["warnings"])

    conflict, = parsed.affiliation_conflicts
    assert conflict.player_id == 304291
    assert [(item.team_id, item.team_name) for item in conflict.affiliations] == [
        (58, "Pontevedra"),
        (104, "Deportivo Fabril"),
    ]
    player = next(item for item in parsed.players if item.player_id == 304291)
    assert player.team_id is None
    assert player.team_name is None and player.crest_url is None
    metadata = json.loads((G1_TOP / "metadata/capture.json").read_text())
    classification_metadata = json.loads(
        (G1_CLASSIFICATION / "metadata/capture.json").read_text()
    )
    assert metadata["group"] == "I"
    assert metadata["related_team_catalog"]["group"] == "I"
    assert metadata["related_team_catalog"]["source_capture_id"] == classification_metadata[
        "capture_id"
    ]
    assert metadata["affiliation_conflicts"][0]["player_id"] == 304291


def test_group1_statistics_fixture_and_chart_are_semantically_valid() -> None:
    metadata_path = G1_STATISTICS / "metadata/capture.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    html = (G1_STATISTICS / "raw/source.html").read_text(encoding="utf-8")
    chart = json.loads(
        (G1_STATISTICS / "raw/chart_data_provider.json").read_text(encoding="utf-8")
    )
    context = get_competition_context(group=1)

    assert metadata["group"] == "I"
    assert validate_statistics_page_html(html, context) == ()
    parsed = parse_statistics_page(
        html,
        chart,
        source_url=context.section_url("statistics"),
        competition=context,
    )
    assert parsed.group == "I"
    assert parsed.source_summary.matches == 60
    assert parsed.source_summary.goals == 156
    assert parsed.exclusive_penalties.penalties_awarded == 16
    assert len(parsed.chart.points) == 38
    assert validate_statistics(parsed)["valid"] is True

    reconciliation = json.loads(
        (G1_STATISTICS / "validation/reconciliation.json").read_text(encoding="utf-8")
    )
    assert reconciliation["match_data_alignment"]["status"] == "identical"
    assert reconciliation["summary"]["metric_differences"] == 0
    assert reconciliation["match_dataset_capture_id"] == json.loads(
        (G1_CLASSIFICATION / "metadata/capture.json").read_text()
    )["capture_id"]


def test_shared_referee_capture_matches_group1_by_exact_ids() -> None:
    metadata = json.loads((REFEREES / "metadata/capture.json").read_text(encoding="utf-8"))
    pages = []
    for scope in ("all", "group1", "group2"):
        scope_capture = metadata["scope_captures"][scope]
        snapshot = REFEREES / scope_capture["file"]
        pages.append(
            parse_referee_page(
                snapshot.read_text(encoding="utf-8"),
                scope=scope,
                source_url=scope_capture["requested_url"],
            )
        )
    parsed = merge_referee_pages(tuple(pages))
    matches_path = G1_CLASSIFICATION / "normalized/matches.json"
    match_payload = json.loads(matches_path.read_text())
    report = build_match_reference_report(
        parsed,
        match_payload,
        reference_path="group1/matches.json",
        reference_sha256=hashlib.sha256(matches_path.read_bytes()).hexdigest(),
        group_scope="group1",
    )

    assert validate_referee_data(parsed)["valid"] is True
    assert parsed.scope_counts["group1"] == 43
    assert report["status"] == "consistent"
    assert report["counts"]["played_matches_with_referee_id"] == 60
    assert report["counts"]["matched_referee_ids"] == 43
    assert report["identity_conflicts"] == []
    assert report["statistic_differences"] == []


def test_orchestrator_runs_groups_in_order_and_keeps_them_independent() -> None:
    observed: list[str] = []

    def runner(context):
        observed.append(f"start-{context.group_number}")
        if context.group_number == 1:
            raise RuntimeError("fixture acquisition failure")
        observed.append(f"finish-{context.group_number}")
        return {"group": context.group_roman, "status": "complete"}

    results = run_groups_sequentially(
        (get_competition_context(group=1), get_competition_context(group=2)), runner
    )

    assert observed == ["start-1", "start-2", "finish-2"]
    assert [item["status"] for item in results] == ["error", "complete"]
