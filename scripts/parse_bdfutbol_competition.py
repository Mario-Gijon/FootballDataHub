#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from football_data_hub.bdfutbol import parse_competition
from football_data_hub.bdfutbol.acquisition import resolve_latest_valid_snapshot
from football_data_hub.bdfutbol.cli import _format_fixture, _print_standings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parsea offline una página de competición de BDFutbol."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--html", help="Ruta al page.html capturado.")
    source.add_argument(
        "--snapshot-name",
        help="Nombre del recurso raw cuya latest_valid se debe resolver.",
    )
    parser.add_argument("--url", required=True, help="URL original de la competición.")
    parser.add_argument("--expect-teams", type=int)
    parser.add_argument("--expect-fixtures", type=int)
    parser.add_argument(
        "--show-standings",
        action="store_true",
        help="Muestra la clasificación parseada y los team_id de BDFutbol.",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    if args.snapshot_name:
        project_root = Path(__file__).resolve().parents[1]
        html_path = resolve_latest_valid_snapshot(project_root, args.snapshot_name)
        print(f"Snapshot: {args.snapshot_name}")
        print(f"HTML:     {html_path}")
    else:
        html_path = Path(args.html)
    html = html_path.read_text(encoding="utf-8")
    snapshot = parse_competition(
        html,
        args.url,
        expected_team_count=args.expect_teams,
        expected_fixture_count=args.expect_fixtures,
    )

    played = sum(fixture.played for fixture in snapshot.fixtures)
    scheduled = len(snapshot.fixtures) - played

    print("=== BDFUTBOL COMPETITION PARSER ===")
    print(f"Competición:  {snapshot.context.competition_code}")
    print(f"Temporada:    {snapshot.context.season}")
    print(f"Grupo:        {snapshot.context.group}")
    print(f"Equipos:      {len(snapshot.standings)}")
    print(f"Partidos:     {len(snapshot.fixtures)}")
    print(f"Disputados:   {played}")
    print(f"Pendientes:   {scheduled}")

    if snapshot.warnings:
        print("\nWarnings:")
        for warning in snapshot.warnings:
            print(f"  - {warning}")

    if args.show_standings:
        _print_standings(snapshot.standings)

    if snapshot.fixtures:
        first = snapshot.fixtures[0]
        last = snapshot.fixtures[-1]
        print("\nPrimer partido:")
        print(f"  {_format_fixture(first)}")
        print("Último partido:")
        print(f"  {_format_fixture(last)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
