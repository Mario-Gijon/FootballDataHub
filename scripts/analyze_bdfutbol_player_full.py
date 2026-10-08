#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag


RESOURCE_ORDER = (
    "player_profile",
    "player_stats",
    "player_matches",
    "player_profile_manager",
    "player_stats_manager",
    "player_matches_manager",
)

_NAV_CLASS_TOKEN = "fons-blau-2"
_SEMANTIC_HEADERS = {
    "#",
    "apodo",
    "apodo y nombre",
    "nombre",
    "fecha",
    "edad",
    "ciudad",
    "lugar de nacimiento",
    "provincia",
    "país",
    "nacionalidad",
    "int",
    "pos",
    "posición",
    "demarcación",
    "altura",
    "peso",
    "temporada",
    "equipo",
    "competición",
    "partido",
    "rival",
    "resultado",
    "tipo",
    "local",
    "visitante",
    "estadio",
    "pj",
    "pt",
    "pc",
    "pi",
    "ps",
    "px",
    "c",
    "min",
    "ta",
    "tr",
    "g",
    "ge",
    "pg",
    "pe",
    "pp",
    "p%",
    "%pg",
    "%pe",
    "%pp",
    "gf",
    "gc",
    "tc",
    "g/p",
    "pmg",
    "minutos/g",
}

_ENTITY_PATTERNS = (
    ("player", re.compile(r"^/es/j/j(?P<id>\d+)\.html$")),
    ("player_matches", re.compile(r"^/es/p/j(?P<id>\d+)\.html$")),
    ("team", re.compile(r"^/es/e/e(?P<id>\d+)\.html$")),
    ("coach", re.compile(r"^/es/l/l(?P<id>\d+)\.html$")),
    ("stadium", re.compile(r"^/es/s/(?P<id>\d+)\.html$")),
)

_HINTS = {
    "identity": (
        "nombre completo",
        "fecha de nacimiento",
        "lugar de nacimiento",
        "provincia",
        "ciudad",
        "país",
        "nacionalidad",
        "demarcación",
        "posición",
        "altura",
        "peso",
        "internacional",
    ),
    "career": (
        "temporada",
        "equipo",
        "competición",
        "trayectoria",
        "debut",
    ),
    "stats": (
        "pj",
        "pt",
        "pc",
        "pi",
        "ps",
        "px",
        "min",
        "ta",
        "tr",
        "g",
        "ge",
        "pg",
        "pe",
        "pp",
        "p%",
        "minutos/g",
        "g/p",
    ),
    "matches": (
        "partido",
        "rival",
        "resultado",
        "local",
        "visitante",
        "estadio",
        "ganados",
        "empatados",
        "perdidos",
    ),
    "media": (
        "fotos",
        "foto",
        "imagen",
    ),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audita offline un player_full de BDFutbol antes de diseñar "
            "el parser normalizado."
        )
    )
    parser.add_argument("--player-id", required=True, type=int)
    parser.add_argument(
        "--run",
        help=(
            "Run exacto. Si se omite usa el último directorio de "
            "data/raw/bdfutbol/player_full_<id>/."
        ),
    )
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=8,
        help="Filas de muestra por tabla semántica. Default: 8.",
    )
    parser.add_argument(
        "--output",
        help=(
            "Ruta JSON de salida. Default: "
            "<run>/analysis/player_full_audit.json"
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


def _resolve_run(
    *,
    project_root: Path,
    player_id: int,
    requested: str | None,
) -> Path:
    if requested:
        path = Path(requested)
        if not path.is_absolute():
            path = project_root / path
        if not path.exists():
            raise FileNotFoundError(path)
        return path.resolve()

    base = (
        project_root
        / "data"
        / "raw"
        / "bdfutbol"
        / f"player_full_{player_id}"
    )
    if not base.exists():
        raise FileNotFoundError(base)

    runs = sorted(
        path
        for path in base.iterdir()
        if path.is_dir() and path.name != "analysis"
    )
    if not runs:
        raise FileNotFoundError(f"No hay runs dentro de {base}")
    return runs[-1].resolve()


def _attempt_dirs(resource_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in resource_dir.glob("attempt_*")
        if path.is_dir()
    )


def _select_attempt(resource_dir: Path) -> Path | None:
    attempts = _attempt_dirs(resource_dir)
    if not attempts:
        return None

    valid = []
    for attempt in attempts:
        meta = _load_json(attempt / "metadata.json", {})
        if meta.get("status") == "VALID":
            valid.append(attempt)

    if valid:
        return valid[-1]
    return attempts[-1]


def _headings(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    result: list[dict[str, str]] = []
    for node in soup.find_all(re.compile(r"^h[1-6]$")):
        if not isinstance(node, Tag):
            continue
        text = " ".join(node.get_text(" ", strip=True).split())
        if text:
            result.append({"tag": node.name, "text": text})
    return result


def _body_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    if soup.body:
        return " ".join(soup.body.get_text(" ", strip=True).split())
    return " ".join(soup.get_text(" ", strip=True).split())


def _field_hints(text: str) -> dict[str, list[str]]:
    folded = text.casefold()
    result: dict[str, list[str]] = {}
    for category, terms in _HINTS.items():
        found = [term for term in terms if term.casefold() in folded]
        if found:
            result[category] = found
    return result


def _normalize_header(value: object) -> str:
    return " ".join(str(value or "").split())


def _is_semantic_table(table: dict[str, Any]) -> bool:
    class_name = str(table.get("class_name") or "").casefold()
    if _NAV_CLASS_TOKEN in class_name:
        return False

    headers = [
        _normalize_header(value)
        for value in table.get("headers") or []
    ]
    folded_headers = {header.casefold() for header in headers if header}

    if folded_headers & _SEMANTIC_HEADERS:
        return True

    table_id = str(table.get("id") or "").casefold()
    if table_id and table_id not in {"classific"}:
        return True

    row_count = int(table.get("row_count") or 0)
    max_columns = int(table.get("max_columns") or 0)
    return row_count >= 2 and max_columns >= 3


def _trim_table(
    table: dict[str, Any],
    *,
    sample_rows: int,
) -> dict[str, Any]:
    return {
        "index": table.get("index"),
        "id": table.get("id"),
        "class_name": table.get("class_name"),
        "row_count": table.get("row_count"),
        "nonempty_row_count": table.get("nonempty_row_count"),
        "max_columns": table.get("max_columns"),
        "headers": table.get("headers") or [],
        "sample_rows": (table.get("sample_rows") or [])[:sample_rows],
    }



def _cell_metadata(cell: Tag, *, base_url: str) -> dict[str, Any]:
    text = " ".join(cell.get_text(" ", strip=True).split())
    links: list[dict[str, str]] = []
    for anchor in cell.find_all("a", href=True):
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        links.append(
            {
                "text": " ".join(
                    anchor.get_text(" ", strip=True).split()
                ),
                "href": urljoin(base_url, href),
            }
        )

    data_attrs = {
        key: value
        for key, value in cell.attrs.items()
        if isinstance(key, str) and key.startswith("data-")
    }
    classes = cell.get("class")
    class_name = (
        " ".join(classes)
        if isinstance(classes, list)
        else str(classes or "")
    )

    return {
        "tag": cell.name,
        "text": text,
        "title": cell.get("title"),
        "abbr": cell.get("abbr"),
        "aria_label": cell.get("aria-label"),
        "scope": cell.get("scope"),
        "class_name": class_name or None,
        "data": data_attrs,
        "links": links,
    }


def _extract_dom_tables(
    html: str,
    *,
    base_url: str,
    sample_rows: int,
) -> list[dict[str, Any]]:
    """Extract semantic table structure from the saved rendered DOM."""
    soup = BeautifulSoup(html, "lxml")
    result: list[dict[str, Any]] = []

    for index, table in enumerate(soup.find_all("table")):
        if not isinstance(table, Tag):
            continue

        classes = table.get("class")
        class_name = (
            " ".join(classes)
            if isinstance(classes, list)
            else str(classes or "")
        )

        rows: list[list[str]] = []
        rows_meta: list[list[dict[str, Any]]] = []
        header_cells: list[dict[str, Any]] = []
        header_row_index: int | None = None

        trs = table.find_all("tr")
        for row_index, tr in enumerate(trs):
            if not isinstance(tr, Tag):
                continue
            cells = tr.find_all(["th", "td"], recursive=False)
            if not cells:
                cells = tr.find_all(["th", "td"])

            meta = [
                _cell_metadata(cell, base_url=base_url)
                for cell in cells
                if isinstance(cell, Tag)
            ]
            texts = [str(cell["text"]) for cell in meta]
            rows.append(texts)
            rows_meta.append(meta)

            if not header_cells:
                th_cells = [
                    cell
                    for cell in cells
                    if isinstance(cell, Tag) and cell.name == "th"
                ]
                if th_cells:
                    header_cells = [
                        _cell_metadata(cell, base_url=base_url)
                        for cell in th_cells
                    ]
                    header_row_index = row_index

        headers = [
            str(cell.get("text") or "")
            for cell in header_cells
        ]

        if not headers and rows:
            first_folded = {
                _normalize_header(value).casefold()
                for value in rows[0]
                if _normalize_header(value)
            }
            if first_folded & _SEMANTIC_HEADERS:
                headers = rows[0]
                header_cells = rows_meta[0]
                header_row_index = 0

        nonempty_pairs = [
            (idx, row, rows_meta[idx])
            for idx, row in enumerate(rows)
            if any(value.strip() for value in row)
        ]
        data_pairs = [
            pair
            for pair in nonempty_pairs
            if pair[0] != header_row_index
        ]

        max_columns = max((len(row) for row in rows), default=0)

        heading = table.find_previous(re.compile(r"^h[1-6]$"))
        nearby_heading = None
        if isinstance(heading, Tag):
            nearby_heading = " ".join(
                heading.get_text(" ", strip=True).split()
            ) or None

        caption = table.find("caption")
        caption_text = None
        if isinstance(caption, Tag):
            caption_text = " ".join(
                caption.get_text(" ", strip=True).split()
            ) or None

        result.append(
            {
                "index": index,
                "id": table.get("id"),
                "class_name": class_name or None,
                "nearby_heading": nearby_heading,
                "caption": caption_text,
                "row_count": len(rows),
                "nonempty_row_count": len(nonempty_pairs),
                "max_columns": max_columns,
                "headers": headers,
                "header_cells": header_cells,
                "sample_rows": [
                    row for _, row, _ in data_pairs[:sample_rows]
                ],
                "sample_rows_meta": [
                    meta for _, _, meta in data_pairs[:sample_rows]
                ],
            }
        )

    return result


_IDENTITY_LABELS = (
    "Nombre completo",
    "Fecha de nacimiento",
    "Lugar de nacimiento",
    "Provincia",
    "Ciudad",
    "País",
    "Nacionalidad",
    "Demarcación",
    "Posición",
    "Altura",
    "Peso",
    "Internacional",
)


def _identity_contexts(html: str) -> list[dict[str, str]]:
    """Keep short DOM contexts around identity labels without guessing values."""
    soup = BeautifulSoup(html, "lxml")
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for label in _IDENTITY_LABELS:
        pattern = re.compile(rf"^\s*{re.escape(label)}\s*:?\s*$", re.I)
        for text_node in soup.find_all(string=pattern):
            parent = text_node.parent
            if not isinstance(parent, Tag):
                continue
            candidate = (
                parent.parent
                if isinstance(parent.parent, Tag)
                else parent
            )
            context = " ".join(
                candidate.get_text(" ", strip=True).split()
            )
            if len(context) > 350:
                context = context[:347] + "..."
            key = (label.casefold(), context)
            if context and key not in seen:
                seen.add(key)
                found.append(
                    {
                        "label": label,
                        "context": context,
                    }
                )

    return found


def _select_key(item: dict[str, Any]) -> str:
    if item.get("id"):
        return f"id:{item['id']}"
    if item.get("name"):
        return f"name:{item['name']}"
    return f"index:{item.get('index')}"


def _compare_resource_pair(
    canonical: dict[str, Any] | None,
    manager: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if canonical is None or manager is None:
        return None

    canonical_tables = {
        str(table.get("id") or f"index:{table.get('index')}"): table
        for table in canonical.get("semantic_tables") or []
    }
    manager_tables = {
        str(table.get("id") or f"index:{table.get('index')}"): table
        for table in manager.get("semantic_tables") or []
    }

    table_differences: list[dict[str, Any]] = []
    for key in sorted(set(canonical_tables) | set(manager_tables)):
        left = canonical_tables.get(key)
        right = manager_tables.get(key)
        if left is None or right is None:
            table_differences.append(
                {
                    "table": key,
                    "canonical_present": left is not None,
                    "manager_present": right is not None,
                }
            )
            continue

        if (
            left.get("row_count") != right.get("row_count")
            or left.get("headers") != right.get("headers")
            or left.get("sample_rows") != right.get("sample_rows")
        ):
            table_differences.append(
                {
                    "table": key,
                    "canonical_row_count": left.get("row_count"),
                    "manager_row_count": right.get("row_count"),
                    "headers_equal": (
                        left.get("headers") == right.get("headers")
                    ),
                    "sample_rows_equal": (
                        left.get("sample_rows")
                        == right.get("sample_rows")
                    ),
                }
            )

    left_selects = {
        _select_key(item): item
        for item in canonical.get("selects") or []
    }
    right_selects = {
        _select_key(item): item
        for item in manager.get("selects") or []
    }

    select_differences: list[dict[str, Any]] = []
    for key in sorted(set(left_selects) | set(right_selects)):
        left = left_selects.get(key)
        right = right_selects.get(key)
        if left is None or right is None:
            select_differences.append(
                {
                    "select": key,
                    "canonical_present": left is not None,
                    "manager_present": right is not None,
                }
            )
            continue

        left_options = (
            left.get("all_options")
            or left.get("sample_options")
            or []
        )
        right_options = (
            right.get("all_options")
            or right.get("sample_options")
            or []
        )
        if left_options != right_options:
            select_differences.append(
                {
                    "select": key,
                    "canonical_option_count": len(left_options),
                    "manager_option_count": len(right_options),
                    "only_canonical": [
                        value
                        for value in left_options
                        if value not in right_options
                    ],
                    "only_manager": [
                        value
                        for value in right_options
                        if value not in left_options
                    ],
                }
            )

    return {
        "canonical_resource": canonical.get("resource"),
        "manager_resource": manager.get("resource"),
        "body_text_chars_delta": (
            int(manager.get("body_text_chars") or 0)
            - int(canonical.get("body_text_chars") or 0)
        ),
        "images_count_delta": (
            int(manager.get("images_count") or 0)
            - int(canonical.get("images_count") or 0)
        ),
        "table_differences": table_differences,
        "select_differences": select_differences,
    }


def _manager_comparison(
    resources: list[dict[str, Any]],
) -> dict[str, Any]:
    by_name = {
        str(resource.get("resource")): resource
        for resource in resources
    }

    result: dict[str, Any] = {}
    for label, canonical_name, manager_name in (
        ("profile", "player_profile", "player_profile_manager"),
        ("stats", "player_stats", "player_stats_manager"),
        ("matches", "player_matches", "player_matches_manager"),
    ):
        comparison = _compare_resource_pair(
            by_name.get(canonical_name),
            by_name.get(manager_name),
        )
        if comparison is not None:
            result[label] = comparison

    return result

def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)


def _related_entities(
    base_url: str,
    *values: Any,
) -> dict[str, Any]:
    by_type: dict[str, dict[int, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )

    for value in values:
        for candidate in _walk_strings(value):
            if not candidate:
                continue
            if candidate.startswith(("http://", "https://", "/")):
                absolute = urljoin(base_url, candidate)
            else:
                continue

            parsed = urlsplit(absolute)
            if parsed.netloc.casefold() not in {
                "bdfutbol.com",
                "www.bdfutbol.com",
            }:
                continue

            for entity_type, pattern in _ENTITY_PATTERNS:
                match = pattern.fullmatch(parsed.path)
                if not match:
                    continue
                entity_id = int(match.group("id"))
                canonical = f"https://www.bdfutbol.com{parsed.path}"
                by_type[entity_type][entity_id].add(canonical)
                break

    result: dict[str, Any] = {}
    for entity_type, entities in sorted(by_type.items()):
        result[entity_type] = {
            "count": len(entities),
            "ids": sorted(entities),
            "sample_urls": [
                url
                for entity_id in sorted(entities)[:20]
                for url in sorted(entities[entity_id])[:1]
            ],
        }
    return result


def _select_summary(selects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in selects:
        options = item.get("options") or []
        result.append(
            {
                "index": item.get("index"),
                "id": item.get("id"),
                "name": item.get("name"),
                "value": item.get("value"),
                "onchange": item.get("onchange"),
                "option_count": len(options),
                "selected": [
                    option.get("text")
                    for option in options
                    if isinstance(option, dict) and option.get("selected")
                ],
                "sample_options": [
                    option.get("text")
                    for option in options[:20]
                    if isinstance(option, dict)
                ],
                "all_options": [
                    option.get("text")
                    for option in options
                    if isinstance(option, dict)
                ],
                "option_values": [
                    {
                        "text": option.get("text"),
                        "value": option.get("value"),
                        "selected": option.get("selected"),
                    }
                    for option in options
                    if isinstance(option, dict)
                ],
            }
        )
    return result


def analyze_resource(
    resource_dir: Path,
    *,
    sample_rows: int,
) -> dict[str, Any]:
    attempt = _select_attempt(resource_dir)
    if attempt is None:
        return {
            "resource": resource_dir.name,
            "status": "MISSING",
            "attempt_directory": None,
        }

    metadata = _load_json(attempt / "metadata.json", {})
    assessment = _load_json(attempt / "assessment.json", {})
    tables = _load_json(attempt / "tables.json", [])
    selects = _load_json(attempt / "selects.json", [])
    forms = _load_json(attempt / "forms.json", [])
    links = _load_json(attempt / "links.json", [])
    images = _load_json(attempt / "images.json", [])
    same_player_links = _load_json(
        attempt / "same_player_links.json",
        [],
    )
    photo_gallery = _load_json(
        attempt / "photo_gallery.json",
        None,
    )

    html_path = attempt / "page.html"
    try:
        html = html_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        html = ""

    headings = _headings(html) if html else []
    body = _body_text(html) if html else ""

    base_url = str(
        metadata.get("final_url")
        or metadata.get("requested_url")
        or "https://www.bdfutbol.com/"
    )
    dom_tables = _extract_dom_tables(
        html,
        base_url=base_url,
        sample_rows=sample_rows,
    )
    semantic_tables = [
        table
        for table in dom_tables
        if _is_semantic_table(table)
    ]

    gallery_analysis: dict[str, Any] | None = None
    gallery_dir = attempt / "photo_gallery"
    if gallery_dir.exists():
        gallery_images = _load_json(gallery_dir / "images.json", [])
        gallery_links = _load_json(gallery_dir / "links.json", [])
        gallery_tables = _load_json(gallery_dir / "tables.json", [])
        gallery_analysis = {
            "metadata": _load_json(gallery_dir / "metadata.json", {}),
            "images_count": len(gallery_images)
            if isinstance(gallery_images, list)
            else None,
            "links_count": len(gallery_links)
            if isinstance(gallery_links, list)
            else None,
            "tables_count": len(gallery_tables)
            if isinstance(gallery_tables, list)
            else None,
            "images": gallery_images,
        }

    return {
        "resource": resource_dir.name,
        "status": metadata.get("status"),
        "provenance": metadata.get("provenance"),
        "attempt_directory": str(
            attempt.relative_to(resource_dir.parent)
        ),
        "requested_url": metadata.get("requested_url"),
        "final_url": metadata.get("final_url"),
        "http_status_diagnostic": metadata.get(
            "http_status_diagnostic"
        ),
        "title": (
            BeautifulSoup(html, "lxml").title.get_text(" ", strip=True)
            if html and BeautifulSoup(html, "lxml").title
            else None
        ),
        "headings": headings,
        "body_text_chars": len(body),
        "field_hints": _field_hints(body),
        "tables_total": len(dom_tables),
        "semantic_tables": semantic_tables,
        "identity_contexts": _identity_contexts(html),
        "selects": _select_summary(selects)
        if isinstance(selects, list)
        else [],
        "forms": forms if isinstance(forms, list) else [],
        "same_player_links": same_player_links,
        "photo_gallery": photo_gallery,
        "photo_gallery_analysis": gallery_analysis,
        "related_entities": _related_entities(
            base_url,
            links,
            same_player_links,
            forms,
            semantic_tables,
        ),
        "assessment": assessment,
        "images_count": len(images)
        if isinstance(images, list)
        else None,
    }


def _master_inventory(
    resources: list[dict[str, Any]],
) -> dict[str, Any]:
    heading_counter: Counter[str] = Counter()
    header_counter: Counter[str] = Counter()
    hints: dict[str, set[str]] = defaultdict(set)
    same_links: set[str] = set()
    entities: dict[str, set[int]] = defaultdict(set)
    galleries: list[dict[str, Any]] = []

    for resource in resources:
        seen_headings = {
            str(item.get("text"))
            for item in resource.get("headings") or []
            if item.get("text")
        }
        heading_counter.update(seen_headings)

        seen_headers: set[str] = set()
        for table in resource.get("semantic_tables") or []:
            for header in table.get("headers") or []:
                normalized = _normalize_header(header)
                if normalized:
                    seen_headers.add(normalized)
        header_counter.update(seen_headers)

        for category, values in (
            resource.get("field_hints") or {}
        ).items():
            hints[category].update(values)

        for link in resource.get("same_player_links") or []:
            if isinstance(link, str):
                same_links.add(link)

        for entity_type, payload in (
            resource.get("related_entities") or {}
        ).items():
            for entity_id in payload.get("ids") or []:
                entities[entity_type].add(int(entity_id))

        gallery = resource.get("photo_gallery")
        if isinstance(gallery, dict):
            galleries.append(
                {
                    "resource": resource.get("resource"),
                    **gallery,
                }
            )

    return {
        "resource_count": len(resources),
        "valid_resources": sum(
            resource.get("status") == "VALID"
            for resource in resources
        ),
        "unique_headings": [
            {"text": text, "resource_count": count}
            for text, count in heading_counter.most_common()
        ],
        "unique_table_headers": [
            {"header": header, "resource_count": count}
            for header, count in header_counter.most_common()
        ],
        "field_hints": {
            category: sorted(values)
            for category, values in sorted(hints.items())
        },
        "same_player_links": sorted(same_links),
        "related_entity_ids": {
            entity_type: sorted(values)
            for entity_type, values in sorted(entities.items())
        },
        "photo_galleries": galleries,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.player_id <= 0:
        print("Error: --player-id debe ser > 0")
        return 2
    if args.sample_rows < 1:
        print("Error: --sample-rows debe ser >= 1")
        return 2

    project_root = Path(__file__).resolve().parents[1]

    try:
        run_dir = _resolve_run(
            project_root=project_root,
            player_id=args.player_id,
            requested=args.run,
        )
    except FileNotFoundError as exc:
        print(f"Error: no existe {exc}")
        return 2

    summary = _load_json(run_dir / "summary.json", {})

    resource_dirs = {
        path.name: path
        for path in run_dir.iterdir()
        if path.is_dir() and path.name != "analysis"
    }

    ordered_names = [
        name for name in RESOURCE_ORDER if name in resource_dirs
    ]
    ordered_names.extend(
        sorted(
            name
            for name in resource_dirs
            if name not in RESOURCE_ORDER
        )
    )

    resources = [
        analyze_resource(
            resource_dirs[name],
            sample_rows=args.sample_rows,
        )
        for name in ordered_names
    ]

    payload = {
        "analysis_version": 1,
        "entity_type": "player",
        "player_id": args.player_id,
        "source_run": run_dir.relative_to(project_root).as_posix(),
        "source_summary": summary,
        "resources": resources,
        "manager_comparison": _manager_comparison(resources),
        "master_inventory": _master_inventory(resources),
    }

    output = (
        Path(args.output)
        if args.output
        else run_dir / "analysis" / "player_full_audit.json"
    )
    if not output.is_absolute():
        output = project_root / output

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    master = payload["master_inventory"]
    print("=== BDFUTBOL PLAYER FULL AUDIT ===")
    print(f"Run:              {payload['source_run']}")
    print(f"Recursos:         {master['resource_count']}")
    print(f"Válidos:          {master['valid_resources']}")
    print(
        f"Links jugador:    {len(master['same_player_links'])}"
    )
    print(
        "Entidades:        "
        + ", ".join(
            f"{key}={len(value)}"
            for key, value
            in master["related_entity_ids"].items()
        )
    )
    if master["photo_galleries"]:
        print(
            "Fotos declaradas: "
            + ", ".join(
                f"{item.get('resource')}="
                f"{item.get('declared_count')}"
                for item in master["photo_galleries"]
            )
        )

    comparison = payload.get("manager_comparison") or {}
    match_cmp = comparison.get("matches") or {}
    select_diffs = match_cmp.get("select_differences") or []
    if select_diffs:
        print(
            "Diferencias manager: "
            f"{len(select_diffs)} select(s) en partidos"
        )

    print(f"Informe:          {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
