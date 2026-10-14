"""Reparse one saved player-capture run without opening a browser or network."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from football_data_hub.providers.bdfutbol.players.export import build_player_capture_export


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-id", required=True)
    parser.add_argument(
        "--capture-root",
        type=Path,
        default=Path(os.environ.get(
            "FDH_PLAYER_CAPTURE_ROOT",
            str(Path.home() / "FootballDataHub-data/players/player-captures"),
        )),
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path(os.environ.get(
            "FDH_PLAYER_INVENTORY",
            str(Path.home() / "FootballDataHub-data/players/inventory-2026-27/players.json"),
        )),
    )
    parser.add_argument("--derivation-id")
    args = parser.parse_args()
    result = build_player_capture_export(
        capture_dir=args.capture_root / args.capture_id,
        inventory_path=args.inventory,
        derivation_id=args.derivation_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
