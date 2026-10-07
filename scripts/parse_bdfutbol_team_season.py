#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from football_data_hub.bdfutbol import parse_team_season
from football_data_hub.bdfutbol.acquisition import resolve_latest_valid_snapshot


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parsea offline una página de equipo/temporada de BDFutbol."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--html", help="Ruta al page.html capturado.")
    source.add_argument(
        "--snapshot-name",
        help="Nombre del recurso raw cuya latest_valid se debe resolver.",
    )
    parser.add_argument("--url", required=True, help="URL original del equipo/temporada.")
    parser.add_argument("--expect-team-id", type=int)
    parser.add_argument("--min-players", type=int)
    parser.add_argument("--show-squad", action="store_true")
    return parser.parse_args(argv)


def _value(value: object | None) -> str:
    return "-" if value is None else str(value)


def _print_squad(snapshot) -> None:
    print("\n=== PLANTILLA ===")
    print(
        f"{'#':>3}  {'Jugador':<24} {'player_id':>9} {'Bloque':<10} "
        f"{'Edad':>4} {'PJ':>3} {'PT':>3} {'PC':>3} {'PS':>3} "
        f"{'C':>3} {'Min':>5} {'TA':>3} {'TR':>3} {'G':>3}"
    )
    print("-" * 101)
    for member in snapshot.squad:
        print(
            f"{_value(member.squad_number):>3}  "
            f"{member.player_name:<24.24} "
            f"{member.player.provider_id:>9} "
            f"{member.squad_section:<10} "
            f"{_value(member.age):>4} "
            f"{_value(member.appearances):>3} "
            f"{_value(member.starts):>3} "
            f"{_value(member.complete_matches):>3} "
            f"{_value(member.substitute_appearances):>3} "
            f"{_value(member.unused_callups):>3} "
            f"{_value(member.minutes):>5} "
            f"{_value(member.yellow_cards):>3} "
            f"{_value(member.red_cards):>3} "
            f"{_value(member.goals):>3}"
        )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]

    if args.snapshot_name:
        html_path = resolve_latest_valid_snapshot(project_root, args.snapshot_name)
        print(f"Snapshot: {args.snapshot_name}")
        print(f"HTML:     {html_path}")
    else:
        html_path = Path(args.html)

    html = html_path.read_text(encoding="utf-8")
    snapshot = parse_team_season(
        html,
        args.url,
        expected_team_id=args.expect_team_id,
        min_squad_members=args.min_players,
    )

    starters = sum(member.squad_section == "starter" for member in snapshot.squad)
    substitutes = len(snapshot.squad) - starters

    print("=== BDFUTBOL TEAM/SEASON PARSER ===")
    print(f"Equipo:       {snapshot.context.team_name}")
    print(f"team_id:      {snapshot.context.team.provider_id}")
    print(f"Temporada:    {snapshot.context.season}")
    print(f"Competición:  {snapshot.context.competition_name or '-'}")
    print(f"Código:       {snapshot.context.competition_code or '-'}")
    print(f"Grupo:        {_value(snapshot.context.group)}")
    print(f"Partidos:     {_value(snapshot.context.matches_played)}")
    print(f"% victorias:  {_value(snapshot.context.win_percentage)}")
    print(f"Entrenadores: {len(snapshot.coaches)}")
    print(f"Jugadores:    {len(snapshot.squad)}")
    print(f"Titulares:    {starters}")
    print(f"Suplentes:    {substitutes}")

    if snapshot.coaches:
        print("\n=== ENTRENADOR ===")
        for coach in snapshot.coaches:
            print(
                f"{coach.coach_name} "
                f"(coach_id={coach.coach.provider_id}, "
                f"jornadas={coach.rounds or '-'}, "
                f"partidos={_value(coach.matches)})"
            )

    if snapshot.warnings:
        print("\nWarnings:")
        for warning in snapshot.warnings:
            print(f"  - {warning}")

    if args.show_squad:
        _print_squad(snapshot)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
