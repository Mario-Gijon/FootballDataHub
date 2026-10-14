"""Build compact, cross-run player exports offline from verified snapshots."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from football_data_hub.providers.bdfutbol.players.catalog import build_player_acquisition_progress
from football_data_hub.providers.bdfutbol.players.compact_export import build_compact_player_generation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory", type=Path,
        default=Path(os.environ.get(
            "FDH_PLAYER_INVENTORY",
            str(Path.home() / "FootballDataHub-data/players/inventory-2026-27/players.json"),
        )),
    )
    parser.add_argument(
        "--capture-root", type=Path,
        default=Path(os.environ.get(
            "FDH_PLAYER_CAPTURE_ROOT",
            str(Path.home() / "FootballDataHub-data/players/player-captures"),
        )),
    )
    parser.add_argument(
        "--output-root", type=Path,
        default=Path(os.environ.get(
            "FDH_PLAYER_COMPACT_ROOT",
            str(Path.home() / "FootballDataHub-data/players/compact-2026-27"),
        )),
    )
    parser.add_argument("--player-id", type=int, action="append")
    parser.add_argument(
        "--complete-only", action="store_true",
        help="Publica únicamente jugadores con las cuatro vistas base verificadas.",
    )
    args = parser.parse_args(argv)
    try:
        progress = build_player_acquisition_progress(
            inventory_path=args.inventory,
            capture_root=args.capture_root,
        )
        result = build_compact_player_generation(
            inventory_path=args.inventory,
            capture_root=args.capture_root,
            output_root=args.output_root,
            player_ids=set(args.player_id) if args.player_id else None,
            complete_only=args.complete_only,
            progress_index=progress,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
