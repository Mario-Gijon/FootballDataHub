"""Offline parsing helpers for BDFutbol club and team-season pages.

The parser keeps every page-content table row, original cell value, link and
image reference. It deliberately does not interpret page-wide filter choices as
new records or fetch linked player/coach histories.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

PARSER_VERSION = "1.3.0"
SCHEMA_VERSION = "football_data_hub.bdfutbol.club_team.v2"

_CLUB_ID = re.compile(r"^e(?P<number>\d+)$")
_TEAM_SEASON_ID = re.compile(r"^t\d{4}-\d+$")
_PROFILE_PATHS = {
    "club_profile": re.compile(r"^/es/e/e(?P<number>\d+)\.html$"),
    "club_players": re.compile(r"^/es/e/egols(?P<number>\d+)\.html$"),
    "club_coaches": re.compile(r"^/es/e/eentr(?P<number>\d+)\.html$"),
    "club_matches": re.compile(r"^/es/p/e(?P<number>\d+)\.html$"),
    "club_rivals": re.compile(r"^/es/p/er(?P<number>\d+)\.html$"),
}
_PERSON_PATH = {
    "player": re.compile(r"^/es/j/(j\d+)\.html$"),
    "coach": re.compile(r"^/es/l/(l\d+)\.html$"),
    "club": re.compile(r"^/es/e/(e\d+)\.html$"),
    "team_season": re.compile(r"^/es/t/(t\d{4}-\d+)\.html$"),
    "stadium": re.compile(r"^/es/s/(\d+)\.html$"),
    "match_path": re.compile(r"^/es/p/(p\d+)\.html$"),
}
_CHART_SELECTOR = re.compile(r"chart|graf|graph|highchart|plot", re.IGNORECASE)


class InvalidClubTeamPage(ValueError):
    """The URL or HTML cannot be interpreted as a BDFutbol club/team page."""


def classify_club_team_url(url: str) -> dict[str, str] | None:
    """Return the known page family and source identity, if URL is in scope."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in {"www.bdfutbol.com", "bdfutbol.com"}:
        return None

    team_match = _PERSON_PATH["team_season"].fullmatch(parts.path)
    if team_match:
        team_id = team_match.group(1)
        params = parse_qs(parts.query)
        query_view = params.get("t", [None])[-1]
        tab_view = params.get("tab", [None])[-1]
        view = {
            None: "team_alignment",
            "plantilla": "team_roster",
            "lista": "team_statistics",
            "seg": "team_tracking",
            "altas": "team_transfers",
        }.get(query_view)
        if tab_view == "partits":
            view = "team_matches"
        if view is None:
            return None
        return {"entity_type": "team_season", "entity_id": team_id, "view": view}

    for view, pattern in _PROFILE_PATHS.items():
        match = pattern.fullmatch(parts.path)
        if not match:
            continue
        number = match.group("number")
        if view == "club_profile" and parse_qs(parts.query).get("p") == ["stats"]:
            view = "club_statistics"
        elif view == "club_profile" and parts.query:
            return None
        return {"entity_type": "club", "entity_id": f"e{number}", "view": view}

    if parts.path == "/es/e/e.html":
        return None
    return None


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _direct_cells(row: Tag) -> list[Tag]:
    cells = row.find_all(["th", "td"], recursive=False)
    return cells or row.select("th, td")


def _content_roots(soup: BeautifulSoup) -> list[Tag]:
    """Exclude BDFutbol's repeated mega-menu tables from page data."""
    body = soup.find("div", id="body")
    if not isinstance(body, Tag):
        return [soup.body] if isinstance(soup.body, Tag) else [soup]
    children = [child for child in body.find_all(recursive=False) if isinstance(child, Tag)]
    hero_index = next(
        (i for i, child in enumerate(children) if "hero" in (child.get("class") or [])),
        None,
    )
    if hero_index is not None:
        return children[hero_index:]
    return [
        child for child in children
        if child.get("id") != "superheader" and "superheader" not in (child.get("class") or [])
    ] or [body]


def _link_record(anchor: Tag, base_url: str) -> dict[str, Any]:
    raw_href = anchor.get("href")
    return {
        "text": _clean_text(anchor.get_text(" ", strip=True)),
        "href_raw": raw_href,
        "url": urljoin(base_url, str(raw_href)) if raw_href else None,
        "title": anchor.get("title"),
        "rel": anchor.get("rel"),
    }


def _image_record(image: Tag, base_url: str) -> dict[str, Any]:
    def absolute(attribute: str) -> str | None:
        value = image.get(attribute)
        return urljoin(base_url, str(value)) if value else None

    return {
        "src_raw": image.get("src"),
        "src": absolute("src"),
        "srcset": image.get("srcset"),
        "data_src": image.get("data-src"),
        "data_lazy_src": image.get("data-lazy-src"),
        "alt": image.get("alt"),
        "title": image.get("title"),
        "width": image.get("width"),
        "height": image.get("height"),
    }


def _cell_record(cell: Tag, base_url: str) -> dict[str, Any]:
    return {
        "tag": cell.name,
        "text": _clean_text(cell.get_text(" ", strip=True)),
        "colspan": cell.get("colspan"),
        "rowspan": cell.get("rowspan"),
        "classes": list(cell.get("class") or []),
        "style": cell.get("style"),
        "hidden_attribute": cell.has_attr("hidden"),
        "links": [_link_record(anchor, base_url) for anchor in cell.select("a[href]")],
        "images": [_image_record(image, base_url) for image in cell.select("img")],
    }


def _parse_table(table: Tag, base_url: str, index: int, heading: str | None) -> dict[str, Any]:
    rows = []
    for row_index, row in enumerate(table.select("tr")):
        cells = _direct_cells(row)
        if not cells:
            continue
        is_header = any(cell.name == "th" for cell in cells)
        classes = list(row.get("class") or [])
        class_tokens = {str(item).casefold() for item in classes}
        if any("subtotal" in item for item in class_tokens):
            row_role = "subtotal"
        elif any("total" in item for item in class_tokens):
            row_role = "total"
        else:
            row_role = "header" if is_header else "data"
        rows.append({
            "row_index": row_index,
            "kind": "header" if is_header else "data",
            "row_role": row_role,
            "classes": classes,
            "cells": [_cell_record(cell, base_url) for cell in cells],
        })
    first_header = next((row for row in rows if row["kind"] == "header"), None)
    column_count = None
    if first_header is not None:
        column_count = sum(
            max(1, int(cell.get("colspan") or 1))
            if str(cell.get("colspan") or "1").isdigit()
            else 1
            for cell in first_header["cells"]
        )
    if column_count is not None:
        for row in rows:
            logical_index = 0
            has_rowspan = False
            for cell in row["cells"]:
                raw_span = cell.get("colspan")
                span = max(1, int(raw_span)) if raw_span and str(raw_span).isdigit() else 1
                try:
                    has_rowspan = has_rowspan or int(cell.get("rowspan") or 1) > 1
                except (TypeError, ValueError):
                    pass
                cell["column_index"] = logical_index
                cell["column_span"] = span
                logical_index += span
            row["column_alignment"] = {
                "expected_column_count": column_count,
                "represented_column_count": logical_index,
                "missing_trailing_column_indexes": (
                    list(range(logical_index, column_count)) if logical_index < column_count else []
                ),
                "overflow_column_count": max(0, logical_index - column_count),
                "status": (
                    "ROWSPAN_CONTEXT_REQUIRED" if has_rowspan
                    else "MATCH" if logical_index == column_count
                    else "TRAILING_COLUMNS_OMITTED" if logical_index < column_count
                    else "OVERFLOW"
                ),
            }
    caption = table.find("caption")
    return {
        "table_index": index,
        "table_id": table.get("id"),
        "classes": list(table.get("class") or []),
        "caption": _clean_text(caption.get_text(" ", strip=True)) if caption else None,
        "section_heading": heading,
        "row_count": len(rows),
        "data_row_count": sum(row["kind"] == "data" for row in rows),
        "column_count": column_count,
        "header_cells": [cell.get("text", "") for cell in first_header["cells"]] if first_header else [],
        "header_rows": [row["row_index"] for row in rows if row["kind"] == "header"],
        "rows": rows,
    }


def _label_for(element: Tag) -> str | None:
    element_id = element.get("id")
    if element_id:
        label = element.find_parent().find("label", attrs={"for": element_id}) if element.find_parent() else None
        if isinstance(label, Tag):
            return _clean_text(label.get_text(" ", strip=True))
    parent = element.find_parent("label")
    if isinstance(parent, Tag):
        return _clean_text(parent.get_text(" ", strip=True))
    return element.get("aria-label") or element.get("title") or element.get("name") or element_id


def _control_inventory(roots: Iterable[Tag], base_url: str) -> dict[str, list[dict[str, Any]]]:
    selects: list[dict[str, Any]] = []
    checkboxes: list[dict[str, Any]] = []
    buttons: list[dict[str, Any]] = []
    tabs: list[dict[str, Any]] = []
    forms: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for root in roots:
        for select in root.select("select"):
            key = ("select", str(select.get("id") or select.get("name") or len(selects)))
            if key in seen:
                continue
            seen.add(key)
            selects.append({
                "id": select.get("id"),
                "name": select.get("name"),
                "label": _label_for(select),
                "multiple": select.has_attr("multiple"),
                "disabled": select.has_attr("disabled"),
                "options": [
                    {
                        "label": _clean_text(option.get_text(" ", strip=True)),
                        "value": option.get("value"),
                        "selected": option.has_attr("selected"),
                        "disabled": option.has_attr("disabled"),
                    }
                    for option in select.select("option")
                ],
            })
        for checkbox in root.select('input[type="checkbox"]'):
            key = ("checkbox", str(checkbox.get("id") or checkbox.get("name") or len(checkboxes)))
            if key in seen:
                continue
            seen.add(key)
            checkboxes.append({
                "id": checkbox.get("id"),
                "name": checkbox.get("name"),
                "label": _label_for(checkbox),
                "checked": checkbox.has_attr("checked"),
                "disabled": checkbox.has_attr("disabled"),
            })
        for button in root.select("button, input[type=button], input[type=submit], [role=button]"):
            buttons.append({
                "tag": button.name,
                "type": button.get("type"),
                "id": button.get("id"),
                "name": button.get("name"),
                "text": _clean_text(button.get_text(" ", strip=True)),
                "title": button.get("title"),
                "aria_label": button.get("aria-label"),
                "disabled": button.has_attr("disabled"),
            })
        for anchor in root.select('[role="tab"], .nav-tabs a, .nav-pills a, [data-toggle="tab"], [data-bs-toggle="tab"]'):
            tabs.append({
                **_link_record(anchor, base_url),
                "role": anchor.get("role"),
                "selected": anchor.get("aria-selected"),
                "classes": list(anchor.get("class") or []),
            })
        for form in root.select("form"):
            forms.append({
                "id": form.get("id"),
                "method": (form.get("method") or "get").lower(),
                "action": urljoin(base_url, str(form.get("action") or base_url)),
                "fields": [
                    {
                        "tag": field.name,
                        "type": field.get("type"),
                        "id": field.get("id"),
                        "name": field.get("name"),
                        "label": _label_for(field),
                    }
                    for field in form.select("input, select, textarea, button")
                ],
            })
    return {"selects": selects, "checkboxes": checkboxes, "buttons": buttons, "tabs": tabs, "forms": forms}


def _relation_for_url(url: str) -> tuple[str, str] | None:
    parts = urlsplit(url)
    for entity_type, pattern in _PERSON_PATH.items():
        match = pattern.fullmatch(parts.path)
        if match:
            return entity_type, match.group(1)
    if parts.path == "/es/p/p.php":
        match_id = parse_qs(parts.query).get("id", [None])[-1]
        if match_id and match_id.isdigit():
            return "match", match_id
    return None


def _relationships(
    tables: list[dict[str, Any]], roots: Iterable[Tag], base_url: str
) -> list[dict[str, Any]]:
    found: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_observation(
        key: tuple[str, str, str],
        relationship: dict[str, Any],
        observation: dict[str, Any],
    ) -> None:
        item = found.setdefault(key, {**relationship, "occurrences": []})
        if observation not in item["occurrences"]:
            item["occurrences"].append(observation)

    for table in tables:
        for row in table["rows"]:
            for column_index, cell in enumerate(row["cells"]):
                for link in cell["links"]:
                    url = link.get("url")
                    if not url:
                        continue
                    relationship = _relation_for_url(url)
                    if not relationship:
                        continue
                    entity_type, entity_id = relationship
                    key = (entity_type, entity_id, url)
                    add_observation(key, {
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "name": link.get("text"),
                        "url": url,
                        "source_table_id": table.get("table_id"),
                        "source_table_index": table["table_index"],
                        "source_row_index": row["row_index"],
                        "source_column_index": column_index,
                    }, {
                        "source_table_id": table.get("table_id"),
                        "source_table_index": table["table_index"],
                        "source_row_index": row["row_index"],
                        "source_column_index": column_index,
                    })
    for root_index, root in enumerate(roots):
        for anchor in root.select("a[href]"):
            if anchor.find_parent("table") is not None:
                continue
            link = _link_record(anchor, base_url)
            url = link.get("url")
            if not url:
                continue
            relationship = _relation_for_url(url)
            if not relationship:
                continue
            entity_type, entity_id = relationship
            key = (entity_type, entity_id, url)
            add_observation(key, {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "name": link.get("text"),
                "url": url,
                "source_table_id": None,
                "source_table_index": None,
                "source_row_index": None,
                "source_column_index": None,
                "source_root_index": root_index,
            }, {
                "source_table_id": None,
                "source_table_index": None,
                "source_row_index": None,
                "source_column_index": None,
                "source_root_index": root_index,
            })
    return list(found.values())


def _page_headings(roots: Iterable[Tag]) -> list[dict[str, Any]]:
    result = []
    for root_index, root in enumerate(roots):
        for heading in root.select("h1, h2, h3, h4, h5, h6"):
            text = _clean_text(heading.get_text(" ", strip=True))
            if text:
                result.append({"level": heading.name, "text": text, "root_index": root_index})
    return result


def _media_and_graphics(roots: Iterable[Tag], base_url: str) -> dict[str, list[dict[str, Any]]]:
    images: list[dict[str, Any]] = []
    graphics: list[dict[str, Any]] = []
    galleries: list[dict[str, Any]] = []
    for root_index, root in enumerate(roots):
        for image in root.select("img"):
            images.append({**_image_record(image, base_url), "root_index": root_index})
        for node in root.select("svg, canvas, [data-highcharts-chart], [class*=chart], [id*=chart], [class*=graph], [id*=graph]"):
            attrs = {
                key: value for key, value in node.attrs.items()
                if key in {"id", "class", "role", "aria-label", "aria-labelledby", "data-highcharts-chart", "width", "height"}
            }
            label_nodes = node.select("title, desc, text")[:80] if node.name == "svg" else []
            graphics.append({
                "tag": node.name,
                "attributes": attrs,
                "text": _clean_text(node.get_text(" ", strip=True))[:2000],
                "labels": [_clean_text(label.get_text(" ", strip=True)) for label in label_nodes],
                "looks_like_chart": bool(_CHART_SELECTOR.search(" ".join(map(str, node.get("class") or [])) + " " + str(node.get("id") or ""))) or node.name in {"canvas", "svg"},
                "root_index": root_index,
            })
        for node in root.select(".carousel, .swiper, .splide, [class*=gallery], [id*=gallery], [data-fancybox], [data-lightbox], [data-gallery]"):
            galleries.append({
                "tag": node.name,
                "id": node.get("id"),
                "classes": list(node.get("class") or []),
                "image_count": len(node.select("img")),
                "text": _clean_text(node.get_text(" ", strip=True))[:240],
            })
    return {"images": images, "graphics": graphics, "galleries": galleries}


def _primary_member_table(page: dict[str, str], tables: list[dict[str, Any]]) -> dict[str, Any] | None:
    if page["view"] == "team_roster":
        expected_id = "c3p1"
    elif page["view"] == "team_alignment":
        expected_id = "taulaplantilla"
    else:
        return None
    return next((table for table in tables if table.get("table_id") == expected_id), None)


def _person_id(cell: dict[str, Any], person_type: str) -> tuple[str, str] | None:
    for link in cell.get("links", []):
        url = link.get("url")
        if not url:
            continue
        relation = _relation_for_url(url)
        if relation and relation[0] == person_type:
            return relation[1], url
    return None


def _header_cells(table: dict[str, Any]) -> list[str]:
    for row in table.get("rows", []):
        if row.get("kind") == "header":
            return [cell.get("text", "") for cell in row.get("cells", [])]
    return []


def _stat_index(table: dict[str, Any] | None, aliases: set[str]) -> int | None:
    if table is None:
        return None
    for index, header in enumerate(_header_cells(table)):
        if _clean_text(header).casefold() in aliases:
            return index
    return None


def _number(raw: str | None) -> int | None:
    if raw is None:
        return None
    value = _clean_text(raw).replace(".", "").replace(",", "")
    return int(value) if value.isdigit() else None


def _expanded_cell_values(cells: list[dict[str, Any]], width: int) -> list[str | None]:
    """Expand colspan cells into the table's header positions without losing raw data."""
    expanded: list[str | None] = []
    for cell in cells:
        try:
            span = max(1, int(cell.get("colspan") or 1))
        except (TypeError, ValueError):
            span = 1
        value = cell.get("text") or None
        expanded.append(value)
        expanded.extend([None] * (span - 1))
    return (expanded + [None] * width)[:width]


def _team_records(page: dict[str, str], tables: list[dict[str, Any]]) -> dict[str, Any]:
    if page["view"] == "team_statistics":
        table = next((item for item in tables if item.get("table_id") == "c3p0"), None)
        if table is None:
            return {
                "roster_table_id": None, "roster_rows": [], "coach_rows": [],
                "player_statistics": [], "statistics_totals": [], "statistics_unparsed_rows": [],
                "diagnostics": ["No se encontró la tabla c3p0 de estadísticas individuales."],
            }
        appearances_index = _stat_index(table, {"pj", "partidos jugados"})
        headers = _header_cells(table)
        statistics = []
        totals = []
        unparsed_rows = []
        for row in table["rows"]:
            if row["kind"] != "data":
                continue
            person = next(
                (found for cell in row["cells"] if (found := _person_id(cell, "player"))),
                None,
            )
            if person is None and "total" in row.get("classes", []):
                expanded_values = _expanded_cell_values(row["cells"], len(headers))
                totals.append({
                    "team_season_id": page["entity_id"],
                    "source_row_index": row["row_index"],
                    "headers": headers,
                    "values": expanded_values,
                    "values_by_column": [
                        {
                            "column_index": index,
                            "header": header or f"column_{index + 1}",
                            "value": expanded_values[index],
                        }
                        for index, header in enumerate(headers)
                    ],
                    "raw_cells": row["cells"],
                })
                continue
            if person is None:
                unparsed_rows.append({
                    "source_row_index": row["row_index"],
                    "classes": row.get("classes", []),
                    "raw_cells": row["cells"],
                })
                continue
            appearances = None
            if appearances_index is not None and appearances_index < len(row["cells"]):
                appearances = _number(row["cells"][appearances_index].get("text"))
            statistics.append({
                "team_season_id": page["entity_id"],
                "player_id": person[0],
                "player_url": person[1],
                "appearances": appearances,
                "zero_appearances": appearances == 0 if appearances is not None else None,
                "source_row_index": row["row_index"],
                "raw_cells": row["cells"],
            })
        return {
            "roster_table_id": None, "roster_rows": [], "coach_rows": [],
            "player_statistics": statistics,
            "statistics_totals": totals,
            "statistics_unparsed_rows": unparsed_rows,
            "diagnostics": ([
                f"{len(unparsed_rows)} fila(s) de estadísticas sin jugador ni clase de total reconocible."
            ] if unparsed_rows else []),
        }

    table = _primary_member_table(page, tables)
    if table is None:
        return {
            "roster_table_id": None, "roster_rows": [], "coach_rows": [],
            "player_statistics": [], "statistics_totals": [], "statistics_unparsed_rows": [],
            "diagnostics": [],
        }
    headers = _header_cells(table)
    player_index = next((i for i, value in enumerate(headers) if "apodo" in value.casefold() or "nombre" in value.casefold()), None)
    statistics_table = next((item for item in tables if item.get("table_id") == "c3p0"), None)
    if statistics_table is None:
        statistics_table = next((item for item in tables if item.get("table_id") == "taulaplantilla"), None)
    appearances_index = _stat_index(statistics_table, {"pj", "partidos jugados"})
    stats_by_player: dict[str, list[dict[str, Any]]] = {}
    if statistics_table:
        for row in statistics_table["rows"]:
            for cell in row["cells"]:
                person = _person_id(cell, "player")
                if person:
                    stats_by_player.setdefault(person[0], row["cells"])
                    break

    roster = []
    for row in table["rows"]:
        if row["kind"] != "data":
            continue
        person: tuple[str, str] | None = None
        for cell in row["cells"]:
            person = _person_id(cell, "player")
            if person:
                break
        if person is None:
            continue
        cells = row["cells"]
        stats_cells = stats_by_player.get(person[0])
        appearances = None
        if stats_cells is not None and appearances_index is not None and appearances_index < len(stats_cells):
            appearances = _number(stats_cells[appearances_index].get("text"))
        name = cells[player_index].get("text") if player_index is not None and player_index < len(cells) else None
        roster.append({
            "team_season_id": page["entity_id"],
            "player_id": person[0],
            "player_url": person[1],
            "name_raw": name,
            "shirt_number_raw": cells[0].get("text") if cells else None,
            "birth_date_raw": cells[4].get("text") if len(cells) > 4 else None,
            "birth_place_raw": cells[5].get("text") if len(cells) > 5 else None,
            "birth_province_raw": cells[6].get("text") if len(cells) > 6 else None,
            "position_raw": cells[7].get("text") if len(cells) > 7 else None,
            "statistics_present": stats_cells is not None,
            "appearances": appearances,
            "zero_appearances": appearances == 0 if appearances is not None else None,
            "source_row_index": row["row_index"],
            "raw_cells": cells,
            "statistics_cells": stats_cells,
        })

    coach_table = next((item for item in tables if item.get("table_id") == "taulaentrenadors"), None)
    coaches = []
    if coach_table:
        for row in coach_table["rows"]:
            if row["kind"] != "data":
                continue
            for cell in row["cells"]:
                coach = _person_id(cell, "coach")
                if coach:
                    coaches.append({
                        "team_season_id": page["entity_id"],
                        "coach_id": coach[0],
                        "coach_url": coach[1],
                        "name_raw": cell.get("text"),
                        "source_row_index": row["row_index"],
                        "raw_cells": row["cells"],
                    })
                    break
    diagnostics = []
    if player_index is None:
        diagnostics.append("No se identificó la columna de nombre de jugador por encabezado.")
    if len({item["player_id"] for item in roster}) != len(roster):
        diagnostics.append("Hay IDs de jugador duplicados en la vista de plantilla.")
    return {
        "roster_table_id": table.get("table_id"),
        "roster_rows": roster,
        "coach_rows": coaches,
        "player_statistics": [],
        "statistics_totals": [],
        "statistics_unparsed_rows": [],
        "diagnostics": diagnostics,
    }


def parse_club_team_html(
    html: str,
    url: str,
    *,
    source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse one validated raw page offline, retaining page-content tables verbatim."""
    page = classify_club_team_url(url)
    if page is None:
        raise InvalidClubTeamPage(f"URL fuera de las familias club/equipo-temporada: {url}")
    if not html or not html.strip():
        raise InvalidClubTeamPage("HTML vacío")
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:  # BeautifulSoup usually repairs malformed HTML itself.
        raise InvalidClubTeamPage(f"No se pudo parsear el HTML: {type(exc).__name__}") from exc
    if soup.html is None:
        raise InvalidClubTeamPage("El documento no contiene un elemento html reconocible")

    roots = _content_roots(soup)
    tables: list[dict[str, Any]] = []
    for root in roots:
        heading: str | None = None
        for element in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "table"]):
            if element.name != "table":
                text = _clean_text(element.get_text(" ", strip=True))
                if text:
                    heading = text
            else:
                tables.append(_parse_table(element, url, len(tables), heading))

    controls = _control_inventory(roots, url)
    media = _media_and_graphics(roots, url)
    relations = _relationships(tables, roots, url)
    title = _clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    headings = _page_headings(roots)
    body = soup.find("div", id="body")
    hero = body.find("div", class_="hero") if isinstance(body, Tag) else None
    hero_text = _clean_text(hero.get_text(" ", strip=True)) if isinstance(hero, Tag) else None
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        **page,
        "url": url,
        "title": title,
        "hero_text": hero_text,
        "headings": headings,
        "tables": tables,
        "controls": controls,
        **media,
        "relationships": relations,
        "structure": {
            "content_roots": len(roots),
            "content_tables": len(tables),
            "table_rows": sum(table["row_count"] for table in tables),
            "data_rows": sum(table["data_row_count"] for table in tables),
            "images": len(media["images"]),
            "graphics_candidates": len(media["graphics"]),
            "gallery_candidates": len(media["galleries"]),
        },
        "diagnostics": [],
    }
    if source_metadata:
        result["source"] = {
            "access_status": source_metadata.get("access_status"),
            "http_status": source_metadata.get("http_status"),
            "requested_url": source_metadata.get("requested_url"),
            "final_url": source_metadata.get("final_url"),
            "captured_at_utc": source_metadata.get("captured_at_utc"),
            "rendered_html_sha256": source_metadata.get("rendered_html_sha256"),
            "rendered_html_bytes": source_metadata.get("rendered_html_bytes"),
        }
    if page["entity_type"] == "team_season":
        team_records = _team_records(page, tables)
        result["team_data"] = team_records
        club_relations = [r for r in relations if r["entity_type"] == "club"]
        result["club_id"] = club_relations[0]["entity_id"] if len(club_relations) == 1 else None
        if len(club_relations) > 1:
            result["diagnostics"].append("Más de un club permanente enlazado desde la vista de equipo-temporada.")
        result["diagnostics"].extend(team_records["diagnostics"])
    if not headings and not tables:
        result["diagnostics"].append("No se encontraron encabezados ni tablas en el contenido principal.")
    return result


def expected_views_for_team() -> tuple[str, ...]:
    """All six team-season page variants found during discovery."""
    return (
        "team_alignment", "team_roster", "team_statistics", "team_tracking",
        "team_transfers", "team_matches",
    )


def expected_views_for_club() -> tuple[str, ...]:
    """All six linked club page variants found during discovery."""
    return (
        "club_profile", "club_statistics", "club_players", "club_coaches",
        "club_matches", "club_rivals",
    )
