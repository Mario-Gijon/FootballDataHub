"""Offline checks using real captured pages and explicitly synthetic edge cases."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from football_data_hub.parsers.individual_entity_pages import (
    EntityPageError,
    load_valid_entity_snapshot,
    parse_entity_metadata_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_REAL_PAGE_URLS = {
    "match": "https://www.bdfutbol.com/es/p/p.php?id=269462",
    "coach": "https://www.bdfutbol.com/es/l/l1835.html",
    "referee": "https://www.bdfutbol.com/es/r/r602267.html",
    "stadium": "https://www.bdfutbol.com/es/s/81.html",
}


def _real_metadata_path(expected_url: str) -> Path:
    for path in (REPO_ROOT / "data/raw/bdfutbol").rglob("metadata.json"):
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if metadata.get("final_url") == expected_url:
            return path
    raise AssertionError(f"No se encontró la captura local requerida: {expected_url}")


def _synthetic_snapshot(
    tmp_path: Path,
    *,
    requested_url: str = _REAL_PAGE_URLS["coach"],
    final_url: str | None = None,
    http_status: int = 200,
    access_status: str = "VALID",
    html: str = (
        "<html><head><title>Entrenador | BDFutbol</title></head>"
        "<body><h1>Entrenador de prueba</h1>"
        "<table class='taula_estil traject'><tr><td>Temp</td></tr></table>"
        "</body></html>"
    ),
) -> Path:
    """Construct synthetic validation input; it is not a claimed BDFutbol sample."""
    snapshot_dir = tmp_path / "synthetic_snapshot"
    snapshot_dir.mkdir()
    html_bytes = html.encode("utf-8")
    (snapshot_dir / "rendered.html").write_bytes(html_bytes)
    metadata = {
        "requested_url": requested_url,
        "final_url": final_url or requested_url,
        "http_status": http_status,
        "access_status": access_status,
        "captured_at_utc": "2026-10-09T00:00:00+00:00",
        "rendered_html_bytes": len(html_bytes),
        "rendered_html_sha256": hashlib.sha256(html_bytes).hexdigest(),
    }
    metadata_path = snapshot_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    return metadata_path


@pytest.mark.parametrize("entity_type,url", _REAL_PAGE_URLS.items())
def test_real_captured_pages_validate_hash_identity_and_parse(entity_type: str, url: str) -> None:
    metadata_path = _real_metadata_path(url)
    snapshot = load_valid_entity_snapshot(metadata_path, REPO_ROOT)
    record = parse_entity_metadata_file(metadata_path, REPO_ROOT)

    assert snapshot.entity_type == entity_type
    assert record["entity_type"] == entity_type
    assert record["entity_id"] == {
        "match": "269462", "coach": "l1835", "referee": "602267", "stadium": "81",
    }[entity_type]
    assert snapshot.html_sha256 == snapshot.metadata["rendered_html_sha256"]
    assert record["source"]["access_status"] == "VALID"
    assert record["source"]["http_status"] == 200
    assert record["coverage"]["page_status"] == "CAPTURED_VALID"
    assert record["coverage"]["semantic_entity_completeness"] == "NOT_ASSERTED"
    assert record["coverage"]["full_html_retained_at_raw_path"].endswith("rendered.html")


def test_real_match_contract_preserves_title_tables_and_explicit_relationships() -> None:
    record = parse_entity_metadata_file(_real_metadata_path(_REAL_PAGE_URLS["match"]), REPO_ROOT)

    assert record["match_title_fields"] == {
        "home_team_name_raw": "Avilés Industrial",
        "away_team_name_raw": "Lugo",
        "home_goals": 1,
        "away_goals": 2,
        "date_raw": "02/10/2026",
        "date": "2026-10-02",
        "evidence": "BDFUTBOL_MATCH_TITLE_PATTERN",
    }
    assert len(record["tables"]) == 6
    assert record["coverage"]["table_row_count"] == 52
    assert record["coverage"]["table_cell_count"] == 278
    links = {
        (item["target_entity_type"], item["target_entity_id"])
        for item in record["related_entity_links"]
    }
    assert ("club", "81") in links
    assert ("club", "76") in links
    assert ("stadium", "81") in links
    assert ("referee", "602267") in links
    assert record["match_hero_fields_raw"][0]["label_raw"] == "Competición"
    assert len(record["match_hero_events_text_raw"]) == 1


def test_real_coach_and_referee_keep_source_trajectory_headers_and_json() -> None:
    coach = parse_entity_metadata_file(_real_metadata_path(_REAL_PAGE_URLS["coach"]), REPO_ROOT)
    referee = parse_entity_metadata_file(_real_metadata_path(_REAL_PAGE_URLS["referee"]), REPO_ROOT)

    coach_trajectory = next(item for item in coach["embedded_json"] if item["variable_name_raw"] == "trajectoria")
    referee_trajectory = next(item for item in referee["embedded_json"] if item["variable_name_raw"] == "trajectoria")
    assert len(coach_trajectory["values_raw"]) == 14
    assert len(referee_trajectory["values_raw"]) == 4
    assert coach["tables"][0]["headers_raw"][:3] == ["Temp", "Equipo", "País"]
    assert referee["tables"][0]["headers_raw"][:3] == ["Temp", "País", ""]
    assert any(cell["value_raw"] == "-" for table in coach["tables"] for row in table["rows"] for cell in row["cells"])
    assert any(cell["hidden_by_source_class"] for table in referee["tables"] for row in table["rows"] for cell in row["cells"])
    assert coach["coverage"]["interpretation_status"] == "PARTIAL_STRUCTURED_WITH_RAW_PRESERVATION"


def test_real_stadium_keeps_sections_chart_values_and_map_literals_raw() -> None:
    record = parse_entity_metadata_file(_real_metadata_path(_REAL_PAGE_URLS["stadium"]), REPO_ROOT)
    data_visit = next(item for item in record["embedded_json"] if item["variable_name_raw"] == "dataVisit")

    assert [section["heading_raw"] for section in record["page_sections"]] == [
        "Equipo Local", "Competiciones", "Top Visitantes", "Equipos Visitantes",
        "Temporadas", "Primer partido oficial", "Nombres", "Ubicación",
    ]
    assert len(data_visit["values_raw"]) == 15
    assert record["map_literals_raw"] == [{
        "center_coordinates_raw": "[43.557,-5.930]",
        "zoom_raw": "15",
        "marker_coordinates_raw": "[43.557,-5.930]",
        "popup_label_raw": "Suárez Puerta",
        "interpretation_status": "SOURCE_LITERALS_ONLY",
    }]


def test_real_snapshot_parse_is_deterministic() -> None:
    path = _real_metadata_path(_REAL_PAGE_URLS["coach"])
    assert parse_entity_metadata_file(path, REPO_ROOT) == parse_entity_metadata_file(path, REPO_ROOT)


def test_synthetic_profile_with_missing_sports_structure_is_rejected(tmp_path: Path) -> None:
    metadata_path = _synthetic_snapshot(
        tmp_path,
        html=(
            "<html><head><title>Entrenador | BDFutbol</title></head>"
            "<body><h1>Entrenador de prueba</h1><p>Contenido sin trayectoria.</p></body></html>"
        ),
    )

    with pytest.raises(EntityPageError, match="estructura deportiva"):
        load_valid_entity_snapshot(metadata_path, tmp_path)


def test_synthetic_wrong_final_identity_is_rejected(tmp_path: Path) -> None:
    metadata_path = _synthetic_snapshot(
        tmp_path,
        final_url="https://www.bdfutbol.com/es/l/l1836.html",
    )

    with pytest.raises(EntityPageError, match="tipo e ID solicitados"):
        load_valid_entity_snapshot(metadata_path, tmp_path)


def test_synthetic_http_403_challenge_is_not_valid_sports_content(tmp_path: Path) -> None:
    metadata_path = _synthetic_snapshot(
        tmp_path,
        http_status=403,
        access_status="BLOCKED",
        html="<html><title>Just a moment</title><body>challenge-platform</body></html>",
    )

    with pytest.raises(EntityPageError, match="estado de acceso no válido"):
        load_valid_entity_snapshot(metadata_path, tmp_path)


def test_synthetic_rendered_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    metadata_path = _synthetic_snapshot(tmp_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["rendered_html_sha256"] = "0" * 64
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(EntityPageError, match="SHA-256"):
        load_valid_entity_snapshot(metadata_path, tmp_path)


def test_versioned_export_reuses_identical_bytes_and_rejects_overwrite(tmp_path: Path) -> None:
    from parse_bdfutbol_entity_pages_offline import write_immutable_entity_exports

    records = {entity_type: [] for entity_type in ("match", "coach", "referee", "stadium")}
    first = write_immutable_entity_exports(
        records_by_type=records,
        coverage=[],
        errors=[],
        source_fingerprint="synthetic-source",
        output_root=tmp_path,
    )
    first_bytes = {path.name: path.read_bytes() for path in first.iterdir() if path.is_file()}
    second = write_immutable_entity_exports(
        records_by_type=records,
        coverage=[],
        errors=[],
        source_fingerprint="synthetic-source",
        output_root=tmp_path,
    )

    assert second == first
    assert {path.name: path.read_bytes() for path in second.iterdir() if path.is_file()} == first_bytes
    changed = {**records, "match": [{"entity_type": "match", "entity_id": "fixture-only"}]}
    with pytest.raises(FileExistsError, match="contenido distinto"):
        write_immutable_entity_exports(
            records_by_type=changed,
            coverage=[],
            errors=[],
            source_fingerprint="synthetic-source",
            output_root=tmp_path,
        )
