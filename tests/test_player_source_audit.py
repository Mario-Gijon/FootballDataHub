from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from football_data_hub.parsers.player_source_audit import (
    audit_caceres_scope,
    audit_competition_exports,
)
from football_data_hub.providers.bdfutbol.competition import COMPETITION_URLS


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _write_competition_candidate(root: Path, key: str, status_version: int, minute: int) -> None:
    export_dir = root / f"snapshot-{key}-parser-1.0.0"
    metadata_sources = {}
    for group, suffix in (("I", "i"), ("II", "ii")):
        raw_dir = root / "raw" / key / suffix
        raw_dir.mkdir(parents=True)
        html = f"<html><body>{key}-{group}</body></html>"
        (raw_dir / "rendered.html").write_text(html, encoding="utf-8")
        sha = hashlib.sha256(html.encode()).hexdigest()
        captured = f"2026-10-08T12:{minute:02d}:00+00:00"
        raw_metadata = {
            "requested_url": COMPETITION_URLS[group],
            "final_url": COMPETITION_URLS[group],
            "captured_at_utc": captured,
            "access_status": "VALID",
            "http_status": 200,
            "rendered_html_sha256": sha,
        }
        _write_json(raw_dir / "metadata.json", raw_metadata)
        metadata_sources[group] = {
            "requested_url": raw_metadata["requested_url"],
            "final_url": raw_metadata["final_url"],
            "captured_at_utc": captured,
            "access_status": "VALID",
            "http_status": 200,
            "snapshot_sha256": sha,
            "path": raw_dir.as_posix(),
        }

    export_metadata = {
        "extraction_key": key,
        "parser_version": "1.0.0",
        "schema_version": "football_data_hub.competition_export.v1",
        "season": "2026/27",
        "source_snapshots": metadata_sources,
    }
    _write_json(export_dir / "dataset_metadata.json", export_metadata)
    for group, suffix in (("I", "i"), ("II", "ii")):
        rows = []
        for row_index in range(380):
            played = row_index == 0
            item = {
                "group": group,
                "round": row_index // 10 + 1,
                "date": "2026-08-28" if played else None,
                "date_raw": "28/08/2026" if played else None,
                "home_team_name": f"Home {group} {row_index}",
                "away_team_name": f"Away {group} {row_index}",
                "home_team_season_id": f"t{group}h{row_index}",
                "away_team_season_id": f"t{group}a{row_index}",
                "home_goals": 2 if played else None,
                "away_goals": 1 if played else None,
                "result_raw": "2 1" if played else "—",
                "match_url": f"https://www.bdfutbol.com/es/p/p.php?id={group}-1" if played else None,
                "match_link_status": "present" if played else "missing",
                "stadium_id": None,
                "stadium_name": None,
                "referee_id": None,
                "referee_name": None,
                "match_id": f"{group}-1" if played else None,
            }
            if status_version == 1:
                item["result_status"] = "played" if played else "scheduled"
            else:
                item["result_status"] = "available" if played else "not_available"
                item["fixture_status"] = "played" if played else "scheduled"
            rows.append(item)
        _write_json(export_dir / f"matches_group_{suffix}.json", {
            **export_metadata,
            "group": group,
            "items": rows,
        })


def test_competition_source_audit_normalizes_status_vocabulary_and_integrity(tmp_path: Path) -> None:
    _write_competition_candidate(tmp_path, "044edc9b2ef3c6026c7f", status_version=1, minute=10)
    _write_competition_candidate(tmp_path, "d047191aa847be5c30d7", status_version=2, minute=39)

    audit = audit_competition_exports(
        tmp_path,
        retained_extraction_key="044edc9b2ef3c6026c7f",
    )
    comparison = audit["cross_candidate_comparison"]
    assert audit["candidate_count"] == 2
    assert all(candidate["quality_valid"] for candidate in audit["candidates"])
    assert comparison["match_id_sets_equal"] is True
    assert comparison["core_field_difference_count"] == 0
    assert comparison["canonical_played_counts"] == [2, 2]
    assert comparison["right_result_status_vocabulary"] == {"available": 2, "not_available": 758}
    assert comparison["right_fixture_status_vocabulary"] == {"played": 2, "scheduled": 758}
    assert "número bruto" in audit["selection_reason"]


def _write_raw_snapshot(directory: Path, url: str, html: str, captured: str) -> None:
    directory.mkdir(parents=True)
    sha = hashlib.sha256(html.encode()).hexdigest()
    (directory / "rendered.html").write_text(html, encoding="utf-8")
    _write_json(directory / "metadata.json", {
        "requested_url": url,
        "final_url": url,
        "captured_at_utc": captured,
        "access_status": "VALID",
        "http_status": 200,
        "rendered_html_sha256": sha,
    })


def test_caceres_aggregate_scope_is_explained_by_copa_federacion_rows(tmp_path: Path) -> None:
    rows = []
    for index in range(6):
        rows.append(
            f'<tr><td>0{index + 1}/09/2026</td><td>Liga</td><td>Jornada {index + 1}</td>'
            f'<td>Home</td><td></td><td>1 0</td><td></td><td>Cacereño</td><td>Ground</td>'
            f'<td><a href="../p/p.php?id={100 + index}">1 0</a></td></tr>'
        )
    rows.extend([
        '<tr><td>09/09/2026</td><td>Copa Federación</td><td>Dieciseisavos</td><td>Cacereño</td><td></td><td>2 0</td><td></td><td>San Pedro</td><td>Ground</td><td><a href="../p/p.php?id=600">2 0</a></td></tr>',
        '<tr><td>16/09/2026</td><td>Copa Federación</td><td>Octavos</td><td>Recreativo</td><td></td><td>2 1</td><td></td><td>Cacereño</td><td>Ground</td><td><a href="../p/p.php?id=601">2 1</a></td></tr>',
    ])
    team_url = "https://www.bdfutbol.com/es/t/t2026-27149.html?tab=partits"
    club_url = "https://www.bdfutbol.com/es/p/e149.html"
    team_dir = tmp_path / "team_matches"
    club_dir = tmp_path / "club_matches"
    _write_raw_snapshot(team_dir, team_url,
                        '<table id="taula-resultats-plantilla"><tr><th>head</th></tr>' + "".join(rows) + "</table>",
                        "2026-10-08T15:54:00Z")
    _write_raw_snapshot(
        club_dir,
        club_url,
        "<html><title>Club matches</title><table id='t1'>"
        "<tr><th>Temporada</th><th>PJ</th><th>PG</th><th>PE</th><th>PP</th>"
        "<th>GF</th><th>GC</th></tr><tr><td>2026-27</td><td>8</td><td>4</td>"
        "<td>2</td><td>2</td><td>9</td><td>5</td></tr></table></html>",
        "2026-10-08T15:54:13Z",
    )
    coverage_path = tmp_path / "sports" / "coverage_by_club.json.gz"
    coverage_path.parent.mkdir()
    with gzip.open(coverage_path, "wt", encoding="utf-8") as stream:
        json.dump({"items": [{
            "club_id": "e149",
            "aggregate_expected": {"PJ": 8, "PG": 4, "PE": 2, "PP": 2, "GF": 9, "GC": 5},
            "competition_match_ids_observed": [str(value) for value in range(100, 106)],
        }]}, stream)

    audit = audit_caceres_scope(team_dir, club_dir, coverage_path)
    assert audit["status"] == "SCOPE_EXPLAINED_BY_TWO_COPA_FEDERACION_MATCHES"
    assert audit["team_match_table_rows_played_count"] == 8
    assert audit["league_rows_count"] == 6
    assert audit["cup_federation_rows_count"] == 2
    assert audit["raw_club_match_aggregate"]["PJ"] == "8"
    assert audit["raw_aggregate_matches_b2_export"] is True
    assert audit["league_match_ids_equal_to_b2_variant"] is True
    assert {row["match_id"] for row in audit["cup_federation_rows"]} == {"600", "601"}
