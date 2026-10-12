"""Derive BDFutbol Seguimiento views from its embedded match matrices.

The derived HTML is an offline representation of values already present in an
acquired source snapshot. It is not evidence of a second browser navigation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup
from bs4.element import Tag


_PLAYER_ID = re.compile(r"(?:^|/)j(\d+)\.html(?:$|[?#])")
_MATCH_ID = re.compile(r"p\.php\?id=(\d+)")
_ARRAY_ASSIGNMENT = re.compile(
    r"(?P<name>JSEG|JSEGC|JSEGG)\[['\"]lig['\"]\]\[(?P<index>\d+)\]"
    r"\s*=\s*new Array\((?P<values>.*?)\);",
    re.DOTALL,
)
_CARD_MARKERS = {"tg1", "tg2", "tv"}
_STATES = ("p", "t", "go", "tot")


class FollowStateDerivationError(ValueError):
    """The embedded source matrices do not form a complete, coherent matrix."""


@dataclass(frozen=True, slots=True)
class DerivedFollowStates:
    html_by_state: dict[str, str]
    source_sha256: str
    player_count: int
    matchdays: tuple[int, ...]
    match_ids: tuple[str, ...]


def derive_follow_states(source_html: str) -> DerivedFollowStates:
    """Build p/t/go/tot DOM views from JSEG, JSEGC, JSEGG and JSEGID.

    Player rows and match columns are checked against the visible table before
    the JavaScript arrays are used. The input string is never modified.
    """

    soup = BeautifulSoup(source_html, "html.parser")
    table = soup.select_one("#taula-seguiment")
    selector = soup.select_one("#vista_jornades")
    if not isinstance(table, Tag) or not isinstance(selector, Tag):
        raise FollowStateDerivationError("Falta la tabla o el selector de Seguimiento.")
    if not {"p", "t", "go", "tot"}.issubset(
        {str(option.get("value")) for option in selector.select("option")}
    ):
        raise FollowStateDerivationError("El selector no ofrece los cuatro estados esperados.")

    arrays = _read_arrays(source_html)
    matchday_values = _read_json_assignment(source_html, "JSEGJ")
    match_ids_by_state = _read_match_ids(source_html)
    matchdays = tuple(int(value) for value in matchday_values.get("lig", []))
    match_ids = tuple(str(value) for value in match_ids_by_state.get("lig", []))
    if not matchdays or len(matchdays) != len(match_ids) or len(set(match_ids)) != len(match_ids):
        raise FollowStateDerivationError("JSEGJ y JSEGID no identifican una lista única de partidos.")

    rows = table.select("tr")
    if len(rows) < 2:
        raise FollowStateDerivationError("La tabla de Seguimiento no contiene filas de jugadores.")
    header_matchdays = tuple(_integer_cell(cell.get_text(" ", strip=True)) for cell in rows[0].select("th, td")[1:])
    if header_matchdays != matchdays:
        raise FollowStateDerivationError("Las jornadas del encabezado no coinciden con JSEGJ.")

    player_rows = rows[1:]
    if len(player_rows) != len(arrays["JSEG"]):
        raise FollowStateDerivationError("Las matrices JavaScript no cubren todas las filas de jugadores.")
    player_ids: list[int] = []
    for index, row in enumerate(player_rows):
        player_anchor = row.select_one("a[href]")
        player_match = _PLAYER_ID.search(str(player_anchor.get("href", ""))) if player_anchor else None
        if player_match is None:
            raise FollowStateDerivationError(f"La fila {index} no tiene un player_id verificable.")
        player_id = int(player_match.group(1))
        player_ids.append(player_id)
        if any(index not in arrays[name] for name in ("JSEG", "JSEGC", "JSEGG")):
            raise FollowStateDerivationError(f"Falta la fila {index} en una matriz JavaScript.")
        if any(len(arrays[name][index]) != len(matchdays) for name in ("JSEG", "JSEGC", "JSEGG")):
            raise FollowStateDerivationError(f"Las matrices de player_id={player_id} no cubren todas las jornadas.")

        cells = row.select("td")[1:]
        if len(cells) != len(matchdays):
            raise FollowStateDerivationError(f"La fila de player_id={player_id} no tiene seis celdas de partido.")
        for column, cell in enumerate(cells):
            wrapper = cell.select_one(".segdiv")
            match_anchor = cell.select_one('a[href*="p.php?id="]')
            match_match = _MATCH_ID.search(str(match_anchor.get("href", ""))) if match_anchor else None
            expected_classes = set(arrays["JSEGC"][index][column].split())
            actual_classes = set(wrapper.get("class", [])) - {"segdiv"} if wrapper else set()
            if match_match is None or match_match.group(1) != match_ids[column]:
                raise FollowStateDerivationError(
                    f"Jornada {matchdays[column]} no coincide con el enlace de partido de player_id={player_id}."
                )
            if wrapper is None or actual_classes != expected_classes:
                raise FollowStateDerivationError(
                    f"JSEGC no coincide con el DOM publicado para player_id={player_id}, match_id={match_ids[column]}."
                )
            minutes = arrays["JSEG"][index][column]
            visible_minutes = match_anchor.get_text(" ", strip=True)
            if visible_minutes != minutes:
                raise FollowStateDerivationError(
                    f"JSEG no coincide con los minutos visibles para player_id={player_id}, match_id={match_ids[column]}."
                )
            goal_value = _goal_integer(arrays["JSEGG"][index][column], player_id, match_ids[column])
            if (goal_value > 0) != ("gol" in expected_classes):
                raise FollowStateDerivationError(
                    f"JSEGG y la marca gol no coinciden para player_id={player_id}, match_id={match_ids[column]}."
                )

    if len(set(player_ids)) != len(player_ids):
        raise FollowStateDerivationError("La tabla repite player_id.")
    states = {"p": source_html}
    for state in ("t", "go", "tot"):
        states[state] = _render_state(source_html, arrays, state)
    return DerivedFollowStates(
        html_by_state=states,
        source_sha256=hashlib.sha256(source_html.encode("utf-8")).hexdigest(),
        player_count=len(player_ids),
        matchdays=matchdays,
        match_ids=match_ids,
    )


def _read_arrays(source_html: str) -> dict[str, dict[int, list[str]]]:
    arrays: dict[str, dict[int, list[str]]] = {name: {} for name in ("JSEG", "JSEGC", "JSEGG")}
    for match in _ARRAY_ASSIGNMENT.finditer(source_html):
        values = _quoted_strings(match.group("values"))
        arrays[match.group("name")][int(match.group("index"))] = values
    if not all(arrays[name] for name in arrays):
        raise FollowStateDerivationError("Falta alguna de las matrices JSEG, JSEGC o JSEGG.")
    return arrays


def _quoted_strings(value: str) -> list[str]:
    tokens = re.findall(r"'((?:\\.|[^'\\])*)'", value)
    if ",".join(f"'{item}'" for item in tokens) != value.strip():
        raise FollowStateDerivationError("Una matriz JavaScript tiene valores no reconocidos.")
    return [bytes(item, "utf-8").decode("unicode_escape") for item in tokens]


def _read_json_assignment(source_html: str, name: str) -> dict[str, list[int]]:
    match = re.search(rf"var\s+{name}\s*=\s*(\{{.*?\}})\s*;", source_html, re.DOTALL)
    if match is None:
        raise FollowStateDerivationError(f"Falta la estructura {name}.")
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise FollowStateDerivationError(f"La estructura {name} no es JSON válido.") from exc
    if not isinstance(value, dict):
        raise FollowStateDerivationError(f"La estructura {name} no es un objeto.")
    return value


def _read_match_ids(source_html: str) -> dict[str, list[str]]:
    match = re.search(r"var\s+JSEGID\s*=\s*JSON\.parse\('(.*?)'\)\s*;", source_html, re.DOTALL)
    if match is None:
        raise FollowStateDerivationError("Falta la estructura JSEGID.")
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise FollowStateDerivationError("JSEGID no contiene JSON válido.") from exc
    if not isinstance(value, dict):
        raise FollowStateDerivationError("JSEGID no es un objeto.")
    return value


def _integer_cell(value: str) -> int:
    if not value.isdigit():
        raise FollowStateDerivationError("El encabezado de jornada no es un entero.")
    return int(value)


def _goal_integer(value: str, player_id: int, match_id: str) -> int:
    if value == "":
        return 0
    if not value.isdigit():
        raise FollowStateDerivationError(
            f"JSEGG tiene un valor no numérico para player_id={player_id}, match_id={match_id}."
        )
    return int(value)


def _render_state(source_html: str, arrays: dict[str, dict[int, list[str]]], state: str) -> str:
    soup = BeautifulSoup(source_html, "html.parser")
    table = soup.select_one("#taula-seguiment")
    assert isinstance(table, Tag)
    for player_index, row in enumerate(table.select("tr")[1:]):
        for match_index, cell in enumerate(row.select("td")[1:]):
            wrapper = cell.select_one(".segdiv")
            anchor = cell.select_one('a[href*="p.php?id="]')
            assert isinstance(wrapper, Tag) and isinstance(anchor, Tag)
            source_classes = arrays["JSEGC"][player_index][match_index].split()
            goal_value = _goal_integer(
                arrays["JSEGG"][player_index][match_index],
                player_id=_player_id_from_row(row),
                match_id=_MATCH_ID.search(str(anchor.get("href", ""))).group(1),
            )
            if state == "t":
                classes = [marker for marker in source_classes if marker == "subs" or marker in _CARD_MARKERS]
                text = arrays["JSEG"][player_index][match_index]
            elif state == "go":
                classes = (["subs"] if "subs" in source_classes else [])
                if goal_value > 0:
                    classes.append("gol")
                text = str(goal_value) if goal_value > 0 else ""
            else:
                classes = source_classes
                if any(marker in source_classes for marker in ("tg1", "tg2")):
                    classes.append("vora-groga")
                if "tv" in source_classes:
                    classes.append("vora-vermella")
                if goal_value > 0:
                    classes.append("gol-marca")
                text = arrays["JSEG"][player_index][match_index]
            wrapper["class"] = ["segdiv", *classes]
            anchor.clear()
            if text:
                anchor.append(text)

    selector = soup.select_one("#vista_jornades")
    if isinstance(selector, Tag):
        for option in selector.select("option"):
            option.attrs.pop("selected", None)
            if option.get("value") == state:
                option["selected"] = "selected"
    return str(soup)


def _player_id_from_row(row: Tag) -> int:
    anchor = row.select_one("a[href]")
    match = _PLAYER_ID.search(str(anchor.get("href", ""))) if anchor else None
    if match is None:
        raise FollowStateDerivationError("No se pudo identificar un jugador al derivar una vista.")
    return int(match.group(1))
