#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

from football_data_hub.bdfutbol import parse_competition
from football_data_hub.bdfutbol.acquisition import (
    AcquisitionResult,
    AcquisitionStatus,
    BDFutbolAcquirer,
)
from football_data_hub.bdfutbol.cli import _assessment_diagnostic, _print_standings


def build_url_and_snapshot_name(
    season: str,
    competition: str = "1rf",
    group: int = 1,
) -> tuple[str, str]:
    if not re.fullmatch(r"\d{4}-\d{2}", season):
        raise ValueError("season debe usar el formato YYYY-YY, por ejemplo 2026-27")
    if not re.fullmatch(r"[a-z0-9]+", competition):
        raise ValueError("competition solo puede contener letras minúsculas y números")
    if group not in (1, 2):
        raise ValueError("group debe ser 1 o 2")

    url = f"https://www.bdfutbol.com/es/t/t{season}{competition}{group}.html"
    snapshot_name = f"competition_{season}_{competition}_group{group}"
    return url, snapshot_name


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Adquiere y parsea una competición de BDFutbol automáticamente."
    )
    parser.add_argument("--season", required=True)
    parser.add_argument("--group", required=True, type=int, choices=(1, 2))
    parser.add_argument("--competition", default="1rf")
    parser.add_argument("--expect-teams", type=int, default=20)
    parser.add_argument("--expect-fixtures", type=int, default=380)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--warmup-seconds", type=float, default=10.0)
    parser.add_argument(
        "--browser",
        choices=("auto", "brave", "chrome", "chromium"),
        default="auto",
    )
    parser.add_argument(
        "--profile",
        default=str(Path.home() / ".football-data-hub-browser"),
    )
    parser.add_argument("--timeout-ms", type=int, default=45_000)
    parser.add_argument("--settle-ms", type=int, default=3_000)
    parser.add_argument("--retry-delay-seconds", type=float, default=1.5)
    parser.add_argument("--show-standings", action="store_true")
    return parser.parse_args(argv)


def _print_attempts(result: AcquisitionResult) -> None:
    for item in result.attempts:
        detail = ""
        if item.http_status_diagnostic is not None:
            detail += f" http={item.http_status_diagnostic}"
        if item.assessment:
            assessment = item.assessment
            detail += (
                f" challenge={assessment['challenge_visible']}"
                f" links={assessment['link_count']}"
            )
        if item.browser_error:
            detail += f" error={item.browser_error}"
        print(f"[{item.phase:<7}] #{item.number} {item.status.value:<18}{detail}")

        if item.status is not AcquisitionStatus.VALID and item.assessment:
            for line in _assessment_diagnostic(item.assessment):
                print(f"           {line}")


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def run_sync(
    args: argparse.Namespace,
    *,
    project_root: Path | None = None,
) -> int:
    project_root = (project_root or Path(__file__).resolve().parents[1]).resolve()
    try:
        url, snapshot_name = build_url_and_snapshot_name(
            args.season,
            args.competition,
            args.group,
        )
    except ValueError as exc:
        print(f"Error de configuración: {exc}")
        return 2

    print("=== BDFUTBOL COMPETITION SYNC ===")
    print(f"Competición: {args.competition}")
    print(f"Temporada:   {args.season}")
    print(f"Grupo:       {args.group}")
    print(f"URL:         {url}")
    print(f"Snapshot:    {snapshot_name}")
    print()

    acquirer = BDFutbolAcquirer(
        project_root=project_root,
        profile=Path(args.profile),
        browser=args.browser,
        timeout_ms=args.timeout_ms,
        settle_ms=args.settle_ms,
        max_attempts=args.max_attempts,
        warmup_seconds=args.warmup_seconds,
        retry_delay_seconds=args.retry_delay_seconds,
    )
    result = acquirer.acquire(url=url, name=snapshot_name)
    _print_attempts(result)

    if result.status is not AcquisitionStatus.VALID:
        print()
        if result.status is AcquisitionStatus.BLOCKED:
            print(
                "Cloudflare sigue bloqueando la página después de los reintentos; "
                "no se ejecutará el parser."
            )
            return 3
        if result.status is AcquisitionStatus.NAVIGATION_ERROR:
            print(
                "La adquisición terminó con un error de navegación/red; "
                "no se ejecutará el parser."
            )
        else:
            print(
                f"La adquisición terminó en {result.status.value}; "
                "no se ejecutará el parser."
            )
        print(f"Run: {_display_path(result.run_directory, project_root)}")
        return 2

    if result.valid_snapshot_directory is None:
        print("La adquisición indicó VALID pero no devolvió la ruta del snapshot.")
        return 2

    page_path = result.valid_snapshot_directory / "page.html"
    if not page_path.is_file():
        print(f"No existe el page.html del snapshot válido: {page_path}")
        return 2

    try:
        html = page_path.read_text(encoding="utf-8")
        snapshot = parse_competition(
            html,
            url,
            expected_team_count=args.expect_teams,
            expected_fixture_count=args.expect_fixtures,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Error al parsear o validar la competición: {exc}")
        print(f"Snapshot: {_display_path(result.valid_snapshot_directory, project_root)}")
        return 4

    played = sum(fixture.played for fixture in snapshot.fixtures)
    pending = len(snapshot.fixtures) - played
    print("\n=== SYNC COMPLETADO ===")
    print(f"Competición:  {snapshot.context.competition_code}")
    print(f"Temporada:    {snapshot.context.season}")
    print(f"Grupo:        {snapshot.context.group}")
    print(f"Equipos:      {len(snapshot.standings)}")
    print(f"Partidos:     {len(snapshot.fixtures)}")
    print(f"Disputados:   {played}")
    print(f"Pendientes:   {pending}")
    print(f"Snapshot:     {_display_path(result.valid_snapshot_directory, project_root)}")

    if snapshot.warnings:
        print("\nWarnings:")
        for warning in snapshot.warnings:
            print(f"  - {warning}")
    if args.show_standings:
        _print_standings(snapshot.standings)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_sync(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
