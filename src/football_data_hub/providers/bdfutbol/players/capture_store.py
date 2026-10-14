"""Immutable, recoverable raw snapshots for BDFutbol player pages."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class PlayerCaptureError(RuntimeError):
    """A player capture could not be safely written or resumed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    _atomic_bytes(path, raw + b"\n")


def _new_capture_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + f"-{uuid4().hex[:8]}"


class PlayerCaptureStore:
    """Write each capture to a unique run and keep a manifest checkpoint."""

    def __init__(self, root: Path, *, capture_id: str | None = None) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.capture_id = capture_id or _new_capture_id()
        if not self.capture_id.replace("-", "").replace(".", "").isalnum():
            raise PlayerCaptureError("capture_id contiene caracteres no admitidos")
        self.run_dir = self.root / self.capture_id
        self.run_dir.mkdir(mode=0o700, exist_ok=capture_id is not None)
        self.manifest_path = self.run_dir / "manifest.json"
        if self.manifest_path.exists():
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if self.manifest.get("capture_id") != self.capture_id:
                raise PlayerCaptureError("El manifiesto no coincide con capture_id")
            self.manifest.setdefault("navigation_events", [])
            self.manifest.setdefault("reused_snapshots", [])
            if self.manifest.get("status") != "complete":
                self.manifest["resumed_at_utc"] = utc_now()
                self.manifest["status"] = "in_progress"
                self._checkpoint()
        else:
            self.manifest = {
                "schema_version": "football_data_hub.bdfutbol.player_capture.v1",
                "capture_id": self.capture_id,
                "created_at_utc": utc_now(),
                "status": "in_progress",
                "snapshots": [],
                "reused_snapshots": [],
                "diagnostics": [],
                "navigation_events": [],
            }
            self._checkpoint()

    def _checkpoint(self) -> None:
        self.manifest["updated_at_utc"] = utc_now()
        _atomic_json(self.manifest_path, self.manifest)

    def record_diagnostic(self, event: dict[str, Any]) -> None:
        self.manifest["diagnostics"].append({"recorded_at_utc": utc_now(), **event})
        self.manifest["status"] = "stopped" if event.get("stop_acquisition") else "in_progress"
        self._checkpoint()

    def record_navigation(self, event: dict[str, Any]) -> None:
        self.manifest.setdefault("navigation_events", []).append(
            {"recorded_at_utc": utc_now(), **event}
        )
        self._checkpoint()

    def record_inventory_source(self, source: dict[str, Any]) -> None:
        """Bind this capture run to the exact offline inventory used to validate IDs."""
        required = ("path", "sha256", "season")
        if any(not source.get(key) for key in required):
            raise PlayerCaptureError("La referencia al inventario requiere path, sha256 y season")
        digest = str(source["sha256"])
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest.lower()):
            raise PlayerCaptureError("SHA-256 del inventario no válido")
        existing = self.manifest.get("inventory_source")
        if existing and existing.get("sha256") != digest:
            raise PlayerCaptureError("El inventario de origen cambió durante la captura")
        self.manifest["inventory_source"] = source
        self._checkpoint()

    def record_reused_snapshot(self, reference: dict[str, Any]) -> None:
        """Checkpoint a verified snapshot reused from another immutable run."""
        required = ("capture_id", "snapshot_id", "player_id", "view", "html_sha256")
        if any(not reference.get(key) for key in required):
            raise PlayerCaptureError("La referencia reutilizada está incompleta")
        refs = self.manifest.setdefault("reused_snapshots", [])
        identity = (
            reference["capture_id"], reference["snapshot_id"],
            reference["player_id"], reference["view"],
        )
        if not any((
            item.get("capture_id"), item.get("snapshot_id"),
            item.get("player_id"), item.get("view"),
        ) == identity for item in refs):
            refs.append(reference)
            self._checkpoint()

    def reconcile_navigation_ledger(self, *, notes: list[str] | None = None) -> None:
        """Rebuild missing ledger entries from immutable raw snapshots/diagnostics."""
        events = list(self.manifest.get("navigation_events", []))
        seen_diagnostics = {
            (
                item.get("player_id"), item.get("view"), item.get("requested_url"),
                item.get("access_status"), item.get("captured_at_utc"),
            )
            for item in events
        }
        for diagnostic in self.manifest.get("diagnostics", []):
            key = (
                diagnostic.get("player_id"), diagnostic.get("view"),
                diagnostic.get("requested_url"), diagnostic.get("access_status"),
                diagnostic.get("captured_at_utc"),
            )
            if diagnostic.get("requested_url") and key not in seen_diagnostics:
                events.append({
                    **diagnostic,
                    "recorded_at_utc": diagnostic.get("recorded_at_utc", utc_now()),
                    "event_source": "capture_diagnostic",
                })
                seen_diagnostics.add(key)

        remaining_valid_events: dict[tuple[int, str, str], int] = {}
        for event in events:
            if event.get("access_status") == "VALID" and event.get("http_status") == 200:
                key = (event.get("player_id"), event.get("view"), event.get("requested_url"))
                remaining_valid_events[key] = remaining_valid_events.get(key, 0) + 1

        for item in self.manifest.get("snapshots", []):
            if item.get("snapshot_kind") != "BASE_VIEW":
                continue
            key = (item.get("player_id"), item.get("view"), item.get("requested_url"))
            if remaining_valid_events.get(key, 0):
                remaining_valid_events[key] -= 1
                continue
            try:
                metadata = json.loads(
                    (self.run_dir / item["metadata_path"]).read_text(encoding="utf-8")
                )
            except (OSError, KeyError, json.JSONDecodeError):
                continue
            if metadata.get("access_status") != "VALID" or metadata.get("http_status") != 200:
                continue
            events.append({
                "player_id": metadata.get("player_id"),
                "view": metadata.get("view"),
                "requested_url": metadata.get("requested_url"),
                "final_url": metadata.get("final_url"),
                "http_status": metadata.get("http_status"),
                "access_status": metadata.get("access_status"),
                "page_title": metadata.get("page_title"),
                "captured_at_utc": metadata.get("captured_at_utc"),
                "navigation_purpose": metadata.get("interaction_observations", {}).get("purpose"),
                "event_source": "reconstructed_from_valid_base_snapshot",
            })

        self.manifest["navigation_events"] = sorted(
            events,
            key=lambda item: str(item.get("captured_at_utc") or item.get("recorded_at_utc") or ""),
        )
        self.manifest["navigation_count_total"] = len(events)
        self.manifest["successful_navigation_count"] = sum(
            item.get("access_status") == "VALID" and item.get("http_status") == 200
            for item in events
        )
        self.manifest["non_valid_navigation_count"] = len(events) - self.manifest["successful_navigation_count"]
        if notes:
            self.manifest.setdefault("review_notes", []).extend(notes)
        self._checkpoint()

    def has_valid_base_snapshot(
        self,
        *,
        player_id: int,
        view: str,
        requested_url: str,
    ) -> bool:
        """Reuse only a raw snapshot whose metadata, route and hash still verify."""
        return self.has_valid_snapshot(
            player_id=player_id,
            view=view,
            requested_url=requested_url,
            snapshot_kind="BASE_VIEW",
        )

    def has_valid_snapshot(
        self,
        *,
        player_id: int,
        view: str,
        requested_url: str,
        snapshot_kind: str,
    ) -> bool:
        """Reuse an exact URL variant only when its original bytes still verify."""
        for item in self.manifest.get("snapshots", []):
            if (
                item.get("player_id") != player_id
                or item.get("view") != view
                or item.get("snapshot_kind") != snapshot_kind
                or item.get("requested_url") != requested_url
            ):
                continue
            try:
                metadata_path = self.run_dir / item["metadata_path"]
                raw_path = self.run_dir / item["raw_path"]
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                raw = gzip.decompress(raw_path.read_bytes())
            except (OSError, KeyError, ValueError, json.JSONDecodeError):
                continue
            if (
                metadata.get("player_id") == player_id
                and metadata.get("view") == view
                and metadata.get("snapshot_kind") == snapshot_kind
                and metadata.get("requested_url") == requested_url
                and metadata.get("final_url") == requested_url
                and metadata.get("access_status") == "VALID"
                and metadata.get("http_status") == 200
                and hashlib.sha256(raw).hexdigest() == metadata.get("html_sha256")
            ):
                return True
        return False

    def save_snapshot(
        self,
        *,
        player_id: int,
        view: str,
        requested_url: str,
        final_url: str,
        http_status: int | None,
        page_title: str,
        html: str,
        browser: dict[str, Any],
        filter_parameters: dict[str, str] | None = None,
        snapshot_kind: str | None = None,
        controls: list[dict[str, Any]] | None = None,
        observations: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw = html.encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        resolved_kind = snapshot_kind or (
            "SELECTOR_VARIANT" if filter_parameters else "BASE_VIEW"
        )
        if resolved_kind not in {"BASE_VIEW", "URL_VARIANT", "SELECTOR_VARIANT"}:
            raise PlayerCaptureError(f"snapshot_kind no reconocido: {resolved_kind}")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        snapshot_id = f"{stamp}-{digest[:12]}"
        relative_dir = Path(f"j{player_id}") / view / snapshot_id
        snapshot_dir = self.run_dir / relative_dir
        snapshot_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
        compressed_path = snapshot_dir / "source.html.gz"
        compressed = gzip.compress(raw, compresslevel=6, mtime=0)
        _atomic_bytes(compressed_path, compressed)
        metadata = {
            "schema_version": "football_data_hub.bdfutbol.player_snapshot.v1",
            "capture_id": self.capture_id,
            "snapshot_id": snapshot_id,
            "captured_at_utc": utc_now(),
            "player_id": player_id,
            "view": view,
            "snapshot_kind": resolved_kind,
            "is_base_view_snapshot": resolved_kind == "BASE_VIEW",
            "requested_url": requested_url,
            "final_url": final_url,
            "http_status": http_status,
            "access_status": "VALID",
            "page_title": page_title,
            "filter_parameters": filter_parameters or {},
            "controls_observed": controls or [],
            "interaction_observations": observations or {},
            "raw_path": (relative_dir / "source.html.gz").as_posix(),
            "raw_compression": "gzip",
            "html_uncompressed_bytes": len(raw),
            "html_compressed_bytes": len(compressed),
            "html_sha256": digest,
            "browser": browser,
        }
        _atomic_json(snapshot_dir / "metadata.json", metadata)
        item = {
            "player_id": player_id,
            "view": view,
            "snapshot_id": snapshot_id,
            "snapshot_kind": metadata["snapshot_kind"],
            "filter_parameters": metadata["filter_parameters"],
            "metadata_path": (relative_dir / "metadata.json").as_posix(),
            "raw_path": metadata["raw_path"],
            "html_sha256": digest,
            "http_status": http_status,
            "requested_url": requested_url,
            "final_url": final_url,
        }
        self.manifest["snapshots"].append(item)
        self.manifest["status"] = "in_progress"
        self._checkpoint()
        return metadata

    def mark_complete(self) -> None:
        self.manifest["status"] = "complete"
        self.manifest["completed_at_utc"] = utc_now()
        self._checkpoint()
