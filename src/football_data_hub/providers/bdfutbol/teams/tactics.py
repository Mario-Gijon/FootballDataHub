"""Read the approximate player layout embedded in a saved BDFutbol roster page.

This module does not acquire pages. It only interprets the verified offline
``#tactica`` markup and keeps each spatial marker linked to its source player.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

_TACTICAL_ELEMENT_ID = re.compile(r"^d_(por|def|mig|dav)(?:(\d+)(\d+))?$")
_PLAYER_LINK_ID = re.compile(r"(?:^|/)j(\d+)\.html$")
_LINE_ORDER = {
    "por": ("goalkeeper", 0.14),
    "def": ("defense", 0.38),
    "mig": ("midfield", 0.62),
    "dav": ("attack", 0.86),
}


class TacticalLayoutError(ValueError):
    """Saved tactical markup is absent, ambiguous, or not linked to the roster."""


@dataclass(frozen=True, slots=True)
class TacticalPosition:
    player_id: int
    horizontal: float
    vertical: float
    line: str
    slot: int
    line_size: int
    source_dom_id: str


def extract_tactical_positions(
    html: str,
    *,
    roster_player_ids: set[int],
    starter_player_ids: set[int],
) -> tuple[TacticalPosition, ...]:
    """Derive app coordinates from source line/slot IDs in ``#tactica``.

    The source stores positional IDs (for example ``d_def13``), not pixel or
    normalized CSS coordinates. Horizontal placement follows the source role
    order from goalkeeper to attack; vertical placement follows the slot index
    and declared number of slots for that line. The returned geometry is thus
    explicitly an approximation, while player identity and source slot remain
    directly traceable to the saved HTML.
    """

    soup = BeautifulSoup(html, "html.parser")
    tactic = soup.select_one("#alineacio #tactica #js")
    if tactic is None:
        raise TacticalLayoutError("No existe #alineacio #tactica #js en el snapshot.")

    positions: list[TacticalPosition] = []
    seen_player_ids: set[int] = set()
    line_sizes: dict[str, int] = {}
    seen_slots: set[tuple[str, int]] = set()

    for element in tactic.find_all(id=True, recursive=False):
        source_dom_id = str(element.get("id", ""))
        match = _TACTICAL_ELEMENT_ID.fullmatch(source_dom_id)
        if match is None:
            if source_dom_id.startswith("d_"):
                raise TacticalLayoutError(f"ID táctico de origen no reconocido: {source_dom_id}.")
            continue

        source_line, ordinal_text, size_text = match.groups()
        if source_line == "por":
            if ordinal_text is not None or size_text is not None:
                raise TacticalLayoutError("El identificador del portero no debe incluir una fila.")
            ordinal, line_size = 1, 1
        else:
            if ordinal_text is None or size_text is None:
                raise TacticalLayoutError(f"Falta el ordinal o tamaño de línea en {source_dom_id}.")
            ordinal, line_size = int(ordinal_text), int(size_text)
            if ordinal < 1 or line_size < 1 or ordinal > line_size:
                raise TacticalLayoutError(f"El ordinal táctico no es válido en {source_dom_id}.")
            previous_size = line_sizes.setdefault(source_line, line_size)
            if previous_size != line_size:
                raise TacticalLayoutError(f"La línea {source_line} declara tamaños incompatibles.")

        slot_key = (source_line, ordinal)
        if slot_key in seen_slots:
            raise TacticalLayoutError(f"La posición de origen {source_dom_id} está duplicada.")
        seen_slots.add(slot_key)

        anchor = element.select_one("a[href]")
        href = str(anchor.get("href", "")) if anchor else ""
        id_match = _PLAYER_LINK_ID.search(href)
        if id_match is None:
            raise TacticalLayoutError(f"{source_dom_id} no enlaza a un jugador de BDFutbol.")
        player_id = int(id_match.group(1))
        if player_id not in roster_player_ids:
            raise TacticalLayoutError(f"El jugador {player_id} no existe en el catálogo de la captura.")
        if player_id not in starter_player_ids:
            raise TacticalLayoutError(f"El jugador {player_id} no pertenece a Titulares en la captura.")
        if player_id in seen_player_ids:
            raise TacticalLayoutError(f"El jugador {player_id} aparece más de una vez en #tactica.")
        seen_player_ids.add(player_id)

        line, horizontal = _LINE_ORDER[source_line]
        vertical = 0.10 + 0.80 * ordinal / (line_size + 1)
        positions.append(TacticalPosition(
            player_id=player_id,
            horizontal=horizontal,
            vertical=vertical,
            line=line,
            slot=ordinal,
            line_size=line_size,
            source_dom_id=source_dom_id,
        ))

    if not positions:
        raise TacticalLayoutError("#tactica no contiene posiciones enlazadas a jugadores.")
    return tuple(positions)
