from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .ids import (
    ProviderRef,
    match_id_from_url,
    referee_id_from_url,
    stadium_id_from_url,
    team_season_id_from_url,
)
from .models import CompetitionContext, CompetitionSnapshot, Fixture, StandingRow


class CompetitionParseError(ValueError):
    pass


_CONTEXT_RE = re.compile(
    r"/t/t(?P<season>\d{4}-\d{2})(?P<competition>1rf)(?P<group>\d+)\.html$",
    re.IGNORECASE,
)
_SE_RE = re.compile(r'SE\[(?P<index>\d+)\]\s*=\s*"(?P<slot>\d+)\|(?P<name>[^"]*)";')
_SP_RE = re.compile(r"SP\[(?P<round>\d+)\]\.push\((?P<payload>\{.*?\})\);", re.DOTALL)

_STANDINGS_REQUIRED_HEADERS = {"PJ", "PG", "PE", "PP", "GF", "GC", "TA", "TR"}


def _clean_text(node: Tag | None) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def _normalized_name(value: str) -> str:
    return " ".join(value.split()).casefold()


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    if not re.fullmatch(r"-?\d+", value):
        return None
    return int(value)


def _context_source_url(soup: BeautifulSoup, source_url: str) -> str:
    canonical = soup.select_one('link[rel="canonical"][href]')
    if canonical:
        href = canonical.get("href")
        if isinstance(href, str) and "/t/t" in href:
            return href
    return source_url


def parse_competition_context(html: str, source_url: str) -> CompetitionContext:
    soup = BeautifulSoup(html, "lxml")
    effective_url = _context_source_url(soup, source_url)
    path = re.sub(r"[?#].*$", "", effective_url)
    match = _CONTEXT_RE.search(path)
    if not match:
        raise CompetitionParseError(
            f"No se pudo extraer competición/temporada/grupo de {effective_url!r}."
        )
    return CompetitionContext(
        competition_code=match.group("competition").lower(),
        season=match.group("season"),
        group=int(match.group("group")),
        source_url=effective_url,
    )


def _extract_source_team_slots(html: str) -> dict[int, str]:
    slots: dict[int, str] = {}
    for match in _SE_RE.finditer(html):
        index = int(match.group("index"))
        slot = int(match.group("slot"))
        if index != slot:
            raise CompetitionParseError(
                f"SE[{index}] declara slot {slot}; no se asume equivalencia silenciosamente."
            )
        slots[index] = match.group("name").strip()
    if not slots:
        raise CompetitionParseError("No se encontró el array SE de equipos.")
    return slots


def _extract_sp_rows(html: str) -> list[tuple[int, dict[str, str]]]:
    rows: list[tuple[int, dict[str, str]]] = []
    for match in _SP_RE.finditer(html):
        round_number = int(match.group("round"))
        try:
            payload = json.loads(match.group("payload"))
        except json.JSONDecodeError as exc:
            raise CompetitionParseError(
                f"No se pudo decodificar un registro SP de la jornada {round_number}."
            ) from exc
        rows.append((round_number, payload))

    if not rows:
        raise CompetitionParseError("No se encontraron registros SP de partidos.")

    ids = [_int_or_none(row.get("id")) for _, row in rows]
    valid_ids = [value for value in ids if value is not None]
    duplicates = [value for value, count in Counter(valid_ids).items() if count > 1]
    if duplicates:
        raise CompetitionParseError(f"Match IDs duplicados en SP: {duplicates[:10]}")
    if len(valid_ids) != len(rows):
        raise CompetitionParseError("Hay registros SP sin match_id numérico.")

    return rows


def _find_standings_table(soup: BeautifulSoup) -> Tag | None:
    for table in soup.select("table"):
        headers = {_clean_text(th).rstrip(".") for th in table.select("th")}
        if _STANDINGS_REQUIRED_HEADERS.issubset(headers) and (
            "Pts" in headers or "Pts." in {_clean_text(th) for th in table.select("th")}
        ):
            return table
    return None


def _parse_standings(soup: BeautifulSoup, season: str) -> tuple[StandingRow, ...]:
    table = _find_standings_table(soup)
    if table is None:
        return ()

    rows: list[StandingRow] = []
    for tr in table.select("tr"):
        cells = tr.find_all(["td", "th"], recursive=False)
        if not cells or tr.find("th"):
            continue

        team_anchor: Tag | None = None
        team_id: int | None = None
        for anchor in tr.select("a[href]"):
            parsed_id = team_season_id_from_url(anchor.get("href"), season)
            if parsed_id is not None:
                team_anchor = anchor
                team_id = parsed_id
                break

        if team_anchor is None or team_id is None:
            continue

        team_cell = team_anchor.find_parent(["td", "th"])
        if team_cell is None:
            continue

        team_name = _clean_text(team_anchor)
        position: int | None = None
        for cell in cells[: cells.index(team_cell)]:
            candidate = _int_or_none(_clean_text(cell))
            if candidate is not None:
                position = candidate

        following = cells[cells.index(team_cell) + 1 :]
        values = [_int_or_none(_clean_text(cell)) for cell in following]
        numeric = [value for value in values if value is not None]
        if len(numeric) < 9:
            continue
        points, played, won, drawn, lost, gf, ga, yellow, red = numeric[:9]

        rows.append(
            StandingRow(
                team=ProviderRef("team", team_id),
                team_name=team_name,
                position=position,
                points=points,
                played=played,
                won=won,
                drawn=drawn,
                lost=lost,
                goals_for=gf,
                goals_against=ga,
                yellow_cards=yellow,
                red_cards=red,
                raw={"cells": [_clean_text(cell) for cell in cells]},
            )
        )

    return tuple(rows)


def _unique_team_refs_by_exact_name(
    standings: tuple[StandingRow, ...],
) -> dict[str, ProviderRef]:
    grouped: dict[str, list[ProviderRef]] = {}
    for row in standings:
        grouped.setdefault(_normalized_name(row.team_name), []).append(row.team)
    return {
        name: refs[0]
        for name, refs in grouped.items()
        if len({ref.key for ref in refs}) == 1
    }


def _dom_fixture_metadata(soup: BeautifulSoup) -> dict[tuple[int, str, str], dict[str, object]]:
    result: dict[tuple[int, str, str], dict[str, object]] = {}

    for tr in soup.select("tr[data-jornada]"):
        if tr.find("th"):
            continue
        cells = tr.find_all("td", recursive=False)
        if len(cells) != 6:
            continue

        round_value = tr.get("data-jornada")
        if not isinstance(round_value, str) or not round_value.isdigit():
            continue

        home_name = _clean_text(cells[1])
        away_name = _clean_text(cells[3])
        if not home_name or not away_name:
            continue

        match_id = None
        stadium_id = None
        referee_id = None
        stadium_name = None
        referee_name = None

        for anchor in tr.select("a[href]"):
            href = anchor.get("href")
            if not isinstance(href, str):
                continue
            match_id = match_id or match_id_from_url(href)
            parsed_stadium = stadium_id_from_url(href)
            if parsed_stadium is not None:
                stadium_id = parsed_stadium
                stadium_name = _clean_text(anchor) or None
            parsed_referee = referee_id_from_url(href)
            if parsed_referee is not None:
                referee_id = parsed_referee
                referee_name = _clean_text(anchor) or None

        key = (int(round_value), _normalized_name(home_name), _normalized_name(away_name))
        if key in result:
            raise CompetitionParseError(f"Fixture DOM duplicado para clave {key!r}.")

        result[key] = {
            "match_id": match_id,
            "stadium_id": stadium_id,
            "stadium_name": stadium_name,
            "referee_id": referee_id,
            "referee_name": referee_name,
            "score_text": _clean_text(cells[2]),
        }

    return result


def parse_competition(
    html: str,
    source_url: str,
    *,
    expected_team_count: int | None = None,
    expected_fixture_count: int | None = None,
) -> CompetitionSnapshot:
    context = parse_competition_context(html, source_url)
    soup = BeautifulSoup(html, "lxml")

    team_slots = _extract_source_team_slots(html)
    sp_rows = _extract_sp_rows(html)
    standings = _parse_standings(soup, context.season)
    team_refs = _unique_team_refs_by_exact_name(standings)
    dom_metadata = _dom_fixture_metadata(soup)

    warnings: list[str] = []
    if not standings:
        warnings.append("standings_not_found")

    fixtures: list[Fixture] = []
    unresolved_team_names: set[str] = set()

    for round_number, raw in sp_rows:
        home_slot = _int_or_none(raw.get("a1"))
        away_slot = _int_or_none(raw.get("a2"))
        match_id = _int_or_none(raw.get("id"))
        if home_slot is None or away_slot is None or match_id is None:
            raise CompetitionParseError(f"Registro SP incompleto: {raw!r}")
        if home_slot not in team_slots or away_slot not in team_slots:
            raise CompetitionParseError(f"Slot de equipo desconocido en SP: {raw!r}")

        home_name = team_slots[home_slot]
        away_name = team_slots[away_slot]
        home_ref = team_refs.get(_normalized_name(home_name))
        away_ref = team_refs.get(_normalized_name(away_name))
        if standings and home_ref is None:
            unresolved_team_names.add(home_name)
        if standings and away_ref is None:
            unresolved_team_names.add(away_name)

        key = (round_number, _normalized_name(home_name), _normalized_name(away_name))
        dom = dom_metadata.get(key, {})
        dom_match_id = dom.get("match_id")
        if dom_match_id is not None and dom_match_id != match_id:
            raise CompetitionParseError(
                f"Match ID SP/DOM no coincide para {home_name}-{away_name}: "
                f"{match_id} != {dom_match_id}"
            )

        raw_home_goals = _int_or_none(raw.get("g1"))
        raw_away_goals = _int_or_none(raw.get("g2"))
        played = (
            raw_home_goals is not None
            and raw_away_goals is not None
            and raw_home_goals >= 0
            and raw_away_goals >= 0
        )

        match_date = datetime.strptime(raw["d"], "%d/%m/%Y").date()
        stadium_id = dom.get("stadium_id")
        referee_id = dom.get("referee_id")

        fixtures.append(
            Fixture(
                match=ProviderRef("match", match_id),
                round_number=round_number,
                match_date=match_date,
                home_team_slot=home_slot,
                away_team_slot=away_slot,
                home_team_name=home_name,
                away_team_name=away_name,
                home_team=home_ref,
                away_team=away_ref,
                home_goals=raw_home_goals if played else None,
                away_goals=raw_away_goals if played else None,
                home_yellow_cards=_int_or_none(raw.get("tg1")) if played else None,
                away_yellow_cards=_int_or_none(raw.get("tg2")) if played else None,
                home_red_cards=_int_or_none(raw.get("tv1")) if played else None,
                away_red_cards=_int_or_none(raw.get("tv2")) if played else None,
                result_code=_int_or_none(raw.get("r")) if played else None,
                stadium=(
                    ProviderRef("stadium", int(stadium_id))
                    if isinstance(stadium_id, int)
                    else None
                ),
                stadium_name=dom.get("stadium_name") if isinstance(dom.get("stadium_name"), str) else None,
                referee=(
                    ProviderRef("referee", int(referee_id))
                    if isinstance(referee_id, int)
                    else None
                ),
                referee_name=dom.get("referee_name") if isinstance(dom.get("referee_name"), str) else None,
                raw={"sp": dict(raw), "dom": dict(dom)},
            )
        )

    if unresolved_team_names:
        warnings.append(
            "unresolved_team_refs:" + ",".join(sorted(unresolved_team_names))
        )

    if expected_team_count is not None and len(standings) != expected_team_count:
        raise CompetitionParseError(
            f"Se esperaban {expected_team_count} equipos en clasificación y se obtuvieron {len(standings)}."
        )
    if expected_fixture_count is not None and len(fixtures) != expected_fixture_count:
        raise CompetitionParseError(
            f"Se esperaban {expected_fixture_count} partidos y se obtuvieron {len(fixtures)}."
        )

    return CompetitionSnapshot(
        context=context,
        standings=standings,
        fixtures=tuple(fixtures),
        warnings=tuple(warnings),
    )
