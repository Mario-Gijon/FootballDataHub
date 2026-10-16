"""Planificador offline de fichas individuales; nunca inicia una navegación."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .inventory import (
    VerifiedGeneration,
    build_match_detail_inventory,
    load_verified_match_generation,
    write_inventory_immutable,
)
from .store import MatchDetailStore


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def build_offline_plan(
    *,
    generation_root: Path,
    data_root: Path,
    store_root: Path,
    min_free_bytes: int = 0,
    verified_generation: VerifiedGeneration | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    verified = verified_generation or load_verified_match_generation(
        generation_root, data_root=data_root
    )
    inventory = build_match_detail_inventory(verified)
    store = MatchDetailStore(store_root)
    reconciliation = store.reconcile(inventory)
    storage = store.storage_status(min_free_bytes=min_free_bytes)
    matches = inventory["matches"]
    verified_ids = reconciliation["verified_by_internal_id"]
    match_states = []
    pending = [
        record["internal_id"]
        for record in matches
        if record["internal_id"] not in verified_ids
    ]
    for record in matches:
        verified_capture = verified_ids.get(record["internal_id"])
        match_states.append(
            {
                "internal_id": record["internal_id"],
                "source_match_id": record["source_match_id"],
                "group": record["group"],
                "source_match_url": record["source_match_url"],
                "acquisition_status": "verified" if verified_capture else "pending",
                "validation_status": "valid" if verified_capture else "not_acquired",
                "capture_id": verified_capture.get("capture_id")
                if verified_capture
                else None,
                "source_html_sha256": verified_capture.get("source_html_sha256")
                if verified_capture
                else None,
            }
        )
    diagnostics = reconciliation["diagnostics"]
    blocked = (
        reconciliation["blocked"]
        or not storage["sufficient"]
        or any(item.get("stop_acquisition", True) for item in diagnostics)
    )
    report = {
        "mode": "offline_dry_run",
        "http_enabled": False,
        "browser_enabled": False,
        "status": "BLOCKED" if blocked else "READY",
        "inventory_id": inventory["inventory_id"],
        "source_generation_id": verified.generation_id,
        "source_generation_manifest_sha256": verified.manifest_sha256,
        "inventory_sha256": hashlib.sha256(_json_bytes(inventory)).hexdigest(),
        "counts": {
            "eligible": len(matches),
            "verified_snapshots": len(verified_ids),
            "pending": len(pending),
            "invalid_snapshots": len(reconciliation["invalid_snapshots"]),
            "diagnostics": len(diagnostics),
        },
        "pending_internal_ids": pending,
        "match_states": match_states,
        "verified_captures": {
            key: value["capture_id"]
            for key, value in sorted(verified_ids.items())
        },
        "invalid_snapshots": reconciliation["invalid_snapshots"],
        "diagnostics": diagnostics,
        "checkpoint_revision": reconciliation["revision"],
        "storage": storage,
    }
    return report, inventory


def main(argv: list[str] | None = None) -> int:
    import argparse

    default_data_root = Path.home() / "FootballDataHub-data"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--generation-root",
        type=Path,
        default=default_data_root
        / "matches/generations/match-00-4ad1d610507e425d",
    )
    parser.add_argument("--data-root", type=Path, default=default_data_root)
    parser.add_argument(
        "--store-root", type=Path, default=default_data_root / "matches/details"
    )
    parser.add_argument("--min-free-bytes", type=int, default=0)
    parser.add_argument(
        "--write-inventory",
        type=Path,
        help="Escribe un JSON inmutable en esta ruta; sin esta opción no escribe datos.",
    )
    parser.add_argument(
        "--persist-plan",
        action="store_true",
        help="Crea la generación inmutable del plan y su checkpoint offline.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicita el modo predeterminado sin HTTP, navegador ni escrituras.",
    )
    args = parser.parse_args(argv)
    if args.min_free_bytes < 0:
        parser.error("--min-free-bytes no puede ser negativo")
    if args.dry_run and (args.write_inventory or args.persist_plan):
        parser.error("--dry-run no puede combinarse con opciones de escritura")
    report, inventory = build_offline_plan(
        generation_root=args.generation_root.expanduser(),
        data_root=args.data_root.expanduser(),
        store_root=args.store_root.expanduser(),
        min_free_bytes=args.min_free_bytes,
    )
    if args.write_inventory:
        path = write_inventory_immutable(args.write_inventory, inventory)
        report["inventory_written_to"] = str(path)
    if args.persist_plan:
        path = MatchDetailStore(args.store_root.expanduser()).prepare_inventory(inventory)
        report["inventory_generation_path"] = str(path)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
