"""Analyze a saved match-detail HTML file without opening a browser or network."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .discovery import discover_html_structure


def write_report_immutable(path: Path, report: dict[str, Any]) -> Path:
    """Create a new report file only; never overwrite an existing target."""

    target = path.expanduser().absolute()
    current = target.parent
    while current != current.parent:
        if current.is_symlink():
            raise ValueError("La ruta de salida no puede contener symlinks")
        current = current.parent
    if target.is_symlink() or not target.parent.is_dir():
        raise ValueError(
            "El destino debe tener un directorio padre existente y no ser symlink"
        )
    content = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            target.unlink()
        except OSError:
            pass
        raise
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "html", type=Path, help="HTML guardado previamente; no se modifica"
    )
    parser.add_argument(
        "--output", type=Path, help="Nuevo JSON de salida; falla si ya existe"
    )
    args = parser.parse_args(argv)
    raw = args.html.expanduser().read_bytes()
    report = discover_html_structure(raw)
    if args.output:
        if args.output.expanduser().absolute() == args.html.expanduser().absolute():
            parser.error("El JSON de salida no puede sobrescribir el HTML de entrada")
        write_report_immutable(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
