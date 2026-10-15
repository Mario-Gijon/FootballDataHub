from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.classification.generation import (
    build_match_generation,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GROUP_I_CAPTURE = (
    REPO_ROOT
    / "data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f"
)
GROUP_II_CAPTURE = (
    REPO_ROOT
    / "data/exports/bdfutbol/group2_classification/20261010T102656.252222Z-72f200ad"
)
GROUP_II_MATCHES = (
    REPO_ROOT
    / "data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json"
)


def _build(output_root: Path, *, group_i_root: Path = GROUP_I_CAPTURE) -> Path:
    return build_match_generation(
        group_i_root=group_i_root,
        group_i_matches=group_i_root / "normalized/matches.json",
        group_ii_root=GROUP_II_CAPTURE,
        group_ii_matches=GROUP_II_MATCHES,
        output_root=output_root,
        data_root=REPO_ROOT,
    )


def test_real_offline_captures_build_a_reproducible_760_match_generation(tmp_path):
    before = {
        path: path.read_bytes()
        for path in (
            GROUP_I_CAPTURE / "raw/source.html",
            GROUP_I_CAPTURE / "normalized/matches.json",
            GROUP_II_CAPTURE / "raw/source.html",
            GROUP_II_MATCHES,
        )
    }

    generation = _build(tmp_path / "matches")
    files = {name: (generation / name).read_bytes() for name in ("matches.json", "validation.json", "manifest.json")}
    repeated = _build(tmp_path / "matches")

    assert repeated == generation
    assert files == {name: (generation / name).read_bytes() for name in files}
    assert before == {path: path.read_bytes() for path in before}

    dataset = json.loads(files["matches.json"])
    validation = json.loads(files["validation.json"])
    assert dataset["metadata"]["season"] == "2026-27"
    assert len(dataset["groups"]["I"]["teams"]) == 20
    assert len(dataset["groups"]["II"]["teams"]) == 20
    assert len(dataset["groups"]["I"]["matches"]) == 380
    assert len(dataset["groups"]["II"]["matches"]) == 380
    assert validation["totals"] == {
        "teams": 40,
        "matches": 760,
        "played": 119,
        "unplayed": 641,
        "incomplete": 0,
        "explicit_individual_urls": 119,
    }
    assert validation["valid"] is True

    group_i_0_0 = next(
        match
        for match in dataset["groups"]["I"]["matches"]
        if match["status"] == "played"
        and match["home_goals"] == 0
        and match["away_goals"] == 0
    )
    assert group_i_0_0["source_match_id"]
    assert group_i_0_0["source_match_url"].endswith(
        f"id={group_i_0_0['source_match_id']}"
    )
    pending = next(
        match for match in dataset["groups"]["II"]["matches"] if match["status"] == "unplayed"
    )
    assert pending["home_goals"] is None and pending["away_goals"] is None
    assert pending["source_match_url"] is None


def test_source_snapshot_hash_failure_stops_before_creating_a_generation(tmp_path):
    copied_root = tmp_path / "tampered-group-i"
    shutil.copytree(GROUP_I_CAPTURE, copied_root)
    with (copied_root / "raw/source.html").open("ab") as source:
        source.write(b" ")
    output_root = tmp_path / "matches"

    with pytest.raises(ValueError, match="SHA-256"):
        _build(output_root, group_i_root=copied_root)

    assert not (output_root / "generations").exists()


def test_existing_generation_is_never_overwritten_when_its_contents_change(tmp_path):
    generation = _build(tmp_path / "matches")
    matches_path = generation / "matches.json"
    matches_path.write_text("tampered\n", encoding="utf-8")
    before = matches_path.read_bytes()

    with pytest.raises(FileExistsError, match="no se sobrescribe"):
        _build(tmp_path / "matches")

    assert matches_path.read_bytes() == before
