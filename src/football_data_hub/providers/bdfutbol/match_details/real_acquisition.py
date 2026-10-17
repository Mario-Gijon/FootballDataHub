"""Single-use, explicitly authorized real discovery of one BDFutbol match.

Importing this module does not start a browser or perform network activity.
The command-line path is the only production caller and always uses the
existing isolated SeleniumBase Pure CDP BrowserSessionManager.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from football_data_hub.core.browser_runtime import BrowserRuntimeConfig
from football_data_hub.core.browser_session import BrowserSessionManager
from football_data_hub.providers.bdfutbol.access import AccessStatus, BDFutbolAccess

from .campaign import (
    MatchCampaignAuthorizationError,
    MatchCampaignIntegrityError,
    MatchDetailCampaignLedger,
    _campaign_spec,
    _now,
)
from .historical_review import verify_historical_stop_evidence
from .inventory import build_match_detail_inventory, load_verified_match_generation
from .store import MatchDetailStore

REAL_EXECUTION_CONFIRMATION = "EXECUTE_ONE_MATCH_DISCOVERY_NAVIGATION"


@dataclass(frozen=True, slots=True)
class RealDiscoveryResponse:
    final_url: str | None
    http_status: int | None
    html: bytes
    page_title: str
    access_classification: str
    access_diagnostic: str | None = None
    challenge_detected: bool = False
    denial_detected: bool = False
    captured_at_utc: str | None = None


@dataclass(frozen=True, slots=True)
class RealDiscoveryResult:
    status: str
    internal_id: str
    source_match_id: str
    requested_url: str
    final_url: str | None
    http_status: int | None
    access_classification: str
    attempt_id: str
    artifact: dict[str, str] | None
    error_code: str | None
    capture_promoted: bool = False
    navigation_count: int = 1
    diagnostic: str | None = None


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _candidate(spec: dict[str, Any], internal_id: str) -> dict[str, Any]:
    selected = [item for item in spec["candidates"] if item["internal_id"] == internal_id]
    if len(selected) != 1:
        raise MatchCampaignAuthorizationError("El partido no es candidato único del plan")
    return selected[0]


def _store_checkpoint_is_unchanged(store: MatchDetailStore, spec: dict[str, Any]) -> None:
    inventory_id = spec["source"]["inventory_id"]
    state_path = store.root / "states" / f"{inventory_id}.json"
    if state_path.is_symlink() or not state_path.is_file():
        raise MatchCampaignIntegrityError("Falta el checkpoint histórico regular")
    raw = state_path.read_bytes()
    if _sha(raw) != spec["legacy_stop_review_reference"]["checkpoint_sha256"]:
        raise MatchCampaignIntegrityError("El checkpoint MATCH cambió desde la revisión")


def _open_real_once(
    config: BrowserRuntimeConfig,
    *,
    url: str,
    session_factory: Callable[..., Any] = BrowserSessionManager,
) -> RealDiscoveryResponse:
    """Start the managed browser and perform one source navigation, without retries."""

    with session_factory(config) as session:
        opened = BDFutbolAccess(session).open(
            url,
            # The title/footer marker is only for coarse page-vs-empty
            # classification. It is not used as semantic match identity.
            required_markers=("BDFutbol",),
            settle_ms=750,
            max_wait_seconds=12.0,
        )
        assessment = opened.assessment
        html = b""
        title = assessment.page_title
        if opened.visit is not None:
            try:
                html = opened.visit.document.html().encode("utf-8")
                title = opened.visit.document.title() or title
            except Exception:
                return RealDiscoveryResponse(
                    final_url=assessment.final_url,
                    http_status=assessment.http_status,
                    html=b"",
                    page_title=title,
                    access_classification=AccessStatus.DOCUMENT_ERROR.value,
                    access_diagnostic="No se pudo leer el HTML del DOM después de la navegación",
                    captured_at_utc=datetime.now(timezone.utc).isoformat(),
                )
        status = assessment.status.value
        diagnostic_parts = [assessment.reason] if assessment.reason else []
        if assessment.missing_markers:
            diagnostic_parts.append(f"missing_markers={assessment.missing_markers!r}")
        if assessment.missing_title_markers:
            diagnostic_parts.append(
                f"missing_title_markers={assessment.missing_title_markers!r}"
            )
        if assessment.missing_selectors:
            diagnostic_parts.append(f"missing_selectors={assessment.missing_selectors!r}")
        diagnostic = "; ".join(diagnostic_parts) or None
        challenge = assessment.status is AccessStatus.CHALLENGE_REQUIRED
        denial = assessment.http_status in {401, 403, 429}
        return RealDiscoveryResponse(
            final_url=assessment.final_url,
            http_status=assessment.http_status,
            html=html,
            page_title=title,
            access_classification=status,
            access_diagnostic=diagnostic,
            challenge_detected=challenge,
            denial_detected=denial,
            captured_at_utc=datetime.now(timezone.utc).isoformat(),
        )


def run_authorized_real_candidate(
    *,
    plan: dict[str, Any],
    ledger: MatchDetailCampaignLedger,
    internal_id: str,
    authorization_id: str,
    confirmed_url: str,
    generation_root: Path,
    inventory_dir: Path,
    store_root: Path,
    data_root: Path,
    profile_dir: Path,
    confirmation: str,
    player_browser_idle_confirmation: str,
    session_factory: Callable[..., Any] = BrowserSessionManager,
) -> RealDiscoveryResult:
    """Execute exactly one already authorized candidate, never promoting it."""

    spec = _campaign_spec(plan)
    candidate = _candidate(spec, internal_id)
    if confirmation != REAL_EXECUTION_CONFIRMATION:
        raise MatchCampaignAuthorizationError("Falta confirmación de ejecución de una navegación")
    if player_browser_idle_confirmation != "PLAYER_BROWSER_IDLE_CONFIRMED":
        raise MatchCampaignAuthorizationError("Falta confirmación de que PLAYER liberó el navegador")
    if confirmed_url != candidate["source_match_url"]:
        raise MatchCampaignAuthorizationError("La URL confirmada no pertenece al candidato")
    requested_profile = profile_dir.expanduser().absolute()
    current = requested_profile
    while current != current.parent:
        if current.is_symlink():
            raise MatchCampaignAuthorizationError(
                f"El perfil/directory contiene symlink: {current}"
            )
        current = current.parent
    expected_profile = requested_profile.resolve()
    data_root_abs = data_root.expanduser().resolve(strict=True)
    try:
        expected_profile.relative_to(data_root_abs)
    except ValueError as exc:
        raise MatchCampaignAuthorizationError(
            "El perfil debe estar dentro del directorio de datos FootballDataHub"
        ) from exc
    if (
        expected_profile == data_root_abs
        or expected_profile.is_symlink()
        or expected_profile.name != f"match-detail-{candidate['source_match_id']}"
        or expected_profile.exists() and not expected_profile.is_dir()
    ):
        raise MatchCampaignAuthorizationError("El perfil no es un perfil dedicado permitido")
    store_abs = store_root.expanduser().absolute()
    if expected_profile == store_abs or store_abs in expected_profile.parents:
        raise MatchCampaignAuthorizationError("El perfil no puede estar dentro del almacén MATCH")
    browser_config = BrowserRuntimeConfig(
        profile_dir=expected_profile,
        backend="seleniumbase-pure-cdp",
        browser="chromium",
        use_xvfb=True,
        start_url="about:blank",
    )
    store = MatchDetailStore(store_root)
    with ledger.exclusive_lock():
        with store.exclusive_lock():
            evidence = verify_historical_stop_evidence(
                plan,
                data_root=data_root,
                generation_root=generation_root,
                inventory_dir=inventory_dir,
                store_root=store_root,
            )
            _store_checkpoint_is_unchanged(store, spec)
            generation = load_verified_match_generation(generation_root, data_root=data_root)
            inventory = build_match_detail_inventory(generation)
            reconciliation = store.reconcile(inventory)
            if reconciliation["integrity_blocked"]:
                raise MatchCampaignIntegrityError(
                    "El almacén MATCH tiene capturas o artefactos corruptos"
                )
            campaign_dir = ledger._ensure_initialized_locked(spec)
            preflight = ledger._preflight_locked(spec, campaign_dir)
            if preflight["blocked_reasons"]:
                raise MatchCampaignAuthorizationError(
                    f"La campaña está bloqueada: {preflight['blocked_reasons']}"
                )
            reviews = ledger._read_reviews(campaign_dir, spec)
            if (
                len(reviews) != 1
                or reviews[0]["decision"] != "scope_to_original_pilot"
                or reviews[0].get("evidence_verification") != evidence
            ):
                raise MatchCampaignAuthorizationError(
                    "La revisión histórica no habilita esta campaña/evidencia"
                )
            events = ledger._read_events(
                ledger._candidate_dir(campaign_dir, internal_id),
                spec["campaign_id"],
                internal_id,
            )
            authorizations = [
                event.get("authorization")
                for event in events
                if event.get("event_type") == "AUTHORIZED"
            ]
            if (
                len(authorizations) != 1
                or authorizations[0].get("authorization_id") != authorization_id
                or authorizations[0].get("source_match_id") != candidate["source_match_id"]
                or authorizations[0].get("source_match_url") != candidate["source_match_url"]
                or authorizations[0].get("capture_promotion_enabled") is not False
                or authorizations[0].get("maximum_navigations") != 1
                or authorizations[0].get("automatic_retries") != 0
                or ledger._state_from_events(events) != "AUTHORIZED"
            ):
                raise MatchCampaignAuthorizationError(
                    "No existe autorización individual vigente para este candidato/URL"
                )

            attempt_id = os.urandom(16).hex()
            ledger._append_event_locked(
                campaign_dir,
                spec,
                internal_id,
                {
                    "event_type": "STARTED",
                    "attempt_id": attempt_id,
                    "authorization_id": authorization_id,
                    "started_at_utc": _now(),
                    "source_match_id": candidate["source_match_id"],
                    "requested_url": candidate["source_match_url"],
                    "maximum_navigations": 1,
                    "browser_profile": str(expected_profile),
                    "browser_backend": "seleniumbase-pure-cdp",
                    "browser_display_mode": "managed_xvfb",
                },
            )
            try:
                response = _open_real_once(
                    browser_config,
                    url=candidate["source_match_url"],
                    session_factory=session_factory,
                )
            except Exception as exc:
                ledger._append_event_locked(
                    campaign_dir,
                    spec,
                    internal_id,
                    {
                        "event_type": "STOPPED",
                        "attempt_id": attempt_id,
                        "stopped_at_utc": _now(),
                        "error_code": "BROWSER_OR_NAVIGATION_ERROR",
                        "error_type": type(exc).__name__,
                        "diagnostic": str(exc)[:1000],
                        "http_status": None,
                        "capture_promoted": False,
                    },
                )
                return RealDiscoveryResult(
                    "STOPPED", internal_id, candidate["source_match_id"],
                    candidate["source_match_url"], None, None,
                    "BROWSER_OR_NAVIGATION_ERROR", attempt_id, None,
                    "BROWSER_OR_NAVIGATION_ERROR",
                )

            security_errors = ledger._security_errors(candidate, response)
            if response.access_classification not in {
                AccessStatus.VALID.value,
                AccessStatus.INVALID_CONTENT.value,
                AccessStatus.HTTP_ERROR.value,
            }:
                security_errors.insert(0, response.access_classification)
            if security_errors:
                error_code = security_errors[0]
                ledger._append_event_locked(
                    campaign_dir,
                    spec,
                    internal_id,
                    {
                        "event_type": "STOPPED",
                        "attempt_id": attempt_id,
                        "stopped_at_utc": _now(),
                        "error_code": error_code,
                        "diagnostics": security_errors,
                        "http_status": response.http_status,
                        "final_url": response.final_url,
                        "access_classification": response.access_classification,
                        "access_diagnostic": response.access_diagnostic,
                        "capture_promoted": False,
                    },
                )
                return RealDiscoveryResult(
                    "STOPPED", internal_id, candidate["source_match_id"],
                    candidate["source_match_url"], response.final_url,
                    response.http_status, response.access_classification,
                    attempt_id, None, error_code,
                    diagnostic=response.access_diagnostic,
                )
            try:
                artifact = ledger._store_discovery_artifact_locked(
                    campaign_dir, spec, candidate, response, attempt_id
                )
            except Exception as exc:
                ledger._append_event_locked(
                    campaign_dir,
                    spec,
                    internal_id,
                    {
                        "event_type": "STOPPED",
                        "attempt_id": attempt_id,
                        "stopped_at_utc": _now(),
                        "error_code": "DISCOVERY_STORAGE_ERROR",
                        "error_type": type(exc).__name__,
                        "diagnostic": str(exc)[:1000],
                        "http_status": response.http_status,
                        "capture_promoted": False,
                    },
                )
                return RealDiscoveryResult(
                    "STOPPED", internal_id, candidate["source_match_id"],
                    candidate["source_match_url"], response.final_url,
                    response.http_status, response.access_classification,
                    attempt_id, None, "DISCOVERY_STORAGE_ERROR",
                )
            ledger._append_event_locked(
                campaign_dir,
                spec,
                internal_id,
                {
                    "event_type": "DISCOVERY_REVIEW_REQUIRED",
                    "attempt_id": attempt_id,
                    "resolved_at_utc": _now(),
                    "http_status": response.http_status,
                    "final_url": response.final_url,
                    "access_classification": response.access_classification,
                    "access_diagnostic": response.access_diagnostic,
                    "artifact": artifact,
                    "capture_promoted": False,
                    "semantic_validation_performed": False,
                },
            )
            return RealDiscoveryResult(
                "DISCOVERY_REVIEW_REQUIRED", internal_id,
                candidate["source_match_id"], candidate["source_match_url"],
                response.final_url, response.http_status,
                response.access_classification, attempt_id, artifact, None,
                diagnostic=response.access_diagnostic,
            )
