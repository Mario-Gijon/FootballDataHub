"""Read-only CLI for planning a sample of match-detail pages."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .sampling_plan import MatchSamplePlanError, build_offline_sample_plan


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _write_report_immutable(path: Path, report: dict[str, Any]) -> Path:
    target = path.expanduser().absolute()
    current = target.parent
    while current != current.parent:
        if current.is_symlink():
            raise MatchSamplePlanError(f"La ruta del informe contiene symlink: {current}")
        current = current.parent
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        raise MatchSamplePlanError(f"No se sobrescribe un informe existente: {target}")
    content = _json_bytes(report)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError as exc:
        raise MatchSamplePlanError(
            f"No se sobrescribe un informe existente: {target}"
        ) from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return target


def main(argv: list[str] | None = None) -> int:
    home_data = Path.home() / "FootballDataHub-data"
    default_inventory = (
        home_data
        / "matches/details/inventories/match-detail-inventory-8cf339654c80c0ef"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root", type=Path, default=home_data, help="Raíz local de datos verificados."
    )
    parser.add_argument(
        "--generation-root",
        type=Path,
        default=home_data / "matches/generations/match-00-4ad1d610507e425d",
    )
    parser.add_argument("--inventory-dir", type=Path, default=default_inventory)
    parser.add_argument("--store-root", type=Path, default=home_data / "matches/details")
    parser.add_argument(
        "--write-report",
        type=Path,
        help="Guarda explícitamente el informe en una ruta nueva e inmutable.",
    )
    args = parser.parse_args(argv)
    try:
        report = build_offline_sample_plan(
            generation_root=args.generation_root,
            inventory_dir=args.inventory_dir,
            data_root=args.data_root,
            store_root=args.store_root,
        )
        if args.write_report:
            output = args.write_report.expanduser().absolute().resolve(strict=False)
            for protected in (args.data_root, args.store_root):
                protected_root = protected.expanduser().resolve(strict=False)
                if output == protected_root or protected_root in output.parents:
                    raise MatchSamplePlanError(
                        "El informe debe guardarse fuera de data_root y store_root"
                    )
            report["report_written_to"] = str(
                _write_report_immutable(args.write_report, report)
            )
    except (MatchSamplePlanError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "football_data_hub.match_detail_sampling_plan_error.v1",
                    "status": "BLOCKED",
                    "http_enabled": False,
                    "browser_started": False,
                    "navigation_enabled": False,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PLAN_ONLY_NOT_AUTHORIZED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
