"""Offline semantic parser for BDFutbol team-season pages."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from football_data_hub.providers.bdfutbol.context import CompetitionContext

from .models import (
    PlayerIdentity,
    PlayerMatchMetric,
    PlayerMatchMinutes,
    PlayerSeasonStatistics,
    PlayerTeamMembership,
    TeamIdentity,
    TeamProfileData,
    TeamSeason,
    TeamSeasonCoach,
    TeamTransfer,
    TeamTransferSection,
)


class TeamProfileParseError(ValueError):
    """The page does not contain the expected semantic team profile."""


_TEAM_URL_ID = re.compile(r"(?:^|/)t\d{4}-\d{2}(\d+)\.html$")
_PLAYER_URL_ID = re.compile(r"(?:^|/)j/j(\d+)\.html$")
_COACH_URL_ID = re.compile(r"(?:^|/)l/l(\d+)\.html$")
_MATCH_URL_ID = re.compile(r"(?:\?|&)id=(\d+)(?:&|$)")
_INTEGER_RE = re.compile(r"^-?\d+$")

_INDICATOR_LABELS = {
    "dot-superior1": "played_in_first_division",
    "dot-superior2": "played_in_second_division",
    "dot-internacionals": "youth_international",
    "dot-alta": "new_signing",
}

_STAT_COLUMNS = {
    "pj": ("matches_played", "Partidos Jugados"),
    "pt": ("starts", "Partidos titular"),
    "pc": ("full_matches", "Partidos completos"),
    "ps": ("substitute_appearances", "Partidos suplente"),
    "px": ("matches_substituted", "Partidos sustituido"),
    "c": ("unused_substitute_calls", "Convocado (sin jugar)"),
    "min": ("minutes_played", "Minutos"),
    "tg": ("yellow_cards", "Tarjetas amarillas"),
    "tv": ("red_cards", "Tarjetas rojas"),
    "g": ("goals", "Goles"),
    "gm": ("minutes_per_goal", "Minutos/Goles"),
    "gy": ("penalty_goals", "Goles penalty"),
    "gp": ("own_goals", "Goles propia puerta"),
    "ge": ("goals_conceded", "Goles encajados"),
    "pg": ("team_wins", "Ganados"),
    "pe": ("team_draws", "Empatados"),
    "pp": ("team_losses", "Perdidos"),
}

_PROFILE_IDENTITY_KEYS = (
    "display_name",
    "full_name",
    "profile_url",
    "photo_url",
    "age_years",
    "birth_date",
    "birthplace",
    "birthplace_province",
    "nationality_flag_url",
    "source_position_code",
)


def clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def team_id_from_url(value: str) -> int | None:
    match = _TEAM_URL_ID.search(urlsplit(value).path)
    return int(match.group(1)) if match else None


def resolve_team_view_urls(source_html: str, team_url: str) -> dict[str, str]:
    """Resolve supported view links/select options from the real base document."""
    soup = BeautifulSoup(source_html, "html.parser")
    urls = {"alignment": team_url}
    view_select = next(
        (
            select
            for select in soup.select("select")
            if {clean_text(option.get_text(" ", strip=True)) for option in select.select("option")}
            >= {"Alineación", "Plantilla", "Estadísticas"}
        ),
        None,
    )
    if view_select is None:
        raise TeamProfileParseError("No se encontró el selector de vista de Plantilla")
    for option in view_select.select("option"):
        label = clean_text(option.get_text(" ", strip=True))
        if label in {"Plantilla", "Estadísticas"}:
            key = "squad" if label == "Plantilla" else "statistics"
            value = option.get("value")
            if not value:
                raise TeamProfileParseError(f"La opción {label} no contiene URL")
            urls[key] = urljoin(team_url, str(value))

    nav_names = {
        "Seguimiento": "follow",
        "Traspasos": "transfers",
        "Partidos": "matches",
    }
    for anchor in soup.select("a.nav-link[href]"):
        label = clean_text(anchor.get_text(" ", strip=True))
        key = nav_names.get(label)
        if key:
            urls[key] = urljoin(team_url, str(anchor["href"]))

    required = {"alignment", "squad", "statistics", "follow", "transfers", "matches"}
    missing = sorted(required - urls.keys())
    if missing:
        raise TeamProfileParseError(f"Faltan enlaces de vistas de equipo: {missing}")
    base_path = urlsplit(team_url).path
    for key, view_url in urls.items():
        parts = urlsplit(view_url)
        if parts.scheme != "https" or parts.hostname not in {"bdfutbol.com", "www.bdfutbol.com"}:
            raise TeamProfileParseError(f"URL de vista no autorizada para {key}: {view_url}")
        if parts.path != base_path:
            raise TeamProfileParseError(f"La vista {key} apunta a otra ficha: {view_url}")
    return urls


def _header_key(cell: Tag) -> str:
    col_id = cell.get("data-colid")
    if col_id:
        return str(col_id)
    return clean_text(str(cell.get("title") or cell.get_text(" ", strip=True))).casefold()


def _header_indexes(table: Tag) -> dict[str, int]:
    row = table.select_one("tr")
    if row is None:
        return {}
    indexes: dict[str, int] = {}
    for index, cell in enumerate(row.select("th, td")):
        key = _header_key(cell)
        if key and key not in indexes:
            indexes[key] = index
    return indexes


def _table_rows(table: Tag) -> list[list[Tag]]:
    return [row.select("th, td") for row in table.select("tr")]


def _cell(cells: list[Tag], indexes: dict[str, int], key: str) -> Tag | None:
    index = indexes.get(key)
    return cells[index] if index is not None and index < len(cells) else None


def _optional_int(value: str, *, field_name: str) -> int | None:
    text = clean_text(value)
    if text in {"", "-", "–", "—", "−"}:
        return None
    if not _INTEGER_RE.fullmatch(text):
        raise TeamProfileParseError(f"Valor no entero en {field_name}: {text!r}")
    return int(text)


def _int_cell(cell: Tag | None, *, field_name: str) -> int | None:
    return _optional_int(cell.get_text(" ", strip=True) if cell else "", field_name=field_name)


def _id_from_link(cell: Tag | None, pattern: re.Pattern[str]) -> tuple[int, str] | None:
    if cell is None:
        return None
    anchors = [cell] if cell.name == "a" and cell.has_attr("href") else []
    anchors.extend(cell.select("a[href]"))
    for anchor in anchors:
        href = str(anchor["href"])
        match = pattern.search(urlsplit(href).path)
        if match:
            return int(match.group(1)), href
    return None


def _absolute(base_url: str, value: str | None) -> str | None:
    return urljoin(base_url, value) if value else None


def _name_parts(anchor: Tag | None) -> tuple[str, str | None]:
    if anchor is None:
        return "", None
    spans = anchor.select("span")
    visible = next(
        (span for span in spans if "font-weight-bold" in span.get("class", [])),
        None,
    )
    full = next(
        (
            span
            for span in spans
            if span is not visible and "dot" not in span.get("class", [])
        ),
        None,
    )
    if visible is not None:
        display_name = clean_text(visible.get_text(" ", strip=True))
    else:
        display_name = clean_text(
            " ".join(
                piece
                for piece in anchor.stripped_strings
                if piece != "⬤"
            )
        )
    full_name = clean_text(full.get_text(" ", strip=True)) if full else None
    if full_name == display_name:
        full_name = None
    return display_name, full_name


def _indicator_values(anchor: Tag | None) -> tuple[str, ...]:
    if anchor is None:
        return ()
    found: set[str] = set()
    for element in anchor.select("[class]"):
        for class_name in element.get("class", []):
            label = _INDICATOR_LABELS.get(str(class_name))
            if label:
                found.add(label)
    return tuple(sorted(found))


def _row_player_anchor(cells: list[Tag]) -> Tag | None:
    for cell in cells:
        for anchor in cell.select("a[href]"):
            if _PLAYER_URL_ID.search(urlsplit(str(anchor["href"])).path):
                return anchor
    return None


def _photo_url(cells: list[Tag], index: int, base_url: str) -> str | None:
    if index >= len(cells):
        return None
    image = cells[index].select_one("img[src]")
    return _absolute(base_url, str(image["src"])) if image else None


def _identity_from_row(
    cells: list[Tag],
    *,
    base_url: str,
    view: str,
    indexes: dict[str, int],
) -> tuple[int, dict[str, Any]] | None:
    anchor = _row_player_anchor(cells)
    linked = _id_from_link(anchor, _PLAYER_URL_ID) if anchor else None
    if linked is None:
        return None
    player_id, href = linked
    display_name, full_name = _name_parts(anchor)
    if not display_name:
        raise TeamProfileParseError(f"El jugador {player_id} no tiene nombre visible")
    age_cell = _cell(cells, indexes, "edat") or _cell(cells, indexes, "edad")
    birth_cell = _cell(cells, indexes, "fecha de nacimiento")
    birthplace_cell = _cell(cells, indexes, "lugar de nacimiento")
    province_cell = _cell(cells, indexes, "provincia")
    position_cell = (
        _cell(cells, indexes, "pos")
        or _cell(cells, indexes, "dem")
        or _cell(cells, indexes, "demarcación")
    )
    photo_index = indexes.get("fot", indexes.get("foto", 1))
    country_index = indexes.get("pais", indexes.get("país", 2))
    country_cell = cells[country_index] if country_index < len(cells) else None
    flag_image = country_cell.select_one("img[src]") if country_cell else None
    birth_date = _parse_date(birth_cell.get_text(" ", strip=True)) if birth_cell else None
    details: dict[str, Any] = {
        "display_name": display_name,
        "full_name": full_name,
        "profile_url": _absolute(base_url, href),
        "photo_url": _photo_url(cells, photo_index, base_url),
        "age_years": _int_cell(age_cell, field_name="age_years"),
        "birth_date": birth_date,
        "birthplace": clean_text(birthplace_cell.get_text(" ", strip=True)) if birthplace_cell else None,
        "birthplace_province": clean_text(province_cell.get_text(" ", strip=True)) if province_cell else None,
        "nationality_flag_url": _absolute(base_url, str(flag_image["src"])) if flag_image else None,
        "source_position_code": _clean_nullable(position_cell.get_text(" ", strip=True)) if position_cell else None,
        "verified_indicators": _indicator_values(anchor),
        "source_views": (view,),
    }
    return player_id, details


def _clean_nullable(value: str) -> str | None:
    text = clean_text(value)
    return text if text and text not in {"-", "–", "—"} else None


def _parse_date(value: str) -> str | None:
    text = clean_text(value)
    if not text or text in {"-", "–", "—"}:
        return None
    try:
        return datetime.strptime(text, "%d/%m/%Y").date().isoformat()
    except ValueError as exc:
        raise TeamProfileParseError(f"Fecha no interpretable en ficha: {text!r}") from exc


def _merge_identity(
    identities: dict[int, dict[str, Any]],
    player_id: int,
    incoming: dict[str, Any],
    issues: list[str],
) -> None:
    current = identities.setdefault(player_id, {key: None for key in _PROFILE_IDENTITY_KEYS})
    views = set(current.get("source_views") or ()) | set(incoming.get("source_views") or ())
    for key in _PROFILE_IDENTITY_KEYS:
        value = incoming.get(key)
        old = current.get(key)
        if value is None or value == "":
            continue
        if old is not None and old != value:
            if key == "source_position_code":
                issues.append(
                    f"player_id={player_id}: demarcación de origen distinta "
                    f"({old!r} frente a {value!r}); se conserva la vista Estadísticas si existe"
                )
                if "statistics" in incoming.get("source_views", ()):
                    current[key] = value
            elif key in {"display_name", "full_name"}:
                # The alignment and roster pages carry the source's full player label.
                if "statistics" in current.get("source_views", ()) and "statistics" not in incoming.get("source_views", ()):
                    current[key] = value
                else:
                    issues.append(
                        f"player_id={player_id}: {key} distinto entre vistas; "
                        "se conserva el primer valor"
                    )
            elif key in {"age_years", "birth_date", "birthplace", "birthplace_province"}:
                # The published value is kept from the view that provides it first.
                continue
            else:
                issues.append(
                    f"player_id={player_id}: conflicto de {key} entre vistas; "
                    f"se conserva el primer valor"
                )
        elif old is None:
            current[key] = value
    current["source_views"] = tuple(sorted(views))
    current["verified_indicators"] = tuple(
        sorted(set(current.get("verified_indicators") or ()) | set(incoming.get("verified_indicators") or ()))
    )


def _parse_players_from_table(
    soup: BeautifulSoup,
    table_id: str,
    *,
    base_url: str,
    view: str,
    issues: list[str],
) -> tuple[dict[int, dict[str, Any]], dict[int, tuple[int | None, str | None]]]:
    table = soup.find(id=table_id)
    if not isinstance(table, Tag):
        return {}, {}
    indexes = _header_indexes(table)
    identities: dict[int, dict[str, Any]] = {}
    memberships: dict[int, tuple[int | None, str | None]] = {}
    rows = _table_rows(table)
    for row in rows[1:]:
        parsed = _identity_from_row(row, base_url=base_url, view=view, indexes=indexes)
        if parsed is None:
            continue
        player_id, details = parsed
        if player_id in identities:
            raise TeamProfileParseError(f"player_id duplicado en #{table_id}: {player_id}")
        identities[player_id] = details
        jersey_cell = _cell(row, indexes, "dor") or _cell(row, indexes, "dorsal")
        jersey = _int_cell(jersey_cell, field_name="jersey_number")
        label: str | None = None
        if table_id == "taulaplantilla":
            for heading in row[0].find_all_previous("h2"):
                text = clean_text(heading.get_text(" ", strip=True))
                if text in {"Titulares", "Suplentes"}:
                    label = text
                    break
        memberships[player_id] = (jersey, label)
    return identities, memberships


def _parse_coaches(
    soup: BeautifulSoup,
    *,
    base_url: str,
    view: str,
    issues: list[str],
) -> dict[int, TeamSeasonCoach]:
    table = soup.find(id="taulaentrenadors")
    if not isinstance(table, Tag):
        return {}
    indexes = _header_indexes(table)
    coaches: dict[int, TeamSeasonCoach] = {}
    for row in _table_rows(table)[1:]:
        anchor = next(
            (
                item
                for cell in row
                for item in cell.select("a[href]")
                if _COACH_URL_ID.search(urlsplit(str(item["href"])).path)
            ),
            None,
        )
        linked = _id_from_link(anchor, _COACH_URL_ID) if anchor else None
        if linked is None:
            continue
        coach_id, href = linked
        display_name, full_name = _name_parts(anchor)
        photo = next(
            (cell.select_one("img[src]") for cell in row if cell.select_one("img[src]")),
            None,
        )
        age_cell = _cell(row, indexes, "edad")
        if age_cell is None:
            age_cell = _cell(row, indexes, "edat")
        birth_date_cell = _cell(row, indexes, "fecha de nacimiento")
        birthplace_cell = _cell(row, indexes, "lugar de nacimiento")
        province_cell = _cell(row, indexes, "provincia")
        matchday_cell = _cell(row, indexes, "jornadas")
        matches_cell = _cell(row, indexes, "partidos")
        yellow_cell = _cell(row, indexes, "tarjetas amarillas") or _cell(row, indexes, "ta")
        red_cell = _cell(row, indexes, "tarjetas rojas") or _cell(row, indexes, "tr")
        candidate = TeamSeasonCoach(
            coach_id=coach_id,
            display_name=display_name,
            full_name=full_name,
            profile_url=_absolute(base_url, href) or href,
            photo_url=_absolute(base_url, str(photo["src"])) if photo else None,
            age_years=_int_cell(age_cell, field_name="coach_age"),
            birth_date=_parse_date(birth_date_cell.get_text(" ", strip=True)) if birth_date_cell else None,
            birthplace=_clean_nullable(birthplace_cell.get_text(" ", strip=True)) if birthplace_cell else None,
            birthplace_province=_clean_nullable(province_cell.get_text(" ", strip=True)) if province_cell else None,
            coached_matchdays_source=_clean_nullable(matchday_cell.get_text(" ", strip=True)) if matchday_cell else None,
            matches_managed=_int_cell(matches_cell, field_name="matches_managed"),
            yellow_cards=_int_cell(yellow_cell, field_name="coach_yellow_cards"),
            red_cards=_int_cell(red_cell, field_name="coach_red_cards"),
            source_views=(view,),
        )
        previous = coaches.get(coach_id)
        if previous is None:
            coaches[coach_id] = candidate
            continue
        merged: dict[str, Any] = {}
        for field_name in TeamSeasonCoach.__dataclass_fields__:
            old_value = getattr(previous, field_name)
            new_value = getattr(candidate, field_name)
            if field_name == "source_views":
                merged[field_name] = tuple(sorted(set(old_value) | set(new_value)))
            elif old_value is None and new_value is not None:
                merged[field_name] = new_value
            elif old_value is not None and new_value is not None and old_value != new_value:
                issues.append(
                    f"coach_id={coach_id}: conflicto en {field_name} entre vistas; "
                    "se conserva el primer valor"
                )
                merged[field_name] = old_value
            else:
                merged[field_name] = old_value
        coaches[coach_id] = TeamSeasonCoach(**merged)
    return coaches


def _parse_statistics(
    soup: BeautifulSoup,
    *,
    base_url: str,
    view: str,
    issues: list[str],
) -> tuple[dict[int, dict[str, Any]], dict[int, PlayerSeasonStatistics]]:
    table = soup.find(id="c3p0")
    if not isinstance(table, Tag):
        return {}, {}
    rows = _table_rows(table)
    if not rows:
        raise TeamProfileParseError("#c3p0 no contiene encabezados")
    indexes: dict[str, int] = {}
    for index, header in enumerate(rows[0]):
        code = str(header.get("data-colid") or "")
        if code in _STAT_COLUMNS:
            title = clean_text(str(header.get("title") or header.get_text(" ", strip=True)))
            expected_title = _STAT_COLUMNS[code][1]
            if title and title.casefold() != expected_title.casefold():
                raise TeamProfileParseError(
                    f"#c3p0 columna {code} cambió de {expected_title!r} a {title!r}"
                )
            indexes[code] = index
    missing = sorted(set(_STAT_COLUMNS) - indexes.keys())
    if missing:
        raise TeamProfileParseError(f"#c3p0 no publica columnas semánticas: {missing}")

    identities: dict[int, dict[str, Any]] = {}
    statistics: dict[int, PlayerSeasonStatistics] = {}
    for row in rows[1:]:
        # Resolve identity from the player-profile link, not the visible name.
        parsed_identity = _identity_from_row(
            row,
            base_url=base_url,
            view=view,
            indexes={
                "dor": 0,
                "fot": 1,
                "pais": 2,
                "nom": 3,
                "pos": 4,
            },
        )
        if parsed_identity is None:
            continue
        player_id, details = parsed_identity
        if player_id in statistics:
            raise TeamProfileParseError(f"player_id duplicado en #c3p0: {player_id}")
        identities[player_id] = details
        raw_values = {
            field_name: _int_cell(
                row[indexes[code]] if indexes[code] < len(row) else None,
                field_name=field_name,
            )
            for code, (field_name, _) in _STAT_COLUMNS.items()
        }
        statistics[player_id] = PlayerSeasonStatistics(
            player_id=player_id,
            team_id=0,
            season="",
            competition="",
            group="",
            **raw_values,
            source_view=view,
        )
    if not identities and len(rows) > 1:
        issues.append("#c3p0 tiene tabla pero no se identificaron jugadores por ID")
    return identities, statistics


def _parse_follow(
    soup: BeautifulSoup,
    *,
    team_id: int,
    season: str,
    competition: str,
    group: str,
) -> tuple[PlayerMatchMinutes, ...]:
    table = soup.find(id="taula-seguiment")
    if not isinstance(table, Tag):
        return ()
    select = soup.find(id="vista_jornades")
    state = str(select.get("value") or "") if isinstance(select, Tag) else ""
    if isinstance(select, Tag):
        selected = select.select_one("option[selected]")
        if selected is not None:
            state = str(selected.get("value") or state)
    state = state or "p"
    if state != "p":
        raise TeamProfileParseError(
            f"Seguimiento solo está semánticamente validado en estado Partidos (p), no {state!r}"
        )
    rows = _table_rows(table)
    if not rows:
        return ()
    matchdays: list[tuple[int, int]] = []
    for index, header in enumerate(rows[0][1:], start=1):
        value = _optional_int(header.get_text(" ", strip=True), field_name="tracking_matchday")
        if value is not None:
            matchdays.append((index, value))
    records: list[PlayerMatchMinutes] = []
    for row in rows[1:]:
        anchor = _row_player_anchor(row)
        linked = _id_from_link(anchor, _PLAYER_URL_ID) if anchor else None
        if linked is None:
            continue
        player_id, _ = linked
        for cell_index, matchday in matchdays:
            if cell_index >= len(row):
                continue
            cell = row[cell_index]
            match_link = next(
                (
                    link
                    for link in cell.select("a[href]")
                    if "p.php?id=" in str(link["href"])
                ),
                None,
            )
            match_id_match = _MATCH_URL_ID.search(str(match_link["href"])) if match_link else None
            if match_id_match is None:
                continue
            raw_value = clean_text(cell.get_text(" ", strip=True))
            records.append(
                PlayerMatchMinutes(
                    player_id=player_id,
                    team_id=team_id,
                    season=season,
                    competition=competition,
                    group=group,
                    matchday=matchday,
                    match_id=match_id_match.group(1),
                    metric="minutes_played",
                    value=_optional_int(raw_value, field_name="minutes_played_by_match"),
                    raw_value=raw_value,
                    source_view="follow",
                    source_state="p",
                )
            )
    keys = {(record.player_id, record.match_id) for record in records}
    if len(keys) != len(records):
        raise TeamProfileParseError("Seguimiento repite el mismo jugador y partido")
    return tuple(records)


def _parse_follow_event_metrics(
    soup: BeautifulSoup,
    *,
    state: str,
    team_id: int,
    season: str,
    competition: str,
    group: str,
) -> tuple[tuple[PlayerMatchMetric, ...], tuple[str, ...]]:
    """Parse positive card/goal facts from their dedicated Seguimiento views.

    The numeric labels in state ``t`` remain playing minutes, so card values
    are taken only from the source's explicit event classes. The ``go`` state
    changes the cell number to a goals-against-that-player count.
    """
    table = soup.find(id="taula-seguiment")
    if not isinstance(table, Tag):
        return (), ()
    if state not in {"t", "go"}:
        raise TeamProfileParseError(f"Estado de eventos no admitido: {state!r}")
    rows = _table_rows(table)
    if not rows:
        return (), ()
    matchdays: list[tuple[int, int]] = []
    for index, header in enumerate(rows[0][1:], start=1):
        matchday = _optional_int(header.get_text(" ", strip=True), field_name="tracking_matchday")
        if matchday is not None:
            matchdays.append((index, matchday))
    records: list[PlayerMatchMetric] = []
    warnings: list[str] = []
    for row in rows[1:]:
        anchor = _row_player_anchor(row)
        linked_player = _id_from_link(anchor, _PLAYER_URL_ID) if anchor else None
        if linked_player is None:
            continue
        player_id, _ = linked_player
        for cell_index, matchday in matchdays:
            if cell_index >= len(row):
                continue
            cell = row[cell_index]
            match_link = next(
                (link for link in cell.select("a[href]") if "p.php?id=" in str(link["href"])),
                None,
            )
            match = _MATCH_URL_ID.search(str(match_link["href"])) if match_link else None
            if match is None:
                continue
            wrapper = cell.select_one(".segdiv")
            classes = set(wrapper.get("class", [])) if wrapper else set()
            raw_value = clean_text(cell.get_text(" ", strip=True))
            if state == "t":
                yellow_count = int("tg1" in classes) + int("tg2" in classes)
                if yellow_count:
                    yellow_markers = [marker for marker in ("tg1", "tg2") if marker in classes]
                    records.append(PlayerMatchMetric(
                        player_id=player_id,
                        team_id=team_id,
                        season=season,
                        competition=competition,
                        group=group,
                        matchday=matchday,
                        match_id=match.group(1),
                        metric="yellow_cards",
                        value=yellow_count,
                        raw_value=" ".join(yellow_markers),
                        source_view="follow",
                        source_state="t",
                    ))
                if "tv" in classes:
                    records.append(PlayerMatchMetric(
                        player_id=player_id,
                        team_id=team_id,
                        season=season,
                        competition=competition,
                        group=group,
                        matchday=matchday,
                        match_id=match.group(1),
                        metric="red_cards",
                        value=1,
                        raw_value="tv",
                        source_view="follow",
                        source_state="t",
                    ))
                continue
            if "gol" not in classes:
                continue
            value = _optional_int(raw_value, field_name="follow_goals")
            if value is None:
                raise TeamProfileParseError(
                    f"Seguimiento estado go marca gol sin valor: player_id={player_id}, match_id={match.group(1)}"
                )
            records.append(PlayerMatchMetric(
                player_id=player_id,
                team_id=team_id,
                season=season,
                competition=competition,
                group=group,
                matchday=matchday,
                match_id=match.group(1),
                metric="goals",
                value=value,
                raw_value=raw_value,
                source_view="follow",
                source_state="go",
            ))
    keys = {(item.player_id, item.match_id, item.metric) for item in records}
    if len(keys) != len(records):
        raise TeamProfileParseError(f"Seguimiento estado {state} repite jugador, partido y métrica")
    return tuple(records), tuple(dict.fromkeys(warnings))


def _follow_marker_keys(soup: BeautifulSoup, *, marker_class: str) -> set[tuple[int, str]]:
    keys: set[tuple[int, str]] = set()
    table = soup.find(id="taula-seguiment")
    if not isinstance(table, Tag):
        return keys
    for row in _table_rows(table)[1:]:
        player_anchor = _row_player_anchor(row)
        linked_player = _id_from_link(player_anchor, _PLAYER_URL_ID) if player_anchor else None
        if linked_player is None:
            continue
        player_id, _ = linked_player
        for cell in row:
            wrapper = cell.select_one(".segdiv")
            if wrapper is None or marker_class not in wrapper.get("class", []):
                continue
            match_link = next(
                (link for link in cell.select("a[href]") if "p.php?id=" in str(link["href"])),
                None,
            )
            match = _MATCH_URL_ID.search(str(match_link["href"])) if match_link else None
            if match:
                keys.add((player_id, match.group(1)))
    return keys


def _parse_transfers(
    soup: BeautifulSoup,
    *,
    team_id: int,
    season: str,
    competition: str,
    group: str,
    base_url: str,
) -> tuple[tuple[TeamTransfer, ...], tuple[TeamTransferSection, ...]]:
    """Parse the shared Altas/Bajas table using its explicit section headers.

    BDFutbol places both sections in one table. The Bajas title is a separator
    row and is followed by a second column-header row whose final column changes
    from "Equipo origen" to "Equipo destino". Unknown layouts are rejected so
    a section can never silently inherit the wrong direction.
    """
    root = soup.select_one("#pestaltesbaixes")
    if not isinstance(root, Tag):
        raise TeamProfileParseError("La vista Traspasos no contiene #pestaltesbaixes")
    headings = [clean_text(item.get_text(" ", strip=True)) for item in root.select("h2")]
    if headings != ["Altas", "Bajas"]:
        raise TeamProfileParseError(
            f"Encabezados de Traspasos inesperados: {headings!r}; se requieren Altas y Bajas"
        )
    tables = root.select("table")
    if len(tables) != 1:
        raise TeamProfileParseError(
            f"Estructura de Traspasos desconocida: se esperaba una tabla compartida, hay {len(tables)}"
        )
    table_rows = _table_rows(tables[0])
    if not table_rows:
        raise TeamProfileParseError("La tabla de Traspasos está vacía y no demuestra sus secciones")

    expected_column = {"incoming": "equipo origen", "outgoing": "equipo destino"}
    heading_by_direction = {"incoming": "Altas", "outgoing": "Bajas"}
    direction = "incoming"
    section_counts = {"incoming": 0, "outgoing": 0}
    seen_headers: set[str] = set()
    transfers: list[TeamTransfer] = []
    for row in table_rows:
        section_heading = next(
            (clean_text(item.get_text(" ", strip=True)) for cell in row for item in cell.select("h2")),
            None,
        )
        if section_heading is not None:
            if section_heading != "Bajas" or direction != "incoming":
                raise TeamProfileParseError(f"Separador de sección inesperado: {section_heading!r}")
            direction = "outgoing"
            continue

        header_cells = [
            clean_text(str(cell.get("title") or cell.get_text(" ", strip=True))).casefold()
            for cell in row
        ]
        relation_columns = [value for value in header_cells if value in {"equipo origen", "equipo destino"}]
        if relation_columns:
            if len(relation_columns) != 1 or relation_columns[0] != expected_column[direction]:
                raise TeamProfileParseError(
                    f"Cabecera incompatible con {heading_by_direction[direction]}: {relation_columns!r}"
                )
            if "apodo y nombre" not in header_cells or "edad" not in header_cells:
                raise TeamProfileParseError("La cabecera de Traspasos no contiene identidad y edad reconocibles")
            if (
                len(row) != 6
                or header_cells[2] != "apodo y nombre"
                or header_cells[3] != "edad"
                or header_cells[4] not in {"demarcación", "pos"}
                or header_cells[5] != expected_column[direction]
            ):
                raise TeamProfileParseError("La disposición de columnas de Traspasos no coincide con la estructura verificada")
            if direction in seen_headers:
                raise TeamProfileParseError(f"Cabecera duplicada para {heading_by_direction[direction]}")
            seen_headers.add(direction)
            continue

        player_anchors = [
            anchor
            for cell in row
            for anchor in cell.select("a[href]")
            if _PLAYER_URL_ID.search(urlsplit(str(anchor["href"])).path)
        ]
        if not player_anchors:
            row_text = clean_text(" ".join(cell.get_text(" ", strip=True) for cell in row))
            if not row_text:
                continue
            raise TeamProfileParseError(
                f"Fila de Traspasos no reconocida bajo {heading_by_direction[direction]}: {row_text[:120]!r}"
            )
        if direction not in seen_headers:
            raise TeamProfileParseError(f"Hay jugadores antes de la cabecera de {heading_by_direction[direction]}")
        if len(player_anchors) != 1:
            raise TeamProfileParseError("Una fila de Traspasos contiene varias identidades de jugador")
        player_link = player_anchors[0]
        player_ref = _id_from_link(player_link, _PLAYER_URL_ID)
        if player_ref is None:
            raise TeamProfileParseError("Fila de Traspasos con enlace de jugador inválido")
        player_id, player_href = player_ref
        player_display_name, player_full_name = _name_parts(player_link)
        if not player_display_name:
            raise TeamProfileParseError(f"Traspaso sin nombre visible para player_id={player_id}")

        cells = row
        if len(cells) != 7 or not cells[2].select_one('a[href*="/j/j"]'):
            raise TeamProfileParseError(f"Fila incompleta o mal alineada para player_id={player_id}")
        age = _optional_int(
            cells[3].get_text(" ", strip=True), field_name="transfer_age"
        ) if clean_text(cells[3].get_text(" ", strip=True)) else None
        position = None
        position_div = cells[4].select_one("div[class]") if len(cells) > 4 else None
        if position_div:
            position = next(
                (str(value) for value in position_div.get("class", []) if str(value) in {"por", "def", "mig", "dav"}),
                None,
            )
        photo = cells[0].select_one("img[src]")
        other_cell = cells[-1]
        other_links = [
            anchor
            for anchor in other_cell.select("a[href]")
            if not _PLAYER_URL_ID.search(urlsplit(str(anchor["href"])).path)
        ]
        if len(other_links) > 1:
            raise TeamProfileParseError(f"Más de un equipo relacionado para player_id={player_id}")
        team_link = other_links[0] if other_links else None
        other_url = _absolute(base_url, str(team_link["href"])) if team_link else None
        other_name = clean_text((team_link or other_cell).get_text(" ", strip=True)) or None
        other_id = team_id_from_url(other_url) if other_url else None
        if other_url and other_id is None:
            raise TeamProfileParseError(f"URL del equipo relacionado no interpretable: {other_url}")
        transfers.append(
            TeamTransfer(
                player_id=player_id,
                player_display_name=player_display_name,
                player_full_name=player_full_name,
                player_profile_url=_absolute(base_url, player_href) or player_href,
                player_photo_url=_absolute(base_url, str(photo["src"])) if photo else None,
                team_id=team_id,
                season=season,
                competition=competition,
                group=group,
                direction=direction,
                other_team_name=other_name,
                other_team_id=other_id,
                other_team_url=other_url,
                age_years=age,
                source_position_code=position,
                transfer_date=None,
                fee=None,
                source_view="transfers",
                source_heading=heading_by_direction[direction],
            )
        )
        section_counts[direction] += 1

    if seen_headers != {"incoming", "outgoing"}:
        raise TeamProfileParseError(f"No se validaron las dos cabeceras de sección: {sorted(seen_headers)}")
    keys = {(item.direction, item.player_id) for item in transfers}
    if len(keys) != len(transfers):
        raise TeamProfileParseError("Traspasos repite una persona en la misma dirección")
    sections = tuple(
        TeamTransferSection(
            direction=key,
            source_heading=heading_by_direction[key],
            status="verified_with_rows" if section_counts[key] else "verified_empty",
            row_count=section_counts[key],
            source_team_column="Equipo origen" if key == "incoming" else "Equipo destino",
        )
        for key in ("incoming", "outgoing")
    )
    return tuple(transfers), sections


def parse_team_transfers_snapshot(
    source_html: str,
    *,
    team_id: int,
    season: str,
    competition: str,
    group: str,
    base_url: str,
) -> tuple[tuple[TeamTransfer, ...], tuple[TeamTransferSection, ...]]:
    """Parse a single saved Traspasos document without a browser or network."""
    return _parse_transfers(
        BeautifulSoup(source_html, "html.parser"),
        team_id=team_id,
        season=season,
        competition=competition,
        group=group,
        base_url=base_url,
    )


def _parse_match_ids(soup: BeautifulSoup) -> tuple[str, ...]:
    table = soup.find(id="taula-resultats-plantilla")
    if not isinstance(table, Tag):
        return ()
    found: list[str] = []
    for anchor in table.select('a[href*="p.php?id="]'):
        match = _MATCH_URL_ID.search(str(anchor["href"]))
        if match:
            found.append(match.group(1))
    return tuple(dict.fromkeys(found))


def _parse_group_team_ids(soup: BeautifulSoup) -> tuple[int, ...]:
    table = soup.find(id="classific")
    if not isinstance(table, Tag):
        return ()
    team_ids: set[int] = set()
    for anchor in table.select("a[href]"):
        team_id = team_id_from_url(urljoin("https://www.bdfutbol.com/es/t/", str(anchor["href"])))
        if team_id is not None:
            team_ids.add(team_id)
    return tuple(sorted(team_ids))


def _require_view(views: dict[str, str], view: str, selector: str) -> BeautifulSoup | None:
    source = views.get(view)
    if source is None:
        return None
    soup = BeautifulSoup(source, "html.parser")
    if soup.select_one(selector) is None:
        raise TeamProfileParseError(f"La vista {view} no contiene {selector}")
    return soup


def parse_team_profile_pages(
    views: dict[str, str],
    *,
    team_catalog_record: dict[str, Any],
    competition_context: CompetitionContext,
    follow_state_html: dict[str, str] | None = None,
) -> TeamProfileData:
    """Normalize available team views without browser access or name-based joins."""
    team_id = int(team_catalog_record["team_id"])
    team_url = str(team_catalog_record["team_url"])
    team_parts = urlsplit(team_url)
    if team_parts.scheme != "https" or team_parts.hostname not in {"bdfutbol.com", "www.bdfutbol.com"}:
        raise TeamProfileParseError(f"team_url no pertenece a BDFutbol: {team_url}")
    if team_id_from_url(team_url) != team_id:
        raise TeamProfileParseError(
            f"team_url del catálogo no coincide con team_id={team_id}: {team_url}"
        )
    name = str(team_catalog_record.get("name") or team_catalog_record.get("team_name") or "")
    if not name:
        raise TeamProfileParseError("El catálogo no publica un nombre de equipo")
    if not views or "alignment" not in views:
        raise TeamProfileParseError("Se requiere la vista real Alineación")
    alignment = _require_view(views, "alignment", "#taulaplantilla")
    assert alignment is not None
    heading = alignment.select_one("h1")
    heading_text = clean_text(heading.get_text(" ", strip=True)) if heading else ""
    title = clean_text(alignment.title.get_text(" ", strip=True)) if alignment.title else ""
    if name.casefold() not in f"{heading_text} {title}".casefold():
        raise TeamProfileParseError(
            f"La ficha no confirma la identidad del catálogo {name!r}: {heading_text!r}"
        )
    if competition_context.season not in f"{heading_text} {title}":
        raise TeamProfileParseError("La ficha no confirma la temporada seleccionada")

    issues: list[str] = []
    player_details: dict[int, dict[str, Any]] = {}
    membership_values: dict[int, dict[str, Any]] = {}
    coaches_by_id: dict[int, TeamSeasonCoach] = {}
    source_selectors = {
        "alignment": "#taulaplantilla",
        "squad": "#c3p1",
        "statistics": "#c3p0",
    }
    for view, selector in source_selectors.items():
        if view not in views:
            continue
        soup = _require_view(views, view, selector)
        assert soup is not None
        _merge_coaches = _parse_coaches(
            soup, base_url=team_url, view=view, issues=issues
        )
        for coach_id, coach in _merge_coaches.items():
            previous = coaches_by_id.get(coach_id)
            if previous is None:
                coaches_by_id[coach_id] = coach
                continue
            merged_values: dict[str, Any] = {}
            for field_name in TeamSeasonCoach.__dataclass_fields__:
                previous_value = getattr(previous, field_name)
                new_value = getattr(coach, field_name)
                if field_name == "source_views":
                    merged_values[field_name] = tuple(sorted(set(previous_value) | set(new_value)))
                elif previous_value is None:
                    merged_values[field_name] = new_value
                else:
                    if new_value is not None and previous_value != new_value:
                        issues.append(
                            f"coach_id={coach_id}: {field_name} no coincide entre vistas"
                        )
                    merged_values[field_name] = previous_value
            coaches_by_id[coach_id] = TeamSeasonCoach(**merged_values)

        if view in {"alignment", "squad"}:
            parsed, memberships = _parse_players_from_table(
                soup,
                "taulaplantilla" if view == "alignment" else "c3p1",
                base_url=team_url,
                view=view,
                issues=issues,
            )
            for player_id, details in parsed.items():
                _merge_identity(player_details, player_id, details, issues)
                jersey, squad_group = memberships[player_id]
                current = membership_values.setdefault(
                    player_id,
                    {"jersey_number": None, "squad_group_label": None, "source_views": set()},
                )
                if jersey is not None:
                    if current["jersey_number"] not in {None, jersey}:
                        issues.append(f"player_id={player_id}: dorsal distinto entre vistas")
                    else:
                        current["jersey_number"] = jersey
                if squad_group:
                    current["squad_group_label"] = squad_group
                current["source_views"].add(view)

    statistics: dict[int, PlayerSeasonStatistics] = {}
    if "statistics" in views:
        soup = _require_view(views, "statistics", "#c3p0")
        assert soup is not None
        parsed, parsed_statistics = _parse_statistics(
            soup, base_url=team_url, view="statistics", issues=issues
        )
        for player_id, details in parsed.items():
            _merge_identity(player_details, player_id, details, issues)
            membership_values.setdefault(
                player_id,
                {"jersey_number": None, "squad_group_label": None, "source_views": set()},
            )["source_views"].add("statistics")
        for player_id, stat in parsed_statistics.items():
            statistics[player_id] = PlayerSeasonStatistics(
                player_id=player_id,
                team_id=team_id,
                season=competition_context.season,
                competition=competition_context.competition,
                group=competition_context.group_roman,
                **{
                    key: getattr(stat, key)
                    for key in PlayerSeasonStatistics.__dataclass_fields__
                    if key not in {"player_id", "team_id", "season", "competition", "group", "source_view"}
                },
                source_view="statistics",
            )

    player_rows = tuple(
        PlayerIdentity(player_id=player_id, **details)
        for player_id, details in sorted(player_details.items())
    )
    memberships = tuple(
        PlayerTeamMembership(
            player_id=player_id,
            team_id=team_id,
            season=competition_context.season,
            competition=competition_context.competition,
            group=competition_context.group_roman,
            jersey_number=values["jersey_number"],
            squad_group_label=values["squad_group_label"],
            source_views=tuple(sorted(values["source_views"])),
        )
        for player_id, values in sorted(membership_values.items())
    )

    follow = _require_view(views, "follow", "#taula-seguiment") if "follow" in views else None
    for state, state_html in (follow_state_html or {}).items():
        state_soup = BeautifulSoup(state_html, "html.parser")
        if state not in {"p", "t", "go", "tot"}:
            raise TeamProfileParseError(f"Estado de seguimiento no reconocido: {state!r}")
        if state_soup.select_one("#taula-seguiment") is None:
            raise TeamProfileParseError(f"El snapshot de seguimiento {state!r} no contiene la tabla")
        select = state_soup.select_one("#vista_jornades")
        option_values = {str(option.get("value")) for option in select.select("option")} if select else set()
        if state not in option_values:
            raise TeamProfileParseError(f"El snapshot de seguimiento no ofrece la opción {state!r}")
    match_minutes = (
        _parse_follow(
            follow,
            team_id=team_id,
            season=competition_context.season,
            competition=competition_context.competition,
            group=competition_context.group_roman,
        )
        if follow
        else ()
    )
    follow_metrics: list[PlayerMatchMetric] = []
    follow_warnings: list[str] = []
    state_soups: dict[str, BeautifulSoup] = {}
    for state, state_html in (follow_state_html or {}).items():
        state_soup = BeautifulSoup(state_html, "html.parser")
        state_soups[state] = state_soup
        if state == "t":
            rows, warnings = _parse_follow_event_metrics(
                state_soup,
                state=state,
                team_id=team_id,
                season=competition_context.season,
                competition=competition_context.competition,
                group=competition_context.group_roman,
            )
            follow_metrics.extend(rows)
            follow_warnings.extend(warnings)
        elif state == "go":
            rows, warnings = _parse_follow_event_metrics(
                state_soup,
                state=state,
                team_id=team_id,
                season=competition_context.season,
                competition=competition_context.competition,
                group=competition_context.group_roman,
            )
            follow_metrics.extend(rows)
            follow_warnings.extend(warnings)

    if "tot" in state_soups and "t" in state_soups and "go" in state_soups:
        total_soup = state_soups["tot"]
        yellow_keys = {
            (item.player_id, item.match_id)
            for item in follow_metrics
            if item.metric == "yellow_cards"
        }
        total_yellow_keys = _follow_marker_keys(total_soup, marker_class="tg1")
        total_yellow_keys.update(_follow_marker_keys(total_soup, marker_class="tg2"))
        red_keys = {
            (item.player_id, item.match_id)
            for item in follow_metrics
            if item.metric == "red_cards"
        }
        total_red_keys = _follow_marker_keys(total_soup, marker_class="tv")
        goal_keys = {
            (item.player_id, item.match_id)
            for item in follow_metrics
            if item.metric == "goals"
        }
        total_goal_keys = _follow_marker_keys(total_soup, marker_class="gol-marca")
        if yellow_keys != total_yellow_keys:
            follow_warnings.append("La vista Todo no reproduce todas las marcas amarillas del estado Tarjetas")
        if red_keys != total_red_keys:
            follow_warnings.append("La vista Todo no reproduce todas las marcas rojas del estado Tarjetas")
        if goal_keys != total_goal_keys:
            follow_warnings.append("La vista Todo no reproduce todas las marcas de gol del estado Goles")
    follow_metric_keys = {
        (item.player_id, item.match_id, item.metric) for item in follow_metrics
    }
    if len(follow_metric_keys) != len(follow_metrics):
        raise TeamProfileParseError("Seguimiento repite una métrica por jugador y partido")
    transfers_soup = views.get("transfers")
    transfers_parsed_soup = BeautifulSoup(transfers_soup, "html.parser") if transfers_soup else None
    if transfers_parsed_soup is not None and transfers_parsed_soup.select_one("#pestaltesbaixes") is None:
        raise TeamProfileParseError("La vista Traspasos no contiene el contenedor #pestaltesbaixes")
    transfers, transfer_sections = (
        _parse_transfers(
            transfers_parsed_soup,
            team_id=team_id,
            season=competition_context.season,
            competition=competition_context.competition,
            group=competition_context.group_roman,
            base_url=team_url,
        )
        if transfers_soup
        else ((), ())
    )
    match_soup = (
        _require_view(views, "matches", "#taula-resultats-plantilla")
        if "matches" in views
        else None
    )
    group_team_ids = _parse_group_team_ids(alignment)
    match_ids = _parse_match_ids(match_soup) if match_soup else ()
    tactic_note = "Se genera automáticamente a partir de las posiciones del once titular"
    if tactic_note not in clean_text(alignment.get_text(" ", strip=True)):
        issues.append("La nota de representación táctica aproximada no está presente")

    for coach_id, coach in tuple(coaches_by_id.items()):
        if not coach.display_name or coach.coach_id != coach_id:
            issues.append(f"Entrenador sin identidad coherente: coach_id={coach_id}")
    if len({player.player_id for player in player_rows}) != len(player_rows):
        raise TeamProfileParseError("Identidades de jugador duplicadas tras unir las vistas")
    if len({membership.player_id for membership in memberships}) != len(memberships):
        raise TeamProfileParseError("Pertenencias duplicadas en el mismo equipo y temporada")
    dangling_memberships = {item.player_id for item in memberships} - {
        item.player_id for item in player_rows
    }
    if dangling_memberships:
        raise TeamProfileParseError(f"Pertenencias sin identidad de jugador: {sorted(dangling_memberships)}")

    warnings = list(issues) + follow_warnings
    if "squad" not in views:
        warnings.append("No se capturó la vista Plantilla con fecha/lugar de nacimiento")
    if "follow" not in views:
        warnings.append("No se capturó Seguimiento")
    if "transfers" not in views:
        warnings.append("No se capturó Traspasos")
    if "matches" not in views:
        warnings.append("No se capturó la vista Partidos")
    if not coaches_by_id:
        warnings.append("La fuente no publicó un entrenador identificable")

    identity = TeamIdentity(
        team_id=team_id,
        name=name,
        team_url=team_url,
        crest_url=team_catalog_record.get("crest_url"),
    )
    season = TeamSeason(
        team_id=team_id,
        season=competition_context.season,
        competition=competition_context.competition,
        group=competition_context.group_roman,
        competition_scope="Liga",
        coaches=tuple(coaches_by_id[key] for key in sorted(coaches_by_id)),
    )
    return TeamProfileData(
        identity=identity,
        season=season,
        players=player_rows,
        memberships=memberships,
        player_statistics=tuple(statistics[key] for key in sorted(statistics)),
        player_match_minutes=match_minutes,
        player_match_metrics=tuple(sorted(follow_metrics, key=lambda item: (item.matchday, item.player_id, item.metric))),
        follow_states_captured=tuple(sorted(follow_state_html or {})),
        transfers=transfers,
        transfer_sections=transfer_sections,
        group_team_ids_from_profile=group_team_ids,
        team_match_ids_from_profile=match_ids,
        warnings=tuple(warnings),
    )


def _unused_player_key(player_id: int) -> str:
    """Stable key helper for diagnostics that may later include player labels."""
    return f"player_id={player_id}"
