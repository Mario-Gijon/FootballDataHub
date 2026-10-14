"""Rebuild the offline, resumable progress index for player acquisitions."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from football_data_hub.providers.bdfutbol.players.catalog import build_player_acquisition_progress


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path(os.environ.get(
            "FDH_PLAYER_INVENTORY",
            str(Path.home() / "FootballDataHub-data/players/inventory-2026-27/players.json"),
        )),
    )
    parser.add_argument(
        "--capture-root",
        type=Path,
        default=Path(os.environ.get(
            "FDH_PLAYER_CAPTURE_ROOT",
            str(Path.home() / "FootballDataHub-data/players/player-captures"),
        )),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Destino opcional; por defecto se escribe bajo --capture-root.",
    )
    args = parser.parse_args(argv)
    output = args.output or args.capture_root / "acquisition-progress-2026-27.json"
    try:
        result = build_player_acquisition_progress(
            inventory_path=args.inventory,
            capture_root=args.capture_root,
            output_path=output,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "output_path": result.get("output_path"),
        "output_sha256": result.get("output_sha256"),
        "summary": result["summary"],
        "corrupt_manifests": result["corrupt_manifests"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
