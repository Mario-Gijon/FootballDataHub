"""Preflight or run the sequential, resumable 2026-27 player acquisition."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from football_data_hub.providers.bdfutbol.players.acquisition import (
    PLAYER_VIEWS,
    acquire_player_views,
)
from football_data_hub.providers.bdfutbol.players.batch import (
    PlayerBatchAlreadyRunning,
    PlayerBatchLock,
    atomic_status,
    estimate_acquisition_storage,
    load_verified_compact_sample,
    ordered_player_ids,
)
from football_data_hub.providers.bdfutbol.players.capture_store import PlayerCaptureStore
from football_data_hub.providers.bdfutbol.players.catalog import build_player_acquisition_progress

# A missing profile must be distinguishable from a transient HTTP failure by
# evidence captured from BDFutbol before a long unattended run can continue past it.
MISSING_PROFILE_POLICY_VERIFIED = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _matching_profile_processes(profile: Path) -> list[int]:
    expected = str(profile.expanduser().resolve()).encode()
    matches: list[int] = []
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return matches
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if expected in command and b"chrom" in command.lower():
            matches.append(int(entry.name))
    return sorted(matches)


def _load_compact_sample(compact_root: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
    try:
        manifest, entries = load_verified_compact_sample(compact_root)
        return manifest, entries, None
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return None, [], f"{type(exc).__name__}: {exc}"


def _make_plan(
    *,
    inventory_path: Path,
    capture_root: Path,
    compact_root: Path,
    progress_output: Path,
    profile: Path,
    browser_executable: Path,
    reserve_gib: float,
) -> tuple[dict[str, Any], dict[str, Any], dict[int, str]]:
    inventory_path = inventory_path.expanduser().resolve()
    capture_root = capture_root.expanduser().resolve()
    compact_root = compact_root.expanduser().resolve()
    progress = build_player_acquisition_progress(
        inventory_path=inventory_path,
        capture_root=capture_root,
        output_path=progress_output,
    )
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    ordered_ids, cohorts = ordered_player_ids(inventory)
    compact_manifest, compact_entries, compact_error = _load_compact_sample(compact_root)
    available = shutil.disk_usage(capture_root).free
    storage = estimate_acquisition_storage(
        progress=progress,
        inventory_player_count=len(ordered_ids),
        compact_entries=compact_entries,
        available_bytes=available,
        reserved_free_bytes=int(reserve_gib * 1024**3),
    ) if compact_entries else {
        "available_bytes": available,
        "available_gib": round(available / 1024**3, 3),
        "sufficient_margin": False,
        "reason": "Falta una generación compacta piloto íntegra para estimar almacenamiento",
        "compact_error": compact_error,
    }
    pending_views = progress["pending_views"]
    missing_by_view = {view: sum(item["view"] == view for item in pending_views) for view in PLAYER_VIEWS}
    roster_ids = [player_id for player_id in ordered_ids if cohorts[player_id] == "roster"]
    transfer_ids = [player_id for player_id in ordered_ids if cohorts[player_id] == "transfer_only"]
    profile = profile.expanduser().resolve()
    browser_executable = browser_executable.expanduser().resolve()
    xvfb_executable = shutil.which("Xvfb")
    matching_processes = _matching_profile_processes(profile)
    summary = progress["summary"]
    checks = {
        "inventory_matches_expected_1709": len(ordered_ids) == 1709,
        "cohort_sizes_match_expected": len(roster_ids) == 1065 and len(transfer_ids) == 644,
        "no_corrupt_manifests": not progress["corrupt_manifests"],
        "no_previous_access_or_structure_errors": summary["players_with_access_errors"] == 0,
        "chromium_available": browser_executable.is_file(),
        "xvfb_available": bool(xvfb_executable),
        "profile_not_in_use": not matching_processes,
        "compact_sample_valid": bool(compact_entries) and compact_manifest is not None,
        "storage_margin_sufficient": bool(storage.get("sufficient_margin")),
        "missing_profile_policy_verified": MISSING_PROFILE_POLICY_VERIFIED,
    }
    ready = all(checks.values())
    plan = {
        "status": "READY_FOR_EXPLICIT_EXECUTION" if ready else "BLOCKED",
        "execution_started": False,
        "season": "2026-27",
        "inventory_path": str(inventory_path),
        "capture_root": str(capture_root),
        "progress_output": str(progress_output.expanduser().resolve()),
        "compact_root": str(compact_root),
        "compact_generation_id": compact_manifest.get("generation_id") if compact_manifest else None,
        "capture_root_free_gib": storage.get("available_gib"),
        "player_counts": {
            "inventory": len(ordered_ids),
            "roster": len(roster_ids),
            "transfer_only": len(transfer_ids),
            "complete_base_views": summary["players_with_all_base_views"],
            "pending_players": summary["players_pending"],
            "pending_views": summary["base_view_navigations_pending"],
            "pending_by_view": missing_by_view,
        },
        "cohort_order": {
            "roster_first_ids": roster_ids[:5],
            "transfer_only_first_ids": transfer_ids[:5],
            "deterministic_id_order": True,
        },
        "acquisition": {
            "browser": "SeleniumBase Pure CDP / Chromium",
            "xvfb": xvfb_executable,
            "profile": str(profile),
            "profile_process_ids": matching_processes,
            "pause_seconds_minimum": 5,
            "parallel_browsers": 1,
            "filter_variants": False,
        },
        "storage": storage,
        "checks": checks,
        "block_reasons": [
            "Falta validar con evidencia de BDFutbol cómo distinguir un perfil inexistente "
            "de un HTTP 404 transitorio; el lote no debe saltar ese caso automáticamente."
        ] if not MISSING_PROFILE_POLICY_VERIFIED else [],
        "progress_sha256": progress.get("output_sha256"),
    }
    return plan, progress, cohorts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    home = Path.home()
    parser.add_argument(
        "--inventory", type=Path,
        default=Path(os.environ.get(
            "FDH_PLAYER_INVENTORY",
            str(home / "FootballDataHub-data/players/inventory-2026-27/players.json"),
        )),
    )
    parser.add_argument(
        "--capture-root", type=Path,
        default=Path(os.environ.get(
            "FDH_PLAYER_CAPTURE_ROOT",
            str(home / "FootballDataHub-data/players/player-captures"),
        )),
    )
    parser.add_argument(
        "--compact-root", type=Path,
        default=Path(os.environ.get(
            "FDH_PLAYER_COMPACT_ROOT",
            str(home / "FootballDataHub-data/players/compact-2026-27"),
        )),
    )
    parser.add_argument(
        "--profile", type=Path,
        default=Path(os.environ.get(
            "FDH_BDFUTBOL_PROFILE", str(home / ".football-data-hub-chromium-pure-cdp")
        )),
    )
    parser.add_argument("--browser-executable", type=Path, default=Path("/usr/bin/chromium"))
    parser.add_argument("--pause-seconds", type=float, default=5.0)
    parser.add_argument("--settle-ms", type=int, default=900)
    parser.add_argument("--reserve-gib", type=float, default=1.5)
    parser.add_argument("--execute", action="store_true", help="Empieza adquisición real; sin esta opción solo muestra el preflight.")
    parser.add_argument("--resume", metavar="CAPTURE_ID", help="Reanuda un run interrumpido conservando sus snapshots.")
    parser.add_argument("--status", action="store_true", help="Muestra el estado persistido sin iniciar adquisición.")
    parser.add_argument("--progress-output", type=Path)
    parser.add_argument("--status-file", type=Path)
    args = parser.parse_args(argv)
    capture_root = args.capture_root.expanduser().resolve()
    progress_output = args.progress_output or capture_root / "acquisition-progress-2026-27.json"
    status_path = args.status_file or capture_root / "acquisition-state-2026-27.json"

    if args.status:
        try:
            print(status_path.read_text(encoding="utf-8"))
        except OSError as exc:
            print(json.dumps({"status": "unavailable", "error": str(exc)}))
            return 1
        return 0

    if args.pause_seconds < 5:
        parser.error("La pausa de adquisición no puede ser inferior a 5 segundos")
    if args.reserve_gib <= 0:
        parser.error("--reserve-gib debe ser mayor que cero")
    if args.resume and not args.resume.replace("-", "").replace(".", "").isalnum():
        parser.error("CAPTURE_ID de reanudación contiene caracteres no admitidos")

    try:
        plan, progress, cohorts = _make_plan(
            inventory_path=args.inventory,
            capture_root=capture_root,
            compact_root=args.compact_root,
            progress_output=progress_output,
            profile=args.profile,
            browser_executable=args.browser_executable,
            reserve_gib=args.reserve_gib,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 3

    if not args.execute:
        plan["requested_resume_capture_id"] = args.resume
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0 if plan["status"] == "READY_FOR_EXPLICIT_EXECUTION" else 3
    if plan["status"] != "READY_FOR_EXPLICIT_EXECUTION":
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 3

    if args.resume:
        run_id = args.resume
        manifest_path = capture_root / run_id / "manifest.json"
        try:
            existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"status": "BLOCKED", "error": f"No se puede reanudar: {exc}"}))
            return 3
        if existing_manifest.get("capture_id") != run_id or existing_manifest.get("status") == "complete":
            print(json.dumps({"status": "BLOCKED", "error": "El run no existe, no coincide o ya está completo"}))
            return 3
    else:
        run_id = None

    try:
        with PlayerBatchLock(capture_root):
            run_store = PlayerCaptureStore(capture_root, capture_id=run_id) if run_id else PlayerCaptureStore(capture_root)
            run_id = run_store.capture_id
            pending = {
                (int(item["player_id"]), str(item["view"]))
                for item in progress.get("pending_views", [])
            }
            players = {
                int(item["player_id"]): item for item in progress.get("players", [])
            }
            summary = progress["summary"]
            complete_ids = {
                player_id for player_id, item in players.items()
                if item.get("status") == "COMPLETE_BASE_VIEWS"
            }
            status: dict[str, Any] = {
                "schema_version": "football_data_hub.player_batch_runtime_status.v1",
                "status": "running",
                "capture_id": run_id,
                "pid": os.getpid(),
                "started_at_utc": _utc_now(),
                "updated_at_utc": _utc_now(),
                "inventory_players": summary["inventory_players"],
                "roster_players": summary["roster_players"],
                "transfer_only_players": summary["transfer_only_players"],
                "completed_players": len(complete_ids),
                "base_views_valid": summary["captured_valid_base_views"],
                "base_views_pending": summary["base_view_navigations_pending"],
                "new_navigations_this_run": 0,
                "current_player_id": None,
                "current_cohort": None,
                "current_view": None,
                "last_snapshot": None,
                "last_error": None,
                "status_file": str(status_path.expanduser().resolve()),
                "progress_file": str(progress_output.expanduser().resolve()),
                "log_outside_git": "Usar la redirección del comando tmux indicada en docs/player_01c0_mass_acquisition.md",
            }
            atomic_status(status_path, status)

            def on_snapshot_saved(snapshot: dict[str, Any]) -> None:
                player_id = int(snapshot["player_id"])
                view = str(snapshot["view"])
                key = (player_id, view)
                if key in pending:
                    pending.remove(key)
                    status["base_views_valid"] += 1
                    status["base_views_pending"] -= 1
                    if not any(item[0] == player_id for item in pending):
                        complete_ids.add(player_id)
                status.update({
                    "updated_at_utc": _utc_now(),
                    "new_navigations_this_run": status["new_navigations_this_run"] + 1,
                    "completed_players": len(complete_ids),
                    "current_player_id": player_id,
                    "current_cohort": cohorts[player_id],
                    "current_view": view,
                    "last_snapshot": {
                        "player_id": player_id,
                        "view": view,
                        "capture_id": snapshot["capture_id"],
                        "snapshot_id": snapshot["snapshot_id"],
                        "html_sha256": snapshot["html_sha256"],
                        "saved_at_utc": snapshot.get("captured_at_utc"),
                        "parse_validation": snapshot.get("parse_validation"),
                    },
                })
                atomic_status(status_path, status)

            ordered_ids = sorted(
                players,
                key=lambda player_id: (0 if cohorts[player_id] == "roster" else 1, player_id),
            )
            result = acquire_player_views(
                player_ids=ordered_ids,
                inventory_path=args.inventory,
                capture_root=capture_root,
                profile_dir=args.profile,
                browser_executable=args.browser_executable,
                capture_id=run_id,
                settle_ms=args.settle_ms,
                pause_seconds=args.pause_seconds,
                explore_filters=False,
                views=PLAYER_VIEWS,
                progress_index=progress,
                on_snapshot_saved=on_snapshot_saved,
            )
            refreshed = build_player_acquisition_progress(
                inventory_path=args.inventory,
                capture_root=capture_root,
                output_path=progress_output,
            )
            status.update({
                "status": "complete",
                "updated_at_utc": _utc_now(),
                "completed_at_utc": _utc_now(),
                "result": {
                    key: result.get(key)
                    for key in (
                        "capture_id", "capture_dir", "snapshot_count", "navigation_count",
                        "verified_navigation_count_total", "status", "filter_variants",
                        "reused_snapshot_count",
                    )
                },
                "final_summary": refreshed["summary"],
                "last_error": None,
            })
            atomic_status(status_path, status)
            print(json.dumps(status, ensure_ascii=False, indent=2))
            return 0
    except PlayerBatchAlreadyRunning as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False))
        return 3
    except KeyboardInterrupt:
        status.update({"status": "interrupted", "updated_at_utc": _utc_now(), "last_error": "KeyboardInterrupt"})
        atomic_status(status_path, status)
        print(json.dumps(status, ensure_ascii=False, indent=2), file=sys.stderr)
        return 130
    except Exception as exc:
        try:
            refreshed = build_player_acquisition_progress(
                inventory_path=args.inventory,
                capture_root=capture_root,
                output_path=progress_output,
            )
            summary = refreshed["summary"]
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            summary = None
        error = {
            "status": "stopped",
            "updated_at_utc": _utc_now(),
            "last_error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "player_id": getattr(exc, "player_id", None),
                "view": getattr(exc, "view", None),
                "access_status": getattr(exc, "status", None),
            },
            "final_summary": summary,
        }
        if "status" in locals():
            status.update(error)
            atomic_status(status_path, status)
            error = status
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
