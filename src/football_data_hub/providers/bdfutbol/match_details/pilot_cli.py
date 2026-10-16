"""Offline preflight and explicitly gated one-match discovery pilot CLI."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from football_data_hub.core.browser_runtime import BrowserRuntimeConfig
from football_data_hub.core.browser_session import BrowserSessionManager
from football_data_hub.providers.bdfutbol.access import BDFutbolAccess

from .acquisition import run_match_discovery_pilot, select_pilot_record
from .inventory import build_match_detail_inventory, load_verified_match_generation
from .store import MatchDetailStore

EXPECTED_INVENTORY_ID = "match-detail-inventory-8cf339654c80c0ef"
EXPECTED_GENERATION_ID = "match-00-4ad1d610507e425d"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _read_inventory_directory(
    path: Path,
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    requested = path.expanduser().absolute()
    current = requested
    while current != current.parent:
        if current.is_symlink():
            raise ValueError(f"La ruta del inventario contiene symlink: {current}")
        current = current.parent
    inventory_path = requested / "inventory.json"
    manifest_path = requested / "manifest.json"
    if any(
        candidate.is_symlink() or not candidate.is_file()
        for candidate in (inventory_path, manifest_path)
    ):
        raise ValueError(
            "Faltan inventory.json/manifest.json regulares en el inventario persistido"
        )
    inventory_raw = inventory_path.read_bytes()
    manifest_raw = manifest_path.read_bytes()
    inventory = json.loads(inventory_raw)
    manifest = json.loads(manifest_raw)
    if not isinstance(inventory, dict) or not isinstance(manifest, dict):
        raise ValueError("Inventario y manifiesto deben ser objetos JSON")
    expected_manifest = {
        "schema_version": "football_data_hub.match_detail_inventory_manifest.v1",
        "inventory_id": inventory.get("inventory_id"),
        "inventory_sha256": _sha256(_canonical_json(inventory)),
        "record_count": len(inventory.get("matches", [])),
        "source_generation": inventory.get("source_generation"),
    }
    if manifest != expected_manifest or manifest_raw != _canonical_json(manifest):
        raise ValueError("Manifiesto persistido del inventario no coincide")
    if requested.name != inventory.get("inventory_id"):
        raise ValueError("La carpeta no coincide con inventory_id")
    return inventory, manifest, _sha256(inventory_raw), _sha256(manifest_raw)


def build_pilot_preflight(
    *,
    inventory_dir: Path,
    generation_root: Path,
    data_root: Path,
    store_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read-only verification of persisted plan, source generation and store."""

    persisted, manifest, inventory_hash, manifest_hash = _read_inventory_directory(
        inventory_dir
    )
    if persisted.get("inventory_id") != EXPECTED_INVENTORY_ID:
        raise ValueError(
            "El piloto solo admite el inventory_id aprobado para MATCH-01B"
        )
    verified = load_verified_match_generation(generation_root, data_root=data_root)
    if verified.generation_id != EXPECTED_GENERATION_ID:
        raise ValueError("La generación MATCH-00 no coincide con la aprobada")
    rebuilt = build_match_detail_inventory(verified)
    if rebuilt != persisted:
        raise ValueError(
            "El inventario persistido no coincide con su generación validada"
        )
    record = select_pilot_record(persisted)
    store = MatchDetailStore(store_root)
    reconciliation = store.reconcile(persisted)
    storage = store.storage_status(min_free_bytes=0)
    dependencies = {
        "seleniumbase_importable": importlib.util.find_spec("seleniumbase") is not None,
        "xvfb_available": shutil.which("Xvfb") is not None,
        "chromium_available": any(
            shutil.which(name) for name in ("chromium", "chromium-browser")
        ),
    }
    status = "PREFLIGHT_READY_PROFILE_UNCHECKED"
    reasons = []
    if reconciliation["blocked"]:
        status = "BLOCKED"
        reasons.append("store_integrity_blocked")
    if reconciliation["active_stop"]:
        status = "BLOCKED"
        reasons.append("active_stop_requires_explicit_resolution")
    if not storage["sufficient"]:
        status = "BLOCKED"
        reasons.append("store_not_writable")
    missing_dependencies = [
        name for name, available in dependencies.items() if not available
    ]
    if missing_dependencies:
        status = "BLOCKED"
        reasons.extend(f"missing_{name}" for name in missing_dependencies)
    report = {
        "schema_version": "football_data_hub.match_detail_pilot_preflight.v1",
        "mode": "offline_preflight",
        "http_enabled": False,
        "browser_started": False,
        "status": status,
        "reasons": reasons,
        "inventory": {
            "inventory_id": persisted["inventory_id"],
            "record_count": len(persisted["matches"]),
            "inventory_sha256": inventory_hash,
            "manifest_sha256": manifest_hash,
            "source_generation_id": verified.generation_id,
            "source_generation_manifest_sha256": verified.manifest_sha256,
            "source_manifest_reference": manifest.get("source_generation"),
        },
        "pilot": {
            "internal_id": record["internal_id"],
            "source_match_id": record["source_match_id"],
            "group": record["group"],
            "season": record["season"],
            "matchday": record["matchday"],
            "home_team_id": record["home_team_id"],
            "away_team_id": record["away_team_id"],
            "reference_result": record["reference_result"],
            "source_match_url": record["source_match_url"],
        },
        "store": {
            "verified_captures": len(reconciliation["verified_by_internal_id"]),
            "active_stop": reconciliation["active_stop"],
            "integrity_blocked": reconciliation["integrity_blocked"],
            "invalid_snapshots": reconciliation["invalid_snapshots"],
            "invalid_discovery_artifacts": reconciliation.get(
                "invalid_discovery_artifacts", []
            ),
            "diagnostics": reconciliation["diagnostics"],
            "storage": storage,
        },
        "runtime_dependencies": dependencies,
        "profile": {
            "checked": False,
            "reason": "No se inspecciona ningún perfil durante el preflight offline; BrowserSessionManager comprobará el lock justo antes de iniciar Chromium.",
            "real_run_requires_explicit_profile_path": True,
            "real_run_requires_user_confirmation_that_PLAYER_is_idle": True,
        },
        "real_execution_eligible": False,
        "guarantees": {
            "one_match_only": True,
            "one_navigation_only": True,
            "automatic_retries": False,
            "promotion_enabled": False,
            "discovery_artifacts_are_not_valid_captures": True,
        },
    }
    return report, persisted


def _parser() -> argparse.ArgumentParser:
    home_data = Path.home() / "FootballDataHub-data"
    defaults = home_data / "matches/details/inventories" / EXPECTED_INVENTORY_ID
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=home_data)
    parser.add_argument(
        "--generation-root",
        type=Path,
        default=home_data / "matches/generations" / EXPECTED_GENERATION_ID,
    )
    parser.add_argument("--inventory-dir", type=Path, default=defaults)
    parser.add_argument(
        "--store-root", type=Path, default=home_data / "matches/details"
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        help="Perfil autorizado y exclusivo; requerido en modo real",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preflight predeterminado sin HTTP, navegador ni escrituras",
    )
    parser.add_argument(
        "--confirm-real-acquisition",
        action="store_true",
        help="Autoriza una única navegación real al partido 272582",
    )
    parser.add_argument(
        "--confirm-player-browser-idle",
        action="store_true",
        help="Confirma que PLAYER-01C2 ya liberó el navegador/perfil; el CLI no inspecciona esos procesos",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.dry_run and args.confirm_real_acquisition:
        parser.error("--dry-run y --confirm-real-acquisition son incompatibles")
    try:
        report, inventory = build_pilot_preflight(
            inventory_dir=args.inventory_dir,
            generation_root=args.generation_root,
            data_root=args.data_root,
            store_root=args.store_root,
        )
    except Exception as exc:
        print(
            json.dumps(
                {"status": "BLOCKED", "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    real_requested = args.confirm_real_acquisition
    if not real_requested:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["status"] == "PREFLIGHT_READY_PROFILE_UNCHECKED" else 2
    if not args.confirm_player_browser_idle:
        parser.error(
            "El modo real requiere --confirm-player-browser-idle; no se inspecciona PLAYER-01C2"
        )
    if args.profile_dir is None:
        parser.error("El modo real requiere --profile-dir explícito")
    if args.profile_dir == Path(".") or args.profile_dir.expanduser().absolute() in {
        Path("/"),
        Path.home().resolve(),
    }:
        parser.error(
            "--profile-dir debe ser un directorio de perfil dedicado, no vacío ni raíz"
        )
    profile_dir = args.profile_dir.expanduser().absolute()
    if profile_dir.is_symlink() or not profile_dir.is_dir():
        parser.error(
            "--profile-dir debe ser un perfil autorizado ya existente y sin symlink"
        )
    if report["status"] != "PREFLIGHT_READY_PROFILE_UNCHECKED":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    store = MatchDetailStore(args.store_root)
    config = BrowserRuntimeConfig(
        profile_dir=profile_dir,
        backend="seleniumbase-pure-cdp",
        browser="chromium",
        use_xvfb=True,
    )
    try:
        # Hold the same filesystem lock from the final checkpoint check through
        # the single network navigation, preventing another MATCH process from
        # racing this pilot. BrowserSessionManager acquires the selected profile
        # lock before it spawns Chromium.
        with store.exclusive_lock():
            reconciliation = store.reconcile(inventory)
            if reconciliation["blocked"] or reconciliation["active_stop"]:
                raise RuntimeError("El almacén quedó bloqueado tras el preflight")
            with BrowserSessionManager(config) as session:
                report["real_execution_eligible"] = True
                report["profile"]["checked"] = True
                report["profile"][
                    "process_and_lock_checked_by_browser_session_manager"
                ] = True
                result = run_match_discovery_pilot(
                    inventory=inventory,
                    access=BDFutbolAccess(session),
                    store=store,
                )
        print(
            json.dumps(
                {"preflight": report, "pilot_result": asdict(result)},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if result.status == "DISCOVERY_REVIEW_REQUIRED" else 3
    except Exception as exc:
        print(
            json.dumps(
                {
                    "preflight": report,
                    "status": "STOPPED",
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
