"""Shared planning, disk-budget and lock helpers for the mass player runner."""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any


class PlayerBatchAlreadyRunning(RuntimeError):
    """Another FootballDataHub player batch owns the acquisition lock."""


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
