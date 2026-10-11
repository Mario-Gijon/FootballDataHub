"""Sequential, resumable orchestration primitives for team-profile captures."""

from __future__ import annotations

import json
import math
import os
import shutil
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from .acquisition import create_team_capture_id
from .capture_store import CaptureInspection, inspect_team_capture

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
    acquired_views: tuple[str, ...] = ()
    reused_views: tuple[str, ...] = ()
    follow_states: tuple[str, ...] = ()
    acquired_follow_states: tuple[str, ...] = ()
    reused_follow_states: tuple[str, ...] = ()
    catalog_reference: dict[str, Any] | None = None
    captured_at_utc: str | None = None
    acquisition_timestamps: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class BatchTeamEntry:
    group: str
    team_id: int
    team_name: str
    status: BatchStatus
    requested_views: tuple[str, ...]
    capture_id: str | None = None
    seed_capture_id: str | None = None
    reused_existing_capture: bool = False
    acquired_views: tuple[str, ...] = ()
    reused_views: tuple[str, ...] = ()
    follow_states: tuple[str, ...] = ()
    acquired_follow_states: tuple[str, ...] = ()
    reused_follow_states: tuple[str, ...] = ()
    coverage: dict[str, Any] | None = None
    catalog_reference: dict[str, Any] | None = None
    captured_at_utc: str | None = None
    acquisition_timestamps: dict[str, Any] | None = None
    failure_class: str | None = None
    error: str | None = None


def run_team_batch(
    *,
    teams_by_group: dict[int, list[dict[str, Any]]],
    groups: tuple[int, ...],
    requested_views: tuple[str, ...],
    find_complete_capture: Callable[[int, int, tuple[str, ...]], str | CaptureInspection | None],
    find_partial_capture: Callable[[int, int], str | CaptureInspection | None],
    process_team: Callable[[int, dict[str, Any], tuple[str, ...]], BatchTeamOutcome],
    catalog_references_by_group: dict[int, dict[str, Any]] | None = None,
    pause_seconds: float = 0.0,
) -> dict[str, Any]:
    """Run teams in a single sequence, skipping complete captures and stopping on denial."""
    if not groups or any(group not in {1, 2} for group in groups):
        raise ValueError("Selecciona el Grupo I, el Grupo II o ambos")
    views = tuple(dict.fromkeys(requested_views))
    if not views:
        raise ValueError("Selecciona al menos una vista")
    if not math.isfinite(pause_seconds) or pause_seconds < 0:
        raise ValueError("pause_seconds debe ser finito y no negativo")
    entries: list[BatchTeamEntry] = []
    stop_reason: dict[str, Any] | None = None
    last_process_at: float | None = None
    for group in groups:
        for team in teams_by_group.get(group, []):
            team_id = int(team["team_id"])
            team_name = str(team.get("name") or team.get("team_name") or "")
            completed_capture = find_complete_capture(group, team_id, views)
            if completed_capture:
                if isinstance(completed_capture, CaptureInspection):
                    complete_info = completed_capture
                    completed_id = completed_capture.capture_id
                    complete_summary = completed_capture.manifest_summary()
                    complete_metadata = completed_capture.metadata
                else:
                    complete_info = None
                    completed_id = str(completed_capture)
                    complete_summary = None
                    complete_metadata = {}
                entries.append(BatchTeamEntry(
                    group="I" if group == 1 else "II",
                    team_id=team_id,
                    team_name=team_name,
                    status="complete",
                    requested_views=views,
                    capture_id=completed_id,
                    reused_existing_capture=True,
                    reused_views=tuple(views),
                    follow_states=complete_info.valid_follow_states if complete_info else (),
                    reused_follow_states=complete_info.valid_follow_states if complete_info else (),
                    coverage=complete_summary,
                    catalog_reference=(
                        complete_metadata.get("related_team_catalog")
                        or (catalog_references_by_group or {}).get(group)
                    ),
                    captured_at_utc=complete_metadata.get("captured_at_utc"),
                    acquisition_timestamps=(
                        {
                            "views": {
                                view: item.get("captured_at_utc")
                                for view, item in (complete_metadata.get("source_snapshots") or {}).items()
                            },
                            "follow_states": {
                                state: item.get("captured_at_utc")
                                for state, item in (complete_metadata.get("follow_states") or {}).items()
                            },
                        }
                        if complete_info
                        else None
                    ),
                ))
                continue
            previous_capture = find_partial_capture(group, team_id)
            previous_info = previous_capture if isinstance(previous_capture, CaptureInspection) else None
            previous_id = (
                previous_info.capture_id
                if previous_info
                else str(previous_capture) if previous_capture else None
            )
            previous_acquisition_timestamps = (
                {
                    "views": {
                        view: item.get("captured_at_utc")
                        for view, item in (previous_info.metadata.get("source_snapshots") or {}).items()
                    },
                    "follow_states": {
                        state: item.get("captured_at_utc")
                        for state, item in (previous_info.metadata.get("follow_states") or {}).items()
                    },
                }
                if previous_info
                else None
            )
            previous_captured_at = (
                previous_info.metadata.get("captured_at_utc") if previous_info else None
            )
            try:
                if last_process_at is not None and pause_seconds:
                    time.sleep(pause_seconds)
                outcome = process_team(group, team, views)
                last_process_at = time.monotonic()
            except BatchAccessDenied as exc:
                last_process_at = time.monotonic()
                entries.append(BatchTeamEntry(
                    group="I" if group == 1 else "II",
                    team_id=team_id,
                    team_name=team_name,
                    status="incomplete" if previous_capture else "failed",
                    requested_views=views,
                    capture_id=previous_id,
                    seed_capture_id=previous_id,
                    coverage=previous_info.manifest_summary() if previous_info else None,
                    catalog_reference=(catalog_references_by_group or {}).get(group),
                    captured_at_utc=previous_captured_at,
                    acquisition_timestamps=previous_acquisition_timestamps,
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
                last_process_at = time.monotonic()
                entries.append(BatchTeamEntry(
                    group="I" if group == 1 else "II",
                    team_id=team_id,
                    team_name=team_name,
                    status="incomplete" if previous_capture else "failed",
                    requested_views=views,
                    capture_id=previous_id,
                    seed_capture_id=previous_id,
                    coverage=previous_info.manifest_summary() if previous_info else None,
                    catalog_reference=(catalog_references_by_group or {}).get(group),
                    captured_at_utc=previous_captured_at,
                    acquisition_timestamps=previous_acquisition_timestamps,
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
                last_process_at = time.monotonic()
                entries.append(BatchTeamEntry(
                    group="I" if group == 1 else "II",
                    team_id=team_id,
                    team_name=team_name,
                    status="incomplete" if previous_capture else "failed",
                    requested_views=views,
                    capture_id=previous_id,
                    seed_capture_id=previous_id,
                    coverage=previous_info.manifest_summary() if previous_info else None,
                    catalog_reference=(catalog_references_by_group or {}).get(group),
                    captured_at_utc=previous_captured_at,
                    acquisition_timestamps=previous_acquisition_timestamps,
                    failure_class="local_acquisition_or_validation",
                    error=f"{type(exc).__name__}: {exc}",
                ))
                continue
            required_follow_states = {"p", "t", "go", "tot"} if "follow" in views else set()
            if (
                not outcome.valid
                or not set(views) <= set(outcome.views)
                or not required_follow_states <= set(outcome.follow_states)
            ):
                entries.append(BatchTeamEntry(
                    group="I" if group == 1 else "II",
                    team_id=team_id,
                    team_name=team_name,
                    status="incomplete",
                    requested_views=views,
                    capture_id=outcome.capture_id,
                    seed_capture_id=previous_id,
                    acquired_views=outcome.acquired_views,
                    reused_views=outcome.reused_views,
                    follow_states=outcome.follow_states,
                    acquired_follow_states=outcome.acquired_follow_states,
                    reused_follow_states=outcome.reused_follow_states,
                    catalog_reference=outcome.catalog_reference or (catalog_references_by_group or {}).get(group),
                    captured_at_utc=outcome.captured_at_utc,
                    acquisition_timestamps=outcome.acquisition_timestamps,
                    failure_class="capture_validation",
                    error="La captura no contiene todas las vistas y estados de Seguimiento solicitados validados.",
                ))
                continue
            entries.append(BatchTeamEntry(
                group="I" if group == 1 else "II",
                team_id=team_id,
                team_name=team_name,
                status="complete",
                requested_views=views,
                capture_id=outcome.capture_id,
                seed_capture_id=previous_id,
                acquired_views=outcome.acquired_views,
                reused_views=outcome.reused_views,
                follow_states=outcome.follow_states,
                acquired_follow_states=outcome.acquired_follow_states,
                reused_follow_states=outcome.reused_follow_states,
                catalog_reference=outcome.catalog_reference or (catalog_references_by_group or {}).get(group),
                captured_at_utc=outcome.captured_at_utc,
                acquisition_timestamps=outcome.acquisition_timestamps,
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
                        catalog_reference=(catalog_references_by_group or {}).get(group),
                    ))
                    completed_ids.add(key)
    return {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": create_team_capture_id(),
        "groups": ["I" if group == 1 else "II" for group in groups],
        "requested_views": list(views),
        "required_follow_states": ["p", "t", "go", "tot"] if "follow" in views else [],
        "pause_seconds": pause_seconds,
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


def inspect_team_captures(
    output_root: Path,
    *,
    season: str,
    team_catalog_record: dict[str, Any],
    competition,
    team_catalog_reference: dict[str, Any],
    group_team_catalog: list[dict[str, Any]],
    known_matches: list[dict[str, Any]],
    required_views: tuple[str, ...],
) -> tuple[CaptureInspection, ...]:
    """Inspect every version for a club and revalidate its contents offline."""
    team_id = int(team_catalog_record["team_id"])
    team_root = output_root.expanduser() / season / str(team_id)
    if not team_root.is_dir():
        return ()
    inspections: list[CaptureInspection] = []
    for run in sorted(team_root.iterdir()):
        if not run.is_dir() or run.name.startswith("."):
            continue
        inspections.append(inspect_team_capture(
            run,
            team_catalog_record=team_catalog_record,
            competition=competition,
            team_catalog_reference=team_catalog_reference,
            group_team_catalog=group_team_catalog,
            known_matches=known_matches,
            required_views=required_views,
        ))
    return tuple(inspections)


def _capture_sort_key(capture: CaptureInspection) -> tuple[tuple[int, int, int, int], str, str]:
    created = str(
        capture.metadata.get("created_at_utc")
        or capture.metadata.get("captured_at_utc")
        or capture.capture_id
    )
    return capture.coverage_score, created, capture.capture_id


def find_best_capture(
    output_root: Path,
    *,
    season: str,
    team_catalog_record: dict[str, Any],
    competition,
    team_catalog_reference: dict[str, Any],
    group_team_catalog: list[dict[str, Any]],
    known_matches: list[dict[str, Any]],
    required_views: tuple[str, ...],
) -> CaptureInspection | None:
    """Prefer the most complete integrity-checked seed, then newest among ties."""
    candidates = [
        item
        for item in inspect_team_captures(
            output_root,
            season=season,
            team_catalog_record=team_catalog_record,
            competition=competition,
            team_catalog_reference=team_catalog_reference,
            group_team_catalog=group_team_catalog,
            known_matches=known_matches,
            required_views=required_views,
        )
        if item.reusable_as_seed
    ]
    return max(candidates, key=_capture_sort_key) if candidates else None


def find_valid_capture(
    output_root: Path,
    *,
    season: str,
    team_catalog_record: dict[str, Any],
    competition,
    team_catalog_reference: dict[str, Any],
    group_team_catalog: list[dict[str, Any]],
    known_matches: list[dict[str, Any]],
    required_views: tuple[str, ...],
) -> CaptureInspection | None:
    """Return a capture only when it meets the current evidence and data policy."""
    candidates = [
        item
        for item in inspect_team_captures(
            output_root,
            season=season,
            team_catalog_record=team_catalog_record,
            competition=competition,
            team_catalog_reference=team_catalog_reference,
            group_team_catalog=group_team_catalog,
            known_matches=known_matches,
            required_views=required_views,
        )
        if item.complete_for_current_policy
    ]
    if not candidates:
        return None
    return max(candidates, key=_capture_sort_key)
