from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, NavigableString, Tag

from .ids import (
    ProviderRef,
    absolute_url,
    coach_id_from_url,
    player_id_from_url,
)
from .models import (
    CoachAssignment,
    SquadMember,
    TeamSeasonContext,
    TeamSeasonSnapshot,
)


class TeamSeasonParseError(ValueError):
    pass


_CONTEXT_RE = re.compile(
    r"/t/t(?P<season>\d{4}-\d{2})(?P<team_id>\d+)\.html$",
    re.IGNORECASE,
)
_COMPETITION_RE_TEMPLATE = (
    r"/t/t{season}(?P<competition>\d*[a-z][a-z0-9]*)(?P<group>\d+)\.html$"
)
_MATCH_SUMMARY_RE = re.compile(
    r"\bPartidos:\s*(?P<matches>\d+)\s*"
    r"\((?P<win_pct>\d+(?:[.,]\d+)?)%\s*ganados\)",
    re.IGNORECASE,
)

_MARKERS = "⬤"


def _clean_text(node: Tag | None) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def _clean_name(value: str) -> str:
    for marker in _MARKERS:
        value = value.replace(marker, "")
    return " ".join(value.split()).strip()


def _display_anchor_text(anchor: Tag) -> str:
    """Return the visible/primary label without BDFutbol's hidden long name.

    Player/coach links can contain both the short display name and an additional
    responsive/hidden full-name span. BeautifulSoup.get_text() concatenates
    both, which produced values such as "Morillas Jaime Morillas".
    """

    # Prefer literal text directly inside the anchor. On the current BDFutbol
    # markup this is the visible alias while auxiliary spans contain the longer
    # name used at other responsive breakpoints.
    for child in anchor.children:
        if isinstance(child, NavigableString):
            value = _clean_name(str(child))
            if value:
                return value

    # If the label is wrapped, use the first meaningful child instead of
    # concatenating every responsive/hidden descendant.
    for child in anchor.children:
        if isinstance(child, Tag):
            value = _clean_name(_clean_text(child))
            if value:
                return value

    return _clean_name(_clean_text(anchor))


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip().replace("\xa0", " ")
    if not re.fullmatch(r"-?\d+", value):
        return None
    return int(value)


def _normalized_header(value: str) -> str:
    value = " ".join(value.replace("\xa0", " ").split())
    return value.rstrip(".").casefold()


def _context_source_url(soup: BeautifulSoup, source_url: str) -> str:
    canonical = soup.select_one('link[rel="canonical"][href]')
    if canonical:
        href = canonical.get("href")
        if isinstance(href, str) and "/t/t" in href:
            return absolute_url(href, source_url)
    return source_url


def _parse_context_identity(
    soup: BeautifulSoup,
    source_url: str,
) -> tuple[str, int, str]:
    effective_url = _context_source_url(soup, source_url)
    path = re.sub(r"[?#].*$", "", urlsplit(effective_url).path)
    match = _CONTEXT_RE.search(path)
    if not match:
        raise TeamSeasonParseError(
            f"No se pudo extraer temporada/team_id de {effective_url!r}."
        )
    return match.group("season"), int(match.group("team_id")), effective_url


def _team_name(soup: BeautifulSoup, season: str) -> str:
    heading = soup.find("h1")
    if heading is None:
        raise TeamSeasonParseError("No se encontró el encabezado principal del equipo.")

    anchor = heading.find("a")
    if isinstance(anchor, Tag):
        name = _display_anchor_text(anchor)
        if name:
            return name

    text = _clean_name(_clean_text(heading))
    text = re.sub(rf"\s+{re.escape(season)}\s*$", "", text).strip()
    if not text:
        raise TeamSeasonParseError("No se pudo extraer el nombre del equipo.")
    return text


def _competition_info(
    soup: BeautifulSoup,
    season: str,
    source_url: str,
) -> tuple[str | None, str | None, int | None]:
    pattern = re.compile(
        _COMPETITION_RE_TEMPLATE.format(season=re.escape(season)),
        re.IGNORECASE,
    )

    heading = soup.find("h1")
    anchors = heading.find_all_next("a", href=True, limit=200) if heading else []

    for anchor in anchors:
        href = anchor.get("href")
        if not isinstance(href, str):
            continue

        # BDFutbol often emits relative hrefs here. Match against the absolute
        # URL so "/es/...", "es/..." and bare relative paths behave equally.
        candidate_url = absolute_url(href, source_url)
        path = urlsplit(candidate_url).path
        match = pattern.search(path)
        if not match:
            continue

        name = _display_anchor_text(anchor) or None
        return (
            match.group("competition").lower(),
            name,
            int(match.group("group")),
        )

    return None, None, None


def _match_summary(soup: BeautifulSoup) -> tuple[int | None, float | None]:
    text = _clean_text(soup)
    match = _MATCH_SUMMARY_RE.search(text)
    if not match:
        return None, None
    win_pct = float(match.group("win_pct").replace(",", "."))
    return int(match.group("matches")), win_pct


def _find_label(soup: BeautifulSoup, text: str) -> Tag | None:
    """Find a section label without assuming BDFutbol uses a fixed heading tag."""

    target = _normalized_header(text)
    preferred_names = {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "div",
        "span",
        "strong",
        "th",
        "td",
    }

    candidates: list[Tag] = []
    for tag in soup.find_all(preferred_names):
        if not isinstance(tag, Tag):
            continue
        if _normalized_header(_clean_text(tag)) == target:
            candidates.append(tag)

    if not candidates:
        return None

    # Prefer the most specific node. Parent wrappers can also normalize to the
    # same text; fewer descendants generally means the actual label.
    return min(candidates, key=lambda tag: len(tag.find_all(True)))


def _table_after_label(soup: BeautifulSoup, text: str) -> Tag | None:
    label = _find_label(soup, text)
    if label is None:
        return None

    # The label may itself live inside the table (BDFutbol currently does this
    # for some responsive layouts).
    parent_table = label.find_parent("table")
    if isinstance(parent_table, Tag):
        return parent_table

    table = label.find_next("table")
    return table if isinstance(table, Tag) else None


def _header_map_from_cells(cells: list[Tag]) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, cell in enumerate(cells):
        key = _normalized_header(_clean_text(cell))
        if key and key not in result:
            result[key] = index
    return result


def _row_cells(row: Tag) -> list[Tag]:
    return [
        cell
        for cell in row.find_all(["td", "th"], recursive=False)
        if isinstance(cell, Tag)
    ]


def _cell(
    cells: list[Tag],
    headers: dict[str, int],
    *names: str,
) -> Tag | None:
    for name in names:
        index = headers.get(_normalized_header(name))
        if index is not None and 0 <= index < len(cells):
            return cells[index]
    return None


def _cell_text(
    cells: list[Tag],
    headers: dict[str, int],
    *names: str,
) -> str:
    return _clean_text(_cell(cells, headers, *names))


def _position_text(cell: Tag | None) -> str | None:
    text = _clean_text(cell)
    if text:
        return text
    if cell is None:
        return None

    image = cell.find("img")
    if isinstance(image, Tag):
        for attr in ("title", "alt"):
            value = image.get(attr)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())

    return None


def _coach_rows(table: Tag | None) -> tuple[CoachAssignment, ...]:
    if table is None:
        return ()

    headers: dict[str, int] = {}
    coaches: list[CoachAssignment] = []

    for row in table.find_all("tr"):
        if not isinstance(row, Tag):
            continue
        cells = _row_cells(row)
        if not cells:
            continue

        if row.find("th"):
            candidate_headers = _header_map_from_cells(cells)
            if "apodo y nombre" in candidate_headers:
                headers = candidate_headers
            continue

        coach_anchor: Tag | None = None
        coach_id: int | None = None

        for anchor in row.select("a[href]"):
            parsed = coach_id_from_url(anchor.get("href"))
            if parsed is not None:
                coach_anchor = anchor
                coach_id = parsed
                break

        if coach_anchor is None or coach_id is None:
            continue

        coach_name = _display_anchor_text(coach_anchor)
        if not coach_name:
            continue

        coaches.append(
            CoachAssignment(
                coach=ProviderRef("coach", coach_id),
                coach_name=coach_name,
                age=_int_or_none(_cell_text(cells, headers, "Edad")),
                rounds=_cell_text(cells, headers, "Jornadas") or None,
                matches=_int_or_none(_cell_text(cells, headers, "Partidos")),
                yellow_cards=_int_or_none(_cell_text(cells, headers, "TA")),
                red_cards=_int_or_none(_cell_text(cells, headers, "TR")),
                raw={"cells": [_clean_text(cell) for cell in cells]},
            )
        )

    return tuple(coaches)


def _section_from_row(row: Tag) -> str | None:
    text = _normalized_header(_clean_text(row))

    # Section rows can contain colspan/header markup. Equality is preferred,
    # with conservative containment fallback for responsive decoration.
    if text == "titulares" or text.startswith("titulares "):
        return "starter"
    if text == "suplentes" or text.startswith("suplentes "):
        return "substitute"
    return None


def _player_from_row(
    row: Tag,
    *,
    headers: dict[str, int],
    section: str,
) -> SquadMember | None:
    cells = _row_cells(row)
    if not cells:
        return None

    player_anchor: Tag | None = None
    player_id: int | None = None

    for anchor in row.select("a[href]"):
        parsed = player_id_from_url(anchor.get("href"))
        if parsed is not None:
            player_anchor = anchor
            player_id = parsed
            break

    if player_anchor is None or player_id is None:
        return None

    name = _display_anchor_text(player_anchor)
    if not name:
        return None

    number_cell = _cell(cells, headers, "#")
    if number_cell is None and cells:
        number_cell = cells[0]

    return SquadMember(
        player=ProviderRef("player", player_id),
        player_name=name,
        squad_number=_int_or_none(_clean_text(number_cell)),
        squad_section=section,
        position=_position_text(_cell(cells, headers, "Pos", "Posición")),
        age=_int_or_none(_cell_text(cells, headers, "Edad")),
        appearances=_int_or_none(_cell_text(cells, headers, "PJ")),
        starts=_int_or_none(_cell_text(cells, headers, "PT")),
        complete_matches=_int_or_none(_cell_text(cells, headers, "PC")),
        substitute_appearances=_int_or_none(_cell_text(cells, headers, "PS")),
        unused_callups=_int_or_none(_cell_text(cells, headers, "C")),
        minutes=_int_or_none(_cell_text(cells, headers, "Min")),
        yellow_cards=_int_or_none(_cell_text(cells, headers, "TA")),
        red_cards=_int_or_none(_cell_text(cells, headers, "TR")),
        goals=_int_or_none(_cell_text(cells, headers, "G")),
        raw={"cells": [_clean_text(cell) for cell in cells]},
    )


def _parse_player_table(
    table: Tag,
    *,
    initial_section: str,
) -> tuple[SquadMember, ...]:
    """Parse one BDFutbol squad table, including internal section boundaries."""

    headers: dict[str, int] = {}
    current_section = initial_section
    members: list[SquadMember] = []

    for row in table.find_all("tr"):
        if not isinstance(row, Tag):
            continue

        section = _section_from_row(row)
        if section is not None:
            current_section = section
            continue

        cells = _row_cells(row)
        if not cells:
            continue

        if row.find("th"):
            candidate_headers = _header_map_from_cells(cells)
            if "apodo y nombre" in candidate_headers:
                headers = candidate_headers
            continue

        member = _player_from_row(
            row,
            headers=headers,
            section=current_section,
        )
        if member is not None:
            members.append(member)

    return tuple(members)


def _squad_rows(soup: BeautifulSoup) -> tuple[SquadMember, ...]:
    """Parse starters/substitutes from either one combined or two separate tables."""

    titular_table = _table_after_label(soup, "Titulares")
    suplentes_table = _table_after_label(soup, "Suplentes")

    members: list[SquadMember] = []

    if titular_table is not None:
        members.extend(
            _parse_player_table(
                titular_table,
                initial_section="starter",
            )
        )

    # If "Suplentes" points to a genuinely different table, parse it as a
    # separate section. If both labels resolve to the same responsive table,
    # the internal section row above already performed the split.
    if (
        suplentes_table is not None
        and suplentes_table is not titular_table
    ):
        members.extend(
            _parse_player_table(
                suplentes_table,
                initial_section="substitute",
            )
        )

    # Deduplicate provider IDs while preserving document order. This protects
    # against responsive duplicate markup without silently merging two
    # genuinely different provider identities.
    unique: list[SquadMember] = []
    seen: set[int] = set()
    for member in members:
        provider_id = member.player.provider_id
        if provider_id in seen:
            continue
        seen.add(provider_id)
        unique.append(member)

    return tuple(unique)


def parse_team_season(
    html: str,
    source_url: str,
    *,
    expected_team_id: int | None = None,
    min_squad_members: int | None = None,
) -> TeamSeasonSnapshot:
    soup = BeautifulSoup(html, "lxml")
    season, team_id, effective_url = _parse_context_identity(soup, source_url)

    if expected_team_id is not None and team_id != expected_team_id:
        raise TeamSeasonParseError(
            f"Se esperaba team_id={expected_team_id} y se obtuvo {team_id}."
        )

    team_name = _team_name(soup, season)
    competition_code, competition_name, group = _competition_info(
        soup,
        season,
        effective_url,
    )
    matches_played, win_percentage = _match_summary(soup)

    coaches = _coach_rows(_table_after_label(soup, "Entrenador"))
    squad = _squad_rows(soup)

    if not squad:
        raise TeamSeasonParseError(
            "No se encontraron jugadores en Titulares/Suplentes."
        )

    duplicate_ids = [
        player_id
        for player_id, count in Counter(
            member.player.provider_id for member in squad
        ).items()
        if count > 1
    ]
    if duplicate_ids:
        raise TeamSeasonParseError(
            f"Player IDs duplicados en la plantilla: {duplicate_ids[:10]}"
        )

    if min_squad_members is not None and len(squad) < min_squad_members:
        raise TeamSeasonParseError(
            f"Se esperaban al menos {min_squad_members} jugadores y se "
            f"obtuvieron {len(squad)}."
        )

    starters = tuple(
        member for member in squad if member.squad_section == "starter"
    )
    substitutes = tuple(
        member for member in squad if member.squad_section == "substitute"
    )

    warnings: list[str] = []
    if not coaches:
        warnings.append("coach_not_found")
    if not starters:
        warnings.append("starters_not_found")
    if not substitutes:
        warnings.append("substitutes_not_found")
    if competition_code is None:
        warnings.append("competition_not_found")

    return TeamSeasonSnapshot(
        context=TeamSeasonContext(
            team=ProviderRef("team", team_id),
            team_name=team_name,
            season=season,
            source_url=effective_url,
            competition_code=competition_code,
            competition_name=competition_name,
            group=group,
            matches_played=matches_played,
            win_percentage=win_percentage,
        ),
        coaches=coaches,
        squad=squad,
        warnings=tuple(warnings),
    )
