#!/usr/bin/env python3
"""Extrae clasificación y calendario 2026/27 desde snapshots de BDFutbol."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from football_data_hub.collectors.bdfutbol_competition import (
    CompetitionAccessStopped,
    InvalidCompetitionSnapshot,
    capture_competition_snapshots,
    load_competition_snapshot,
)
from football_data_hub.parsers.competition_coverage import build_competition_coverage
from football_data_hub.providers.bdfutbol.competition import (
    COMPETITION_URLS,
    PARSER_VERSION,
    parse_competition_html,
)
from football_data_hub.storage.competition_exports import write_competition_exports

DEFAULT_OUTPUT_ROOT = Path("data/parsed/bdfutbol/primera_federacion_2026_27")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    offline = modes.add_parser("offline", help="Procesa snapshots raw existentes sin red")
    offline.add_argument("--group-i", type=Path, required=True, help="Directorio de snapshot del Grupo I")
    offline.add_argument("--group-ii", type=Path, required=True, help="Directorio de snapshot del Grupo II")
    offline.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)

    live = modes.add_parser("live", help="Captura ambos grupos con Brave/Xvfb/CDP y los procesa")
    live.add_argument("--raw-root", type=Path, default=Path("data/raw/bdfutbol/competition_2026_27"))
    live.add_argument("--profile", type=Path, default=Path.home() / ".football-data-hub-v2-probe")
    live.add_argument("--browser", choices=("brave", "chrome", "chromium", "auto"), default="brave")
    live.add_argument("--settle-ms", type=int, default=1000)
    live.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args(argv)


def _load_and_parse(snapshot_paths: dict[str, Path]) -> tuple[list[dict], dict[str, object], dict[str, dict]]:
    snapshots = {
        group: load_competition_snapshot(snapshot_paths[group], group)
        for group in ("I", "II")
    }
    parsed_groups = []
    for group in ("I", "II"):
        parsed = parse_competition_html(
            snapshots[group].html,
            COMPETITION_URLS[group],
            captured_at_utc=snapshots[group].metadata.get("captured_at_utc"),
        )
        issue_codes = {issue["code"] for issue in parsed["diagnostics"]["issues"]}
        if not parsed["diagnostics"]["standings_headers_valid"] or not parsed["standings"]:
            raise InvalidCompetitionSnapshot(
                f"El HTML VALID de Grupo {group} no contiene una clasificación deportiva reconocible"
            )
        if issue_codes & {
            "competition_group_title_mismatch",
            "competition_season_title_mismatch",
        }:
            raise InvalidCompetitionSnapshot(
                f"El título del HTML no corresponde a temporada/grupo esperados: Grupo {group}"
            )
        parsed_groups.append(parsed)
    metadata = {group: snapshots[group].metadata for group in ("I", "II")}
    return parsed_groups, snapshots, metadata


def _write_outputs(
    *,
    parsed_groups: list[dict],
    snapshots: dict,
    metadata: dict,
    output_root: Path,
) -> int:
    quality = build_competition_coverage(parsed_groups, metadata)
    output_dir = write_competition_exports(
        parsed_groups=parsed_groups,
        snapshots_by_group=snapshots,
        quality=quality,
        output_root=output_root,
    )
    print(f"Parser: {PARSER_VERSION}")
    print(f"Salida: {output_dir}")
    print(
        "Cobertura observada: "
        f"{quality['observed']['groups']} grupos, "
        f"{quality['observed']['teams_total']} equipos, "
        f"{quality['observed']['matches_total']} partidos"
    )
    for group in quality["groups"]:
        observed = group["observed"]
        print(
            f"Grupo {group['group']}: {observed['teams']} equipos, "
            f"{observed['rounds']} jornadas, {observed['matches']} partidos "
            f"({observed['played_matches']} disputados, "
            f"{observed['scheduled_matches']} futuros, "
            f"{observed['unresolved_matches']} sin resultado con fecha pasada); "
            f"cobertura={'COMPLETA' if group['fixture_coverage_complete'] else 'INCOMPLETA'}"
        )
    return 0 if quality["coverage_complete"] else 2


def run(args: argparse.Namespace) -> int:
    try:
        if args.mode == "offline":
            snapshot_paths = {"I": args.group_i, "II": args.group_ii}
        else:
            if args.settle_ms < 0:
                raise ValueError("--settle-ms debe ser >= 0")
            print("Modo live: navegación limitada a las dos páginas de competición autorizadas.")
            snapshot_paths = capture_competition_snapshots(
                raw_root=args.raw_root,
                profile_dir=args.profile,
                browser=args.browser,
                settle_ms=args.settle_ms,
            )
            for group, path in snapshot_paths.items():
                print(f"Grupo {group}: snapshot VALID guardado en {path}")
        parsed_groups, snapshots, metadata = _load_and_parse(snapshot_paths)
        return _write_outputs(
            parsed_groups=parsed_groups,
            snapshots=snapshots,
            metadata=metadata,
            output_root=args.output_root,
        )
    except CompetitionAccessStopped as exc:
        assessment = exc.assessment
        print(
            f"ACCESO DETENIDO: Grupo {exc.group} status={assessment.status.value} "
            f"http={assessment.http_status} url={assessment.final_url or assessment.requested_url}. "
            "No se intentó resolver ni eludir el desafío; los snapshots válidos anteriores se conservaron.",
            file=sys.stderr,
        )
        return 4
    except (InvalidCompetitionSnapshot, OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
