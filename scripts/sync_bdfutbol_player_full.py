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

from bs4 import BeautifulSoup, Tag
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
)

if __package__:
    from . import sync_bdfutbol_team_season as team_sync
else:
    import sync_bdfutbol_team_season as team_sync


STATUS_VALID = "VALID"
STATUS_BLOCKED = "BLOCKED"
STATUS_INVALID = "INVALID_CONTENT"
STATUS_NAVIGATION_ERROR = "NAVIGATION_ERROR"
STATUS_EMPTY = "EMPTY"

_PLAYER_PROFILE_RE = re.compile(r"^/es/j/j(?P<id>\d+)\.html$")
_PLAYER_MATCHES_RE = re.compile(r"^/es/p/j(?P<id>\d+)\.html$")
_PHOTO_BUTTON_RE = re.compile(r"^Fotos\s*\((?P<count>\d+)\)\s*$", re.I)


@dataclass(frozen=True, slots=True)
class ResourceSpec:
    name: str
    url: str
    required_markers: tuple[str, ...] = ()
    any_markers: tuple[str, ...] = ()
    optional: bool = False
    provenance: str = "bdfutbol"
    required_table_id: str | None = None
    min_table_rows: int | None = None
    scope: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ResourceResult:
    name: str
    url: str
    status: str
    snapshot_directory: str | None = None
    http_status: int | None = None
    error: str | None = None
    attempts: int = 0
    provenance: str = "bdfutbol"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Captura raw de todas las vistas conocidas de un jugador de "
            "BDFutbol antes de diseñar el parser normalizado."
        )
    )
    parser.add_argument("--player-id", required=True, type=int)
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


def build_resource_specs(player_id: int) -> tuple[ResourceSpec, ...]:
    if player_id <= 0:
        raise ValueError("player_id debe ser > 0")

    profile = f"https://www.bdfutbol.com/es/j/j{player_id}.html"
    matches = f"https://www.bdfutbol.com/es/p/j{player_id}.html"

    # manager=1 is BDFutbol's community/manager layer. It can expose extra
    # lower-category/youth history not present in the public canonical view.
    # We preserve it separately and never silently merge provenance later.
    return (
        ResourceSpec(
            "player_profile",
            profile,
            required_markers=(
                "Nombre completo",
                "Fecha de nacimiento",
                "Demarcación",
            ),
            any_markers=(
                "Lugar de nacimiento",
                "Altura",
                "Partidos Jugados",
            ),
        ),
        ResourceSpec(
            "player_stats",
            f"{profile}?p=stats",
            required_markers=("Partidos Jugados",),
            any_markers=(
                "Competiciones",
                "Equipos",
                "Temporadas",
            ),
        ),
        ResourceSpec(
            "player_matches",
            matches,
            required_markers=("Ganados", "Empatados", "Perdidos"),
            any_markers=(
                "Partidos jugados",
                "Competición",
                "Temporadas",
            ),
        ),
        ResourceSpec(
            "player_profile_manager",
            f"{profile}?manager=1",
            required_markers=("Nombre completo", "Demarcación"),
            any_markers=("Temporada", "Equipo", "Partidos Jugados"),
            optional=True,
            provenance="bdfutbol_manager",
        ),
        ResourceSpec(
            "player_stats_manager",
            f"{profile}?p=stats&manager=1",
            required_markers=("Partidos Jugados",),
            any_markers=("Competiciones", "Equipos", "Temporadas"),
            optional=True,
            provenance="bdfutbol_manager",
        ),
        ResourceSpec(
            "player_matches_manager",
            f"{matches}?manager=1",
            required_markers=("Ganados", "Empatados", "Perdidos"),
            any_markers=("Partidos jugados", "Competición", "Temporadas"),
            optional=True,
            provenance="bdfutbol_manager",
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


def _extract_forms(page: Any) -> list[dict[str, Any]]:
    try:
        return page.locator("form").evaluate_all(
            """forms => forms.map((form, index) => ({
                index,
                id: form.id || null,
                action: form.action || null,
                method: (form.method || 'get').toLowerCase(),
                controls: Array.from(
                    form.querySelectorAll('input, select, button, textarea')
                ).map((node, controlIndex) => ({
                    index: controlIndex,
                    tag: node.tagName.toLowerCase(),
                    type: node.getAttribute('type'),
                    id: node.id || null,
                    name: node.getAttribute('name'),
                    value: node.value ?? null,
                    text: (node.textContent || '').trim(),
                    checked: 'checked' in node ? Boolean(node.checked) : null
                }))
            }))"""
        )
    except Exception:
        return []


def _canonical_player_link(url: str, player_id: int) -> str | None:
    parsed = urlsplit(url)
    if parsed.netloc.casefold() not in {"www.bdfutbol.com", "bdfutbol.com"}:
        return None

    match = _PLAYER_PROFILE_RE.fullmatch(parsed.path)
    if match and int(match.group("id")) == player_id:
        allowed = {
            key: value
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key in {"p", "manager"}
        }
        return urlunsplit(
            ("https", "www.bdfutbol.com", parsed.path, urlencode(allowed), "")
        )

    match = _PLAYER_MATCHES_RE.fullmatch(parsed.path)
    if match and int(match.group("id")) == player_id:
        # Match-page filters (temp/rival/team/result/etc.) are data views of
        # the same complete table. Only keep the unfiltered route and manager
        # provenance toggle for discovery; filters are preserved in selects/forms.
        allowed = {
            key: value
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key == "manager"
        }
        return urlunsplit(
            ("https", "www.bdfutbol.com", parsed.path, urlencode(allowed), "")
        )

    return None


def _extract_same_player_links(
    page: Any,
    *,
    player_id: int,
) -> list[str]:
    try:
        hrefs = page.locator("a[href]").evaluate_all(
            "nodes => nodes.map(a => a.href).filter(Boolean)"
        )
    except Exception:
        return []

    result: set[str] = set()
    for href in hrefs:
        if not isinstance(href, str):
            continue
        canonical = _canonical_player_link(href, player_id)
        if canonical:
            result.add(canonical)

    return sorted(result)



def _safe_resource_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    token = token.strip("._-")
    return token or "unknown"



def _with_manager_context(url: str) -> str:
    """Preserve the manager data context when following a link from it.

    BDFutbol renders season links inside ?manager=1 pages without repeating
    manager=1 in each href. Direct navigation to that bare href falls back to
    the canonical dataset, so manager-only seasons disappear. Re-attach the
    context flag explicitly while preserving every query parameter emitted by
    BDFutbol.
    """
    parsed = urlsplit(url)
    query_items = list(parse_qsl(parsed.query, keep_blank_values=True))

    if not any(key == "manager" for key, _ in query_items):
        query_items.append(("manager", "1"))

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query_items),
            parsed.fragment,
        )
    )

def _extract_season_match_specs_from_html(
    html: str,
    *,
    player_id: int,
    provenance: str,
    optional: bool,
) -> list[ResourceSpec]:
    """Discover exact season-match URLs from BDFutbol's rendered t1 table.

    We reuse the href emitted by BDFutbol. For manager provenance we only
    re-attach manager=1, because BDFutbol omits that context flag from the
    rendered season href even though the row belongs to the manager dataset.
    The unfiltered player-matches page has an empty tpartits body, while the t1
    season rows link to the filtered views that render the match-by-match list.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="t1")
    if not isinstance(table, Tag):
        return []

    result: list[ResourceSpec] = []
    seen: set[str] = set()

    for row in table.find_all("tr"):
        if not isinstance(row, Tag):
            continue

        cells = row.find_all(["th", "td"], recursive=False)
        if not cells:
            cells = row.find_all(["th", "td"])
        if not cells:
            continue

        season = " ".join(cells[0].get_text(" ", strip=True).split())
        if not re.fullmatch(r"\d{4}-\d{2}", season):
            continue

        href: str | None = None
        for cell in cells[:2]:
            if not isinstance(cell, Tag):
                continue
            anchor = cell.find("a", href=True)
            if isinstance(anchor, Tag):
                candidate = anchor.get("href")
                if isinstance(candidate, str):
                    href = candidate
                    break

        if not href:
            continue

        if href.startswith("/"):
            href = f"https://www.bdfutbol.com{href}"
        elif href.startswith("../"):
            href = (
                "https://www.bdfutbol.com/es/"
                + href.removeprefix("../")
            )

        parsed = urlsplit(href)
        if parsed.netloc.casefold() not in {
            "www.bdfutbol.com",
            "bdfutbol.com",
        }:
            continue
        if parsed.path != f"/es/p/j{player_id}.html":
            continue

        query = dict(
            parse_qsl(parsed.query, keep_blank_values=True)
        )
        if query.get("temp") != season:
            continue

        if provenance == "bdfutbol_manager":
            href = _with_manager_context(href)

        if season in seen:
            continue
        seen.add(season)

        result.append(
            ResourceSpec(
                name=(
                    "player_matches_season_"
                    + _safe_resource_token(season)
                ),
                url=href,
                required_markers=(season,),
                any_markers=(
                    "Fecha",
                    "Local",
                    "Visitante",
                    "Partidos",
                ),
                optional=optional,
                provenance=provenance,
                required_table_id="tpartits",
                min_table_rows=2,
                scope={
                    "season": season,
                    "source_table": "t1",
                },
            )
        )

    return result


def build_season_match_specs(
    *,
    player_id: int,
    canonical_html: str | None,
    manager_html: str | None,
) -> tuple[ResourceSpec, ...]:
    """Build a canonical-first superset of exact per-season match views."""
    if player_id <= 0:
        raise ValueError("player_id debe ser > 0")

    canonical = _extract_season_match_specs_from_html(
        canonical_html or "",
        player_id=player_id,
        provenance="bdfutbol",
        optional=False,
    )
    manager = _extract_season_match_specs_from_html(
        manager_html or "",
        player_id=player_id,
        provenance="bdfutbol_manager",
        optional=True,
    )

    by_season: dict[str, ResourceSpec] = {}
    for spec in canonical:
        season = str((spec.scope or {}).get("season") or "")
        if season:
            by_season[season] = spec

    for spec in manager:
        season = str((spec.scope or {}).get("season") or "")
        if season and season not in by_season:
            by_season[season] = spec

    return tuple(
        by_season[season]
        for season in sorted(by_season, reverse=True)
    )


def _read_snapshot_html(
    *,
    project_root: Path,
    result: ResourceResult | None,
) -> str | None:
    if result is None or not result.snapshot_directory:
        return None

    page_path = (
        project_root
        / result.snapshot_directory
        / "page.html"
    )
    try:
        return page_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _table_row_requirement_ok(
    page: Any,
    spec: ResourceSpec,
) -> tuple[bool, str | None]:
    if not spec.required_table_id:
        return True, None

    minimum = spec.min_table_rows or 1
    try:
        count = page.locator(
            f"table#{spec.required_table_id} tr"
        ).count()
    except Exception as exc:
        return (
            False,
            "No se pudo inspeccionar "
            f"table#{spec.required_table_id}: "
            f"{type(exc).__name__}: {exc}",
        )

    if count < minimum:
        return (
            False,
            f"table#{spec.required_table_id} tiene "
            f"{count} filas; se requieren >= {minimum}",
        )

    return True, None

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
            table_ok, table_error = _table_row_requirement_ok(
                page,
                spec,
            )
            if ok and table_ok:
                return STATUS_VALID, last_assessment, None

            errors: list[str] = []
            if not ok:
                errors.append(
                    "Marcadores semánticos incompletos: "
                    f"missing={missing} "
                    f"any_markers_ok={any_ok}"
                )
            if not table_ok and table_error:
                errors.append(table_error)
            last_error = " | ".join(errors)
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
    player_id: int,
) -> None:
    team_sync._save_page_artifacts(
        page,
        output_dir,
        assessment,
        metadata=metadata,
    )
    _dump_json(output_dir / "selects.json", _extract_selects(page))
    _dump_json(output_dir / "forms.json", _extract_forms(page))
    _dump_json(
        output_dir / "same_player_links.json",
        _extract_same_player_links(page, player_id=player_id),
    )


def _photo_gallery_state(page: Any) -> tuple[int | None, int | None]:
    """Return (element_index, declared_photo_count) for the Fotos (N) control."""
    try:
        controls = page.locator("button, a")
        texts = controls.all_inner_texts()
    except Exception:
        return None, None

    for index, raw in enumerate(texts):
        text = " ".join(str(raw).split())
        match = _PHOTO_BUTTON_RE.fullmatch(text)
        if match:
            return index, int(match.group("count"))

    return None, None


def _capture_photo_gallery(
    page: Any,
    *,
    output_dir: Path,
    player_id: int,
) -> dict[str, Any]:
    index, count = _photo_gallery_state(page)

    state: dict[str, Any] = {
        "declared_count": count,
        "control_found": index is not None,
        "status": STATUS_EMPTY if count == 0 else None,
    }

    if index is None:
        state["status"] = "NOT_FOUND"
        return state

    if count == 0:
        return state

    try:
        page.locator("button, a").nth(index).click()
        page.wait_for_timeout(700)
        assessment = assess_page(page)
        gallery_dir = output_dir / "photo_gallery"
        _save_extended_artifacts(
            page,
            gallery_dir,
            assessment,
            metadata={
                "resource": "player_photo_gallery",
                "player_id": player_id,
                "declared_count": count,
                "status": STATUS_VALID,
                "final_url": page.url,
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            },
            player_id=player_id,
        )
        state["status"] = STATUS_VALID
        state["snapshot_directory"] = str(gallery_dir)
    except Exception as exc:
        state["status"] = STATUS_INVALID
        state["error"] = f"{type(exc).__name__}: {exc}"

    return state


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
                "player_id": args.player_id,
                "provenance": spec.provenance,
                "optional": spec.optional,
                "scope": spec.scope,
                "attempt": attempt,
                "status": status,
                "requested_url": spec.url,
                "final_url": page.url,
                "url_matches_target": url_matches_target(spec.url, page.url),
                "http_status_diagnostic": response_status,
                "navigation_error": navigation_error,
                "semantic_error": error,
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            }

            _save_extended_artifacts(
                page,
                output_dir,
                assessment,
                metadata=metadata,
                player_id=args.player_id,
            )

            if status == STATUS_VALID:
                if spec.name == "player_profile":
                    gallery = _capture_photo_gallery(
                        page,
                        output_dir=output_dir,
                        player_id=args.player_id,
                    )
                    _dump_json(
                        output_dir / "photo_gallery.json",
                        gallery,
                    )

                return ResourceResult(
                    name=spec.name,
                    url=spec.url,
                    status=STATUS_VALID,
                    snapshot_directory=(
                        output_dir.relative_to(project_root).as_posix()
                    ),
                    http_status=response_status,
                    attempts=attempt,
                    provenance=spec.provenance,
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
        provenance=spec.provenance,
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
        "provenance": result.provenance,
    }


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def _write_latest_valid(
    *,
    root: Path,
    run_dir: Path,
    summary_path: Path,
) -> None:
    _dump_json(
        root / "latest_valid.json",
        {
            "run_directory": str(run_dir),
            "summary": str(summary_path),
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )


def run_sync(
    args: argparse.Namespace,
    *,
    project_root: Path | None = None,
) -> int:
    project_root = (
        project_root
        if project_root is not None
        else Path(__file__).resolve().parents[1]
    )

    if args.player_id <= 0:
        print("Error: --player-id debe ser > 0")
        return 2
    if args.attempts_per_resource < 1:
        print("Error: --attempts-per-resource debe ser >= 1")
        return 2

    specs = build_resource_specs(args.player_id)
    profile_url = specs[0].url

    raw_root = (
        project_root
        / "data"
        / "raw"
        / "bdfutbol"
        / f"player_full_{args.player_id}"
    )
    run_dir = raw_root / _run_id()
    run_dir.mkdir(parents=True, exist_ok=True)

    print("=== BDFUTBOL PLAYER FULL DISCOVERY ===")
    print(f"player_id:      {args.player_id}")
    print(f"Recursos base:  {len(specs)}")

    try:
        runtime = start_browser(
            profile=Path(args.profile),
            preference=args.browser,
            start_url=profile_url,
        )
    except BrowserRuntimeError as exc:
        print(f"No se pudo iniciar navegador: {exc}")
        return 3

    results: list[ResourceResult] = []
    season_specs: tuple[ResourceSpec, ...] = ()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(runtime.cdp_url)
            if not browser.contexts:
                print("El navegador no expone ningún contexto.")
                return 3

            context = browser.contexts[0]
            preflight_page = team_sync._find_same_origin_page(
                context.pages,
                profile_url,
            )

            deadline = time.monotonic() + 5.0
            while (
                preflight_page is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.25)
                preflight_page = team_sync._find_same_origin_page(
                    context.pages,
                    profile_url,
                )

            if preflight_page is None:
                print("No apareció ninguna pestaña BDFutbol.")
                return 3

            assessment, preflight_status = (
                team_sync._wait_for_bdfutbol_session(
                    preflight_page,
                    url=profile_url,
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
                print(
                    "La sesión persistente no está válida. "
                    "No se continuará."
                )
                return 3

            for index, spec in enumerate(specs, start=1):
                suffix = " (optional)" if spec.optional else ""
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

                extra = f" — {result.error}" if result.error else ""
                print(f"{result.status}{suffix}{extra}")

                if (
                    index < len(specs)
                    and args.between_resources_seconds > 0
                ):
                    time.sleep(args.between_resources_seconds)

            result_by_name = {
                result.name: result
                for result in results
            }
            canonical_matches_html = _read_snapshot_html(
                project_root=project_root,
                result=result_by_name.get("player_matches"),
            )
            manager_matches_html = _read_snapshot_html(
                project_root=project_root,
                result=result_by_name.get(
                    "player_matches_manager"
                ),
            )

            season_specs = build_season_match_specs(
                player_id=args.player_id,
                canonical_html=canonical_matches_html,
                manager_html=manager_matches_html,
            )
            print(
                f"Temporadas con partidos descubiertas: "
                f"{len(season_specs)}"
            )

            for index, spec in enumerate(season_specs, start=1):
                season = (spec.scope or {}).get("season")
                suffix = " (optional)" if spec.optional else ""
                print(
                    f"[S{index:02d}/{len(season_specs):02d}] "
                    f"{season or spec.name:<10} ... ",
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

                extra = f" — {result.error}" if result.error else ""
                print(
                    f"{result.status}{suffix} "
                    f"[{spec.provenance}]{extra}"
                )

                if (
                    index < len(season_specs)
                    and args.between_resources_seconds > 0
                ):
                    time.sleep(args.between_resources_seconds)
    finally:
        stop_browser(runtime)

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
        and result.status != STATUS_VALID
    ]
    optional_failed = [
        result
        for result in results
        if result.name in optional_names
        and result.status != STATUS_VALID
    ]

    discovered_links: set[str] = set()
    for result in results:
        if not result.snapshot_directory:
            continue
        links_path = (
            project_root
            / result.snapshot_directory
            / "same_player_links.json"
        )
        try:
            links = json.loads(links_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for link in links:
            if isinstance(link, str):
                discovered_links.add(link)

    summary = {
        "source": "bdfutbol",
        "entity_type": "player",
        "player_id": args.player_id,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_resources_requested": len(specs),
        "season_match_resources_requested": len(season_specs),
        "resources_requested": len(all_specs),
        "resources_valid": sum(
            result.status == STATUS_VALID for result in results
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
        "same_player_links_discovered": sorted(discovered_links),
        "resources": [_result_dict(result) for result in results],
    }

    summary_path = run_dir / "summary.json"
    _dump_json(summary_path, summary)

    if not required_failed:
        _write_latest_valid(
            root=raw_root,
            run_dir=run_dir,
            summary_path=summary_path,
        )

    print("\n=== PLAYER FULL DISCOVERY COMPLETADO ===")
    print(f"Recursos:          {summary['resources_requested']}")
    print(
        f"Partidos/temporada:{summary['season_match_resources_requested']:>3}"
    )
    print(f"Válidos:           {summary['resources_valid']}")
    print(f"Required fallidos: {summary['required_failed']}")
    print(f"Optional fallidos: {summary['optional_failed']}")
    print(
        f"Links jugador:     "
        f"{len(summary['same_player_links_discovered'])}"
    )
    print(f"Resumen:           {summary_path}")

    return 0 if not required_failed else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_sync(args)


if __name__ == "__main__":
    raise SystemExit(main())
