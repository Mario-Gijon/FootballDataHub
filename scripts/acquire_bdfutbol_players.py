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
    STOP_ON_UNVERIFIED_HTTP_ERROR,
    access_policy_is_complete,
    acquire_player_views,
)
from football_data_hub.providers.bdfutbol.players.batch import (
    PlayerBatchAlreadyRunning,
    PlayerBatchLock,
    PlayerDiskSpaceGuard,
    atomic_status,
    estimate_acquisition_storage,
    load_verified_compact_sample,
    ordered_player_ids,
    validate_player_batch_completion,
)
from football_data_hub.providers.bdfutbol.players.capture_store import PlayerCaptureStore
from football_data_hub.providers.bdfutbol.players.catalog import build_player_acquisition_progress

EXPECTED_INVENTORY_PLAYERS = 1709


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _matching_profile_processes(profile: Path, proc_root: Path = Path("/proc")) -> list[int]:
    expected = profile.expanduser().resolve()
    browser_names = {
        "brave", "brave-browser", "chrome", "google-chrome",
        "google-chrome-stable", "chromium", "chromium-browser",
    }
    matches: list[int] = []
    if not proc_root.is_dir():
        return matches
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            arguments = [
                os.fsdecode(value) for value in (entry / "cmdline").read_bytes().split(b"\0") if value
            ]
        except OSError:
            continue
        if not arguments or Path(arguments[0]).name.casefold() not in browser_names:
            continue
        profile_value = None
        for index, argument in enumerate(arguments[1:], start=1):
            if argument.startswith("--user-data-dir="):
                profile_value = argument.partition("=")[2]
                break
            if argument == "--user-data-dir" and index + 1 < len(arguments):
                profile_value = arguments[index + 1]
                break
        if profile_value:
            try:
                if Path(profile_value).expanduser().resolve() == expected:
                    matches.append(int(entry.name))
            except OSError:
                continue
    return sorted(matches)


def _load_compact_sample(compact_root: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
    try:
        manifest, entries = load_verified_compact_sample(compact_root)
        return manifest, entries, None
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return None, [], f"{type(exc).__name__}: {exc}"


def _explicit_retry_is_authorized(
    progress: dict[str, Any],
    retry_target: tuple[int, str] | None,
    retry_capture_id: str | None,
) -> bool:
    if not retry_target or not retry_capture_id:
        return False
    all_issues = [
        {"player_id": record["player_id"], "view": view, **issue}
        for record in progress.get("players", [])
        for view, issues in record.get("access_issues", {}).items()
        for issue in issues
    ]
    candidates = progress.get("retryable_navigation_errors", [])
    issue = all_issues[0] if len(all_issues) == 1 else {}
    return bool(
        len(all_issues) == 1
        and len(candidates) == 1
        and issue.get("player_id") == retry_target[0]
        and issue.get("view") == retry_target[1]
        and issue.get("capture_id") == retry_capture_id
        and issue.get("error_code") == "NAVIGATION_ERROR"
        and issue.get("access_status") == "NAVIGATION_ERROR"
        and issue.get("http_status") is None
        and candidates[0].get("player_id") == retry_target[0]
        and candidates[0].get("view") == retry_target[1]
        and candidates[0].get("capture_id") == retry_capture_id
        and candidates[0].get("http_status") is None
    )


def _make_plan(
    *,
    inventory_path: Path,
    capture_root: Path,
    compact_root: Path,
    progress_output: Path,
    profile: Path,
    browser_executable: Path,
    reserve_gib: float,
    retry_target: tuple[int, str] | None = None,
    retry_capture_id: str | None = None,
    progress_callback: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[int, str]]:
    inventory_path = inventory_path.expanduser().resolve()
    capture_root = capture_root.expanduser().resolve()
    compact_root = compact_root.expanduser().resolve()
    progress = build_player_acquisition_progress(
        inventory_path=inventory_path,
        capture_root=capture_root,
        output_path=progress_output,
        progress_callback=progress_callback,
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
    explicit_retry_authorized = _explicit_retry_is_authorized(
        progress, retry_target, retry_capture_id,
    )
    no_access_errors = summary["players_with_access_errors"] == 0
    checks = {
        "inventory_matches_expected_1709": len(ordered_ids) == EXPECTED_INVENTORY_PLAYERS,
        "cohort_sizes_match_expected": len(roster_ids) == 1065 and len(transfer_ids) == 644,
        "no_corrupt_manifests": not progress["corrupt_manifests"],
        "no_previous_access_or_structure_errors": no_access_errors or explicit_retry_authorized,
        "explicit_retry_is_single_unconfirmed_timeout": retry_target is None or explicit_retry_authorized,
        "chromium_available": browser_executable.is_file(),
        "xvfb_available": bool(xvfb_executable),
        "profile_not_in_use": not matching_processes,
        "compact_sample_valid": bool(compact_entries) and compact_manifest is not None,
        "storage_margin_sufficient": bool(storage.get("sufficient_margin")),
        "stop_on_unverified_http_error_policy": access_policy_is_complete(),
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
        "access_policy": {
            "name": STOP_ON_UNVERIFIED_HTTP_ERROR,
            "behavior": "Solo VALID con HTTP 200 continúa; cualquier error durante la adquisición detiene el lote.",
            "http_404_means_missing_player": False,
            "http_404_action": "record_and_stop",
            "transient_navigation_retry": (
                "Un timeout único sin HTTP confirmado puede ejecutarse una vez solo con --retry-transient-navigation PLAYER_ID/VIEW y el capture_id correspondiente. Si vuelve a fallar, la política detiene el lote."
            ),
        },
        "explicit_retry": {
            "target": f"{retry_target[0]}/{retry_target[1]}" if retry_target else None,
            "capture_id": retry_capture_id if retry_target else None,
            "authorized": explicit_retry_authorized if retry_target else False,
            "navigation_attempts_permitted": 1 if explicit_retry_authorized else 0,
        },
        "checks": checks,
        "block_reasons": [],
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
    parser.add_argument(
        "--retry-transient-navigation", metavar="PLAYER_ID/VIEW",
        help="Autoriza exactamente una navegación explícita para un único TimeoutError sin HTTP confirmado; exige --resume y no reintenta automáticamente.",
    )
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
    retry_target: tuple[int, str] | None = None
    if args.retry_transient_navigation:
        if not args.resume:
            parser.error("--retry-transient-navigation requiere --resume CAPTURE_ID")
        try:
            player_text, view = args.retry_transient_navigation.split("/", 1)
            retry_target = (int(player_text), view)
        except (TypeError, ValueError):
            parser.error("Use --retry-transient-navigation PLAYER_ID/VIEW")
        if retry_target[0] <= 0 or retry_target[1] not in PLAYER_VIEWS:
            parser.error("PLAYER_ID/VIEW no corresponde a una vista admitida")

    last_progress_at = 0.0

    def report_preflight_progress(event: dict[str, Any]) -> None:
        nonlocal last_progress_at
        now = float(event.get("elapsed_seconds") or 0)
        if event.get("phase") not in {"manifest_scan_started", "manifest_complete"} and now - last_progress_at < 2.0:
            return
        last_progress_at = now
        print(json.dumps({"preflight_progress": event}, ensure_ascii=False), file=sys.stderr, flush=True)

    try:
        plan, progress, cohorts = _make_plan(
            inventory_path=args.inventory,
            capture_root=capture_root,
            compact_root=args.compact_root,
            progress_output=progress_output,
            profile=args.profile,
            browser_executable=args.browser_executable,
            reserve_gib=args.reserve_gib,
            retry_target=retry_target,
            retry_capture_id=args.resume,
            progress_callback=report_preflight_progress,
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
                "current_requested_url": None,
                "last_snapshot": None,
                "last_error": None,
                "last_disk_check": None,
                "final_validation": None,
                "status_file": str(status_path.expanduser().resolve()),
                "progress_file": str(progress_output.expanduser().resolve()),
                "log_outside_git": "Usar la redirección del comando tmux indicada en docs/player_01c0_mass_acquisition.md",
            }
            atomic_status(status_path, status)

            compact_manifest, compact_entries, compact_error = _load_compact_sample(args.compact_root)
            if not compact_entries or compact_manifest is None:
                raise ValueError(
                    "No se pudo verificar la muestra compacta para el control dinámico: "
                    f"{compact_error}"
                )
            disk_guard = PlayerDiskSpaceGuard(
                capture_root=capture_root,
                inventory_player_count=summary["inventory_players"],
                compact_entries=compact_entries,
                reserved_free_bytes=int(args.reserve_gib * 1024**3),
            )

            def remaining_progress() -> dict[str, Any]:
                records = []
                for record in progress.get("players", []):
                    player_id = int(record["player_id"])
                    records.append({
                        **record,
                        "views_pending": [
                            view for view in record.get("views_pending", [])
                            if (player_id, view) in pending
                        ],
                    })
                return {**progress, "players": records}

            def before_navigation(player_id: int, view: str, url: str) -> None:
                status.update({
                    "updated_at_utc": _utc_now(),
                    "current_player_id": player_id,
                    "current_cohort": cohorts[player_id],
                    "current_view": view,
                    "current_requested_url": url,
                })
                atomic_status(status_path, status)
                live_progress = remaining_progress()
                estimate = disk_guard.check_before_navigation(
                    progress=live_progress,
                    player_id=player_id,
                    view=view,
                    requested_url=url,
                )
                status["last_disk_check"] = {
                    "stage": "before_navigation",
                    "at_utc": _utc_now(),
                    "available_bytes": estimate["available_bytes"],
                    "projected_free_bytes": estimate["projected_free_bytes"],
                    "reserved_free_bytes": estimate["reserved_free_bytes"],
                    "remaining_pending_views": sum(
                        len(item["views_pending"]) for item in live_progress["players"]
                    ),
                }
                atomic_status(status_path, status)

            def before_snapshot_save(player_id: int, view: str, url: str, html: str) -> None:
                estimate = disk_guard.check_before_snapshot(
                    html=html,
                    player_id=player_id,
                    view=view,
                    requested_url=url,
                )
                status["last_disk_check"] = {
                    "stage": "before_snapshot_write",
                    "at_utc": _utc_now(),
                    **estimate,
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
                raw_path = (capture_root / run_id / str(snapshot.get("raw_path") or "")).resolve()
                metadata_path = (capture_root / run_id / str(snapshot.get("metadata_path") or "")).resolve()
                if player_id in players:
                    players[player_id].setdefault("view_snapshots", {})[view] = {
                        "http_status": snapshot.get("http_status"),
                        "access_status": "VALID",
                        "compressed_bytes": raw_path.stat().st_size if raw_path.is_file() else 0,
                        "metadata_bytes": metadata_path.stat().st_size if metadata_path.is_file() else 0,
                    }
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
                free_bytes = disk_guard.check_after_snapshot(
                    player_id=player_id,
                    view=view,
                    requested_url=str(snapshot.get("requested_url") or ""),
                )
                status["last_disk_check"] = {
                    "stage": "after_snapshot_write",
                    "at_utc": _utc_now(),
                    "available_bytes": free_bytes,
                    "reserved_free_bytes": int(args.reserve_gib * 1024**3),
                }
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
                before_navigation=before_navigation,
                before_snapshot_save=before_snapshot_save,
            )
            refreshed = build_player_acquisition_progress(
                inventory_path=args.inventory,
                capture_root=capture_root,
                output_path=progress_output,
            )
            final_validation = validate_player_batch_completion(
                refreshed,
                expected_player_count=EXPECTED_INVENTORY_PLAYERS,
            )
            if not final_validation["valid"]:
                status.update({
                    "status": "stopped",
                    "updated_at_utc": _utc_now(),
                    "last_error": {
                        "error_code": "GLOBAL_COMPLETENESS_VALIDATION_FAILED",
                        "message": "No se certifica cobertura global completa de las cuatro vistas base.",
                    },
                    "final_summary": refreshed["summary"],
                    "final_validation": final_validation,
                })
                atomic_status(status_path, status)
                print(json.dumps(status, ensure_ascii=False, indent=2), file=sys.stderr)
                return 1
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
                "final_validation": final_validation,
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
        diagnostic = getattr(exc, "diagnostic", {})
        requested_url = diagnostic.get("requested_url")
        if not requested_url and "status" in locals():
            requested_url = status.get("current_requested_url")
        error = {
            "status": "stopped",
            "updated_at_utc": _utc_now(),
            "last_error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "player_id": getattr(exc, "player_id", None),
                "view": getattr(exc, "view", None),
                "access_status": getattr(exc, "status", None),
                "error_code": getattr(exc, "error_code", None),
                "requested_url": requested_url,
                "diagnostic": diagnostic,
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
