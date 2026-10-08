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
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from football_data_hub.bdfutbol.browser import (
    BrowserRuntimeError,
    start_browser,
    stop_browser,
)
from football_data_hub.bdfutbol.validation import (
    PageAssessment,
    assess_page,
    url_matches_target,
    urls_share_origin,
)

if __package__:
    from . import sync_bdfutbol_team_season as team_sync
else:
    import sync_bdfutbol_team_season as team_sync


STATUS_VALID = "VALID"
STATUS_BLOCKED = "BLOCKED"
STATUS_INVALID = "INVALID_CONTENT"
STATUS_NAVIGATION_ERROR = "NAVIGATION_ERROR"

TRACKING_MODE_LABELS = ("partidos", "tarjetas", "goles", "todo")
_STADIUM_PATH_RE = re.compile(r"^/es/s/(?P<id>\d+)\.html$")


@dataclass(frozen=True, slots=True)
class ResourceSpec:
    name: str
    url: str
    required_markers: tuple[str, ...] = ()
    any_markers: tuple[str, ...] = ()
    optional: bool = False


@dataclass(frozen=True, slots=True)
class ResourceResult:
    name: str
    url: str
    status: str
    snapshot_directory: str | None = None
    http_status: int | None = None
    error: str | None = None
    attempts: int = 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Captura en raw todas las vistas conocidas de un equipo de "
            "BDFutbol: temporada, seguimiento, traspasos, partidos y ficha "
            "histórica del club."
        )
    )
    parser.add_argument("--season", required=True)
    parser.add_argument("--team-id", required=True, type=int)
    parser.add_argument("--competition", default="1rf")
    parser.add_argument("--min-players", type=int, default=15)
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
    return parser.parse_args(argv)


def _dump_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def _slug(value: str) -> str:
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "value"


def build_resource_specs(
    season: str,
    team_id: int,
    competition: str = "1rf",
) -> tuple[ResourceSpec, ...]:
    if not re.fullmatch(r"\d{4}-\d{2}", season):
        raise ValueError("season debe usar formato YYYY-YY")
    if team_id <= 0:
        raise ValueError("team_id debe ser > 0")
    if not re.fullmatch(r"[a-z0-9]+", competition):
        raise ValueError("competition inválida")

    season_base = (
        f"https://www.bdfutbol.com/es/t/t{season}{team_id}.html"
    )
    club_base = f"https://www.bdfutbol.com/es/e/e{team_id}.html"

    return (
        ResourceSpec(
            "season_alignment",
            season_base,
            required_markers=("Entrenador",),
            any_markers=("Titulares", "Jugadores"),
        ),
        ResourceSpec(
            "season_roster",
            f"{season_base}?t=plantilla",
            required_markers=("Entrenador", "Jugadores"),
            any_markers=("Lugar de nacimiento", "Fecha"),
        ),
        ResourceSpec(
            "season_stats",
            f"{season_base}?t=lista",
            required_markers=("Jugadores",),
            any_markers=("PJ", "PT", "Min"),
        ),
        ResourceSpec(
            "season_tracking",
            f"{season_base}?t=seg",
            required_markers=("Completo", "Titular", "Suplente"),
            any_markers=("Convocado", "Amarillas", "Gol"),
        ),
        ResourceSpec(
            "season_transfers",
            f"{season_base}?t=altas",
            required_markers=("Altas", "Bajas"),
            any_markers=("Equipo origen", "Equipo destino"),
        ),
        ResourceSpec(
            "season_matches",
            f"{season_base}?tab=partits",
            required_markers=("Fecha", "Local", "Visitante"),
            any_markers=("Progreso Liga", "Récords", "Jornada"),
        ),
        ResourceSpec(
            "club_profile",
            club_base,
            required_markers=("Nombre completo", "Fundación", "Localidad"),
            any_markers=("Estadio", "Títulos", "Nombres"),
        ),
        ResourceSpec(
            "club_stats",
            f"{club_base}?p=stats",
            required_markers=("Partidos Jugados", "Ganados", "Perdidos"),
            any_markers=("Goles a favor", "Máxima victoria"),
        ),
        ResourceSpec(
            "club_matches",
            f"https://www.bdfutbol.com/es/p/e{team_id}.html",
            required_markers=("Ganados", "Empatados", "Perdidos"),
            any_markers=("Competición", "Temporada", "Resultados"),
        ),
        ResourceSpec(
            "club_coaches_all",
            f"https://www.bdfutbol.com/es/e/eentr{team_id}.html",
            required_markers=("Listado de entrenadores",),
            any_markers=("Apodo y Nombre", "PG", "%PG"),
            optional=True,
        ),
        ResourceSpec(
            "club_goals_discovery",
            f"https://www.bdfutbol.com/es/e/egols{team_id}.html",
            any_markers=("Goles", "Goleadores", "Jugador", "Apodo y Nombre"),
            optional=True,
        ),
        ResourceSpec(
            "club_referees_discovery",
            f"https://www.bdfutbol.com/es/p/er{team_id}.html",
            any_markers=("Árbitro", "Árbitros", "Partidos", "PJ"),
            optional=True,
        ),
        ResourceSpec(
            "club_competition_players",
            (
                f"https://www.bdfutbol.com/es/e/"
                f"e{competition}{team_id}.html"
            ),
            required_markers=("Listado de jugadores",),
            any_markers=("Apodo y Nombre", "Partidos Jugados", "PJ"),
            optional=True,
        ),
        ResourceSpec(
            "club_competition_coaches",
            (
                f"https://www.bdfutbol.com/es/e/"
                f"eentr{competition}{team_id}.html"
            ),
            required_markers=("Listado de entrenadores",),
            any_markers=("Apodo y Nombre", "Ganados", "PG"),
            optional=True,
        ),
    )


def _extract_selects(page: Any) -> list[dict[str, Any]]:
    try:
        return page.locator("select").evaluate_all(
            """selects => selects.map((select, index) => ({
                index,
                id: select.id || null,
                name: select.name || null,
                value: select.value || null,
                onchange: select.getAttribute('onchange'),
                options: Array.from(select.options).map((option, optionIndex) => ({
                    index: optionIndex,
                    text: (option.textContent || '').trim(),
                    value: option.value,
                    selected: option.selected
                }))
            }))"""
        )
    except Exception:
        return []


def _extract_same_team_links(
    page: Any,
    *,
    team_id: int,
    season: str,
) -> list[str]:
    try:
        hrefs = page.locator("a[href]").evaluate_all(
            "nodes => nodes.map(a => a.href).filter(Boolean)"
        )
    except Exception:
        return []

    team_tokens = (
        f"t{season}{team_id}.html",
        f"/e/e{team_id}.html",
        f"/p/e{team_id}.html",
        f"{team_id}.html",
    )
    result: set[str] = set()

    for href in hrefs:
        if not isinstance(href, str):
            continue
        parsed = urlsplit(href)
        if parsed.netloc not in {"www.bdfutbol.com", "bdfutbol.com"}:
            continue
        related_team_url = any(token in href for token in team_tokens)
        stadium_url = _STADIUM_PATH_RE.fullmatch(parsed.path) is not None

        if related_team_url or stadium_url:
            result.add(href)

    return sorted(result)


def _page_text(page: Any) -> str:
    try:
        return page.locator("body").inner_text(timeout=3_000)
    except Exception:
        try:
            return page.content()
        except Exception:
            return ""


def _markers_ok(
    text: str,
    spec: ResourceSpec,
) -> tuple[bool, list[str], bool]:
    folded = text.casefold()
    missing = [
        marker
        for marker in spec.required_markers
        if marker.casefold() not in folded
    ]
    any_ok = (
        True
        if not spec.any_markers
        else any(
            marker.casefold() in folded
            for marker in spec.any_markers
        )
    )
    return not missing and any_ok, missing, any_ok


def _wait_for_resource(
    page: Any,
    *,
    spec: ResourceSpec,
    wait_seconds: float,
) -> tuple[str, PageAssessment, str | None]:
    deadline = time.monotonic() + max(wait_seconds, 0.0)
    last_assessment = assess_page(page)
    last_error: str | None = None

    while True:
        last_assessment = assess_page(page)

        if last_assessment.challenge_visible:
            last_error = "Cloudflare challenge visible"
        elif not url_matches_target(spec.url, page.url):
            last_error = f"URL final distinta: {page.url}"
        elif last_assessment.accessible:
            text = _page_text(page)
            ok, missing, any_ok = _markers_ok(text, spec)
            if ok:
                return STATUS_VALID, last_assessment, None
            last_error = (
                f"Marcadores semánticos incompletos: "
                f"missing={missing} any_markers_ok={any_ok}"
            )
        else:
            last_error = "Página no accesible/estructuralmente incompleta"

        if time.monotonic() >= deadline:
            if last_assessment.challenge_visible:
                return STATUS_BLOCKED, last_assessment, last_error
            return STATUS_INVALID, last_assessment, last_error

        time.sleep(0.4)


def _save_extended_artifacts(
    page: Any,
    output_dir: Path,
    assessment: PageAssessment,
    *,
    metadata: dict[str, Any],
    team_id: int,
    season: str,
) -> None:
    team_sync._save_page_artifacts(
        page,
        output_dir,
        assessment,
        metadata=metadata,
    )
    _dump_json(
        output_dir / "selects.json",
        _extract_selects(page),
    )
    _dump_json(
        output_dir / "same_team_links.json",
        _extract_same_team_links(
            page,
            team_id=team_id,
            season=season,
        ),
    )


def _capture_tracking_modes(
    page: Any,
    *,
    parent_dir: Path,
    team_id: int,
    season: str,
) -> list[dict[str, Any]]:
    """Capture rendered Seguimiento modes if BDFutbol exposes a native select."""

    wanted = set(TRACKING_MODE_LABELS)
    captures: list[dict[str, Any]] = []

    try:
        selects = page.locator("select")
        count = selects.count()
    except Exception:
        return captures

    target_index: int | None = None
    target_options: list[dict[str, str]] = []

    for index in range(count):
        try:
            options = selects.nth(index).locator("option").evaluate_all(
                """opts => opts.map(o => ({
                    text: (o.textContent || '').trim(),
                    value: o.value
                }))"""
            )
        except Exception:
            continue

        labels = {
            str(item.get("text", "")).strip().casefold()
            for item in options
            if isinstance(item, dict)
        }
        if len(wanted & labels) >= 2:
            target_index = index
            target_options = [
                item
                for item in options
                if isinstance(item, dict)
                and str(item.get("text", "")).strip().casefold() in wanted
            ]
            break

    if target_index is None:
        return captures

    selector = selects.nth(target_index)

    for item in target_options:
        label = str(item["text"]).strip()
        value = str(item.get("value", ""))
        mode_dir = parent_dir / f"tracking_mode_{_slug(label)}"

        try:
            if value:
                selector.select_option(value=value)
            else:
                selector.select_option(label=label)
            page.wait_for_timeout(500)
            assessment = assess_page(page)
            _save_extended_artifacts(
                page,
                mode_dir,
                assessment,
                metadata={
                    "phase": "tracking_mode",
                    "mode": label,
                    "selected_value": value,
                    "final_url": page.url,
                    "captured_at_utc": datetime.now(
                        timezone.utc
                    ).isoformat(),
                },
                team_id=team_id,
                season=season,
            )
            captures.append(
                {
                    "mode": label,
                    "value": value,
                    "status": STATUS_VALID,
                    "snapshot_directory": str(mode_dir),
                }
            )
        except Exception as exc:
            captures.append(
                {
                    "mode": label,
                    "value": value,
                    "status": STATUS_INVALID,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    return captures


def _capture_resource(
    *,
    context: Any,
    spec: ResourceSpec,
    args: argparse.Namespace,
    project_root: Path,
    run_dir: Path,
) -> ResourceResult:
    last_status = STATUS_INVALID
    last_error: str | None = None
    last_http: int | None = None

    for attempt in range(1, args.attempts_per_resource + 1):
        page = context.new_page()
        page.set_default_navigation_timeout(args.timeout_ms)
        output_dir = run_dir / spec.name / f"attempt_{attempt:02d}"

        navigation_error: str | None = None
        response_status: int | None = None

        try:
            try:
                response = page.goto(
                    spec.url,
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
                status, assessment, semantic_error = _wait_for_resource(
                    page,
                    spec=spec,
                    wait_seconds=args.resource_wait_seconds,
                )
                error = semantic_error
            else:
                assessment = assess_page(page)
                status = STATUS_NAVIGATION_ERROR
                error = navigation_error

            last_status = status
            last_error = error
            last_http = response_status

            metadata = {
                "resource": spec.name,
                "optional": spec.optional,
                "attempt": attempt,
                "status": status,
                "requested_url": spec.url,
                "final_url": page.url,
                "url_matches_target": url_matches_target(
                    spec.url,
                    page.url,
                ),
                "http_status_diagnostic": response_status,
                "navigation_error": navigation_error,
                "semantic_error": error,
                "captured_at_utc": datetime.now(
                    timezone.utc
                ).isoformat(),
            }

            _save_extended_artifacts(
                page,
                output_dir,
                assessment,
                metadata=metadata,
                team_id=args.team_id,
                season=args.season,
            )

            if status == STATUS_VALID:
                if spec.name == "season_tracking":
                    modes = _capture_tracking_modes(
                        page,
                        parent_dir=output_dir,
                        team_id=args.team_id,
                        season=args.season,
                    )
                    _dump_json(
                        output_dir / "tracking_modes.json",
                        modes,
                    )

                return ResourceResult(
                    name=spec.name,
                    url=spec.url,
                    status=STATUS_VALID,
                    snapshot_directory=(
                        output_dir.relative_to(
                            project_root
                        ).as_posix()
                    ),
                    http_status=response_status,
                    attempts=attempt,
                )
        finally:
            try:
                page.close()
            except Exception:
                pass

        if (
            attempt < args.attempts_per_resource
            and args.retry_delay_seconds > 0
        ):
            time.sleep(args.retry_delay_seconds)

    return ResourceResult(
        name=spec.name,
        url=spec.url,
        status=last_status,
        http_status=last_http,
        error=last_error,
        attempts=args.attempts_per_resource,
    )


def _discover_stadium_specs_from_snapshot(
    snapshot_directory: Path,
) -> tuple[ResourceSpec, ...]:
    """Discover stadium detail pages actually linked from the club profile.

    Stadium IDs are their own provider identity. They MUST NOT be inferred
    from team_id, even when a particular club happens to share the same
    numeric value.
    """

    links = _load_json(snapshot_directory / "links.json", [])
    by_id: dict[int, str] = {}

    for item in links:
        if not isinstance(item, dict):
            continue

        href = item.get("href")
        if not isinstance(href, str) or not href.strip():
            continue

        parsed = urlsplit(href)
        if parsed.netloc.casefold() not in {
            "www.bdfutbol.com",
            "bdfutbol.com",
        }:
            continue

        match = _STADIUM_PATH_RE.fullmatch(parsed.path)
        if not match:
            continue

        stadium_id = int(match.group("id"))
        by_id[stadium_id] = (
            f"https://www.bdfutbol.com/es/s/{stadium_id}.html"
        )

    return tuple(
        ResourceSpec(
            name=f"club_stadium_{stadium_id}",
            url=url,
            required_markers=("Nombre completo", "Aforo", "Localidad"),
            any_markers=("Inauguración", "Dimensiones", "Partidos"),
            optional=True,
        )
        for stadium_id, url in sorted(by_id.items())
    )


def _result_dict(result: ResourceResult) -> dict[str, Any]:
    return {
        "name": result.name,
        "url": result.url,
        "status": result.status,
        "snapshot_directory": result.snapshot_directory,
        "http_status_diagnostic": result.http_status,
        "error": result.error,
        "attempts": result.attempts,
    }


def run(
    args: argparse.Namespace,
    *,
    project_root: Path | None = None,
) -> int:
    project_root = (
        project_root or Path(__file__).resolve().parents[1]
    ).resolve()

    try:
        specs = build_resource_specs(
            args.season,
            args.team_id,
            args.competition,
        )
    except ValueError as exc:
        print(f"Error de configuración: {exc}")
        return 2

    if args.attempts_per_resource < 1:
        print("--attempts-per-resource debe ser >= 1")
        return 2

    base_url, _ = team_sync.build_url_and_snapshot_name(
        args.season,
        args.team_id,
    )

    run_id = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S.%fZ"
    )
    resource_name = (
        f"team_full_{args.season}_{args.team_id}"
    )
    run_dir = (
        project_root
        / "data"
        / "raw"
        / "bdfutbol"
        / resource_name
        / run_id
    )
    run_dir.mkdir(parents=True, exist_ok=False)

    print("=== BDFUTBOL FULL TEAM AUDIT/SYNC ===")
    print(f"Temporada:  {args.season}")
    print(f"team_id:    {args.team_id}")
    print(f"Competición:{args.competition}")
    print(f"Recursos base: {len(specs)}")
    print()

    try:
        runtime = start_browser(
            profile=Path(args.profile),
            preference=args.browser,
            start_url=base_url,
        )
    except BrowserRuntimeError as exc:
        print(f"No se pudo iniciar navegador: {exc}")
        return 3

    results: list[ResourceResult] = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(
                runtime.cdp_url
            )
            if not browser.contexts:
                print("El navegador no expone ningún contexto.")
                return 3

            context = browser.contexts[0]
            preflight_page = team_sync._find_same_origin_page(
                context.pages,
                base_url,
            )

            if preflight_page is None:
                deadline = time.monotonic() + 5.0
                while (
                    time.monotonic() < deadline
                    and preflight_page is None
                ):
                    time.sleep(0.25)
                    preflight_page = (
                        team_sync._find_same_origin_page(
                            context.pages,
                            base_url,
                        )
                    )

            if preflight_page is None:
                print("No apareció ninguna pestaña BDFutbol.")
                return 3

            assessment, preflight_status = (
                team_sync._wait_for_bdfutbol_session(
                    preflight_page,
                    url=base_url,
                    wait_seconds=args.challenge_wait_seconds,
                )
            )
            print(
                f"[preflight] {preflight_status:<18} "
                f"challenge={assessment.challenge_visible} "
                f"links={assessment.link_count}"
            )
            print(f"            final_url={preflight_page.url}")

            if preflight_status != STATUS_VALID:
                return 3

            for index, spec in enumerate(specs, start=1):
                print(
                    f"[{index:02d}/{len(specs):02d}] "
                    f"{spec.name:<26} ... ",
                    end="",
                    flush=True,
                )
                result = _capture_resource(
                    context=context,
                    spec=spec,
                    args=args,
                    project_root=project_root,
                    run_dir=run_dir,
                )
                results.append(result)

                suffix = (
                    f" — {result.error}"
                    if result.error
                    else ""
                )
                optional = " (optional)" if spec.optional else ""
                print(f"{result.status}{optional}{suffix}")

                if (
                    index < len(specs)
                    and args.between_resources_seconds > 0
                ):
                    time.sleep(args.between_resources_seconds)

            # The audit showed that stadium history is linked from the club
            # profile and uses an independent stadium_id. Discover those URLs
            # from the captured profile instead of assuming stadium_id=team_id.
            profile_result = next(
                (
                    result
                    for result in results
                    if result.name == "club_profile"
                    and result.status == STATUS_VALID
                    and result.snapshot_directory is not None
                ),
                None,
            )

            stadium_specs: tuple[ResourceSpec, ...] = ()
            if profile_result is not None:
                profile_snapshot = (
                    project_root / profile_result.snapshot_directory
                )
                stadium_specs = _discover_stadium_specs_from_snapshot(
                    profile_snapshot
                )

            if stadium_specs:
                print(
                    f"Estadios descubiertos desde club_profile: "
                    f"{len(stadium_specs)}"
                )

            for stadium_index, spec in enumerate(
                stadium_specs,
                start=1,
            ):
                print(
                    f"[stadium {stadium_index:02d}/"
                    f"{len(stadium_specs):02d}] "
                    f"{spec.name:<26} ... ",
                    end="",
                    flush=True,
                )
                result = _capture_resource(
                    context=context,
                    spec=spec,
                    args=args,
                    project_root=project_root,
                    run_dir=run_dir,
                )
                results.append(result)

                suffix = (
                    f" — {result.error}"
                    if result.error
                    else ""
                )
                print(f"{result.status} (optional){suffix}")

                if (
                    stadium_index < len(stadium_specs)
                    and args.between_resources_seconds > 0
                ):
                    time.sleep(args.between_resources_seconds)
    finally:
        stop_browser(runtime)

    all_specs = specs + stadium_specs
    required_names = {
        spec.name
        for spec in all_specs
        if not spec.optional
    }
    required_failed = [
        result
        for result in results
        if result.name in required_names
        and result.status != STATUS_VALID
    ]
    optional_names = {
        spec.name
        for spec in all_specs
        if spec.optional
    }
    optional_failed = [
        result
        for result in results
        if result.name in optional_names
        and result.status != STATUS_VALID
    ]

    summary = {
        "source": "bdfutbol",
        "season": args.season,
        "team_id": args.team_id,
        "competition": args.competition,
        "finished_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "static_resources_requested": len(specs),
        "discovered_stadiums": [
            {
                "name": spec.name,
                "url": spec.url,
            }
            for spec in stadium_specs
        ],
        "resources_requested": len(all_specs),
        "resources_valid": sum(
            result.status == STATUS_VALID
            for result in results
        ),
        "required_failed": len(required_failed),
        "optional_failed": len(optional_failed),
        "resources": [
            _result_dict(result)
            for result in results
        ],
    }
    _dump_json(run_dir / "summary.json", summary)

    print("\n=== FULL TEAM CAPTURE COMPLETADO ===")
    print(
        f"Recursos base:     "
        f"{summary['static_resources_requested']}"
    )
    print(
        f"Estadios extra:    "
        f"{len(summary['discovered_stadiums'])}"
    )
    print(f"Recursos totales:  {summary['resources_requested']}")
    print(f"Válidos:           {summary['resources_valid']}")
    print(f"Required fallidos: {summary['required_failed']}")
    print(f"Optional fallidos: {summary['optional_failed']}")
    print(f"Resumen:           {run_dir / 'summary.json'}")

    return 0 if not required_failed else 1


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
