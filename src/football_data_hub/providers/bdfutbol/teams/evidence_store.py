"""Durable, non-publishable checkpoints for validated team-page evidence."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import uuid
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from .acquisition import FOLLOW_STATES, TEAM_VIEW_SELECTORS, _view_markers, create_team_capture_id
from .parser import resolve_team_view_urls

_RECOVERABLE_STATUSES = {"acquiring", "parse_failed", "local_error", "incomplete"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    _atomic_write(path, (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _read_snapshot(directory: Path, evidence: dict[str, Any]) -> str:
    relative = Path(str(evidence.get("path") or ""))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("La ruta del snapshot sale del directorio de evidencia")
    path = directory / relative
    payload = path.read_bytes()
    if evidence.get("compression") != "gzip":
        raise ValueError("La compresión del snapshot no está reconocida")
    try:
        html_bytes = gzip.decompress(payload)
    except (gzip.BadGzipFile, EOFError, zlib.error) as exc:
        raise ValueError("El snapshot gzip no se puede descomprimir") from exc
    if hashlib.sha256(html_bytes).hexdigest() != evidence.get("sha256"):
        raise ValueError("El SHA-256 del snapshot no coincide")
    try:
        return html_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("El snapshot no contiene HTML UTF-8 válido") from exc


@dataclass(frozen=True, slots=True)
class PendingEvidence:
    """Integrity-checked, valid source pages that have not been published."""

    capture_id: str
    path: Path
    manifest: dict[str, Any]
    seed: dict[str, Any]
    warnings: tuple[str, ...] = ()

    @property
    def valid_views(self) -> tuple[str, ...]:
        return tuple(self.seed.get("raw_views", {}))

    @property
    def valid_follow_states(self) -> tuple[str, ...]:
        return tuple(self.seed.get("follow_state_html", {}))


class TeamEvidenceCheckpoint:
    """Persist each validated HTML response before semantic parsing begins."""

    def __init__(
        self,
        output_root: Path,
        *,
        season: str,
        group: str,
        team_record: dict[str, Any],
        catalog_reference: dict[str, Any],
        requested_views: tuple[str, ...],
        capture_id: str | None = None,
        resume_path: Path | None = None,
    ) -> None:
        self.capture_id = capture_id or create_team_capture_id()
        self.path = resume_path or (
            output_root.expanduser()
            / season
            / str(int(team_record["team_id"]))
            / "diagnostics"
            / self.capture_id
        )
        self.manifest_path = self.path / "metadata" / "evidence.json"
        if resume_path is None:
            self.path.mkdir(parents=True, exist_ok=False)
            self.manifest: dict[str, Any] = {
                "schema_version": 1,
                "capture_id": self.capture_id,
                "source": "BDFutbol",
                "section": "team_profile_evidence_checkpoint",
                "season": season,
                "group": group,
                "team_id": int(team_record["team_id"]),
                "team_name": str(team_record.get("name") or team_record.get("team_name") or ""),
                "team_url": str(team_record["team_url"]),
                "related_team_catalog": catalog_reference,
                "requested_views": list(requested_views),
                "status": "acquiring",
                "created_at_utc": _utc_now(),
                "updated_at_utc": _utc_now(),
                "source_snapshots": {},
                "follow_states": {},
                "failures": [],
            }
            self._save()
        else:
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if self.manifest.get("capture_id") != self.capture_id:
                raise ValueError("El capture_id del checkpoint no coincide con su ruta")

    def _save(self) -> None:
        self.manifest["updated_at_utc"] = _utc_now()
        _atomic_json(self.manifest_path, self.manifest)

    def _save_html(self, relative: str, html: str) -> dict[str, Any]:
        html_bytes = html.encode("utf-8")
        compressed = gzip.compress(html_bytes, compresslevel=9, mtime=0)
        _atomic_write(self.path / relative, compressed)
        return {
            "path": relative,
            "compression": "gzip",
            "sha256": hashlib.sha256(html_bytes).hexdigest(),
            "bytes_utf8": len(html_bytes),
            "stored_bytes": len(compressed),
        }

    def record_view(
        self,
        view: str,
        html: str,
        *,
        requested_url: str,
        final_url: str,
        title: str,
        access: dict[str, Any],
    ) -> None:
        if str(access.get("status", "")).upper().split(".")[-1] != "VALID" or access.get("http_status") != 200:
            raise ValueError("Solo se conserva una vista con acceso VALID y HTTP 200")
        details = self._save_html(f"raw/{view}.html.gz", html)
        self.manifest.setdefault("source_snapshots", {})[view] = {
            **details,
            "requested_url": requested_url,
            "final_url": final_url,
            "title": title,
            "http_status": 200,
            "access_status": "VALID",
            "captured_at_utc": access.get("captured_at_utc"),
            "capture_timestamp_basis": access.get("capture_timestamp_basis"),
            "access": access,
        }
        self._save()

    def record_rejected_view(
        self,
        view: str,
        html: str,
        *,
        access: dict[str, Any],
    ) -> None:
        """Preserve rejected HTTP 200 evidence without making it reusable as a valid view."""
        if view not in TEAM_VIEW_SELECTORS:
            raise ValueError("Vista de equipo desconocida")
        if str(access.get("status", "")).upper().split(".")[-1] != "INVALID_CONTENT":
            raise ValueError("Solo se conserva contenido rechazado por estructura")
        if access.get("http_status") != 200:
            raise ValueError("La evidencia rechazada requiere HTTP 200 confirmado")
        if view in self.manifest.get("rejected_snapshots", {}):
            raise ValueError("La evidencia rechazada ya está registrada; no se sobrescribe")
        details = self._save_html(f"raw/rejected/{view}.html.gz", html)
        self.manifest.setdefault("rejected_snapshots", {})[view] = {
            **details,
            "requested_url": access.get("requested_url"),
            "final_url": access.get("final_url"),
            "title": access.get("page_title"),
            "http_status": 200,
            "access_status": "INVALID_CONTENT",
            "captured_at_utc": _utc_now(),
            "access": access,
        }
        self._save()

    def record_follow_state(self, state: str, html: str, diagnostics: dict[str, Any]) -> None:
        if state not in FOLLOW_STATES or diagnostics.get("selected_value") != state:
            raise ValueError("El estado de Seguimiento no coincide con el valor seleccionado")
        details = self._save_html(f"raw/follow_states/{state}.html.gz", html)
        self.manifest.setdefault("follow_states", {})[state] = {
            **details,
            **diagnostics,
            "status": "VALID",
            "source_capture_id": self.capture_id,
            "reused": False,
        }
        self._save()

    def record_browser(self, browser: dict[str, Any]) -> None:
        self.manifest["browser"] = browser
        self._save()

    def record_failure(self, *, kind: str, message: str) -> None:
        self.manifest.setdefault("failures", []).append({
            "at_utc": _utc_now(),
            "kind": kind,
            "message": message,
        })
        self.manifest["status"] = "access_denied" if kind == "access_denied" else (
            "parse_failed" if kind == "parse_failed" else "local_error"
        )
        self._save()

    def mark_complete_and_remove_checkpoint(self, published_directory: Path) -> None:
        """Drop only the temporary duplicate after the complete capture is durable."""
        if not (published_directory / "metadata" / "capture.json").is_file():
            raise ValueError("No se limpia el checkpoint sin una captura publicada")
        shutil.rmtree(self.path)


def read_pending_evidence(
    checkpoint_dir: Path,
    *,
    season: str,
    group: str,
    team_record: dict[str, Any],
) -> PendingEvidence:
    """Load valid, hash-checked pages from an incomplete checkpoint."""
    directory = checkpoint_dir.expanduser()
    manifest = json.loads((directory / "metadata" / "evidence.json").read_text(encoding="utf-8"))
    expected = {
        "source": "BDFutbol",
        "section": "team_profile_evidence_checkpoint",
        "season": season,
        "group": group,
        "team_id": int(team_record["team_id"]),
        "team_url": str(team_record["team_url"]),
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("La identidad, grupo, temporada o procedencia del checkpoint no coincide")
    if manifest.get("status") not in _RECOVERABLE_STATUSES:
        raise ValueError(f"El estado {manifest.get('status')!r} no es reutilizable")

    raw_views: dict[str, str] = {}
    access_by_view: dict[str, dict[str, Any]] = {}
    view_urls: dict[str, str] = {}
    page_titles: dict[str, str] = {}
    warnings: list[str] = []
    snapshots = manifest.get("source_snapshots") or {}
    ordered_snapshots = sorted(snapshots.items(), key=lambda item: (item[0] != "alignment", item[0]))
    for view, evidence in ordered_snapshots:
        try:
            if view not in TEAM_VIEW_SELECTORS:
                raise ValueError("vista desconocida")
            if evidence.get("access_status") != "VALID" or evidence.get("http_status") != 200:
                raise ValueError("el acceso no fue VALID/HTTP 200")
            html = _read_snapshot(directory, evidence)
            if _view_markers(view, html):
                raise ValueError("la estructura HTML no coincide con la vista")
            if str(team_record.get("name") or "").casefold() not in html.casefold():
                raise ValueError("el HTML no conserva el marcador de identidad del equipo")
            if season.casefold() not in str(evidence.get("title") or "").casefold():
                raise ValueError("el título no confirma la temporada")
            if view == "alignment":
                expected_urls = resolve_team_view_urls(html, str(team_record["team_url"]))
                expected_url = str(team_record["team_url"])
            else:
                alignment = raw_views.get("alignment")
                if alignment is None:
                    raise ValueError("falta Alineación para validar la URL de esta vista")
                expected_urls = resolve_team_view_urls(alignment, str(team_record["team_url"]))
                expected_url = expected_urls[view]
            if evidence.get("requested_url") != expected_url or evidence.get("final_url") != expected_url:
                raise ValueError("la URL solicitada/final no coincide con la vista esperada")
            raw_views[view] = html
            access_by_view[view] = dict(evidence.get("access") or {})
            view_urls[view] = expected_url
            page_titles[view] = str(evidence.get("title") or "")
        except (OSError, ValueError, KeyError, TypeError, gzip.BadGzipFile) as exc:
            warnings.append(f"Vista {view} no reutilizada: {exc}")

    if "alignment" not in raw_views:
        # Child URLs cannot be authenticated without the base page.
        raw_views.clear()
        access_by_view.clear()
        view_urls.clear()
        page_titles.clear()

    follow_state_html: dict[str, str] = {}
    follow_state_diagnostics: dict[str, dict[str, Any]] = {}
    for state, evidence in (manifest.get("follow_states") or {}).items():
        try:
            if state not in FOLLOW_STATES or evidence.get("status") != "VALID" or evidence.get("selected_value") != state:
                raise ValueError("estado no válido")
            html = _read_snapshot(directory, evidence)
            select = BeautifulSoup(html, "html.parser").select_one("#vista_jornades")
            if select is None or not any(
                option.get("value") == state for option in select.select("option")
            ):
                raise ValueError("el HTML no contiene la opción de Seguimiento capturada")
            # `selected_value` comes from the live DOM property read by
            # Playwright/Pure CDP. `document.html()` serializes markup and may
            # retain the original `selected` attribute even after JavaScript
            # changed the control's live value, so that attribute is not a
            # reliable source for a captured state.
            follow_state_html[state] = html
            follow_state_diagnostics[state] = {**evidence, "reused": True}
        except (OSError, ValueError, KeyError, TypeError, gzip.BadGzipFile) as exc:
            warnings.append(f"Estado Seguimiento {state} no reutilizado: {exc}")

    seed = {
        "capture_id": manifest["capture_id"],
        "seed_capture_ids": (manifest["capture_id"],),
        "raw_views": raw_views,
        "access_by_view": access_by_view,
        "view_urls": view_urls,
        "page_titles": page_titles,
        "browser": manifest.get("browser") or {},
        "follow_state_html": follow_state_html,
        "follow_state_diagnostics": follow_state_diagnostics,
    }
    return PendingEvidence(
        capture_id=str(manifest["capture_id"]),
        path=directory,
        manifest=manifest,
        seed=seed,
        warnings=tuple(warnings),
    )


def find_pending_evidence(
    output_root: Path,
    *,
    season: str,
    group: str,
    team_record: dict[str, Any],
) -> PendingEvidence | None:
    """Return the newest recoverable checkpoint with at least one valid page."""
    root = output_root.expanduser() / season / str(int(team_record["team_id"])) / "diagnostics"
    if not root.is_dir():
        return None
    candidates: list[PendingEvidence] = []
    for directory in root.iterdir():
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        try:
            evidence = read_pending_evidence(
                directory,
                season=season,
                group=group,
                team_record=team_record,
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
        if evidence.valid_views or evidence.valid_follow_states:
            candidates.append(evidence)
    if not candidates:
        return None
    candidates.sort(key=lambda item: str(item.manifest.get("updated_at_utc") or item.capture_id))
    return candidates[-1]
