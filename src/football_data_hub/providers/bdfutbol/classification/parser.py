"""Parser semántico del HTML renderizado de la clasificación."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .models import (
    ParsedClassification,
    ProgressContext,
    ProgressRecord,
    PositionChange,
    SportsZone,
    TeamStanding,
)


class ClassificationParseError(ValueError):
    """El documento no contiene una clasificación interpretable con seguridad."""


@dataclass(slots=True)
class _Link:
    attrs: dict[str, str | None]
    text: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Cell:
    attrs: dict[str, str | None]
    text: list[str] = field(default_factory=list)
    links: list[_Link] = field(default_factory=list)
    images: list[dict[str, str | None]] = field(default_factory=list)


@dataclass(slots=True)
class _Row:
    attrs: dict[str, str | None]
    cells: list[_Cell] = field(default_factory=list)


class _DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_classification_table = False
        self.table_depth = 0
        self.current_row: _Row | None = None
        self.current_cell: _Cell | None = None
        self.current_link: _Link | None = None
        self.rows: list[_Row] = []
        self.scripts: list[str] = []
        self.in_script = False
        self.current_script: list[str] = []
        self.in_jornada_select = False
        self.current_option: dict[str, object] | None = None
        self.jornada_options: list[tuple[int, str]] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str | None]:
        return {key: value for key, value in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = self._attrs(attrs)
        if tag == "script":
            self.in_script = True
            self.current_script = []
        if tag == "select" and values.get("id") == "jornada":
            self.in_jornada_select = True
        if tag == "option" and self.in_jornada_select:
            self.current_option = {"attrs": values, "text": []}

        if tag == "table":
            if not self.in_classification_table and values.get("id") == "classific":
                self.in_classification_table = True
                self.table_depth = 1
            elif self.in_classification_table:
                self.table_depth += 1
            return

        if not self.in_classification_table or self.table_depth != 1:
            return
        if tag == "tr":
            self.current_row = _Row(values)
            self.current_cell = None
            self.current_link = None
        elif tag in {"td", "th"} and self.current_row is not None:
            self.current_cell = _Cell(values)
        elif tag == "a" and self.current_cell is not None:
            self.current_link = _Link(values)
        elif tag == "img" and self.current_cell is not None:
            self.current_cell.images.append(values)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.in_script:
            self.scripts.append("".join(self.current_script))
            self.current_script = []
            self.in_script = False
        if tag == "option" and self.current_option is not None:
            attrs = self.current_option["attrs"]
            text = _clean_text("".join(self.current_option["text"]))
            if isinstance(attrs, dict) and self.in_jornada_select:
                value = attrs.get("value")
                match = re.search(r"\d+", str(value or ""))
                date_match = re.search(r"\((\d{2}/\d{2}/\d{4})\)", text)
                if match and date_match:
                    from datetime import datetime

                    round_number = int(match.group())
                    date_value = datetime.strptime(date_match.group(1), "%d/%m/%Y")
                    self.jornada_options.append((round_number, date_value.date().isoformat()))
            self.current_option = None
        if tag == "select" and self.in_jornada_select:
            self.in_jornada_select = False

        if not self.in_classification_table:
            return
        if tag in {"td", "th"} and self.current_cell is not None:
            if self.current_row is not None:
                self.current_row.cells.append(self.current_cell)
            self.current_cell = None
            self.current_link = None
        elif tag == "a" and self.current_link is not None:
            if self.current_cell is not None:
                self.current_cell.links.append(self.current_link)
            self.current_link = None
        elif tag == "tr" and self.current_row is not None:
            self.rows.append(self.current_row)
            self.current_row = None
            self.current_cell = None
            self.current_link = None
        elif tag == "table":
            self.table_depth -= 1
            if self.table_depth <= 0:
                self.table_depth = 0
                self.in_classification_table = False
                self.current_row = None
                self.current_cell = None
                self.current_link = None

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.current_script.append(data)
            return
        if self.current_option is not None:
            text = self.current_option["text"]
            if isinstance(text, list):
                text.append(data)
        if self.in_classification_table and self.table_depth == 1:
            if self.current_cell is not None:
                self.current_cell.text.append(data)
            if self.current_link is not None:
                self.current_link.text.append(data)


def _clean_text(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


_HEADER_NAMES = ("PTS.", "PJ", "PG", "PE", "PP", "GF", "GC", "TA", "TR")
_HEADER_TITLES = (
    "Puntos",
    "Partidos Jugados",
    "Ganados",
    "Empatados",
    "Perdidos",
    "Goles a favor",
    "Goles en contra",
    "Tarjetas amarillas",
    "Tarjetas rojas",
)
_STAT_FIELDS = (
    "points",
    "matches_played",
    "wins",
    "draws",
    "losses",
    "goals_for",
    "goals_against",
    "yellow_cards",
    "red_cards",
)
_ZONE_MAP: dict[str, SportsZone] = {
    "prom_puja1": "direct_promotion",
    "prom_puja": "promotion",
    "res": "stay",
    "prom_baixa": "relegation",
}


def _parse_int(value: str, *, field_name: str, nullable: bool = True) -> int | None:
    text = _clean_text(value)
    if text in {"", "-", "–", "—", "−"}:
        if nullable:
            return None
        raise ClassificationParseError(f"Falta el valor obligatorio {field_name}")
    try:
        return int(text)
    except ValueError as exc:
        raise ClassificationParseError(
            f"Valor no numérico en {field_name}: {text!r}"
        ) from exc


def _absolute_url(base_url: str, value: str | None) -> str | None:
    if not value:
        return None
    return urljoin(base_url, value)


def _check_header(row: _Row) -> None:
    if len(row.cells) < 13:
        raise ClassificationParseError(
            f"#classific tiene {len(row.cells)} columnas de encabezado; se esperaban al menos 13"
        )
    for offset, (expected_name, expected_title) in enumerate(
        zip(_HEADER_NAMES, _HEADER_TITLES, strict=True), start=4
    ):
        cell = row.cells[offset]
        label = _clean_text("".join(cell.text))
        title = _clean_text(str(cell.attrs.get("title") or ""))
        if label.casefold() != expected_name.casefold() or title.casefold() != expected_title.casefold():
            raise ClassificationParseError(
                f"Encabezado inesperado en columna {offset}: "
                f"texto={label!r}, title={title!r}"
            )


def _parse_standings(
    rows: list[_Row], *, base_url: str, expected_teams: int
) -> tuple[TeamStanding, ...]:
    if not rows:
        raise ClassificationParseError("No se encontró table#classific")
    _check_header(rows[0])
    team_rows = [row for row in rows[1:] if row.attrs.get("data-ideq") is not None]
    if len(team_rows) != expected_teams:
        raise ClassificationParseError(
            f"Clasificación incompleta: {len(team_rows)} equipos; se esperaban {expected_teams}"
        )

    standings: list[TeamStanding] = []
    seen_ids: set[int] = set()
    for row in team_rows:
        if len(row.cells) < 13:
            raise ClassificationParseError(
                f"Fila de equipo {row.attrs.get('data-ideq')} con solo {len(row.cells)} celdas"
            )
        team_id = _parse_int(
            str(row.attrs.get("data-ideq") or ""), field_name="team_id", nullable=False
        )
        assert team_id is not None
        if team_id in seen_ids:
            raise ClassificationParseError(f"team_id duplicado: {team_id}")
        seen_ids.add(team_id)

        position_cell = row.cells[1]
        crest_cell = row.cells[2]
        team_cell = row.cells[3]
        name_link = next(
            (link for link in team_cell.links if _clean_text("".join(link.text))), None
        )
        team_name = _clean_text("".join(name_link.text)) if name_link else _clean_text("".join(team_cell.text))
        if not team_name:
            raise ClassificationParseError(f"Falta el nombre para team_id={team_id}")

        raw_values: dict[str, str] = {
            "position": _clean_text("".join(position_cell.text)),
        }
        stat_values: dict[str, int | None] = {}
        for index, field_name in enumerate(_STAT_FIELDS, start=4):
            raw = _clean_text("".join(row.cells[index].text))
            raw_values[field_name] = raw
            stat_values[field_name] = _parse_int(raw, field_name=field_name)

        position = _parse_int(raw_values["position"], field_name="position", nullable=False)
        assert position is not None
        position_classes = tuple(
            token for token in str(position_cell.attrs.get("class") or "").split() if token
        )
        zone_code = next((token for token in position_classes if token in _ZONE_MAP), None)
        movement_image = next(
            (
                image
                for image in position_cell.images
                if urlsplit(str(image.get("src") or "")).path.rsplit("/", 1)[-1]
                in {"up.png", "dn.png", "none.png"}
            ),
            None,
        )
        movement_src = _absolute_url(
            base_url, str(movement_image.get("src")) if movement_image and movement_image.get("src") else None
        )
        movement_name = (
            urlsplit(str(movement_image.get("src") or "")).path.rsplit("/", 1)[-1]
            if movement_image
            else ""
        )
        position_change: PositionChange | None = {
            "up.png": "up",
            "dn.png": "down",
            "none.png": "same",
        }.get(movement_name)  # type: ignore[assignment]
        crest = next(
            (
                image
                for image in crest_cell.images
                if "escut-mini" in str(image.get("class") or "").split()
            ),
            None,
        )
        crest_url = _absolute_url(
            base_url, str(crest.get("src")) if crest and crest.get("src") else None
        )
        team_url = _absolute_url(base_url, str(name_link.attrs.get("href"))) if name_link else None

        standings.append(
            TeamStanding(
                team_id=team_id,
                team_name=team_name,
                team_url=team_url,
                crest_url=crest_url,
                position=position,
                points=stat_values["points"],
                matches_played=stat_values["matches_played"],
                wins=stat_values["wins"],
                draws=stat_values["draws"],
                losses=stat_values["losses"],
                goals_for=stat_values["goals_for"],
                goals_against=stat_values["goals_against"],
                yellow_cards=stat_values["yellow_cards"],
                red_cards=stat_values["red_cards"],
                position_change=position_change,
                zone_code=zone_code,
                sports_zone=_ZONE_MAP.get(zone_code) if zone_code else None,
                position_cell_classes=position_classes,
                movement_icon_src=movement_src,
                raw_values=raw_values,
            )
        )
    return tuple(standings)


def _parse_arrays(scripts: list[str], variable: str) -> dict[int, list[int]]:
    text = "\n".join(scripts)
    pattern = re.compile(
        rf"\b{re.escape(variable)}\s*\[\s*(\d+)\s*\]\s*=\s*new\s+Array\(([^)]*)\)",
        re.IGNORECASE,
    )
    arrays: dict[int, list[int]] = {}
    for match in pattern.finditer(text):
        key = int(match.group(1))
        raw_items = [item.strip() for item in match.group(2).split(",")]
        try:
            values = [int(item) for item in raw_items if item]
        except ValueError as exc:
            raise ClassificationParseError(
                f"Arreglo JavaScript {variable}[{key}] no numérico"
            ) from exc
        arrays[key] = values
    return arrays


def _parse_played_rounds(scripts: list[str]) -> int:
    text = "\n".join(scripts)
    match = re.search(r"\bjornades_jugades\s*=\s*(\d+)\s*;", text)
    if not match:
        raise ClassificationParseError("No se encontró jornades_jugades en JavaScript")
    value = int(match.group(1))
    if not 0 <= value <= 38:
        raise ClassificationParseError(f"jornades_jugades fuera de rango: {value}")
    return value


def _parse_progress(
    scripts: list[str],
    team_ids: tuple[int, ...],
    matchday_dates: dict[int, str],
) -> tuple[tuple[ProgressRecord, ...], int, tuple[str, ...]]:
    played_rounds = _parse_played_rounds(scripts)
    positions = _parse_arrays(scripts, "PRG")
    points = _parse_arrays(scripts, "PRGP")
    goals_for = _parse_arrays(scripts, "PRGGF")
    goals_against = _parse_arrays(scripts, "PRGGC")
    warnings: list[str] = []
    output: list[ProgressRecord] = []

    for matchday in range(1, played_rounds + 1):
        ranked_ids = positions.get(matchday)
        if ranked_ids is None:
            warnings.append(f"PRG no contiene Jornada {matchday}")
            ranked_ids = []
        if len(ranked_ids) != len(team_ids) or len(set(ranked_ids)) != len(ranked_ids):
            warnings.append(f"PRG[{matchday}] no es una permutación de los equipos")
        position_by_id = {team_id: index for index, team_id in enumerate(ranked_ids, start=1)}
        for team_id in team_ids:
            def item_at(source: dict[int, list[int]], *, label: str) -> int | None:
                values = source.get(team_id)
                if values is None or matchday > len(values):
                    warnings.append(f"{label}[{team_id}] no contiene Jornada {matchday}")
                    return None
                return values[matchday - 1]

            output.append(
                ProgressRecord(
                    team_id=team_id,
                    matchday=matchday,
                    matchday_date=matchday_dates.get(matchday),
                    position=position_by_id.get(team_id),
                    points=item_at(points, label="PRGP"),
                    goals_for=item_at(goals_for, label="PRGGF"),
                    goals_against=item_at(goals_against, label="PRGGC"),
                )
            )
    return tuple(output), played_rounds, tuple(dict.fromkeys(warnings))


def validate_page_structure(html: str, *, expected_teams: int = 20) -> tuple[str, ...]:
    """Return structural errors suitable for ``BDFutbolAccess`` validation."""
    parser = _DocumentParser()
    parser.feed(html)
    if not parser.rows:
        return ("No se encontró table#classific",)
    try:
        _parse_standings(
            parser.rows,
            base_url="https://www.bdfutbol.com/",
            expected_teams=expected_teams,
        )
    except ClassificationParseError as exc:
        return (str(exc),)
    return ()


def parse_classification_page(
    html: str,
    *,
    base_url: str,
    expected_teams: int = 20,
) -> ParsedClassification:
    """Parsea clasificación y progreso sin ejecutar el JavaScript de la fuente."""
    parser = _DocumentParser()
    parser.feed(html)
    standings = _parse_standings(
        parser.rows, base_url=base_url, expected_teams=expected_teams
    )
    matchday_dates = dict(parser.jornada_options)
    progress, played_rounds, warnings = _parse_progress(
        parser.scripts,
        tuple(row.team_id for row in standings),
        matchday_dates,
    )
    return ParsedClassification(
        standings=standings,
        progress=progress,
        progress_context=ProgressContext(
            classification_type="general",
            postponed_policy="source_defined_unknown",
            range_type="all",
            source_independent_of_standings_filters=True,
            available_through_matchday=played_rounds,
        ),
        matchday_dates=matchday_dates,
        played_matchdays=played_rounds,
        progress_warnings=warnings,
    )
