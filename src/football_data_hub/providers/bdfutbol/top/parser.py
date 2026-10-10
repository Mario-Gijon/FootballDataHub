"""Parser semántico offline de HTML y datos JavaScript de Destacados."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit

from .models import (
    ForeignPlayerStatistics,
    ForeignersSummary,
    ParsedTop,
    ProgressPoint,
    ProgressSeries,
    RankingRecord,
    TopPlayer,
)

TOP_URL = "https://www.bdfutbol.com/es/t/t2026-271rf2.html?tab=top"
_POSITION_NAMES = {
    "por": "Portero",
    "def": "Defensa",
    "mig": "Centrocampista",
    "dav": "Delantero",
}
_COUNTRY_FALLBACKS = {"espanya": "España"}
_CATEGORY_DEFINITIONS: dict[str, dict[str, Any]] = {
    "1": {
        "category": "goals", "container": "jugs1", "metric": "goals",
        "unit": "goals", "header": "G", "series": "DG",
        "selector_prefix": "DG",
    },
    "2": {
        "category": "minutes", "container": "jugs2", "metric": "minutes_played",
        "unit": "minutes", "header": "Min", "series": "DM",
        "selector_prefix": "DM",
    },
    "3": {
        "category": "yellow_cards", "container": "jugs3", "metric": "yellow_cards",
        "unit": "cards", "header": "TA", "series": "DTG",
        "selector_prefix": "DTG",
    },
    "4": {
        "category": "red_cards", "container": "jugs4", "metric": "red_cards",
        "unit": "cards", "header": "TR", "series": "DTV",
        "selector_prefix": "DTV",
    },
    "8": {
        "category": "youngest", "container": "jugs8", "metric": "age_years",
        "unit": "years", "header": "PJ", "series": None,
        "selector_prefix": None,
    },
    "9": {
        "category": "oldest", "container": "jugs9", "metric": "age_years",
        "unit": "years", "header": "PJ", "series": None,
        "selector_prefix": None,
    },
}
_EXPECTED_HEADERS = {
    "1": ("", "Jugador", "País", "Pos", "Edad", "G", "Club"),
    "2": ("", "Jugador", "País", "Pos", "Edad", "Min", "Club"),
    "3": ("", "Jugador", "País", "Pos", "Edad", "TA", "Club"),
    "4": ("", "Jugador", "País", "Pos", "Edad", "TR", "Club"),
    "8": ("Jugador", "País", "Pos", "Edad", "PJ", "Club"),
    "9": ("Jugador", "País", "Pos", "Edad", "PJ", "Club"),
}


class TopParseError(ValueError):
    """El documento no contiene datos de Destacados interpretables."""


@dataclass(slots=True)
class _Link:
    attrs: dict[str, str | None]
    text: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Span:
    attrs: dict[str, str | None]
    text: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Cell:
    tag: str
    attrs: dict[str, str | None]
    text: list[str] = field(default_factory=list)
    links: list[_Link] = field(default_factory=list)
    images: list[dict[str, str | None]] = field(default_factory=list)
    div_classes: list[str] = field(default_factory=list)
    spans: list[_Span] = field(default_factory=list)
    inputs: list[dict[str, str | None]] = field(default_factory=list)


@dataclass(slots=True)
class _Row:
    cells: list[_Cell] = field(default_factory=list)


@dataclass(slots=True)
class _Table:
    scope: str
    rows: list[_Row] = field(default_factory=list)


class _TopDocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.bucket_id: str | None = None
        self.bucket_div_depth = 0
        self.active_table: _Table | None = None
        self.current_row: _Row | None = None
        self.current_cell: _Cell | None = None
        self.current_link: _Link | None = None
        self.span_stack: list[_Span] = []
        self.tables: dict[str, _Table] = {}
        self.select_id: str | None = None
        self.current_option: dict[str, Any] | None = None
        self.options: dict[str, list[tuple[str, str]]] = {}
        self.heading_id: str | None = None
        self.heading_text: list[str] = []
        self.foreign_heading = ""
        self.see_all = False

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str | None]:
        return {key: value for key, value in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = self._attrs(attrs)
        if tag == "div":
            if self.current_cell is not None:
                self.current_cell.div_classes.extend((values.get("class") or "").split())
            if self.bucket_id is not None:
                self.bucket_div_depth += 1
            elif values.get("id") in {definition["container"] for definition in _CATEGORY_DEFINITIONS.values()}:
                self.bucket_id = str(values["id"])
                self.bucket_div_depth = 1
        elif tag == "table" and self.active_table is None:
            table_id = values.get("id")
            if table_id == "tab_estran":
                self.active_table = _Table("foreigners")
            elif self.bucket_id is not None:
                category_id = next(
                    key for key, definition in _CATEGORY_DEFINITIONS.items()
                    if definition["container"] == self.bucket_id
                )
                self.active_table = _Table(category_id)
        elif tag == "tr" and self.active_table is not None:
            self.current_row = _Row()
            self.current_cell = None
        elif tag in {"td", "th"} and self.current_row is not None:
            self.current_cell = _Cell(tag, values)
        elif tag == "a" and self.current_cell is not None:
            self.current_link = _Link(values)
        elif tag == "img" and self.current_cell is not None:
            self.current_cell.images.append(values)
        elif tag == "span" and self.current_cell is not None:
            span = _Span(values)
            self.current_cell.spans.append(span)
            self.span_stack.append(span)
        elif tag == "input" and self.current_cell is not None:
            self.current_cell.inputs.append(values)
        elif tag == "select":
            self.select_id = values.get("id")
        elif tag == "option" and self.select_id is not None:
            self.current_option = {"value": values.get("value", ""), "text": []}
        elif tag == "h2":
            self.heading_id = values.get("id") or "h2"
            self.heading_text = []
        if tag == "a" and values.get("onclick", "").startswith("veure_mesdest"):
            self.see_all = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.current_link is not None:
            if self.current_cell is not None:
                self.current_cell.links.append(self.current_link)
            self.current_link = None
        elif tag == "span" and self.span_stack:
            self.span_stack.pop()
        elif tag in {"td", "th"} and self.current_cell is not None:
            if self.current_row is not None:
                self.current_row.cells.append(self.current_cell)
            self.current_cell = None
            self.current_link = None
        elif tag == "tr" and self.current_row is not None:
            if self.active_table is not None:
                self.active_table.rows.append(self.current_row)
            self.current_row = None
            self.current_cell = None
            self.current_link = None
        elif tag == "table" and self.active_table is not None:
            self.tables[self.active_table.scope] = self.active_table
            self.active_table = None
        elif tag == "option" and self.current_option is not None:
            value = str(self.current_option["value"] or "")
            text = _clean_text("".join(self.current_option["text"]))
            if self.select_id:
                self.options.setdefault(self.select_id, []).append((value, text))
            self.current_option = None
        elif tag == "select":
            self.select_id = None
        elif tag == "h2" and self.heading_id is not None:
            text = _clean_text("".join(self.heading_text))
            if text.casefold().startswith("extranjeros"):
                self.foreign_heading = text
            self.heading_id = None
            self.heading_text = []
        elif tag == "div" and self.bucket_id is not None:
            self.bucket_div_depth -= 1
            if self.bucket_div_depth <= 0:
                self.bucket_id = None
                self.bucket_div_depth = 0

    def handle_data(self, data: str) -> None:
        if self.current_option is not None:
            self.current_option["text"].append(data)
        if self.heading_id is not None:
            self.heading_text.append(data)
        if self.current_cell is not None:
            self.current_cell.text.append(data)
            if self.current_link is not None:
                self.current_link.text.append(data)
            for span in self.span_stack:
                span.text.append(data)


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _cell_text(cell: _Cell) -> str:
    return _clean_text("".join(cell.text))


def _integer(value: str, field_name: str, *, nullable: bool = False) -> int | None:
    text = _clean_text(value)
    if text in {"", "-", "–", "—"}:
        if nullable:
            return None
        raise TopParseError(f"Falta el campo numérico {field_name}")
    try:
        return int(text)
    except ValueError as exc:
        raise TopParseError(f"Valor no numérico en {field_name}: {text!r}") from exc


def _absolute(base_url: str, value: str | None) -> str | None:
    if not value:
        return None
    return urljoin(base_url, value.replace("../..//", "/"))


def _player_id_from_row(row: _Row) -> int:
    for cell in row.cells:
        for link in cell.links:
            href = link.attrs.get("href") or ""
            match = re.search(r"(?:^|/)j(\d+)\.html(?:$|[?#])", href)
            if match:
                return int(match.group(1))
    raise TopParseError("Fila de jugador sin identificador BDFutbol en su enlace")


def _team_catalog(
    catalog: Iterable[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_crest: dict[str, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for team in catalog:
        crest_url = team.get("crest_url")
        crest_name = PurePosixPath(urlsplit(str(crest_url or "")).path).name
        if crest_name:
            if crest_name in by_crest:
                raise TopParseError(f"Escudo ambiguo en catálogo de equipos: {crest_name}")
            by_crest[crest_name] = team
        by_id[str(team.get("team_id"))] = team
    if not by_id:
        raise TopParseError("El catálogo de equipos está vacío")
    return by_crest, by_id


def _resolve_team(
    image: dict[str, str | None],
    teams_by_crest: dict[str, dict[str, Any]],
    *,
    player_id: int,
) -> dict[str, Any]:
    source_path = urlsplit(str(image.get("src") or "")).path
    basename = PurePosixPath(source_path).name
    team = teams_by_crest.get(basename)
    if team is None:
        raise TopParseError(
            f"No se pudo relacionar el escudo {basename!r} con el catálogo existente "
            f"(player_id={player_id})"
        )
    return team


def _country(cell: _Cell, options: dict[str, str]) -> tuple[str | None, str | None]:
    code = next((item for item in cell.div_classes if item not in {"pais"}), None)
    return code, options.get(code or "") or _COUNTRY_FALLBACKS.get(code or "")


def _position(cell: _Cell) -> tuple[str | None, str | None]:
    code = next((item for item in cell.div_classes if item in _POSITION_NAMES), None)
    return code, _POSITION_NAMES.get(code or "")


def _link_url(cell: _Cell, base_url: str, pattern: str) -> str | None:
    for link in cell.links:
        href = link.attrs.get("href") or ""
        if re.search(pattern, href):
            return _absolute(base_url, href)
    return None


def _merge_player(
    players: dict[int, dict[str, Any]],
    *,
    player_id: int,
    display_name: str,
    full_name: str | None,
    profile_url: str,
    photo_url: str | None,
    nationality_code: str | None,
    nationality: str | None,
    position_code: str | None,
    position_name: str | None,
    age_years: int | None,
    team: dict[str, Any],
) -> None:
    candidate = {
        "player_id": player_id,
        "display_name": display_name,
        "full_name": full_name,
        "profile_url": profile_url,
        "photo_url": photo_url,
        "nationality_code": nationality_code,
        "nationality": nationality,
        "position_code": position_code,
        "position_name": position_name,
        "age_years": age_years,
        "team_id": int(team["team_id"]),
        "team_name": str(team["name"]),
        "team_url": team.get("team_url"),
        "crest_url": team.get("crest_url"),
    }
    existing = players.get(player_id)
    if existing is None:
        players[player_id] = candidate
        return
    for key in ("nationality_code", "age_years", "team_id"):
        old, new = existing.get(key), candidate.get(key)
        if old is not None and new is not None and old != new:
            raise TopParseError(
                f"Datos contradictorios para player_id={player_id}: {key} {old!r}/{new!r}"
            )
    if existing["display_name"] != display_name:
        raise TopParseError(f"Nombre visible contradictorio para player_id={player_id}")
    if full_name:
        existing["full_name"] = full_name
    for key, value in candidate.items():
        if existing.get(key) is None and value is not None:
            existing[key] = value


def _player_from_ranking_row(
    row: _Row,
    *,
    category_id: str,
    base_url: str,
    countries: dict[str, str],
    teams_by_crest: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], int, int | None, bool | None]:
    checkbox_category = category_id in {"1", "2", "3", "4"}
    offset = 1 if checkbox_category else 0
    required_cells = 7 if checkbox_category else 6
    if len(row.cells) < required_cells:
        raise TopParseError(
            f"Fila #jugs{category_id} con {len(row.cells)} celdas; "
            f"se esperaban {required_cells}"
        )
    cells = row.cells
    name_cell, country_cell, position_cell = cells[offset : offset + 3]
    age_cell = cells[offset + 3]
    metric_cell = cells[offset + 4]
    crest_cell = cells[offset + 5]
    player_id = _player_id_from_row(row)
    player_link = next(
        (link for link in name_cell.links if re.search(r"(?:^|/)j\d+\.html", link.attrs.get("href") or "")),
        None,
    )
    display_name = _clean_text("".join(player_link.text)) if player_link else _cell_text(name_cell)
    if not display_name:
        raise TopParseError(f"Nombre visible ausente para player_id={player_id}")
    profile_url = _absolute(base_url, str(player_link.attrs.get("href"))) if player_link else None
    if profile_url is None:
        raise TopParseError(f"URL de ficha ausente para player_id={player_id}")
    photo = next(
        (image for image in name_cell.images if "mini-foto-jugador" in (image.get("class") or "").split()),
        None,
    )
    crest = next(
        (image for image in crest_cell.images if "escut-mini" in (image.get("class") or "").split()),
        None,
    )
    if crest is None:
        raise TopParseError(f"Escudo de club ausente para player_id={player_id}")
    team = _resolve_team(crest, teams_by_crest, player_id=player_id)
    country_code, country_name = _country(country_cell, countries)
    position_code, position_name = _position(position_cell)
    if position_code is None:
        raise TopParseError(f"Posición ausente para player_id={player_id}")
    age = _integer(_cell_text(age_cell), "age_years", nullable=True)
    table_value = _integer(_cell_text(metric_cell), "ranking_metric")
    assert table_value is not None
    if category_id in {"8", "9"}:
        if age is None:
            raise TopParseError(f"Edad ausente en ranking para player_id={player_id}")
        metric_value = age
        matches_played = table_value
    else:
        metric_value = table_value
        matches_played = None
    age_years = age
    checkbox = next(
        (item for item in cells[0].inputs if (item.get("id") or "").startswith("DG" if category_id == "1" else "DM" if category_id == "2" else "DTG" if category_id == "3" else "DTV")),
        None,
    ) if checkbox_category else None
    selected = checkbox is not None and "checked" in checkbox
    full_name = next(
        (
            _clean_text("".join(span.text))
            for span in name_cell.spans
            if {"d-none", "d-md-block"}.issubset(set((span.attrs.get("class") or "").split()))
        ),
        None,
    )
    player = {
        "player_id": player_id,
        "display_name": display_name,
        "full_name": full_name,
        "profile_url": profile_url,
        "photo_url": _absolute(base_url, photo.get("src")) if photo else None,
        "nationality_code": country_code,
        "nationality": country_name,
        "position_code": position_code,
        "position_name": position_name,
        "age_years": age_years,
        "team": team,
    }
    return player, metric_value, matches_played, selected if checkbox_category else None


def _extract_destacats_js(source_html: str) -> dict[str, Any]:
    match = re.search(r"\bconst\s+DESTACATS_JS\s*=\s*(\{.*?\})\s*;", source_html, re.S)
    if not match:
        raise TopParseError("No se encontró el objeto DESTACATS_JS")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise TopParseError("DESTACATS_JS no contiene JSON interpretable") from exc
    if not isinstance(payload, dict):
        raise TopParseError("DESTACATS_JS no es un objeto")
    required = {"NTC_G", "NT_G", "LG", "DG", "DM", "DTG", "DTV"}
    missing = required.difference(payload)
    if missing:
        raise TopParseError(f"Faltan campos en DESTACATS_JS: {sorted(missing)}")
    return payload


def _source_goals_tail(
    rows: list[list[Any]],
    *,
    base_url: str,
    countries: dict[str, str],
    teams_by_crest: dict[str, dict[str, Any]],
    players: dict[int, dict[str, Any]],
) -> list[tuple[int, int, bool]]:
    results: list[tuple[int, int, bool]] = []
    seen: set[int] = set()
    for index, values in enumerate(rows):
        if len(values) < 8:
            raise TopParseError(f"DESTACATS_JS.LG[{index}] tiene menos de ocho campos")
        country_code, raw_id, display_name, position_code, raw_goals, crest_path, photo_flag, raw_age = values[:8]
        try:
            player_id = int(raw_id)
            goals = int(raw_goals)
            age_years = int(raw_age) if raw_age is not None else None
        except (TypeError, ValueError) as exc:
            raise TopParseError(f"DESTACATS_JS.LG[{index}] tiene IDs o métricas no numéricos") from exc
        if player_id in seen:
            raise TopParseError(f"Jugador duplicado entre tabla de goles y LG: {player_id}")
        seen.add(player_id)
        crest_name = PurePosixPath(urlsplit(str(crest_path)).path).name
        team = teams_by_crest.get(crest_name)
        if team is None:
            raise TopParseError(f"DESTACATS_JS.LG[{index}] usa escudo sin equipo: {crest_name}")
        if not isinstance(position_code, str) or position_code not in _POSITION_NAMES:
            raise TopParseError(f"DESTACATS_JS.LG[{index}] tiene posición desconocida")
        if not isinstance(country_code, str) or not country_code:
            raise TopParseError(f"DESTACATS_JS.LG[{index}] tiene país ausente")
        if isinstance(photo_flag, bool) or not isinstance(photo_flag, int):
            raise TopParseError(f"DESTACATS_JS.LG[{index}] tiene indicador de foto inválido")
        photo_url = (
            urljoin(base_url, f"/i/m/{player_id}.png")
            if photo_flag > 0
            else (urljoin(base_url, str(values[8])) if len(values) > 8 and values[8] else None)
        )
        _merge_player(
            players,
            player_id=player_id,
            display_name=str(display_name),
            full_name=None,
            profile_url=urljoin(base_url, f"../j/j{player_id}.html"),
            photo_url=photo_url,
            nationality_code=country_code,
            nationality=countries.get(country_code) or _COUNTRY_FALLBACKS.get(country_code),
            position_code=position_code,
            position_name=_POSITION_NAMES[position_code],
            age_years=age_years,
            team=team,
        )
        results.append((player_id, goals, False))
    return results


def parse_top_page(
    source_html: str,
    *,
    team_catalog: Iterable[dict[str, Any]],
    base_url: str = TOP_URL,
) -> ParsedTop:
    """Parse a captured Destacados page without browser or network access.

    The catalog must be the existing normalized BDFutbol team catalog. Team
    identity is joined by the exact crest asset basename used by the source.
    """
    document = _TopDocumentParser()
    document.feed(source_html)
    team_catalog_by_crest, _ = _team_catalog(team_catalog)
    options = {key: dict(values) for key, values in document.options.items()}
    countries = options.get("paisos_destacats", {})
    if not countries:
        raise TopParseError("No se encontró el selector de países #paisos_destacats")
    category_options = tuple(options.get("tipdest", {}).items())
    expected_categories = category_options
    if len(category_options) != 6 or {value for value, _ in category_options} != set(_CATEGORY_DEFINITIONS):
        raise TopParseError("El selector #tipdest no contiene las seis categorías esperadas")
    if set(document.tables).intersection(_CATEGORY_DEFINITIONS) != set(_CATEGORY_DEFINITIONS):
        raise TopParseError("No se encontraron las seis tablas #jugs1, #jugs2, #jugs3, #jugs4, #jugs8 y #jugs9")
    foreigners_table = document.tables.get("foreigners")
    if foreigners_table is None:
        raise TopParseError("No se encontró table#tab_estran")

    js_data = _extract_destacats_js(source_html)
    players: dict[int, dict[str, Any]] = {}
    rankings: list[RankingRecord] = []
    ranking_player_ids: dict[str, list[int]] = {}
    category_counts: dict[str, int] = {}
    selected_ids: dict[str, set[int]] = {}

    for category_id, definition in _CATEGORY_DEFINITIONS.items():
        table = document.tables[category_id]
        expected_headers = _EXPECTED_HEADERS[category_id]
        if not table.rows or tuple(_cell_text(cell) for cell in table.rows[0].cells) != expected_headers:
            actual = tuple(_cell_text(cell) for cell in table.rows[0].cells) if table.rows else ()
            raise TopParseError(
                f"Encabezados inesperados en #{definition['container']}: {actual!r}"
            )
        parsed_rows: list[tuple[int, int | None, bool | None]] = []
        for rank, row in enumerate(table.rows[1:], start=1):
            player, metric_value, matches_played, selected = _player_from_ranking_row(
                row,
                category_id=category_id,
                base_url=base_url,
                countries=countries,
                teams_by_crest=team_catalog_by_crest,
            )
            _merge_player(players, **player)
            player_id = player["player_id"]
            parsed_rows.append((player_id, metric_value, selected))
            rankings.append(
                RankingRecord(
                    category=definition["category"],
                    rank=rank,
                    player_id=player_id,
                    metric=definition["metric"],
                    metric_value=metric_value,
                    unit=definition["unit"],
                    matches_played=matches_played,
                    source_record="html_table",
                    graph_selected_by_default=selected,
                )
            )
        if not parsed_rows:
            raise TopParseError(f"#{definition['container']} no contiene jugadores")
        if len({entry[0] for entry in parsed_rows}) != len(parsed_rows):
            raise TopParseError(f"IDs duplicados en #{definition['container']}")
        category = str(definition["category"])
        ranking_player_ids[category] = [entry[0] for entry in parsed_rows]
        selected_ids[category] = {
            entry[0] for entry in parsed_rows if entry[2] is True
        }
        category_counts[category] = len(parsed_rows)

    goals_tail = _source_goals_tail(
        js_data["LG"],
        base_url=base_url,
        countries=countries,
        teams_by_crest=team_catalog_by_crest,
        players=players,
    )
    start_rank = category_counts["goals"] + 1
    for offset, (player_id, goal_value, selected) in enumerate(goals_tail):
        rank = start_rank + offset
        rankings.append(
            RankingRecord(
                category="goals", rank=rank, player_id=player_id,
                metric="goals", metric_value=goal_value, unit="goals",
                matches_played=None, source_record="destacats_js_lg",
                graph_selected_by_default=selected,
            )
        )
        ranking_player_ids["goals"].append(player_id)
        category_counts["goals"] += 1
    if len(goals_tail) != len(js_data["LG"]):
        raise TopParseError("La cobertura de goles no coincide con DESTACATS_JS.LG")

    foreign_rows = [row for row in foreigners_table.rows if row.cells and row.cells[0].tag != "th"]
    if not foreigners_table.rows:
        raise TopParseError("#tab_estran no tiene encabezado")
    foreign_headers = tuple(_cell_text(cell) for cell in foreigners_table.rows[0].cells)
    expected_foreign_headers = (
        "", "Nombre", "País", "Pos", "Edad", "PJ", "Min", "G", "TA", "TR", "Club"
    )
    if foreign_headers != expected_foreign_headers:
        raise TopParseError(f"Encabezados inesperados en #tab_estran: {foreign_headers!r}")
    foreign_records: list[ForeignPlayerStatistics] = []
    foreign_ids: set[int] = set()
    for row in foreign_rows:
        if len(row.cells) < 11:
            raise TopParseError("Fila incompleta en #tab_estran")
        player_id = _player_id_from_row(row)
        if player_id in foreign_ids:
            raise TopParseError(f"ID duplicado en #tab_estran: {player_id}")
        foreign_ids.add(player_id)
        cells = row.cells
        name_cell, country_cell, position_cell = cells[1:4]
        age, matches, minutes, goals_value, yellow, red = (
            _integer(_cell_text(cells[index]), field, nullable=True)
            for index, field in zip(
                (4, 5, 6, 7, 8, 9),
                ("age_years", "matches_played", "minutes_played", "goals", "yellow_cards", "red_cards"),
                strict=True,
            )
        )
        player_link = next(
            (link for link in name_cell.links if re.search(r"(?:^|/)j\d+\.html", link.attrs.get("href") or "")),
            None,
        )
        if player_link is None:
            raise TopParseError(f"#tab_estran player_id={player_id} sin enlace de ficha")
        display_name = next(
            (_clean_text("".join(span.text)) for span in name_cell.spans if "font-weight-bold" in (span.attrs.get("class") or "").split()),
            _clean_text("".join(player_link.text)),
        )
        full_name = next(
            (_clean_text("".join(span.text)) for span in name_cell.spans if {"d-none", "d-md-block"}.issubset(set((span.attrs.get("class") or "").split()))),
            None,
        )
        country_code, country_name = _country(country_cell, countries)
        if not country_code or country_code == "espanya":
            raise TopParseError(f"Registro #tab_estran no es extranjero: player_id={player_id}")
        position_code, position_name = _position(position_cell)
        crest_cell = cells[10]
        crest = next(
            (image for image in crest_cell.images if "escut-mini" in (image.get("class") or "").split()),
            None,
        )
        if crest is None:
            raise TopParseError(f"Escudo de club ausente en #tab_estran player_id={player_id}")
        team = _resolve_team(crest, team_catalog_by_crest, player_id=player_id)
        photo = next(
            (image for image in cells[0].images if "mini-foto-jugador" in (image.get("class") or "").split()),
            None,
        )
        profile_url = _absolute(base_url, str(player_link.attrs.get("href")))
        _merge_player(
            players,
            player_id=player_id,
            display_name=display_name,
            full_name=full_name,
            profile_url=profile_url or "",
            photo_url=_absolute(base_url, photo.get("src")) if photo else None,
            nationality_code=country_code,
            nationality=country_name,
            position_code=position_code,
            position_name=position_name,
            age_years=age,
            team=team,
        )
        foreign_records.append(
            ForeignPlayerStatistics(
                player_id=player_id,
                matches_played=matches,
                minutes_played=minutes,
                goals=goals_value,
                yellow_cards=yellow,
                red_cards=red,
            )
        )
    if not foreign_records:
        raise TopParseError("No se extrajeron jugadores de #tab_estran")

    heading_match = re.search(
        r"Extranjeros\s+(\d+)\s*\(\s*([\d,.]+)\s*%\s*\)",
        document.foreign_heading,
        re.I,
    )
    if not heading_match:
        raise TopParseError(f"No se interpreta el encabezado de extranjeros: {document.foreign_heading!r}")
    source_foreigner_count = int(heading_match.group(1))
    source_percentage = float(heading_match.group(2).replace(",", "."))
    implied_denominator = round(source_foreigner_count / (source_percentage / 100)) if source_percentage else None
    if source_foreigner_count != len(foreign_records):
        raise TopParseError(
            f"#tab_estran contiene {len(foreign_records)} filas pero el encabezado indica {source_foreigner_count}"
        )

    progress: list[ProgressSeries] = []
    for category_id in ("1", "2", "3", "4"):
        definition = _CATEGORY_DEFINITIONS[category_id]
        series_key = str(definition["series"])
        source_series = js_data[series_key]
        ordered_player_ids = ranking_player_ids[str(definition["category"])]
        if len(source_series) != len(ordered_player_ids):
            raise TopParseError(
                f"{series_key} tiene {len(source_series)} series para "
                f"{len(ordered_player_ids)} jugadores en el ranking"
            )
        for index, (player_id, raw_values) in enumerate(zip(ordered_player_ids, source_series, strict=True)):
            if not isinstance(raw_values, list) or not raw_values:
                raise TopParseError(f"{series_key}[{index}] no es una serie no vacía")
            points: list[ProgressPoint] = []
            for matchday, raw_value in enumerate(raw_values, start=1):
                if raw_value is not None and (isinstance(raw_value, bool) or not isinstance(raw_value, int)):
                    raise TopParseError(f"{series_key}[{index}] contiene un dato no numérico")
                points.append(ProgressPoint(matchday=matchday, value=raw_value))
            matching_record = next(
                record for record in rankings
                if record.category == definition["category"] and record.player_id == player_id
            )
            if points[-1].value != matching_record.metric_value:
                raise TopParseError(
                    f"Serie {series_key} de player_id={player_id} termina en "
                    f"{points[-1].value}, pero el ranking muestra {matching_record.metric_value}"
                )
            progress.append(
                ProgressSeries(
                    category=definition["category"],
                    player_id=player_id,
                    metric=definition["metric"],
                    unit=definition["unit"],
                    points=tuple(points),
                    graph_selected_by_default=player_id in selected_ids[str(definition["category"])],
                )
            )

    if len({record.player_id for record in rankings if record.category == "goals"}) != category_counts["goals"]:
        raise TopParseError("El ranking de goles contiene IDs duplicados")
    all_points = {point.matchday for series in progress for point in series.points}
    if not all_points or all_points != set(range(1, max(all_points) + 1)):
        raise TopParseError("Las jornadas del gráfico no forman una secuencia desde la jornada 1")
    warnings = (
        "Las categorías distintas de Goles solo exponen las diez filas publicadas en sus tablas.",
        "La edad se conserva como edad mostrada al capturar; BDFutbol no publica aquí su fecha de referencia.",
        "El denominador del porcentaje de extranjeros no está publicado; el valor implícito es solo una inferencia.",
    )
    return ParsedTop(
        players=tuple(TopPlayer(**players[player_id]) for player_id in sorted(players)),
        rankings=tuple(rankings),
        progress=tuple(progress),
        foreigners=tuple(foreign_records),
        foreigners_summary=ForeignersSummary(
            source_count=source_foreigner_count,
            source_percentage=source_percentage,
            denominator_count=None,
            implied_denominator_count=implied_denominator,
            country_options=tuple(options.get("paisos_destacats", {}).items()),
        ),
        category_options=expected_categories,
        category_source_counts=category_counts,
        chart_matchdays=tuple(sorted(all_points)),
        see_all_available=document.see_all,
        warnings=warnings,
    )
