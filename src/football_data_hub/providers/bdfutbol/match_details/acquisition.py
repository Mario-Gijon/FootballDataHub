"""Single-match, one-navigation structural discovery pilot.

This adapter intentionally never calls ``store_valid_capture``. Without a
BDFutbol-specific parser validated against a real page, even an HTTP 200 page
can only be preserved as isolated discovery evidence for manual review.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

from football_data_hub.providers.bdfutbol.access import AccessStatus

from .discovery import discover_html_structure
from .inventory import INVENTORY_SCHEMA
from .store import MatchDetailStore, MatchDetailStoreError

PILOT_SOURCE_MATCH_ID = "272582"
PILOT_INTERNAL_ID = "pf-2026-27-group-ii-bdfutbol-272582"
PILOT_GENERATION_ID = "match-00-4ad1d610507e425d"
PILOT_GENERATION_MANIFEST_SHA256 = (
    "00166887b13413e3e6a5344fa1c64d52db8d38800f3ef9f282237584b3e65fbf"
)


def _inventory_id_matches(inventory: dict[str, Any]) -> bool:
    inventory_id = inventory.get("inventory_id")
    unsigned = {key: value for key, value in inventory.items() if key != "inventory_id"}
    canonical = (
        json.dumps(unsigned, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    expected = "match-detail-inventory-" + hashlib.sha256(canonical).hexdigest()[:16]
    return inventory_id == expected


class MatchDiscoveryAccess(Protocol):
    def open(
        self, url: str, *, required_markers: tuple[str, ...], **kwargs: Any
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class MatchDiscoveryPilotResult:
    status: str
    internal_id: str
    source_match_id: str
    requested_url: str
    final_url: str | None
    http_status: int | None
    access_status: str
    duration_ms: int
    discovery_artifact: dict[str, str] | None
    diagnostic: dict[str, Any]
    capture_promoted: bool = False
    navigation_count: int = 1


class MatchDiscoveryPilotBlocked(RuntimeError):
    """The fixed pilot is absent, invalid, or already stopped in its store."""


def select_pilot_record(inventory: dict[str, Any]) -> dict[str, Any]:
    """Select the authorized pilot from a validated persisted inventory object."""

    matches = inventory.get("matches")
    if (
        inventory.get("schema_version") != INVENTORY_SCHEMA
        or inventory.get("source") != "BDFutbol"
        or inventory.get("competition") != "Primera Federación"
        or inventory.get("season") != "2026-27"
        or inventory.get("source_generation", {}).get("generation_id")
        != PILOT_GENERATION_ID
        or inventory.get("source_generation", {}).get("manifest_sha256")
        != PILOT_GENERATION_MANIFEST_SHA256
        or not _inventory_id_matches(inventory)
        or not isinstance(inventory.get("inventory_id"), str)
        or not isinstance(matches := inventory.get("matches"), list)
    ):
        raise MatchDiscoveryPilotBlocked(
            "El inventario no contiene una lista de partidos"
        )
    selected = [
        record
        for record in matches
        if isinstance(record, dict)
        and record.get("source_match_id") == PILOT_SOURCE_MATCH_ID
    ]
    if len(selected) != 1:
        raise MatchDiscoveryPilotBlocked(
            "El partido piloto no es único dentro del inventario"
        )
    record = selected[0]
    if (
        record.get("internal_id") != PILOT_INTERNAL_ID
        or record.get("season") != "2026-27"
        or record.get("competition") != "Primera Federación"
        or record.get("group") != "II"
        or record.get("home_team_id") != 49
        or record.get("away_team_id") != 94
        or record.get("reference_result") != {"home_goals": 3, "away_goals": 3}
        or record.get("source_match_url")
        != "https://www.bdfutbol.com/es/p/p.php?id=272582"
        or record.get("source_generation_id") != PILOT_GENERATION_ID
        or record.get("source_generation_manifest_sha256")
        != inventory.get("source_generation", {}).get("manifest_sha256")
        or record.get("acquisition_status") != "pending"
        or record.get("validation_status") != "not_acquired"
    ):
        raise MatchDiscoveryPilotBlocked(
            "La identidad o procedencia del piloto no coincide"
        )
    return record


def _diagnostic_code(status: str, http_status: int | None) -> str:
    if status == "DISCOVERY_STORAGE_ERROR":
        return "DISCOVERY_STORAGE_ERROR"
    if status == AccessStatus.CHALLENGE_REQUIRED.value:
        return "CHALLENGE_REQUIRED"
    if status == AccessStatus.HTTP_ERROR.value:
        return f"HTTP_{http_status}" if http_status is not None else "HTTP_UNKNOWN"
    if status == AccessStatus.NAVIGATION_ERROR.value:
        return "NAVIGATION_ERROR"
    if status == AccessStatus.DOCUMENT_ERROR.value:
        return "DOCUMENT_ERROR"
    if status == AccessStatus.INVALID_URL.value:
        return "UNEXPECTED_URL"
    if status == AccessStatus.INVALID_CONTENT.value:
        return "IDENTITY_OR_CONTENT_UNVERIFIED"
    return "DISCOVERY_REVIEW_REQUIRED"


def run_match_discovery_pilot(
    *,
    inventory: dict[str, Any],
    access: MatchDiscoveryAccess,
    store: MatchDetailStore,
) -> MatchDiscoveryPilotResult:
    """Make at most one injected access call and persist diagnostic-only output."""

    record = select_pilot_record(inventory)
    requested_url = record["source_match_url"]
    with store.exclusive_lock():
        reconciliation = store.reconcile(inventory)
        if reconciliation["blocked"] or reconciliation["active_stop"]:
            raise MatchDiscoveryPilotBlocked(
                "El almacén tiene integridad bloqueada o una parada activa; no se navega"
            )
        started = time.monotonic()
        opened = None
        http_status: int | None = None
        final_url: str | None = None
        access_status = "NOT_STARTED"
        elapsed_ms = 0
        try:
            # The inventory ID is a weak preliminary body marker for access
            # classification only. It is not identity or structural evidence.
            opened = access.open(
                requested_url,
                required_markers=(PILOT_SOURCE_MATCH_ID,),
                settle_ms=750,
                max_wait_seconds=12.0,
            )
            assessment = opened.assessment
            access_status = str(assessment.status.value)
            http_status = assessment.http_status
            final_url = assessment.final_url
            title = assessment.page_title or ""
            elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
            artifact = None
            diagnostic_text = (
                f"access_status={access_status}; preliminary_match_id_marker="
                f"{'present' if access_status == AccessStatus.VALID.value else 'not_confirmed'}; "
                "the match ID marker is not semantic identity validation; "
                "discovery requires human semantic review before any parser or promotion."
            )

            if (
                http_status == 200
                and final_url == requested_url
                and access_status
                in {
                    AccessStatus.VALID.value,
                    AccessStatus.INVALID_CONTENT.value,
                }
                and opened.visit is not None
            ):
                try:
                    html_text = opened.visit.document.html()
                    html = html_text.encode("utf-8")
                    title = opened.visit.document.title() or title
                    report = discover_html_structure(html)
                except Exception as exc:
                    access_status = AccessStatus.DOCUMENT_ERROR.value
                    diagnostic_text += (
                        f" HTML discovery failed: {type(exc).__name__}: {exc}"
                    )
                else:
                    elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
                    try:
                        artifact = store.store_discovery_artifact(
                            inventory,
                            record,
                            html,
                            report,
                            requested_url=requested_url,
                            final_url=final_url,
                            http_status=http_status,
                            access_status=assessment.status.value,
                            page_title=title,
                            duration_ms=elapsed_ms,
                        )
                    except MatchDetailStoreError as exc:
                        access_status = "DISCOVERY_STORAGE_ERROR"
                        diagnostic_text += (
                            f" Discovery artifact could not be safely stored: {exc}"
                        )
                    else:
                        diagnostic_text += (
                            " Browser DOM HTML and generic structural observations were saved under "
                            "diagnostics/; this artifact is not a valid capture."
                        )

            code = _diagnostic_code(access_status, http_status)
            diagnostic = store.record_diagnostic(
                inventory,
                internal_id=record["internal_id"],
                requested_url=requested_url,
                final_url=final_url,
                http_status=http_status,
                error_code=code,
                stage="structural_discovery",
                diagnostic=diagnostic_text,
                access_status=access_status,
                duration_ms=elapsed_ms,
            )
            return MatchDiscoveryPilotResult(
                status="DISCOVERY_REVIEW_REQUIRED" if artifact else "STOPPED",
                internal_id=record["internal_id"],
                source_match_id=record["source_match_id"],
                requested_url=requested_url,
                final_url=final_url,
                http_status=http_status,
                access_status=access_status,
                duration_ms=elapsed_ms,
                discovery_artifact=artifact,
                diagnostic=diagnostic,
            )
        except MatchDiscoveryPilotBlocked:
            raise
        except MatchDetailStoreError:
            raise
        except Exception as exc:
            elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
            diagnostic = store.record_diagnostic(
                inventory,
                internal_id=record["internal_id"],
                requested_url=requested_url,
                final_url=final_url,
                http_status=http_status,
                error_code="PILOT_ADAPTER_ERROR",
                stage="structural_discovery",
                diagnostic=f"{type(exc).__name__}: {exc}",
                access_status=access_status
                if access_status != "NOT_STARTED"
                else "ADAPTER_ERROR",
                duration_ms=elapsed_ms,
            )
            return MatchDiscoveryPilotResult(
                status="STOPPED",
                internal_id=record["internal_id"],
                source_match_id=record["source_match_id"],
                requested_url=requested_url,
                final_url=final_url,
                http_status=http_status,
                access_status=access_status
                if access_status != "NOT_STARTED"
                else "ADAPTER_ERROR",
                duration_ms=elapsed_ms,
                discovery_artifact=None,
                diagnostic=diagnostic,
            )
        finally:
            if opened is not None:
                opened.close()
