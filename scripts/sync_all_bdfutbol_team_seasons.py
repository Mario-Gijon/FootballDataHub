#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from football_data_hub.bdfutbol import parse_competition
from football_data_hub.bdfutbol.acquisition import resolve_latest_valid_snapshot
from football_data_hub.bdfutbol.browser import (
    BrowserRuntimeError,
    start_browser,
    stop_browser,
)
from football_data_hub.bdfutbol.validation import (
    assess_page,
    url_matches_target,
)

if __package__:
    from . import sync_bdfutbol_team_season as team_sync
else:
    import sync_bdfutbol_team_season as team_sync


@dataclass(frozen=True, slots=True)
class TeamTarget:
    team_id: int
    team_name: str
    group: int


@dataclass(frozen=True, slots=True)
class TeamResult:
    team_id: int
    team_name: str
    group: int
    status: str
    url: str
    squad_count: int | None = None
    player_ids: tuple[int, ...] = ()
    snapshot_directory: str | None = None
    error: str | None = None
    attempts: int = 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sincroniza en una única sesión los equipos/temporada de los "
            "grupos I y II de una competición BDFutbol."
        )
    )
    parser.add_argument("--season", required=True)
    parser.add_argument("--competition", default="1rf")
    parser.add_argument("--expect-teams-per-group", type=int, default=20)
    parser.add_argument("--expect-fixtures-per-group", type=int, default=380)
    parser.add_argument("--min-players", type=int, default=15)
    parser.add_argument("--target-attempts", type=int, default=2)
    parser.add_argument("--challenge-wait-seconds", type=float, default=12.0)
    parser.add_argument("--resource-wait-seconds", type=float, default=20.0)
    parser.add_argument("--between-teams-seconds", type=float, default=0.35)
    parser.add_argument("--retry-delay-seconds", type=float, default=1.0)
    parser.add_argument("--timeout-ms", type=int, default=45_000)
    parser.add_argument("--settle-ms", type=int, default=2_000)
    parser.add_argument(
        "--browser",
        choices=("auto", "brave", "chrome", "chromium"),
        default="auto",
    )
    parser.add_argument(
        "--profile",
        default=str(Path.home() / ".football-data-hub-browser"),
    )
    parser.add_argument(
        "--show-teams",
        action="store_true",
        help="Muestra una línea final por equipo.",
    )
    return parser.parse_args(argv)


def _dump_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _validate_configuration(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"\d{4}-\d{2}", args.season):
        raise ValueError(
            "season debe usar el formato YYYY-YY, por ejemplo 2026-27"
        )
    if not re.fullmatch(r"[a-z0-9]+", args.competition):
        raise ValueError(
            "competition solo puede contener letras minúsculas y números"
        )
    if args.expect_teams_per_group < 1:
        raise ValueError("--expect-teams-per-group debe ser >= 1")
    if args.expect_fixtures_per_group < 1:
        raise ValueError("--expect-fixtures-per-group debe ser >= 1")
    if args.min_players < 1:
        raise ValueError("--min-players debe ser >= 1")
    if args.target_attempts < 1:
        raise ValueError("--target-attempts debe ser >= 1")
    if args.between_teams_seconds < 0:
        raise ValueError("--between-teams-seconds debe ser >= 0")


def _competition_snapshot_name(
    season: str,
    competition: str,
    group: int,
) -> str:
    return f"competition_{season}_{competition}_group{group}"


def discover_team_targets(
    *,
    project_root: Path,
    season: str,
    competition: str,
    expected_teams_per_group: int,
    expected_fixtures_per_group: int,
) -> tuple[TeamTarget, ...]:
    """Read the two validated competition snapshots and return 40 team IDs."""

    targets: list[TeamTarget] = []

    for group in (1, 2):
        snapshot_name = _competition_snapshot_name(
            season,
            competition,
            group,
        )
        page_path = resolve_latest_valid_snapshot(
            project_root,
            snapshot_name,
        )
        html = page_path.read_text(encoding="utf-8")
        source_url = (
            f"https://www.bdfutbol.com/es/t/"
            f"t{season}{competition}{group}.html"
        )

        snapshot = parse_competition(
            html,
            source_url,
            expected_team_count=expected_teams_per_group,
            expected_fixture_count=expected_fixtures_per_group,
        )

        if snapshot.context.group != group:
            raise ValueError(
                f"{snapshot_name} contiene grupo={snapshot.context.group}, "
                f"se esperaba {group}."
            )
        if snapshot.context.season != season:
            raise ValueError(
                f"{snapshot_name} contiene temporada={snapshot.context.season}, "
                f"se esperaba {season}."
            )
        if snapshot.context.competition_code != competition:
            raise ValueError(
                f"{snapshot_name} contiene competición="
                f"{snapshot.context.competition_code}, "
                f"se esperaba {competition}."
            )

        for row in snapshot.standings:
            targets.append(
                TeamTarget(
                    team_id=row.team.provider_id,
                    team_name=row.team_name,
                    group=group,
                )
            )

    ids = [target.team_id for target in targets]
    duplicates = sorted(
        team_id
        for team_id in set(ids)
        if ids.count(team_id) > 1
    )
    if duplicates:
        raise ValueError(
            f"Hay team_id duplicados entre grupos: {duplicates}"
        )

    expected_total = expected_teams_per_group * 2
    if len(targets) != expected_total:
        raise ValueError(
            f"Se esperaban {expected_total} equipos y se obtuvieron "
            f"{len(targets)}."
        )

    return tuple(targets)


def _team_run_paths(
    *,
    project_root: Path,
    season: str,
    team_id: int,
) -> tuple[Path, Path, str]:
    url, snapshot_name = team_sync.build_url_and_snapshot_name(
        season,
        team_id,
    )
    del url

    base_dir = (
        project_root
        / "data"
        / "raw"
        / "bdfutbol"
        / snapshot_name
    )
    run_id = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S.%fZ"
    )
    run_dir = base_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return base_dir, run_dir, snapshot_name


def _target_attempt(
    *,
    context: Any,
    project_root: Path,
    args: argparse.Namespace,
    target: TeamTarget,
    batch_run_id: str,
) -> TeamResult:
    url, _ = team_sync.build_url_and_snapshot_name(
        args.season,
        target.team_id,
    )
    base_dir, run_dir, _ = _team_run_paths(
        project_root=project_root,
        season=args.season,
        team_id=target.team_id,
    )

    attempts: list[dict[str, Any]] = []
    last_status = team_sync.STATUS_INVALID
    last_error: str | None = None

    for attempt_number in range(1, args.target_attempts + 1):
        target_dir = run_dir / f"target_{attempt_number:02d}"
        page = context.new_page()
        page.set_default_navigation_timeout(args.timeout_ms)

        navigation_error: str | None = None
        response_status: int | None = None

        try:
            try:
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=args.timeout_ms,
                )
                if response is not None:
                    response_status = response.status
            except PlaywrightTimeoutError as exc:
                navigation_error = f"{type(exc).__name__}: {exc}"
            except PlaywrightError as exc:
                navigation_error = f"{type(exc).__name__}: {exc}"

            if args.settle_ms > 0:
                page.wait_for_timeout(args.settle_ms)

            if navigation_error is None:
                (
                    status,
                    assessment,
                    snapshot,
                    resource_error,
                ) = team_sync._wait_for_team_season_resource(
                    page,
                    url=url,
                    team_id=target.team_id,
                    min_players=args.min_players,
                    wait_seconds=args.resource_wait_seconds,
                )
            else:
                assessment = assess_page(page)
                snapshot = None
                resource_error = navigation_error
                status = team_sync.STATUS_NAVIGATION_ERROR

            last_status = status
            last_error = resource_error

            metadata = {
                "phase": "batch_target",
                "batch_run_id": batch_run_id,
                "team_id": target.team_id,
                "team_name": target.team_name,
                "group": target.group,
                "attempt": attempt_number,
                "status": status,
                "requested_url": url,
                "final_url": page.url,
                "url_matches_target": url_matches_target(url, page.url),
                "http_status_diagnostic": response_status,
                "navigation_error": navigation_error,
                "resource_error": resource_error,
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            team_sync._save_page_artifacts(
                page,
                target_dir,
                assessment,
                metadata=metadata,
            )
            attempts.append(metadata)

            if status == team_sync.STATUS_VALID and snapshot is not None:
                team_sync._write_latest_valid(
                    project_root=project_root,
                    base_dir=base_dir,
                    run_dir=run_dir,
                    snapshot_dir=target_dir,
                    url=url,
                )
                player_ids = tuple(
                    member.player.provider_id
                    for member in snapshot.squad
                )
                _dump_json(
                    run_dir / "run_summary.json",
                    {
                        "source": "bdfutbol",
                        "batch_run_id": batch_run_id,
                        "team_id": target.team_id,
                        "team_name": snapshot.context.team_name,
                        "group": target.group,
                        "url": url,
                        "status": team_sync.STATUS_VALID,
                        "valid_snapshot_directory": (
                            target_dir.relative_to(
                                project_root
                            ).as_posix()
                        ),
                        "squad_count": len(snapshot.squad),
                        "player_ids": list(player_ids),
                        "attempts": attempts,
                        "finished_at_utc": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    },
                )
                return TeamResult(
                    team_id=target.team_id,
                    team_name=snapshot.context.team_name,
                    group=target.group,
                    status=team_sync.STATUS_VALID,
                    url=url,
                    squad_count=len(snapshot.squad),
                    player_ids=player_ids,
                    snapshot_directory=target_dir.relative_to(
                        project_root
                    ).as_posix(),
                    attempts=attempt_number,
                )
        finally:
            try:
                page.close()
            except Exception:
                pass

        if (
            attempt_number < args.target_attempts
            and args.retry_delay_seconds > 0
        ):
            time.sleep(args.retry_delay_seconds)

    _dump_json(
        run_dir / "run_summary.json",
        {
            "source": "bdfutbol",
            "batch_run_id": batch_run_id,
            "team_id": target.team_id,
            "team_name": target.team_name,
            "group": target.group,
            "url": url,
            "status": last_status,
            "valid_snapshot_directory": None,
            "squad_count": None,
            "player_ids": [],
            "error": last_error,
            "attempts": attempts,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )

    return TeamResult(
        team_id=target.team_id,
        team_name=target.team_name,
        group=target.group,
        status=last_status,
        url=url,
        error=last_error,
        attempts=args.target_attempts,
    )


def run_batch_session(
    *,
    project_root: Path,
    args: argparse.Namespace,
    targets: tuple[TeamTarget, ...],
    batch_run_id: str,
) -> tuple[TeamResult, ...]:
    """Open one browser session and walk all team-season targets."""

    first_url, _ = team_sync.build_url_and_snapshot_name(
        args.season,
        targets[0].team_id,
    )

    try:
        runtime = start_browser(
            profile=Path(args.profile),
            preference=args.browser,
            start_url=first_url,
        )
    except BrowserRuntimeError as exc:
        raise RuntimeError(
            f"No se pudo iniciar navegador: {exc}"
        ) from exc

    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(
                    runtime.cdp_url
                )
            except PlaywrightError as exc:
                raise RuntimeError(
                    f"No se pudo conectar por CDP: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

            if not browser.contexts:
                raise RuntimeError(
                    "El navegador no expone ningún contexto."
                )

            context = browser.contexts[0]
            preflight_page = team_sync._find_same_origin_page(
                context.pages,
                first_url,
            )

            if preflight_page is None:
                deadline = time.monotonic() + 5.0
                while (
                    time.monotonic() < deadline
                    and preflight_page is None
                ):
                    time.sleep(0.25)
                    preflight_page = team_sync._find_same_origin_page(
                        context.pages,
                        first_url,
                    )

            if preflight_page is None:
                raise RuntimeError(
                    "No apareció ninguna pestaña de BDFutbol "
                    "para realizar el preflight."
                )

            assessment, preflight_status = (
                team_sync._wait_for_bdfutbol_session(
                    preflight_page,
                    url=first_url,
                    wait_seconds=args.challenge_wait_seconds,
                )
            )

            print(
                f"[preflight] {preflight_status:<18} "
                f"challenge={assessment.challenge_visible} "
                f"links={assessment.link_count}"
            )
            print(f"            final_url={preflight_page.url}")

            if preflight_status != team_sync.STATUS_VALID:
                raise RuntimeError(
                    f"Preflight BDFutbol terminó en "
                    f"{preflight_status}."
                )

            results: list[TeamResult] = []

            for index, target in enumerate(targets, start=1):
                print(
                    f"[{index:02d}/{len(targets):02d}] "
                    f"{target.team_name} (team_id={target.team_id}, "
                    f"G{target.group}) ... ",
                    end="",
                    flush=True,
                )

                result = _target_attempt(
                    context=context,
                    project_root=project_root,
                    args=args,
                    target=target,
                    batch_run_id=batch_run_id,
                )
                results.append(result)

                if result.status == team_sync.STATUS_VALID:
                    print(
                        f"VALID — {result.squad_count} jugadores"
                    )
                else:
                    print(
                        f"{result.status}"
                        + (
                            f" — {result.error}"
                            if result.error
                            else ""
                        )
                    )

                if (
                    index < len(targets)
                    and args.between_teams_seconds > 0
                ):
                    time.sleep(args.between_teams_seconds)

            return tuple(results)
    finally:
        stop_browser(runtime)


def _result_dict(result: TeamResult) -> dict[str, Any]:
    return {
        "team_id": result.team_id,
        "team_name": result.team_name,
        "group": result.group,
        "status": result.status,
        "url": result.url,
        "squad_count": result.squad_count,
        "player_ids": list(result.player_ids),
        "snapshot_directory": result.snapshot_directory,
        "error": result.error,
        "attempts": result.attempts,
    }


def _write_batch_summary(
    *,
    batch_dir: Path,
    season: str,
    competition: str,
    targets: tuple[TeamTarget, ...],
    results: tuple[TeamResult, ...],
) -> dict[str, Any]:
    valid = tuple(
        result
        for result in results
        if result.status == team_sync.STATUS_VALID
    )
    failed = tuple(
        result
        for result in results
        if result.status != team_sync.STATUS_VALID
    )

    all_player_ids = [
        player_id
        for result in valid
        for player_id in result.player_ids
    ]
    unique_player_ids = sorted(set(all_player_ids))

    summary = {
        "source": "bdfutbol",
        "season": season,
        "competition": competition,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_teams": len(targets),
        "valid": len(valid),
        "failed": len(failed),
        "players_total": sum(
            result.squad_count or 0
            for result in valid
        ),
        "unique_player_ids": len(unique_player_ids),
        "unique_player_id_values": unique_player_ids,
        "groups": {
            "1": {
                "requested": sum(
                    target.group == 1
                    for target in targets
                ),
                "valid": sum(
                    result.group == 1
                    and result.status == team_sync.STATUS_VALID
                    for result in results
                ),
            },
            "2": {
                "requested": sum(
                    target.group == 2
                    for target in targets
                ),
                "valid": sum(
                    result.group == 2
                    and result.status == team_sync.STATUS_VALID
                    for result in results
                ),
            },
        },
        "teams": [
            _result_dict(result)
            for result in results
        ],
    }

    _dump_json(batch_dir / "summary.json", summary)
    _dump_json(
        batch_dir / "unique_player_ids.json",
        unique_player_ids,
    )
    return summary


def run(
    args: argparse.Namespace,
    *,
    project_root: Path | None = None,
) -> int:
    project_root = (
        project_root or Path(__file__).resolve().parents[1]
    ).resolve()

    try:
        _validate_configuration(args)
        targets = discover_team_targets(
            project_root=project_root,
            season=args.season,
            competition=args.competition,
            expected_teams_per_group=args.expect_teams_per_group,
            expected_fixtures_per_group=args.expect_fixtures_per_group,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Error de configuración/discovery: {exc}")
        return 2

    batch_run_id = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S.%fZ"
    )
    batch_dir = (
        project_root
        / "data"
        / "raw"
        / "bdfutbol"
        / f"batch_team_seasons_{args.season}"
        / batch_run_id
    )
    batch_dir.mkdir(parents=True, exist_ok=False)

    print("=== BDFUTBOL ALL TEAM/SEASONS SYNC ===")
    print(f"Temporada:   {args.season}")
    print(f"Competición: {args.competition}")
    print(f"Equipos:     {len(targets)}")
    print(
        f"Grupo I:     "
        f"{sum(target.group == 1 for target in targets)}"
    )
    print(
        f"Grupo II:    "
        f"{sum(target.group == 2 for target in targets)}"
    )
    print(
        "Sesión:      una única sesión de navegador "
        "para todo el lote"
    )
    print()

    try:
        results = run_batch_session(
            project_root=project_root,
            args=args,
            targets=targets,
            batch_run_id=batch_run_id,
        )
    except RuntimeError as exc:
        _dump_json(
            batch_dir / "summary.json",
            {
                "source": "bdfutbol",
                "season": args.season,
                "competition": args.competition,
                "requested_teams": len(targets),
                "valid": 0,
                "failed": len(targets),
                "fatal_error": str(exc),
                "finished_at_utc": datetime.now(
                    timezone.utc
                ).isoformat(),
            },
        )
        print(f"\nError fatal del batch: {exc}")
        print(f"Resumen: {batch_dir / 'summary.json'}")
        return 3

    summary = _write_batch_summary(
        batch_dir=batch_dir,
        season=args.season,
        competition=args.competition,
        targets=targets,
        results=results,
    )

    print("\n=== BATCH COMPLETADO ===")
    print(f"Solicitados:       {summary['requested_teams']}")
    print(f"Válidos:           {summary['valid']}")
    print(f"Fallidos:          {summary['failed']}")
    print(f"Plantillas total:  {summary['players_total']}")
    print(
        f"player_id únicos:  "
        f"{summary['unique_player_ids']}"
    )
    print(f"Resumen:           {batch_dir / 'summary.json'}")
    print(
        f"IDs únicos:        "
        f"{batch_dir / 'unique_player_ids.json'}"
    )

    if args.show_teams:
        print("\n=== RESULTADOS POR EQUIPO ===")
        for result in results:
            detail = (
                f"{result.squad_count} jugadores"
                if result.squad_count is not None
                else (result.error or "-")
            )
            print(
                f"G{result.group} "
                f"{result.team_id:>4} "
                f"{result.team_name:<28.28} "
                f"{result.status:<18} {detail}"
            )

    # Partial batch failure should be visible to shell/CI, while preserving
    # every successful team snapshot and the audit summary.
    return 0 if summary["failed"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
