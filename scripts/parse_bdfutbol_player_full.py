#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from football_data_hub.bdfutbol.player import parse_player_full_run


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parsea un player_full raw de BDFutbol.")
    parser.add_argument("--player-id", required=True, type=int)
    parser.add_argument("--run")
    parser.add_argument("--output")
    return parser.parse_args(argv)


def _resolve_run(*, project_root: Path, player_id: int, requested: str | None) -> Path:
    if requested:
        path = Path(requested)
        if not path.is_absolute():
            path = project_root / path
        if not path.is_dir():
            raise FileNotFoundError(path)
        return path.resolve()

    base = project_root / "data" / "raw" / "bdfutbol" / f"player_full_{player_id}"
    if not base.is_dir():
        raise FileNotFoundError(base)
    runs = sorted(path for path in base.iterdir() if path.is_dir() and not path.name.startswith("."))
    if not runs:
        raise FileNotFoundError(f"No hay runs en {base}")
    return runs[-1].resolve()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    try:
        run_dir = _resolve_run(project_root=project_root, player_id=args.player_id, requested=args.run)
    except FileNotFoundError as exc:
        print(f"Error: no existe {exc}")
        return 2

    snapshot = parse_player_full_run(run_dir, player_id=args.player_id)

    if args.output:
        output = Path(args.output)
        if not output.is_absolute():
            output = project_root / output
    else:
        output = (
            project_root / "data" / "parsed" / "bdfutbol"
            / f"player_full_{args.player_id}" / run_dir.name / "player_snapshot.json"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(snapshot), ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== BDFUTBOL PLAYER PARSER ===")
    print(f"Jugador:           {snapshot.identity.provider_id}")
    print(f"Nombre:            {snapshot.identity.full_name}")
    print(f"Posición:          {snapshot.identity.position}")
    print(f"Trayectoria canon: {len(snapshot.canonical_career)}")
    print(f"Trayectoria mgr:   {len(snapshot.manager_career)}")
    print(f"Partidos:          {len(snapshot.match_appearances)}")
    print(f"Stats competición: {0 if snapshot.competition_stats is None else len(snapshot.competition_stats.rows)}")
    print(f"Stats equipo:      {0 if snapshot.team_stats is None else len(snapshot.team_stats.rows)}")
    print(f"Warnings:          {len(snapshot.warnings)}")
    print(f"Salida:            {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
