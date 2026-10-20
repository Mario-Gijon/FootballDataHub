from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from scripts.extract_bdfutbol_matches import main


REPO_ROOT = Path(__file__).resolve().parents[1]
CAPTURES = {
    "I": REPO_ROOT / "data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f",
    "II": REPO_ROOT / "data/exports/bdfutbol/group2_classification/20261010T102656.252222Z-72f200ad",
}


def test_two_group_normalizations_write_distinct_validation_reports_offline(
    tmp_path: Path, monkeypatch
) -> None:
    source_hashes = {
        group: hashlib.sha256((capture / "raw/source.html").read_bytes()).hexdigest()
        for group, capture in CAPTURES.items()
    }
    outputs: dict[str, Path] = {}
    validations: dict[str, Path] = {}

    for group, capture in CAPTURES.items():
        output = tmp_path / "normalized" / f"group-{group.lower()}" / "matches.json"
        validation_output = (
            tmp_path / "normalized" / "validation" / f"group-{group.lower()}-matches.json"
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "extract_bdfutbol_matches.py",
                "--snapshot", str(capture / "raw/source.html"),
                "--capture", str(capture / "metadata/capture.json"),
                "--output", str(output),
                "--validation-output", str(validation_output),
            ],
        )

        assert main() == 0
        outputs[group] = output
        validations[group] = validation_output

    assert outputs["I"] != outputs["II"]
    assert validations["I"].is_file() and validations["II"].is_file()
    assert json.loads(validations["I"].read_text(encoding="utf-8"))["valid"] is True
    assert json.loads(validations["II"].read_text(encoding="utf-8"))["valid"] is True
    for group, capture in CAPTURES.items():
        assert json.loads(outputs[group].read_text(encoding="utf-8"))["counts"]["matches"] == 380
        assert hashlib.sha256((capture / "raw/source.html").read_bytes()).hexdigest() == source_hashes[group]
