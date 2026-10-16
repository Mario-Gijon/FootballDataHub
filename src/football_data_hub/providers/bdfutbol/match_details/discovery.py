"""Generic offline HTML inventory for first-page structural discovery.

This module deliberately does not assign BDFutbol semantics or selectors. Its
output records raw DOM observations and keyword-based hypotheses only.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup

DISCOVERY_SCHEMA = "football_data_hub.match_detail_discovery.v1"
DISCOVERY_TOOL_VERSION = "0.1.0"
_MAX_TABLES = 100
_MAX_ROWS_PER_TABLE = 20
_MAX_CELLS_PER_ROW = 30
_MAX_LINKS = 500
_MAX_SCRIPTS = 200
_MAX_TEXT = 500

# These words are search cues, not evidence that a particular element has the
# corresponding sporting meaning. Real-page review must confirm each mapping.
_HYPOTHESIS_TERMS: dict[str, tuple[str, ...]] = {
    "match_identity_or_teams": ("partido", "encuentro", "equipo", "local", "visitante"),
    "date_or_result": ("fecha", "resultado", "jornada", "goles", "marcador"),
    "venue_or_official": ("estadio", "árbitro", "arbitro", "campo"),
    "players_or_lineups": (
        "jugador",
        "titular",
        "suplente",
        "alineación",
        "alineacion",
        "dorsal",
    ),
    "coaches": ("entrenador", "técnico", "tecnico"),
    "match_events": (
        "gol",
        "autogol",
        "penalti",
        "penalty",
        "tarjeta",
        "sustitución",
        "sustitucion",
        "minuto",
    ),
}
_ID_QUERY_RE = re.compile(r"(?:^|[?&])id=([^&#]+)", re.IGNORECASE)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _text(node: Any, limit: int = _MAX_TEXT) -> str:
    value = " ".join(node.stripped_strings) if node is not None else ""
    return value[:limit]


def _json_keys(script_text: str) -> list[str] | None:
    try:
        value = json.loads(script_text)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(value, dict):
        return sorted(str(key) for key in value)[:100]
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return sorted(str(key) for key in value[0])[:100]
    return []


def _json_shape(script_text: str) -> dict[str, Any] | None:
    """Return bounded JSON keys/types without copying source values."""

    try:
        value = json.loads(script_text)
    except (json.JSONDecodeError, TypeError):
        return None

    def describe(item: Any, depth: int = 0) -> dict[str, Any]:
        if isinstance(item, dict):
            keys = sorted(str(key) for key in item)[:40]
            result: dict[str, Any] = {"type": "object", "keys": keys}
            if depth < 3:
                result["children"] = {
                    key: describe(item[key], depth + 1) for key in keys if key in item
                }
            return result
        if isinstance(item, list):
            result = {"type": "array", "length": len(item)}
            if item and depth < 3:
                result["first_item_shape"] = describe(item[0], depth + 1)
            return result
        return {"type": type(item).__name__}

    return describe(value)


def discover_html_structure(source_html: bytes | str) -> dict[str, Any]:
    """Describe observed HTML without claiming that any structure is semantic."""

    raw = source_html.encode("utf-8") if isinstance(source_html, str) else source_html
    if not isinstance(raw, bytes) or not raw:
        raise ValueError("source_html debe contener HTML no vacío")
    text = raw.decode("utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")
    tags = Counter(tag.name for tag in soup.find_all(True))

    attribute_signatures: list[dict[str, Any]] = []
    for tag in soup.find_all(True, attrs={"id": True})[:500]:
        attribute_signatures.append(
            {
                "tag": tag.name,
                "id_value": str(tag.get("id")),
                "class_values": [str(value) for value in tag.get("class", [])],
            }
        )

    tables: list[dict[str, Any]] = []
    for ordinal, table in enumerate(soup.find_all("table")[:_MAX_TABLES], start=1):
        rows = []
        for row in table.find_all("tr")[:_MAX_ROWS_PER_TABLE]:
            cells = row.find_all(["th", "td"], recursive=False)
            if cells:
                rows.append([_text(cell) for cell in cells[:_MAX_CELLS_PER_ROW]])
        tables.append(
            {
                "ordinal": ordinal,
                "attributes": {
                    key: table.attrs[key]
                    for key in ("id", "class", "role")
                    if key in table.attrs
                },
                "row_count_observed": len(table.find_all("tr")),
                "rows_excerpt": rows,
            }
        )

    controls: list[dict[str, Any]] = []
    for tag in soup.find_all(
        ["form", "input", "select", "option", "button", "textarea"]
    ):
        controls.append(
            {
                "tag": tag.name,
                "attributes": {
                    key: tag.attrs[key]
                    for key in (
                        "id",
                        "name",
                        "type",
                        "value",
                        "action",
                        "method",
                        "class",
                    )
                    if key in tag.attrs
                },
                "text": _text(tag, 160),
            }
        )
        if len(controls) >= 500:
            break

    scripts: list[dict[str, Any]] = []
    for script in soup.find_all("script")[:_MAX_SCRIPTS]:
        script_text = script.string or script.get_text() or ""
        scripts.append(
            {
                "attributes": {
                    key: script.attrs[key]
                    for key in ("id", "type", "src", "class")
                    if key in script.attrs
                },
                "character_count": len(script_text),
                "content_sha256": _sha256(script_text.encode("utf-8")),
                "json_object_keys_if_parseable": (
                    _json_keys(script_text)
                    if str(script.get("type", "")).lower()
                    in {"application/json", "application/ld+json"}
                    else None
                ),
                "json_shape_if_parseable": (
                    _json_shape(script_text)
                    if str(script.get("type", "")).lower()
                    in {"application/json", "application/ld+json"}
                    else None
                ),
            }
        )

    links: list[dict[str, Any]] = []
    for anchor in soup.find_all("a", href=True)[:_MAX_LINKS]:
        href = str(anchor.get("href", ""))
        id_match = _ID_QUERY_RE.search(href)
        links.append(
            {
                "href": href,
                "text": _text(anchor, 160),
                "class_values": [str(value) for value in anchor.get("class", [])],
                "query_id_candidate": id_match.group(1) if id_match else None,
            }
        )

    searchable = "\n".join(
        [
            soup.get_text(" ", strip=True),
            *(script.get_text() or "" for script in soup.find_all("script")),
        ]
    ).casefold()
    hypotheses = []
    for topic, terms in _HYPOTHESIS_TERMS.items():
        matches = [term for term in terms if term.casefold() in searchable]
        if matches:
            hypotheses.append(
                {
                    "topic_hypothesis": topic,
                    "matched_terms": matches,
                    "interpretation_status": "unverified_keyword_hypothesis",
                }
            )

    return {
        "schema_version": DISCOVERY_SCHEMA,
        "tool_version": DISCOVERY_TOOL_VERSION,
        "generated_at_utc": datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "source_html_sha256": _sha256(raw),
        "source_html_bytes": len(raw),
        "document_title_observed": _text(soup.title),
        "document_body_text_observed_excerpt": _text(soup.body, 2000),
        "semantic_mapping_confirmed": False,
        "observed_html": {
            "tag_counts": dict(sorted(tags.items())),
            "elements_with_ids_excerpt": attribute_signatures,
            "tables": tables,
            "form_controls": controls,
            "scripts": scripts,
            "links": links,
        },
        "hypotheses": hypotheses,
        "limitations": [
            "No BDFutbol-specific selector or field mapping is asserted.",
            "Keyword matches and numeric query IDs are discovery leads only.",
            "The first real page must be reviewed before a semantic parser is defined.",
            "This report cannot authorize capture promotion.",
        ],
    }
