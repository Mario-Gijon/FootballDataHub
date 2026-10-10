"""Extracción del calendario y resultados embebidos en la página de BDFutbol."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin

from football_data_hub.domain.classification.models import MatchResult, Team

from .models import ParsedClassification
from .parser import _clean_text


class MatchParseError(ValueError):
    """La captura no permite reconciliar el calendario con sus resultados."""


@dataclass(slots=True)
class _Goal:
    attrs: dict[str, str | None]
    text: list[str]


@dataclass(slots=True)
class _Cell:
    tag: str
    attrs: dict[str, str | None]
    text: list[str]
    links: list[str]
    goals: list[_Goal]


@dataclass(slots=True)
class _Row:
    attrs: dict[str, str | None]
    cells: list[_Cell]


class _ResultatsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_resultats = False
        self.div_depth = 0
        self.current_row: _Row | None = None
        self.current_cell: _Cell | None = None
        self.current_goal: _Goal | None = None
        self.rows: list[_Row] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "div" and values.get("id") == "resultats" and not self.in_resultats:
            self.in_resultats = True
            self.div_depth = 1
            return
        if not self.in_resultats:
            return
        if tag == "div":
            self.div_depth += 1
            if self.current_cell is not None and "resultat-gols" in (
                values.get("class") or ""
            ).split():
                self.current_goal = _Goal(values, [])
                self.current_cell.goals.append(self.current_goal)
        elif tag == "tr":
            self.current_row = _Row(values, [])
            self.current_cell = None
        elif tag in {"td", "th"} and self.current_row is not None:
            self.current_cell = _Cell(tag, values, [], [], [])
        elif tag == "a" and self.current_cell is not None:
            href = values.get("href")
            if href:
                self.current_cell.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if not self.in_resultats:
            return
        if tag in {"td", "th"} and self.current_cell is not None:
            if self.current_row is not None:
                self.current_row.cells.append(self.current_cell)
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            self.rows.append(self.current_row)
            self.current_row = None
            self.current_cell = None
        elif tag == "div":
            if self.current_goal is not None:
                self.current_goal = None
            self.div_depth -= 1
            if self.div_depth <= 0:
                self.div_depth = 0
                self.in_resultats = False

    def handle_data(self, data: str) -> None:
        if not self.in_resultats:
            return
        if self.current_cell is not None:
            self.current_cell.text.append(data)
        if self.current_goal is not None:
            self.current_goal.text.append(data)


def _parse_source_arrays(source_html: str) -> tuple[dict[int, str], list[tuple[int, dict[str, str]]]]:
    names: dict[int, str] = {}
    for match in re.finditer(r"SE\[(\d+)\]=(\"(?:\\.|[^\"\\])*\");", source_html):
        index = int(match.group(1))
        try:
            names[index] = str(json.loads(match.group(2)).split("|", 1)[1])
        except (ValueError, IndexError, TypeError) as exc:
            raise MatchParseError(f"No se puede interpretar SE[{index}]") from exc

    records: list[tuple[int, dict[str, str]]] = []
    for match in re.finditer(r"SP\[(\d+)\]\.push\((\{.*?\})\);", source_html, re.S):
        try:
            record = json.loads(match.group(2))
        except json.JSONDecodeError as exc:
            raise MatchParseError("Un registro SP no contiene JSON válido") from exc
        if not isinstance(record, dict) or not all(
            isinstance(key, str) and isinstance(value, (str, int))
            for key, value in record.items()
        ):
            raise MatchParseError("Un registro SP tiene campos inesperados")
        records.append((int(match.group(1)), {key: str(value) for key, value in record.items()}))
    if not names or not records:
        raise MatchParseError("No se encontraron las estructuras SE y SP")
    return names, records


def _parse_date(value: str, *, field: str) -> date:
    try:
        return datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError as exc:
        raise MatchParseError(f"Fecha inválida en {field}: {value!r}") from exc


def _parse_nonnegative(raw: str, *, field: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise MatchParseError(f"Valor no numérico en {field}: {raw!r}") from exc
    if value < 0:
        raise MatchParseError(f"Valor negativo inesperado en {field}: {value}")
    return value


def _parse_result_rows(source_html: str) -> dict[int, list[tuple[int, _Row]]]:
    parser = _ResultatsParser()
    parser.feed(source_html)
    by_round: dict[int, list[tuple[int, _Row]]] = {}
    row_index_by_round: Counter[int] = Counter()
    for row in parser.rows:
        if "jornadai" not in (row.attrs.get("class") or "").split():
            continue
        if any(cell.tag == "th" for cell in row.cells):
            continue
        round_value = row.attrs.get("data-jornada")
        if round_value is None:
            match_round = re.search(r"\bij(\d+)\b", row.attrs.get("class") or "")
            round_value = match_round.group(1) if match_round else None
        if round_value is None:
            raise MatchParseError("Fila de partido sin jornada identificable")
        matchday = int(round_value)
        row_index_by_round[matchday] += 1
        by_round.setdefault(matchday, []).append((row_index_by_round[matchday], row))
    return by_round


def _result_row_indexes(
    rows: list[tuple[int, _Row]],
) -> tuple[dict[str, tuple[int, _Row]], dict[tuple[str, str, str], tuple[int, _Row]]]:
    by_match_id: dict[str, tuple[int, _Row]] = {}
    by_fixture: dict[tuple[str, str, str], tuple[int, _Row]] = {}
    for row_index, row in rows:
        if len(row.cells) < 4:
            raise MatchParseError(f"Fila de #resultats {row_index} incompleta")
        fixture = (
            _cell_text(row.cells[0]),
            _cell_text(row.cells[1]),
            _cell_text(row.cells[3]),
        )
        if fixture in by_fixture:
            raise MatchParseError(f"Fila fixture duplicada en #resultats: {fixture}")
        by_fixture[fixture] = (row_index, row)
        for match_id in _source_ids(row):
            if match_id in by_match_id:
                raise MatchParseError(f"ID de partido repetido en filas de #resultats: {match_id}")
            by_match_id[match_id] = (row_index, row)
    return by_match_id, by_fixture


def _cell_text(cell: _Cell) -> str:
    return _clean_text("".join(cell.text))


def _goal_value(goal: _Goal, field: str) -> int:
    return _parse_nonnegative(_clean_text("".join(goal.text)), field=field)


def _source_ids(row: _Row) -> set[str]:
    return {
        match.group(1)
        for cell in row.cells
        for href in cell.links
        if (match := re.search(r"[?&]id=(\d+)", href)) is not None
    }


def _validate_result_row(
    row: _Row,
    *,
    matchday: int,
    matchday_row_index: int,
    match_id: str,
    source_match_date: date,
    home_name: str,
    away_name: str,
    played: bool,
    source_fields: dict[str, str],
    base_url: str,
) -> str | None:
    if len(row.cells) < 6:
        raise MatchParseError(
            f"#resultats J{matchday} fila {matchday_row_index} tiene menos de seis celdas"
        )
    observed_date = _parse_date(_cell_text(row.cells[0]), field="#resultats.date")
    observed_home = _cell_text(row.cells[1])
    observed_away = _cell_text(row.cells[3])
    if observed_date != source_match_date:
        raise MatchParseError(f"Fecha distinta entre SP y #resultats para id={match_id}")
    if observed_home != home_name or observed_away != away_name:
        raise MatchParseError(f"Equipos distintos entre SP y #resultats para id={match_id}")

    goals = row.cells[2].goals
    if played:
        if len(goals) != 2:
            raise MatchParseError(f"Falta un marcador en #resultats para id={match_id}")
        score = tuple(_goal_value(goal, "#resultats.goals") for goal in goals)
        if score != (int(source_fields["g1"]), int(source_fields["g2"])):
            raise MatchParseError(f"Marcador distinto entre SP y #resultats para id={match_id}")
        for goal, yellow_key, red_key in zip(
            goals, ("tg1", "tg2"), ("tv1", "tv2"), strict=True
        ):
            yellow = goal.attrs.get("data-tg")
            if (yellow is None and int(source_fields[yellow_key]) != 0) or (
                yellow is not None and int(yellow) != int(source_fields[yellow_key])
            ):
                raise MatchParseError(f"Tarjetas amarillas distintas entre fuentes para id={match_id}")
            red = goal.attrs.get("data-tv")
            # BDFutbol omite data-tg/data-tv cuando el valor es cero; SP lo conserva.
            if (red is None and int(source_fields[red_key]) != 0) or (
                red is not None and int(red) != int(source_fields[red_key])
            ):
                raise MatchParseError(f"Tarjetas rojas distintas entre fuentes para id={match_id}")
        ids = _source_ids(row)
        if ids != {match_id}:
            raise MatchParseError(f"ID de partido distinto entre SP y #resultats: {ids} / {match_id}")
        href = next(
            (
                href
                for cell in row.cells
                for href in cell.links
                if re.search(r"[?&]id=\d+", href)
            ),
            None,
        )
        return urljoin(base_url, href) if href else None

    if goals:
        raise MatchParseError(f"#resultats muestra marcador pero SP no para id={match_id}")
    ids = _source_ids(row)
    if ids and ids != {match_id}:
        raise MatchParseError(f"ID distinto en fila no disputada de #resultats: {ids}")
    return None


def extract_matches(
    source_html: str,
    parsed_classification: ParsedClassification,
    *,
    base_url: str,
    captured_at: datetime | date | None = None,
) -> tuple[tuple[Team, ...], tuple[MatchResult, ...]]:
    """Une los registros SP con las filas del calendario oculto #resultats.

    La tabla de clasificación aporta el catálogo estable de equipos. El nombre
    de SE solo se usa como puente entre el índice interno de SP y ese catálogo;
    cada unión se contrasta también con la fila de local/visitante y el ID de
    partido visible en #resultats cuando hay un marcador.
    """
    teams = tuple(
        Team(
            team_id=item.team_id,
            name=item.team_name,
            team_url=item.team_url,
            crest_url=item.crest_url,
        )
        for item in parsed_classification.standings
    )
    if len(teams) != 20 or len({team.team_id for team in teams}) != 20:
        raise MatchParseError("El catálogo de #classific no contiene 20 equipos con ID único")
    team_by_name = {team.name: team for team in teams}
    if len(team_by_name) != len(teams):
        raise MatchParseError("El catálogo contiene nombres ambiguos para resolver SE")

    source_names, source_records = _parse_source_arrays(source_html)
    if len(source_names) != 20 or set(source_names) != set(range(20)):
        raise MatchParseError("SE no contiene los 20 índices esperados")
    source_team_by_index: dict[int, Team] = {}
    for index, name in source_names.items():
        team = team_by_name.get(name)
        if team is None:
            raise MatchParseError(f"SE[{index}]={name!r} no coincide con el catálogo de equipos")
        source_team_by_index[index] = team

    rows_by_round = _parse_result_rows(source_html)
    captured_date = captured_at.date() if isinstance(captured_at, datetime) else captured_at
    source_by_round: dict[int, list[dict[str, str]]] = {}
    for matchday, fields in source_records:
        source_by_round.setdefault(matchday, []).append(fields)
    if set(source_by_round) != set(range(1, 39)):
        raise MatchParseError("SP no cubre las 38 jornadas")
    if any(len(source_by_round[round_number]) != 10 for round_number in range(1, 39)):
        raise MatchParseError("SP no contiene 10 registros para cada jornada")
    if set(rows_by_round) != set(range(1, 39)) or any(
        len(rows_by_round[round_number]) != 10 for round_number in range(1, 39)
    ):
        raise MatchParseError("#resultats no contiene 10 filas de partido para cada jornada")
    all_ids = [record.get("id", "") for _, record in source_records]
    if any(not value for value in all_ids) or len(set(all_ids)) != len(all_ids):
        raise MatchParseError("Los IDs de partido SP faltan o están duplicados")

    matches: list[MatchResult] = []
    fixture_keys: set[tuple[int, int, int]] = set()
    consumed_result_rows: set[tuple[int, int]] = set()
    for matchday in range(1, 39):
        matchday_date_value = parsed_classification.matchday_dates.get(matchday)
        matchday_date = date.fromisoformat(matchday_date_value) if matchday_date_value else None
        if matchday_date is None:
            raise MatchParseError(f"Falta la fecha publicada de la jornada {matchday}")
        result_rows = rows_by_round[matchday]
        result_by_id, result_by_fixture = _result_row_indexes(result_rows)
        for index, fields in enumerate(source_by_round[matchday]):
            try:
                match_id = fields["id"]
                home_index = int(fields["a1"])
                away_index = int(fields["a2"])
                home = source_team_by_index[home_index]
                away = source_team_by_index[away_index]
                source_match_date = _parse_date(fields["d"], field="SP.d")
                home_score_raw = int(fields["g1"])
                away_score_raw = int(fields["g2"])
            except (KeyError, ValueError, IndexError) as exc:
                raise MatchParseError(f"Registro SP inválido en jornada {matchday}") from exc
            fixture_key = (matchday, home.team_id, away.team_id)
            if fixture_key in fixture_keys:
                raise MatchParseError(f"Partido duplicado por jornada/local/visitante: {fixture_key}")
            fixture_keys.add(fixture_key)

            if home_score_raw >= 0 and away_score_raw >= 0:
                status = "played"
                home_goals, away_goals = home_score_raw, away_score_raw
                home_yellow = _parse_nonnegative(fields.get("tg1", ""), field="SP.tg1")
                away_yellow = _parse_nonnegative(fields.get("tg2", ""), field="SP.tg2")
                home_red = _parse_nonnegative(fields.get("tv1", ""), field="SP.tv1")
                away_red = _parse_nonnegative(fields.get("tv2", ""), field="SP.tv2")
            elif home_score_raw < 0 and away_score_raw < 0:
                status = "unplayed"
                home_goals = away_goals = None
                home_yellow = away_yellow = home_red = away_red = None
            else:
                status = "incomplete"
                home_goals = home_score_raw if home_score_raw >= 0 else None
                away_goals = away_score_raw if away_score_raw >= 0 else None
                home_yellow = away_yellow = home_red = away_red = None

            if status == "played":
                expected_result = (home_score_raw > away_score_raw) - (
                    home_score_raw < away_score_raw
                )
                try:
                    observed_result = int(fields["r"])
                except (KeyError, ValueError) as exc:
                    raise MatchParseError(f"Código r inválido en SP id={match_id}") from exc
                if observed_result != expected_result:
                    raise MatchParseError(f"Código r no coincide con marcador en SP id={match_id}")

            unplayed_state = None
            if status == "unplayed":
                unplayed_state = (
                    "scheduled"
                    if captured_date is not None and source_match_date > captured_date
                    else "result_unavailable_at_capture"
                    if captured_date is not None
                    else "unknown"
                )

            if status == "played":
                result_row_ref = result_by_id.get(match_id)
                if result_row_ref is None:
                    raise MatchParseError(f"ID disputado {match_id} no aparece en #resultats")
            else:
                fixture_ref = (
                    source_match_date.strftime("%d/%m/%Y"),
                    home.name,
                    away.name,
                )
                result_row_ref = result_by_fixture.get(fixture_ref)
                if result_row_ref is None:
                    raise MatchParseError(f"Fixture de SP no aparece en #resultats: {fixture_ref}")
            row_index, result_row = result_row_ref
            consumed_result_rows.add((matchday, row_index))
            match_url = _validate_result_row(
                result_row,
                matchday=matchday,
                matchday_row_index=row_index,
                match_id=match_id,
                source_match_date=source_match_date,
                home_name=home.name,
                away_name=away.name,
                played=status == "played",
                source_fields=fields,
                base_url=base_url,
            )
            postponed = (
                source_match_date > matchday_date + timedelta(days=3)
                if source_match_date and matchday_date
                else None
            )
            matches.append(
                MatchResult(
                    match_id=match_id,
                    matchday=matchday,
                    matchday_date=matchday_date,
                    source_match_date=source_match_date,
                    home_team_id=home.team_id,
                    away_team_id=away.team_id,
                    home_goals=home_goals,
                    away_goals=away_goals,
                    home_yellow_cards=home_yellow,
                    away_yellow_cards=away_yellow,
                    home_red_cards=home_red,
                    away_red_cards=away_red,
                    status=status,
                    unplayed_state=unplayed_state,
                    postponed_by_source_rule=postponed,
                    source_match_url=match_url,
                    source_references=(
                        f"SP[{matchday}].push(id={match_id})",
                        f"#resultats[data-jornada={matchday}] match-row={row_index}",
                    ),
                    source_fields=fields,
                )
            )

    observed_id_count = sum(len(_source_ids(row)) for rows in rows_by_round.values() for _, row in rows)
    if observed_id_count != sum(match.status == "played" for match in matches):
        raise MatchParseError("#resultats contiene IDs inesperados o duplicados")
    expected_row_keys = {
        (matchday, row_index)
        for matchday, rows in rows_by_round.items()
        for row_index, _ in rows
    }
    if consumed_result_rows != expected_row_keys:
        raise MatchParseError("SP y #resultats no describen el mismo conjunto de fixtures")
    return teams, tuple(matches)
