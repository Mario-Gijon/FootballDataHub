from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from football_data_hub.providers.bdfutbol.match_details.inventory import (
    VerifiedGeneration,
    build_match_detail_inventory,
)


def make_verified_generation(
    *, duplicate_source_id: bool = False, duplicate_across_groups: bool = False
) -> VerifiedGeneration:
    data_root = Path("/virtual/FootballDataHub-data")
    generation_id = "match-00-testgeneration"
    sources = []
    groups: dict[str, dict[str, Any]] = {}
    for group, base_team in (("I", 100), ("II", 200)):
        capture_id = f"capture-group-{group}"
        sources.append(
            {
                "group": group,
                "capture_id": capture_id,
                "captured_at_utc": "2026-10-14T10:00:00+00:00",
                "source_snapshot_sha256": group.lower() * 64,
                "files": {
                    "capture_metadata": {
                        "path": f"source/{group}/capture.json",
                        "sha256": "a" * 64,
                    },
                    "source_html": {
                        "path": f"source/{group}/source.html",
                        "sha256": group.lower() * 64,
                    },
                    "normalized_matches": {
                        "path": f"source/{group}/matches.json",
                        "sha256": "b" * 64,
                    },
                },
            }
        )
        matches = []
        for offset, status in ((0, "played"), (1, "unplayed")):
            source_id = str(269400 + offset if group == "I" else 272500 + offset)
            if duplicate_source_id and group == "I" and offset == 1:
                source_id = "269400"
                status = "played"
            if duplicate_across_groups and group == "II" and offset == 0:
                source_id = "269400"
            matches.append(
                {
                    "internal_id": (
                        f"pf-2026-27-group-{group.lower()}-bdfutbol-{source_id}"
                    ),
                    "source_match_id": source_id,
                    "status": status,
                    "source_match_url": (
                        f"https://www.bdfutbol.com/es/p/p.php?id={source_id}"
                        if status == "played"
                        else None
                    ),
                    "home_team_id": base_team,
                    "away_team_id": base_team + 1,
                    "matchday": 1,
                    "source_match_date": "2026-08-28",
                    "matchday_date": "2026-08-29",
                    "home_goals": 0 if status == "played" else None,
                    "away_goals": 0 if status == "played" else None,
                }
            )
        groups[group] = {
            "group": group,
            "teams": [{"team_id": base_team + index} for index in range(20)],
            "matches": matches,
        }
    manifest = {
        "source_captures": sources,
    }
    manifest_path = data_root / "matches/generations" / generation_id / "manifest.json"
    return VerifiedGeneration(
        generation_id=generation_id,
        manifest_path=manifest_path,
        manifest_sha256=hashlib.sha256(b"manifest").hexdigest(),
        matches_payload={
            "metadata": {"generation_id": generation_id},
            "groups": groups,
        },
        validation_payload={},
        manifest_payload=manifest,
        data_root=data_root,
    )


def make_inventory() -> dict[str, Any]:
    return build_match_detail_inventory(make_verified_generation())


def inventory_record(inventory: dict[str, Any], index: int = 0) -> dict[str, Any]:
    return inventory["matches"][index]
