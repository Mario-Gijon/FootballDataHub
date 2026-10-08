#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup, Tag


RESOURCE_ORDER = (
    "season_alignment",
    "season_roster",
    "season_stats",
    "season_tracking",
    "season_transfers",
    "season_matches",
    "club_profile",
    "club_stats",
    "club_matches",
    "club_competition_players",
    "club_competition_coaches",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analiza offline una captura team_full de BDFutbol y genera "
            "un inventario compacto de tablas, secciones, selects y enlaces."
        )
    )
    parser.add_argument("--season", required=True)
    parser.add_argument("--team-id", required=True, type=int)
    parser.add_argument(
        "--run-dir",
        help=(
            "Directorio exacto del run team_full. Si se omite, usa el run "
            "más reciente de data/raw/bdfutbol/team_full_<season>_<team_id>."
        ),
    )
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=4,
        help="Filas de muestra por tabla. Default: 4.",
    )
    parser.add_argument(
        "--max-links",
        type=int,
        default=30,
        help="Máximo de enlaces internos de ejemplo por recurso. Default: 30.",
    )
    parser.add_argument(
        "--output",
        help=(
            "Ruta del JSON de salida. Default: <run>/analysis/team_full_audit.json"
        ),
    )
    return parser.parse_args(argv)


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def _clean(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.replace("\xa0", " ").split())


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def resolve_run_dir(
    *,
    project_root: Path,
    season: str,
    team_id: int,
    run_dir: str | None,
) -> Path:
    if run_dir:
        candidate = Path(run_dir)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        if not candidate.exists():
            raise FileNotFoundError(
                f"No existe el run solicitado: {candidate}"
            )
        return candidate.resolve()

    base = (
        project_root
        / "data"
        / "raw"
        / "bdfutbol"
        / f"team_full_{season}_{team_id}"
    )
    if not base.exists():
        raise FileNotFoundError(
            f"No existe el recurso full-team: {base}"
        )

    runs = sorted(
        path
        for path in base.iterdir()
        if path.is_dir()
    )
    if not runs:
        raise FileNotFoundError(
            f"No hay runs dentro de: {base}"
        )
    return runs[-1].resolve()


def _resource_attempt_dir(resource_dir: Path) -> Path | None:
    """Prefer the last VALID attempt; otherwise the newest attempt."""

    attempts = sorted(
        path
        for path in resource_dir.glob("attempt_*")
        if path.is_dir()
    )
    if not attempts:
        return None

    valid: list[Path] = []
    for attempt in attempts:
        metadata = _load_json(attempt / "metadata.json", {})
        if metadata.get("status") == "VALID":
            valid.append(attempt)

    return valid[-1] if valid else attempts[-1]


def _headings(soup: BeautifulSoup) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for tag in soup.find_all(re.compile(r"^h[1-6]$")):
        if not isinstance(tag, Tag):
            continue
        text = _clean(tag.get_text(" ", strip=True))
        if text:
            result.append(
                {
                    "tag": tag.name,
                    "text": text,
                }
            )
    return result


def _forms(soup: BeautifulSoup) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for index, form in enumerate(soup.find_all("form")):
        if not isinstance(form, Tag):
            continue

        controls: list[dict[str, Any]] = []
        for control in form.find_all(["input", "select", "button"]):
            if not isinstance(control, Tag):
                continue

            item: dict[str, Any] = {
                "tag": control.name,
                "name": control.get("name"),
                "id": control.get("id"),
            }

            if control.name == "input":
                item["type"] = control.get("type")
                item["value"] = control.get("value")
            elif control.name == "select":
                item["options"] = [
                    {
                        "text": _clean(option.get_text(" ", strip=True)),
                        "value": option.get("value"),
                        "selected": option.has_attr("selected"),
                    }
                    for option in control.find_all("option")
                    if isinstance(option, Tag)
                ]
            elif control.name == "button":
                item["text"] = _clean(
                    control.get_text(" ", strip=True)
                )

            controls.append(item)

        result.append(
            {
                "index": index,
                "action": form.get("action"),
                "method": (form.get("method") or "get").lower(),
                "controls": controls,
            }
        )

    return result


def _canonical_url(soup: BeautifulSoup) -> str | None:
    tag = soup.select_one('link[rel="canonical"][href]')
    if not isinstance(tag, Tag):
        return None
    href = tag.get("href")
    return href if isinstance(href, str) else None


def _table_rows_from_artifact(
    table: dict[str, Any],
) -> list[list[str]]:
    rows: list[list[str]] = []

    for row in table.get("rows") or []:
        if isinstance(row, dict):
            cells = row.get("cells") or []
        elif isinstance(row, list):
            cells = row
        else:
            cells = []

        texts: list[str] = []
        for cell in cells:
            if isinstance(cell, dict):
                texts.append(_clean(str(cell.get("text") or "")))
            else:
                texts.append(_clean(str(cell)))
        rows.append(texts)

    return rows


def _infer_headers(
    table: dict[str, Any],
    rows: list[list[str]],
) -> list[str]:
    raw_rows = table.get("rows") or []

    for raw_row, text_row in zip(raw_rows, rows):
        if not isinstance(raw_row, dict):
            continue
        cells = raw_row.get("cells") or []
        tags = [
            str(cell.get("tag") or "").lower()
            for cell in cells
            if isinstance(cell, dict)
        ]
        if tags and "th" in tags:
            return text_row

    # Some BDFutbol tables use TD even for visual headers.
    if rows:
        candidate = rows[0]
        nonempty = [value for value in candidate if value]
        if nonempty and any(
            token.casefold() in {
                "#",
                "apodo",
                "apodo y nombre",
                "pos",
                "edad",
                "pj",
                "pt",
                "pc",
                "ps",
                "c",
                "min",
                "ta",
                "tr",
                "g",
                "fecha",
                "local",
                "visitante",
                "estadio",
                "temporada",
                "competición",
                "equipo",
                "equipo origen",
                "equipo destino",
            }
            for token in nonempty
        ):
            return candidate

    return []


def _table_inventory(
    tables: list[dict[str, Any]],
    sample_rows: int,
) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []

    for table in tables:
        rows = _table_rows_from_artifact(table)
        headers = _infer_headers(table, rows)

        nonempty_rows = [
            row
            for row in rows
            if any(cell for cell in row)
        ]

        inventory.append(
            {
                "index": table.get(
                    "index",
                    table.get("table_index"),
                ),
                "id": table.get("id"),
                "class_name": table.get("class_name"),
                "row_count": len(rows),
                "nonempty_row_count": len(nonempty_rows),
                "max_columns": max(
                    (len(row) for row in rows),
                    default=0,
                ),
                "headers": headers,
                "sample_rows": nonempty_rows[:sample_rows],
            }
        )

    return inventory


def _select_inventory(
    selects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    for select in selects:
        if not isinstance(select, dict):
            continue

        options = []
        for option in select.get("options") or []:
            if not isinstance(option, dict):
                continue
            options.append(
                {
                    "text": _clean(str(option.get("text") or "")),
                    "value": option.get("value"),
                    "selected": bool(option.get("selected")),
                }
            )

        result.append(
            {
                "index": select.get("index"),
                "id": select.get("id"),
                "name": select.get("name"),
                "value": select.get("value"),
                "onchange": select.get("onchange"),
                "options": options,
            }
        )

    return result


def _link_signature(url: str) -> str:
    parsed = urlsplit(url)
    keys = sorted(
        {
            key
            for key, _ in parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )
        }
    )
    if keys:
        return f"{parsed.path}?{'&'.join(keys)}"
    return parsed.path


def _links_inventory(
    links: list[str],
    *,
    max_links: int,
) -> dict[str, Any]:
    unique = sorted(
        {
            link
            for link in links
            if isinstance(link, str)
            and link.strip()
        }
    )

    signatures = Counter(
        _link_signature(link)
        for link in unique
    )

    return {
        "unique_count": len(unique),
        "examples": unique[:max_links],
        "signatures": [
            {
                "signature": signature,
                "count": count,
            }
            for signature, count
            in signatures.most_common()
        ],
    }


KNOWN_FIELD_PATTERNS: tuple[
    tuple[str, tuple[str, ...]],
    ...
] = (
    (
        "identity",
        (
            "nombre completo",
            "fundación",
            "localidad",
            "país",
            "estadio",
            "aforo",
        ),
    ),
    (
        "roster_personal",
        (
            "fecha",
            "lugar de nacimiento",
            "provincia",
            "pos",
        ),
    ),
    (
        "player_stats",
        (
            "pj",
            "pt",
            "pc",
            "ps",
            "px",
            "c",
            "min",
            "ta",
            "tr",
            "g",
            "pg",
            "pe",
            "pp",
        ),
    ),
    (
        "tracking",
        (
            "completo",
            "titular",
            "suplente",
            "convocado",
            "amarillas",
            "rojas",
            "gol",
        ),
    ),
    (
        "transfers",
        (
            "altas",
            "bajas",
            "equipo origen",
            "equipo destino",
        ),
    ),
    (
        "fixtures",
        (
            "jornada",
            "local",
            "visitante",
            "estadio",
            "progreso liga",
            "récords",
        ),
    ),
    (
        "history",
        (
            "temporada",
            "competición",
            "títulos",
            "nombres",
            "estadios",
        ),
    ),
)


def _detect_field_hints(text: str) -> dict[str, list[str]]:
    folded = text.casefold()
    result: dict[str, list[str]] = {}

    for category, tokens in KNOWN_FIELD_PATTERNS:
        found = [
            token
            for token in tokens
            if token.casefold() in folded
        ]
        if found:
            result[category] = found

    return result


def analyze_resource(
    resource_dir: Path,
    *,
    run_dir: Path,
    sample_rows: int,
    max_links: int,
) -> dict[str, Any]:
    attempt_dir = _resource_attempt_dir(resource_dir)
    if attempt_dir is None:
        return {
            "resource": resource_dir.name,
            "status": "MISSING_ATTEMPT",
        }

    metadata = _load_json(
        attempt_dir / "metadata.json",
        {},
    )
    assessment = _load_json(
        attempt_dir / "assessment.json",
        {},
    )
    tables = _load_json(
        attempt_dir / "tables.json",
        [],
    )
    selects = _load_json(
        attempt_dir / "selects.json",
        [],
    )
    same_team_links = _load_json(
        attempt_dir / "same_team_links.json",
        [],
    )

    html_path = attempt_dir / "page.html"
    html = (
        html_path.read_text(encoding="utf-8")
        if html_path.exists()
        else ""
    )
    soup = BeautifulSoup(html, "lxml")
    body_text = _clean(
        soup.get_text(" ", strip=True)
    )

    title = ""
    if soup.title:
        title = _clean(soup.title.get_text(" ", strip=True))

    forms = _forms(soup)

    tracking_modes = []
    tracking_modes_path = attempt_dir / "tracking_modes.json"
    if tracking_modes_path.exists():
        tracking_modes = _load_json(
            tracking_modes_path,
            [],
        )

    return {
        "resource": resource_dir.name,
        "status": metadata.get("status"),
        "attempt_directory": _relative(
            attempt_dir,
            run_dir,
        ),
        "requested_url": metadata.get("requested_url"),
        "final_url": metadata.get("final_url"),
        "http_status_diagnostic": metadata.get(
            "http_status_diagnostic"
        ),
        "canonical_url": _canonical_url(soup),
        "title": title,
        "headings": _headings(soup),
        "body_text_chars": len(body_text),
        "field_hints": _detect_field_hints(body_text),
        "tables": _table_inventory(
            tables,
            sample_rows,
        ),
        "selects": _select_inventory(selects),
        "forms": forms,
        "same_team_links": _links_inventory(
            same_team_links,
            max_links=max_links,
        ),
        "tracking_modes": tracking_modes,
        "assessment": {
            "accessible": assessment.get("accessible"),
            "challenge_visible": assessment.get(
                "challenge_visible"
            ),
            "link_count": assessment.get("link_count"),
            "table_count": assessment.get("table_count"),
            "image_count": assessment.get("image_count"),
        },
    }


def build_master_inventory(
    resources: list[dict[str, Any]],
) -> dict[str, Any]:
    table_headers: Counter[str] = Counter()
    headings: Counter[str] = Counter()
    field_hints: dict[str, set[str]] = {}
    select_options: dict[str, set[str]] = {}

    for resource in resources:
        for heading in resource.get("headings") or []:
            text = heading.get("text")
            if text:
                headings[str(text)] += 1

        for table in resource.get("tables") or []:
            for header in table.get("headers") or []:
                header = _clean(str(header))
                if header:
                    table_headers[header] += 1

        for category, tokens in (
            resource.get("field_hints") or {}
        ).items():
            field_hints.setdefault(
                str(category),
                set(),
            ).update(str(token) for token in tokens)

        for select in resource.get("selects") or []:
            key = (
                str(select.get("name"))
                if select.get("name")
                else f"select_{select.get('index')}"
            )
            for option in select.get("options") or []:
                text = _clean(str(option.get("text") or ""))
                if text:
                    select_options.setdefault(
                        key,
                        set(),
                    ).add(text)

    return {
        "resource_count": len(resources),
        "valid_resources": sum(
            resource.get("status") == "VALID"
            for resource in resources
        ),
        "unique_headings": [
            {
                "text": text,
                "resource_count": count,
            }
            for text, count
            in headings.most_common()
        ],
        "unique_table_headers": [
            {
                "header": header,
                "resource_count": count,
            }
            for header, count
            in table_headers.most_common()
        ],
        "field_hints": {
            category: sorted(tokens)
            for category, tokens
            in sorted(field_hints.items())
        },
        "select_options": {
            key: sorted(values)
            for key, values
            in sorted(select_options.items())
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.sample_rows < 1:
        print("--sample-rows debe ser >= 1")
        return 2
    if args.max_links < 1:
        print("--max-links debe ser >= 1")
        return 2

    project_root = Path(__file__).resolve().parents[1]

    try:
        run_dir = resolve_run_dir(
            project_root=project_root,
            season=args.season,
            team_id=args.team_id,
            run_dir=args.run_dir,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return 2

    summary = _load_json(
        run_dir / "summary.json",
        {},
    )

    resource_names = [
        name
        for name in RESOURCE_ORDER
        if (run_dir / name).exists()
    ]

    # Preserve any newly discovered resource directory that was not yet known
    # when this analyzer was written.
    extras = sorted(
        path.name
        for path in run_dir.iterdir()
        if path.is_dir()
        and path.name not in resource_names
        and path.name != "analysis"
    )
    resource_names.extend(extras)

    resources = [
        analyze_resource(
            run_dir / name,
            run_dir=run_dir,
            sample_rows=args.sample_rows,
            max_links=args.max_links,
        )
        for name in resource_names
    ]

    audit = {
        "analysis_version": 1,
        "season": args.season,
        "team_id": args.team_id,
        "source_run": _relative(
            run_dir,
            project_root,
        ),
        "source_summary": summary,
        "resources": resources,
        "master_inventory": build_master_inventory(
            resources
        ),
    }

    output_path = (
        Path(args.output)
        if args.output
        else run_dir / "analysis" / "team_full_audit.json"
    )
    if not output_path.is_absolute():
        output_path = project_root / output_path
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    output_path.write_text(
        json.dumps(
            audit,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("=== BDFUTBOL TEAM FULL OFFLINE AUDIT ===")
    print(f"Run:       {_relative(run_dir, project_root)}")
    print(f"Recursos:  {len(resources)}")
    print(
        f"Válidos:   "
        f"{audit['master_inventory']['valid_resources']}"
    )

    print("\n=== RECURSOS ===")
    for resource in resources:
        table_count = len(resource.get("tables") or [])
        select_count = len(resource.get("selects") or [])
        heading_count = len(resource.get("headings") or [])
        print(
            f"{resource['resource']:<28} "
            f"{str(resource.get('status')):<8} "
            f"tables={table_count:<3} "
            f"selects={select_count:<2} "
            f"headings={heading_count:<2}"
        )

    print("\n=== CAMPOS DETECTADOS ===")
    for category, tokens in (
        audit["master_inventory"]["field_hints"].items()
    ):
        print(
            f"{category:<18} "
            + ", ".join(tokens)
        )

    print(f"\nInforme: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
