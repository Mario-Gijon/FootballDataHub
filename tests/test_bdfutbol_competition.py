from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from football_data_hub.collectors.bdfutbol_competition import (
    InvalidCompetitionExport,
    InvalidCompetitionSnapshot,
    load_competition_export,
    load_competition_snapshot,
)
from football_data_hub.parsers.competition_coverage import build_competition_coverage
from football_data_hub.providers.bdfutbol.competition import (
    COMPETITION_URLS,
    parse_competition_html,
)
from football_data_hub.storage.competition_exports import write_competition_exports

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RAW_GROUP_ROOT = REPOSITORY_ROOT / "data/raw/bdfutbol/luna_audit/20261008T121024.595861Z"
GROUP_SNAPSHOT_NAMES = {"I": "competition_group_i", "II": "competition_group_ii"}


def competition_html(
    *,
    fixtures: str,
    headers: tuple[str, ...] = ("Pts.", "PJ", "PG", "PE", "PP", "GF", "GC", "TA", "TR"),
) -> str:
    header_cells = "".join(f"<td>{value}</td>" for value in ("", "", "", "", *headers))
    standings = []
    for position, name, team_id in (
        (1, "Local FC", "t2026-27101"),
        (2, "Visitante FC", "t2026-27102"),
    ):
        values = "".join(f"<td><a href=\"javascript:void(0)\">{value}</a></td>" for value in range(9))
        standings.append(
            f"<tr><td></td><td>{position}</td><td></td>"
            f"<td><a href=\"../t/{team_id}.html\">{name}</a></td>{values}</tr>"
        )
    return f"""<!doctype html>
    <html><head><title>Clasificación 1ª RFEF Grupo I 2026-27 | BDFutbol</title></head>
    <body>
      <table id="classific"><tr>{header_cells}</tr>{''.join(standings)}</table>
      <table class="taula_estil taula_estil-16">{fixtures}</table>
    </body></html>"""


def fixture_row(
    *,
    date: str = "12/09/2026",
    home: str = "Local FC",
    score: str = "—",
    away: str = "Visitante FC",
    match_id: str | None = None,
    stadium: str | None = None,
    referee: str | None = None,
) -> str:
    match_href = f"../p/p.php?id={match_id}" if match_id else None
    home_cell = f'<a href="{match_href}">{home}</a>' if match_href else home
    score_cell = f'<a href="{match_href}">{score}</a>' if match_href else score
    away_cell = f'<a href="{match_href}">{away}</a>' if match_href else away
    date_cell = f'<a href="{match_href}">{date}</a>' if match_href else date
    stadium_cell = f'<a href="{stadium}">Estadio</a>' if stadium else ""
    referee_cell = f'<a href="{referee}">Árbitro</a>' if referee else ""
    return (
        "<tr>"
        f"<td>{date_cell}</td><td>{home_cell}</td><td>{score_cell}</td>"
        f"<td>{away_cell}</td><td>{stadium_cell}</td><td>{referee_cell}</td>"
        "</tr>"
    )


def parse_fragment(rows: str, captured_at_utc: str | None = "2026-09-01T12:00:00+00:00") -> dict:
    html = competition_html(
        fixtures=(
            '<tr><td colspan="6">Jornada 1</td></tr>'
            '<tr><td>Fecha</td><td>Local</td><td></td><td>Visitante</td>'
            '<td>Estadio</td><td>Árbitro</td></tr>'
            f"{rows}"
        )
    )
    return parse_competition_html(
        html, COMPETITION_URLS["I"], captured_at_utc=captured_at_utc
    )


def load_real_snapshots() -> tuple[list[dict], dict, dict]:
    snapshots = {
        group: load_competition_snapshot(RAW_GROUP_ROOT / dirname, group)
        for group, dirname in GROUP_SNAPSHOT_NAMES.items()
    }
    parsed = [
        parse_competition_html(
            snapshots[group].html,
            COMPETITION_URLS[group],
            captured_at_utc=snapshots[group].metadata.get("captured_at_utc"),
        )
        for group in ("I", "II")
    ]
    metadata = {group: snapshots[group].metadata for group in ("I", "II")}
    return parsed, snapshots, metadata


def test_real_snapshots_cover_both_groups_and_full_fixture_tables() -> None:
    parsed, snapshots, metadata = load_real_snapshots()
    report = build_competition_coverage(parsed, metadata)

    assert [group["competition"]["group"] for group in parsed] == ["I", "II"]
    assert [len(group["standings"]) for group in parsed] == [20, 20]
    assert [len(group["matches"]) for group in parsed] == [380, 380]
    assert all(len({team["team_season_id"] for team in group["standings"]}) == 20 for group in parsed)
    assert all(Counter(match["round"] for match in group["matches"]) == Counter({n: 10 for n in range(1, 39)}) for group in parsed)
    assert all(snapshot.metadata["access_status"] == "VALID" for snapshot in snapshots.values())
    assert all(group["diagnostics"]["standings_headers_valid"] for group in parsed)
    logroñes = next(team for team in parsed[0]["standings"] if team["team_name"] == "UD Logroñés")
    assert logroñes["stats"] == {
        "points": 16,
        "played": 6,
        "wins": 5,
        "draws": 1,
        "losses": 0,
        "goals_for": 15,
        "goals_against": 7,
        "yellow_cards": 15,
        "red_cards": 2,
    }
    assert report["observed"]["matches_total"] == 760
    assert report["observed"]["teams_total"] == 40
    assert report["coverage_complete"] is True
    assert report["access_valid_for_all_groups"] is True
    assert report["season_outcomes_complete"] is False

    for group in parsed:
        matches = group["matches"]
        assert all(match["group"] == group["competition"]["group"] for match in matches)
        assert all(match["home_team_season_id"] for match in matches)
        assert all(match["away_team_season_id"] for match in matches)
        assert all(match["match_id"] is not None for match in matches if match["fixture_status"] == "played")
        assert all(match["match_id"] is None for match in matches if match["result_status"] == "not_available")
        assert all(match["home_goals"] is None and match["away_goals"] is None for match in matches if match["result_status"] == "not_available")
    group_ii_states = Counter(match["fixture_status"] for match in parsed[1]["matches"])
    assert group_ii_states["unresolved"] == 1


def test_hito1b_exports_are_quality_selected_and_each_has_119_played_matches() -> None:
    root = REPOSITORY_ROOT / "data/parsed/bdfutbol/primera_federacion_2026_27"
    expected_keys = ("044edc9b2ef3c6026c7f", "d047191aa847be5c30d7")
    if not all((root / f"snapshot-{key}-parser-1.0.0/dataset_metadata.json").is_file() for key in expected_keys):
        pytest.skip("Los exports locales reales de Hito 1B no están disponibles")

    selected_keys = []
    for extraction_key in expected_keys:
        export = load_competition_export(root, extraction_key=extraction_key)
        matches = export["matches"]
        selection = export["selection"]
        selected_keys.append(selection["selected_extraction_key"])
        assert len(matches) == 760
        assert sum(item["match_state"] == "played" for item in matches) == 119
        assert selection["fixtures_loaded"] == 760
        assert selection["normalized_state_counts"]["I"]["played"] + selection["normalized_state_counts"]["II"]["played"] == 119
        assert {item["_competition_extraction_key"] for item in matches} == {extraction_key}
        assert all(item["_captured_at_utc"] for item in matches)
        assert set(selection["groups"]) == {"I", "II"}

    automatic = load_competition_export(root)
    assert selected_keys == list(expected_keys)
    assert automatic["selection"]["selection_mode"] == "automatic_quality_then_recency"
    assert automatic["selection"]["selected_extraction_key"] == "d047191aa847be5c30d7"


def test_explicit_selection_rejects_an_incompatible_local_export(tmp_path: Path) -> None:
    export_dir = tmp_path / "snapshot-untrusted-parser-1.0.0"
    export_dir.mkdir()
    (export_dir / "dataset_metadata.json").write_text(json.dumps({
        "extraction_key": "untrusted",
        "schema_version": "unknown.schema",
        "parser_version": "1.0.0",
        "season": "2026/27",
    }), encoding="utf-8")

    automatic = load_competition_export(tmp_path)
    assert automatic["selection"]["selection_status"] == "NO_COMPATIBLE_EXPORT"
    assert "untrusted" in automatic["selection"]["rejected_candidates"]
    with pytest.raises(InvalidCompetitionExport, match="untrusted"):
        load_competition_export(tmp_path, extraction_key="untrusted")


def test_scheduled_fixture_preserves_missing_ids_and_optional_links() -> None:
    parsed = parse_fragment(fixture_row(date="—", stadium=None, referee=None))
    match = parsed["matches"][0]

    assert len(parsed["matches"]) == 1  # La cabecera de Jornada 1 no es un partido.
    assert match["round"] == 1
    assert match["date"] is None
    assert match["date_raw"] == "—"
    assert match["result_status"] == "not_available"
    assert match["fixture_status"] == "unresolved"
    assert match["result_raw"] == "—"
    assert match["home_goals"] is None and match["away_goals"] is None
    assert match["match_id"] is None and match["match_url"] is None
    assert match["match_link_status"] == "not_published_by_source"
    assert match["home_team_season_id"] == "t2026-27101"
    assert match["away_team_season_id"] == "t2026-27102"
    assert match["stadium_id"] is None and match["referee_id"] is None


def test_future_dated_fixture_is_scheduled_as_of_snapshot_capture() -> None:
    parsed = parse_fragment(fixture_row(date="12/09/2026"))
    match = parsed["matches"][0]

    assert match["fixture_status"] == "scheduled"
    assert match["result_status"] == "not_available"
    assert match["result_raw"] == "—"


def test_played_fixture_extracts_source_ids_and_score() -> None:
    parsed = parse_fragment(
        fixture_row(
            date="13/09/2026",
            score="2 1",
            match_id="98765",
            stadium="../s/81.html",
            referee="../r/r602065.html",
        ),
        captured_at_utc="2026-10-01T12:00:00+00:00",
    )
    match = parsed["matches"][0]

    assert match["result_status"] == "available"
    assert match["fixture_status"] == "played"
    assert (match["home_goals"], match["away_goals"]) == (2, 1)
    assert match["match_id"] == "98765"
    assert match["match_url"] == "https://www.bdfutbol.com/es/p/p.php?id=98765"
    assert match["stadium_id"] == "81"
    assert match["stadium_url"] == "https://www.bdfutbol.com/es/s/81.html"
    assert match["referee_id"] == "r602065"
    assert match["referee_url"] == "https://www.bdfutbol.com/es/r/r602065.html"


def test_unexpected_score_and_invalid_date_are_preserved_and_reported() -> None:
    parsed = parse_fragment(fixture_row(date="31/02/2027", score="pendiente"))
    match = parsed["matches"][0]
    issue_codes = {issue["code"] for issue in parsed["diagnostics"]["issues"]}

    assert match["date"] is None
    assert match["date_raw"] == "31/02/2027"
    assert match["result_status"] == "unknown"
    assert match["fixture_status"] == "inconsistent"
    assert match["result_raw"] == "pendiente"
    assert match["home_goals"] is None and match["away_goals"] is None
    assert "date_unparseable" in issue_codes
    assert "result_unexpected_value" in issue_codes


def test_pages_without_sporting_tables_produce_no_fake_records() -> None:
    parsed = parse_competition_html(
        '<html><title>Clasificación 1ª RFEF Grupo I 2026-27</title><body>Access denied</body></html>',
        COMPETITION_URLS["I"],
    )

    assert parsed["standings"] == []
    assert parsed["participants"] == []
    assert parsed["matches"] == []
    assert {issue["code"] for issue in parsed["diagnostics"]["issues"]} == {
        "standings_table_missing",
        "fixtures_table_missing",
    }


def test_duplicate_match_ids_are_reported_not_silently_removed() -> None:
    parsed, _, metadata = load_real_snapshots()
    duplicated = dict(parsed[0]["matches"][0])
    parsed[0]["matches"].append(duplicated)
    report = build_competition_coverage(parsed, metadata)
    group_i = next(group for group in report["groups"] if group["group"] == "I")

    assert len(parsed[0]["matches"]) == 381
    assert group_i["observed"]["duplicate_match_ids"] == {duplicated["match_id"]: 2}
    assert group_i["coverage_checks"]["match_ids_present_and_unique"] is False
    assert report["coverage_complete"] is False


def test_challenge_snapshot_is_rejected_before_parsing(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "challenge"
    snapshot_dir.mkdir()
    html = b"<html><title>Just a moment</title></html>"
    (snapshot_dir / "rendered.html").write_bytes(html)
    (snapshot_dir / "metadata.json").write_text(
        json.dumps({
            "access_status": "CHALLENGE_REQUIRED",
            "requested_url": COMPETITION_URLS["I"],
            "final_url": COMPETITION_URLS["I"],
            "http_status": 403,
            "rendered_html_sha256": hashlib.sha256(html).hexdigest(),
            "rendered_html_bytes": len(html),
        }),
        encoding="utf-8",
    )

    with pytest.raises(InvalidCompetitionSnapshot, match="no está validado como VALID"):
        load_competition_snapshot(snapshot_dir, "I")


def test_reprocessing_same_snapshots_reuses_output_without_appending_rows(tmp_path: Path) -> None:
    parsed, snapshots, metadata = load_real_snapshots()
    quality = build_competition_coverage(parsed, metadata)
    output_root = tmp_path / "parsed"
    first_dir = write_competition_exports(
        parsed_groups=parsed,
        snapshots_by_group=snapshots,
        quality=quality,
        output_root=output_root,
    )
    second_dir = write_competition_exports(
        parsed_groups=parsed,
        snapshots_by_group=snapshots,
        quality=quality,
        output_root=output_root,
    )

    assert first_dir == second_dir
    assert len(list(output_root.iterdir())) == 1
    for suffix in ("i", "ii"):
        json_rows = json.loads((first_dir / f"matches_group_{suffix}.json").read_text(encoding="utf-8"))["items"]
        with (first_dir / f"matches_group_{suffix}.csv").open(encoding="utf-8", newline="") as handle:
            csv_rows = list(csv.DictReader(handle))
        assert len(json_rows) == 380
        assert len(csv_rows) == 380
    assert len(json.loads((first_dir / "participants.json").read_text(encoding="utf-8"))["items"]) == 40
    assert json.loads((first_dir / "quality_coverage.json").read_text(encoding="utf-8"))["coverage_complete"] is True
