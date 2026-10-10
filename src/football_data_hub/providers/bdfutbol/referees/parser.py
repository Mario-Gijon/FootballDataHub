"""Parser offline semántico de la tabla `#tab_arb`."""

from __future__ import annotations

import re
from dataclasses import fields
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin

from ..context import SUPPORTED_SEASON, get_competition_context

from .models import (
    ParsedRefereePage,
    ParsedReferees,
    Referee,
    RefereeFilterOption,
    RefereeRow,
    RefereeScope,
    RefereeStatistics,
)

REFEREES_URL = get_competition_context(group=2).section_url("referees")
_REFEREE_ID = re.compile(r"(?:^|/)r/(r\d+)\.html(?:$|[?#])")
_SEASON_LABEL = re.compile(r"^\d{4}-\d{2}$")
_GROUP_SCOPES: dict[str, RefereeScope] = {
    "todos": "all",
    "grupo 1": "group1",
    "grupo 2": "group2",
}
_EXPECTED_HEADERS = (
    "",
    "",
    "",
    "nombre",
    "edad",
    "fecha",
    "lugar de nacimiento",
    "provincia",
    "p",
    "ta",
    "tr",
)


class RefereeParseError(ValueError):
    """La fuente no coincide con el contrato real de la tabla de árbitros."""


class _Cell:
    def __init__(self, tag: str, attrs: dict[str, str | None]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.text: list[str] = []
        self.images: list[dict[str, str | None]] = []
        self.links: list[dict[str, str | None]] = []


class _Row:
    def __init__(self) -> None:
        self.cells: list[_Cell] = []


class _SourceDocument(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_referee_table = False
        self.table_depth = 0
        self.table_count = 0
        self.rows: list[_Row] = []
        self.current_row: _Row | None = None
        self.current_cell: _Cell | None = None
        self.current_select: dict[str, object] | None = None
        self.current_option: dict[str, object] | None = None
        self.selects: list[dict[str, object]] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str | None]:
        return dict(attrs)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = self._attrs(attrs)
        if tag == "table":
            if not self.in_referee_table and values.get("id") == "tab_arb":
                self.in_referee_table = True
                self.table_depth = 1
                self.table_count += 1
            elif self.in_referee_table:
                self.table_depth += 1
            return

        if tag == "select":
            self.current_select = {"attrs": values, "options": []}
        elif tag == "option" and self.current_select is not None:
            self.current_option = {
                "raw_value": values.get("value"),
                "selected": "selected" in values,
                "text": [],
            }

        if not self.in_referee_table:
            return
        if tag == "tr" and self.current_row is None:
            self.current_row = _Row()
        elif tag in {"th", "td"} and self.current_row is not None:
            self.current_cell = _Cell(tag, values)
        elif tag == "img" and self.current_cell is not None:
            self.current_cell.images.append(values)
        elif tag == "a" and self.current_cell is not None:
            self.current_cell.links.append(values)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "option" and self.current_option is not None:
            option = self.current_option
            option["label"] = _clean_text("".join(option["text"]))
            assert self.current_select is not None
            options = self.current_select["options"]
            assert isinstance(options, list)
            options.append(option)
            self.current_option = None
        elif tag == "select" and self.current_select is not None:
            self.selects.append(_finish_select(self.current_select))
            self.current_select = None

        if not self.in_referee_table:
            return
        if tag in {"th", "td"} and self.current_cell is not None:
            self.current_cell.text = [_clean_text("".join(self.current_cell.text))]
            assert self.current_row is not None
            self.current_row.cells.append(self.current_cell)
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            self.rows.append(self.current_row)
            self.current_row = None
        elif tag == "table":
            self.table_depth -= 1
            if self.table_depth <= 0:
                self.in_referee_table = False
                self.table_depth = 0

    def handle_data(self, data: str) -> None:
        if self.current_option is not None:
            text = self.current_option["text"]
            assert isinstance(text, list)
            text.append(data)
        if self.current_cell is not None:
            self.current_cell.text.append(data)


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _finish_select(select: dict[str, object]) -> dict[str, object]:
    options = select["options"]
    assert isinstance(options, list)
    for option in options:
        raw_value = option["raw_value"]
        option["value"] = str(raw_value) if raw_value is not None else str(option["label"])
    if options and not any(bool(option["selected"]) for option in options):
        options[0]["selected"] = True
    selected = next((option for option in options if option["selected"]), None)
    select["value"] = selected["value"] if selected else None
    select["selected_label"] = selected["label"] if selected else None
    return select


def _integer(value: str, field_name: str) -> int | None:
    text = _clean_text(value)
    if text in {"", "-", "–", "—"}:
        return None
    try:
        result = int(text)
    except ValueError as exc:
        raise RefereeParseError(f"Valor no entero en {field_name}: {text!r}") from exc
    if result < 0:
        raise RefereeParseError(f"Valor negativo en {field_name}: {result}")
    return result


def _date(value: str) -> date | None:
    text = _clean_text(value)
    if text in {"", "-", "–", "—"}:
        return None
    try:
        return datetime.strptime(text, "%d/%m/%Y").date()
    except ValueError as exc:
        raise RefereeParseError(f"Fecha de nacimiento no interpretable: {text!r}") from exc


def _absolute(base_url: str, value: str | None) -> str | None:
    if not value:
        return None
    result = urljoin(base_url, value)
    if not result.startswith("https://www.bdfutbol.com/"):
        raise RefereeParseError(f"URL fuera del origen BDFutbol: {result}")
    return result


def _select_options(
    selects: list[dict[str, object]],
    *,
    base_url: str,
) -> tuple[tuple[RefereeFilterOption, ...], tuple[RefereeFilterOption, ...]]:
    group_select = None
    season_select = None
    for select in selects:
        options = select["options"]
        assert isinstance(options, list)
        labels = {str(option["label"]).casefold() for option in options}
        if set(_GROUP_SCOPES) <= labels:
            group_select = select
        if any(str(option["label"]) == SUPPORTED_SEASON for option in options) and any(
            _SEASON_LABEL.fullmatch(str(option["label"])) for option in options
        ):
            season_select = select
    if group_select is None:
        raise RefereeParseError("No se encontró el selector Todos/Grupo 1/Grupo 2")
    if season_select is None:
        raise RefereeParseError("No se encontró el selector de temporadas")

    def convert(select: dict[str, object], *, is_group: bool) -> tuple[RefereeFilterOption, ...]:
        options = select["options"]
        assert isinstance(options, list)
        converted = []
        for option in options:
            label = str(option["label"])
            raw_value = str(option["value"])
            scope = _GROUP_SCOPES.get(label.casefold()) if is_group else None
            is_url = ".html" in raw_value and " " not in raw_value
            converted.append(
                RefereeFilterOption(
                    label=label,
                    value=raw_value,
                    selected=bool(option["selected"]),
                    target_url=_absolute(base_url, raw_value) if is_url else None,
                    scope=scope,
                )
            )
        return tuple(converted)

    group_options = convert(group_select, is_group=True)
    season_options = convert(season_select, is_group=False)
    if not any(option.label == SUPPORTED_SEASON and option.selected for option in season_options):
        raise RefereeParseError("La captura no tiene seleccionada la temporada 2026-27")
    return group_options, season_options


def parse_referee_page(
    source_html: str,
    *,
    scope: RefereeScope,
    source_url: str,
) -> ParsedRefereePage:
    """Parsea una página ya adquirida; no accede a red ni a un navegador."""
    if scope not in {"all", "group1", "group2"}:
        raise RefereeParseError(f"Ámbito desconocido: {scope!r}")
    if SUPPORTED_SEASON not in source_html:
        raise RefereeParseError("El documento no contiene la temporada 2026-27")
    document = _SourceDocument()
    document.feed(source_html)
    if document.table_count != 1 or not document.rows:
        raise RefereeParseError("No se encontró exactamente una tabla table#tab_arb")

    header = document.rows[0].cells
    headers = tuple(_clean_text(cell.text[0]).casefold() for cell in header)
    if headers != _EXPECTED_HEADERS:
        raise RefereeParseError(f"Cabeceras inesperadas en #tab_arb: {headers!r}")
    header_titles = {index: (cell.attrs.get("title") or "").casefold() for index, cell in enumerate(header)}
    if (
        header_titles.get(5) != "fecha de nacimiento"
        or header_titles.get(8) != "partidos"
        or header_titles.get(9) != "tarjetas amarillas"
        or header_titles.get(10) != "tarjetas rojas"
    ):
        raise RefereeParseError("Los atributos title no confirman la semántica de fecha/P/TA/TR")

    rows: list[RefereeRow] = []
    ids: set[str] = set()
    for source_row in document.rows[1:]:
        if len(source_row.cells) != len(_EXPECTED_HEADERS):
            raise RefereeParseError(
                f"Fila de árbitro con {len(source_row.cells)} celdas; se esperaban {len(_EXPECTED_HEADERS)}"
            )
        cells = source_row.cells
        profile_link = next(
            (
                link
                for link in cells[3].links
                if _REFEREE_ID.search(link.get("href") or "")
            ),
            None,
        )
        if profile_link is None:
            raise RefereeParseError("Fila sin enlace de perfil con ID BDFutbol")
        raw_profile_url = profile_link.get("href") or ""
        id_match = _REFEREE_ID.search(raw_profile_url)
        assert id_match is not None
        referee_id = id_match.group(1)
        if referee_id in ids:
            raise RefereeParseError(f"ID duplicado dentro de #tab_arb: {referee_id}")
        ids.add(referee_id)

        order = _integer(cells[0].text[0], "published_order")
        if order is None:
            raise RefereeParseError(f"Falta el orden publicado para {referee_id}")
        photo_src = next(
            (
                image.get("src")
                for image in cells[1].images
                if "mini-foto-jugador" in (image.get("class") or "").split()
            ),
            None,
        )
        flag_src = next((image.get("src") for image in cells[2].images if image.get("src")), None)
        statistics_link = next(
            (link.get("href") for link in cells[8].links if link.get("href")),
            None,
        )
        age = _integer(cells[4].text[0], "age_years")
        if age is not None and age > 120:
            raise RefereeParseError(f"Edad fuera de rango para {referee_id}: {age}")
        referee = Referee(
            referee_id=referee_id,
            display_name=_clean_text(cells[3].text[0]),
            full_name=None,
            profile_url=_absolute(source_url, raw_profile_url) or "",
            photo_url=_absolute(source_url, photo_src),
            flag_url=_absolute(source_url, flag_src),
            nationality=None,
            nationality_code=None,
            age_years=age,
            birth_date=_date(cells[5].text[0]),
            birthplace=_clean_text(cells[6].text[0]) or None,
            province=_clean_text(cells[7].text[0]) or None,
        )
        statistics = RefereeStatistics(
            referee_id=referee_id,
            season=SUPPORTED_SEASON,
            group_scope=scope,
            published_order=order,
            matches_officiated=_integer(cells[8].text[0], "matches_officiated"),
            yellow_cards=_integer(cells[9].text[0], "yellow_cards"),
            red_cards=_integer(cells[10].text[0], "red_cards"),
            statistics_url=_absolute(source_url, statistics_link),
            source_page_url=source_url,
        )
        if not referee.display_name:
            raise RefereeParseError(f"Nombre vacío para {referee_id}")
        rows.append(RefereeRow(referee=referee, statistics=statistics))

    if not rows:
        raise RefereeParseError("#tab_arb no contiene árbitros")
    group_options, season_options = _select_options(document.selects, base_url=source_url)
    selected_group = next((option for option in group_options if option.selected), None)
    if selected_group is None or selected_group.scope != scope:
        raise RefereeParseError(
            f"El ámbito de la URL ({scope}) no coincide con el selector "
            f"({selected_group.label if selected_group else 'sin selección'})"
        )
    return ParsedRefereePage(
        scope=scope,
        source_url=source_url,
        rows=tuple(rows),
        group_options=group_options,
        season_options=season_options,
    )


def merge_referee_pages(pages: tuple[ParsedRefereePage, ...]) -> ParsedReferees:
    """Une identidades por ID exacto y conserva estadísticas de cada ámbito."""
    by_scope = {page.scope: page for page in pages}
    if set(by_scope) != {"all", "group1", "group2"}:
        raise RefereeParseError("Se requieren capturas explícitas de all, group1 y group2")
    catalog: dict[str, Referee] = {}
    conflicts: list[dict[str, object]] = []
    statistics: list[RefereeStatistics] = []
    for scope in ("all", "group1", "group2"):
        page = by_scope[scope]  # type: ignore[index]
        for row in page.rows:
            known = catalog.get(row.referee.referee_id)
            if known is None:
                catalog[row.referee.referee_id] = row.referee
            else:
                changed = {
                    field.name: {
                        "catalog": getattr(known, field.name).isoformat()
                        if isinstance(getattr(known, field.name), date)
                        else getattr(known, field.name),
                        "scope": getattr(row.referee, field.name).isoformat()
                        if isinstance(getattr(row.referee, field.name), date)
                        else getattr(row.referee, field.name),
                    }
                    for field in fields(Referee)
                    if getattr(known, field.name) != getattr(row.referee, field.name)
                }
                if changed:
                    conflicts.append({"referee_id": row.referee.referee_id, "scope": scope, "fields": changed})
            statistics.append(row.statistics)

    aggregate_group_options = by_scope["all"].group_options
    season_options = by_scope["all"].season_options
    return ParsedReferees(
        referees=tuple(catalog[key] for key in sorted(catalog)),
        statistics=tuple(statistics),
        group_options=aggregate_group_options,
        season_options=season_options,
        scope_counts={scope: len(by_scope[scope].rows) for scope in ("all", "group1", "group2")},
        identity_conflicts=tuple(conflicts),
    )
