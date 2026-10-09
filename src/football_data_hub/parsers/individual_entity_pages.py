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

ENTITY_PAGE_PARSER_VERSION = "0.2.0"
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
                "source_elements_raw": [
                    {
                        "tag": element.name,
                        "text_raw": _text(element),
                        "classes_raw": list(element.get("class", [])),
                        "title_raw": element.get("title"),
                        "style_raw": element.get("style"),
                        "src_raw": element.get("src"),
                        "alt_raw": element.get("alt"),
                    }
                    for element in cell.find_all(True)
                    if any(element.get(key) for key in (
                        "class", "title", "style", "src", "alt",
                    ))
                ],
            })
        source_header = bool(row.find_all("th", recursive=False)) or (is_trajectory and row_index == 0)
        rows.append({
            "row_index": row_index,
            "row_kind": "source_header" if source_header else "source_row",
            "classes_raw": list(row.get("class", [])),
            "style_raw": row.get("style"),
            "hidden_by_inline_style": bool(
                row.get("style") and re.search(r"display\s*:\s*none", row["style"], re.I)
            ),
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


def _linked_entity(anchor: Tag, base_url: str) -> dict[str, Any] | None:
    url = _relative_source_url(base_url, anchor.get("href"))
    identity = _url_identity(url)
    if identity is None:
        return None
    final_path_component = urlsplit(url).path.rsplit("/", 1)[-1]
    source_id_raw = (
        identity["entity_id"] if identity["entity_type"] == "match"
        else final_path_component.rsplit(".", 1)[0]
    )
    return {
        "entity_type": identity["entity_type"],
        "entity_id": identity["entity_id"],
        "source_id_raw": source_id_raw,
        "name_raw": _text(anchor),
        "href_raw": anchor.get("href"),
        "url": url,
    }


def _match_clubs(soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
    hero = soup.select_one(".hero-partit")
    heading = hero.find("h1") if hero else None
    if heading is None:
        return []
    clubs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for anchor in heading.find_all("a", href=True):
        linked = _linked_entity(anchor, base_url)
        if linked is None or linked["entity_type"] != "club":
            continue
        if linked["entity_id"] not in seen:
            seen.add(linked["entity_id"])
            clubs.append(linked)
    return clubs


def _own_table_rows(table: Tag) -> list[Tag]:
    return [row for row in table.find_all("tr") if row.find_parent("table") is table]


def _match_table_contexts(soup: BeautifulSoup) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Group visible match tables by the headings and two-column DOM layout."""
    all_tables = soup.find_all("table")
    table_indices = {id(table): index for index, table in enumerate(all_tables)}
    contexts: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    handled: set[int] = set()

    for layout_row in soup.select(".row.pt-3.pb-2"):
        heading_raw: str | None = None
        groups: list[dict[str, Any]] = []
        for node in layout_row.find_all(["h2", "table"]):
            if node.name == "h2":
                heading_raw = _text(node)
                continue
            if "taula_estil" not in node.get("class", []):
                continue
            table_index = table_indices[id(node)]
            handled.add(table_index)
            classes = set(node.get("class", []))
            if classes & {"d-none", "fons-blau-2"}:
                rows = _own_table_rows(node)
                excluded.append({
                    "table_index": table_index,
                    "table_id_raw": node.get("id"),
                    "classes_raw": list(node.get("class", [])),
                    "row_count": len(rows),
                    "cell_count": sum(
                        len(row.find_all(["th", "td"], recursive=False)) for row in rows
                    ),
                    "interpretation_status": "RAW_ONLY_HIDDEN_TABLE_NOT_PROMOTED",
                })
                continue
            if not groups or groups[-1]["heading_raw"] != heading_raw:
                groups.append({"heading_raw": heading_raw, "tables": []})
            groups[-1]["tables"].append(node)

        has_substitutes_heading = any(
            (group["heading_raw"] or "").strip().casefold() == "suplentes"
            for group in groups
        )
        for group in groups:
            heading = group["heading_raw"]
            tables = group["tables"]
            heading_folded = (heading or "").strip().casefold()
            section = "UNKNOWN"
            section_evidence = "NO_MATCH_SECTION_HEADING"
            if heading_folded == "suplentes":
                section = "SUBSTITUTES"
                section_evidence = (
                    "EXPLICIT_H2_SUPLENTES_AND_TWO_SIDE_TABLES"
                    if len(tables) == 2 else "EXPLICIT_H2_SUPLENTES_UNPAIRED_TABLES"
                )
            elif heading_folded == "entrenadores":
                section = "COACHES"
                section_evidence = (
                    "EXPLICIT_H2_ENTRENADORES_AND_TWO_SIDE_TABLES"
                    if len(tables) == 2 else "EXPLICIT_H2_ENTRENADORES_UNPAIRED_TABLES"
                )
            elif heading is None and has_substitutes_heading and len(tables) == 2:
                player_counts = []
                for table in tables:
                    count = 0
                    for row in _own_table_rows(table):
                        if row.get("style") and re.search(r"display\s*:\s*none", row["style"], re.I):
                            continue
                        if row.get_text(" ", strip=True):
                            count += 1
                    player_counts.append(count)
                if player_counts == [11, 11]:
                    section = "STARTING_LINEUP"
                    section_evidence = "TWO_ELEVEN_ROW_TABLES_PRECEDING_EXPLICIT_H2_SUPLENTES"
                else:
                    section_evidence = "UNLABELED_TWO_COLUMN_GROUP_BEFORE_SUPLENTES"

            for side_index, table in enumerate(tables):
                contexts.append({
                    "table": table,
                    "table_index": table_indices[id(table)],
                    "section_heading_raw": heading,
                    "section": section,
                    "section_evidence": section_evidence,
                    "side_index": side_index if len(tables) == 2 else None,
                })

    # Retain visibility evidence for a sports table outside the recognized match layout.
    for table in soup.select("table.taula_estil"):
        table_index = table_indices[id(table)]
        if table_index in handled:
            continue
        classes = set(table.get("class", []))
        if classes & {"d-none", "fons-blau-2"}:
            rows = _own_table_rows(table)
            excluded.append({
                "table_index": table_index,
                "table_id_raw": table.get("id"),
                "classes_raw": list(table.get("class", [])),
                "row_count": len(rows),
                "cell_count": sum(
                    len(row.find_all(["th", "td"], recursive=False)) for row in rows
                ),
                "interpretation_status": "RAW_ONLY_HIDDEN_TABLE_NOT_PROMOTED",
            })
        else:
            contexts.append({
                "table": table,
                "table_index": table_index,
                "section_heading_raw": None,
                "section": "UNKNOWN",
                "section_evidence": "TABLE_OUTSIDE_RECOGNIZED_MATCH_LAYOUT",
                "side_index": None,
            })
    return contexts, excluded


def _team_assignment(
    clubs: list[dict[str, Any]], side_index: int | None,
) -> dict[str, Any]:
    if side_index in (0, 1) and len(clubs) == 2:
        club = clubs[side_index]
        return {
            "entity_type": "club",
            "entity_id": club["entity_id"],
            "source_entity_id_raw": club["source_id_raw"],
            "name_raw": club["name_raw"],
            "side": "HOME" if side_index == 0 else "AWAY",
            "assignment_status": "STRUCTURAL_ORDER_MATCHES_HOME_AWAY_HERO",
        }
    return {
        "entity_type": None,
        "entity_id": None,
        "name_raw": None,
        "side": None,
        "assignment_status": "UNVERIFIABLE_FROM_TWO_COLUMN_MATCH_LAYOUT",
    }


def _marker_minute_raw(marker: Tag) -> str | None:
    container = marker.parent if isinstance(marker.parent, Tag) else marker
    container_text = _text(container)
    marker_text = _text(marker)
    if marker_text:
        container_text = container_text.replace(marker_text, " ", 1).strip()
    match = re.search(r"(?P<minute>\d+(?:\+\d+)?)\s*['’′]?\s*$", container_text)
    return match.group("minute") if match else None


def _match_hero_events(
    soup: BeautifulSoup,
    base_url: str,
    clubs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    hero = soup.select_one(".hero-partit")
    event_row = hero.select_one(".row.text-center.mb-0") if hero else None
    if event_row is None:
        return [], [], []
    team_columns = [
        child for child in event_row.find_all("div", recursive=False)
        if "col-6" in child.get("class", [])
    ]
    team_column_index = {id(column): index for index, column in enumerate(team_columns)}
    occurrences: list[dict[str, Any]] = []
    unclassified: list[dict[str, Any]] = []
    canonical: dict[tuple[Any, ...], dict[str, Any]] = {}
    occurrence_index = 0
    for column in team_columns:
        column_index = team_column_index[id(column)]
        for node in column.select(".text-blanc"):
            raw_text = _text(node)
            score_span = next((span for span in node.find_all("span") if re.fullmatch(
                r"\s*\d+\s*-\s*\d+\s*", _text(span)
            )), None)
            player_links = []
            for anchor in node.find_all("a", href=True):
                linked = _linked_entity(anchor, base_url)
                if linked and linked["entity_type"] == "player":
                    player_links.append(linked)
            minute_match = re.search(
                r"(?P<minute_text>\d+(?:\+\d+)?)\s*['’′]?\s*$", raw_text
            )
            minute_raw = minute_match.group("minute_text") if minute_match else None
            score_raw = _text(score_span) if score_span else None
            actor = player_links[0] if len(player_links) == 1 else None
            team = _team_assignment(clubs, column_index)
            occurrence = {
                "occurrence_index": occurrence_index,
                "event_text_raw": raw_text,
                "html_raw": str(node),
                "score_raw": score_raw,
                "minute_raw": minute_raw,
                "minute_text_raw": minute_match.group(0) if minute_match else None,
                "player_links": player_links,
                "team_assignment": team,
            }
            occurrences.append(occurrence)
            occurrence_index += 1
            if score_raw is None:
                unclassified.append({
                    **occurrence,
                    "interpretation_status": "RAW_ONLY_NO_SCORE_CHANGE_MARKER",
                })
                continue
            event_key = ("GOAL", score_raw, actor["entity_id"] if actor else None, minute_raw,
                         raw_text if actor is None else None)
            if event_key in canonical:
                event = canonical[event_key]
                event["source_occurrence_indexes"].append(occurrence["occurrence_index"])
                event["source_occurrence_count"] += 1
                continue
            canonical[event_key] = {
                "event_type": "GOAL",
                "score_raw": score_raw,
                "minute_raw": minute_raw,
                "minute_status": "PRESENT" if minute_raw is not None else "NOT_PRESENT",
                "player_entity_id": actor["entity_id"] if actor else None,
                "player_source_id_raw": actor["source_id_raw"] if actor else None,
                "player_name_raw": actor["name_raw"] if actor else (
                    player_links[0]["name_raw"] if player_links else None
                ),
                "player_identity_status": (
                    "LINK_VERIFIED" if actor else
                    "AMBIGUOUS_PLAYER_LINKS" if len(player_links) > 1 else "PLAYER_LINK_NOT_PRESENT"
                ),
                "team": team,
                "source_occurrence_indexes": [occurrence["occurrence_index"]],
                "source_occurrence_count": 1,
                "source_event_text_raw": raw_text,
                "interpretation_status": "SCORE_CHANGE_AND_HERO_EVENT_STRUCTURE",
            }
    return list(canonical.values()), occurrences, unclassified


def _row_source_markers(row: Tag) -> list[dict[str, Any]]:
    markers = []
    for marker in row.select(".cosa > div"):
        cell = marker.find_parent(["td", "th"])
        cells = row.find_all(["td", "th"], recursive=False)
        markers.append({
            "title_raw": marker.get("title"),
            "classes_raw": list(marker.get("class", [])),
            "minute_raw": _marker_minute_raw(marker),
            "cell_index": next((index for index, item in enumerate(cells) if item is cell), None),
            "cell_text_raw": _text(cell) if cell else None,
            "marker_html_raw": str(marker),
        })
    return markers


def _match_players_and_coaches(
    contexts: list[dict[str, Any]],
    clubs: list[dict[str, Any]],
    base_url: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    players: list[dict[str, Any]] = []
    coaches: list[dict[str, Any]] = []
    substitution_events: list[dict[str, Any]] = []
    card_events: list[dict[str, Any]] = []
    unclassified_markers: list[dict[str, Any]] = []
    for context in contexts:
        table = context["table"]
        section = context["section"]
        team = _team_assignment(clubs, context["side_index"])
        if section not in {"STARTING_LINEUP", "SUBSTITUTES", "COACHES"}:
            continue
        for row_index, row in enumerate(_own_table_rows(table)):
            if row.get("style") and re.search(r"display\s*:\s*none", row["style"], re.I):
                continue
            cells = row.find_all(["td", "th"], recursive=False)
            if not cells or not _text(row):
                continue
            links = [
                linked for anchor in row.find_all("a", href=True)
                if (linked := _linked_entity(anchor, base_url)) is not None
                and linked["entity_type"] == ("coach" if section == "COACHES" else "player")
            ]
            name_cell_index = 2 if section == "COACHES" and len(cells) >= 3 else 3
            name_raw = links[0]["name_raw"] if len(links) == 1 else (
                _text(cells[name_cell_index]) if len(cells) > name_cell_index else None
            )
            markers = _row_source_markers(row)
            source_ref = {
                "table_index": context["table_index"],
                "row_index": row_index,
                "section_heading_raw": context["section_heading_raw"],
                "section_evidence": context["section_evidence"],
            }
            if section == "COACHES":
                coach = {
                    "coach_entity_id": links[0]["entity_id"] if len(links) == 1 else None,
                    "coach_source_id_raw": links[0]["source_id_raw"] if len(links) == 1 else None,
                    "coach_name_raw": name_raw,
                    "role_raw": context["section_heading_raw"],
                    "role": "COACH" if context["section_heading_raw"] == "Entrenadores" else None,
                    "team": team,
                    "identity_status": (
                        "LINK_VERIFIED" if len(links) == 1 else
                        "AMBIGUOUS_COACH_LINKS" if len(links) > 1 else "COACH_LINK_NOT_PRESENT"
                    ),
                    "source": source_ref,
                    "source_markers": markers,
                }
                coaches.append(coach)
                actor_type = "COACH"
                actor_id = coach["coach_entity_id"]
                actor_source_id = coach["coach_source_id_raw"]
                actor_name = coach["coach_name_raw"]
            else:
                participant = {
                    "player_entity_id": links[0]["entity_id"] if len(links) == 1 else None,
                    "player_source_id_raw": links[0]["source_id_raw"] if len(links) == 1 else None,
                    "player_name_raw": name_raw,
                    "team": team,
                    "roster_section": section,
                    "roster_section_evidence": context["section_evidence"],
                    "participation_status": (
                        "STARTING_LINEUP_LISTED" if section == "STARTING_LINEUP" else
                        "SUBSTITUTE_ENTERED" if any(marker["title_raw"] == "Entra" for marker in markers) else
                        "SUBSTITUTE_LISTED_PARTICIPATION_NOT_EVIDENCED"
                    ),
                    "leading_cell_raw": _text(cells[0]) if cells else None,
                    "leading_cell_interpretation": "RAW_ONLY_NO_VERIFIED_COLUMN_HEADER",
                    "identity_status": (
                        "LINK_VERIFIED" if len(links) == 1 else
                        "AMBIGUOUS_PLAYER_LINKS" if len(links) > 1 else "PLAYER_LINK_NOT_PRESENT"
                    ),
                    "source": source_ref,
                    "source_markers": markers,
                }
                players.append(participant)
                actor_type = "PLAYER"
                actor_id = participant["player_entity_id"]
                actor_source_id = participant["player_source_id_raw"]
                actor_name = participant["player_name_raw"]

            for marker in markers:
                title = marker["title_raw"]
                if title in {"Entra", "Sale"} and section != "COACHES":
                    substitution_events.append({
                        "event_type": "SUBSTITUTION_ACTION",
                        "action": "PLAYER_ENTERED" if title == "Entra" else "PLAYER_LEFT",
                        "minute_raw": marker["minute_raw"],
                        "player_entity_id": actor_id,
                        "player_source_id_raw": actor_source_id,
                        "player_name_raw": actor_name,
                        "player_identity_status": "LINK_VERIFIED" if actor_id else "PLAYER_ID_NOT_LINKED",
                        "team": team,
                        "pairing_status": "NOT_INFERRED",
                        "source": {**source_ref, "cell_index": marker["cell_index"]},
                        "source_marker": marker,
                    })
                elif title in {"Tarjeta Amarilla", "Tarjeta Roja"}:
                    card_events.append({
                        "event_type": "CARD",
                        "card_type": "YELLOW" if title == "Tarjeta Amarilla" else "RED",
                        "label_raw": title,
                        "minute_raw": marker["minute_raw"],
                        "actor_entity_type": actor_type,
                        "actor_entity_id": actor_id,
                        "actor_source_id_raw": actor_source_id,
                        "actor_name_raw": actor_name,
                        "team": team,
                        "source": {**source_ref, "cell_index": marker["cell_index"]},
                        "source_marker": marker,
                    })
                elif title != "Gol":
                    unclassified_markers.append({
                        "title_raw": title,
                        "actor_entity_type": actor_type,
                        "actor_entity_id": actor_id,
                        "actor_name_raw": actor_name,
                        "source": {**source_ref, "cell_index": marker["cell_index"]},
                        "source_marker": marker,
                        "interpretation_status": "RAW_ONLY_UNKNOWN_MARKER",
                    })
    return players, coaches, substitution_events, card_events, unclassified_markers


def _match_detail_semantics(
    soup: BeautifulSoup,
    base_url: str,
    title_fields: dict[str, Any] | None,
    capture_inventory: dict[str, Any] | None,
    capture_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    clubs = _match_clubs(soup, base_url)
    contexts, excluded_tables = _match_table_contexts(soup)
    goals, hero_occurrences, unclassified_hero = _match_hero_events(soup, base_url, clubs)
    participants, coaches, substitutions, cards, unclassified_markers = _match_players_and_coaches(
        contexts, clubs, base_url,
    )
    for goal in goals:
        goal["corroborating_player_table_markers"] = [
            {
                "player_entity_id": participant["player_entity_id"],
                "player_name_raw": participant["player_name_raw"],
                "source": participant["source"],
                "marker": marker,
            }
            for participant in participants
            if participant["player_entity_id"] == goal["player_entity_id"]
            for marker in participant["source_markers"]
            if marker["title_raw"] == "Gol" and marker["minute_raw"] == goal["minute_raw"]
        ]
    events = goals + substitutions + cards
    title_goals = (
        title_fields["home_goals"] + title_fields["away_goals"]
        if title_fields else None
    )
    last_score = goals[-1]["score_raw"] if goals else None
    published_score = (
        f"{title_fields['home_goals']}-{title_fields['away_goals']}"
        if title_fields else None
    )
    if title_goals is not None and goals:
        result_coherence = (
            "EVENT_SCORE_SEQUENCE_MATCHES_PUBLISHED_RESULT_COUNT_NOT_COMPLETENESS"
            if len(goals) == title_goals and last_score == published_score
            else "EVENTS_DO_NOT_FULLY_MATCH_PUBLISHED_RESULT"
        )
    else:
        result_coherence = "NOT_COMPARABLE"
    presentation_tables = [
        table for table in soup.find_all("table")
        if "taula_estil" not in table.get("class", [])
        and set(table.get("class", [])) & {"d-none", "fons-blau-2"}
    ]
    return {
        "clubs": clubs,
        "players": participants,
        "coaches": coaches,
        "events": events,
        "event_occurrences_raw": hero_occurrences,
        "unclassified_hero_event_occurrences": unclassified_hero,
        "unclassified_source_markers": unclassified_markers,
        "excluded_hidden_sports_tables": excluded_tables,
        "quality": {
            "table_context_count": len(contexts),
            "visible_match_table_count": len(_tables(soup, "match", base_url)),
            "total_source_table_count": len(soup.find_all("table")),
            "excluded_presentation_table_count": len(presentation_tables),
            "hidden_sports_table_count": len(excluded_tables),
            "participant_count": len(participants),
            "linked_participant_count": sum(bool(item["player_entity_id"]) for item in participants),
            "coach_count": len(coaches),
            "goal_event_count": len(goals),
            "goal_occurrence_count": sum(item["source_occurrence_count"] for item in goals),
            "substitution_action_count": len(substitutions),
            "card_event_count": len(cards),
            "unclassified_hero_event_count": len(unclassified_hero),
            "unclassified_source_marker_count": len(unclassified_markers),
            "event_list_completeness": "UNKNOWN",
            "event_ordering": "GOALS_THEN_TABLE_ACTIONS_THEN_CARDS_NOT_A_GLOBAL_TIMELINE",
            "semantic_entity_completeness": "NOT_ASSERTED",
            "published_result_coherence": result_coherence,
            "capture_ready_state": (
                capture_inventory.get("document_ready_state") if capture_inventory else None
            ),
            "capture_inventory_complete": (
                capture_summary.get("complete") if capture_summary else
                capture_inventory.get("complete") if capture_inventory else None
            ),
            "capture_interaction_coverage": (
                capture_summary.get("interaction_coverage") if capture_summary else None
            ),
            "capture_readiness_status": (
                "PRESENT_SNAPSHOT_REPORTED_LOADING"
                if capture_inventory and capture_inventory.get("document_ready_state") == "loading"
                or capture_summary and capture_summary.get("complete") is False
                else "CAPTURE_READINESS_NOT_AVAILABLE"
            ),
            "limitations": [
                "Visible goal sequence matching the final score does not prove all match events were captured.",
                "Substitution actions are not paired into substitutions when pairing is not explicit.",
                "Player cells without source headers remain raw-only and are not interpreted as position or statistics.",
                "The snapshot inventory reports loading; absent resources or late DOM content cannot be ruled out.",
            ],
        },
    }


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
            "complete": inventory.get("complete"),
            "total_elements": document.get("total_elements"),
            "observed_counts": {
                key: (inventory.get(key, {}).get("total") if isinstance(inventory.get(key), dict) else None)
                for key in ("tables", "images", "sources", "selects", "buttons", "tabs", "galleries", "charts", "scripts", "iframes", "xhr")
            },
        }
    summary_path = snapshot.metadata_path.parent / "summary.json"
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            summary = {}
        if isinstance(summary, dict):
            source["capture_summary"] = {
                "scope": summary.get("scope"),
                "interaction_coverage": summary.get("interaction_coverage"),
                "complete": summary.get("complete"),
                "coverage_warnings": summary.get("coverage_warnings", []),
                "truncated_collections": summary.get("truncated_collections", []),
            }

    record: dict[str, Any] = {
        "schema_version": f"football_data_hub.{snapshot.entity_type}_detail.v2",
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
        semantics = _match_detail_semantics(
            soup,
            snapshot.final_url,
            record["match_title_fields"],
            source.get("capture_inventory"),
            source.get("capture_summary"),
        )
        record["match_clubs"] = semantics["clubs"]
        record["match_participants"] = semantics["players"]
        record["match_coaches"] = semantics["coaches"]
        record["match_events"] = semantics["events"]
        record["match_event_occurrences_raw"] = semantics["event_occurrences_raw"]
        record["unclassified_hero_event_occurrences"] = semantics[
            "unclassified_hero_event_occurrences"
        ]
        record["unclassified_source_markers"] = semantics["unclassified_source_markers"]
        record["excluded_hidden_sports_tables"] = semantics["excluded_hidden_sports_tables"]
        record["match_quality"] = semantics["quality"]
        record["field_interpretation"]["match_title_fields"] = (
            "NORMALIZED_FROM_OBSERVED_TITLE_PATTERN"
            if record["match_title_fields"] else "NOT_PARSED_TITLE_PATTERN_NOT_MATCHED"
        )
        record["field_interpretation"].update({
            "match_clubs": "LINKED_FROM_HERO_H1_HOME_AWAY_ORDER",
            "match_participants": "SOURCE_ROSTER_TABLES_WITH_SECTION_AND_LINK_EVIDENCE",
            "match_coaches": "EXPLICIT_ENTRENADORES_SECTION_AND_LINKS",
            "match_events": "SCORE_CHANGE_AND_EXPLICIT_SOURCE_MARKERS_ONLY",
            "unclassified_hero_event_occurrences": "RAW_ONLY",
            "unclassified_source_markers": "RAW_ONLY",
            "excluded_hidden_sports_tables": "RAW_ONLY_NOT_PROMOTED",
            "match_quality": "CAPTURE_AND_INTERPRETATION_LIMITATIONS_RETAINED",
        })
        record["coverage"]["normalized_field_count"] += 5 if record["match_title_fields"] else 0
        record["coverage"].update({
            "participant_count": len(record["match_participants"]),
            "coach_count": len(record["match_coaches"]),
            "event_count": len(record["match_events"]),
            "event_occurrence_count": len(record["match_event_occurrences_raw"]),
            "event_list_completeness": "UNKNOWN",
            "semantic_entity_completeness": "NOT_ASSERTED",
        })
    else:
        record["display_name_raw"] = h1_values[0]
        record["field_interpretation"]["display_name"] = "RAW_ONLY"
    return record


def parse_entity_metadata_file(metadata_path: Path, repo_root: Path) -> dict[str, Any]:
    """Validate and parse one local metadata/rendered HTML pair."""
    return parse_entity_snapshot(load_valid_entity_snapshot(metadata_path, repo_root), repo_root)
