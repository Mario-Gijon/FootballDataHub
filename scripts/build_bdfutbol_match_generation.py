"""Valida capturas locales y exporta una generación combinada de Grupo I y II."""

from __future__ import annotations

import argparse
from pathlib import Path

from football_data_hub.providers.bdfutbol.classification.generation import (
    build_match_generation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group-i-root", type=Path, required=True)
    parser.add_argument("--group-i-matches", type=Path, required=True)
    parser.add_argument("--group-ii-root", type=Path, required=True)
    parser.add_argument("--group-ii-matches", type=Path, required=True)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path.home() / "FootballDataHub-data",
        help="Raíz externa usada para hacer portables las rutas del manifiesto.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path.home() / "FootballDataHub-data" / "matches",
    )
    args = parser.parse_args()
    generation = build_match_generation(
        group_i_root=args.group_i_root.expanduser(),
        group_i_matches=args.group_i_matches.expanduser(),
        group_ii_root=args.group_ii_root.expanduser(),
        group_ii_matches=args.group_ii_matches.expanduser(),
        output_root=args.output_root.expanduser(),
        data_root=args.data_root.expanduser(),
    )
    print(generation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
