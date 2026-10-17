"""Deterministic, offline parsers for captured BDFutbol player pages."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

PLAYER_PARSER_VERSION = "1.1.0"
PLAYER_SCHEMA_VERSION = "football_data_hub.bdfutbol.player_pages.v2"
PLAYER_VIEWS = ("profile", "statistics", "matches", "rivals")
_PLAYER_URL = re.compile(r"/es/(?:j/j|p/jr?|p/j)(\d+)\.html$")
_PLAYER_ID = re.compile(r"(?:^|/)j(\d+)\.html$")
_TEAM_SEASON_ID = re.compile(r"(?:^|/)(t[^/]+)\.html$")
_INTEGER = re.compile(r"^-?\d+$")
_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_SEASON = re.compile(r"^\d{4}-\d{2}$")
_SCORE = re.compile(r"^(\d+)\s+(\d+)$")
_WINDOW_P_ASSIGNMENT = re.compile(r"(?<![\w$])(?:window\.)?P\s*=\s*")
_WINDOW_P_FIELD_NAMES = (
    "t", "cat", "jor1", "dat", "loc", "e1", "gc", "gf", "id",
    "pt", "pc", "ps", "min", "pv", "tg1", "tg2", "tv", "tg",
    "e2", "ce1", "ce2", "gp", "genc", "px", "jor2", "jor", "nomtemp",
)
_SOUP_BACKEND = "lxml" if importlib.util.find_spec("lxml") else "html.parser"


class PlayerSnapshotError(ValueError):
    """Raised when a raw player snapshot is incomplete or not a player view."""


def soup_from_html(html: str) -> BeautifulSoup:
    """Build a DOM with the fast optional lxml backend, with stdlib fallback."""
    return BeautifulSoup(html, _SOUP_BACKEND)


def classify_player_view(url: str) -> tuple[str, str]:
    """Return the source player ID and one of the four supported page views."""
    parts = urlsplit(url)
    match = _PLAYER_URL.search(parts.path)
    if match is None:
        raise PlayerSnapshotError(f"La URL no identifica una vista de jugador: {url}")
    player_id = f"j{match.group(1)}"
    if parts.path.startswith("/es/p/jr"):
        return player_id, "rivals"
    if parts.path.startswith("/es/p/j"):
        return player_id, "matches"
    query = dict(pair.split("=", 1) for pair in parts.query.split("&") if "=" in pair)
    if query.get("p") == "stats":
        return player_id, "statistics"
    return player_id, "profile"


def _is_base_view_url(url: str, view: str) -> bool:
    """Recognize the canonical unfiltered route for each player view."""
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    if view == "statistics":
        return query == {"p": ["stats"]}
    return not query


def _text(node: Tag | None) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _integer(raw: str | None) -> int | None:
    value = (raw or "").strip()
    return int(value) if _INTEGER.fullmatch(value) else None


def _integer_value(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return _integer(str(value)) if isinstance(value, str) else None


def _window_p_values(soup: BeautifulSoup) -> tuple[str, list[list[Any]]]:
    """Parse the serialized player-match array only when its shape is verified."""
    assignments = 0
    arrays: list[list[list[Any]]] = []
    decoder = json.JSONDecoder()
    for script in soup.find_all("script"):
        source = script.string or script.get_text()
        if not source:
            continue
        for match in _WINDOW_P_ASSIGNMENT.finditer(source):
            assignments += 1
            try:
                value, _ = decoder.raw_decode(source[match.end():])
            except json.JSONDecodeError:
                continue
            if isinstance(value, list) and all(isinstance(row, list) for row in value):
                arrays.append(value)
    if assignments > 1 or len(arrays) > 1:
        return "AMBIGUOUS_ASSIGNMENTS", []
    if not arrays:
        return ("UNINTERPRETED_ASSIGNMENT" if assignments else "NOT_PRESENT", [])
    values = arrays[0]
    if any(len(row) != len(_WINDOW_P_FIELD_NAMES) for row in values):
        return "UNSUPPORTED_TUPLE_WIDTH", []
    return ("PARSED_27_FIELD_TUPLES" if values else "PRESENT_EMPTY", values)


def _cell_value_status(raw: str) -> str:
    if raw.strip() in {"", "-", "—", "–"}:
        return "MISSING_OR_PLACEHOLDER"
    if _integer(raw) is not None:
        return "INTEGER_NORMALIZED"
    return "RAW_ONLY"


def _source(metadata: dict[str, Any], snapshot_directory: str | None, html: str) -> dict[str, Any]:
    html_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
    expected_hash = metadata.get("html_sha256") or metadata.get("rendered_html_sha256")
    return {
        "requested_url": metadata.get("requested_url"),
        "final_url": metadata.get("final_url") or metadata.get("requested_url"),
        "captured_at_utc": metadata.get("captured_at_utc"),
        "access_status": metadata.get("access_status"),
        "http_status": metadata.get("http_status"),
        "snapshot_kind": metadata.get("snapshot_kind", "BASE_VIEW"),
        "is_base_view_snapshot": metadata.get("is_base_view_snapshot"),
        "filter_parameters": metadata.get("filter_parameters", {}),
        "interaction_requests": metadata.get("interaction_requests", []),
        "base_snapshot_directory": metadata.get("base_snapshot_directory"),
        "base_snapshot_sha256": metadata.get("base_snapshot_sha256"),
        "snapshot_directory": snapshot_directory,
        "rendered_html_sha256": html_hash,
        "metadata_sha256_matches": (
            html_hash == expected_hash
            if expected_hash
            else None
        ),
    }


def _links(cell: Tag, base_url: str) -> list[dict[str, str | None]]:
    result = []
    for anchor in cell.find_all("a"):
        href = anchor.get("href")
        result.append({
            "text_raw": _text(anchor),
            "href_raw": href,
            "url": urljoin(base_url, href) if href and not href.startswith("#") else None,
        })
    return result


def _cell_record(cell: Tag, column_index: int, base_url: str) -> dict[str, Any]:
    raw = _text(cell)
    style = cell.get("style")
    classes = list(cell.get("class", []))
    inline_hidden = bool(style and re.search(r"display\s*:\s*none", style, re.I))
    marker_labels: list[str] = []
    if {"colTrofeu", "colComps"}.intersection(classes) or cell.select_one(".punt_comp"):
        for marker in cell.select("[title], [alt], .punt_comp"):
            label = str(marker.get("title") or marker.get("alt") or _text(marker)).strip()
            if label and label not in marker_labels:
                marker_labels.append(label)
    return {
        "column_index": column_index,
        "tag": cell.name,
        "raw_value": raw,
        "data_colid_raw": cell.get("data-colid"),
        "normalized_integer": _integer(raw),
        "value_status": _cell_value_status(raw),
        "title_raw": cell.get("title"),
        "classes_raw": classes,
        "style_raw": style,
        "hidden_by_inline_style": inline_hidden,
        "responsive_optional": "resp_off" in classes,
        "marker_labels_raw": marker_labels,
        "colspan": int(cell.get("colspan", 1) or 1),
        "rowspan": int(cell.get("rowspan", 1) or 1),
        "links": _links(cell, base_url),
    }


def _row_cells(row: Tag, base_url: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    column_index = 0
    for cell in row.find_all(["th", "td"], recursive=False):
        item = _cell_record(cell, column_index, base_url)
        result.append(item)
        column_index += item["colspan"]
    return result


def _row_role(row: Tag, cells: list[dict[str, Any]], max_width: int) -> str:
    if any(cell.name == "th" for cell in row.find_all(["th", "td"], recursive=False)):
        return "header"
    classes = set(row.get("class", []))
    values = [str(cell["raw_value"]) for cell in cells]
    first_nonempty = next((value.strip() for value in values if value.strip()), "")
    if (
        "total" in classes
        or re.match(r"^total(?:es)?(?:\s|$)", first_nonempty, re.I)
    ):
        return "total"
    if not first_nonempty and not any(values):
        return "blank"
    visible = sum(bool(value.strip()) for value in values)
    if visible == 1 and len(cells) < max_width:
        return "section"
    return "data"


def _header_group_labels(header_rows: list[dict[str, Any]], width: int) -> list[str | None]:
    groups: list[str | None] = [None] * width
    if len(header_rows) < 2:
        return groups
    group_row = header_rows[0]
    for cell in group_row["cells"]:
        label = cell["raw_value"].strip() or None
        start = cell["column_index"]
        for col in range(start, min(width, start + cell["colspan"])):
            groups[col] = label
    return groups


def _table_record(
    table: Tag,
    *,
    table_index: int,
    table_role: str,
    base_url: str,
) -> dict[str, Any]:
    dom_rows = [row for row in table.find_all("tr") if row.find_parent("table") is table]
    raw_rows = [_row_cells(row, base_url) for row in dom_rows]
    width = max((
        max((cell["column_index"] + cell["colspan"] for cell in cells), default=0)
        for cells in raw_rows
    ), default=0)
    rows: list[dict[str, Any]] = []
    signatures: dict[tuple[str, ...], int] = {}
    for index, (dom_row, cells) in enumerate(zip(dom_rows, raw_rows, strict=True)):
        role = _row_role(dom_row, cells, width)
        signature = tuple(str(cell["raw_value"]) for cell in cells)
        duplicate_of = signatures.get(signature) if role == "data" else None
        if role == "data" and duplicate_of is None:
            signatures[signature] = index
        rows.append({
            "row_index": index,
            "row_role": role,
            "classes_raw": list(dom_row.get("class", [])),
            "cell_count": len(cells),
            "expanded_column_width": sum(cell["colspan"] for cell in cells),
            "duplicate_of_row_index": duplicate_of,
            "cells": cells,
        })

    header_rows = [row for row in rows if row["row_role"] == "header"]
    leaf_header = header_rows[-1] if header_rows else None
    column_headers: list[dict[str, Any]] = []
    if leaf_header is not None:
        group_labels = _header_group_labels(header_rows, width)
        for cell in leaf_header["cells"]:
            for offset in range(cell["colspan"]):
                column_index = cell["column_index"] + offset
                column_headers.append({
                    "column_index": column_index,
                    "header_original": cell["raw_value"],
                    "header_title_raw": cell["title_raw"],
                    "data_colid_raw": cell.get("data_colid_raw"),
                    "group_header_raw": group_labels[column_index] if column_index < width else None,
                    "classes_raw": cell["classes_raw"],
                    "hidden_by_inline_style": cell["hidden_by_inline_style"],
                    "responsive_optional": cell["responsive_optional"],
                    "column_interpretation_status": (
                        "SOURCE_TITLE_AVAILABLE" if cell["title_raw"] else "PENDING_INTERPRETATION"
                    ),
                })

    return {
        "table_index": table_index,
        "table_id": table.get("id"),
        "table_role": table_role,
        "classes_raw": list(table.get("class", [])),
        "caption_raw": _text(table.caption) if table.caption else None,
        "row_count": len(rows),
        "column_width_max": width,
        "header_rows": [row["row_index"] for row in header_rows],
        "column_headers": column_headers,
        "rows": rows,
        "data_row_count": sum(row["row_role"] == "data" for row in rows),
        "total_row_count": sum(row["row_role"] == "total" for row in rows),
        "section_row_count": sum(row["row_role"] == "section" for row in rows),
    }


def _cells_with_headers(row: dict[str, Any], table: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep the source's actual leaf and grouped headers beside each data cell."""
    headers = {
        int(header["column_index"]): header
        for header in table.get("column_headers", [])
        if isinstance(header, dict) and type(header.get("column_index")) is int
    }
    result = []
    for source_cell in row.get("cells", []):
        if not isinstance(source_cell, dict):
            continue
        cell = dict(source_cell)
        header = headers.get(cell.get("column_index"), {})
        cell.update({
            "header_original": header.get("header_original"),
            "header_title_raw": header.get("header_title_raw"),
            "group_header_raw": header.get("group_header_raw"),
            "header_classes_raw": header.get("classes_raw", []),
            "header_data_colid_raw": header.get("data_colid_raw"),
            "header_hidden_by_inline_style": header.get("hidden_by_inline_style"),
        })
        result.append(cell)
    return result


def _window_p_match_statistics(
    record: dict[str, Any], fixture_table: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Label per-match P values only where the same captured DOM exposes a meaning."""
    if fixture_table is None:
        return []
    headers = {
        str(header.get("data_colid_raw")): header
        for header in fixture_table.get("column_headers", [])
        if isinstance(header, dict) and header.get("data_colid_raw")
    }
    metrics = record.get("player_match_metrics_raw")
    if not isinstance(metrics, dict):
        return []
    # These P fields were matched by match_id against the captured #tpartits
    # headings in the saved base and filtered views. Unmatched P tuple fields
    # remain in the raw compact record and are deliberately not relabeled here.
    field_columns = (
        ("pt", "pt"), ("pc", "pc"), ("ps", "ps"), ("px", "px"),
        ("pv", "pv"), ("min", "mins"), ("tg1", "tg1"),
        ("tv", "tv"), ("tg", "gols"), ("genc", "genc"),
    )
    result = []
    for field, colid in field_columns:
        header = headers.get(colid)
        if not header:
            continue
        label = str(header.get("header_title_raw") or header.get("header_original") or "").strip()
        if not label:
            continue
        value = metrics.get(field)
        normalized = value if type(value) is int else _integer(str(value)) if isinstance(value, str) else None
        result.append({
            "label_raw": label,
            "source_colid": colid,
            "raw_value": value,
            "normalized_integer": normalized,
        })
    return result


_TABLE_ROLES: dict[str, dict[str, str]] = {
    "profile": {".traject": "career_trajectory"},
    "statistics": {
        "#table-estadistiques-competicions": "statistics_by_competition",
        "#table-estadistiques-equips": "statistics_by_team",
        ".taula-fites-jugador": "milestone_matches",
    },
    "matches": {
        "#t2": "match_summary_by_competition",
        "#t1": "match_summary_by_season",
        "#t55": "match_summary_by_team",
        "#t5": "match_summary_by_opponent",
        "#tpartits": "individual_match_fixtures",
    },
    "rivals": {
        "#t5": "opponent_player_statistics",
        "#t6": "opponent_coach_statistics",
        "#t7": "opponent_team_statistics",
    },
}

_FILTER_IDS: dict[str, tuple[str, ...]] = {
    "profile": ("sel-equip", "sel-pais"),
    "statistics": ("cats_milestones",),
    "matches": ("jug", "pgep", "rival", "temp", "equip", "comp"),
    "rivals": ("filtre-cat", "filtre-temp", "filtre-dem"),
}

_REQUIRED_TABLE_ROLES: dict[str, tuple[str, ...]] = {
    "profile": ("career_trajectory",),
    "statistics": ("statistics_by_competition", "statistics_by_team"),
    "matches": (
        "match_summary_by_competition", "match_summary_by_season",
        "match_summary_by_team", "match_summary_by_opponent",
    ),
    "rivals": (
        "opponent_player_statistics", "opponent_coach_statistics",
        "opponent_team_statistics",
    ),
}


def _view_tables(soup: BeautifulSoup, view: str, base_url: str) -> list[dict[str, Any]]:
    roles = _TABLE_ROLES[view]
    selected: list[tuple[Tag, str]] = []
    if view == "statistics":
        for selector, role in roles.items():
            selected.extend((table, role) for table in soup.select(selector))
    else:
        for selector, role in roles.items():
            selected.extend((table, role) for table in soup.select(selector))

    seen: set[int] = set()
    indexed: list[tuple[int, Tag, str]] = []
    for table, role in selected:
        identity = id(table)
        if identity in seen:
            continue
        seen.add(identity)
        all_tables = soup.find_all("table")
        indexed.append((all_tables.index(table), table, role))

    # Include additional sport tables from later DOM revisions, while excluding
    # the many global season-navigation matrices captured in the same HTML.
    for index, table in enumerate(soup.find_all("table")):
        if id(table) in seen or "taula_estil" not in table.get("class", []):
            continue
        classes = set(table.get("class", []))
        if {"d-none", "d-md-block"}.issubset(classes):
            continue
        if not table.find_all("tr"):
            continue
        indexed.append((index, table, "additional_sports_table"))

    records = []
    for index, table, role in sorted(indexed, key=lambda item: item[0]):
        record = _table_record(table, table_index=index, table_role=role, base_url=base_url)
        if role == "milestone_matches":
            heading = table.find_previous_sibling("h4")
            if isinstance(heading, Tag):
                record["caption_raw"] = _text(heading)
        records.append(record)
    return records


def _find_profile_value(soup: BeautifulSoup, label: str) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for text_node in soup.find_all(string=lambda value: value and value.strip() == label):
        label_node = text_node.parent
        wrapper = label_node.parent
        if not isinstance(wrapper, Tag):
            continue
        direct_divs = wrapper.find_all("div", recursive=False)
        if len(direct_divs) < 2 or _text(direct_divs[0]) != label:
            continue
        if "float-left" not in wrapper.get("class", []):
            continue
        value_node = direct_divs[1]
        classes = set(value_node.get("class", []))
        if label != "Demarcación" and "font-weight-bold" not in classes:
            continue
        candidates.append({
            "label_original": label,
            "raw_value": _text(value_node),
            "links": _links(value_node, soup.base.get("href") if soup.base else "https://www.bdfutbol.com/es/"),
            "source_classes": list(wrapper.get("class", [])),
        })
    return candidates[0] if candidates else None


def missing_profile_field_evidence(html: str) -> tuple[str, ...]:
    """Return required personal fields not found by the profile parser's DOM rules.

    BeautifulSoup reads text nodes in the captured DOM, including responsive
    elements hidden from ``innerText`` at a particular viewport. Field
    recognition deliberately reuses ``_find_profile_value`` so acquisition
    validation and offline parsing accept the same labeled structures.
    """
    soup = soup_from_html(html)
    return tuple(
        label for label in ("Nombre completo", "Demarcación")
        if not (field := _find_profile_value(soup, label))
        or not str(field.get("raw_value") or "").strip()
    )


def _profile_data(soup: BeautifulSoup, tables: list[dict[str, Any]], base_url: str) -> dict[str, Any]:
    title = _text(soup.title)
    h1 = _text(soup.find("h1"))
    labels = (
        "Nombre completo", "Fecha de nacimiento", "Lugar de nacimiento",
        "País de nacimiento", "Demarcación", "Altura", "Peso", "Nacionalidad",
    )
    fields = {label: _find_profile_value(soup, label) for label in labels}
    full_name = fields["Nombre completo"]
    birth_date = fields["Fecha de nacimiento"]
    birth_raw = birth_date.get("raw_value", "") if birth_date else ""
    date_match = _DATE.match(birth_raw[:10])
    birth_iso = (
        f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
        if date_match else None
    )
    age_match = re.search(r"\((\d+)\s+año", birth_raw)
    height = fields["Altura"].get("raw_value", "") if fields["Altura"] else ""
    height_match = re.search(r"(\d+)\s*cm\b", height, re.I)
    trajectory_table = next((table for table in tables if table["table_role"] == "career_trajectory"), None)
    trajectories: list[dict[str, Any]] = []
    total_rows: list[dict[str, Any]] = []
    if trajectory_table:
        headers = trajectory_table["column_headers"]
        header_by_index = {item["column_index"]: item for item in headers}
        for row in trajectory_table["rows"]:
            if row["row_role"] == "total":
                total_rows.append({
                    **row,
                    "table_id": trajectory_table.get("table_id"),
                    "table_role": "career_totals",
                    "source_table_index": trajectory_table.get("table_index"),
                    "table_caption_raw": trajectory_table.get("caption_raw"),
                    "cells": _cells_with_headers(row, trajectory_table),
                })
                continue
            values = {cell["column_index"]: cell for cell in row["cells"]}
            season = values.get(0, {}).get("raw_value", "")
            if row["row_role"] != "data" or not _SEASON.match(season):
                continue
            team_cell = values.get(1, {})
            team_link = next((link for link in team_cell.get("links", []) if link.get("href_raw")), None)
            team_url = team_link.get("url") if team_link else None
            team_season_match = _TEAM_SEASON_ID.search(urlsplit(team_url).path) if team_url else None
            trajectories.append({
                "table_id": trajectory_table.get("table_id"),
                "table_role": "career_trajectory",
                "source_table_index": trajectory_table.get("table_index"),
                "table_caption_raw": trajectory_table.get("caption_raw"),
                "season_raw": season,
                "team_name_raw": team_cell.get("raw_value"),
                "team_season_url": team_url,
                "team_season_reference": team_season_match.group(1) if team_season_match else None,
                "country_raw": values.get(2, {}).get("raw_value"),
                "division_raw": values.get(4, {}).get("raw_value"),
                "age_raw": values.get(5, {}).get("raw_value"),
                "age_integer": _integer(values.get(5, {}).get("raw_value")),
                "team_achievements_raw": values.get(3, {}).get("marker_labels_raw", []),
                "competition_participations_raw": values.get(25, {}).get("marker_labels_raw", []),
                "columns": [
                    {
                        "column_index": index,
                        "header_original": header_by_index.get(index, {}).get("header_original"),
                        "header_title_raw": header_by_index.get(index, {}).get("header_title_raw"),
                        "group_header_raw": header_by_index.get(index, {}).get("group_header_raw"),
                        "classes_raw": header_by_index.get(index, {}).get("classes_raw", []),
                        "marker_labels_raw": values.get(index, {}).get("marker_labels_raw", []),
                        "raw_value": values.get(index, {}).get("raw_value"),
                        "normalized_integer": values.get(index, {}).get("normalized_integer"),
                        "value_status": values.get(index, {}).get("value_status", "CELL_NOT_PRESENT"),
                        "hidden_by_inline_style": header_by_index.get(index, {}).get("hidden_by_inline_style"),
                    }
                    for index in range(trajectory_table["column_width_max"])
                ],
                "source_row_index": row["row_index"],
                "row_duplicate_of": row.get("duplicate_of_row_index"),
            })

    image_references: list[dict[str, Any]] = []
    profile_heading = soup.find("h1")
    ancestor = profile_heading
    for _ in range(4):
        if isinstance(ancestor, Tag) and ancestor.parent:
            ancestor = ancestor.parent
    if isinstance(ancestor, Tag):
        for image in ancestor.find_all("img"):
            src = image.get("src") or image.get("data-src")
            if not src or image.get("class") and "img-hero" in image.get("class", []):
                continue
            image_references.append({
                "src_raw": src,
                "url": urljoin(base_url, src),
                "alt_raw": image.get("alt"),
                "classes_raw": list(image.get("class", [])),
                "downloaded": False,
            })

    normalized_status = {
        label: "NORMALIZED_FROM_LABEL_VALUE" if value else "NOT_FOUND_IN_CAPTURED_SNAPSHOT"
        for label, value in fields.items()
    }
    return {
        "display_name_raw": h1 or None,
        "page_title_raw": title or None,
        "personal_fields": fields,
        "personal_field_status": normalized_status,
        "full_name_raw": full_name.get("raw_value") if full_name else None,
        "birth_date_raw": birth_raw or None,
        "birth_date_iso": birth_iso,
        "age_as_displayed_years": int(age_match.group(1)) if age_match else None,
        "birth_place_raw": fields["Lugar de nacimiento"].get("raw_value") if fields["Lugar de nacimiento"] else None,
        "country_of_birth_raw": fields["País de nacimiento"].get("raw_value") if fields["País de nacimiento"] else None,
        "nationality_raw": fields["Nacionalidad"].get("raw_value") if fields["Nacionalidad"] else None,
        "position_raw": fields["Demarcación"].get("raw_value") if fields["Demarcación"] else None,
        "height_raw": height or None,
        "height_cm": int(height_match.group(1)) if height_match else None,
        "weight_raw": fields["Peso"].get("raw_value") if fields["Peso"] else None,
        "photo_references": image_references,
        "career_rows": trajectories,
        "career_totals_raw": total_rows,
        "career_rows_observed": len(trajectories),
        "career_completeness": "NOT_CERTIFIED_COMPLETE",
    }


def _controls(soup: BeautifulSoup, view: str) -> list[dict[str, Any]]:
    result = []
    wanted = set(_FILTER_IDS[view])
    for control in soup.find_all(["select", "input", "button"]):
        control_id = control.get("id")
        name = control.get("name")
        if control_id not in wanted and name not in {"dem", "pais"}:
            continue
        if control.name == "select":
            options = [
                {
                    "value_raw": option.get("value"),
                    "label_raw": _text(option),
                    "selected": option.has_attr("selected"),
                }
                for option in control.find_all("option")
            ]
        else:
            options = []
        form = control.find_parent("form")
        result.append({
            "tag": control.name,
            "id": control_id,
            "name": name,
            "type": control.get("type"),
            "value_raw": control.get("value"),
            "label_raw": _text(control),
            "form_action_raw": form.get("action") if form else None,
            "form_method_raw": form.get("method") if form else None,
            "options": options,
            "interaction_status": "NOT_TESTED_OFFLINE_SNAPSHOT_ONLY",
        })
    return result


def _tabs(soup: BeautifulSoup, player_id: str, base_url: str) -> list[dict[str, str | None]]:
    tabs = []
    for anchor in soup.find_all("a", href=True):
        text = _text(anchor)
        if text not in {"Trayectoria", "Estadísticas", "Partidos", "Rivales"}:
            continue
        href = anchor["href"]
        absolute = urljoin(base_url, href)
        try:
            linked_player_id, _ = classify_player_view(absolute)
        except PlayerSnapshotError:
            continue
        if linked_player_id != player_id:
            continue
        tabs.append({"label_raw": text, "href_raw": href, "url": absolute})
    return tabs


def _entity_reference(href: str) -> tuple[str | None, str | None]:
    path = urlsplit(href).path
    patterns = (
        ("player", r"/j/j(\d+)\.html$", "j"),
        ("coach", r"/l/l(\d+)\.html$", "l"),
        ("team_season", r"/t/(t[^/]+)\.html$", ""),
        ("club", r"/e/e(\d+)\.html$", "e"),
        ("match", r"/p/p\.php$", ""),
        ("stadium", r"/s/(\d+)\.html$", "s"),
        ("referee", r"/r/r(\d+)\.html$", "r"),
    )
    for entity_type, pattern, prefix in patterns:
        match = re.search(pattern, path)
        if match:
            if entity_type == "match":
                from urllib.parse import parse_qs

                match_id = parse_qs(urlsplit(href).query).get("id", [None])[-1]
                return entity_type, str(match_id) if match_id else None
            return entity_type, f"{prefix}{match.group(1)}" if prefix else match.group(1)
    return None, None


def _relationship_occurrences(
    tables: list[dict[str, Any]], player_id: str, view: str,
) -> list[dict[str, Any]]:
    relationships = []
    for table in tables:
        for row in table["rows"]:
            if row["row_role"] not in {"data", "total", "section"}:
                continue
            for cell in row["cells"]:
                for link in cell["links"]:
                    url = link.get("url")
                    if not url:
                        continue
                    entity_type, entity_id = _entity_reference(url)
                    if not entity_type or (entity_type == "player" and entity_id == player_id):
                        continue
                    relationships.append({
                        "player_id": player_id,
                        "related_entity_type": entity_type,
                        "related_entity_id": entity_id,
                        "related_name_raw": link.get("text_raw"),
                        "url": url,
                        "page_view": view,
                        "table_id": table.get("table_id"),
                        "table_role": table.get("table_role"),
                        "source_table_index": table.get("table_index"),
                        "source_row_index": row.get("row_index"),
                        "source_column_index": cell.get("column_index"),
                    })
    return relationships


def _header_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _individual_player_match_rows(
    table: dict[str, Any],
    *,
    player_id: str,
    captured_at_utc: str | None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Read fixture-like data rows from tpartits while retaining every source cell."""
    from football_data_hub.providers.bdfutbol.players.match_status import assess_match_status

    headers = {
        int(header["column_index"]): header
        for header in table.get("column_headers", [])
        if isinstance(header.get("column_index"), int)
    }

    def column_index(*, colids: tuple[str, ...] = (), labels: tuple[str, ...] = ()) -> int | None:
        for index, header in sorted(headers.items()):
            if str(header.get("data_colid_raw") or "").casefold() in colids:
                return index
            label = _header_key(header.get("header_original"))
            title = _header_key(header.get("header_title_raw"))
            if label in labels or title in labels:
                return index
        return None

    columns = {
        "date": column_index(colids=("data",), labels=("fecha", "date")),
        "season": column_index(colids=("temp",), labels=("temporada", "season")),
        "competition": column_index(colids=("tipus",), labels=("competición", "competicion", "competition")),
        "round": column_index(colids=("jor",), labels=("jornada", "round")),
        "home": column_index(colids=("e1",), labels=("local", "home")),
        "score": column_index(colids=("res",), labels=("marcador", "resultado", "result", "score")),
        "away": column_index(colids=("e2",), labels=("visitante", "away")),
    }
    if columns["score"] is None and columns["home"] is not None and columns["away"] is not None:
        between = [
            index for index in sorted(headers)
            if columns["home"] < index < columns["away"]
        ]
        if between:
            columns["score"] = between[-1]

    rows: list[dict[str, Any]] = []
    role_counts = {role: 0 for role in ("header", "data", "total", "blank", "section")}
    for row in table.get("rows", []):
        role = str(row.get("row_role") or "data")
        role_counts[role] = role_counts.get(role, 0) + 1
        if role != "data":
            continue
        cells = {int(cell["column_index"]): cell for cell in row.get("cells", [])}

        def raw(field: str) -> str | None:
            index = columns[field]
            value = cells.get(index, {}).get("raw_value") if index is not None else None
            return str(value) if value is not None else None

        match_link = None
        match_id = None
        for cell in row.get("cells", []):
            for link in cell.get("links", []):
                href = link.get("url")
                entity_type, entity_id = _entity_reference(href) if href else (None, None)
                if entity_type == "match" and entity_id:
                    match_link = link
                    match_id = entity_id
                    break
            if match_id:
                break

        # The table is the source's fixture list. A data row is retained even
        # when some expected cells are malformed or absent; it is never made up.
        date_raw = raw("date")
        date_match = _DATE.fullmatch((date_raw or "").strip())
        date_iso = (
            f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
            if date_match else None
        )
        score_raw = raw("score")
        score_match = _SCORE.fullmatch((score_raw or "").strip())
        home_goals = int(score_match.group(1)) if score_match else None
        away_goals = int(score_match.group(2)) if score_match else None
        assessment_input = {
            "match_id": match_id,
            "date": date_iso,
            "date_raw": date_raw,
            "result_raw": score_raw,
            "home_goals": home_goals,
            "away_goals": away_goals,
        }
        assessment = assess_match_status(assessment_input, captured_at_utc=captured_at_utc)
        match_row = {
            "player_id": player_id,
            "match_id": match_id,
            "match_url": match_link.get("url") if match_link else None,
            "season_raw": raw("season"),
            "competition_raw": raw("competition"),
            "round_raw": raw("round"),
            "date_raw": date_raw,
            "date": date_iso,
            "home_team_raw": raw("home"),
            "away_team_raw": raw("away"),
            "result_raw": score_raw,
            "home_goals": home_goals,
            "away_goals": away_goals,
            "source_values_raw": [cell.get("raw_value") for cell in row.get("cells", [])],
            "cells": row.get("cells", []),
            "column_headers": list(table.get("column_headers", [])),
            "source_table_id": table.get("table_id"),
            "source_table_index": table.get("table_index"),
            "source_row_index": row.get("row_index"),
            "row_duplicate_of": row.get("duplicate_of_row_index"),
            "match_state": assessment["state"],
            "match_state_issues": assessment["issues"],
            "match_state_evidence": assessment["evidence"],
        }
        rows.append(match_row)
    return rows, role_counts


def _window_p_player_match_rows(
    values: list[list[Any]],
    *,
    player_id: str,
    base_url: str,
    captured_at_utc: str | None,
    source_reference: dict[str, Any],
) -> list[dict[str, Any]]:
    """Normalize verified P tuples while retaining their exact positions and values."""
    from football_data_hub.providers.bdfutbol.players.match_status import assess_match_status

    records: list[dict[str, Any]] = []
    for source_index, raw_values in enumerate(values):
        source_values = dict(zip(_WINDOW_P_FIELD_NAMES, raw_values, strict=True))
        match_id_value = _integer_value(source_values["id"])
        match_id = str(match_id_value) if match_id_value is not None and match_id_value > 0 else None
        date_raw = str(source_values["dat"]) if source_values["dat"] is not None else None
        date_match = _DATE.fullmatch((date_raw or "").strip())
        date_iso = (
            f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"
            if date_match else None
        )
        home_goals = _integer_value(source_values["gc"])
        away_goals = _integer_value(source_values["gf"])
        result_raw = (
            f"{home_goals} {away_goals}"
            if home_goals is not None and away_goals is not None else None
        )
        location = _integer_value(source_values["loc"])
        if location == 1:
            player_side = "home"
            player_team, opponent_team = source_values["e1"], source_values["e2"]
            player_club_id, opponent_club_id = source_values["ce1"], source_values["ce2"]
        elif location == 0:
            player_side = "away"
            player_team, opponent_team = source_values["e2"], source_values["e1"]
            player_club_id, opponent_club_id = source_values["ce2"], source_values["ce1"]
        else:
            player_side = player_team = opponent_team = player_club_id = opponent_club_id = None

        appearance_flags = [_integer_value(source_values[name]) for name in ("pt", "pc", "ps")]
        if any(flag == 1 for flag in appearance_flags):
            appearance_status = "APPEARED_PER_SOURCE_FLAGS"
        elif all(flag in {0, 1} for flag in appearance_flags):
            appearance_status = "NO_APPEARANCE_PER_SOURCE_FLAGS"
        else:
            appearance_status = "UNINTERPRETED_SOURCE_FLAGS"
        summoned_flag = _integer_value(source_values["pv"])
        if summoned_flag == 1 and appearance_status == "NO_APPEARANCE_PER_SOURCE_FLAGS":
            summoned_status = "SUMMONED_WITHOUT_APPEARANCE_PER_SOURCE_FLAG"
        elif summoned_flag == 0:
            summoned_status = "NOT_MARKED_AS_SUMMONED"
        elif summoned_flag == 1:
            summoned_status = "SUMMONED_PER_SOURCE_FLAG"
        else:
            summoned_status = "UNINTERPRETED_SOURCE_FLAG"

        match_assessment = assess_match_status(
            {
                "match_id": match_id,
                "date": date_iso,
                "date_raw": date_raw,
                "result_raw": result_raw,
                "home_goals": home_goals,
                "away_goals": away_goals,
            },
            captured_at_utc=captured_at_utc,
        )
        records.append({
            "player_id": player_id,
            "match_id": match_id,
            "match_url": urljoin(base_url, f"/es/p/p.php?id={match_id}") if match_id else None,
            "season_start_year_raw": source_values["t"],
            "season_raw": source_values["nomtemp"],
            "competition_raw": source_values["cat"],
            "round_raw": source_values["jor"],
            "round_title_raw": source_values["jor2"],
            "date_raw": date_raw,
            "date": date_iso,
            "home_team_raw": source_values["e1"],
            "away_team_raw": source_values["e2"],
            "home_club_id_raw": source_values["ce1"],
            "away_club_id_raw": source_values["ce2"],
            "home_goals": home_goals,
            "away_goals": away_goals,
            "result_raw": result_raw,
            "player_team_side_raw": player_side,
            "player_team_raw": player_team,
            "player_club_id_raw": player_club_id,
            "opponent_team_raw": opponent_team,
            "opponent_club_id_raw": opponent_club_id,
            "player_appearance_status": appearance_status,
            "player_summoned_status": summoned_status,
            "minutes": _integer_value(source_values["min"]),
            "minutes_raw": source_values["min"],
            "result_relative_code_raw": source_values["gp"],
            "player_match_metrics_raw": {
                name: source_values[name]
                for name in ("pt", "pc", "ps", "min", "pv", "tg1", "tg2", "tv", "tg", "genc", "px")
            },
            "source_kind": "WINDOW_P",
            "source_record_index": source_index,
            "source_js_field_names": list(_WINDOW_P_FIELD_NAMES),
            "source_values_raw": raw_values,
            "source_snapshot": source_reference,
            "match_state": match_assessment["state"],
            "match_state_issues": match_assessment["issues"],
            "match_state_evidence": match_assessment["evidence"],
        })
    return records


def _view_records(
    view: str,
    tables: list[dict[str, Any]],
    player_id: str,
    *,
    base_url: str = "",
    captured_at_utc: str | None = None,
    filter_parameters: dict[str, str] | None = None,
    is_base_view_snapshot: bool | None = None,
    window_p_status: str = "NOT_PRESENT",
    window_p_values: list[list[Any]] | None = None,
    snapshot_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if view == "profile":
        raise PlayerSnapshotError("La vista profile requiere el parser de identidad y trayectoria")
    if view == "statistics":
        stat_rows = []
        for table in tables:
            for row in table["rows"]:
                if row["row_role"] in {"data", "total", "section"}:
                    stat_rows.append({
                        "player_id": player_id,
                        "table_id": table.get("table_id"),
                        "table_role": table.get("table_role"),
                        "table_caption_raw": table.get("caption_raw"),
                        "source_row_index": row.get("row_index"),
                        "row_role": row.get("row_role"),
                        "metric_label_raw": row["cells"][0]["raw_value"] if row["cells"] else None,
                        "columns": _cells_with_headers(row, table),
                        "source_table_index": table.get("table_index"),
                    })
        return {"statistics_rows": stat_rows}
    if view == "matches":
        summaries = []
        for table in tables:
            if table.get("table_role") == "individual_match_fixtures":
                continue
            for row in table["rows"]:
                if row["row_role"] in {"data", "total", "section"}:
                    summaries.append({
                        "player_id": player_id,
                        "summary_dimension": table.get("table_role"),
                        "table_id": table.get("table_id"),
                        "table_role": table.get("table_role"),
                        "table_caption_raw": table.get("caption_raw"),
                        "source_row_index": row.get("row_index"),
                        "row_role": row.get("row_role"),
                        "dimension_value_raw": row["cells"][0]["raw_value"] if row["cells"] else None,
                        "columns": _cells_with_headers(row, table),
                        "source_table_index": table.get("table_index"),
                    })
        fixture_table = next(
            (table for table in tables if table.get("table_role") == "individual_match_fixtures"),
            None,
        )
        individual_rows, row_role_counts = _individual_player_match_rows(
            fixture_table,
            player_id=player_id,
            captured_at_utc=captured_at_utc,
        ) if fixture_table else ([], {})
        table_individual_rows = individual_rows
        query = parse_qs(urlsplit(base_url).query, keep_blank_values=True)
        filters = {key: values[-1] for key, values in query.items()}
        filters.update(filter_parameters or {})
        is_base_view = (
            is_base_view_snapshot
            if is_base_view_snapshot is not None
            else _is_base_view_url(base_url, view)
        )
        if window_p_status == "PARSED_27_FIELD_TUPLES" and is_base_view:
            individual_rows = _window_p_player_match_rows(
                window_p_values or [],
                player_id=player_id,
                base_url=base_url,
                captured_at_utc=captured_at_utc,
                source_reference=snapshot_source or {},
            )
            for record in individual_rows:
                record["match_statistics"] = _window_p_match_statistics(record, fixture_table)
            individual_rows_source = "WINDOW_P" if individual_rows else None
        else:
            individual_rows_source = "TPARTITS" if individual_rows else None

        if individual_rows and individual_rows_source == "WINDOW_P":
            detail_status = (
                "WINDOW_P_MATCH_RECORDS_PRESENT; BASE_TPARTITS_ROWS_ALSO_PRESENT"
                if table_individual_rows
                else "WINDOW_P_MATCH_RECORDS_PRESENT; BASE_TPARTITS_HEADER_ONLY"
            )
        elif individual_rows:
            detail_status = "INDIVIDUAL_MATCH_FIXTURE_ROWS_PRESENT"
        elif window_p_status == "PARSED_27_FIELD_TUPLES" and not is_base_view:
            detail_status = "FILTERED_TPARTITS_EMPTY; WINDOW_P_NOT_USED_FOR_FILTERED_OUTPUT"
        elif window_p_status == "PRESENT_EMPTY":
            detail_status = "WINDOW_P_PRESENT_EMPTY"
        elif fixture_table and row_role_counts.get("header", 0):
            detail_status = "AGGREGATE_TABLES_ONLY_HEADER_ONLY_NO_FIXTURES"
        elif fixture_table:
            detail_status = "AGGREGATE_TABLES_ONLY_TPARTITS_EMPTY"
        else:
            detail_status = "AGGREGATE_TABLES_ONLY_TPARTITS_NOT_PRESENT"
        return {
            "match_summary_rows": summaries,
            "individual_match_rows": individual_rows,
            "individual_match_rows_source": individual_rows_source,
            "window_p_parse_status": window_p_status,
            "window_p_record_count": (
                len(window_p_values or [])
                if window_p_status in {"PARSED_27_FIELD_TUPLES", "PRESENT_EMPTY"}
                else None
            ),
            "match_detail_coverage": detail_status,
            "individual_match_row_role_counts": row_role_counts,
            "filter_parameters": filters,
            "filtered_view": bool(filters),
            "exhaustiveness_status": (
                "FILTERED_SNAPSHOT_NOT_EXHAUSTIVE" if filters
                else "SNAPSHOT_SCOPE_ONLY_NOT_CERTIFIED_COMPLETE"
            ),
        }
    if view == "rivals":
        records = []
        entity_by_role = {
            "opponent_player_statistics": "player",
            "opponent_coach_statistics": "coach",
            "opponent_team_statistics": "club",
        }
        for table in tables:
            role = table.get("table_role")
            for row in table["rows"]:
                if row["row_role"] != "data":
                    continue
                name_cell = next((cell for cell in row["cells"] if cell.get("links")), None)
                link = (name_cell or {}).get("links", [None])[0]
                href = link.get("url") if link else None
                entity_type, entity_id = _entity_reference(href) if href else (None, None)
                records.append({
                    "player_id": player_id,
                    "rival_kind": entity_by_role.get(role, "unclassified"),
                    "rival_id": entity_id,
                    "rival_name_raw": link.get("text_raw") if link else None,
                    "rival_url": href,
                    "source_table_id": table.get("table_id"),
                    "source_table_role": role,
                    "table_caption_raw": table.get("caption_raw"),
                    "source_row_index": row.get("row_index"),
                    "row_duplicate_of": row.get("duplicate_of_row_index"),
                    "columns": _cells_with_headers(row, table),
                })
        return {"rival_records": records}
    raise PlayerSnapshotError(f"Vista no soportada: {view}")


def parse_player_html(
    html: str,
    metadata: dict[str, Any],
    *,
    snapshot_directory: str | None = None,
    expected_player_id: str | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse one captured rendered HTML page without network access."""
    url = str(metadata.get("final_url") or metadata.get("requested_url") or "")
    expected_hash = metadata.get("html_sha256") or metadata.get("rendered_html_sha256")
    actual_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
    if expected_hash and actual_hash != expected_hash:
        raise PlayerSnapshotError("SHA-256 del HTML no coincide con la metadata")
    player_id, view = classify_player_view(url)
    if expected_player_id and player_id != expected_player_id:
        raise PlayerSnapshotError(
            f"ID esperado {expected_player_id} no coincide con URL {player_id}"
        )
    soup = soup_from_html(html)
    source = _source(metadata, snapshot_directory, html)
    if source["metadata_sha256_matches"] is False:
        raise PlayerSnapshotError(f"SHA-256 del HTML no coincide: {snapshot_directory or url}")
    tables = _view_tables(soup, view, url)
    window_p_status, window_p_values = (
        _window_p_values(soup) if view == "matches" else ("NOT_APPLICABLE", [])
    )
    source_reference = {
        "capture_id": metadata.get("capture_id"),
        "snapshot_id": metadata.get("snapshot_id"),
        "snapshot_kind": metadata.get("snapshot_kind", "BASE_VIEW"),
        "requested_url": metadata.get("requested_url"),
        "captured_at_utc": metadata.get("captured_at_utc"),
        "html_sha256": metadata.get("html_sha256"),
        "snapshot_directory": snapshot_directory,
    }
    if view == "profile":
        view_data = _profile_data(soup, tables, url)
    else:
        view_data = _view_records(
            view,
            tables,
            player_id,
            base_url=url,
            captured_at_utc=str(metadata.get("captured_at_utc") or "") or None,
            filter_parameters=(
                {str(key): str(value) for key, value in metadata.get("filter_parameters", {}).items()}
                if isinstance(metadata.get("filter_parameters"), dict) else None
            ),
            is_base_view_snapshot=(
                metadata.get("is_base_view_snapshot")
                if isinstance(metadata.get("is_base_view_snapshot"), bool)
                else _is_base_view_url(url, view)
            ),
            window_p_status=window_p_status,
            window_p_values=window_p_values,
            snapshot_source=source_reference,
        )
    roles_observed = [table["table_role"] for table in tables]
    missing_roles = [
        role for role in _REQUIRED_TABLE_ROLES[view]
        if role not in roles_observed
    ]
    coverage = {
        "view": view,
        "snapshot_status": "CAPTURED_VALID" if metadata.get("access_status") == "VALID" and metadata.get("http_status") == 200 else "CAPTURED_NON_VALID",
        "parse_status": "PARSED" if not missing_roles else "PARSED_PARTIAL_TABLE_SET",
        "required_table_roles": list(_REQUIRED_TABLE_ROLES[view]),
        "table_roles_observed": roles_observed,
        "required_table_roles_missing": missing_roles,
        "interaction_coverage": (summary or {}).get("interaction_coverage", "UNKNOWN"),
        "filters_pending": [
            control["id"] or control["name"] for control in _controls(soup, view)
            if (control["id"] or control["name"])
            not in (metadata.get("filter_parameters") or {})
        ],
        "filters_applied": metadata.get("filter_parameters", {}),
        "is_base_view_snapshot": metadata.get("is_base_view_snapshot", _is_base_view_url(url, view)),
        "data_scope": (
            "FILTERED_VARIANT_NOT_EXHAUSTIVE"
            if metadata.get("is_base_view_snapshot") is False
            else
            "CAREER_ROWS_PRESENT_NOT_CERTIFIED_COMPLETE" if view == "profile"
            else "SNAPSHOT_CONTENT_ONLY_FILTER_VARIANTS_NOT_TESTED"
        ),
        "player_identity_key": player_id,
    }
    if view == "matches":
        coverage["match_detail_scope"] = (
            "INDIVIDUAL_FIXTURE_ROWS"
            if view_data.get("individual_match_rows") else "AGGREGATE_ONLY"
        )
        coverage["match_detail_coverage"] = view_data.get("match_detail_coverage")
        coverage["individual_match_rows_source"] = view_data.get("individual_match_rows_source")
        coverage["window_p_parse_status"] = view_data.get("window_p_parse_status")
        coverage["window_p_record_count"] = view_data.get("window_p_record_count")
        coverage["match_detail_scope"] = (
            "WINDOW_P_MATCH_RECORDS_NOT_CERTIFIED_COMPLETE"
            if view_data.get("individual_match_rows_source") == "WINDOW_P"
            else "TPARTITS_RENDERED_ROWS_NOT_CERTIFIED_COMPLETE"
            if view_data.get("individual_match_rows_source") == "TPARTITS"
            else "NO_INDIVIDUAL_FIXTURE_ROWS_OBSERVED"
        )
        coverage["filtered_view"] = view_data.get("filtered_view", False)
        coverage["filter_parameters"] = view_data.get("filter_parameters", {})
    return {
        "schema_version": PLAYER_SCHEMA_VERSION,
        "parser_version": PLAYER_PARSER_VERSION,
        "player_id": player_id,
        "view": view,
        "url": url,
        "source": source,
        "page_title_raw": _text(soup.title) or metadata.get("page_title"),
        "view_tabs": _tabs(soup, player_id, url),
        "filter_controls": _controls(soup, view),
        "tables": tables,
        "relationships": _relationship_occurrences(tables, player_id, view),
        "view_data": view_data,
        "coverage": coverage,
    }
