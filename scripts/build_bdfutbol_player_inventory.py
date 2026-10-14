#!/usr/bin/env python3
"""Build a verified player inventory from local team-profile captures only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from football_data_hub.providers.bdfutbol.teams.player_inventory import (
    PlayerInventoryError,
    build_player_inventory,
    write_inventory_atomic,
)


def _default_index() -> Path:
    return Path.home() / "FootballDataHub-data/published/team_profiles_2026-27.json"


def _default_output() -> Path:
    return Path.home() / "FootballDataHub-data/players/inventory-2026-27"


def _default_top_roots() -> dict[str, Path]:
    repository_root = Path(__file__).resolve().parents[1]
    roots = {
        "I": repository_root / "data/exports/bdfutbol/group1_top/20261010T202506.237287Z-c92b19fb",
        "II": repository_root / "data/exports/bdfutbol/group2_top/20261010T155145.195266Z-c5b031a6",
    }
    return {group: root for group, root in roots.items() if root.is_dir()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--published-index", type=Path, default=_default_index())
    parser.add_argument("--output-dir", type=Path, default=_default_output())
    parser.add_argument("--group1-top-root", type=Path)
    parser.add_argument("--group2-top-root", type=Path)
    parser.add_argument(
        "--without-top-enrichment",
        action="store_true",
        help="No usar los snapshots validados de Destacados para nacionalidad/códigos auxiliares.",
    )
    args = parser.parse_args()
    top_roots = {} if args.without_top_enrichment else _default_top_roots()
    if args.group1_top_root:
        top_roots["I"] = args.group1_top_root
    if args.group2_top_root:
        top_roots["II"] = args.group2_top_root
    try:
        players, memberships, report, manifest = build_player_inventory(
            args.published_index,
            top_roots=top_roots,
        )
        hashes = write_inventory_atomic(args.output_dir, players, memberships, report, manifest)
    except (PlayerInventoryError, OSError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir.expanduser().resolve()),
                "counts": report["counts"],
                "by_group": report["by_group"],
                "output_sha256": hashes,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
