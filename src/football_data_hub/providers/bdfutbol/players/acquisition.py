"""Controlled acquisition of the four individual BDFutbol player views."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from football_data_hub.core.browser_runtime import BrowserRuntimeConfig
from football_data_hub.core.browser_session import BrowserSessionManager
from football_data_hub.providers.bdfutbol.access import (
    AccessAssessment,
    AccessStatus,
    BDFutbolAccess,
    is_bdfutbol_https_url,
)
from football_data_hub.providers.bdfutbol.players.catalog import build_player_acquisition_progress
from football_data_hub.providers.bdfutbol.players.html_parser import (
    PLAYER_PARSER_VERSION,
    soup_from_html,
)
from .capture_store import PlayerCaptureStore, utc_now
from .parsers import PlayerCaptureParseError, parse_snapshot

PLAYER_VIEWS = ("profile", "statistics", "matches", "rivals")
STOP_ON_UNVERIFIED_HTTP_ERROR = "STOP_ON_UNVERIFIED_HTTP_ERROR"
_PLAYER_ID = re.compile(r"^\d{1,9}$")
_VIEW_MARKERS = {
    "profile": (".traject",),
    "statistics": ("#table-estadistiques-competicions", "#table-estadistiques-equips"),
    "matches": ("#t2", "#t1", "#t55", "#t5"),
    "rivals": ("#t5", "#t6", "#t7"),
}
_FILTER_IDS = {
    "profile": ("sel-equip", "sel-pais", "dem", "pais"),
    "statistics": ("cats_milestones", "dem", "pais"),
    "matches": ("jug", "pgep", "comp", "temp", "equip", "rival", "dem", "pais"),
    "rivals": ("filtre-cat", "filtre-temp", "filtre-dem", "dem", "pais"),
}


class PlayerAcquisitionStopped(RuntimeError):
    """The first invalid page or acquisition error stopped this run."""

    def __init__(
        self,
        player_id: int,
        view: str,
        status: str,
        reason: str | None = None,
        *,
        diagnostic: dict[str, Any] | None = None,
    ) -> None:
        self.player_id = player_id
        self.view = view
        self.status = status
        self.reason = reason
        self.diagnostic = diagnostic or {}
        self.error_code = self.diagnostic.get("error_code")
        super().__init__(f"Adquisición detenida en {player_id}/{view}: {status}: {reason or ''}")


def access_policy_matrix() -> dict[str, str]:
    """Only a semantically valid HTTP 200 may advance; every other outcome stops."""
    return {
        status.value: "CONTINUE_ONLY_WITH_HTTP_200" if status is AccessStatus.VALID else "STOP"
        for status in AccessStatus
    }


def access_policy_is_complete() -> bool:
    matrix = access_policy_matrix()
    return (
        set(matrix) == {status.value for status in AccessStatus}
        and matrix.get(AccessStatus.VALID.value) == "CONTINUE_ONLY_WITH_HTTP_200"
        and all(action == "STOP" for name, action in matrix.items() if name != AccessStatus.VALID.value)
    )


def enforce_access_policy(
    assessment: AccessAssessment,
    *,
    player_id: int,
    view: str,
    requested_url: str,
    visit_available: bool,
) -> None:
    """Fail closed for 404 and every other unverified access/content outcome."""
    if assessment.status is AccessStatus.VALID and assessment.http_status == 200 and visit_available:
        return
    status = assessment.status.value
    error_code = (
        f"HTTP_{assessment.http_status}_STOPPED"
        if assessment.http_status is not None and assessment.status is AccessStatus.HTTP_ERROR
        else assessment.status.value
    )
    diagnostic = {
        "error_code": error_code,
        "policy": STOP_ON_UNVERIFIED_HTTP_ERROR,
        "classification": (
            "document_inspection_error"
            if assessment.status is AccessStatus.DOCUMENT_ERROR
            else "unverified_http_or_content_error"
        ),
        "failure_stage": (
            "document_inspection"
            if assessment.status is AccessStatus.DOCUMENT_ERROR
            else "access_assessment"
        ),
        "player_id": player_id,
        "view": view,
        "requested_url": requested_url,
        "final_url": assessment.final_url,
        "http_status": assessment.http_status,
        "access_status": assessment.status.value,
        "page_title": assessment.page_title,
        "reason": assessment.reason or "La respuesta no superó la política de acceso",
        "missing_markers": list(assessment.missing_markers),
        "missing_title_markers": list(assessment.missing_title_markers),
        "missing_selectors": list(assessment.missing_selectors),
        "missing_dom_markers": list(assessment.missing_dom_markers),
        "missing_dom_evidence": list(assessment.missing_dom_evidence),
        "recorded_at_utc": utc_now(),
        "stop_acquisition": True,
    }
    raise PlayerAcquisitionStopped(
        player_id, view, f"{status} ({assessment.http_status})", diagnostic["reason"],
        diagnostic=diagnostic,
    )


def player_view_url(player_id: int | str, view: str) -> str:
    identifier = str(player_id)
    if not _PLAYER_ID.fullmatch(identifier):
        raise ValueError(f"ID BDFutbol de jugador no válido: {player_id}")
    if view not in PLAYER_VIEWS:
        raise ValueError(f"Vista de jugador no admitida: {view}")
    if view == "profile":
        path = f"/es/j/j{identifier}.html"
    elif view == "statistics":
        path = f"/es/j/j{identifier}.html?p=stats"
    elif view == "matches":
        path = f"/es/p/j{identifier}.html"
    else:
        path = f"/es/p/jr{identifier}.html"
    return f"https://www.bdfutbol.com{path}"


def player_match_variant_url(player_id: int | str, filters: dict[str, str]) -> str:
    """Build an explicitly filtered match URL without changing its view identity."""
    if not filters or any(key != "cat" for key in filters):
        raise ValueError("Solo se admite el filtro de URL cat para una vista de Partidos")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,16}", value) for value in filters.values()):
        raise ValueError("Valor del filtro de competición no válido")
    base = player_view_url(player_id, "matches")
    return f"{base}?{urlencode(filters)}"


def load_inventory_players(path: Path, player_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Resolve explicit IDs from PLAYER-01A's verified, offline inventory."""
    document = json.loads(path.expanduser().read_text(encoding="utf-8"))
    records = document.get("records")
    if not isinstance(records, list):
        raise ValueError(f"Inventario sin records: {path}")
    result: dict[int, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("player_id"), int):
            continue
        player_id = record["player_id"]
        if player_id in player_ids:
            if player_id in result:
                raise ValueError(f"ID duplicado en inventario: {player_id}")
            result[player_id] = record
    missing = sorted(set(player_ids) - result.keys())
    if missing:
        raise ValueError(f"IDs no presentes en el inventario publicado: {missing}")
    return result


def _identity_evidence(
    html: str,
    player_id: int,
    display_name: str,
    full_name: str = "",
) -> tuple[str, ...]:
    soup = soup_from_html(html)
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    h1 = soup.find("h1")
    h1_text = h1.get_text(" ", strip=True) if h1 else ""
    visible_text = f"{title} {h1_text}".casefold()
    names = tuple(name.casefold() for name in (display_name, full_name) if name)
    if not any(name in visible_text for name in names):
        return ("player name is absent from title and h1",)
    routes = {
        f"/j/j{player_id}.html",
        f"/p/j{player_id}.html",
        f"/p/jr{player_id}.html",
    }
    observed = {
        str(node.get("href", "")).split("?", 1)[0]
        for node in soup.select("a[href]")
    }
    observed.update(
        str(node.get(attr, "")).split("?", 1)[0]
        for node in soup.select("[src], [data-src]")
        for attr in ("src", "data-src")
    )
    if not any(any(route.endswith(expected) for route in observed) for expected in routes):
        # The active page's own canonical URL is additional identity evidence
        # for views which do not include a profile tab in this DOM revision.
        raw_routes = (f"j{player_id}.html", f"jr{player_id}.html")
        if not any(route in html for route in raw_routes):
            return ("no player-specific route or media reference found in DOM",)
    return ()


def _controls(document: Any, view: str) -> list[dict[str, Any]]:
    controls = document.evaluate(
        "(() => Array.from(document.querySelectorAll('select, input, button')).map(el => ({"
        "tag: el.tagName.toLowerCase(), id: el.id || null, name: el.name || null,"
        "type: el.type || null, value: el.value ?? null, text: (el.innerText || el.textContent || '').trim(),"
        "selected: el.tagName === 'SELECT' ? {"
        "value: el.value, text: el.selectedOptions?.[0]?.textContent?.trim() || null} : null,"
        "options: el.tagName === 'SELECT' ? Array.from(el.options).map(o => ({value:o.value,text:o.textContent.trim()})) : []"
        "})))()"
    )
    if not isinstance(controls, list):
        return []
    wanted = set(_FILTER_IDS[view])
    return [
        {**control, "recognized_filter": control.get("id") in wanted or control.get("name") in wanted}
        for control in controls
    ]


def _resource_entries(document: Any) -> list[dict[str, Any]]:
    values = document.evaluate(
        "performance.getEntriesByType('resource').map(e => ({name:e.name,initiatorType:e.initiatorType,"
        "responseStatus:typeof e.responseStatus==='number'?e.responseStatus:null}))"
    )
    return values if isinstance(values, list) else []


def _row_counts(document: Any) -> dict[str, int]:
    values = document.evaluate(
        "(() => Object.fromEntries(['.traject','#table-estadistiques-competicions',"
        "'#table-estadistiques-equips','.taula-fites-jugador','#t2','#t1','#t55','#t5','#t6','#t7','#tpartits']"
        ".map(s => [s,document.querySelector(s)?.querySelectorAll('tr').length || 0])))()"
    )
    return {str(key): int(value) for key, value in values.items()} if isinstance(values, dict) else {}


def _non_default_option(options: list[dict[str, Any]], current_value: str) -> dict[str, Any] | None:
    default_labels = {"all", "all matches", "todos", "todas", "seleccionar", "-"}
    default_values = {"", "*", "-", "null", "none"}
    return next((
        option for option in options
        if str(option.get("value") or "") != current_value
        and str(option.get("value") or "").casefold() not in default_values
        and str(option.get("text") or "").strip().casefold() not in default_labels
    ), None)


def _has_filter_variant(
    store: PlayerCaptureStore,
    player_id: int,
    view: str,
    control_key: str,
    selected_value: str,
) -> bool:
    for item in store.manifest.get("snapshots", []):
        if (
            item.get("player_id") != player_id
            or item.get("view") != view
            or item.get("snapshot_kind") not in {"SELECTOR_VARIANT", "FILTERED_VARIANT"}
            or (item.get("filter_parameters") or {}).get(control_key) != selected_value
        ):
            continue
        try:
            metadata = json.loads((store.run_dir / item["metadata_path"]).read_text(encoding="utf-8"))
            raw = gzip.decompress((store.run_dir / item["raw_path"]).read_bytes())
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            continue
        if (
            metadata.get("access_status") == "VALID"
            and metadata.get("http_status") == 200
            and hashlib.sha256(raw).hexdigest() == metadata.get("html_sha256")
        ):
            return True
    return False


def acquire_player_match_variant(
    *,
    player_id: int,
    inventory_path: Path,
    capture_root: Path,
    profile_dir: Path,
    filters: dict[str, str],
    browser_executable: Path | None = None,
    capture_id: str | None = None,
    settle_ms: int = 900,
    pause_seconds: float = 5.0,
) -> dict[str, Any]:
    """Acquire one allowlisted URL-filtered matches snapshot, stopping on denial."""
    if settle_ms < 0 or pause_seconds < 0:
        raise ValueError("Los tiempos no pueden ser negativos")
    url = player_match_variant_url(player_id, filters)
    inventory_path = inventory_path.expanduser().resolve()
    inventory_raw = inventory_path.read_bytes()
    inventory_document = json.loads(inventory_raw)
    inventory = load_inventory_players(inventory_path, [player_id])
    candidate = inventory[player_id]
    display_name = str(candidate.get("display_name") or "").strip()
    full_name = str(candidate.get("full_name") or "").strip()
    names = tuple(name for name in (display_name, full_name) if name)
    if not names:
        raise ValueError(f"El inventario no tiene nombres para {player_id}")
    store = PlayerCaptureStore(capture_root, capture_id=capture_id)
    store.record_inventory_source({
        "path": str(inventory_path),
        "sha256": hashlib.sha256(inventory_raw).hexdigest(),
        "schema_version": inventory_document.get("schema_version"),
        "season": inventory_document.get("metadata", {}).get("season", "2026-27"),
        "source": "PLAYER-01A published offline player inventory",
    })
    if store.has_valid_snapshot(
        player_id=player_id,
        view="matches",
        requested_url=url,
        snapshot_kind="URL_VARIANT",
    ):
        return {
            "capture_id": store.capture_id,
            "capture_dir": str(store.run_dir),
            "player_id": player_id,
            "view": "matches",
            "requested_url": url,
            "snapshot_reused": True,
            "navigation_count": 0,
        }

    config = BrowserRuntimeConfig(
        profile_dir=profile_dir,
        backend="seleniumbase-pure-cdp",
        browser="chromium",
        browser_executable_path=browser_executable,
        use_xvfb=True,
        start_url="about:blank",
    )
    if pause_seconds:
        time.sleep(pause_seconds)
    try:
        with BrowserSessionManager(config) as session:
            browser = {
                "backend": session.info.backend if session.info else None,
                "browser_name": session.info.browser_name if session.info else None,
                "browser_executable": session.info.browser_executable if session.info else None,
                "browser_version": session.info.browser_version if session.info else None,
                "automation_version": session.info.automation_version if session.info else None,
                "display": session.info.display if session.info else None,
                "process_display": session.info.process_display if session.info else None,
                "uses_xvfb": session.info.uses_xvfb if session.info else False,
                "xvfb_external": session.info.xvfb_external if session.info else None,
                "screen_size": session.info.screen_size if session.info else None,
            }
            opened = BDFutbolAccess(session).open(
                url,
                required_markers=(display_name,),
                required_selectors=("#tpartits", "#t2", "#pest1", "#pest2"),
                document_validator=lambda html: _identity_evidence(
                    html, player_id, display_name, full_name,
                ),
                settle_ms=settle_ms,
                max_wait_seconds=8.0,
            )
            assessment = opened.assessment
            event = {
                "player_id": player_id,
                "view": "matches",
                "snapshot_kind": "URL_VARIANT",
                "requested_url": url,
                "final_url": assessment.final_url,
                "http_status": assessment.http_status,
                "access_status": assessment.status.value,
                "page_title": assessment.page_title,
                "filter_parameters": filters,
                "missing_markers": list(assessment.missing_markers),
                "missing_title_markers": list(assessment.missing_title_markers),
                "missing_selectors": list(assessment.missing_selectors),
                "reason": assessment.reason,
                "captured_at_utc": utc_now(),
                "navigation_purpose": "url_filter_variant_capture",
            }
            store.record_navigation(event)
            if assessment.status is not AccessStatus.VALID or opened.visit is None:
                store.record_diagnostic({**event, "stop_acquisition": True})
                opened.close()
                raise PlayerAcquisitionStopped(
                    player_id, "matches", assessment.status.value, assessment.reason,
                )

            visit = opened.visit
            page = visit.document
            browser_snapshot = page.evaluate(
                """(() => {
                    const table = document.querySelector('#tpartits');
                    const rows = Array.from(table?.querySelectorAll('tbody tr') || []);
                    const matchRows = rows.map((row, index) => {
                        const link = row.querySelector('a[href*="p.php?id="]');
                        const href = link?.getAttribute('href') || null;
                        const id = href ? new URL(href, location.href).searchParams.get('id') : null;
                        return id ? {row_index:index, match_id:id, href, text:row.innerText.trim()} : null;
                    }).filter(Boolean);
                    const rawP = Array.isArray(window.P) ? window.P : null;
                    const scripts = Array.from(document.scripts)
                        .map(script => script.src).filter(src => /scripts_partits\\.js/.test(src));
                    const visible = selector => {
                        const element = document.querySelector(selector);
                        return element ? getComputedStyle(element).display !== 'none' : null;
                    };
                    return {
                        table_row_count: table?.querySelectorAll('tr').length || 0,
                        table_body_row_count: rows.length,
                        rendered_match_rows: matchRows,
                        rendered_match_id_count: matchRows.length,
                        rendered_unique_match_ids: new Set(matchRows.map(row => row.match_id)).size,
                        table_headers: Array.from(table?.querySelectorAll('thead th') || []).map(cell => ({
                            text:cell.innerText.trim(), title:cell.title || null,
                            data_colid:cell.dataset.colid || null
                        })),
                        window_p_present: rawP !== null,
                        window_p_record_count: rawP?.length ?? null,
                        window_p_tuple_widths: rawP ? [...new Set(rawP.map(row => Array.isArray(row) ? row.length : null))] : [],
                        window_p_unique_match_ids: rawP ? new Set(rawP.map(row => Array.isArray(row) ? String(row[8]) : '')).size : null,
                        panel_pest1_visible: visible('#pest1'),
                        panel_pest2_visible: visible('#pest2'),
                        scripts_partits_urls: scripts,
                        selected_controls: Array.from(document.querySelectorAll('select')).map(select => ({
                            id:select.id || null, name:select.name || null,
                            value:select.value, text:select.selectedOptions?.[0]?.textContent?.trim() || null
                        }))
                    };
                })()"""
            )
            html = page.html()
            metadata = store.save_snapshot(
                player_id=player_id,
                view="matches",
                requested_url=url,
                final_url=visit.final_url,
                http_status=visit.response_status,
                page_title=page.title(),
                html=html,
                browser=browser,
                filter_parameters=filters,
                snapshot_kind="URL_VARIANT",
                controls=_controls(page, "matches"),
                observations={
                    "variant_type": "url",
                    "interaction": "navigation_query_parameters",
                    "url_unchanged_after_load": page.url == url,
                    **(browser_snapshot if isinstance(browser_snapshot, dict) else {}),
                },
            )
            opened.close()
        store.mark_complete()
    except BaseException as exc:
        if not isinstance(exc, PlayerAcquisitionStopped):
            store.record_diagnostic({
                "player_id": player_id,
                "view": "matches",
                "requested_url": url,
                "snapshot_kind": "URL_VARIANT",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "stop_acquisition": True,
            })
        raise
    return {
        "capture_id": store.capture_id,
        "capture_dir": str(store.run_dir),
        "player_id": player_id,
        "view": "matches",
        "requested_url": url,
        "snapshot_id": metadata["snapshot_id"],
        "raw_sha256": metadata["html_sha256"],
        "observations": metadata["interaction_observations"],
        "snapshot_reused": False,
        "navigation_count": 1,
    }


def acquire_player_views(
    *,
    player_ids: list[int],
    inventory_path: Path,
    capture_root: Path,
    profile_dir: Path,
    browser_executable: Path | None = None,
    capture_id: str | None = None,
    settle_ms: int = 900,
    pause_seconds: float = 5.0,
    explore_filters: bool = True,
    views: tuple[str, ...] = PLAYER_VIEWS,
    revisit_existing: bool = False,
    progress_index: dict[str, Any] | None = None,
    on_snapshot_saved: Callable[[dict[str, Any]], None] | None = None,
    before_navigation: Callable[[int, str, str], None] | None = None,
    before_snapshot_save: Callable[[int, str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Capture explicit player pages sequentially and stop on first denial.

    The raw HTML is persisted immediately after access and identity validation,
    before any parser is called. Filter variants are explored only on the first
    requested player; each control is changed individually and restored.
    """
    if not player_ids or len(set(player_ids)) != len(player_ids):
        raise ValueError("Indica IDs explícitos, sin duplicados")
    if not views or len(set(views)) != len(views) or any(view not in PLAYER_VIEWS for view in views):
        raise ValueError("Indica vistas válidas y sin duplicados")
    if pause_seconds < 0 or settle_ms < 0:
        raise ValueError("Los tiempos no pueden ser negativos")
    inventory = load_inventory_players(inventory_path, player_ids)
    store = PlayerCaptureStore(capture_root, capture_id=capture_id)
    inventory_path = inventory_path.expanduser().resolve()
    inventory_raw = inventory_path.read_bytes()
    inventory_document = json.loads(inventory_raw)
    store.record_inventory_source({
        "path": str(inventory_path),
        "sha256": hashlib.sha256(inventory_raw).hexdigest(),
        "schema_version": inventory_document.get("schema_version"),
        "season": inventory_document.get("metadata", {}).get("season", "2026-27"),
        "source": "PLAYER-01A published offline player inventory",
    })
    if progress_index is None:
        progress = build_player_acquisition_progress(
            inventory_path=inventory_path,
            capture_root=capture_root,
        )
    else:
        if progress_index.get("inventory", {}).get("sha256") != hashlib.sha256(inventory_raw).hexdigest():
            raise ValueError("El índice de progreso corresponde a otro inventario")
        if Path(str(progress_index.get("capture_root", ""))).expanduser().resolve() != capture_root.expanduser().resolve():
            raise ValueError("El índice de progreso corresponde a otra raíz de capturas")
        progress = progress_index
    indexed_players = {item["player_id"]: item for item in progress["players"]}
    navigation_queue: set[tuple[int, str]] = set()
    for player_id in player_ids:
        for view in views:
            url = player_view_url(player_id, view)
            current_base_exists = store.has_valid_base_snapshot(
                player_id=player_id,
                view=view,
                requested_url=url,
            )
            reused = indexed_players[player_id]["view_snapshots"].get(view)
            if revisit_existing:
                if not current_base_exists:
                    raise ValueError(
                        f"No se encontró una vista base válida para revalidar: {player_id}/{view}"
                    )
                navigation_queue.add((player_id, view))
                continue
            if reused:
                if reused["capture_id"] != store.capture_id:
                    store.record_reused_snapshot(reused)
                continue
            navigation_queue.add((player_id, view))

    if not navigation_queue:
        store.mark_complete()
        return {
            "capture_id": store.capture_id,
            "capture_dir": str(store.run_dir),
            "snapshot_count": len(store.manifest["snapshots"]),
            "navigation_count": 0,
            "reused_snapshot_count": len(store.manifest.get("reused_snapshots", [])),
            "status": store.manifest["status"],
            "access_assessments": [],
            "filter_variants": 0,
        }
    config = BrowserRuntimeConfig(
        profile_dir=profile_dir,
        backend="seleniumbase-pure-cdp",
        browser="chromium",
        browser_executable_path=browser_executable,
        use_xvfb=True,
        start_url="about:blank",
    )
    assessments: list[dict[str, Any]] = []
    pages_seen = 0
    try:
        with BrowserSessionManager(config) as session:
            browser = {
                "backend": session.info.backend if session.info else None,
                "browser_name": session.info.browser_name if session.info else None,
                "browser_executable": session.info.browser_executable if session.info else None,
                "browser_version": session.info.browser_version if session.info else None,
                "automation_version": session.info.automation_version if session.info else None,
                "display": session.info.display if session.info else None,
                "process_display": session.info.process_display if session.info else None,
                "uses_xvfb": session.info.uses_xvfb if session.info else False,
                "xvfb_external": session.info.xvfb_external if session.info else None,
                "screen_size": session.info.screen_size if session.info else None,
            }
            access = BDFutbolAccess(session)
            for player_index, player_id in enumerate(player_ids):
                candidate = inventory[player_id]
                display_name = str(candidate.get("display_name") or "").strip()
                full_name = str(candidate.get("full_name") or "").strip()
                if not display_name:
                    raise ValueError(f"El inventario no tiene display_name para {player_id}")
                for view in views:
                    if (player_id, view) not in navigation_queue:
                        continue
                    url = player_view_url(player_id, view)
                    existing_base = store.has_valid_base_snapshot(
                        player_id=player_id,
                        view=view,
                        requested_url=url,
                    )
                    if existing_base and not revisit_existing:
                        continue
                    if revisit_existing and not existing_base:
                        raise ValueError(
                            f"No se encontró una vista base válida para reutilizar: {player_id}/{view}"
                        )
                    if pages_seen and pause_seconds:
                        time.sleep(pause_seconds)
                    if not is_bdfutbol_https_url(url):
                        raise ValueError(f"URL fuera del dominio permitido: {url}")
                    if before_navigation is not None:
                        before_navigation(player_id, view, url)
                    required = _VIEW_MARKERS[view]
                    selectors = ("h1", *required)

                    def identity_validator(html: str) -> tuple[str, ...]:
                        return _identity_evidence(html, player_id, display_name, full_name)

                    opened = access.open(
                        url,
                        required_markers=(full_name or display_name,),
                        required_title_markers=(full_name or display_name,),
                        required_selectors=selectors,
                        document_validator=identity_validator,
                        settle_ms=settle_ms,
                        max_wait_seconds=4.0,
                    )
                    assessment = opened.assessment
                    assessments.append({
                        "player_id": player_id,
                        "view": view,
                        "requested_url": url,
                        "final_url": assessment.final_url,
                        "http_status": assessment.http_status,
                        "access_status": assessment.status.value,
                        "page_title": assessment.page_title,
                        "reason": assessment.reason,
                        "missing_markers": assessment.missing_markers,
                        "missing_title_markers": assessment.missing_title_markers,
                        "missing_selectors": assessment.missing_selectors,
                        "missing_dom_evidence": assessment.missing_dom_evidence,
                        "navigation_purpose": "filter_exploration_revisit" if existing_base else "base_view_capture",
                        "captured_at_utc": utc_now(),
                    })
                    pages_seen += 1
                    store.record_navigation(assessments[-1])
                    try:
                        enforce_access_policy(
                            assessment,
                            player_id=player_id,
                            view=view,
                            requested_url=url,
                            visit_available=opened.visit is not None,
                        )
                    except PlayerAcquisitionStopped as exc:
                        store.record_diagnostic({
                            **assessments[-1],
                            **exc.diagnostic,
                        })
                        opened.close()
                        raise
                    visit = opened.visit
                    page = visit.document
                    controls = _controls(page, view)
                    base_rows = _row_counts(page)
                    base_html = page.html()
                    if before_snapshot_save is not None:
                        before_snapshot_save(player_id, view, url, base_html)
                    base_metadata = store.save_snapshot(
                        player_id=player_id,
                        view=view,
                        requested_url=url,
                        final_url=visit.final_url,
                        http_status=visit.response_status,
                        page_title=page.title(),
                        html=base_html,
                        browser=browser,
                        controls=controls,
                        observations={
                            "row_counts": base_rows,
                            "filter_state": "base",
                            "purpose": "filter_exploration_revisit" if existing_base else "base_view_capture",
                        },
                    )
                    saved_record = store.manifest["snapshots"][-1]
                    try:
                        parse_snapshot(
                            store.run_dir,
                            saved_record,
                            expected_player_id=player_id,
                            expected_names=tuple(
                                value for value in (display_name, full_name) if value
                            ),
                        )
                    except (PlayerCaptureParseError, OSError, ValueError, TypeError) as exc:
                        store.record_snapshot_validation(
                            str(saved_record["snapshot_id"]),
                            status="INVALID",
                            parser_version=PLAYER_PARSER_VERSION,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                        store.record_diagnostic({
                            "player_id": player_id,
                            "view": view,
                            "requested_url": url,
                            "access_status": "STRUCTURE_ERROR",
                            "reason": f"Snapshot HTML no supera el parser: {exc}",
                            "stop_acquisition": True,
                        })
                        opened.close()
                        raise PlayerAcquisitionStopped(
                            player_id, view, "STRUCTURE_ERROR", str(exc)
                        ) from exc
                    store.record_snapshot_validation(
                        str(saved_record["snapshot_id"]),
                        status="VALID",
                        parser_version=PLAYER_PARSER_VERSION,
                    )
                    if on_snapshot_saved is not None:
                        on_snapshot_saved({
                            **saved_record,
                            "capture_id": store.capture_id,
                            "captured_at_utc": base_metadata.get("captured_at_utc"),
                        })
                    if explore_filters and player_index == 0:
                        for control in controls:
                            control_id = str(control.get("id") or "")
                            control_name = str(control.get("name") or "")
                            control_key = control_id or control_name
                            if not control.get("recognized_filter") or control.get("tag") != "select" or not control_key:
                                continue
                            options = control.get("options") or []
                            initial = str(control.get("value") or "")
                            option = _non_default_option(options, initial)
                            if option is None:
                                continue
                            alternative = str(option.get("value") or "")
                            if _has_filter_variant(store, player_id, view, control_key, alternative):
                                continue
                            selector = f"#{control_id}" if control_id else f'[name="{control_name}"]'
                            before_resources = _resource_entries(page)
                            before_rows = _row_counts(page)
                            try:
                                page.select(selector, alternative)
                                page.wait(500)
                            except Exception as exc:
                                store.record_diagnostic({
                                    "player_id": player_id,
                                    "view": view,
                                    "control_id": control_id,
                                    "access_status": "FILTER_INTERACTION_ERROR",
                                    "reason": f"{type(exc).__name__}: {exc}",
                                    "stop_acquisition": False,
                                })
                                continue
                            final_url = page.url
                            selected_value = page.value(selector)
                            after_resources = _resource_entries(page)
                            known_resources = {entry.get("name") for entry in before_resources}
                            additions = [entry for entry in after_resources if entry.get("name") not in known_resources]
                            after_rows = _row_counts(page)
                            variant_filters = {control_key: selected_value}
                            variant_html = page.html()
                            current_title = page.title().casefold()
                            current_body = page.text("body").casefold()
                            challenge = any(marker in current_title or marker in current_body for marker in (
                                "just a moment", "checking your browser", "verify you are human",
                                "cf-challenge", "challenges.cloudflare.com",
                            ))
                            if final_url != url or challenge:
                                store.record_diagnostic({
                                    "player_id": player_id,
                                    "view": view,
                                    "requested_url": url,
                                    "final_url": final_url,
                                    "access_status": "INVALID_CONTENT",
                                    "reason": "URL changed or challenge title observed during filter interaction",
                                    "stop_acquisition": True,
                                })
                                raise PlayerAcquisitionStopped(player_id, view, "INVALID_CONTENT", "filter interaction changed resource or showed challenge")
                            _identity_errors = _identity_evidence(variant_html, player_id, display_name, full_name)
                            if _identity_errors:
                                store.record_diagnostic({
                                    "player_id": player_id,
                                    "view": view,
                                    "requested_url": url,
                                    "final_url": final_url,
                                    "access_status": "INVALID_CONTENT",
                                    "reason": "; ".join(_identity_errors),
                                    "stop_acquisition": True,
                                })
                                raise PlayerAcquisitionStopped(player_id, view, "INVALID_CONTENT", "identity changed during filter interaction")
                            statuses = [entry.get("responseStatus") for entry in additions]
                            denied_resources = [
                                entry for entry in additions
                                if entry.get("responseStatus") in {403, 429}
                                and "bdfutbol.com" in str(entry.get("name", ""))
                            ]
                            if denied_resources:
                                store.record_diagnostic({
                                    "player_id": player_id,
                                    "view": view,
                                    "filter_parameters": variant_filters,
                                    "new_resources": additions,
                                    "access_status": "HTTP_ERROR",
                                    "reason": "BDFutbol subresource denied during filter selection",
                                    "stop_acquisition": True,
                                })
                                raise PlayerAcquisitionStopped(player_id, view, "HTTP_ERROR", "BDFutbol filter subresource denied")
                            store.save_snapshot(
                                player_id=player_id,
                                view=view,
                                requested_url=url,
                                final_url=final_url,
                                http_status=visit.response_status,
                                page_title=page.title(),
                                html=variant_html,
                                browser=browser,
                                filter_parameters=variant_filters,
                                controls=_controls(page, view),
                                observations={
                                    "interaction": "select_option",
                                    "selector": selector,
                                    "selected_value": selected_value,
                                    "selected_label": next((item.get("text") for item in options if str(item.get("value") or "") == selected_value), None),
                                    "url_unchanged": final_url == url,
                                    "base_row_counts": before_rows,
                                    "variant_row_counts": after_rows,
                                    "new_resource_entries": additions,
                                    "new_resource_statuses": statuses,
                                    "dom_html_sha256_changed": hashlib.sha256(variant_html.encode()).hexdigest() != base_metadata["html_sha256"],
                                },
                            )
                            page.select(selector, initial)
                            page.wait(250)
                    opened.close()
        store.mark_complete()
    except PlayerAcquisitionStopped:
        raise
    except BaseException as exc:
        diagnostic = getattr(exc, "diagnostic", {})
        store.record_diagnostic({
            **diagnostic,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "player_id": getattr(exc, "player_id", diagnostic.get("player_id")),
            "view": getattr(exc, "view", diagnostic.get("view")),
            "requested_url": diagnostic.get("requested_url"),
            "http_status": diagnostic.get("http_status"),
            "error_code": getattr(exc, "error_code", diagnostic.get("error_code")),
            "stop_acquisition": True,
        })
        raise
    return {
        "capture_id": store.capture_id,
        "capture_dir": str(store.run_dir),
        "snapshot_count": len(store.manifest["snapshots"]),
        "navigation_count": pages_seen,
        "verified_navigation_count_total": len(store.manifest.get("navigation_events", [])),
        "status": store.manifest["status"],
        "access_assessments": assessments,
        "filter_variants": sum(
            item["snapshot_kind"] in {"SELECTOR_VARIANT", "FILTERED_VARIANT"}
            for item in store.manifest["snapshots"]
        ),
        "reused_snapshot_count": len(store.manifest.get("reused_snapshots", [])),
    }
