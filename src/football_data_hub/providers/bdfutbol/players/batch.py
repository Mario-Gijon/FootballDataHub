"""Shared planning, disk-budget and lock helpers for the mass player runner."""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import math
import os
import tempfile
import shutil
from pathlib import Path
from typing import Any
from datetime import datetime, timezone


class PlayerBatchAlreadyRunning(RuntimeError):
    """Another FootballDataHub player batch owns the acquisition lock."""


class PlayerDiskSpaceLow(RuntimeError):
    """The next acquisition step would violate the configured free-space reserve."""

    def __init__(self, diagnostic: dict[str, Any]) -> None:
        self.diagnostic = diagnostic
        self.player_id = diagnostic.get("player_id")
        self.view = diagnostic.get("view")
        self.error_code = "DISK_SPACE_LOW"
        super().__init__(
            "Espacio insuficiente para continuar sin comprometer la reserva mínima "
            f"({diagnostic.get('projected_free_bytes')} bytes proyectados; "
            f"{diagnostic.get('required_reserved_bytes')} requeridos)"
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class PlayerDiskSpaceGuard:
    """Recheck the remaining-work forecast and each pending snapshot before writing."""

    def __init__(
        self,
        *,
        capture_root: Path,
        inventory_player_count: int,
        compact_entries: list[dict[str, Any]],
        reserved_free_bytes: int,
        usage_provider: Any = shutil.disk_usage,
    ) -> None:
        self.capture_root = capture_root.expanduser().resolve()
        self.inventory_player_count = inventory_player_count
        self.compact_entries = compact_entries
        self.reserved_free_bytes = reserved_free_bytes
        self.usage_provider = usage_provider

    def _low_space(self, *, available: int, estimate: int, player_id: int, view: str,
                   requested_url: str, stage: str, pending_write_bytes: int = 0) -> PlayerDiskSpaceLow:
        diagnostic = {
            "error_code": "DISK_SPACE_LOW",
            "player_id": player_id,
            "view": view,
            "requested_url": requested_url,
            "recorded_at_utc": _utc_now(),
            "stage": stage,
            "available_bytes": available,
            "required_reserved_bytes": self.reserved_free_bytes,
            "estimated_remaining_bytes": estimate,
            "pending_write_bytes": pending_write_bytes,
            "projected_free_bytes": available - estimate - pending_write_bytes,
            "stop_acquisition": True,
        }
        return PlayerDiskSpaceLow(diagnostic)

    def check_before_navigation(
        self, *, progress: dict[str, Any], player_id: int, view: str, requested_url: str
    ) -> dict[str, Any]:
        available = int(self.usage_provider(self.capture_root).free)
        estimate = estimate_acquisition_storage(
            progress=progress,
            inventory_player_count=self.inventory_player_count,
            compact_entries=self.compact_entries,
            available_bytes=available,
            reserved_free_bytes=self.reserved_free_bytes,
        )
        if not estimate["sufficient_margin"]:
            raise self._low_space(
                available=available,
                estimate=(available - int(estimate["projected_free_bytes"])),
                player_id=player_id,
                view=view,
                requested_url=requested_url,
                stage="before_navigation",
            )
        return estimate

    def check_before_snapshot(
        self, *, html: str, player_id: int, view: str, requested_url: str
    ) -> dict[str, int]:
        available = int(self.usage_provider(self.capture_root).free)
        # Uncompressed HTML bounds the eventual gzip payload; extra allowance
        # covers metadata and gzip headers without touching the reserve.
        pending_write = len(html.encode("utf-8")) + 64 * 1024
        projected = available - pending_write
        if projected < self.reserved_free_bytes:
            raise self._low_space(
                available=available,
                estimate=0,
                player_id=player_id,
                view=view,
                requested_url=requested_url,
                stage="before_snapshot_write",
                pending_write_bytes=pending_write,
            )
        return {
            "available_bytes": available,
            "reserved_free_bytes": self.reserved_free_bytes,
            "pending_write_bytes": pending_write,
            "projected_free_bytes": projected,
        }

    def check_after_snapshot(self, *, player_id: int, view: str, requested_url: str) -> int:
        available = int(self.usage_provider(self.capture_root).free)
        if available < self.reserved_free_bytes:
            raise self._low_space(
                available=available,
                estimate=0,
                player_id=player_id,
                view=view,
                requested_url=requested_url,
                stage="after_snapshot_write",
            )
        return available


def validate_player_batch_completion(
    progress: dict[str, Any], *, expected_player_count: int = 1709
) -> dict[str, Any]:
    """Certify global base-view coverage; a completed capture run alone is insufficient."""
    summary = progress.get("summary", {})
    players = progress.get("players", [])
    player_ids = [item.get("player_id") for item in players if isinstance(item, dict)]
    valid_pairs = 0
    missing_pairs: list[dict[str, Any]] = []
    for item in players:
        if not isinstance(item, dict):
            continue
        player_id = item.get("player_id")
        snapshots = item.get("view_snapshots", {})
        pending = set(item.get("views_pending", []))
        for view in ("profile", "statistics", "matches", "rivals"):
            reference = snapshots.get(view) if isinstance(snapshots, dict) else None
            if (
                isinstance(reference, dict)
                and reference.get("http_status") == 200
                and reference.get("access_status") == "VALID"
                and reference.get("parse_validation", {}).get("status") == "VALID"
                and len(str(reference.get("html_sha256") or "")) == 64
            ):
                valid_pairs += 1
            else:
                missing_pairs.append({"player_id": player_id, "view": view})
            if view in pending and not any(
                pair["player_id"] == player_id and pair["view"] == view
                for pair in missing_pairs
            ):
                missing_pairs.append({"player_id": player_id, "view": view})
    checks = {
        "inventory_player_count": len(player_ids) == expected_player_count,
        "summary_inventory_player_count": summary.get("inventory_players") == expected_player_count,
        "unique_player_ids": len(set(player_ids)) == expected_player_count,
        "all_players_have_four_verified_views": valid_pairs == expected_player_count * 4
        and not missing_pairs,
        "summary_all_players_complete": summary.get("players_with_all_base_views") == expected_player_count,
        "summary_zero_pending_players": summary.get("players_pending") == 0,
        "summary_zero_pending_views": summary.get("base_view_navigations_pending") == 0,
        "summary_verified_view_count": summary.get("captured_valid_base_views") == expected_player_count * 4,
        "summary_zero_unresolved_access_errors": summary.get("players_with_access_errors") == 0
        and summary.get("blocked_base_views") == 0,
        "no_corrupt_manifests": not progress.get("corrupt_manifests"),
    }
    return {
        "valid": all(checks.values()),
        "expected_players": expected_player_count,
        "observed_players": len(player_ids),
        "expected_player_view_pairs": expected_player_count * 4,
        "verified_player_view_pairs": valid_pairs,
        "missing_player_view_pairs": missing_pairs,
        "unresolved_access_errors": summary.get("blocked_base_views"),
        "corrupt_manifests": progress.get("corrupt_manifests", []),
        "checks": checks,
    }


class PlayerBatchLock:
    def __init__(self, capture_root: Path) -> None:
        self.path = capture_root.expanduser().resolve() / ".player-mass-acquisition.lock"
        self.fd: int | None = None

    def __enter__(self) -> "PlayerBatchLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.lseek(self.fd, 0, os.SEEK_SET)
            active = os.read(self.fd, 2048).decode("utf-8", errors="replace")
            os.close(self.fd)
            self.fd = None
            raise PlayerBatchAlreadyRunning(
                f"Ya existe una adquisición que posee {self.path}: {active.strip()}"
            ) from exc
        payload = json.dumps({"pid": os.getpid(), "status": "running"}).encode()
        os.ftruncate(self.fd, 0)
        os.lseek(self.fd, 0, os.SEEK_SET)
        os.write(self.fd, payload)
        os.fsync(self.fd)
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


def ordered_player_ids(inventory: dict[str, Any]) -> tuple[list[int], dict[int, str]]:
    records = inventory.get("records")
    if not isinstance(records, list):
        raise ValueError("El inventario no contiene records")
    roster: list[int] = []
    transfer_only: list[int] = []
    cohort_by_id: dict[int, str] = {}
    seen: set[int] = set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("player_id"), int):
            raise ValueError("El inventario contiene un registro sin player_id entero")
        player_id = record["player_id"]
        if player_id in seen:
            raise ValueError(f"player_id duplicado en inventario: {player_id}")
        seen.add(player_id)
        is_roster = int(record.get("membership_count") or 0) > 0
        cohort = "roster" if is_roster else "transfer_only"
        cohort_by_id[player_id] = cohort
        (roster if is_roster else transfer_only).append(player_id)
    ordered = [*sorted(roster), *sorted(transfer_only)]
    return ordered, cohort_by_id


def load_verified_compact_sample(compact_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    compact_root = compact_root.expanduser().resolve()
    pointer_path = compact_root / "current.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    generation_dir = compact_root / "generations" / str(pointer["generation_id"])
    manifest_path = generation_dir / "manifest.json"
    manifest_raw = manifest_path.read_bytes()
    if hashlib.sha256(manifest_raw).hexdigest() != pointer.get("manifest_sha256"):
        raise ValueError("El manifest compacto no coincide con current.json")
    manifest = json.loads(manifest_raw)
    if manifest.get("generation_id") != pointer.get("generation_id"):
        raise ValueError("La generación compacta no coincide con el puntero")
    entries = [
        entry for entry in manifest.get("entries", [])
        if entry.get("status") == "COMPLETE_BASE_VIEWS"
    ]
    for entry in entries:
        path = (generation_dir / str(entry["path"])).resolve()
        if generation_dir.resolve() not in path.parents:
            raise ValueError("Ruta compacta fuera de la generación")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
            raise ValueError(f"Hash compacto no válido para player_id={entry.get('player_id')}")
        if entry.get("compression") != "gzip":
            raise ValueError(f"Compresión compacta desconocida para player_id={entry.get('player_id')}")
        try:
            document = json.loads(gzip.decompress(raw))
        except (EOFError, OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Export compacto gzip ilegible para player_id={entry.get('player_id')}") from exc
        if (
            not isinstance(document, dict)
            or document.get("player_id") != entry.get("player_id")
            or document.get("status") != entry.get("status")
        ):
            raise ValueError(f"Identidad o estado compacto no válido para player_id={entry.get('player_id')}")
    if not entries:
        raise ValueError("No hay export compacto completo para estimar almacenamiento")
    return manifest, entries


def estimate_acquisition_storage(
    *,
    progress: dict[str, Any],
    inventory_player_count: int,
    compact_entries: list[dict[str, Any]],
    available_bytes: int,
    reserved_free_bytes: int = 1536 * 1024**2,
    overhead_bytes: int = 256 * 1024**2,
) -> dict[str, Any]:
    """Use per-view maxima and compact pilot sizes, with explicit safety margins."""
    views = ("profile", "statistics", "matches", "rivals")
    sizes_by_view: dict[str, list[int]] = {view: [] for view in views}
    for player in progress.get("players", []):
        for view, reference in player.get("view_snapshots", {}).items():
            if view not in sizes_by_view or not isinstance(reference, dict):
                continue
            byte_count = int(reference.get("compressed_bytes") or 0) + int(
                reference.get("metadata_bytes") or 0
            )
            if byte_count > 0:
                sizes_by_view[view].append(byte_count)
    pending_by_view = {
        view: sum(view in player.get("views_pending", []) for player in progress.get("players", []))
        for view in views
    }
    missing_samples = [
        view for view in views if pending_by_view[view] and not sizes_by_view[view]
    ]
    estimated_raw = sum(
        max(sizes_by_view[view]) * pending_by_view[view]
        for view in views if sizes_by_view[view]
    )
    raw_with_margin = math.ceil(estimated_raw * 1.25)
    sample_bytes = [int(entry["bytes"]) for entry in compact_entries]
    compact_mean = sum(sample_bytes) / len(sample_bytes)
    compact_max = max(sample_bytes)
    conservative_per_player = max(compact_max, compact_mean * 1.5)
    estimated_compact = math.ceil(conservative_per_player * inventory_player_count * 1.25)
    required_total = raw_with_margin + estimated_compact + overhead_bytes + reserved_free_bytes
    projected_free = available_bytes - raw_with_margin - estimated_compact - overhead_bytes
    return {
        "available_bytes": available_bytes,
        "available_gib": round(available_bytes / 1024**3, 3),
        "pending_by_view": pending_by_view,
        "sample_count_by_view": {view: len(sizes_by_view[view]) for view in views},
        "estimated_raw_and_metadata_bytes": estimated_raw,
        "raw_forecast_with_25_percent_margin_bytes": raw_with_margin,
        "compact_sample_count": len(sample_bytes),
        "compact_sample_mean_bytes": round(compact_mean),
        "compact_sample_max_bytes": compact_max,
        "estimated_compact_generation_with_margin_bytes": estimated_compact,
        "manifest_log_and_index_allowance_bytes": overhead_bytes,
        "reserved_free_bytes": reserved_free_bytes,
        "projected_free_bytes": projected_free,
        "projected_free_gib": round(projected_free / 1024**3, 3),
        "required_available_bytes": required_total,
        "sufficient_margin": not missing_samples and projected_free >= reserved_free_bytes,
        "missing_size_samples": missing_samples,
    }


def atomic_status(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
