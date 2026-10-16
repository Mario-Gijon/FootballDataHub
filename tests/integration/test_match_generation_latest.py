from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from football_data_hub.providers.bdfutbol.classification.generation import (
    build_match_generation,
)

ENABLED = os.environ.get("FDH_MATCH_00_LATEST_INTEGRATION") == "1"
DATA_ROOT = Path(
    os.environ.get("FDH_MATCH_00_DATA_ROOT", "~/FootballDataHub-data")
).expanduser().resolve()
CAPTURES = {
    "I": DATA_ROOT
    / "team03d/classification/group1/20261014T105436.115041Z-ab4f4a09",
    "II": DATA_ROOT
    / "team03d/classification/group2/20261014T105457.351953Z-3bb27f9e",
}
CAPTURE_IDS = {
    "I": "20261014T105436.115041Z-ab4f4a09",
    "II": "20261014T105457.351953Z-3bb27f9e",
}


@pytest.mark.integration
@pytest.mark.skipif(
    not ENABLED,
    reason="set FDH_MATCH_00_LATEST_INTEGRATION=1 to use local Oct 14 snapshots",
)
def test_october_14_captures_rebuild_latest_match_generation_idempotently(
    tmp_path: Path,
) -> None:
    matches_paths = {
        group: capture / "normalized/matches.json"
        for group, capture in CAPTURES.items()
    }
    output_root = tmp_path / "match-generation"

    generation = build_match_generation(
        group_i_root=CAPTURES["I"],
        group_i_matches=matches_paths["I"],
        group_ii_root=CAPTURES["II"],
        group_ii_matches=matches_paths["II"],
        output_root=output_root,
        data_root=DATA_ROOT,
    )
    artifact_names = ("matches.json", "validation.json", "manifest.json")
    first_bytes = {name: (generation / name).read_bytes() for name in artifact_names}
    repeated = build_match_generation(
        group_i_root=CAPTURES["I"],
        group_i_matches=matches_paths["I"],
        group_ii_root=CAPTURES["II"],
        group_ii_matches=matches_paths["II"],
        output_root=output_root,
        data_root=DATA_ROOT,
    )
    assert repeated == generation
    assert first_bytes == {name: (generation / name).read_bytes() for name in artifact_names}

    dataset = json.loads(first_bytes["matches.json"])
    validation = json.loads(first_bytes["validation.json"])
    manifest = json.loads(first_bytes["manifest.json"])
    groups = dataset["groups"]
    teams = [team for group in groups.values() for team in group["teams"]]
    matches = [match for group in groups.values() for match in group["matches"]]

    assert len(teams) == 40
    assert len({team["team_id"] for team in teams}) == 40
    assert len(matches) == 760
    assert len({match["internal_id"] for match in matches}) == 760
    played = [match for match in matches if match["status"] == "played"]
    pending = [match for match in matches if match["status"] == "unplayed"]
    assert len(played) == 140
    assert len(pending) == 620
    assert all(match["home_goals"] is not None and match["away_goals"] is not None for match in played)
    assert all(match["home_goals"] is None and match["away_goals"] is None for match in pending)
    urls = [match["source_match_url"] for match in matches if match["source_match_url"]]
    assert len(urls) == 140
    assert len(set(urls)) == 140
    assert all(match["source_match_url"] is None for match in pending)
    assert validation["valid"] is True
    assert validation["totals"] == {
        "teams": 40,
        "matches": 760,
        "played": 140,
        "unplayed": 620,
        "incomplete": 0,
        "explicit_individual_urls": 140,
    }

    sources = {source["group"]: source for source in manifest["source_captures"]}
    assert set(sources) == {"I", "II"}
    for group, source in sources.items():
        capture_root = CAPTURES[group]
        assert source["capture_id"] == CAPTURE_IDS[group]
        assert source["http_status"] == 200
        assert source["requested_url"] == source["final_url"]
        for entry in source["files"].values():
            source_path = (DATA_ROOT / entry["path"]).resolve()
            assert source_path.is_relative_to(DATA_ROOT)
            actual = hashlib.sha256(source_path.read_bytes()).hexdigest()
            assert actual == entry["sha256"]
        assert source["files"]["source_html"]["path"].endswith("/raw/source.html")
        assert source["files"]["normalized_matches"]["path"].endswith(
            "/normalized/matches.json"
        )
        capture = json.loads((capture_root / "metadata/capture.json").read_text())
        assert capture["capture_id"] == source["capture_id"]

    for artifact_name in ("matches.json", "validation.json"):
        artifact = first_bytes[artifact_name]
        declared = manifest["artifacts"][artifact_name]
        assert hashlib.sha256(artifact).hexdigest() == declared["sha256"]
        assert len(artifact) == declared["bytes"]
