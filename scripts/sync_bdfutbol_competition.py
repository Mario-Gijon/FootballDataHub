#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from football_data_hub.bdfutbol import parse_competition
from football_data_hub.bdfutbol.browser import (
    BrowserRuntimeError,
    start_browser,
    stop_browser,
)
from football_data_hub.bdfutbol.cli import _print_standings
from football_data_hub.bdfutbol.validation import (
    PageAssessment,
    assess_page,
    url_matches_target,
    urls_share_origin,
)


STATUS_VALID = "VALID"
STATUS_BLOCKED = "BLOCKED"
STATUS_INVALID = "INVALID_CONTENT"
STATUS_NAVIGATION_ERROR = "NAVIGATION_ERROR"
STATUS_BROWSER_ERROR = "BROWSER_ERROR"


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
        description=(
            "Sincroniza una competición de BDFutbol con una sesión de navegador "
            "real y valida el recurso usando el propio CompetitionParser."
        )
    )
    parser.add_argument("--season", required=True)
    parser.add_argument("--group", required=True, type=int, choices=(1, 2))
    parser.add_argument("--competition", default="1rf")
    parser.add_argument("--expect-teams", type=int, default=20)
    parser.add_argument("--expect-fixtures", type=int, default=380)
    parser.add_argument("--browser-sessions", type=int, default=3)
    parser.add_argument("--target-attempts-per-session", type=int, default=2)
    parser.add_argument("--challenge-wait-seconds", type=float, default=12.0)
    parser.add_argument("--resource-wait-seconds", type=float, default=20.0)
    parser.add_argument("--retry-delay-seconds", type=float, default=1.5)
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
    parser.add_argument("--show-standings", action="store_true")
    return parser.parse_args(argv)


def _dump_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _extract_links(page: Any) -> list[dict[str, Any]]:
    try:
        return page.locator("a").evaluate_all(
            """nodes => nodes.map((a, index) => ({
                index,
                text: (a.innerText || a.textContent || '').trim(),
                href: a.href || null,
                href_raw: a.getAttribute('href'),
                title: a.getAttribute('title')
            }))"""
        )
    except Exception:
        return []


def _extract_images(page: Any) -> list[dict[str, Any]]:
    try:
        return page.locator("img").evaluate_all(
            """nodes => nodes.map((img, index) => ({
                index,
                src: img.currentSrc || img.src || null,
                src_raw: img.getAttribute('src'),
                alt: img.getAttribute('alt'),
                title: img.getAttribute('title'),
                width: img.naturalWidth || null,
                height: img.naturalHeight || null
            }))"""
        )
    except Exception:
        return []


def _extract_tables(page: Any) -> list[dict[str, Any]]:
    try:
        return page.locator("table").evaluate_all(
            """tables => tables.map((table, tableIndex) => ({
                index: tableIndex,
                id: table.id || null,
                class_name: table.className || null,
                rows: Array.from(table.querySelectorAll('tr')).map((tr, rowIndex) => ({
                    row_index: rowIndex,
                    cells: Array.from(tr.querySelectorAll('th,td')).map(cell => ({
                        tag: cell.tagName.toLowerCase(),
                        text: (cell.innerText || cell.textContent || '').trim(),
                        html: cell.innerHTML,
                        colspan: cell.getAttribute('colspan'),
                        rowspan: cell.getAttribute('rowspan')
                    }))
                }))
            }))"""
        )
    except Exception:
        return []


def _save_page_artifacts(
    page: Any,
    output_dir: Path,
    assessment: PageAssessment,
    *,
    metadata: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        html = page.content()
    except Exception:
        html = ""

    (output_dir / "page.html").write_text(html, encoding="utf-8")
    _dump_json(output_dir / "links.json", _extract_links(page))
    _dump_json(output_dir / "images.json", _extract_images(page))
    _dump_json(output_dir / "tables.json", _extract_tables(page))
    _dump_json(output_dir / "assessment.json", assessment.as_dict())
    _dump_json(output_dir / "metadata.json", metadata)

    try:
        page.screenshot(
            path=str(output_dir / "screenshot.png"),
            full_page=True,
        )
    except Exception as exc:
        _dump_json(
            output_dir / "screenshot_error.json",
            {"error": f"{type(exc).__name__}: {exc}"},
        )


def _find_same_origin_page(pages: list[Any], url: str) -> Any | None:
    exact = None
    accessible_candidate = None
    fallback = None

    for page in pages:
        try:
            page_url = page.url
        except Exception:
            continue

        if not urls_share_origin(url, page_url):
            continue

        if fallback is None:
            fallback = page

        if url_matches_target(url, page_url):
            exact = page
            break

        try:
            assessment = assess_page(page)
        except Exception:
            assessment = None

        if (
            assessment is not None
            and assessment.accessible
            and not assessment.challenge_visible
            and accessible_candidate is None
        ):
            accessible_candidate = page

    return exact or accessible_candidate or fallback


def _competition_from_page(
    page: Any,
    *,
    url: str,
    expected_team_count: int,
    expected_fixture_count: int,
) -> tuple[Any | None, str | None]:
    try:
        html = page.content()
    except Exception as exc:
        return None, f"page.content: {type(exc).__name__}: {exc}"

    try:
        snapshot = parse_competition(
            html,
            url,
            expected_team_count=expected_team_count,
            expected_fixture_count=expected_fixture_count,
        )
    except (ValueError, OSError, UnicodeError) as exc:
        return None, str(exc)

    return snapshot, None


def _wait_for_bdfutbol_session(
    page: Any,
    *,
    url: str,
    wait_seconds: float,
) -> tuple[PageAssessment, str]:
    """Espera a que la verificación pasiva desaparezca.

    Aquí NO exigimos todavía el recurso de competición. Solo necesitamos que
    alguna pestaña del mismo origen sea una página BDFutbol real para conservar
    la misma sesión/cookies y abrir después una pestaña nueva al target exacto.
    """
    deadline = time.monotonic() + max(wait_seconds, 0.0)
    last_assessment = assess_page(page)

    while True:
        last_assessment = assess_page(page)

        if (
            last_assessment.accessible
            and not last_assessment.challenge_visible
            and urls_share_origin(url, page.url)
        ):
            return last_assessment, STATUS_VALID

        if time.monotonic() >= deadline:
            if last_assessment.challenge_visible:
                return last_assessment, STATUS_BLOCKED
            return last_assessment, STATUS_INVALID

        time.sleep(0.5)


def _wait_for_competition_resource(
    page: Any,
    *,
    url: str,
    expected_team_count: int,
    expected_fixture_count: int,
    wait_seconds: float,
) -> tuple[str, PageAssessment, Any | None, str | None]:
    """No considera VALID una URL correcta que siga mostrando la home.

    El criterio definitivo de disponibilidad del recurso es que el propio
    CompetitionParser pueda leer 20 equipos/380 fixtures (o los counts pedidos).
    """
    deadline = time.monotonic() + max(wait_seconds, 0.0)
    last_error: str | None = None
    last_assessment = assess_page(page)

    while True:
        last_assessment = assess_page(page)

        if last_assessment.challenge_visible:
            last_error = "Cloudflare challenge visible"
        elif not url_matches_target(url, page.url):
            last_error = f"URL final distinta: {page.url}"
        elif last_assessment.accessible:
            snapshot, parse_error = _competition_from_page(
                page,
                url=url,
                expected_team_count=expected_team_count,
                expected_fixture_count=expected_fixture_count,
            )
            if snapshot is not None:
                return STATUS_VALID, last_assessment, snapshot, None
            last_error = parse_error
        else:
            last_error = "Página BDFutbol no accesible/estructuralmente incompleta"

        if time.monotonic() >= deadline:
            if last_assessment.challenge_visible:
                return STATUS_BLOCKED, last_assessment, None, last_error
            return STATUS_INVALID, last_assessment, None, last_error

        time.sleep(0.5)


def _write_latest_valid(
    *,
    project_root: Path,
    base_dir: Path,
    run_dir: Path,
    snapshot_dir: Path,
    url: str,
) -> None:
    relative_run = run_dir.relative_to(project_root).as_posix()
    relative_snapshot = snapshot_dir.relative_to(project_root).as_posix()

    _dump_json(
        base_dir / "latest_valid.json",
        {
            "source": "bdfutbol",
            "url": url,
            "status": STATUS_VALID,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "run_directory": relative_run,
            "snapshot_directory": relative_snapshot,
            "page_html": f"{relative_snapshot}/page.html",
        },
    )


def _session_attempt(
    *,
    args: argparse.Namespace,
    project_root: Path,
    url: str,
    session_dir: Path,
    session_number: int,
) -> tuple[str, Any | None, Path | None, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []

    try:
        runtime = start_browser(
            profile=Path(args.profile),
            preference=args.browser,
            start_url=url,
        )
    except BrowserRuntimeError as exc:
        events.append(
            {
                "phase": "browser_start",
                "status": STATUS_BROWSER_ERROR,
                "error": str(exc),
            }
        )
        return STATUS_BROWSER_ERROR, None, None, events

    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(runtime.cdp_url)
            except PlaywrightError as exc:
                events.append(
                    {
                        "phase": "cdp_connect",
                        "status": STATUS_BROWSER_ERROR,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                return STATUS_BROWSER_ERROR, None, None, events

            contexts = browser.contexts
            if not contexts:
                events.append(
                    {
                        "phase": "context",
                        "status": STATUS_BROWSER_ERROR,
                        "error": "El navegador no expone ningún contexto.",
                    }
                )
                return STATUS_BROWSER_ERROR, None, None, events

            context = contexts[0]

            preflight_page = _find_same_origin_page(context.pages, url)
            if preflight_page is None:
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline and preflight_page is None:
                    time.sleep(0.25)
                    preflight_page = _find_same_origin_page(context.pages, url)

            if preflight_page is None:
                events.append(
                    {
                        "phase": "preflight",
                        "status": STATUS_INVALID,
                        "error": "No apareció ninguna pestaña de BDFutbol.",
                    }
                )
                return STATUS_INVALID, None, None, events

            preflight_assessment, preflight_status = _wait_for_bdfutbol_session(
                preflight_page,
                url=url,
                wait_seconds=args.challenge_wait_seconds,
            )

            preflight_dir = session_dir / "preflight"
            _save_page_artifacts(
                preflight_page,
                preflight_dir,
                preflight_assessment,
                metadata={
                    "phase": "preflight",
                    "session": session_number,
                    "status": preflight_status,
                    "requested_url": url,
                    "final_url": preflight_page.url,
                    "url_matches_target": url_matches_target(url, preflight_page.url),
                    "browser_binary": runtime.browser_path,
                    "profile": str(runtime.profile),
                    "using_xvfb": runtime.using_xvfb,
                    "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                },
            )
            events.append(
                {
                    "phase": "preflight",
                    "status": preflight_status,
                    "final_url": preflight_page.url,
                    "challenge": preflight_assessment.challenge_visible,
                    "links": preflight_assessment.link_count,
                }
            )

            if preflight_status != STATUS_VALID:
                return preflight_status, None, None, events

            # Cloudflare ya ha dejado una sesión BDFutbol utilizable. A partir de
            # aquí SIEMPRE usamos una pestaña NUEVA dentro del mismo context.
            # Así no dependemos del estado/ruta de la pestaña que pasó el challenge.
            last_status = STATUS_INVALID

            for target_number in range(1, args.target_attempts_per_session + 1):
                target_dir = session_dir / f"target_{target_number:02d}"
                target_page = context.new_page()
                target_page.set_default_navigation_timeout(args.timeout_ms)

                navigation_error = None
                response_status = None
                try:
                    response = target_page.goto(
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
                    target_page.wait_for_timeout(args.settle_ms)

                if navigation_error is None:
                    (
                        target_status,
                        target_assessment,
                        snapshot,
                        resource_error,
                    ) = _wait_for_competition_resource(
                        target_page,
                        url=url,
                        expected_team_count=args.expect_teams,
                        expected_fixture_count=args.expect_fixtures,
                        wait_seconds=args.resource_wait_seconds,
                    )
                else:
                    target_assessment = assess_page(target_page)
                    snapshot = None
                    resource_error = navigation_error
                    target_status = STATUS_NAVIGATION_ERROR

                last_status = target_status

                _save_page_artifacts(
                    target_page,
                    target_dir,
                    target_assessment,
                    metadata={
                        "phase": "target",
                        "session": session_number,
                        "target_attempt": target_number,
                        "status": target_status,
                        "requested_url": url,
                        "final_url": target_page.url,
                        "url_matches_target": url_matches_target(url, target_page.url),
                        "http_status_diagnostic": response_status,
                        "navigation_error": navigation_error,
                        "resource_error": resource_error,
                        "browser_binary": runtime.browser_path,
                        "profile": str(runtime.profile),
                        "using_xvfb": runtime.using_xvfb,
                        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                    },
                )
                events.append(
                    {
                        "phase": "target",
                        "target_attempt": target_number,
                        "status": target_status,
                        "http": response_status,
                        "final_url": target_page.url,
                        "url_matches_target": url_matches_target(url, target_page.url),
                        "challenge": target_assessment.challenge_visible,
                        "links": target_assessment.link_count,
                        "resource_error": resource_error,
                    }
                )

                if target_status == STATUS_VALID and snapshot is not None:
                    return STATUS_VALID, snapshot, target_dir, events

                try:
                    target_page.close()
                except Exception:
                    pass

            return last_status, None, None, events
    finally:
        stop_browser(runtime)


def _print_events(events: list[dict[str, Any]]) -> None:
    for event in events:
        phase = event.get("phase", "?")
        status = event.get("status", "?")
        if phase == "target":
            prefix = f"[target {event.get('target_attempt', '?')}]"
        else:
            prefix = f"[{phase}]"

        detail = ""
        if event.get("http") is not None:
            detail += f" http={event['http']}"
        if event.get("challenge") is not None:
            detail += f" challenge={event['challenge']}"
        if event.get("links") is not None:
            detail += f" links={event['links']}"
        if event.get("url_matches_target") is not None:
            detail += f" url_matches_target={event['url_matches_target']}"

        print(f"{prefix:<12} {status:<18}{detail}")
        if event.get("final_url"):
            print(f"             final_url={event['final_url']}")
        if event.get("resource_error"):
            print(f"             resource_error={event['resource_error']}")
        if event.get("error"):
            print(f"             error={event['error']}")


def run_sync(
    args: argparse.Namespace,
    *,
    project_root: Path | None = None,
) -> int:
    project_root = (
        project_root or Path(__file__).resolve().parents[1]
    ).resolve()

    try:
        url, snapshot_name = build_url_and_snapshot_name(
            args.season,
            args.competition,
            args.group,
        )
    except ValueError as exc:
        print(f"Error de configuración: {exc}")
        return 2

    if args.browser_sessions < 1:
        print("--browser-sessions debe ser >= 1")
        return 2
    if args.target_attempts_per_session < 1:
        print("--target-attempts-per-session debe ser >= 1")
        return 2

    base_dir = project_root / "data" / "raw" / "bdfutbol" / snapshot_name
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = base_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    print("=== BDFUTBOL COMPETITION SYNC V2 ===")
    print(f"Competición: {args.competition}")
    print(f"Temporada:   {args.season}")
    print(f"Grupo:       {args.group}")
    print(f"URL:         {url}")
    print(f"Snapshot:    {snapshot_name}")
    print(
        "Criterio VALID: URL exacta + página BDFutbol + "
        f"{args.expect_teams} equipos + {args.expect_fixtures} partidos"
    )
    print()

    all_events: list[dict[str, Any]] = []
    final_status = STATUS_INVALID
    final_snapshot = None
    valid_snapshot_dir: Path | None = None

    for session_number in range(1, args.browser_sessions + 1):
        print(f"--- Browser session {session_number}/{args.browser_sessions} ---")
        session_dir = run_dir / f"session_{session_number:02d}"
        session_dir.mkdir(parents=True, exist_ok=False)

        (
            session_status,
            snapshot,
            snapshot_dir,
            events,
        ) = _session_attempt(
            args=args,
            project_root=project_root,
            url=url,
            session_dir=session_dir,
            session_number=session_number,
        )
        _print_events(events)
        all_events.extend(
            {"session": session_number, **event}
            for event in events
        )
        final_status = session_status

        if session_status == STATUS_VALID and snapshot is not None and snapshot_dir:
            final_snapshot = snapshot
            valid_snapshot_dir = snapshot_dir
            _write_latest_valid(
                project_root=project_root,
                base_dir=base_dir,
                run_dir=run_dir,
                snapshot_dir=snapshot_dir,
                url=url,
            )
            break

        if session_number < args.browser_sessions and args.retry_delay_seconds > 0:
            time.sleep(args.retry_delay_seconds)
        print()

    _dump_json(
        run_dir / "run_summary.json",
        {
            "source": "bdfutbol",
            "name": snapshot_name,
            "url": url,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": final_status,
            "valid_snapshot_directory": (
                valid_snapshot_dir.relative_to(project_root).as_posix()
                if valid_snapshot_dir is not None
                else None
            ),
            "events": all_events,
        },
    )

    if final_status != STATUS_VALID or final_snapshot is None or valid_snapshot_dir is None:
        print()
        print(f"Estado final: {final_status}")
        print(f"Run:          {_display_path(run_dir, project_root)}")
        print(
            "No se ha actualizado latest_valid porque el CompetitionParser "
            "no llegó a aceptar el recurso."
        )
        return 3 if final_status == STATUS_BLOCKED else 2

    played = sum(fixture.played for fixture in final_snapshot.fixtures)
    pending = len(final_snapshot.fixtures) - played

    print("\n=== SYNC COMPLETADO ===")
    print(f"Competición:  {final_snapshot.context.competition_code}")
    print(f"Temporada:    {final_snapshot.context.season}")
    print(f"Grupo:        {final_snapshot.context.group}")
    print(f"Equipos:      {len(final_snapshot.standings)}")
    print(f"Partidos:     {len(final_snapshot.fixtures)}")
    print(f"Disputados:   {played}")
    print(f"Pendientes:   {pending}")
    print(f"Snapshot:     {_display_path(valid_snapshot_dir, project_root)}")

    if final_snapshot.warnings:
        print("\nWarnings:")
        for warning in final_snapshot.warnings:
            print(f"  - {warning}")

    if args.show_standings:
        _print_standings(final_snapshot.standings)

    return 0


def main(argv: list[str] | None = None) -> int:
    return run_sync(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
