"""One-team, one-season acquisition using the shared Pure CDP session."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from football_data_hub.core.browser_runtime import BrowserRuntimeConfig
from football_data_hub.core.browser_session import BrowserSessionManager
from football_data_hub.providers.bdfutbol.access import (
    AccessAssessment,
    AccessStatus,
    BDFutbolAccess,
)
from football_data_hub.providers.bdfutbol.context import CompetitionContext

from .models import TeamProfileData
from .parser import parse_team_profile_pages, resolve_team_view_urls
from .validation import validate_team_profile

EXTRACTOR_VERSION = "0.1.0"
TEAM_VIEW_SELECTORS = {
    "alignment": ("#taulaplantilla",),
    "squad": ("#c3p1",),
    "statistics": ("#c3p0",),
    "follow": ("#taula-seguiment",),
    "transfers": (),
    "matches": ("#taula-resultats-plantilla",),
}
DEFAULT_VIEWS = ("alignment", "squad", "statistics", "follow", "transfers", "matches")


class TeamAcquisitionStopped(RuntimeError):
    """A source page failed access or semantic validation; acquisition stops."""

    def __init__(self, view: str, assessment: AccessAssessment) -> None:
        self.view = view
        self.assessment = assessment
        super().__init__(
            f"Adquisición de ficha detenida en {view}: {assessment.status}; "
            f"HTTP={assessment.http_status}; {assessment.reason or 'contenido no validado'}"
        )


@dataclass(frozen=True, slots=True)
class TeamAcquisitionBundle:
    capture_id: str
    captured_at_utc: str
    requested_views: tuple[str, ...]
    raw_views: dict[str, str]
    view_urls: dict[str, str]
    access_by_view: dict[str, dict[str, Any]]
    page_titles: dict[str, str]
    browser: dict[str, Any]
    team_catalog_reference: dict[str, Any]
    parsed: TeamProfileData
    validation: dict[str, Any]
    competition: CompetitionContext
    acquired_views: tuple[str, ...] = ()
    follow_state_html: dict[str, str] = field(default_factory=dict)
    follow_state_diagnostics: dict[str, dict[str, Any]] = field(default_factory=dict)
    seed_capture_ids: tuple[str, ...] = ()
    started_at_utc: str | None = None


def create_team_capture_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now.strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex[:8]}"


def _view_markers(view: str, source_html: str) -> tuple[str, ...]:
    """Return missing structural evidence for a particular team-profile view."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(source_html, "html.parser")
    required = TEAM_VIEW_SELECTORS[view]
    missing = [selector for selector in required if soup.select_one(selector) is None]
    if view == "transfers":
        # BDFutbol omits the heading/table for a genuinely empty direction on
        # some teams. The enclosing transfer section is the required marker;
        # absence of its root is an incomplete page, not an empty transfer set.
        if soup.select_one("#pestaltesbaixes") is None:
            missing.append("#pestaltesbaixes")
    return tuple(missing)


def _resource_origins(urls: Any) -> list[str]:
    """Keep resource origin/path for diagnostics without tracking query IDs."""
    normalized: set[str] = set()
    for value in urls or []:
        parts = urlsplit(str(value))
        if parts.scheme and parts.netloc:
            normalized.add(urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")))
    return sorted(normalized)


def acquire_team_profile(
    *,
    team_catalog_record: dict[str, Any],
    team_catalog_reference: dict[str, Any],
    group_team_catalog: list[dict[str, Any]],
    known_matches: list[dict[str, Any]],
    competition: CompetitionContext,
    profile_dir: Path,
    requested_views: tuple[str, ...] = DEFAULT_VIEWS,
    browser: str = "chromium",
    browser_executable_path: Path | None = None,
    startup_timeout_seconds: float = 35.0,
    navigation_timeout_ms: int = 45_000,
    use_xvfb: bool = True,
    capture_id: str | None = None,
    seed_raw_views: dict[str, str] | None = None,
    seed_access_by_view: dict[str, dict[str, Any]] | None = None,
    seed_view_urls: dict[str, str] | None = None,
    seed_page_titles: dict[str, str] | None = None,
    seed_browser: dict[str, Any] | None = None,
    seed_capture_id: str | None = None,
    explore_follow_states: bool = True,
) -> TeamAcquisitionBundle:
    """Acquire selected team views and optionally reuse validated seed snapshots."""
    views = tuple(dict.fromkeys(requested_views))
    if not views and not seed_raw_views:
        raise ValueError("Indica vistas que adquirir o snapshots de origen")
    unknown = sorted(set(views) - set(TEAM_VIEW_SELECTORS))
    if unknown:
        raise ValueError(f"Vistas no admitidas: {unknown}")
    team_url = str(team_catalog_record["team_url"])
    capture_id = capture_id or create_team_capture_id()
    started_at = datetime.now(timezone.utc).isoformat()
    config = BrowserRuntimeConfig(
        profile_dir=profile_dir,
        backend="seleniumbase-pure-cdp",
        browser=browser,
        browser_executable_path=browser_executable_path,
        startup_timeout_seconds=startup_timeout_seconds,
        use_xvfb=use_xvfb,
    )
    raw_views: dict[str, str] = dict(seed_raw_views or {})
    view_urls: dict[str, str] = dict(seed_view_urls or {})
    access_by_view: dict[str, dict[str, Any]] = dict(seed_access_by_view or {})
    page_titles: dict[str, str] = dict(seed_page_titles or {})
    follow_state_html: dict[str, str] = {}
    follow_state_diagnostics: dict[str, dict[str, Any]] = {}
    captured_views: list[str] = []
    if "alignment" not in raw_views and "alignment" not in views:
        raise ValueError("La adquisición debe incluir alignment o reutilizar su snapshot")
    with BrowserSessionManager(config, navigation_timeout_ms=navigation_timeout_ms) as session:
        access = BDFutbolAccess(session)
        for view in views:
            if view in raw_views:
                raise ValueError(f"La vista {view} ya existe en los snapshots reutilizados")
            if view == "alignment":
                url = team_url
            else:
                # Resolve every sub-view from the catalog URL and the real base-page links.
                if "alignment" not in raw_views:
                    raise ValueError("La página base debe adquirirse antes de otras vistas")
                url = resolve_team_view_urls(raw_views["alignment"], team_url)[view]
            selectors = TEAM_VIEW_SELECTORS[view]
            opened = access.open(
                url,
                required_markers=(str(team_catalog_record.get("name") or ""), competition.season),
                required_title_markers=(competition.season,),
                required_selectors=selectors,
                document_validator=lambda html, v=view: _view_markers(v, html),
                settle_ms=750,
                max_wait_seconds=0,
            )
            with opened:
                assessment = opened.assessment
                access_by_view[view] = asdict(assessment)
                view_urls[view] = url
                if assessment.status is not AccessStatus.VALID or opened.visit is None:
                    raise TeamAcquisitionStopped(view, assessment)
                document = opened.visit.document
                raw_views[view] = document.html()
                page_titles[view] = assessment.page_title
                captured_at_view = datetime.now(timezone.utc).isoformat()
                access_by_view[view] = {
                    **access_by_view[view],
                    "captured_at_utc": captured_at_view,
                    "capture_timestamp_basis": "browser navigation and DOM serialization",
                }
                captured_views.append(view)
                if view == "follow" and explore_follow_states:
                    resource_urls_before = set(
                        document.evaluate(
                            "performance.getEntriesByType('resource').map(entry => entry.name)"
                        )
                        or []
                    )
                    for state, label in (("p", "Partidos"), ("t", "Tarjetas"), ("go", "Goles"), ("tot", "Todo")):
                        document.select("#vista_jornades", state)
                        document.wait(150)
                        selected = document.value("#vista_jornades")
                        state_html = document.html()
                        if selected != state or "#taula-seguiment" in _view_markers("follow", state_html):
                            raise ValueError(f"Seguimiento no actualizó el estado {state!r}")
                        resource_urls_after = set(
                            document.evaluate(
                                "performance.getEntriesByType('resource').map(entry => entry.name)"
                            )
                            or []
                        )
                        follow_state_html[state] = state_html
                        follow_state_diagnostics[state] = {
                            "label": label,
                            "selected_value": selected,
                            "url": document.url,
                            "table_rows": document.count("#taula-seguiment tr"),
                            "html_sha256": hashlib.sha256(state_html.encode("utf-8")).hexdigest(),
                            "resource_urls_added_since_previous_state": _resource_origins(resource_urls_after - resource_urls_before),
                        }
                        resource_urls_before = resource_urls_after
        info = session.info
        browser_info = {
            "backend": info.backend if info else config.backend,
            "browser_name": info.browser_name if info else browser,
            "browser_executable": info.browser_executable if info else None,
            "browser_version": info.browser_version if info else None,
            "automation_version": info.automation_version if info else None,
            "display": info.display if info else None,
            "uses_xvfb": info.uses_xvfb if info else use_xvfb,
            "xvfb_external": info.xvfb_external if info else use_xvfb,
        }
        if seed_browser:
            browser_info["reused_seed_browser"] = seed_browser

    full_views = tuple(view for view in DEFAULT_VIEWS if view in raw_views)
    parsed = parse_team_profile_pages(
        raw_views,
        team_catalog_record=team_catalog_record,
        competition_context=competition,
        follow_state_html=follow_state_html,
    )
    validation = validate_team_profile(
        parsed,
        catalog_record=team_catalog_record,
        group_team_catalog=group_team_catalog,
        known_matches=known_matches,
        requested_views=full_views,
    )
    if not validation["valid"]:
        raise ValueError(f"La ficha no pasó validación: {validation['issues']}")
    return TeamAcquisitionBundle(
        capture_id=capture_id,
        captured_at_utc=datetime.now(timezone.utc).isoformat(),
        requested_views=full_views,
        raw_views=raw_views,
        view_urls=view_urls,
        access_by_view=access_by_view,
        page_titles=page_titles,
        browser=browser_info,
        team_catalog_reference=team_catalog_reference,
        parsed=parsed,
        validation=validation,
        competition=competition,
        acquired_views=tuple(captured_views),
        follow_state_html=follow_state_html,
        follow_state_diagnostics=follow_state_diagnostics,
        seed_capture_ids=((seed_capture_id,) if seed_capture_id else ()),
        started_at_utc=started_at,
    )
