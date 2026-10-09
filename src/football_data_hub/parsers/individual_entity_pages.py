"""Offline parsers for captured individual BDFutbol entity pages.

The page contracts deliberately retain source text, table cells, classes, links,
and embedded JSON. Only identity and fields with a stable, visible source
contract are promoted to parsed values.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from football_data_hub.audits.entity_inventory import identify_entity_url

ENTITY_PAGE_PARSER_VERSION = "0.1.1"
ENTITY_PAGE_TYPES = ("match", "coach", "referee", "stadium")
_MATCH_TITLE = re.compile(
    r"^(?P<home>.+?)\s+-\s+(?P<away>.+?)\s+"
    r"\((?P<home_goals>\d+)\s+-\s+(?P<away_goals>\d+)\)\s+"
    r"(?P<date>\d{2}/\d{2}/\d{4})(?:\s+\([^)]*\))?\s+\|\s+BDFutbol$"
)
_JS_JSON_PARSE = re.compile(
    r"\b(?:var|let|const)\s+(?P<name>[\w$]+)\s*=\s*JSON\.parse\s*\(\s*",
)
_JS_JSON_VALUE = re.compile(r"\b(?:var|let|const)\s+(?P<name>[\w$]+)\s*=\s*(?P<value>[\[{])")
_CHALLENGE_MARKERS = (
    "just a moment",
    "verify you are human",
    "attention required! | cloudflare",
    "cf-chl-",
    "challenge-platform",
    "access denied",
)
_RELATED_ENTITY_TYPES = {"club", "player", "coach", "referee", "stadium", "match", "team_season"}
_TEAM_SEASON_PAGE_ID = re.compile(r"^t\d{4}-\d{3,}$")


class EntityPageError(ValueError):
    """Raised when a local entity snapshot fails integrity or page validation."""


@dataclass(frozen=True)
class EntitySnapshot:
    """A validated page snapshot and the source metadata needed to parse it."""

    metadata_path: Path
    html_path: Path
    metadata: dict[str, Any]
    html_bytes: bytes
    html_sha256: str
    entity_type: str
    entity_id: str
    final_url: str


def _safe_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _url_identity(url: Any) -> dict[str, str] | None:
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme != "https" or parts.netloc.casefold() not in {
        "www.bdfutbol.com", "bdfutbol.com",
    }:
        return None
    return identify_entity_url(url)


def _is_sports_page(entity_type: str, soup: BeautifulSoup) -> bool:
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    title_folded = title.casefold()
    h1_text = [" ".join(h.get_text(" ", strip=True).split()) for h in soup.find_all("h1")]
    if not any(h1_text):
        return False
    if entity_type == "match":
        return bool(soup.select_one(".hero-partit")) and len(
            soup.select(".hero-partit a[href*='/e/e']")
        ) >= 2
    if entity_type == "coach":
        return "entrenador" in title_folded and bool(soup.select_one("table.traject"))
    if entity_type == "referee":
        return "árbitro" in title_folded and bool(soup.select_one("table.traject"))
    if entity_type == "stadium":
        headings = {" ".join(h.get_text(" ", strip=True).split()).casefold() for h in soup.find_all("h2")}
        return bool(headings & {"equipo local", "competiciones", "ubicación"}) and bool(
            soup.select_one("#estadi, #chartVisitants, .stat-card")
        )
    return False


def load_valid_entity_snapshot(metadata_path: Path, repo_root: Path) -> EntitySnapshot:
    """Read and validate metadata, raw hash, requested/final identity, and DOM family."""
    try:
        metadata_bytes = metadata_path.read_bytes()
        metadata = json.loads(metadata_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EntityPageError(f"metadata.json no legible: {metadata_path}") from exc
    if not isinstance(metadata, dict):
        raise EntityPageError("metadata.json no contiene un objeto")

    requested = _url_identity(metadata.get("requested_url"))
    final_url = metadata.get("final_url") or metadata.get("requested_url")
    final = _url_identity(final_url)
    if final is None or final["entity_type"] not in ENTITY_PAGE_TYPES:
        raise EntityPageError("URL final fuera de las familias de ficha individual admitidas")
    if requested is None or requested != final:
        raise EntityPageError("la URL final no conserva el tipo e ID solicitados")
    if metadata.get("access_status") != "VALID":
        raise EntityPageError(f"estado de acceso no válido: {metadata.get('access_status')!r}")
    if metadata.get("http_status") != 200:
        raise EntityPageError(f"HTTP no válido: {metadata.get('http_status')!r}")

    html_path = metadata_path.parent / "rendered.html"
    try:
        html_bytes = html_path.read_bytes()
    except OSError as exc:
        raise EntityPageError("falta rendered.html") from exc
    actual_hash = hashlib.sha256(html_bytes).hexdigest()
    if metadata.get("rendered_html_sha256") != actual_hash:
        raise EntityPageError("SHA-256 de rendered.html no coincide con metadata.json")
    declared_size = metadata.get("rendered_html_bytes")
    if declared_size is not None and declared_size != len(html_bytes):
        raise EntityPageError("tamaño de rendered.html no coincide con metadata.json")

    html = html_bytes.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    body_text = soup.body.get_text(" ", strip=True) if soup.body else ""
    challenge_source = f"{title}\n{body_text[:5000]}\n{html[:5000]}".casefold()
    marker = next((value for value in _CHALLENGE_MARKERS if value in challenge_source), None)
    if marker:
        raise EntityPageError(f"marcador de desafío/error detectado: {marker}")
    if not _is_sports_page(final["entity_type"], soup):
        raise EntityPageError("DOM sin la estructura deportiva mínima de su tipo de ficha")

    return EntitySnapshot(
        metadata_path=metadata_path,
        html_path=html_path,
        metadata=metadata,
        html_bytes=html_bytes,
        html_sha256=actual_hash,
        entity_type=final["entity_type"],
        entity_id=final["entity_id"],
        final_url=str(final_url),
    )


def _text(node: Tag | None) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _relative_source_url(base_url: str, href: Any) -> str | None:
    if not isinstance(href, str) or not href.strip():
        return None
    try:
        return urljoin(base_url, href)
    except ValueError:
        return None


def _table_record(
    table: Tag,
    *,
    table_index: int,
    heading_raw: str | None,
    base_url: str,
) -> dict[str, Any]:
    rows = []
    is_trajectory = "traject" in table.get("class", [])
    for row_index, row in enumerate(table.find_all("tr")):
        if row.find_parent("table") is not table:
            continue
        cells = []
        for column_index, cell in enumerate(row.find_all(["th", "td"], recursive=False)):
            hrefs = [
                {
                    "text_raw": _text(anchor),
                    "href_raw": anchor.get("href"),
                    "url": _relative_source_url(base_url, anchor.get("href")),
                }
                for anchor in cell.find_all("a", href=True)
            ]
            classes = list(cell.get("class", []))
            cells.append({
                "column_index": column_index,
                "tag": cell.name,
                "value_raw": _text(cell),
                "title_raw": cell.get("title"),
                "classes_raw": classes,
                "style_raw": cell.get("style"),
                "hidden_by_inline_style": bool(
                    cell.get("style") and re.search(r"display\s*:\s*none", cell["style"], re.I)
                ),
                "hidden_by_source_class": any(
                    token in classes for token in ("d-none", "resp_off", "d-md-none")
                ),
                "colspan": int(cell.get("colspan", 1) or 1),
                "rowspan": int(cell.get("rowspan", 1) or 1),
                "links": hrefs,
            })
        source_header = bool(row.find_all("th", recursive=False)) or (is_trajectory and row_index == 0)
        rows.append({
            "row_index": row_index,
            "row_kind": "source_header" if source_header else "source_row",
            "classes_raw": list(row.get("class", [])),
            "cells": cells,
        })
    header_row = next((row for row in rows if row["row_kind"] == "source_header"), None)
    return {
        "table_index": table_index,
        "table_id_raw": table.get("id"),
        "classes_raw": list(table.get("class", [])),
        "section_heading_raw": heading_raw,
        "headers_raw": [cell["value_raw"] for cell in header_row["cells"]] if header_row else [],
        "rows": rows,
    }


def _tables(soup: BeautifulSoup, entity_type: str, base_url: str) -> list[dict[str, Any]]:
    records = []
    heading_raw: str | None = None
    relevant_tables = []
    for node in soup.find_all(["h2", "table"]):
        if node.name == "h2":
            heading_raw = _text(node)
            continue
        classes = set(node.get("class", []))
        if "d-none" in classes or "fons-blau-2" in classes:
            continue
        if entity_type == "match" and "taula_estil" not in classes:
            continue
        relevant_tables.append((node, heading_raw))
    all_tables = soup.find_all("table")
    source_indices = {id(table): index for index, table in enumerate(all_tables)}
    for table, heading in relevant_tables:
        records.append(_table_record(
            table,
            table_index=source_indices[id(table)],
            heading_raw=heading,
            base_url=base_url,
        ))
    return records


def _page_sections(soup: BeautifulSoup) -> list[dict[str, Any]]:
    sections = []
    for heading in soup.find_all(["h2", "h3"]):
        container = heading.parent if isinstance(heading.parent, Tag) else heading
        sections.append({
            "heading_level": int(heading.name[1]),
            "heading_raw": _text(heading),
            "container_tag": container.name,
            "container_classes_raw": list(container.get("class", [])),
            "text_raw": _text(container),
        })
    return sections


def _relationships(soup: BeautifulSoup, base_url: str, current: EntitySnapshot) -> list[dict[str, Any]]:
    results = []
    all_tables = soup.find_all("table")
    table_indices = {id(table): index for index, table in enumerate(all_tables)}
    for anchor_index, anchor in enumerate(soup.find_all("a", href=True)):
        url = _relative_source_url(base_url, anchor.get("href"))
        identity = _url_identity(url)
        if identity is None or identity["entity_type"] not in _RELATED_ENTITY_TYPES:
            continue
        if identity["entity_type"] == "team_season" and not _TEAM_SEASON_PAGE_ID.fullmatch(
            identity["entity_id"]
        ):
            continue
        if identity["entity_type"] == current.entity_type and identity["entity_id"] == current.entity_id:
            continue
        table = anchor.find_parent("table")
        row = anchor.find_parent("tr")
        cell = anchor.find_parent(["td", "th"])
        results.append({
            "target_entity_type": identity["entity_type"],
            "target_entity_id": identity["entity_id"],
            "anchor_text_raw": _text(anchor),
            "href_raw": anchor.get("href"),
            "url": url,
            "table_index": table_indices.get(id(table)) if table else None,
            "row_index": (
                len(row.find_previous_siblings("tr")) if row and table else None
            ),
            "cell_index": (
                len(cell.find_previous_siblings(["td", "th"])) if cell else None
            ),
            "anchor_index": anchor_index,
            "relationship_semantics": "LINK_OBSERVED_ONLY",
        })
    return results


def _image_references(soup: BeautifulSoup) -> list[dict[str, Any]]:
    return [
        {
            "src_raw": image.get("src"),
            "srcset_raw": image.get("srcset"),
            "data_src_raw": image.get("data-src"),
            "alt_raw": image.get("alt"),
            "title_raw": image.get("title"),
            "classes_raw": list(image.get("class", [])),
            "media_semantics": "UNCLASSIFIED_SOURCE_REFERENCE",
        }
        for image in soup.find_all("img")
        if any(image.get(key) for key in ("src", "srcset", "data-src"))
    ]


def _quoted_js_string(source: str, start: int) -> tuple[str, int] | None:
    quote = source[start] if start < len(source) else ""
    if quote not in {"'", '"'}:
        return None
    escaped = False
    for index in range(start + 1, len(source)):
        character = source[index]
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == quote:
            return source[start:index + 1], index + 1
    return None


def _embedded_json(soup: BeautifulSoup) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for script_index, script in enumerate(soup.find_all("script")):
        source = script.string or script.get_text()
        if not source:
            continue
        for match in _JS_JSON_PARSE.finditer(source):
            name = match.group("name")
            if name in {"data", "params", "response", "options"}:
                continue
            quoted = _quoted_js_string(source, match.end())
            if quoted is None:
                continue
            literal, end = quoted
            if not re.match(r"\s*\)", source[end:]):
                continue
            try:
                # JavaScript permits an escaped slash; Python warns about it in
                # string literals although its decoded value is simply "/".
                python_literal = literal.replace("\\/", "/")
                value = json.loads(ast.literal_eval(python_literal))
            except (ValueError, SyntaxError, json.JSONDecodeError):
                items.append({
                    "variable_name_raw": name,
                    "script_index": script_index,
                    "parse_status": "UNPARSED_JSON_PARSE_VALUE",
                })
                continue
            if isinstance(value, (list, dict)):
                signature = (name, json.dumps(value, ensure_ascii=False, sort_keys=True))
                if signature not in seen:
                    seen.add(signature)
                    items.append({
                        "variable_name_raw": name,
                        "script_index": script_index,
                        "parse_status": "SOURCE_JSON_PARSED",
                        "values_raw": value,
                    })
        for match in _JS_JSON_VALUE.finditer(source):
            name = match.group("name")
            if name in {"map", "chart", "root", "panel", "data", "params"}:
                continue
            try:
                value, _ = json.JSONDecoder().raw_decode(source[match.start("value"):])
            except json.JSONDecodeError:
                continue
            if isinstance(value, (list, dict)):
                signature = (name, json.dumps(value, ensure_ascii=False, sort_keys=True))
                if signature not in seen:
                    seen.add(signature)
                    items.append({
                        "variable_name_raw": name,
                        "script_index": script_index,
                        "parse_status": "SOURCE_JSON_PARSED",
                        "values_raw": value,
                    })
    return items


def _script_inventory(soup: BeautifulSoup) -> list[dict[str, Any]]:
    scripts = []
    for index, script in enumerate(soup.find_all("script")):
        text = script.string or script.get_text()
        variable_names = re.findall(
            r"\b(?:var|let|const)\s+([\w$]+)\s*=", text or ""
        )
        scripts.append({
            "script_index": index,
            "src_raw": script.get("src"),
            "inline_character_count": len(text or ""),
            "inline_variable_names_raw": variable_names,
        })
    return scripts


def _map_literals(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Preserve literal map center/marker arguments without interpreting them."""
    results = []
    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        if not text or "L.map(" not in text or "L.marker(" not in text:
            continue
        center = re.search(r"\.setView\(\s*(\[[^\]]+\])\s*,\s*([^\)]+)\)", text)
        marker = re.search(r"L\.marker\(\s*(\[[^\]]+\])\s*\)", text)
        popup = re.search(r"\.bindPopup\(\s*(['\"])(.*?)\1\s*\)", text, re.S)
        results.append({
            "center_coordinates_raw": center.group(1) if center else "",
            "zoom_raw": center.group(2).strip() if center else "",
            "marker_coordinates_raw": marker.group(1) if marker else "",
            "popup_label_raw": popup.group(2) if popup else "",
            "interpretation_status": "SOURCE_LITERALS_ONLY",
        })
    return results


def _match_title_fields(title: str) -> dict[str, Any] | None:
    match = _MATCH_TITLE.fullmatch(title)
    if match is None:
        return None
    try:
        date = datetime.strptime(match.group("date"), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None
    return {
        "home_team_name_raw": match.group("home").strip(),
        "away_team_name_raw": match.group("away").strip(),
        "home_goals": int(match.group("home_goals")),
        "away_goals": int(match.group("away_goals")),
        "date_raw": match.group("date"),
        "date": date,
        "evidence": "BDFUTBOL_MATCH_TITLE_PATTERN",
    }


def _match_hero_fields(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    hero = soup.select_one(".hero-partit")
    if hero is None:
        return []
    values = []
    for label in hero.select(".f14"):
        label_raw = _text(label)
        if label_raw not in {"Competición", "Jornada", "Estadio", "Fecha"}:
            continue
        value = label.find_next_sibling()
        if value is None:
            continue
        values.append({
            "label_raw": label_raw,
            "value_raw": _text(value),
            "value_classes_raw": list(value.get("class", [])),
            "links": [
                {
                    "text_raw": _text(anchor),
                    "href_raw": anchor.get("href"),
                    "url": _relative_source_url(base_url, anchor.get("href")),
                }
                for anchor in value.find_all("a", href=True)
            ],
        })
    return values


def parse_entity_snapshot(snapshot: EntitySnapshot, repo_root: Path) -> dict[str, Any]:
    """Parse a validated raw page without changing or exporting the raw HTML."""
    html = snapshot.html_bytes.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    h1_values = [_text(item) for item in soup.find_all("h1") if _text(item)]
    tables = _tables(soup, snapshot.entity_type, snapshot.final_url)
    relationships = _relationships(soup, snapshot.final_url, snapshot)
    embedded = _embedded_json(soup)
    image_references = _image_references(soup)
    source = {
        "provider": "BDFutbol",
        "requested_url": snapshot.metadata.get("requested_url"),
        "final_url": snapshot.final_url,
        "captured_at_utc": snapshot.metadata.get("captured_at_utc"),
        "http_status": snapshot.metadata.get("http_status"),
        "access_status": snapshot.metadata.get("access_status"),
        "snapshot_directory": _safe_relative(snapshot.metadata_path.parent, repo_root),
        "metadata_path": _safe_relative(snapshot.metadata_path, repo_root),
        "rendered_html_path": _safe_relative(snapshot.html_path, repo_root),
        "rendered_html_bytes": len(snapshot.html_bytes),
        "rendered_html_sha256": snapshot.html_sha256,
    }
    inventory_path = snapshot.metadata_path.parent / "inventory.json"
    if inventory_path.is_file():
        try:
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            inventory = {}
        document = inventory.get("document", {}) if isinstance(inventory, dict) else {}
        source["capture_inventory"] = {
            "document_ready_state": document.get("ready_state"),
            "total_elements": document.get("total_elements"),
            "observed_counts": {
                key: (inventory.get(key, {}).get("total") if isinstance(inventory.get(key), dict) else None)
                for key in ("tables", "images", "sources", "selects", "buttons", "tabs", "galleries", "charts", "scripts", "iframes", "xhr")
            },
        }

    record: dict[str, Any] = {
        "schema_version": f"football_data_hub.{snapshot.entity_type}_detail.v1",
        "parser_version": ENTITY_PAGE_PARSER_VERSION,
        "entity_type": snapshot.entity_type,
        "entity_id": snapshot.entity_id,
        "url": snapshot.final_url,
        "identity_status": "VERIFIED_FROM_REQUESTED_AND_FINAL_URL",
        "page_title_raw": title,
        "h1_raw": h1_values,
        "page_sections": _page_sections(soup),
        "tables": tables,
        "related_entity_links": relationships,
        "image_references": image_references,
        "embedded_json": embedded,
        "scripts": _script_inventory(soup),
        "map_literals_raw": _map_literals(soup),
        "source": source,
        "coverage": {
            "page_status": "CAPTURED_VALID",
            "semantic_entity_completeness": "NOT_ASSERTED",
            "normalized_field_count": 1,
            "table_count": len(tables),
            "table_row_count": sum(len(table["rows"]) for table in tables),
            "table_cell_count": sum(
                len(row["cells"]) for table in tables for row in table["rows"]
            ),
            "related_link_count": len(relationships),
            "image_reference_count": len(image_references),
            "embedded_json_dataset_count": len(embedded),
            "interpretation_status": "PARTIAL_STRUCTURED_WITH_RAW_PRESERVATION",
            "full_html_retained_at_raw_path": source["rendered_html_path"],
        },
        "field_interpretation": {
            "entity_id": "NORMALIZED_FROM_VALIDATED_SOURCE_URL",
            "page_title": "RAW_ONLY",
            "h1": "RAW_ONLY",
            "table_cells": "RAW_ONLY_WITH_SOURCE_CLASSES_AND_LINKS",
            "related_entity_links": "LINK_OBSERVED_ONLY",
            "image_references": "UNCLASSIFIED_SOURCE_REFERENCE",
            "embedded_json": "SOURCE_KEYS_AND_VALUES_PRESERVED_WITHOUT_DOMAIN_EXPANSION",
        },
    }
    if snapshot.entity_type == "match":
        record["match_title_fields"] = _match_title_fields(title)
        record["match_hero_fields_raw"] = _match_hero_fields(soup, snapshot.final_url)
        hero = soup.select_one(".hero-partit")
        events = hero.select_one(".row.text-center.mb-0") if hero else None
        record["match_hero_events_text_raw"] = [_text(events)] if _text(events) else []
        record["field_interpretation"]["match_title_fields"] = (
            "NORMALIZED_FROM_OBSERVED_TITLE_PATTERN"
            if record["match_title_fields"] else "NOT_PARSED_TITLE_PATTERN_NOT_MATCHED"
        )
        record["coverage"]["normalized_field_count"] += 5 if record["match_title_fields"] else 0
    else:
        record["display_name_raw"] = h1_values[0]
        record["field_interpretation"]["display_name"] = "RAW_ONLY"
    return record


def parse_entity_metadata_file(metadata_path: Path, repo_root: Path) -> dict[str, Any]:
    """Validate and parse one local metadata/rendered HTML pair."""
    return parse_entity_snapshot(load_valid_entity_snapshot(metadata_path, repo_root), repo_root)
