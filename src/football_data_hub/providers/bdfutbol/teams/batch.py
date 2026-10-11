"""Sequential, resumable orchestration primitives for team-profile captures."""

from __future__ import annotations

import json
import gzip
import hashlib
import os
import shutil
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from .acquisition import create_team_capture_id

BatchStatus = Literal["complete", "incomplete", "failed", "pending"]


class BatchStop(RuntimeError):
    """A condition makes further navigations in this run unhelpful."""

    def __init__(self, message: str, *, kind: str = "access_denied") -> None:
        self.kind = kind
        super().__init__(message)


class BatchAccessDenied(BatchStop):
    """The provider reported a challenge or explicit access denial."""


@dataclass(frozen=True, slots=True)
class BatchTeamOutcome:
    capture_id: str
    views: tuple[str, ...]
    valid: bool = True


@dataclass(frozen=True, slots=True)
class BatchTeamEntry:
    group: str
    team_id: int
    team_name: str
    status: BatchStatus
    requested_views: tuple[str, ...]
    capture_id: str | None = None
    reused_existing_capture: bool = False
    failure_class: str | None = None
    error: str | None = None


def run_team_batch(
    *,
    teams_by_group: dict[int, list[dict[str, Any]]],
    groups: tuple[int, ...],
    requested_views: tuple[str, ...],
    find_complete_capture: Callable[[int, int, tuple[str, ...]], str | None],
    find_partial_capture: Callable[[int, int], str | None],
    process_team: Callable[[int, dict[str, Any], tuple[str, ...]], BatchTeamOutcome],
) -> dict[str, Any]:
    """Run teams in a single sequence, skipping complete captures and stopping on denial."""
    if not groups or any(group not in {1, 2} for group in groups):
        raise ValueError("Selecciona el Grupo I, el Grupo II o ambos")
    views = tuple(dict.fromkeys(requested_views))
    if not views:
        raise ValueError("Selecciona al menos una vista")
    entries: list[BatchTeamEntry] = []
    stop_reason: dict[str, Any] | None = None
    for group in groups:
        for team in teams_by_group.get(group, []):
            team_id = int(team["team_id"])
            team_name = str(team.get("name") or team.get("team_name") or "")
            completed_capture = find_complete_capture(group, team_id, views)
            if completed_capture:
                entries.append(BatchTeamEntry(
                    group="I" if group == 1 else "II",
                    team_id=team_id,
                    team_name=team_name,
                    status="complete",
                    requested_views=views,
                    capture_id=completed_capture,
                    reused_existing_capture=True,
                ))
                continue
            previous_capture = find_partial_capture(group, team_id)
            try:
                outcome = process_team(group, team, views)
            except BatchAccessDenied as exc:
                entries.append(BatchTeamEntry(
                    group="I" if group == 1 else "II",
                    team_id=team_id,
                    team_name=team_name,
                    status="incomplete" if previous_capture else "failed",
                    requested_views=views,
                    capture_id=previous_capture,
                    failure_class=exc.kind,
                    error=str(exc),
                ))
                stop_reason = {
                    "kind": exc.kind,
                    "group": "I" if group == 1 else "II",
                    "team_id": team_id,
                    "message": str(exc),
                }
                break
            except BatchStop as exc:
                entries.append(BatchTeamEntry(
                    group="I" if group == 1 else "II",
                    team_id=team_id,
                    team_name=team_name,
                    status="incomplete" if previous_capture else "failed",
                    requested_views=views,
                    capture_id=previous_capture,
                    failure_class=exc.kind,
                    error=str(exc),
                ))
                stop_reason = {
                    "kind": exc.kind,
                    "group": "I" if group == 1 else "II",
                    "team_id": team_id,
                    "message": str(exc),
                }
                break
            except Exception as exc:  # local parser/browser failures are isolated per team
                entries.append(BatchTeamEntry(
                    group="I" if group == 1 else "II",
                    team_id=team_id,
                    team_name=team_name,
                    status="incomplete" if previous_capture else "failed",
                    requested_views=views,
                    capture_id=previous_capture,
                    failure_class="local_acquisition_or_validation",
                    error=f"{type(exc).__name__}: {exc}",
                ))
                continue
            if not outcome.valid or not set(views) <= set(outcome.views):
                entries.append(BatchTeamEntry(
                    group="I" if group == 1 else "II",
                    team_id=team_id,
                    team_name=team_name,
                    status="incomplete",
                    requested_views=views,
                    capture_id=outcome.capture_id,
                    failure_class="capture_validation",
                    error="La captura no contiene todas las vistas solicitadas validadas.",
                ))
                continue
            entries.append(BatchTeamEntry(
                group="I" if group == 1 else "II",
                team_id=team_id,
                team_name=team_name,
                status="complete",
                requested_views=views,
                capture_id=outcome.capture_id,
            ))
        if stop_reason:
            break
    completed_ids = {(entry.group, entry.team_id) for entry in entries}
    if stop_reason:
        for group in groups:
            for team in teams_by_group.get(group, []):
                group_label = "I" if group == 1 else "II"
                key = (group_label, int(team["team_id"]))
                if key not in completed_ids:
                    entries.append(BatchTeamEntry(
                        group=group_label,
                        team_id=key[1],
                        team_name=str(team.get("name") or team.get("team_name") or ""),
                        status="pending",
                        requested_views=views,
                    ))
                    completed_ids.add(key)
    return {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": create_team_capture_id(),
        "groups": ["I" if group == 1 else "II" for group in groups],
        "requested_views": list(views),
        "execution": "sequential_one_team_at_a_time",
        "stopped_on_access_denial": bool(stop_reason and stop_reason["kind"] in {"access_denied", "challenge_required", "http_denial"}),
        "stop_reason": stop_reason,
        "summary": dict(Counter(entry.status for entry in entries)),
        "teams": [asdict(entry) for entry in entries],
    }


def write_batch_manifest(output_root: Path, manifest: dict[str, Any]) -> Path:
    """Publish a manifest atomically in a new versioned directory."""
    parent = output_root.expanduser() / "batch-manifests"
    parent.mkdir(parents=True, exist_ok=True)
    run_dir = parent / str(manifest["run_id"])
    staging = parent / f".{manifest['run_id']}.tmp"
    staging.mkdir(exist_ok=False)
    try:
        path = staging / "manifest.json"
        with path.open("x", encoding="utf-8") as target:
            json.dump(manifest, target, ensure_ascii=False, indent=2)
            target.write("\n")
        if run_dir.exists():
            raise FileExistsError(f"El manifiesto ya existe y no se sobrescribirá: {run_dir}")
        os.rename(staging, run_dir)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return run_dir / "manifest.json"


def find_valid_capture(
    output_root: Path,
    *,
    season: str,
    team_id: int,
    required_views: tuple[str, ...],
) -> tuple[str, Path] | None:
    """Find the newest capture whose validation and raw snapshots cover all views."""
    team_root = output_root.expanduser() / season / str(team_id)
    if not team_root.is_dir():
        return None
    candidates: list[tuple[str, Path]] = []
    for run in team_root.iterdir():
        metadata_path = run / "metadata" / "capture.json"
        validation_path = run / "validation" / "results.json"
        if not run.is_dir() or run.name.startswith(".") or not metadata_path.is_file() or not validation_path.is_file():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            snapshots = metadata.get("source_snapshots", {})
            if (
                int(metadata.get("team_id", -1)) != team_id
                or not validation.get("valid")
                or not set(required_views) <= set(metadata.get("requested_views", []))
                or not set(required_views) <= set(snapshots)
            ):
                continue
            snapshot_valid = True
            for view in required_views:
                evidence = snapshots[view]
                raw_path = run / evidence.get("path", "")
                if evidence.get("access_status") != "VALID" or evidence.get("http_status") != 200 or not raw_path.is_file():
                    snapshot_valid = False
                    break
                payload = raw_path.read_bytes()
                if evidence.get("compression") == "gzip" or raw_path.suffix == ".gz":
                    payload = gzip.decompress(payload)
                if evidence.get("sha256") and hashlib.sha256(payload).hexdigest() != evidence["sha256"]:
                    snapshot_valid = False
                    break
            if not snapshot_valid:
                continue
            candidates.append((str(metadata.get("created_at_utc") or metadata.get("capture_id") or run.name), run))
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    if not candidates:
        return None
    _, path = max(candidates, key=lambda item: item[0])
    metadata = json.loads((path / "metadata" / "capture.json").read_text(encoding="utf-8"))
    return str(metadata["capture_id"]), path
