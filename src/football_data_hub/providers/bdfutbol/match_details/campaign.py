"""Fail-closed, offline campaign ledger for explicitly authorized match samples.

This ledger module intentionally has no browser, HTTP, SeleniumBase, Playwright,
or production access-adapter imports. The isolated D1 real executor lives in a
separate module and uses these persistence primitives without promoting captures.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal, Protocol

from .discovery import discover_html_structure

CAMPAIGN_SCHEMA = "football_data_hub.match_detail_campaign.v1"
CAMPAIGN_MANIFEST_SCHEMA = "football_data_hub.match_detail_campaign_manifest.v1"
CAMPAIGN_EVENT_SCHEMA = "football_data_hub.match_detail_campaign_event.v1"
CAMPAIGN_REVIEW_SCHEMA = "football_data_hub.match_detail_legacy_stop_review.v1"
CAMPAIGN_REVIEW_MANIFEST_SCHEMA = "football_data_hub.match_detail_legacy_stop_review_manifest.v1"
CAMPAIGN_ARTIFACT_SCHEMA = "football_data_hub.match_detail_campaign_discovery.v1"
CAMPAIGN_ARTIFACT_MANIFEST_SCHEMA = "football_data_hub.match_detail_campaign_artifact_manifest.v1"
HUMAN_REVIEW_CONFIRMATION = "I_REVIEWED_MATCH_272582_AND_CHOOSE_A_SCOPE"
HUMAN_AUTHORIZATION_CONFIRMATION = "AUTHORIZE_ONE_DISCOVERY_NAVIGATION"

_EXPECTED_SAMPLE_IDS = ("272525", "272517", "272577", "272524", "269411")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_INTERNAL_ID = re.compile(r"^pf-2026-27-group-(?:i|ii)-bdfutbol-[0-9]+$")
_CAMPAIGN_ID = re.compile(r"^match-detail-sample-campaign-[0-9a-f]{16}$")
_EVENT_FILE = re.compile(r"^[0-9]{6}-[0-9a-f]{32}\.json$")
_REVIEW_ID = re.compile(r"^legacy-stop-review-[0-9a-f]{16}$")
_ARTIFACT_ID = re.compile(r"^discovery-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
_PUBLICATION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,95}$")


def review_completion_confirmation(
    source_match_id: str, source_html_sha256: str, details_sha256: str
) -> str:
    """Return a human confirmation bound to the reviewed match and content."""

    if not _is_sha(source_html_sha256) or not _is_sha(details_sha256):
        raise MatchCampaignAuthorizationError("La confirmación requiere hashes verificados")
    if not re.fullmatch(r"[0-9]{5,10}", source_match_id):
        raise MatchCampaignAuthorizationError("El ID de partido no es válido")
    return (
        f"COMPLETE-REVIEW-{source_match_id}-"
        f"{source_html_sha256[:12]}-{details_sha256[:12]}"
    )


class MatchCampaignError(ValueError):
    """Invalid campaign plan, ledger, or candidate transition."""


class MatchCampaignLocked(MatchCampaignError):
    """Another process currently owns the campaign ledger lock."""


class MatchCampaignIntegrityError(MatchCampaignError):
    """Persisted campaign evidence is corrupt, missing, or orphaned."""


class MatchCampaignAuthorizationError(MatchCampaignError):
    """A requested transition lacks the required explicit authorization."""


class CampaignDiscoveryResponse(Protocol):
    final_url: str | None
    http_status: int | None
    html: bytes
    page_title: str
    access_classification: str
    challenge_detected: bool
    denial_detected: bool
    captured_at_utc: str | None


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _read_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise MatchCampaignIntegrityError(f"{label} no es un archivo regular: {path}")
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatchCampaignIntegrityError(f"{label} no es JSON legible: {path}") from exc
    if not isinstance(value, dict) or raw != _canonical(value):
        raise MatchCampaignIntegrityError(f"{label} no es un objeto JSON canónico: {path}")
    return value, raw


def _reject_symlink_path(path: Path) -> None:
    current = path.expanduser().absolute()
    while current != current.parent:
        if current.is_symlink():
            raise MatchCampaignIntegrityError(f"No se permiten symlinks: {current}")
        current = current.parent


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _mkdirs_durable(path: Path) -> None:
    """Create directory components and sync each parent after the mkdir."""

    missing: list[Path] = []
    current = path
    while not current.exists():
        if current.is_symlink():
            raise MatchCampaignIntegrityError(f"No se permiten symlinks: {current}")
        missing.append(current)
        current = current.parent
    if current.is_symlink() or not current.is_dir():
        raise MatchCampaignIntegrityError(f"Directorio padre inválido: {current}")
    for directory in reversed(missing):
        directory.mkdir()
        _fsync_dir(directory.parent)
    _fsync_dir(path)


def _atomic_create(path: Path, raw: bytes) -> None:
    """Durably create a new immutable file; never replace an existing file."""

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
        _fsync_dir(path.parent)
    except FileExistsError as exc:
        raise MatchCampaignIntegrityError(f"No se sobrescribe evidencia: {path}") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _atomic_directory(parent: Path, name: str, files: dict[str, bytes]) -> Path:
    if not name or Path(name).name != name or name.startswith("."):
        raise MatchCampaignIntegrityError("Nombre de directorio inmutable no seguro")
    target = parent / name
    if target.exists() or target.is_symlink():
        raise MatchCampaignIntegrityError(f"No se sobrescribe evidencia: {target}")
    with tempfile.TemporaryDirectory(prefix=f".{name}.", dir=parent) as temporary_name:
        stage = Path(temporary_name)
        for relative, raw in files.items():
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
        for directory in sorted(
            (item for item in stage.rglob("*") if item.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            _fsync_dir(directory)
        _fsync_dir(stage)
        os.rename(stage, target)
        _fsync_dir(parent)
    return target


def _campaign_spec(plan: dict[str, Any]) -> dict[str, Any]:
    """Validate and freeze the canonical plan inputs, not its changing report."""

    if not isinstance(plan, dict) or plan.get("schema_version") != (
        "football_data_hub.match_detail_sampling_plan.v1"
    ):
        raise MatchCampaignError("Se requiere el plan canónico MATCH-01C-C")
    if (
        plan.get("mode") != "offline_read_only_sample_plan"
        or plan.get("http_enabled") is not False
        or plan.get("browser_started") is not False
        or plan.get("navigation_enabled") is not False
        or plan.get("promotion_enabled") is not False
    ):
        raise MatchCampaignError("El plan no es de solo lectura y sin navegación")
    plan_without_digest = {key: value for key, value in plan.items() if key != "campaign_digest"}
    plan_without_digest.pop("report_written_to", None)
    plan_digest = _sha(_canonical(plan_without_digest))
    if plan.get("campaign_digest") != plan_digest:
        raise MatchCampaignError("campaign_digest del plan no coincide")

    source = plan.get("source")
    campaign = plan.get("campaign")
    basis = campaign.get("campaign_basis") if isinstance(campaign, dict) else None
    candidates = plan.get("candidates")
    if not isinstance(source, dict) or not isinstance(campaign, dict) or not isinstance(basis, dict):
        raise MatchCampaignError("Faltan metadatos de campaña o procedencia")
    if not isinstance(candidates, list) or len(candidates) != 5:
        raise MatchCampaignError("La selección canónica debe contener cinco partidos")
    if tuple(str(item.get("source_match_id")) for item in candidates if isinstance(item, dict)) != _EXPECTED_SAMPLE_IDS:
        raise MatchCampaignError("La selección no coincide con los cinco candidatos de MATCH-01C-C")
    if len(candidates) != len([item for item in candidates if isinstance(item, dict)]):
        raise MatchCampaignError("Candidato no es un objeto")
    if campaign.get("is_authorization") is not False:
        raise MatchCampaignError("Un plan no puede constituir autorización")
    if campaign.get("authorization_status") != "NOT_AUTHORIZED":
        raise MatchCampaignError("El plan debe declarar todos los candidatos no autorizados")

    inventory_id = source.get("inventory_id")
    inventory_sha = source.get("inventory_sha256")
    inventory_manifest_sha = source.get("inventory_manifest_sha256")
    generation_id = source.get("generation_id")
    generation_sha = source.get("generation_manifest_sha256")
    selected_ids = [item.get("internal_id") for item in candidates]
    expected_basis = {
        "inventory_id": inventory_id,
        "inventory_sha256": inventory_sha,
        "source_generation_id": generation_id,
        "source_generation_manifest_sha256": generation_sha,
        "selected_internal_ids": selected_ids,
    }
    if basis != expected_basis:
        raise MatchCampaignError("El campaign_basis no coincide con sus fuentes y selección")
    campaign_id = campaign.get("campaign_id")
    expected_campaign_id = "match-detail-sample-campaign-" + _sha(_canonical(basis))[:16]
    if campaign_id != expected_campaign_id or not _CAMPAIGN_ID.fullmatch(str(campaign_id)):
        raise MatchCampaignError("campaign_id no deriva del basis canónico")
    if (
        not isinstance(inventory_id, str)
        or not inventory_id.startswith("match-detail-inventory-")
        or not _is_sha(inventory_sha)
        or not _is_sha(inventory_manifest_sha)
        or not isinstance(generation_id, str)
        or not _is_sha(generation_sha)
    ):
        raise MatchCampaignError("Hashes o identificadores de procedencia ausentes")
    if (
        source.get("competition") != "Primera Federación"
        or source.get("season") != "2026-27"
        or source.get("record_count", 0) < 5
    ):
        raise MatchCampaignError("La procedencia no corresponde a Primera Federación 2026/27")

    normalized_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        source_id = candidate.get("source_match_id")
        internal_id = candidate.get("internal_id")
        group = candidate.get("group")
        url = candidate.get("source_match_url")
        if (
            not isinstance(source_id, str)
            or not source_id.isdigit()
            or not isinstance(internal_id, str)
            or not _INTERNAL_ID.fullmatch(internal_id)
            or not internal_id.endswith(f"-bdfutbol-{source_id}")
            or group not in {"I", "II"}
            or f"group-{group.lower()}-" not in internal_id
            or url != f"https://www.bdfutbol.com/es/p/p.php?id={source_id}"
            or candidate.get("source_generation_id") != generation_id
            or candidate.get("source_generation_manifest_sha256") != generation_sha
            or not isinstance(candidate.get("source_capture_id"), str)
            or not _is_sha(candidate.get("source_snapshot_sha256"))
            or not _is_sha(candidate.get("source_matches_sha256"))
        ):
            raise MatchCampaignError(f"Identidad/URL/procedencia inválida para {source_id!r}")
        normalized_candidates.append(candidate)

    legacy = campaign.get("legacy_pilot_stop")
    diagnostic = legacy.get("diagnostic") if isinstance(legacy, dict) else None
    if (
        campaign.get("requires_explicit_review_of_legacy_stop") is not True
        or not isinstance(legacy, dict)
        or legacy.get("active_stop") is not True
        or legacy.get("checkpoint_status") != "stopped"
        or not _is_sha(legacy.get("checkpoint_sha256"))
        or not isinstance(diagnostic, dict)
        or diagnostic.get("source_match_id") != "272582"
        or diagnostic.get("error_code") != "IDENTITY_OR_CONTENT_UNVERIFIED"
        or diagnostic.get("http_status") != 200
        or not isinstance(diagnostic.get("navigation_attempt_id"), str)
    ):
        raise MatchCampaignError("No se acredita la parada histórica 272582 esperada")
    legacy_reference = {
        "inventory_id": inventory_id,
        "checkpoint_status": legacy["checkpoint_status"],
        "checkpoint_revision": legacy.get("checkpoint_revision"),
        "checkpoint_sha256": legacy["checkpoint_sha256"],
        "original_attempt_id": diagnostic["navigation_attempt_id"],
        "original_diagnostic_sha256": _sha(_canonical(diagnostic)),
        "original_diagnostic": diagnostic,
        "semantic_evidence_required": True,
    }
    return {
        "schema_version": CAMPAIGN_SCHEMA,
        "campaign_id": campaign_id,
        "campaign_digest": plan["campaign_digest"],
        "plan_sha256": plan_digest,
        "source": {
            key: source[key]
            for key in (
                "competition",
                "season",
                "generation_id",
                "generation_manifest_sha256",
                "generation_sources",
                "inventory_id",
                "inventory_sha256",
                "inventory_manifest_sha256",
                "record_count",
            )
        },
        "campaign_basis": basis,
        "selection_policy": plan.get("selection_policy"),
        "candidates": normalized_candidates,
        "legacy_stop_review_reference": legacy_reference,
    }


class MatchDetailCampaignLedger:
    """Append-only campaign ledger; records are isolated by candidate."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().absolute()
        self._thread_lock = threading.RLock()
        self._lock_file = None
        self._lock_depth = 0

    @contextmanager
    def exclusive_lock(self) -> Iterator[None]:
        if not self._thread_lock.acquire(blocking=False):
            raise MatchCampaignLocked("Otra operación tiene el lock local de campaña")
        try:
            if self._lock_depth == 0:
                _reject_symlink_path(self.root)
                _mkdirs_durable(self.root)
                lock_path = self.root / "campaign-ledger.lock"
                if lock_path.is_symlink():
                    raise MatchCampaignIntegrityError("campaign-ledger.lock no puede ser symlink")
                if not lock_path.exists() and any(
                    item.is_dir() and _CAMPAIGN_ID.fullmatch(item.name)
                    for item in self.root.iterdir()
                ):
                    raise MatchCampaignIntegrityError(
                        "Falta el lock de un ledger ya inicializado; no se recrea automáticamente"
                    )
                handle = lock_path.open("a+b")
                _fsync_dir(self.root)
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    handle.close()
                    raise MatchCampaignLocked("Otra ejecución posee el lock de campaña") from exc
                self._lock_file = handle
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1
                if self._lock_depth == 0 and self._lock_file is not None:
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                    self._lock_file.close()
                    self._lock_file = None
        finally:
            self._thread_lock.release()

    def _campaign_dir(self, spec: dict[str, Any]) -> Path:
        return self.root / spec["campaign_id"]

    def _ensure_initialized_locked(self, spec: dict[str, Any]) -> Path:
        campaign_dir = self._campaign_dir(spec)
        if campaign_dir.is_symlink():
            raise MatchCampaignIntegrityError("El directorio de campaña no puede ser symlink")
        if not campaign_dir.exists():
            manifest = {
                "schema_version": CAMPAIGN_MANIFEST_SCHEMA,
                "campaign_id": spec["campaign_id"],
                "campaign_sha256": _sha(_canonical(spec)),
                "candidate_count": len(spec["candidates"]),
                "event_log_policy": "append_only_hash_chained_by_candidate",
            }
            _atomic_directory(
                self.root,
                spec["campaign_id"],
                {"campaign.json": _canonical(spec), "manifest.json": _canonical(manifest)},
            )
        self._verify_campaign_dir(campaign_dir, spec)
        return campaign_dir

    def _verify_campaign_dir(self, campaign_dir: Path, expected: dict[str, Any]) -> None:
        if campaign_dir.is_symlink() or not campaign_dir.is_dir():
            raise MatchCampaignIntegrityError("El namespace de campaña no es directorio regular")
        persisted, raw = _read_json(campaign_dir / "campaign.json", label="campaign.json")
        manifest, manifest_raw = _read_json(campaign_dir / "manifest.json", label="manifest.json")
        expected_manifest = {
            "schema_version": CAMPAIGN_MANIFEST_SCHEMA,
            "campaign_id": expected["campaign_id"],
            "campaign_sha256": _sha(_canonical(expected)),
            "candidate_count": len(expected["candidates"]),
            "event_log_policy": "append_only_hash_chained_by_candidate",
        }
        if persisted != expected or raw != _canonical(expected):
            raise MatchCampaignIntegrityError("La identidad persistida difiere del plan canónico")
        if manifest != expected_manifest or manifest_raw != _canonical(expected_manifest):
            raise MatchCampaignIntegrityError("Manifiesto de campaña corrupto o discordante")
        allowed = {"campaign.json", "manifest.json", "candidates", "reviews"}
        unexpected = {item.name for item in campaign_dir.iterdir()} - allowed
        if unexpected:
            raise MatchCampaignIntegrityError(
                f"Archivos huérfanos en namespace de campaña: {sorted(unexpected)}"
            )

    def initialize(self, plan: dict[str, Any]) -> Path:
        """Explicitly create the immutable campaign identity; never authorizes."""

        spec = _campaign_spec(plan)
        with self.exclusive_lock():
            campaign_dir = self._ensure_initialized_locked(spec)
            self._preflight_locked(spec, campaign_dir)
            return campaign_dir

    def _candidate_dir(self, campaign_dir: Path, internal_id: str) -> Path:
        if not _INTERNAL_ID.fullmatch(internal_id):
            raise MatchCampaignError("internal_id no es seguro")
        return campaign_dir / "candidates" / internal_id

    def _read_events(self, candidate_dir: Path, campaign_id: str, internal_id: str) -> list[dict[str, Any]]:
        event_dir = candidate_dir / "events"
        if event_dir.is_symlink():
            raise MatchCampaignIntegrityError(f"events inválido para {internal_id}")
        if not event_dir.exists():
            return []
        if event_dir.is_symlink() or not event_dir.is_dir():
            raise MatchCampaignIntegrityError(f"events inválido para {internal_id}")
        entries = sorted(event_dir.iterdir(), key=lambda path: path.name)
        if any(path.is_symlink() or not path.is_file() or not _EVENT_FILE.fullmatch(path.name) for path in entries):
            raise MatchCampaignIntegrityError(f"Archivo de evento inesperado para {internal_id}")
        events: list[dict[str, Any]] = []
        previous = None
        for sequence, path in enumerate(entries, start=1):
            envelope, raw = _read_json(path, label="campaign event")
            payload = envelope.get("payload")
            expected_name = f"{sequence:06d}-{envelope.get('event_id')}.json"
            if (
                path.name != expected_name
                or envelope.get("schema_version") != CAMPAIGN_EVENT_SCHEMA
                or envelope.get("campaign_id") != campaign_id
                or envelope.get("internal_id") != internal_id
                or envelope.get("sequence") != sequence
                or envelope.get("previous_event_sha256") != previous
                or not isinstance(payload, dict)
                or envelope.get("payload_sha256") != _sha(_canonical(payload))
            ):
                raise MatchCampaignIntegrityError(f"Cadena/hash de eventos inválida para {internal_id}")
            previous = _sha(raw)
            events.append(
                {
                    **payload,
                    "campaign_id": campaign_id,
                    "sequence": sequence,
                    "event_sha256": previous,
                }
            )
        self._validate_transitions(events, internal_id)
        return events

    @staticmethod
    def _validate_transitions(events: list[dict[str, Any]], internal_id: str) -> None:
        state = "NOT_AUTHORIZED"
        for event in events:
            event_type = event.get("event_type")
            if event_type == "AUTHORIZED" and state == "NOT_AUTHORIZED":
                state = "AUTHORIZED"
            elif event_type == "STARTED" and state == "AUTHORIZED":
                state = "STARTED"
            elif event_type == "DISCOVERY_REVIEW_REQUIRED" and state == "STARTED":
                state = "DISCOVERY_REVIEW_REQUIRED"
            elif event_type == "STOPPED" and state == "STARTED":
                state = "STOPPED"
            elif event_type == "REVIEW_COMPLETED" and state == "DISCOVERY_REVIEW_REQUIRED":
                MatchDetailCampaignLedger._validate_review_completion_event(
                    events, event, internal_id
                )
                state = "REVIEW_COMPLETED"
            else:
                raise MatchCampaignIntegrityError(
                    f"Transición ilegal {event_type!r} para {internal_id} desde {state}"
                )

    @staticmethod
    def _validate_review_completion_event(
        events: list[dict[str, Any]], event: dict[str, Any], internal_id: str
    ) -> None:
        payload_fields = {
            "event_type",
            "reviewer",
            "completed_at_utc",
            "human_confirmation",
            "publication_evidence",
            "historic_acquisition_state",
            "capture_promoted",
        }
        if set(event) - {"campaign_id", "sequence", "event_sha256"} != payload_fields:
            raise MatchCampaignIntegrityError("El evento de cierre tiene campos no reconocidos")
        if len(events) < 3:
            raise MatchCampaignIntegrityError("Cierre de revisión sin adquisición previa")
        started = next(
            (item for item in events[:-1] if item.get("event_type") == "STARTED"), None
        )
        discovery = next(
            (item for item in events[:-1] if item.get("event_type") == "DISCOVERY_REVIEW_REQUIRED"),
            None,
        )
        evidence = event.get("publication_evidence")
        required = {
            "schema_version",
            "publication_id",
            "publication_manifest_sha256",
            "approval_sha256",
            "details_sha256",
            "source_html_sha256",
            "campaign_id",
            "internal_id",
            "source_match_id",
            "group",
            "source_capture_id",
            "inventory_id",
            "source_generation_id",
            "source_generation_manifest_sha256",
            "artifact_id",
            "artifact_manifest_sha256",
            "navigation_attempt_id",
        }
        if (
            started is None
            or discovery is None
            or not isinstance(evidence, dict)
            or set(evidence) != required
            or evidence.get("schema_version")
            != "football_data_hub.match_detail_campaign_review_completion_evidence.v1"
            or evidence.get("internal_id") != internal_id
            or evidence.get("source_match_id") != started.get("source_match_id")
            or evidence.get("campaign_id") != discovery.get("campaign_id")
            or evidence.get("navigation_attempt_id") != started.get("attempt_id")
            or evidence.get("artifact_id")
            != (discovery.get("artifact") or {}).get("artifact_id")
            or evidence.get("artifact_manifest_sha256")
            != (discovery.get("artifact") or {}).get("manifest_sha256")
            or evidence.get("source_html_sha256")
            != (discovery.get("artifact") or {}).get("source_html_sha256")
            or not _PUBLICATION_ID.fullmatch(str(evidence.get("publication_id", "")))
            or any(
                not _is_sha(evidence.get(key))
                for key in (
                    "publication_manifest_sha256",
                    "approval_sha256",
                    "details_sha256",
                    "source_html_sha256",
                    "source_generation_manifest_sha256",
                    "artifact_manifest_sha256",
                )
            )
            or not isinstance(event.get("reviewer"), str)
            or not event["reviewer"].strip()
            or not isinstance(event.get("completed_at_utc"), str)
            or event.get("historic_acquisition_state") != "DISCOVERY_REVIEW_REQUIRED"
            or event.get("capture_promoted") is not False
            or not re.fullmatch(r"[0-9]{5,10}", str(evidence.get("source_match_id", "")))
            or event.get("human_confirmation")
            != review_completion_confirmation(
                str(evidence.get("source_match_id", "")),
                str(evidence.get("source_html_sha256", "")),
                str(evidence.get("details_sha256", "")),
            )
        ):
            raise MatchCampaignIntegrityError(
                "El cierre de revisión no está enlazado al intento y publicación aprobada"
            )
        try:
            completed_at = datetime.fromisoformat(
                event["completed_at_utc"].replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise MatchCampaignIntegrityError("Fecha de cierre de revisión inválida") from exc
        if completed_at.tzinfo is None:
            raise MatchCampaignIntegrityError("La fecha de cierre debe incluir zona horaria")

    def _append_review_completion_locked(
        self,
        campaign_dir: Path,
        spec: dict[str, Any],
        *,
        internal_id: str,
        reviewer: str,
        confirmation: str,
        publication_evidence: dict[str, Any],
        completed_at_utc: str | None = None,
    ) -> dict[str, Any]:
        """Append a verified review closure; caller must hold ``exclusive_lock``."""

        self._verify_campaign_dir(campaign_dir, spec)
        candidate = next(
            (item for item in spec["candidates"] if item["internal_id"] == internal_id), None
        )
        if candidate is None:
            raise MatchCampaignAuthorizationError("El candidato no pertenece al plan")
        events = self._read_events(
            self._candidate_dir(campaign_dir, internal_id), spec["campaign_id"], internal_id
        )
        state = self._state_from_events(events)
        if state == "REVIEW_COMPLETED":
            previous = events[-1]
            if (
                previous.get("reviewer") == reviewer.strip()
                and previous.get("human_confirmation") == confirmation
                and previous.get("publication_evidence") == publication_evidence
            ):
                return {
                    "status": "REVIEW_ALREADY_COMPLETED",
                    "event_sequence": previous["sequence"],
                    "event_sha256": previous["event_sha256"],
                    "idempotent": True,
                }
            raise MatchCampaignAuthorizationError(
                "El cierre ya existe con otra identidad o evidencia; requiere revisión manual"
            )
        if state != "DISCOVERY_REVIEW_REQUIRED":
            raise MatchCampaignAuthorizationError(
                f"No se puede cerrar la revisión desde el estado {state}"
            )
        discovery = events[-1]
        expected_confirmation = review_completion_confirmation(
            candidate["source_match_id"],
            str((discovery.get("artifact") or {}).get("source_html_sha256", "")),
            str(publication_evidence.get("details_sha256", "")),
        )
        if confirmation != expected_confirmation:
            raise MatchCampaignAuthorizationError(
                "La confirmación no coincide con el partido y los hashes publicados"
            )
        payload = {
            "event_type": "REVIEW_COMPLETED",
            "reviewer": reviewer.strip(),
            "completed_at_utc": completed_at_utc or _now(),
            "human_confirmation": confirmation,
            "publication_evidence": publication_evidence,
            "historic_acquisition_state": "DISCOVERY_REVIEW_REQUIRED",
            "capture_promoted": False,
        }
        appended = self._append_event_locked(campaign_dir, spec, internal_id, payload)
        return {
            "status": "REVIEW_COMPLETED",
            "event_sequence": appended["sequence"],
            "event_sha256": appended["event_sha256"],
            "idempotent": False,
        }

    def _append_event_locked(
        self,
        campaign_dir: Path,
        spec: dict[str, Any],
        internal_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        candidate_dir = self._candidate_dir(campaign_dir, internal_id)
        events_dir = candidate_dir / "events"
        _mkdirs_durable(events_dir)
        events = self._read_events(candidate_dir, spec["campaign_id"], internal_id)
        previous = events[-1]["event_sha256"] if events else None
        event_id = uuid.uuid4().hex
        envelope = {
            "schema_version": CAMPAIGN_EVENT_SCHEMA,
            "campaign_id": spec["campaign_id"],
            "internal_id": internal_id,
            "sequence": len(events) + 1,
            "event_id": event_id,
            "previous_event_sha256": previous,
            "payload_sha256": _sha(_canonical(payload)),
            "payload": payload,
        }
        path = events_dir / f"{len(events) + 1:06d}-{event_id}.json"
        _atomic_create(path, _canonical(envelope))
        return {**payload, "sequence": len(events) + 1, "event_sha256": _sha(_canonical(envelope))}

    def _read_reviews(self, campaign_dir: Path, spec: dict[str, Any]) -> list[dict[str, Any]]:
        reviews_parent = campaign_dir / "reviews"
        if reviews_parent.is_symlink() or (
            reviews_parent.exists()
            and (
                not reviews_parent.is_dir()
                or {item.name for item in reviews_parent.iterdir()} - {"legacy-stop"}
            )
        ):
            raise MatchCampaignIntegrityError(
                "Namespace de revisiones contiene entradas inesperadas"
            )
        reviews_root = campaign_dir / "reviews" / "legacy-stop"
        if reviews_root.is_symlink():
            raise MatchCampaignIntegrityError("Directorio de revisiones inválido")
        if not reviews_root.exists():
            return []
        if reviews_root.is_symlink() or not reviews_root.is_dir():
            raise MatchCampaignIntegrityError("Directorio de revisiones inválido")
        reviews = []
        for review_dir in sorted(reviews_root.iterdir(), key=lambda path: path.name):
            if review_dir.is_symlink() or not review_dir.is_dir() or not _REVIEW_ID.fullmatch(review_dir.name):
                raise MatchCampaignIntegrityError("Registro de revisión inesperado")
            review, review_raw = _read_json(review_dir / "review.json", label="review.json")
            manifest, manifest_raw = _read_json(review_dir / "manifest.json", label="review manifest")
            expected = {
                "schema_version": CAMPAIGN_REVIEW_MANIFEST_SCHEMA,
                "review_id": review_dir.name,
                "review_sha256": _sha(review_raw),
                "campaign_id": spec["campaign_id"],
            }
            if (
                manifest != expected
                or manifest_raw != _canonical(expected)
                or review.get("schema_version") != CAMPAIGN_REVIEW_SCHEMA
                or review.get("review_id") != review_dir.name
                or review.get("campaign_id") != spec["campaign_id"]
                or review.get("legacy_stop_reference") != spec["legacy_stop_review_reference"]
                or review.get("human_confirmation") != HUMAN_REVIEW_CONFIRMATION
                or review.get("decision") not in {"scope_to_original_pilot", "block_entire_campaign"}
                or not isinstance(review.get("evidence_verification"), dict)
                or not isinstance(review.get("reviewer"), str)
                or not review["reviewer"].strip()
            ):
                raise MatchCampaignIntegrityError("Contenido de revisión histórica inválido")
            evidence = review["evidence_verification"]
            legacy = spec["legacy_stop_review_reference"]
            if (
                evidence.get("evidence_schema")
                != "football_data_hub.match_detail_legacy_stop_evidence.v1"
                or evidence.get("inventory_id") != spec["source"]["inventory_id"]
                or evidence.get("source_match_id") != "272582"
                or evidence.get("internal_id")
                != "pf-2026-27-group-ii-bdfutbol-272582"
                or evidence.get("generation_id") != spec["source"]["generation_id"]
                or evidence.get("generation_manifest_sha256")
                != spec["source"]["generation_manifest_sha256"]
                or evidence.get("original_attempt_id")
                != legacy["original_attempt_id"]
                or evidence.get("checkpoint_sha256") != legacy["checkpoint_sha256"]
                or evidence.get("checkpoint_revision") != legacy["checkpoint_revision"]
                or evidence.get("diagnostic_sha256")
                != legacy["original_diagnostic_sha256"]
                or not _is_sha(evidence.get("artifact_manifest_sha256"))
                or not _is_sha(evidence.get("source_html_sha256"))
                or not isinstance(evidence.get("artifact_id"), str)
                or not re.fullmatch(
                    r"[0-9]{8}T[0-9]{6}\.[0-9]{6}Z-[0-9a-f]{8}",
                    evidence["artifact_id"],
                )
                or evidence.get("artifact_relative_path")
                != f"diagnostics/{spec['source']['inventory_id']}/{evidence.get('artifact_id')}"
                or not isinstance(evidence.get("parser_version"), str)
                or not evidence["parser_version"].strip()
                or evidence.get("semantic_valid") is not True
                or evidence.get("promotion_eligible") is not False
            ):
                raise MatchCampaignIntegrityError(
                    "La revisión no contiene evidencia semántica histórica verificada"
                )
            actual_files = {
                item.relative_to(review_dir).as_posix()
                for item in review_dir.rglob("*")
                if item.is_file()
            }
            if actual_files != {"review.json", "manifest.json"}:
                raise MatchCampaignIntegrityError("La revisión tiene archivos huérfanos")
            reviews.append(review)
        return reviews

    def append_legacy_stop_review(
        self,
        plan: dict[str, Any],
        *,
        reviewer: str,
        decision: Literal["scope_to_original_pilot", "block_entire_campaign"],
        data_root: Path,
        generation_root: Path,
        inventory_dir: Path,
        store_root: Path,
        confirmation: str,
        reviewed_at_utc: str | None = None,
    ) -> str:
        """Append a human decision only after re-verifying the historical files."""

        spec = _campaign_spec(plan)
        if confirmation != HUMAN_REVIEW_CONFIRMATION:
            raise MatchCampaignAuthorizationError("Falta confirmación humana explícita")
        if decision not in {"scope_to_original_pilot", "block_entire_campaign"}:
            raise MatchCampaignAuthorizationError("Decisión de alcance histórica desconocida")
        reference = spec["legacy_stop_review_reference"]
        if reviewer.strip() == "":
            raise MatchCampaignAuthorizationError("Debe identificarse la persona revisora")
        from .historical_review import verify_historical_stop_evidence
        from .store import MatchDetailStore

        # Do not even initialize a campaign lock/root for a bad or stale proof.
        # Recheck under the ordered locks immediately before appending the record.
        verify_historical_stop_evidence(
            plan,
            data_root=data_root,
            generation_root=generation_root,
            inventory_dir=inventory_dir,
            store_root=store_root,
        )
        with self.exclusive_lock():
            with MatchDetailStore(store_root).exclusive_lock():
                evidence = verify_historical_stop_evidence(
                    plan,
                    data_root=data_root,
                    generation_root=generation_root,
                    inventory_dir=inventory_dir,
                    store_root=store_root,
                )
                campaign_dir = self._ensure_initialized_locked(spec)
                self._preflight_locked(spec, campaign_dir)
                reviews = self._read_reviews(campaign_dir, spec)
                if reviews:
                    raise MatchCampaignAuthorizationError(
                        "Ya existe una revisión histórica; no se sustituye ni se resuelve automáticamente"
                    )
                review_payload = {
                    "schema_version": CAMPAIGN_REVIEW_SCHEMA,
                    "campaign_id": spec["campaign_id"],
                    "legacy_stop_reference": reference,
                    "decision": decision,
                    "reviewer": reviewer.strip(),
                    "reviewed_at_utc": reviewed_at_utc or _now(),
                    "human_confirmation": confirmation,
                    "evidence_verification": evidence,
                    "authorizes_any_navigation": False,
                }
                review_id = "legacy-stop-review-" + _sha(_canonical(review_payload))[:16]
                review = {**review_payload, "review_id": review_id}
                review_raw = _canonical(review)
                manifest = {
                    "schema_version": CAMPAIGN_REVIEW_MANIFEST_SCHEMA,
                    "review_id": review_id,
                    "review_sha256": _sha(review_raw),
                    "campaign_id": spec["campaign_id"],
                }
                reviews_root = campaign_dir / "reviews" / "legacy-stop"
                _mkdirs_durable(reviews_root)
                _atomic_directory(
                    reviews_root,
                    review_id,
                    {"review.json": review_raw, "manifest.json": _canonical(manifest)},
                )
                return review_id

    def authorize_candidate(
        self,
        plan: dict[str, Any],
        *,
        internal_id: str,
        reviewer: str,
        review_id: str,
        confirmed_url: str,
        data_root: Path,
        generation_root: Path,
        inventory_dir: Path,
        store_root: Path,
        confirmation: str,
        authorized_at_utc: str | None = None,
    ) -> str:
        """Append a single-use authorization, with no command-line shortcut."""

        spec = _campaign_spec(plan)
        if confirmation != HUMAN_AUTHORIZATION_CONFIRMATION:
            raise MatchCampaignAuthorizationError("Falta confirmación individual explícita")
        candidate = next((item for item in spec["candidates"] if item["internal_id"] == internal_id), None)
        if candidate is None or candidate["source_match_url"] != confirmed_url:
            raise MatchCampaignAuthorizationError("El candidato o URL no pertenece al plan canónico")
        if not reviewer.strip():
            raise MatchCampaignAuthorizationError("Debe identificarse la persona autorizante")
        with self.exclusive_lock():
            from .historical_review import verify_historical_stop_evidence
            from .store import MatchDetailStore

            with MatchDetailStore(store_root).exclusive_lock():
                evidence = verify_historical_stop_evidence(
                    plan,
                    data_root=data_root,
                    generation_root=generation_root,
                    inventory_dir=inventory_dir,
                    store_root=store_root,
                )
                campaign_dir = self._ensure_initialized_locked(spec)
                reviews = self._read_reviews(campaign_dir, spec)
                matching = [review for review in reviews if review["review_id"] == review_id]
                if len(matching) != 1 or matching[0]["decision"] != "scope_to_original_pilot":
                    raise MatchCampaignAuthorizationError(
                        "No existe revisión humana válida que acote la parada al piloto original"
                    )
                if matching[0].get("evidence_verification") != evidence:
                    raise MatchCampaignAuthorizationError(
                        "La evidencia histórica cambió desde la revisión; requiere revisión manual nueva"
                    )
                preflight = self._preflight_locked(spec, campaign_dir)
                if preflight["blocked_reasons"]:
                    raise MatchCampaignAuthorizationError(
                        f"La campaña está bloqueada: {preflight['blocked_reasons']}"
                    )
                candidate_dir = self._candidate_dir(campaign_dir, internal_id)
                events = self._read_events(candidate_dir, spec["campaign_id"], internal_id)
                if events:
                    raise MatchCampaignAuthorizationError(
                        "El candidato ya tiene autorización o intento; no se emite otra"
                    )
                authorization_id = "match-detail-authorization-" + uuid.uuid4().hex
                payload = {
                    "event_type": "AUTHORIZED",
                    "authorization": {
                        "authorization_id": authorization_id,
                        "campaign_id": spec["campaign_id"],
                        "inventory_id": spec["source"]["inventory_id"],
                        "inventory_sha256": spec["source"]["inventory_sha256"],
                        "inventory_manifest_sha256": spec["source"]["inventory_manifest_sha256"],
                        "source_generation_id": spec["source"]["generation_id"],
                        "source_generation_manifest_sha256": spec["source"]["generation_manifest_sha256"],
                        "internal_id": internal_id,
                        "source_match_id": candidate["source_match_id"],
                        "source_match_url": candidate["source_match_url"],
                        "review_id": review_id,
                        "reviewer": reviewer.strip(),
                        "authorized_at_utc": authorized_at_utc or _now(),
                        "maximum_navigations": 1,
                        "automatic_retries": 0,
                        "capture_promotion_enabled": False,
                        "human_confirmation": confirmation,
                    },
                }
                self._append_event_locked(campaign_dir, spec, internal_id, payload)
                return authorization_id

    def _store_discovery_artifact_locked(
        self,
        campaign_dir: Path,
        spec: dict[str, Any],
        candidate: dict[str, Any],
        response: CampaignDiscoveryResponse,
        attempt_id: str,
    ) -> dict[str, str]:
        html = response.html
        report = discover_html_structure(html)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        artifact_id = f"discovery-{timestamp}-{uuid.uuid4().hex[:8]}"
        internal_id = candidate["internal_id"]
        artifact_dir = self._candidate_dir(campaign_dir, internal_id) / "artifacts"
        _mkdirs_durable(artifact_dir)
        metadata = {
            "schema_version": CAMPAIGN_ARTIFACT_SCHEMA,
            "campaign_id": spec["campaign_id"],
            "internal_id": internal_id,
            "source_match_id": candidate["source_match_id"],
            "requested_url": candidate["source_match_url"],
            "final_url": response.final_url,
            "http_status": response.http_status,
            "page_title": response.page_title,
            "access_classification": response.access_classification,
            "access_diagnostic": getattr(response, "access_diagnostic", None),
            "challenge_detected": response.challenge_detected,
            "denial_detected": response.denial_detected,
            "navigation_attempt_id": attempt_id,
            "capture_promoted": False,
            "semantic_identity_verified": False,
            "captured_at_utc": response.captured_at_utc or _now(),
        }
        files = {
            "source.html": html,
            "discovery.json": _canonical(report),
            "metadata.json": _canonical(metadata),
        }
        manifest = {
            "schema_version": CAMPAIGN_ARTIFACT_MANIFEST_SCHEMA,
            "artifact_id": artifact_id,
            "campaign_id": spec["campaign_id"],
            "internal_id": internal_id,
            "files": {
                name: {"sha256": _sha(raw), "bytes": len(raw)}
                for name, raw in sorted(files.items())
            },
        }
        files["manifest.json"] = _canonical(manifest)
        target = _atomic_directory(artifact_dir, artifact_id, files)
        return {
            "artifact_id": artifact_id,
            "artifact_relative_path": target.relative_to(campaign_dir).as_posix(),
            "manifest_sha256": _sha(files["manifest.json"]),
            "source_html_sha256": _sha(html),
        }

    def run_simulated_candidate(
        self,
        plan: dict[str, Any],
        *,
        internal_id: str,
        adapter: "SimulatedMatchAccessAdapter",
    ) -> dict[str, Any]:
        """Exercise state transitions with the local simulation adapter only."""

        if not isinstance(adapter, SimulatedMatchAccessAdapter):
            raise MatchCampaignAuthorizationError(
                "MATCH-01C-D0 no incluye adaptador de acceso real; solo simulación offline"
            )
        spec = _campaign_spec(plan)
        candidate = next((item for item in spec["candidates"] if item["internal_id"] == internal_id), None)
        if candidate is None:
            raise MatchCampaignError("El candidato no pertenece a la selección canónica")
        with self.exclusive_lock():
            campaign_dir = self._ensure_initialized_locked(spec)
            preflight = self._preflight_locked(spec, campaign_dir)
            if preflight["blocked_reasons"]:
                raise MatchCampaignAuthorizationError(
                    f"La campaña está bloqueada: {preflight['blocked_reasons']}"
                )
            review = self._effective_review(campaign_dir, spec)
            if review is None or review["decision"] != "scope_to_original_pilot":
                raise MatchCampaignAuthorizationError("Falta revisión histórica explícita válida")
            events = self._read_events(
                self._candidate_dir(campaign_dir, internal_id), spec["campaign_id"], internal_id
            )
            state = self._state_from_events(events)
            if state != "AUTHORIZED":
                raise MatchCampaignAuthorizationError(f"Estado del candidato: {state}")
            authorization = events[-1]["authorization"]
            attempt_id = uuid.uuid4().hex
            self._append_event_locked(
                campaign_dir,
                spec,
                internal_id,
                {
                    "event_type": "STARTED",
                    "attempt_id": attempt_id,
                    "authorization_id": authorization["authorization_id"],
                    "started_at_utc": _now(),
                    "source_match_id": candidate["source_match_id"],
                    "requested_url": candidate["source_match_url"],
                    "maximum_navigations": 1,
                },
            )
            try:
                response = adapter.open(candidate["source_match_url"])
            except Exception as exc:
                code = "SIMULATED_ACCESS_ERROR"
                self._append_event_locked(
                    campaign_dir,
                    spec,
                    internal_id,
                    {
                        "event_type": "STOPPED",
                        "attempt_id": attempt_id,
                        "stopped_at_utc": _now(),
                        "error_code": code,
                        "error_type": type(exc).__name__,
                        "diagnostic": str(exc)[:1000],
                        "http_status": None,
                        "capture_promoted": False,
                    },
                )
                return {"status": "STOPPED", "error_code": code, "attempt_id": attempt_id}
            if not isinstance(response, SimulatedAccessResponse):
                response = SimulatedAccessResponse(
                    final_url=None,
                    http_status=None,
                    html=b"",
                    page_title="",
                    access_classification="malformed_simulation_response",
                )
            security_errors = self._security_errors(candidate, response)
            if security_errors:
                code = security_errors[0]
                self._append_event_locked(
                    campaign_dir,
                    spec,
                    internal_id,
                    {
                        "event_type": "STOPPED",
                        "attempt_id": attempt_id,
                        "stopped_at_utc": _now(),
                        "error_code": code,
                        "diagnostics": security_errors,
                        "http_status": response.http_status,
                        "final_url": response.final_url,
                        "access_classification": response.access_classification,
                        "capture_promoted": False,
                    },
                )
                return {"status": "STOPPED", "error_code": code, "attempt_id": attempt_id}
            try:
                artifact = self._store_discovery_artifact_locked(
                    campaign_dir, spec, candidate, response, attempt_id
                )
            except Exception as exc:
                self._append_event_locked(
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
                return {"status": "STOPPED", "error_code": "DISCOVERY_STORAGE_ERROR", "attempt_id": attempt_id}
            self._append_event_locked(
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
                    "artifact": artifact,
                    "capture_promoted": False,
                    "semantic_validation_performed": False,
                },
            )
            return {
                "status": "DISCOVERY_REVIEW_REQUIRED",
                "attempt_id": attempt_id,
                "artifact": artifact,
                "capture_promoted": False,
            }

    @staticmethod
    def _security_errors(
        candidate: dict[str, Any], response: CampaignDiscoveryResponse
    ) -> list[str]:
        errors = []
        if isinstance(response.http_status, bool) or not isinstance(response.http_status, int):
            errors.append("HTTP_UNKNOWN")
        elif response.http_status != 200:
            errors.append(f"HTTP_{response.http_status}")
        if response.challenge_detected:
            errors.append("CHALLENGE_REQUIRED")
        if response.denial_detected:
            errors.append("ACCESS_DENIED")
        if response.final_url != candidate["source_match_url"]:
            errors.append("UNEXPECTED_URL")
        if not isinstance(response.html, bytes) or not response.html.strip():
            errors.append("DOCUMENT_OR_STRUCTURE_ERROR")
        return errors

    @staticmethod
    def _state_from_events(events: list[dict[str, Any]]) -> str:
        if not events:
            return "NOT_AUTHORIZED"
        last = events[-1]
        if last["event_type"] == "AUTHORIZED":
            return "AUTHORIZED"
        if last["event_type"] == "STARTED":
            return "INTERRUPTED_REQUIRES_REVIEW"
        return last["event_type"]

    def _effective_review(self, campaign_dir: Path, spec: dict[str, Any]) -> dict[str, Any] | None:
        reviews = self._read_reviews(campaign_dir, spec)
        if len(reviews) > 1:
            decisions = {item["decision"] for item in reviews}
            if len(decisions) > 1:
                raise MatchCampaignIntegrityError("Revisiones históricas contradictorias")
            raise MatchCampaignIntegrityError("Hay revisiones repetidas; requiere revisión manual")
        return reviews[0] if reviews else None

    def _verify_artifact_reference(
        self,
        campaign_dir: Path,
        spec: dict[str, Any],
        internal_id: str,
        artifact_ref: dict[str, Any],
    ) -> None:
        relative = artifact_ref.get("artifact_relative_path")
        if not isinstance(relative, str) or ".." in Path(relative).parts or Path(relative).is_absolute():
            raise MatchCampaignIntegrityError("Ruta de artefacto insegura")
        artifact_dir = campaign_dir / relative
        if artifact_dir.is_symlink() or not artifact_dir.is_dir() or not _ARTIFACT_ID.fullmatch(artifact_ref.get("artifact_id", "")):
            raise MatchCampaignIntegrityError("Artefacto referenciado ausente")
        manifest, manifest_raw = _read_json(artifact_dir / "manifest.json", label="artifact manifest")
        if _sha(manifest_raw) != artifact_ref.get("manifest_sha256"):
            raise MatchCampaignIntegrityError("Hash del manifiesto del artefacto no coincide")
        if (
            manifest.get("schema_version") != CAMPAIGN_ARTIFACT_MANIFEST_SCHEMA
            or manifest.get("artifact_id") != artifact_ref["artifact_id"]
            or manifest.get("campaign_id") != spec["campaign_id"]
            or manifest.get("internal_id") != internal_id
        ):
            raise MatchCampaignIntegrityError("Manifiesto de artefacto no coincide con candidato")
        expected_files = {"source.html", "discovery.json", "metadata.json"}
        if set(manifest.get("files", {})) != expected_files:
            raise MatchCampaignIntegrityError("El manifiesto del artefacto tiene archivos inesperados")
        for name, details in manifest.get("files", {}).items():
            path = artifact_dir / name
            if path.is_symlink() or not path.is_file() or not isinstance(details, dict):
                raise MatchCampaignIntegrityError("Archivo de artefacto ausente o inválido")
            raw = path.read_bytes()
            if _sha(raw) != details.get("sha256") or len(raw) != details.get("bytes"):
                raise MatchCampaignIntegrityError(f"Hash de artefacto no coincide: {name}")
        actual_files = {
            item.relative_to(artifact_dir).as_posix()
            for item in artifact_dir.rglob("*")
            if item.is_file()
        }
        if actual_files != expected_files | {"manifest.json"}:
            raise MatchCampaignIntegrityError("El artefacto contiene archivos huérfanos")
        metadata, _ = _read_json(artifact_dir / "metadata.json", label="artifact metadata")
        if (
            metadata.get("internal_id") != internal_id
            or metadata.get("capture_promoted") is not False
            or metadata.get("semantic_identity_verified") is not False
            or _sha((artifact_dir / "source.html").read_bytes()) != artifact_ref.get("source_html_sha256")
        ):
            raise MatchCampaignIntegrityError("La evidencia de descubrimiento perdió su contexto")

    def _preflight_locked(self, spec: dict[str, Any], campaign_dir: Path) -> dict[str, Any]:
        self._verify_campaign_dir(campaign_dir, spec)
        reviews = self._read_reviews(campaign_dir, spec)
        if len(reviews) > 1:
            raise MatchCampaignIntegrityError("Revisiones históricas múltiples requieren revisión manual")
        candidates_report = []
        referenced_artifacts: set[str] = set()
        known_ids = {candidate["internal_id"] for candidate in spec["candidates"]}
        candidates_root = campaign_dir / "candidates"
        if candidates_root.is_symlink() or (
            candidates_root.exists() and not candidates_root.is_dir()
        ):
            raise MatchCampaignIntegrityError("Directorio candidates inválido")
        if candidates_root.exists():
            unknown = {item.name for item in candidates_root.iterdir()} - known_ids
            if unknown:
                raise MatchCampaignIntegrityError(f"Registros de candidatos desconocidos: {sorted(unknown)}")
        for candidate in spec["candidates"]:
            internal_id = candidate["internal_id"]
            candidate_dir = self._candidate_dir(campaign_dir, internal_id)
            if candidate_dir.is_symlink() or (
                candidate_dir.exists() and not candidate_dir.is_dir()
            ):
                raise MatchCampaignIntegrityError(f"Directorio de candidato inválido: {internal_id}")
            events = self._read_events(candidate_dir, spec["campaign_id"], internal_id)
            for event in events:
                if event["event_type"] == "AUTHORIZED":
                    authorization = event.get("authorization")
                    matching_reviews = [
                        item
                        for item in reviews
                        if item["review_id"] == authorization.get("review_id")
                    ]
                    expected_candidate = next(
                        item
                        for item in spec["candidates"]
                        if item["internal_id"] == internal_id
                    )
                    if (
                        not isinstance(authorization, dict)
                        or authorization.get("campaign_id") != spec["campaign_id"]
                        or authorization.get("inventory_id")
                        != spec["source"]["inventory_id"]
                        or authorization.get("inventory_sha256")
                        != spec["source"]["inventory_sha256"]
                        or authorization.get("inventory_manifest_sha256")
                        != spec["source"]["inventory_manifest_sha256"]
                        or authorization.get("source_generation_id")
                        != spec["source"]["generation_id"]
                        or authorization.get("source_generation_manifest_sha256")
                        != spec["source"]["generation_manifest_sha256"]
                        or authorization.get("internal_id") != internal_id
                        or authorization.get("source_match_id")
                        != expected_candidate["source_match_id"]
                        or authorization.get("source_match_url")
                        != expected_candidate["source_match_url"]
                        or len(matching_reviews) != 1
                        or matching_reviews[0]["decision"] != "scope_to_original_pilot"
                        or authorization.get("maximum_navigations") != 1
                        or authorization.get("automatic_retries") != 0
                        or authorization.get("capture_promotion_enabled") is not False
                        or authorization.get("human_confirmation")
                        != HUMAN_AUTHORIZATION_CONFIRMATION
                    ):
                        raise MatchCampaignIntegrityError(
                            f"Contrato de autorización inválido para {internal_id}"
                        )
                if event["event_type"] == "STARTED":
                    prior_auth = next(
                        (item.get("authorization", {}) for item in events[: event["sequence"] - 1]
                         if item["event_type"] == "AUTHORIZED"),
                        {},
                    )
                    if (
                        event.get("authorization_id") != prior_auth.get("authorization_id")
                        or event.get("requested_url")
                        != next(
                            item["source_match_url"]
                            for item in spec["candidates"]
                            if item["internal_id"] == internal_id
                        )
                        or event.get("maximum_navigations") != 1
                    ):
                        raise MatchCampaignIntegrityError(
                            f"Reserva STARTED no coincide con la autorización para {internal_id}"
                        )
                artifact_ref = event.get("artifact")
                if artifact_ref is not None:
                    if event["event_type"] != "DISCOVERY_REVIEW_REQUIRED" or not isinstance(artifact_ref, dict):
                        raise MatchCampaignIntegrityError("Referencia de artefacto en evento inesperado")
                    self._verify_artifact_reference(campaign_dir, spec, internal_id, artifact_ref)
                    referenced_artifacts.add(artifact_ref["artifact_relative_path"])
                if event["event_type"] == "REVIEW_COMPLETED":
                    evidence = event["publication_evidence"]
                    if (
                        evidence.get("campaign_id") != spec["campaign_id"]
                        or evidence.get("inventory_id") != spec["source"]["inventory_id"]
                        or evidence.get("source_generation_id") != spec["source"]["generation_id"]
                        or evidence.get("source_generation_manifest_sha256")
                        != spec["source"]["generation_manifest_sha256"]
                        or evidence.get("source_match_id")
                        != next(
                            item["source_match_id"]
                            for item in spec["candidates"]
                            if item["internal_id"] == internal_id
                        )
                        or evidence.get("group")
                        != next(
                            item["group"]
                            for item in spec["candidates"]
                            if item["internal_id"] == internal_id
                        )
                        or evidence.get("source_capture_id")
                        != next(
                            item["source_capture_id"]
                            for item in spec["candidates"]
                            if item["internal_id"] == internal_id
                        )
                    ):
                        raise MatchCampaignIntegrityError(
                            f"Cierre de revisión discordante con el plan para {internal_id}"
                        )
            if candidate_dir.exists():
                unexpected_candidate_entries = {
                    item.name for item in candidate_dir.iterdir()
                } - {"events", "artifacts"}
                if unexpected_candidate_entries:
                    raise MatchCampaignIntegrityError(
                        f"Archivos huérfanos en candidato {internal_id}: "
                        f"{sorted(unexpected_candidate_entries)}"
                    )
                event_dir = candidate_dir / "events"
                artifact_dir = candidate_dir / "artifacts"
                if event_dir.is_symlink() or artifact_dir.is_symlink():
                    raise MatchCampaignIntegrityError("events/artifacts no pueden ser symlinks")
                if not events and any((candidate_dir / name).exists() for name in ("events", "artifacts")):
                    raise MatchCampaignIntegrityError(f"Candidato huérfano sin evento: {internal_id}")
                if artifact_dir.exists():
                    if artifact_dir.is_symlink() or not artifact_dir.is_dir():
                        raise MatchCampaignIntegrityError("Directorio artifacts inválido")
                    for item in artifact_dir.iterdir():
                        relative = item.relative_to(campaign_dir).as_posix()
                        if relative not in referenced_artifacts:
                            raise MatchCampaignIntegrityError(f"Artefacto huérfano: {relative}")
                if event_dir.exists() and not events:
                    raise MatchCampaignIntegrityError(f"Directorio events vacío huérfano: {internal_id}")
            state = self._state_from_events(events)
            candidates_report.append(
                {
                    "internal_id": internal_id,
                    "source_match_id": candidate["source_match_id"],
                    "state": state,
                    "acquisition_state": (
                        "DISCOVERY_REVIEW_REQUIRED"
                        if state == "REVIEW_COMPLETED"
                        else state
                    ),
                    "review_status": (
                        "completed" if state == "REVIEW_COMPLETED" else "pending"
                    ),
                    "authorization_consumed": any(item["event_type"] == "STARTED" for item in events),
                    "navigation_count": sum(item["event_type"] == "STARTED" for item in events),
                    "capture_promoted": False,
                }
            )
        review = reviews[0] if reviews else None
        reasons = []
        if review is None:
            reasons.append("LEGACY_STOP_REVIEW_REQUIRED")
        elif review["decision"] == "block_entire_campaign":
            reasons.append("LEGACY_REVIEW_BLOCKS_CAMPAIGN")
        for item in candidates_report:
            if item["state"] == "INTERRUPTED_REQUIRES_REVIEW":
                reasons.append(f"INTERRUPTED_REQUIRES_REVIEW:{item['source_match_id']}")
            elif item["state"] == "STOPPED":
                reasons.append(f"CANDIDATE_STOPPED_REQUIRES_REVIEW:{item['source_match_id']}")
            elif item["state"] == "DISCOVERY_REVIEW_REQUIRED":
                reasons.append(f"DISCOVERY_REVIEW_REQUIRED:{item['source_match_id']}")
        return {
            "schema_version": "football_data_hub.match_detail_campaign_preflight.v1",
            "campaign_id": spec["campaign_id"],
            "status": "READY_FOR_FUTURE_HUMAN_AUTHORIZATION" if not reasons else "BLOCKED",
            "blocked_reasons": reasons,
            "historical_review": (
                {"review_id": review["review_id"], "decision": review["decision"]}
                if review
                else None
            ),
            "candidates": candidates_report,
            "http_enabled": False,
            "browser_started": False,
            "navigation_enabled": False,
            "real_access_adapter_enabled": False,
            "real_access_adapter_implemented": True,
            "capture_promotion_enabled": False,
        }

    def preflight(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Read-only status; does not create the campaign directory or lock file."""

        spec = _campaign_spec(plan)
        campaign_dir = self._campaign_dir(spec)
        _reject_symlink_path(self.root)
        if campaign_dir.is_symlink():
            raise MatchCampaignIntegrityError("Namespace de campaña no puede ser symlink")
        if not campaign_dir.exists():
            return {
                "schema_version": "football_data_hub.match_detail_campaign_preflight.v1",
                "campaign_id": spec["campaign_id"],
                "status": "BLOCKED",
                "blocked_reasons": ["LEGACY_STOP_REVIEW_REQUIRED"],
                "historical_review": None,
                "candidates": [
                    {
                        "internal_id": candidate["internal_id"],
                        "source_match_id": candidate["source_match_id"],
                        "state": "NOT_AUTHORIZED",
                        "authorization_consumed": False,
                        "navigation_count": 0,
                        "capture_promoted": False,
                    }
                    for candidate in spec["candidates"]
                ],
                "http_enabled": False,
                "browser_started": False,
                "navigation_enabled": False,
                "real_access_adapter_enabled": False,
                "real_access_adapter_implemented": True,
                "capture_promotion_enabled": False,
            }
        if campaign_dir.is_symlink() or not campaign_dir.is_dir():
            raise MatchCampaignIntegrityError("Namespace de campaña no válido")
        lock_path = self.root / "campaign-ledger.lock"
        if lock_path.is_symlink():
            raise MatchCampaignIntegrityError("Lock de campaña inválido")
        if lock_path.exists():
            if not lock_path.is_file():
                raise MatchCampaignIntegrityError("Lock de campaña inválido")
            with lock_path.open("rb") as handle:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise MatchCampaignLocked("El ledger cambia durante el preflight") from exc
                try:
                    return self._preflight_locked(spec, campaign_dir)
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        raise MatchCampaignIntegrityError("Falta campaign-ledger.lock en un ledger persistido")

    def inspect_persisted_campaign_read_only(
        self, campaign_dir: Path, *, internal_id: str
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        """Verify a persisted campaign snapshot without creating or changing files.

        This is intended for offline evidence readers. It validates the campaign
        manifest, review records, candidate event hash chains, artifact hashes,
        and state transitions using the same rules as the acquisition preflight.
        """

        _reject_symlink_path(campaign_dir)
        candidate = campaign_dir.expanduser().absolute()
        if candidate.is_symlink() or not candidate.is_dir():
            raise MatchCampaignIntegrityError("La campaña persistida no es un directorio regular")
        root = candidate.resolve(strict=True)
        configured_root = self.root.expanduser().resolve(strict=True)
        if root.parent != configured_root:
            raise MatchCampaignIntegrityError("La campaña no pertenece al ledger configurado")
        spec, _ = _read_json(root / "campaign.json", label="campaign.json")
        if (
            spec.get("schema_version") != CAMPAIGN_SCHEMA
            or spec.get("campaign_id") != root.name
            or not isinstance(spec.get("campaign_basis"), dict)
            or not isinstance(spec.get("candidates"), list)
        ):
            raise MatchCampaignIntegrityError("Identidad del snapshot de campaña inválida")
        basis = spec["campaign_basis"]
        source = spec.get("source")
        if not isinstance(source, dict):
            raise MatchCampaignIntegrityError("El snapshot de campaña no contiene source")
        expected_basis = {
            "inventory_id": source.get("inventory_id"),
            "inventory_sha256": source.get("inventory_sha256"),
            "source_generation_id": source.get("generation_id"),
            "source_generation_manifest_sha256": source.get(
                "generation_manifest_sha256"
            ),
            "selected_internal_ids": [
                item.get("internal_id")
                for item in spec["candidates"]
                if isinstance(item, dict)
            ],
        }
        if (
            len(expected_basis["selected_internal_ids"]) != len(spec["candidates"])
            or basis != expected_basis
            or spec["campaign_id"]
            != "match-detail-sample-campaign-" + _sha(_canonical(basis))[:16]
        ):
            raise MatchCampaignIntegrityError("El basis/campaign_id no coincide con la campaña")
        self._verify_campaign_dir(root, spec)
        report = self._preflight_locked(spec, root)
        if internal_id not in {item["internal_id"] for item in spec["candidates"]}:
            raise MatchCampaignIntegrityError("El candidato no forma parte de la campaña")
        events = self._read_events(
            root / "candidates" / internal_id, spec["campaign_id"], internal_id
        )
        return spec, report, events


class SimulatedMatchAccessAdapter:
    """Local-only fake adapter. It contains no networking or browser code."""

    def __init__(self, response: "SimulatedAccessResponse | None" = None, error: BaseException | None = None):
        self.response = response
        self.error = error
        self.calls: list[str] = []

    def open(self, url: str) -> "SimulatedAccessResponse":
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise RuntimeError("No se configuró respuesta simulada")
        return self.response


class SimulatedAccessResponse:
    """Explicit synthetic outcome; byte contents are test fixtures only."""

    def __init__(
        self,
        *,
        final_url: str | None,
        http_status: int | None,
        html: bytes,
        page_title: str = "Synthetic fixture",
        access_classification: str = "simulated",
        challenge_detected: bool = False,
        denial_detected: bool = False,
        captured_at_utc: str | None = None,
    ) -> None:
        self.final_url = final_url
        self.http_status = http_status
        self.html = html
        self.page_title = page_title
        self.access_classification = access_classification
        self.challenge_detected = challenge_detected
        self.denial_detected = denial_detected
        self.captured_at_utc = captured_at_utc
