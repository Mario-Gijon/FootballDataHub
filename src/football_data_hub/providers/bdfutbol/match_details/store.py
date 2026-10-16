"""Almacén versionado de snapshots individuales, sin cliente HTTP."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from football_data_hub.domain.matches.details import (
    MatchDetail,
    MatchDetailValidation,
    match_detail_from_payload,
    validate_match_detail_contract,
)
from football_data_hub.providers.bdfutbol.access import (
    contains_bdfutbol_access_challenge,
)

from .inventory import _canonical_json
from .policy import (
    CaptureDecision,
    REQUIRED_STRUCTURE_EVIDENCE,
    assess_capture,
    validate_promotion_evidence,
)

_INVENTORY_ID = re.compile(r"^match-detail-inventory-[a-f0-9]{16}$")
_CAPTURE_ID = re.compile(r"^\d{8}T\d{6}\.\d{6}Z-[a-f0-9]{8}$")


class MatchDetailStoreError(RuntimeError):
    """El almacén no permite una operación íntegra o reanudable."""


class MatchDetailStoreLocked(MatchDetailStoreError):
    """Otra adquisición ya posee el bloqueo exclusivo del almacén."""


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatchDetailStoreError(f"No se puede leer snapshot JSON: {path}") from exc
    if not isinstance(value, dict):
        raise MatchDetailStoreError(f"El snapshot JSON no es un objeto: {path}")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    raw = _canonical_json(value)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _atomic_directory(parent: Path, name: str, files: dict[str, bytes]) -> Path:
    """Install an immutable evidence directory with hashes prepared by caller."""

    if not name or Path(name).name != name or name.startswith("."):
        raise MatchDetailStoreError("Nombre de artefacto no seguro")
    target = parent / name
    if target.exists() or target.is_symlink():
        raise MatchDetailStoreError(f"El artefacto ya existe: {name}")
    with tempfile.TemporaryDirectory(prefix=f".{name}.", dir=parent) as temporary:
        stage = Path(temporary)
        for relative, content in files.items():
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        for path in stage.rglob("*"):
            if path.is_file():
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
            elif path.is_dir():
                _fsync_directory(path)
        _fsync_directory(stage)
        try:
            os.rename(stage, target)
        except FileExistsError as exc:
            raise MatchDetailStoreError(f"El artefacto ya existe: {name}") from exc
        _fsync_directory(parent)
    return target


def _safe_directory(path: Path) -> Path:
    candidate = path.expanduser().absolute()
    current = candidate
    while current != current.parent:
        if current.is_symlink():
            raise MatchDetailStoreError(
                f"No se permiten symlinks en la ruta del almacén: {current}"
            )
        current = current.parent
    candidate.mkdir(parents=True, exist_ok=True)
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        raise MatchDetailStoreError(f"No es un directorio: {resolved}")
    return resolved


def _inventory_records(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    inventory_id = inventory.get("inventory_id")
    if not isinstance(inventory_id, str) or not _INVENTORY_ID.fullmatch(inventory_id):
        raise MatchDetailStoreError(
            "inventory_id no tiene el formato namespaced esperado"
        )
    records = inventory.get("matches")
    if not isinstance(records, list) or not records:
        raise MatchDetailStoreError("El inventario no contiene partidos")
    unsigned_inventory = {
        key: value for key, value in inventory.items() if key != "inventory_id"
    }
    expected_id = (
        "match-detail-inventory-" + _sha256(_canonical_json(unsigned_inventory))[:16]
    )
    if expected_id != inventory_id:
        raise MatchDetailStoreError(
            "El hash de inventory_id no coincide con el contenido"
        )
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(
            record.get("internal_id"), str
        ):
            raise MatchDetailStoreError("Registro de inventario inválido")
        if record["internal_id"] in result:
            raise MatchDetailStoreError("El inventario contiene internal_id duplicados")
        result[record["internal_id"]] = record
    return result


class MatchDetailStore:
    """Snapshots inmutables y estado recuperable por generación de inventario."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().absolute()
        self._lock_guard = threading.RLock()
        self._lock_file = None
        self._lock_depth = 0

    @contextmanager
    def exclusive_lock(self) -> Iterator[None]:
        if not self._lock_guard.acquire(blocking=False):
            raise MatchDetailStoreLocked(
                "Otra operación local posee el bloqueo del almacén"
            )
        try:
            if self._lock_depth == 0:
                root = _safe_directory(self.root)
                lock_path = root / "acquisition.lock"
                if lock_path.is_symlink():
                    raise MatchDetailStoreError(
                        "El archivo de bloqueo no puede ser un symlink"
                    )
                lock_file = lock_path.open("a+b")
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    lock_file.close()
                    raise MatchDetailStoreLocked(
                        f"Ya existe una adquisición en curso para {root}"
                    ) from exc
                self._lock_file = lock_file
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
            self._lock_guard.release()

    def _inventory_dir(self, inventory_id: str) -> Path:
        if not _INVENTORY_ID.fullmatch(inventory_id):
            raise MatchDetailStoreError("inventory_id no seguro")
        return self.root / "inventories" / inventory_id

    def _state_path(self, inventory_id: str) -> Path:
        return self.root / "states" / f"{inventory_id}.json"

    def _prepare_inventory_locked(self, inventory: dict[str, Any]) -> Path:
        records = _inventory_records(inventory)
        inventory_id = inventory["inventory_id"]
        inventory_content = _canonical_json(inventory)
        unsigned = {
            key: value for key, value in inventory.items() if key != "inventory_id"
        }
        expected_id = (
            "match-detail-inventory-" + _sha256(_canonical_json(unsigned))[:16]
        )
        if expected_id != inventory_id:
            raise MatchDetailStoreError(
                "El ID del inventario no coincide con su contenido"
            )
        manifest = {
            "schema_version": "football_data_hub.match_detail_inventory_manifest.v1",
            "inventory_id": inventory_id,
            "inventory_sha256": _sha256(inventory_content),
            "record_count": len(records),
            "source_generation": inventory.get("source_generation"),
        }
        manifest_content = _canonical_json(manifest)
        inventories = _safe_directory(self.root / "inventories")
        target = inventories / inventory_id
        if target.exists():
            if (
                target.is_symlink()
                or not (target / "inventory.json").is_file()
                or not (target / "manifest.json").is_file()
                or (target / "inventory.json").read_bytes() != inventory_content
                or (target / "manifest.json").read_bytes() != manifest_content
            ):
                raise MatchDetailStoreError(
                    "El inventario existente no coincide; no se sobrescribe"
                )
        else:
            with tempfile.TemporaryDirectory(
                prefix=f".{inventory_id}.", dir=inventories
            ) as temporary:
                stage = Path(temporary)
                (stage / "inventory.json").write_bytes(inventory_content)
                (stage / "manifest.json").write_bytes(manifest_content)
                for name in ("inventory.json", "manifest.json"):
                    with (stage / name).open("rb") as stream:
                        os.fsync(stream.fileno())
                _fsync_directory(stage)
                try:
                    os.rename(stage, target)
                except FileExistsError:
                    if (
                        target / "inventory.json"
                    ).read_bytes() != inventory_content or (
                        target / "manifest.json"
                    ).read_bytes() != manifest_content:
                        raise MatchDetailStoreError(
                            "Una generación concurrente difiere; no se sobrescribe"
                        )
                else:
                    _fsync_directory(inventories)
        states = _safe_directory(self.root / "states")
        state_path = states / f"{inventory_id}.json"
        if state_path.is_symlink():
            raise MatchDetailStoreError("El checkpoint no puede ser un symlink")
        if not state_path.exists():
            _atomic_json(
                state_path,
                {
                    "schema_version": "football_data_hub.match_detail_state.v1",
                    "inventory_id": inventory_id,
                    "status": "in_progress",
                    "revision": 0,
                    "verified_snapshots": [],
                    "discovery_artifacts": [],
                    "diagnostics": [],
                    "updated_at_utc": _utc_now(),
                },
            )
        return target

    def prepare_inventory(self, inventory: dict[str, Any]) -> Path:
        with self.exclusive_lock():
            return self._prepare_inventory_locked(inventory)

    def _load_state_locked(self, inventory_id: str) -> dict[str, Any]:
        path = self._state_path(inventory_id)
        if path.is_symlink():
            raise MatchDetailStoreError("El checkpoint no puede ser un symlink")
        if not path.exists():
            return {
                "schema_version": "football_data_hub.match_detail_state.v1",
                "inventory_id": inventory_id,
                "status": "in_progress",
                "revision": 0,
                "verified_snapshots": [],
                "discovery_artifacts": [],
                "diagnostics": [],
            }
        state = _read_object(path)
        if (
            state.get("inventory_id") != inventory_id
            or state.get("schema_version") != "football_data_hub.match_detail_state.v1"
        ):
            raise MatchDetailStoreError("El checkpoint no corresponde al inventario")
        return state

    def record_diagnostic(
        self,
        inventory: dict[str, Any],
        *,
        internal_id: str,
        requested_url: str | None,
        error_code: str,
        diagnostic: str,
        http_status: int | None = None,
        stage: str = "access_or_validation",
        final_url: str | None = None,
        access_status: str | None = None,
        duration_ms: int | None = None,
    ) -> dict[str, Any]:
        records = _inventory_records(inventory)
        if internal_id not in records:
            raise MatchDetailStoreError("El diagnóstico no corresponde al inventario")
        expected_url = records[internal_id]["source_match_url"]
        requested_value = (
            requested_url if isinstance(requested_url, str) else expected_url
        )
        event = {
            "recorded_at_utc": _utc_now(),
            "internal_id": internal_id,
            "source_match_id": records[internal_id]["source_match_id"],
            "requested_url": requested_value,
            "observed_requested_url": requested_url,
            "expected_url": expected_url,
            "final_url": final_url,
            "http_status": http_status,
            "error_code": error_code,
            "stage": stage,
            "diagnostic": diagnostic,
            "stop_acquisition": True,
        }
        if access_status is not None:
            event["access_status"] = access_status
        if duration_ms is not None:
            if (
                not isinstance(duration_ms, int)
                or isinstance(duration_ms, bool)
                or duration_ms < 0
            ):
                raise MatchDetailStoreError(
                    "duration_ms debe ser un entero no negativo"
                )
            event["duration_ms"] = duration_ms
        with self.exclusive_lock():
            self._prepare_inventory_locked(inventory)
            state = self._load_state_locked(inventory["inventory_id"])
            state.setdefault("diagnostics", []).append(event)
            state["status"] = "stopped"
            state["revision"] = int(state.get("revision", 0)) + 1
            state["updated_at_utc"] = _utc_now()
            _atomic_json(self._state_path(inventory["inventory_id"]), state)
        return event

    def store_discovery_artifact(
        self,
        inventory: dict[str, Any],
        calendar_record: dict[str, Any],
        source_html: bytes,
        discovery_report: dict[str, Any],
        *,
        requested_url: str,
        final_url: str,
        http_status: int | None,
        access_status: str,
        page_title: str,
        duration_ms: int | None,
    ) -> dict[str, str]:
        """Persist an unverified 200 page outside captures; never promotes it.

        Only a same-resource HTTP 200 non-challenge candidate is eligible for
        diagnostic preservation. The report must be generic discovery output,
        explicitly marked as having no confirmed semantic mapping.
        """

        records = _inventory_records(inventory)
        internal_id = calendar_record.get("internal_id")
        if internal_id not in records or records[internal_id] != calendar_record:
            raise MatchDetailStoreError(
                "El descubrimiento no corresponde al inventario"
            )
        expected_url = calendar_record.get("source_match_url")
        if (
            not isinstance(source_html, bytes)
            or not source_html
            or http_status != 200
            or requested_url != expected_url
            or final_url != expected_url
            or access_status not in {"VALID", "INVALID_CONTENT"}
        ):
            raise MatchDetailStoreError(
                "Solo se conserva como descubrimiento HTML HTTP 200 del recurso esperado"
            )
        if contains_bdfutbol_access_challenge(
            page_title=page_title,
            body_text=source_html.decode("utf-8", errors="replace"),
            http_status=http_status,
        ):
            raise MatchDetailStoreError(
                "No se conserva HTML con marcadores de desafío de acceso"
            )
        html_hash = _sha256(source_html)
        if (
            discovery_report.get("schema_version")
            != "football_data_hub.match_detail_discovery.v1"
            or discovery_report.get("semantic_mapping_confirmed") is not False
            or discovery_report.get("source_html_sha256") != html_hash
            or discovery_report.get("source_html_bytes") != len(source_html)
        ):
            raise MatchDetailStoreError(
                "El informe de descubrimiento no está ligado al HTML"
            )
        with self.exclusive_lock():
            self._prepare_inventory_locked(inventory)
            reconciliation = self.reconcile(inventory)
            if reconciliation["blocked"] or reconciliation["active_stop"]:
                raise MatchDetailStoreError(
                    "No se puede añadir evidencia con integridad bloqueada o parada activa"
                )
            discovery_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            discovery_id += f"-{uuid4().hex[:8]}"
            report_content = _canonical_json(discovery_report)
            metadata = {
                "schema_version": "football_data_hub.match_detail_discovery_artifact.v1",
                "artifact_type": "discovery_only_unverified",
                "discovery_id": discovery_id,
                "inventory_id": inventory["inventory_id"],
                "source_generation_id": calendar_record["source_generation_id"],
                "source_capture_id": calendar_record["source_capture_id"],
                "internal_id": internal_id,
                "source_match_id": calendar_record["source_match_id"],
                "season": calendar_record["season"],
                "competition": calendar_record["competition"],
                "group": calendar_record["group"],
                "matchday": calendar_record["matchday"],
                "requested_url": requested_url,
                "final_url": final_url,
                "http_status": http_status,
                "access_status": access_status,
                "page_title": page_title,
                "source_representation": (
                    "BrowserDocument.html() DOM serialization; transport response bytes unavailable"
                ),
                "captured_at_utc": _utc_now(),
                "duration_ms": duration_ms,
                "source_html_sha256": html_hash,
                "source_html_bytes": len(source_html),
                "discovery_sha256": _sha256(report_content),
                "promotion_eligible": False,
            }
            metadata_content = _canonical_json(metadata)
            files = {
                "raw/source.html": source_html,
                "discovery.json": report_content,
                "metadata.json": metadata_content,
            }
            manifest = {
                "schema_version": "football_data_hub.match_detail_discovery_manifest.v1",
                "artifact_type": "discovery_only_unverified",
                "discovery_id": discovery_id,
                "inventory_id": inventory["inventory_id"],
                "files": {
                    name: {"sha256": _sha256(content), "bytes": len(content)}
                    for name, content in files.items()
                },
            }
            files["manifest.json"] = _canonical_json(manifest)
            artifact_root = _safe_directory(
                self.root / "diagnostics" / inventory["inventory_id"]
            )
            target = _atomic_directory(artifact_root, discovery_id, files)
            state = self._load_state_locked(inventory["inventory_id"])
            state.setdefault("discovery_artifacts", []).append(
                {
                    "discovery_id": discovery_id,
                    "internal_id": internal_id,
                    "source_html_sha256": html_hash,
                    "manifest_sha256": _sha256((target / "manifest.json").read_bytes()),
                }
            )
            state["revision"] = int(state.get("revision", 0)) + 1
            state["updated_at_utc"] = _utc_now()
            _atomic_json(self._state_path(inventory["inventory_id"]), state)
            return {
                "discovery_id": discovery_id,
                "path": str(target),
                "source_html_sha256": html_hash,
                "manifest_sha256": _sha256((target / "manifest.json").read_bytes()),
            }

    def stop_for_validation(
        self,
        inventory: dict[str, Any],
        calendar_record: dict[str, Any],
        detail: MatchDetail,
        validation: MatchDetailValidation,
    ) -> CaptureDecision:
        """Persiste un rechazo y deja el checkpoint detenido; no reintenta."""

        decision = assess_capture(calendar_record, detail, validation)
        if decision.accepted:
            raise MatchDetailStoreError(
                "La validación fue aceptada; no corresponde detenerla"
            )
        self.record_diagnostic(
            inventory,
            internal_id=calendar_record["internal_id"],
            requested_url=validation.requested_url,
            http_status=validation.http_status,
            error_code=decision.code,
            stage="access_or_validation",
            diagnostic="; ".join(validation.diagnostics) or decision.message,
            final_url=validation.final_url,
        )
        return decision

    def store_valid_capture(
        self,
        inventory: dict[str, Any],
        calendar_record: dict[str, Any],
        html: bytes,
        detail: MatchDetail,
        validation: MatchDetailValidation,
        *,
        parser_version: str,
    ) -> str:
        """Promueve únicamente una observación verificada; el HTML queda inmutable."""

        with self.exclusive_lock():
            return self._store_valid_capture_locked(
                inventory,
                calendar_record,
                html,
                detail,
                validation,
                parser_version=parser_version,
            )

    def _store_valid_capture_locked(
        self,
        inventory: dict[str, Any],
        calendar_record: dict[str, Any],
        html: bytes,
        detail: MatchDetail,
        validation: MatchDetailValidation,
        *,
        parser_version: str,
    ) -> str:
        records = _inventory_records(inventory)
        internal_id = calendar_record.get("internal_id")
        if internal_id not in records or records[internal_id] != calendar_record:
            raise MatchDetailStoreError(
                "El partido no pertenece al inventario verificado"
            )
        if not isinstance(html, bytes) or not html:
            raise MatchDetailStoreError(
                "El HTML original debe ser un bloque de bytes no vacío"
            )
        self._prepare_inventory_locked(inventory)
        reconciliation = self.reconcile(inventory)
        if reconciliation["blocked"]:
            raise MatchDetailStoreError(
                "La integridad de snapshots o checkpoints está bloqueada"
            )
        if reconciliation["active_stop"]:
            raise MatchDetailStoreError(
                "La adquisición tiene una parada activa; requiere resolución explícita"
            )
        existing = reconciliation["verified_by_internal_id"].get(internal_id)
        if existing is not None:
            return existing["capture_id"]
        decision = assess_capture(calendar_record, detail, validation)
        if not decision.accepted:
            raise MatchDetailStoreError(
                f"Captura no promovida ({decision.code}): {decision.message}"
            )
        if (
            detail.source_generation_id
            != inventory["source_generation"]["generation_id"]
        ):
            raise MatchDetailStoreError(
                "El detalle apunta a otra generación de calendario"
            )
        html_hash = _sha256(html)
        evidence_errors = validate_promotion_evidence(
            calendar_record,
            detail,
            html,
            parser_version=parser_version,
        )
        if evidence_errors:
            diagnostic = "; ".join(evidence_errors)
            self.record_diagnostic(
                inventory,
                internal_id=internal_id,
                requested_url=validation.requested_url,
                http_status=validation.http_status,
                error_code="SOURCE_EVIDENCE_UNVERIFIED",
                stage="identity_and_structure_evidence",
                diagnostic=diagnostic,
                final_url=validation.final_url,
            )
            raise MatchDetailStoreError(
                f"Captura no promovida (SOURCE_EVIDENCE_UNVERIFIED): {diagnostic}"
            )
        if detail.source_html_sha256 not in {None, html_hash}:
            raise MatchDetailStoreError(
                "El hash HTML del modelo no coincide con los bytes"
            )
        capture_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        capture_id += f"-{uuid4().hex[:8]}"
        discrepancies = tuple(
            dict.fromkeys((*detail.discrepancies, *decision.discrepancies))
        )
        detail = replace(
            detail,
            capture_id=capture_id,
            captured_at_utc=_utc_now(),
            source_html_sha256=html_hash,
            discrepancies=discrepancies,
        )
        detail_payload = asdict(detail)
        detail_content = _canonical_json(detail_payload)
        validation_payload = asdict(validation)
        validation_payload["decision"] = {
            "accepted": True,
            "code": decision.code,
            "message": decision.message,
        }
        validation_payload["discrepancies"] = [asdict(item) for item in discrepancies]
        validation_content = _canonical_json(validation_payload)
        metadata = {
            "schema_version": "football_data_hub.bdfutbol.match_detail_capture.v1",
            "capture_id": capture_id,
            "inventory_id": inventory["inventory_id"],
            "source_generation_id": inventory["source_generation"]["generation_id"],
            "source_generation_manifest_sha256": inventory["source_generation"][
                "manifest_sha256"
            ],
            "source_capture_id": calendar_record["source_capture_id"],
            "internal_id": internal_id,
            "source_match_id": calendar_record["source_match_id"],
            "season": calendar_record["season"],
            "competition": calendar_record["competition"],
            "group": calendar_record["group"],
            "matchday": calendar_record["matchday"],
            "home_team_id": calendar_record["home_team_id"],
            "away_team_id": calendar_record["away_team_id"],
            "requested_url": validation.requested_url,
            "final_url": validation.final_url,
            "http_status": validation.http_status,
            "access_status": "VALID",
            "captured_at_utc": detail.captured_at_utc,
            "source_html_sha256": html_hash,
            "source_html_bytes": len(html),
            "match_detail_sha256": _sha256(detail_content),
            "validation_sha256": _sha256(validation_content),
            "parser_version": parser_version,
        }
        capture_root = _safe_directory(
            self.root / "captures" / inventory["inventory_id"]
        )
        target = capture_root / capture_id
        if target.exists() or target.is_symlink():
            raise MatchDetailStoreError(f"capture_id ya existe: {capture_id}")
        with tempfile.TemporaryDirectory(
            prefix=f".{capture_id}.", dir=capture_root
        ) as temporary:
            stage = Path(temporary)
            (stage / "raw").mkdir()
            (stage / "raw" / "source.html").write_bytes(html)
            (stage / "match_detail.json").write_bytes(detail_content)
            (stage / "validation.json").write_bytes(validation_content)
            metadata_content = _canonical_json(metadata)
            (stage / "metadata.json").write_bytes(metadata_content)
            snapshot_manifest = {
                "schema_version": "football_data_hub.bdfutbol.match_detail_snapshot_manifest.v1",
                "capture_id": capture_id,
                "inventory_id": inventory["inventory_id"],
                "files": {
                    "raw/source.html": {"sha256": html_hash, "bytes": len(html)},
                    "match_detail.json": {
                        "sha256": _sha256(detail_content),
                        "bytes": len(detail_content),
                    },
                    "validation.json": {
                        "sha256": _sha256(validation_content),
                        "bytes": len(validation_content),
                    },
                    "metadata.json": {
                        "sha256": _sha256(metadata_content),
                        "bytes": len(metadata_content),
                    },
                },
            }
            (stage / "manifest.json").write_bytes(_canonical_json(snapshot_manifest))
            for path in stage.rglob("*"):
                if path.is_file():
                    with path.open("rb") as stream:
                        os.fsync(stream.fileno())
                elif path.is_dir():
                    _fsync_directory(path)
            _fsync_directory(stage)
            try:
                os.rename(stage, target)
            except FileExistsError as exc:
                raise MatchDetailStoreError(
                    f"capture_id ya existe: {capture_id}"
                ) from exc
            else:
                _fsync_directory(capture_root)
        state = self._load_state_locked(inventory["inventory_id"])
        state.setdefault("verified_snapshots", []).append(
            {
                "capture_id": capture_id,
                "internal_id": internal_id,
                "source_html_sha256": html_hash,
                "match_detail_sha256": metadata["match_detail_sha256"],
                "snapshot_manifest_sha256": _sha256(
                    (target / "manifest.json").read_bytes()
                ),
            }
        )
        state["status"] = "in_progress"
        state["revision"] = int(state.get("revision", 0)) + 1
        state["updated_at_utc"] = _utc_now()
        _atomic_json(self._state_path(inventory["inventory_id"]), state)
        return capture_id

    def _verify_capture(
        self,
        capture_path: Path,
        inventory_id: str,
        records: dict[str, dict[str, Any]],
    ) -> tuple[str, dict[str, Any]]:
        if capture_path.is_symlink() or not capture_path.is_dir():
            raise MatchDetailStoreError(
                "Entrada de captura no es un directorio regular"
            )
        for rel in (
            "manifest.json",
            "metadata.json",
            "validation.json",
            "match_detail.json",
            "raw/source.html",
        ):
            path = capture_path / rel
            if path.is_symlink() or not path.is_file():
                raise MatchDetailStoreError(f"Falta archivo de captura regular: {rel}")
        if (capture_path / "raw").is_symlink():
            raise MatchDetailStoreError("El directorio raw del snapshot es un symlink")
        metadata = _read_object(capture_path / "metadata.json")
        snapshot_manifest = _read_object(capture_path / "manifest.json")
        validation = _read_object(capture_path / "validation.json")
        detail = _read_object(capture_path / "match_detail.json")
        raw = (capture_path / "raw/source.html").read_bytes()
        if not raw:
            raise MatchDetailStoreError("El snapshot HTML está vacío")
        file_manifest = snapshot_manifest.get("files")
        if (
            snapshot_manifest.get("schema_version")
            != "football_data_hub.bdfutbol.match_detail_snapshot_manifest.v1"
            or snapshot_manifest.get("capture_id") != capture_path.name
            or snapshot_manifest.get("inventory_id") != inventory_id
            or not isinstance(file_manifest, dict)
        ):
            raise MatchDetailStoreError("Manifiesto del snapshot no válido")
        expected_files = {
            "raw/source.html": raw,
            "match_detail.json": (capture_path / "match_detail.json").read_bytes(),
            "validation.json": (capture_path / "validation.json").read_bytes(),
            "metadata.json": (capture_path / "metadata.json").read_bytes(),
        }
        if set(file_manifest) != set(expected_files):
            raise MatchDetailStoreError(
                "Manifiesto del snapshot incompleto o con archivos extra"
            )
        for filename, content in expected_files.items():
            manifest_item = file_manifest[filename]
            if (
                not isinstance(manifest_item, dict)
                or manifest_item.get("sha256") != _sha256(content)
                or manifest_item.get("bytes") != len(content)
            ):
                raise MatchDetailStoreError(
                    f"Hash/tamaño no coincide en el manifiesto: {filename}"
                )
        identity = detail.get("identity")
        home_team = detail.get("home_team")
        away_team = detail.get("away_team")
        structural_evidence = validation.get("structural_evidence")
        validation_decision = validation.get("decision")
        if (
            not all(
                isinstance(value, dict)
                for value in (identity, home_team, away_team, validation_decision)
            )
            or not isinstance(structural_evidence, list)
            or not all(isinstance(value, str) for value in structural_evidence)
        ):
            raise MatchDetailStoreError(
                "Estructura JSON del detalle o validación inválida"
            )
        try:
            typed_detail = match_detail_from_payload(detail)
        except (TypeError, ValueError) as exc:
            raise MatchDetailStoreError(
                "No se puede rehidratar el contrato tipado"
            ) from exc
        model_errors = validate_match_detail_contract(typed_detail)
        if model_errors:
            raise MatchDetailStoreError(
                f"El contrato tipado del snapshot no es válido: {', '.join(model_errors)}"
            )
        internal_id = metadata.get("internal_id")
        record = records.get(internal_id)
        if record is None or metadata.get("inventory_id") != inventory_id:
            raise MatchDetailStoreError("Captura de otro inventario o partido")
        if (
            metadata.get("capture_id") != capture_path.name
            or not _CAPTURE_ID.fullmatch(capture_path.name)
            or metadata.get("source_match_id") != record.get("source_match_id")
            or metadata.get("source_generation_id")
            != record.get("source_generation_id")
            or metadata.get("source_generation_manifest_sha256")
            != record.get("source_generation_manifest_sha256")
            or metadata.get("source_capture_id") != record.get("source_capture_id")
            or metadata.get("requested_url") != record.get("source_match_url")
            or metadata.get("final_url") != record.get("source_match_url")
            or metadata.get("http_status") != 200
            or metadata.get("access_status") != "VALID"
            or metadata.get("season") != record.get("season")
            or metadata.get("competition") != record.get("competition")
            or metadata.get("group") != record.get("group")
            or metadata.get("matchday") != record.get("matchday")
            or not metadata.get("parser_version")
        ):
            raise MatchDetailStoreError("Metadatos de acceso/captura incompatibles")
        if (
            _sha256(raw) != metadata.get("source_html_sha256")
            or len(raw) != metadata.get("source_html_bytes")
            or _sha256((capture_path / "match_detail.json").read_bytes())
            != metadata.get("match_detail_sha256")
            or _sha256((capture_path / "validation.json").read_bytes())
            != metadata.get("validation_sha256")
        ):
            raise MatchDetailStoreError("Hash o tamaño de captura no coincide")
        evidence_errors = validate_promotion_evidence(
            record,
            typed_detail,
            raw,
            parser_version=metadata["parser_version"],
        )
        if evidence_errors:
            raise MatchDetailStoreError(
                "Evidencia de origen no verificable en snapshot: "
                + "; ".join(evidence_errors)
            )
        if (
            detail.get("schema_version") != "football_data_hub.match_detail.v1"
            or detail.get("source") != "BDFutbol"
            or detail.get("capture_id") != capture_path.name
            or detail.get("source_html_sha256") != metadata.get("source_html_sha256")
            or detail.get("source_url") != record.get("source_match_url")
            or detail.get("source_generation_id") != record.get("source_generation_id")
            or detail.get("source_capture_id") != record.get("source_capture_id")
            or identity.get("internal_id") != internal_id
            or identity.get("source_match_id") != record.get("source_match_id")
            or identity.get("season") != record.get("season")
            or identity.get("competition") != record.get("competition")
            or identity.get("group") != record.get("group")
            or identity.get("matchday") != record.get("matchday")
            or identity.get("home_team_id") != record.get("home_team_id")
            or identity.get("away_team_id") != record.get("away_team_id")
            or home_team.get("team_id") != record.get("home_team_id")
            or away_team.get("team_id") != record.get("away_team_id")
        ):
            raise MatchDetailStoreError(
                "Identidad normalizada no coincide con inventario"
            )
        if (
            validation.get("schema_version")
            != "football_data_hub.match_detail_validation.v1"
            or validation.get("valid") is not True
            or validation.get("http_status") != 200
            or validation.get("requested_url") != record.get("source_match_url")
            or validation.get("final_url") != record.get("source_match_url")
            or validation.get("identity_verified") is not True
            or not REQUIRED_STRUCTURE_EVIDENCE.issubset(set(structural_evidence))
            or validation.get("challenge_detected") is True
            or validation.get("denial_detected") is True
            or validation_decision.get("accepted") is not True
        ):
            raise MatchDetailStoreError(
                "Contrato de validación del snapshot no es válido"
            )
        if (
            metadata.get("group") != record.get("group")
            or metadata.get("home_team_id") != record.get("home_team_id")
            or metadata.get("away_team_id") != record.get("away_team_id")
        ):
            raise MatchDetailStoreError("Metadatos de equipos/grupo incompatibles")
        return internal_id, metadata

    def reconcile(self, inventory: dict[str, Any]) -> dict[str, Any]:
        """Reconstruye un índice en memoria y rehash todos los snapshots antes de usarlos."""

        records = _inventory_records(inventory)
        inventory_id = inventory["inventory_id"]
        captures_root = self.root / "captures"
        states_root = self.root / "states"
        inventories_root = self.root / "inventories"
        captures = captures_root / inventory_id
        inventory_dir = inventories_root / inventory_id
        verified_by_match: dict[str, dict[str, Any]] = {}
        invalid: list[dict[str, str]] = []
        invalid_discovery: list[dict[str, str]] = []
        if any(component.is_symlink() for component in (self.root, *self.root.parents)):
            invalid.append(
                {
                    "capture_id": "store-root",
                    "reason": "ruta de la raíz contiene symlink",
                }
            )
        elif self.root.exists() and not self.root.is_dir():
            invalid.append(
                {
                    "capture_id": "store-root",
                    "reason": "raíz del almacén no es directorio",
                }
            )
        elif captures_root.is_symlink():
            invalid.append({"capture_id": "captures", "reason": "directorio symlink"})
        elif captures_root.exists() and not captures_root.is_dir():
            invalid.append({"capture_id": "captures", "reason": "no es directorio"})
        elif captures.is_symlink():
            invalid.append(
                {
                    "capture_id": inventory_id,
                    "reason": "directorio de generación symlink",
                }
            )
        elif captures.exists():
            if not captures.is_dir():
                invalid.append(
                    {"capture_id": inventory_id, "reason": "no es directorio"}
                )
            else:
                for path in sorted(captures.iterdir(), key=lambda item: item.name):
                    if path.name.startswith("."):
                        continue
                    try:
                        internal_id, metadata = self._verify_capture(
                            path, inventory_id, records
                        )
                    except MatchDetailStoreError as exc:
                        invalid.append({"capture_id": path.name, "reason": str(exc)})
                        continue
                    current = verified_by_match.get(internal_id)
                    if current is None or str(metadata["captured_at_utc"]) > str(
                        current["captured_at_utc"]
                    ):
                        verified_by_match[internal_id] = metadata
        if inventories_root.is_symlink() or inventory_dir.is_symlink():
            invalid.append(
                {
                    "capture_id": "inventory",
                    "reason": "ruta de generación contiene symlink",
                }
            )
        elif inventories_root.exists() and not inventories_root.is_dir():
            invalid.append(
                {
                    "capture_id": "inventory",
                    "reason": "raíz de generaciones no es directorio",
                }
            )
        elif inventory_dir.exists():
            inventory_content = _canonical_json(inventory)
            expected_manifest = _canonical_json(
                {
                    "schema_version": "football_data_hub.match_detail_inventory_manifest.v1",
                    "inventory_id": inventory_id,
                    "inventory_sha256": _sha256(inventory_content),
                    "record_count": len(records),
                    "source_generation": inventory.get("source_generation"),
                }
            )
            if (
                not inventory_dir.is_dir()
                or (inventory_dir / "inventory.json").is_symlink()
                or (inventory_dir / "manifest.json").is_symlink()
                or not (inventory_dir / "inventory.json").is_file()
                or not (inventory_dir / "manifest.json").is_file()
                or (inventory_dir / "inventory.json").read_bytes() != inventory_content
                or (inventory_dir / "manifest.json").read_bytes() != expected_manifest
            ):
                invalid.append(
                    {
                        "capture_id": "inventory",
                        "reason": "generación persistida corrupta o incompatible",
                    }
                )
        state: dict[str, Any] = {}
        state_path = self._state_path(inventory_id)
        if states_root.is_symlink() or state_path.is_symlink():
            invalid.append(
                {
                    "capture_id": "checkpoint",
                    "reason": "ruta del checkpoint contiene symlink",
                }
            )
        elif states_root.exists() and not states_root.is_dir():
            invalid.append(
                {
                    "capture_id": "checkpoint",
                    "reason": "raíz de checkpoints no es directorio",
                }
            )
        elif state_path.exists():
            try:
                state = _read_object(state_path)
                if (
                    state.get("inventory_id") != inventory_id
                    or state.get("schema_version")
                    != "football_data_hub.match_detail_state.v1"
                    or state.get("status") not in {"in_progress", "stopped", "complete"}
                    or not isinstance(state.get("verified_snapshots", []), list)
                    or not isinstance(state.get("diagnostics", []), list)
                    or any(
                        not isinstance(item, dict)
                        for item in state.get("verified_snapshots", [])
                    )
                    or any(
                        not isinstance(item, dict)
                        for item in state.get("diagnostics", [])
                    )
                ):
                    raise MatchDetailStoreError("Checkpoint de otro inventario")
                for reference in state.get("verified_snapshots", []):
                    capture_id = reference.get("capture_id")
                    internal_id = reference.get("internal_id")
                    match_capture = verified_by_match.get(internal_id)
                    if (
                        match_capture is None
                        or match_capture.get("capture_id") != capture_id
                        or match_capture.get("source_html_sha256")
                        != reference.get("source_html_sha256")
                        or reference.get("snapshot_manifest_sha256")
                        != _sha256(
                            (captures / str(capture_id) / "manifest.json").read_bytes()
                        )
                    ):
                        invalid.append(
                            {
                                "capture_id": "checkpoint",
                                "reason": f"Referencia de snapshot sin verificar: {capture_id}",
                            }
                        )
                discovery_refs = state.get("discovery_artifacts", [])
                if not isinstance(discovery_refs, list) or any(
                    not isinstance(item, dict) for item in discovery_refs
                ):
                    raise MatchDetailStoreError(
                        "Referencias de descubrimiento inválidas"
                    )
                for reference in discovery_refs:
                    try:
                        self._verify_discovery_artifact(reference, inventory, records)
                    except MatchDetailStoreError as exc:
                        invalid_discovery.append(
                            {
                                "discovery_id": str(
                                    reference.get("discovery_id", "unknown")
                                ),
                                "reason": str(exc),
                            }
                        )
                if state.get("status") == "complete" and (
                    len(verified_by_match) != len(records) or state.get("diagnostics")
                ):
                    invalid.append(
                        {
                            "capture_id": "checkpoint",
                            "reason": "checkpoint complete no cuadra con capturas verificadas",
                        }
                    )
            except MatchDetailStoreError as exc:
                invalid.append({"capture_id": "checkpoint", "reason": str(exc)})
        diagnostics_root = self.root / "diagnostics"
        discovery_root = diagnostics_root / inventory_id
        if diagnostics_root.is_symlink() or discovery_root.is_symlink():
            invalid_discovery.append(
                {"discovery_id": "diagnostics-root", "reason": "directorio symlink"}
            )
        elif diagnostics_root.exists() and not diagnostics_root.is_dir():
            invalid_discovery.append(
                {"discovery_id": "diagnostics-root", "reason": "no es directorio"}
            )
        elif discovery_root.exists():
            if not discovery_root.is_dir():
                invalid_discovery.append(
                    {"discovery_id": inventory_id, "reason": "no es directorio"}
                )
            else:
                referenced = {
                    item.get("discovery_id")
                    for item in state.get("discovery_artifacts", [])
                    if isinstance(item, dict)
                }
                for artifact_path in discovery_root.iterdir():
                    if artifact_path.name.startswith("."):
                        continue
                    if artifact_path.name not in referenced:
                        invalid_discovery.append(
                            {
                                "discovery_id": artifact_path.name,
                                "reason": "artefacto sin referencia íntegra en el checkpoint",
                            }
                        )
        return {
            "inventory_id": inventory_id,
            "verified_by_internal_id": verified_by_match,
            "invalid_snapshots": invalid,
            "invalid_discovery_artifacts": invalid_discovery,
            "diagnostics": list(state.get("diagnostics", [])),
            "revision": state.get("revision", 0),
            "integrity_blocked": bool(invalid or invalid_discovery),
            "active_stop": state.get("status") == "stopped"
            or bool(state.get("discovery_artifacts", []))
            or any(
                item.get("stop_acquisition", True)
                for item in state.get("diagnostics", [])
            ),
            "blocked": bool(invalid or invalid_discovery),
        }

    def _verify_discovery_artifact(
        self,
        reference: dict[str, Any],
        inventory: dict[str, Any],
        records: dict[str, dict[str, Any]],
    ) -> None:
        discovery_id = reference.get("discovery_id")
        internal_id = reference.get("internal_id")
        record = records.get(internal_id)
        if (
            not isinstance(discovery_id, str)
            or not _CAPTURE_ID.fullmatch(discovery_id)
            or record is None
            or not isinstance(internal_id, str)
        ):
            raise MatchDetailStoreError(
                "Referencia de descubrimiento fuera del inventario"
            )
        root = self.root / "diagnostics" / inventory["inventory_id"]
        artifact = root / discovery_id
        if (
            root.is_symlink()
            or artifact.is_symlink()
            or not artifact.is_dir()
            or any(
                (artifact / rel).is_symlink() or not (artifact / rel).is_file()
                for rel in (
                    "manifest.json",
                    "metadata.json",
                    "discovery.json",
                    "raw/source.html",
                )
            )
            or (artifact / "raw").is_symlink()
        ):
            raise MatchDetailStoreError(
                "Artefacto de descubrimiento incompleto o con symlink"
            )
        expected_paths = {
            "manifest.json",
            "metadata.json",
            "discovery.json",
            "raw",
            "raw/source.html",
        }
        if (
            any(path.is_symlink() for path in artifact.rglob("*"))
            or {path.relative_to(artifact).as_posix() for path in artifact.rglob("*")}
            != expected_paths
        ):
            raise MatchDetailStoreError(
                "El artefacto de descubrimiento tiene archivos inesperados"
            )
        manifest = _read_object(artifact / "manifest.json")
        metadata = _read_object(artifact / "metadata.json")
        report = _read_object(artifact / "discovery.json")
        raw = (artifact / "raw/source.html").read_bytes()
        files = {
            "raw/source.html": raw,
            "discovery.json": (artifact / "discovery.json").read_bytes(),
            "metadata.json": (artifact / "metadata.json").read_bytes(),
        }
        if (
            manifest.get("schema_version")
            != "football_data_hub.match_detail_discovery_manifest.v1"
            or manifest.get("artifact_type") != "discovery_only_unverified"
            or manifest.get("discovery_id") != discovery_id
            or manifest.get("inventory_id") != inventory["inventory_id"]
            or manifest.get("files")
            != {
                name: {"sha256": _sha256(content), "bytes": len(content)}
                for name, content in files.items()
            }
            or _sha256((artifact / "manifest.json").read_bytes())
            != reference.get("manifest_sha256")
            or metadata.get("schema_version")
            != "football_data_hub.match_detail_discovery_artifact.v1"
            or metadata.get("artifact_type") != "discovery_only_unverified"
            or metadata.get("promotion_eligible") is not False
            or metadata.get("source_representation")
            != "BrowserDocument.html() DOM serialization; transport response bytes unavailable"
            or metadata.get("inventory_id") != inventory["inventory_id"]
            or metadata.get("discovery_id") != discovery_id
            or metadata.get("internal_id") != internal_id
            or metadata.get("source_match_id") != record.get("source_match_id")
            or metadata.get("source_generation_id")
            != record.get("source_generation_id")
            or metadata.get("source_capture_id") != record.get("source_capture_id")
            or metadata.get("season") != record.get("season")
            or metadata.get("competition") != record.get("competition")
            or metadata.get("group") != record.get("group")
            or metadata.get("matchday") != record.get("matchday")
            or metadata.get("requested_url") != record.get("source_match_url")
            or metadata.get("final_url") != record.get("source_match_url")
            or metadata.get("http_status") != 200
            or metadata.get("access_status") not in {"VALID", "INVALID_CONTENT"}
            or metadata.get("source_html_sha256") != _sha256(raw)
            or metadata.get("source_html_sha256") != reference.get("source_html_sha256")
            or metadata.get("source_html_bytes") != len(raw)
            or metadata.get("discovery_sha256") != _sha256(files["discovery.json"])
            or report.get("schema_version")
            != "football_data_hub.match_detail_discovery.v1"
            or report.get("semantic_mapping_confirmed") is not False
            or report.get("source_html_sha256") != _sha256(raw)
        ):
            raise MatchDetailStoreError(
                "Hash, procedencia o contrato del descubrimiento inválido"
            )

    def finalize_inventory(self, inventory: dict[str, Any]) -> dict[str, Any]:
        """Marca complete solo tras rehash y verificación de todos los snapshots."""

        with self.exclusive_lock():
            self._prepare_inventory_locked(inventory)
            reconciliation = self.reconcile(inventory)
            total = len(_inventory_records(inventory))
            verified = len(reconciliation["verified_by_internal_id"])
            diagnostics = reconciliation["diagnostics"]
            if (
                reconciliation["blocked"]
                or reconciliation["active_stop"]
                or verified != total
                or any(item.get("stop_acquisition", True) for item in diagnostics)
            ):
                state = self._load_state_locked(inventory["inventory_id"])
                state["status"] = (
                    "stopped"
                    if reconciliation["active_stop"] or diagnostics
                    else "in_progress"
                )
                state["revision"] = int(state.get("revision", 0)) + 1
                state["updated_at_utc"] = _utc_now()
                _atomic_json(self._state_path(inventory["inventory_id"]), state)
                raise MatchDetailStoreError(
                    f"No se puede finalizar: {verified}/{total} snapshots verificados; "
                    f"inválidos={len(reconciliation['invalid_snapshots'])}, "
                    f"diagnósticos={len(diagnostics)}"
                )
            state = self._load_state_locked(inventory["inventory_id"])
            state["status"] = "complete"
            state["revision"] = int(state.get("revision", 0)) + 1
            state["completed_at_utc"] = _utc_now()
            state["updated_at_utc"] = state["completed_at_utc"]
            _atomic_json(self._state_path(inventory["inventory_id"]), state)
            return {
                "status": "complete",
                "inventory_id": inventory["inventory_id"],
                "verified_snapshots": verified,
            }

    def storage_status(self, *, min_free_bytes: int = 0) -> dict[str, Any]:
        path = self.root
        while not path.exists() and path != path.parent:
            path = path.parent
        if any(component.is_symlink() for component in (path, *path.parents)):
            raise MatchDetailStoreError(
                "La ruta de almacenamiento existente contiene un symlink"
            )
        usage = shutil.disk_usage(path)
        writable = os.access(path, os.W_OK)
        return {
            "path": str(self.root),
            "nearest_existing_path": str(path),
            "free_bytes": usage.free,
            "minimum_free_bytes": min_free_bytes,
            "writable": writable,
            "sufficient": usage.free >= min_free_bytes and writable,
        }
