#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SRC_ROOT = PROJECT_ROOT / "src"

for _import_root in (PROJECT_ROOT, SRC_ROOT):
    _value = str(_import_root)
    if _value not in sys.path:
        sys.path.insert(0, _value)


from playwright.sync_api import sync_playwright

from football_data_hub.bdfutbol.browser import (
    BrowserRuntimeError,
    start_browser,
    stop_browser,
)
from football_data_hub.bdfutbol.player import parse_player_full_run

from scripts import sync_bdfutbol_player_full as player_sync
from scripts import sync_bdfutbol_team_season as team_sync


STATUS_VALID = "VALID"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED_VALID = "SKIPPED_VALID"
STATUS_PARSE_FAILED = "PARSE_FAILED"


@dataclass(frozen=True, slots=True)
class BatchPlayerResult:
    player_id: int
    status: str
    run_directory: str | None = None
    summary_path: str | None = None
    required_failed: int | None = None
    optional_failed: int | None = None
    resources_valid: int | None = None
    resources_requested: int | None = None
    parsed_snapshot: str | None = None
    parse_status: str | None = None
    parse_warnings: int | None = None
    error: str | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sincroniza Player Full para muchos jugadores de BDFutbol usando "
            "una única sesión persistente de navegador."
        )
    )
    parser.add_argument(
        "--season",
        required=True,
        help="Temporada origen del listado, por ejemplo 2026-27.",
    )
    parser.add_argument(
        "--ids-file",
        help=(
            "JSON con IDs de jugadores. Si se omite se usa el "
            "unique_player_ids.json más reciente del batch de equipos."
        ),
    )
    parser.add_argument(
        "--player-id",
        type=int,
        action="append",
        dest="player_ids",
        help=(
            "Limita el batch a este player_id. Puede repetirse varias veces."
        ),
    )
    parser.add_argument(
        "--start-at",
        type=int,
        help=(
            "Empieza en este player_id dentro del listado seleccionado."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help=(
            "Máximo de jugadores seleccionados después de --start-at. "
            "Los SKIPPED_VALID cuentan dentro del límite."
        ),
    )
    parser.add_argument(
        "--skip-valid",
        action="store_true",
        help=(
            "No vuelve a capturar jugadores con latest_valid.json correcto."
        ),
    )
    parser.add_argument(
        "--parse-after-sync",
        action="store_true",
        help=(
            "Genera player_snapshot.json después de cada jugador válido; "
            "también para SKIPPED_VALID."
        ),
    )
    parser.add_argument(
        "--between-players-seconds",
        type=float,
        default=0.75,
    )
    parser.add_argument("--attempts-per-resource", type=int, default=2)
    parser.add_argument("--challenge-wait-seconds", type=float, default=12.0)
    parser.add_argument("--resource-wait-seconds", type=float, default=15.0)
    parser.add_argument("--retry-delay-seconds", type=float, default=0.8)
    parser.add_argument("--between-resources-seconds", type=float, default=0.25)
    parser.add_argument("--timeout-ms", type=int, default=45_000)
    parser.add_argument("--settle-ms", type=int, default=1_500)
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
        "--show-resources",
        action="store_true",
        help="Muestra el estado de cada recurso de cada jugador.",
    )
    return parser.parse_args(argv)


def _dump_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def _validate_args(args: argparse.Namespace) -> None:
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit debe ser >= 1")
    if args.start_at is not None and args.start_at <= 0:
        raise ValueError("--start-at debe ser > 0")
    if args.player_ids and any(player_id <= 0 for player_id in args.player_ids):
        raise ValueError("--player-id debe ser > 0")
    if args.attempts_per_resource < 1:
        raise ValueError("--attempts-per-resource debe ser >= 1")
    if args.between_players_seconds < 0:
        raise ValueError("--between-players-seconds debe ser >= 0")
    if args.between_resources_seconds < 0:
        raise ValueError("--between-resources-seconds debe ser >= 0")


def resolve_ids_file(
    *,
    project_root: Path,
    season: str,
    requested: str | None,
) -> Path:
    if requested:
        path = Path(requested)
        if not path.is_absolute():
            path = project_root / path
        if not path.is_file():
            raise FileNotFoundError(path)
        return path.resolve()

    base = (
        project_root
        / "data"
        / "raw"
        / "bdfutbol"
        / f"batch_team_seasons_{season}"
    )
    if not base.is_dir():
        raise FileNotFoundError(base)

    candidates = sorted(
        path / "unique_player_ids.json"
        for path in base.iterdir()
        if path.is_dir() and (path / "unique_player_ids.json").is_file()
    )
    if not candidates:
        raise FileNotFoundError(
            f"No hay unique_player_ids.json en {base}"
        )
    return candidates[-1].resolve()


def load_player_ids(path: Path) -> tuple[int, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} debe contener una lista JSON")

    result: list[int] = []
    seen: set[int] = set()
    for raw in data:
        if isinstance(raw, bool):
            raise ValueError(f"ID inválido en {path}: {raw!r}")
        try:
            player_id = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"ID inválido en {path}: {raw!r}") from exc
        if player_id <= 0:
            raise ValueError(f"ID inválido en {path}: {player_id}")
        if player_id not in seen:
            seen.add(player_id)
            result.append(player_id)

    if not result:
        raise ValueError(f"{path} no contiene player IDs")
    return tuple(result)


def select_player_ids(
    source_ids: Iterable[int],
    *,
    explicit_ids: list[int] | None,
    start_at: int | None,
    limit: int | None,
) -> tuple[int, ...]:
    source = tuple(source_ids)

    if explicit_ids:
        available = set(source)
        selected: list[int] = []
        seen: set[int] = set()
        missing: list[int] = []
        for player_id in explicit_ids:
            if player_id not in available:
                missing.append(player_id)
                continue
            if player_id not in seen:
                seen.add(player_id)
                selected.append(player_id)
        if missing:
            raise ValueError(
                "player_id no presentes en el fichero origen: "
                + ", ".join(map(str, missing))
            )
    else:
        selected = list(source)

    if start_at is not None:
        try:
            index = selected.index(start_at)
        except ValueError as exc:
            raise ValueError(
                f"--start-at {start_at} no está en la selección"
            ) from exc
        selected = selected[index:]

    if limit is not None:
        selected = selected[:limit]

    return tuple(selected)


def _player_raw_root(project_root: Path, player_id: int) -> Path:
    return (
        project_root
        / "data"
        / "raw"
        / "bdfutbol"
        / f"player_full_{player_id}"
    )


def resolve_latest_valid_player_run(
    *,
    project_root: Path,
    player_id: int,
) -> Path | None:
    root = _player_raw_root(project_root, player_id)
    pointer = root / "latest_valid.json"
    if not pointer.is_file():
        return None

    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
    except Exception:
        return None

    raw_run = payload.get("run_directory")
    if not isinstance(raw_run, str) or not raw_run:
        return None

    run_dir = Path(raw_run)
    if not run_dir.is_absolute():
        candidate = project_root / run_dir
        if candidate.is_dir():
            run_dir = candidate
        else:
            run_dir = root / run_dir.name

    summary_path = run_dir / "summary.json"
    if not run_dir.is_dir() or not summary_path.is_file():
        return None

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if summary.get("player_id") != player_id:
        return None
    if int(summary.get("required_failed", 1)) != 0:
        return None
    return run_dir.resolve()


def _player_args(
    batch_args: argparse.Namespace,
    *,
    player_id: int,
) -> argparse.Namespace:
    return argparse.Namespace(
        player_id=player_id,
        attempts_per_resource=batch_args.attempts_per_resource,
        challenge_wait_seconds=batch_args.challenge_wait_seconds,
        resource_wait_seconds=batch_args.resource_wait_seconds,
        retry_delay_seconds=batch_args.retry_delay_seconds,
        between_resources_seconds=batch_args.between_resources_seconds,
        timeout_ms=batch_args.timeout_ms,
        settle_ms=batch_args.settle_ms,
        browser=batch_args.browser,
        profile=batch_args.profile,
    )


def _collect_same_player_links(
    *,
    project_root: Path,
    results: list[player_sync.ResourceResult],
) -> list[str]:
    links: set[str] = set()
    for result in results:
        if not result.snapshot_directory:
            continue
        path = (
            project_root
            / result.snapshot_directory
            / "same_player_links.json"
        )
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(values, list):
            links.update(value for value in values if isinstance(value, str))
    return sorted(links)


def sync_player_in_context(
    *,
    context: Any,
    project_root: Path,
    batch_args: argparse.Namespace,
    player_id: int,
    batch_run_id: str,
) -> BatchPlayerResult:
    args = _player_args(batch_args, player_id=player_id)
    specs = player_sync.build_resource_specs(player_id)

    raw_root = _player_raw_root(project_root, player_id)
    run_dir = raw_root / player_sync._run_id()
    run_dir.mkdir(parents=True, exist_ok=False)

    results: list[player_sync.ResourceResult] = []
    season_specs: tuple[player_sync.ResourceSpec, ...] = ()

    try:
        for index, spec in enumerate(specs, start=1):
            result = player_sync._capture_resource(
                context=context,
                spec=spec,
                args=args,
                project_root=project_root,
                run_dir=run_dir,
            )
            results.append(result)
            if batch_args.show_resources:
                suffix = " optional" if spec.optional else ""
                print(
                    f"      [{index:02d}/{len(specs):02d}] "
                    f"{spec.name}: {result.status}{suffix}"
                )
            if (
                index < len(specs)
                and args.between_resources_seconds > 0
            ):
                time.sleep(args.between_resources_seconds)

        result_by_name = {result.name: result for result in results}
        canonical_matches_html = player_sync._read_snapshot_html(
            project_root=project_root,
            result=result_by_name.get("player_matches"),
        )
        manager_matches_html = player_sync._read_snapshot_html(
            project_root=project_root,
            result=result_by_name.get("player_matches_manager"),
        )
        season_specs = player_sync.build_season_match_specs(
            player_id=player_id,
            canonical_html=canonical_matches_html,
            manager_html=manager_matches_html,
        )

        for index, spec in enumerate(season_specs, start=1):
            result = player_sync._capture_resource(
                context=context,
                spec=spec,
                args=args,
                project_root=project_root,
                run_dir=run_dir,
            )
            results.append(result)
            if batch_args.show_resources:
                season = (spec.scope or {}).get("season") or spec.name
                suffix = " optional" if spec.optional else ""
                print(
                    f"      [S{index:02d}/{len(season_specs):02d}] "
                    f"{season}: {result.status}{suffix} "
                    f"[{spec.provenance}]"
                )
            if (
                index < len(season_specs)
                and args.between_resources_seconds > 0
            ):
                time.sleep(args.between_resources_seconds)

        all_specs = tuple(specs) + tuple(season_specs)
        required_names = {
            spec.name for spec in all_specs if not spec.optional
        }
        optional_names = {
            spec.name for spec in all_specs if spec.optional
        }
        required_failed = [
            result
            for result in results
            if result.name in required_names
            and result.status != player_sync.STATUS_VALID
        ]
        optional_failed = [
            result
            for result in results
            if result.name in optional_names
            and result.status != player_sync.STATUS_VALID
        ]

        summary = {
            "source": "bdfutbol",
            "entity_type": "player",
            "player_id": player_id,
            "batch_run_id": batch_run_id,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "base_resources_requested": len(specs),
            "season_match_resources_requested": len(season_specs),
            "resources_requested": len(all_specs),
            "resources_valid": sum(
                result.status == player_sync.STATUS_VALID
                for result in results
            ),
            "match_seasons_discovered": [
                {
                    "season": (spec.scope or {}).get("season"),
                    "url": spec.url,
                    "provenance": spec.provenance,
                    "optional": spec.optional,
                }
                for spec in season_specs
            ],
            "required_failed": len(required_failed),
            "optional_failed": len(optional_failed),
            "same_player_links_discovered": _collect_same_player_links(
                project_root=project_root,
                results=results,
            ),
            "resources": [
                player_sync._result_dict(result) for result in results
            ],
        }
        summary_path = run_dir / "summary.json"
        player_sync._dump_json(summary_path, summary)

        if not required_failed:
            player_sync._write_latest_valid(
                root=raw_root,
                run_dir=run_dir,
                summary_path=summary_path,
            )

        status = STATUS_VALID if not required_failed else STATUS_FAILED
        return BatchPlayerResult(
            player_id=player_id,
            status=status,
            run_directory=run_dir.relative_to(project_root).as_posix(),
            summary_path=summary_path.relative_to(project_root).as_posix(),
            required_failed=len(required_failed),
            optional_failed=len(optional_failed),
            resources_valid=summary["resources_valid"],
            resources_requested=summary["resources_requested"],
        )
    except Exception as exc:
        failure_summary = {
            "source": "bdfutbol",
            "entity_type": "player",
            "player_id": player_id,
            "batch_run_id": batch_run_id,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": STATUS_FAILED,
            "error": f"{type(exc).__name__}: {exc}",
            "resources": [
                player_sync._result_dict(result) for result in results
            ],
        }
        summary_path = run_dir / "summary.json"
        player_sync._dump_json(summary_path, failure_summary)
        return BatchPlayerResult(
            player_id=player_id,
            status=STATUS_FAILED,
            run_directory=run_dir.relative_to(project_root).as_posix(),
            summary_path=summary_path.relative_to(project_root).as_posix(),
            error=f"{type(exc).__name__}: {exc}",
        )


def parse_player_run_to_disk(
    *,
    project_root: Path,
    player_id: int,
    run_dir: Path,
) -> tuple[str, str, int]:
    snapshot = parse_player_full_run(run_dir, player_id=player_id)
    output = (
        project_root
        / "data"
        / "parsed"
        / "bdfutbol"
        / f"player_full_{player_id}"
        / run_dir.name
        / "player_snapshot.json"
    )
    _dump_json(output, asdict(snapshot))
    status = "VALID" if not snapshot.warnings else "VALID_WITH_WARNINGS"
    return (
        output.relative_to(project_root).as_posix(),
        status,
        len(snapshot.warnings),
    )


def _replace_parse_fields(
    result: BatchPlayerResult,
    *,
    parsed_snapshot: str | None,
    parse_status: str | None,
    parse_warnings: int | None,
    error: str | None = None,
) -> BatchPlayerResult:
    return BatchPlayerResult(
        player_id=result.player_id,
        status=result.status,
        run_directory=result.run_directory,
        summary_path=result.summary_path,
        required_failed=result.required_failed,
        optional_failed=result.optional_failed,
        resources_valid=result.resources_valid,
        resources_requested=result.resources_requested,
        parsed_snapshot=parsed_snapshot,
        parse_status=parse_status,
        parse_warnings=parse_warnings,
        error=error or result.error,
    )


def _batch_counts(results: list[BatchPlayerResult]) -> dict[str, int]:
    return {
        "processed": len(results),
        "valid": sum(result.status == STATUS_VALID for result in results),
        "skipped_valid": sum(
            result.status == STATUS_SKIPPED_VALID for result in results
        ),
        "failed": sum(result.status == STATUS_FAILED for result in results),
        "parse_failed": sum(
            result.parse_status == STATUS_PARSE_FAILED for result in results
        ),
    }


def _write_checkpoint(
    *,
    path: Path,
    batch_run_id: str,
    season: str,
    ids_file: Path,
    selected_ids: tuple[int, ...],
    results: list[BatchPlayerResult],
) -> None:
    processed_ids = [result.player_id for result in results]
    next_player_id = (
        selected_ids[len(results)]
        if len(results) < len(selected_ids)
        else None
    )
    _dump_json(
        path,
        {
            "batch_run_id": batch_run_id,
            "season": season,
            "ids_file": str(ids_file),
            "selected_count": len(selected_ids),
            "processed_count": len(results),
            "processed_player_ids": processed_ids,
            "next_player_id": next_player_id,
            "counts": _batch_counts(results),
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "results": [asdict(result) for result in results],
        },
    )


def run_batch(
    args: argparse.Namespace,
    *,
    project_root: Path | None = None,
) -> int:
    project_root = (
        project_root
        if project_root is not None
        else Path(__file__).resolve().parents[1]
    )

    try:
        _validate_args(args)
        ids_file = resolve_ids_file(
            project_root=project_root,
            season=args.season,
            requested=args.ids_file,
        )
        source_ids = load_player_ids(ids_file)
        selected_ids = select_player_ids(
            source_ids,
            explicit_ids=args.player_ids,
            start_at=args.start_at,
            limit=args.limit,
        )
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"Error de configuración: {exc}")
        return 2

    if not selected_ids:
        print("No hay jugadores seleccionados.")
        return 0

    batch_run_id = _run_id()
    analysis_dir = (
        project_root
        / "data"
        / "analysis"
        / "bdfutbol"
        / f"batch_player_full_{args.season}"
        / batch_run_id
    )
    analysis_dir.mkdir(parents=True, exist_ok=False)
    checkpoint_path = analysis_dir / "checkpoint.json"
    summary_path = analysis_dir / "summary.json"

    _dump_json(
        analysis_dir / "plan.json",
        {
            "batch_run_id": batch_run_id,
            "season": args.season,
            "ids_file": str(ids_file),
            "selected_player_ids": list(selected_ids),
            "skip_valid": args.skip_valid,
            "parse_after_sync": args.parse_after_sync,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )

    existing_valid: dict[int, Path] = {}
    if args.skip_valid:
        for player_id in selected_ids:
            run = resolve_latest_valid_player_run(
                project_root=project_root,
                player_id=player_id,
            )
            if run is not None:
                existing_valid[player_id] = run

    to_sync = [
        player_id
        for player_id in selected_ids
        if player_id not in existing_valid
    ]

    print("=== BDFUTBOL PLAYER FULL BATCH ===")
    print(f"Temporada:        {args.season}")
    print(f"IDs origen:       {len(source_ids)}")
    print(f"Seleccionados:    {len(selected_ids)}")
    print(f"Ya válidos:       {len(existing_valid)}")
    print(f"A sincronizar:    {len(to_sync)}")
    print(f"IDs file:         {ids_file}")
    print(f"Batch:            {analysis_dir}")

    runtime = None
    browser = None
    context = None
    playwright = None

    if to_sync:
        first_url = player_sync.build_resource_specs(to_sync[0])[0].url
        try:
            runtime = start_browser(
                profile=Path(args.profile),
                preference=args.browser,
                start_url=first_url,
            )
        except BrowserRuntimeError as exc:
            _dump_json(
                summary_path,
                {
                    "batch_run_id": batch_run_id,
                    "status": STATUS_FAILED,
                    "error": f"BrowserRuntimeError: {exc}",
                    "selected_player_ids": list(selected_ids),
                },
            )
            print(f"No se pudo iniciar navegador: {exc}")
            return 3

        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.connect_over_cdp(runtime.cdp_url)
            if not browser.contexts:
                raise RuntimeError("El navegador no expone ningún contexto")
            context = browser.contexts[0]

            preflight_page = team_sync._find_same_origin_page(
                context.pages,
                first_url,
            )
            deadline = time.monotonic() + 5.0
            while preflight_page is None and time.monotonic() < deadline:
                time.sleep(0.25)
                preflight_page = team_sync._find_same_origin_page(
                    context.pages,
                    first_url,
                )
            if preflight_page is None:
                raise RuntimeError("No apareció ninguna pestaña BDFutbol")

            assessment, preflight_status = team_sync._wait_for_bdfutbol_session(
                preflight_page,
                url=first_url,
                wait_seconds=args.challenge_wait_seconds,
            )
            print(
                f"[preflight] {preflight_status:<18} "
                f"challenge={assessment.challenge_visible} "
                f"links={assessment.link_count}"
            )
            print(f"            final_url={preflight_page.url}")
            if preflight_status != player_sync.STATUS_VALID:
                raise RuntimeError(
                    f"Preflight BDFutbol no válido: {preflight_status}"
                )
        except Exception as exc:
            if playwright is not None:
                try:
                    playwright.stop()
                except Exception:
                    pass
            stop_browser(runtime)
            _dump_json(
                summary_path,
                {
                    "batch_run_id": batch_run_id,
                    "status": STATUS_FAILED,
                    "error": f"{type(exc).__name__}: {exc}",
                    "selected_player_ids": list(selected_ids),
                },
            )
            print(f"Preflight fallido: {exc}")
            return 3

    results: list[BatchPlayerResult] = []
    started = time.monotonic()

    try:
        for index, player_id in enumerate(selected_ids, start=1):
            print(
                f"[{index:04d}/{len(selected_ids):04d}] "
                f"player_id={player_id} ... ",
                end="",
                flush=True,
            )

            if player_id in existing_valid:
                run_dir = existing_valid[player_id]
                result = BatchPlayerResult(
                    player_id=player_id,
                    status=STATUS_SKIPPED_VALID,
                    run_directory=run_dir.relative_to(project_root).as_posix(),
                    summary_path=(run_dir / "summary.json").relative_to(
                        project_root
                    ).as_posix(),
                )
                print("SKIPPED_VALID", end="")
            else:
                if context is None:
                    result = BatchPlayerResult(
                        player_id=player_id,
                        status=STATUS_FAILED,
                        error="No hay browser context disponible",
                    )
                else:
                    result = sync_player_in_context(
                        context=context,
                        project_root=project_root,
                        batch_args=args,
                        player_id=player_id,
                        batch_run_id=batch_run_id,
                    )
                print(result.status, end="")
                if result.required_failed is not None:
                    print(
                        f" resources={result.resources_valid}/"
                        f"{result.resources_requested} "
                        f"req_fail={result.required_failed} "
                        f"opt_fail={result.optional_failed}",
                        end="",
                    )

            if (
                args.parse_after_sync
                and result.status in {STATUS_VALID, STATUS_SKIPPED_VALID}
                and result.run_directory
            ):
                run_dir = project_root / result.run_directory
                try:
                    parsed, parse_status, warnings = parse_player_run_to_disk(
                        project_root=project_root,
                        player_id=player_id,
                        run_dir=run_dir,
                    )
                    result = _replace_parse_fields(
                        result,
                        parsed_snapshot=parsed,
                        parse_status=parse_status,
                        parse_warnings=warnings,
                    )
                    print(
                        f" parse={parse_status} warnings={warnings}",
                        end="",
                    )
                except Exception as exc:
                    result = _replace_parse_fields(
                        result,
                        parsed_snapshot=None,
                        parse_status=STATUS_PARSE_FAILED,
                        parse_warnings=None,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    print(f" parse=FAILED({type(exc).__name__})", end="")

            print()
            results.append(result)
            _write_checkpoint(
                path=checkpoint_path,
                batch_run_id=batch_run_id,
                season=args.season,
                ids_file=ids_file,
                selected_ids=selected_ids,
                results=results,
            )

            if (
                index < len(selected_ids)
                and args.between_players_seconds > 0
                and player_id not in existing_valid
            ):
                time.sleep(args.between_players_seconds)
    finally:
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
        if runtime is not None:
            stop_browser(runtime)

    counts = _batch_counts(results)
    summary = {
        "source": "bdfutbol",
        "entity_type": "player_batch",
        "season": args.season,
        "batch_run_id": batch_run_id,
        "ids_file": str(ids_file),
        "selected_player_ids": list(selected_ids),
        "selected_count": len(selected_ids),
        "skip_valid": args.skip_valid,
        "parse_after_sync": args.parse_after_sync,
        "counts": counts,
        "duration_seconds": round(time.monotonic() - started, 3),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "results": [asdict(result) for result in results],
    }
    _dump_json(summary_path, summary)

    print("\n=== PLAYER FULL BATCH COMPLETADO ===")
    print(f"Procesados:        {counts['processed']}")
    print(f"Válidos nuevos:    {counts['valid']}")
    print(f"Saltados válidos:  {counts['skipped_valid']}")
    print(f"Fallidos:          {counts['failed']}")
    if args.parse_after_sync:
        print(f"Parse fallidos:    {counts['parse_failed']}")
    print(f"Checkpoint:        {checkpoint_path}")
    print(f"Resumen:           {summary_path}")

    return 0 if counts["failed"] == 0 and counts["parse_failed"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_batch(args)


if __name__ == "__main__":
    raise SystemExit(main())
