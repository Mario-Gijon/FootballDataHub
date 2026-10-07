#!/usr/bin/env python3
"""Analiza offline una captura de discovery de BDFutbol.

Este script NO realiza ninguna petición de red. Trabaja exclusivamente con los
artefactos generados por probe_bdfutbol_cdp.py para responder preguntas como:

- ¿Cuántos enlaces únicos hay realmente?
- ¿Qué hosts y familias de rutas aparecen?
- ¿Qué combinaciones path/query utiliza BDFutbol?
- ¿Cuántas imágenes únicas existen?
- ¿Qué tablas contiene la página y de qué tamaño?
- ¿Qué URLs parecen representar entidades reutilizables?

El objetivo es mapear la estructura real de BDFutbol antes de escribir parsers
o un crawler.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


DEFAULT_CAPTURE = "data/raw/discovery/group1_cdp"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analiza offline una captura CDP de BDFutbol."
    )
    parser.add_argument(
        "--capture",
        default=DEFAULT_CAPTURE,
        help=f"Directorio de captura. Default: {DEFAULT_CAPTURE}",
    )
    parser.add_argument(
        "--examples",
        type=int,
        default=5,
        help="Número máximo de ejemplos por patrón. Default: 5",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def normalized_url(url: str) -> str:
    """Normaliza una URL sin destruir IDs ni parámetros significativos."""
    parsed = urlsplit(url)

    # Fragmentos no afectan al recurso HTTP y generan muchos duplicados.
    fragment = ""

    # Ordenar query ayuda a deduplicar URLs equivalentes.
    query_pairs = sorted(parse_qsl(parsed.query, keep_blank_values=True))
    query = urlencode(query_pairs, doseq=True)

    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            query,
            fragment,
        )
    )


def route_family(url: str) -> str:
    parsed = urlsplit(url)
    parts = [part for part in parsed.path.split("/") if part]

    if len(parts) >= 2:
        return "/" + "/".join(parts[:2]) + "/"
    if parts:
        return "/" + parts[0] + "/"
    return "/"


def path_query_signature(url: str) -> str:
    """Agrupa URLs por path + nombres de parámetros, no por sus valores."""
    parsed = urlsplit(url)
    query_keys = sorted({key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)})

    if query_keys:
        return f"{parsed.path}?{'&'.join(query_keys)}"
    return parsed.path


_ID_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "match_query_id",
        re.compile(r"/(?:es|en)/p/p\.php(?:\?.*?\bid=(?P<id>\d+))", re.IGNORECASE),
    ),
    (
        "referee_path_id",
        re.compile(r"/(?:es|en)/r/r(?P<id>\d+)\.html$", re.IGNORECASE),
    ),
    (
        "stadium_path_id",
        re.compile(r"/(?:es|en)/s/(?P<id>\d+)\.html$", re.IGNORECASE),
    ),
    (
        "player_path_id",
        re.compile(r"/(?:es|en)/j/j(?P<id>\d+)\.html$", re.IGNORECASE),
    ),
    (
        "team_path_id",
        re.compile(r"/(?:es|en)/e/e(?P<id>\d+)\.html$", re.IGNORECASE),
    ),
)


def detect_known_id(url: str) -> dict[str, str] | None:
    """Detecta solo patrones que podamos reconocer sintácticamente.

    No asigna significado a rutas desconocidas.
    """
    parsed = urlsplit(url)
    target = parsed.path
    if parsed.query:
        target += "?" + parsed.query

    for kind, pattern in _ID_PATTERNS:
        match = pattern.search(target)
        if match:
            return {"kind": kind, "id": match.group("id")}

    return None


def summarize_tables(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []

    for table in tables:
        rows = table.get("rows") or []
        row_lengths = []

        for row in rows:
            # probe antiguo: row puede ser lista de strings.
            # probe nuevo: row puede ser {"row_index": ..., "cells": [...]}
            if isinstance(row, dict):
                cells = row.get("cells") or []
            else:
                cells = row if isinstance(row, list) else []

            row_lengths.append(len(cells))

        summaries.append(
            {
                "index": table.get("index", table.get("table_index")),
                "id": table.get("id"),
                "class_name": table.get("class_name"),
                "row_count": len(rows),
                "max_columns": max(row_lengths, default=0),
                "min_columns": min(row_lengths, default=0),
            }
        )

    return summaries


def main() -> int:
    args = parse_args()

    project_root = Path(__file__).resolve().parents[1]
    capture_dir = Path(args.capture)
    if not capture_dir.is_absolute():
        capture_dir = project_root / capture_dir

    required = {
        "summary": capture_dir / "summary.json",
        "links": capture_dir / "links.json",
        "images": capture_dir / "images.json",
        "tables": capture_dir / "tables.json",
    }

    missing = [str(path) for path in required.values() if not path.exists()]
    if missing:
        print("[!] Faltan artefactos requeridos:")
        for path in missing:
            print(f"    {path}")
        return 2

    source_summary = load_json(required["summary"])
    links = load_json(required["links"])
    images = load_json(required["images"])
    tables = load_json(required["tables"])

    output_dir = capture_dir / "analysis"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # ENLACES
    # ------------------------------------------------------------------
    raw_link_urls = [
        item.get("href")
        for item in links
        if isinstance(item, dict) and item.get("href")
    ]

    unique_link_urls = sorted(
        {normalized_url(url) for url in raw_link_urls}
    )

    host_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    signature_counts: Counter[str] = Counter()
    signature_examples: dict[str, list[str]] = defaultdict(list)
    known_ids: dict[str, set[str]] = defaultdict(set)
    known_id_examples: dict[str, list[str]] = defaultdict(list)

    for url in unique_link_urls:
        parsed = urlsplit(url)
        host_counts[parsed.netloc] += 1
        family_counts[route_family(url)] += 1

        signature = path_query_signature(url)
        signature_counts[signature] += 1
        if len(signature_examples[signature]) < args.examples:
            signature_examples[signature].append(url)

        detected = detect_known_id(url)
        if detected:
            kind = detected["kind"]
            entity_id = detected["id"]
            known_ids[kind].add(entity_id)
            if len(known_id_examples[kind]) < args.examples:
                known_id_examples[kind].append(url)

    route_patterns = []
    for signature, count in signature_counts.most_common():
        route_patterns.append(
            {
                "signature": signature,
                "unique_url_count": count,
                "examples": signature_examples[signature],
            }
        )

    detected_entity_counts = {
        kind: len(ids)
        for kind, ids in sorted(known_ids.items())
    }

    detected_entities = {
        kind: {
            "count": len(ids),
            "ids": sorted(ids, key=lambda value: int(value)),
            "examples": known_id_examples[kind],
        }
        for kind, ids in sorted(known_ids.items())
    }

    # ------------------------------------------------------------------
    # IMÁGENES
    # ------------------------------------------------------------------
    raw_image_urls = [
        item.get("src")
        for item in images
        if isinstance(item, dict) and item.get("src")
    ]
    unique_image_urls = sorted(
        {normalized_url(url) for url in raw_image_urls}
    )

    image_host_counts: Counter[str] = Counter()
    image_path_counts: Counter[str] = Counter()

    for url in unique_image_urls:
        parsed = urlsplit(url)
        image_host_counts[parsed.netloc] += 1

        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2:
            family = "/" + "/".join(parts[:2]) + "/"
        elif parts:
            family = "/" + parts[0] + "/"
        else:
            family = "/"
        image_path_counts[family] += 1

    # ------------------------------------------------------------------
    # TABLAS
    # ------------------------------------------------------------------
    table_summaries = summarize_tables(tables)
    largest_tables = sorted(
        table_summaries,
        key=lambda item: (item["row_count"], item["max_columns"]),
        reverse=True,
    )

    report = {
        "analysis_version": 1,
        "source_capture": str(capture_dir),
        "source_page": {
            "url": source_summary.get("page_url")
            or source_summary.get("final_url")
            or source_summary.get("requested_url"),
            "title": source_summary.get("page_title")
            or source_summary.get("title"),
            "html_bytes": source_summary.get("html_bytes"),
        },
        "links": {
            "raw_count": len(raw_link_urls),
            "unique_count": len(unique_link_urls),
            "duplicate_count": len(raw_link_urls) - len(unique_link_urls),
            "unique_ratio": (
                len(unique_link_urls) / len(raw_link_urls)
                if raw_link_urls
                else 0.0
            ),
            "hosts": dict(host_counts.most_common()),
            "route_families": dict(family_counts.most_common()),
            "route_pattern_count": len(route_patterns),
        },
        "images": {
            "raw_count": len(raw_image_urls),
            "unique_count": len(unique_image_urls),
            "duplicate_count": len(raw_image_urls) - len(unique_image_urls),
            "hosts": dict(image_host_counts.most_common()),
            "path_families": dict(image_path_counts.most_common()),
        },
        "tables": {
            "count": len(table_summaries),
            "largest": largest_tables[:20],
        },
        "syntactically_detected_entities": detected_entity_counts,
        "notes": [
            "Entity counts are based only on explicit URL patterns recognized by this analysis script.",
            "Unknown route families are intentionally left unclassified until inspected.",
            "No network requests are performed by this script.",
        ],
    }

    dump_json(output_dir / "discovery_report.json", report)
    dump_json(output_dir / "unique_links.json", unique_link_urls)
    dump_json(output_dir / "route_patterns.json", route_patterns)
    dump_json(output_dir / "detected_entities.json", detected_entities)
    dump_json(output_dir / "unique_images.json", unique_image_urls)
    dump_json(output_dir / "tables_summary.json", table_summaries)

    print("=== BDFUTBOL DISCOVERY OFFLINE ===")
    print(f"Página:            {report['source_page']['title']}")
    print()
    print(
        f"Enlaces DOM:       {report['links']['raw_count']}"
    )
    print(
        f"Enlaces únicos:    {report['links']['unique_count']}"
    )
    print(
        f"Duplicados:        {report['links']['duplicate_count']}"
    )
    print(
        f"Patrones de ruta:  {report['links']['route_pattern_count']}"
    )
    print()
    print(
        f"Imágenes DOM:      {report['images']['raw_count']}"
    )
    print(
        f"Imágenes únicas:   {report['images']['unique_count']}"
    )
    print(
        f"Tablas:            {report['tables']['count']}"
    )

    if detected_entity_counts:
        print("\nIDs detectados sintácticamente:")
        for kind, count in detected_entity_counts.items():
            print(f"  {kind:<20} {count}")

    print("\nFamilias de rutas únicas:")
    for family, count in list(family_counts.most_common(20)):
        print(f"  {family:<16} {count}")

    print("\nPatrones más frecuentes:")
    for item in route_patterns[:20]:
        print(
            f"  {item['unique_url_count']:>5}  {item['signature']}"
        )

    print("\nTablas más grandes:")
    for table in largest_tables[:10]:
        print(
            f"  table[{table['index']}] "
            f"rows={table['row_count']} "
            f"cols<= {table['max_columns']} "
            f"id={table['id']!r} "
            f"class={table['class_name']!r}"
        )

    print(f"\n[+] Informe guardado en: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
