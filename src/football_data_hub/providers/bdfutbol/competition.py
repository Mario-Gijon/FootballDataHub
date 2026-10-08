"""Parsers deterministas de las páginas de competición de BDFutbol.

El parser trabaja solo sobre HTML y no abre navegadores ni realiza solicitudes.
Los selectores se basan en los dos snapshots reales de Primera Federación 2026/27.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from football_data_hub.parsers.match_status import assess_match_status

PARSER_VERSION = "1.1.0"
COMPETITION_URLS = {
    "I": "https://www.bdfutbol.com/es/t/t2026-271rf1.html",
    "II": "https://www.bdfutbol.com/es/t/t2026-271rf2.html",
}
STANDING_HEADERS = ("Pts.", "PJ", "PG", "PE", "PP", "GF", "GC", "TA", "TR")
STANDING_FIELDS = {
    "Pts.": "points",
    "PJ": "played",
    "PG": "wins",
    "PE": "draws",
    "PP": "losses",
    "GF": "goals_for",
    "GC": "goals_against",
    "TA": "yellow_cards",
    "TR": "red_cards",
}
FIXTURE_HEADERS = ("Fecha", "Local", "", "Visitante", "Estadio", "Árbitro")
_ROUND_RE = re.compile(r"^Jornada\s+(\d+)\s*$", re.IGNORECASE)
_MATCH_SCORE_RE = re.compile(r"^(\d+)\s+(\d+)$")
_TEAM_ID_RE = re.compile(r"/t/(t\d{4}-\d+)\.html$")
_STADIUM_ID_RE = re.compile(r"/s/(\d+[a-z]?)\.html$", re.IGNORECASE)
_REFEREE_ID_RE = re.compile(r"/r/(r\d+)\.html$", re.IGNORECASE)


def _text(node: Tag) -> str:
    return " ".join(node.stripped_strings)


def _source_link(cell: Tag, page_url: str, pattern: re.Pattern[str]) -> tuple[str | None, str | None]:
    for anchor in cell.select("a[href]"):
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        absolute_url = urljoin(page_url, href)
        match = pattern.search(urlsplit(absolute_url).path)
        if match:
            return match.group(1), absolute_url
    return None, None


def _integer(raw_value: str) -> int | None:
    if re.fullmatch(r"\d+", raw_value.strip()):
        return int(raw_value)
    return None


def _date(raw_value: str) -> tuple[str | None, str | None]:
    if raw_value.strip() in {"", "—", "-"}:
        return None, None
    try:
        parsed = datetime.strptime(raw_value.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None, "date_unparseable"
    return parsed.isoformat(), None


def _parse_competition(source_url: str, title: str) -> dict[str, str | None]:
    route = urlsplit(source_url).path
    match = re.search(r"/(t2026-271rf([12]))\.html$", route)
    if not match:
        raise ValueError(f"URL de competición fuera del alcance: {source_url}")
    group = "I" if match.group(2) == "1" else "II"
    title_group = re.search(r"Grupo\s+(I{1,2})\b", title, re.IGNORECASE)
    source_season = re.search(r"\b(2026-27)\b", title)
    return {
        "provider": "bdfutbol",
        "name": "Primera Federación",
        "source_name": "1ª RFEF",
        "source_title": title or None,
        "season": "2026/27",
        "season_source": source_season.group(1) if source_season else None,
        "group": group,
        "group_source": title_group.group(1).upper() if title_group else None,
        "url": source_url,
        "source_route_id": match.group(1),
    }


def _parse_standings(
    soup: BeautifulSoup, page_url: str, group: str, issues: list[dict[str, object]]
) -> tuple[list[dict[str, object]], bool]:
    table = soup.find(id="classific")
    if not isinstance(table, Tag) or table.name != "table":
        issues.append({"code": "standings_table_missing", "group": group})
        return [], False

    rows = table.find_all("tr")
    if not rows:
        issues.append({"code": "standings_table_empty", "group": group})
        return [], False
    header_cells = rows[0].find_all(["th", "td"], recursive=False)
    headers = [_text(cell) for cell in header_cells]
    headers_valid = tuple(headers[4:13]) == STANDING_HEADERS and len(headers) >= 13
    if not headers_valid:
        issues.append({
            "code": "standings_headers_unexpected",
            "group": group,
            "observed": headers,
        })
        return [], False

    standings: list[dict[str, object]] = []
    for row_index, row in enumerate(rows[1:], start=1):
        cells = row.find_all(["th", "td"], recursive=False)
        if not cells or all(not _text(cell) for cell in cells):
            continue
        if len(cells) < 13:
            issues.append({
                "code": "standing_row_unexpected_cell_count",
                "group": group,
                "row_index": row_index,
                "cell_count": len(cells),
            })
            continue

        team_cell = cells[3]
        team_name = _text(team_cell)
        team_season_id, team_season_url = _source_link(team_cell, page_url, _TEAM_ID_RE)
        if not team_name:
            issues.append({"code": "standing_team_name_missing", "group": group, "row_index": row_index})
            continue
        if team_season_id is None:
            issues.append({"code": "standing_team_link_missing", "group": group, "row_index": row_index, "team_name": team_name})

        position_raw = _text(cells[1])
        stats_raw = {header: _text(cells[4 + index]) for index, header in enumerate(STANDING_HEADERS)}
        stats = {STANDING_FIELDS[header]: _integer(value) for header, value in stats_raw.items()}
        for header, raw_value in stats_raw.items():
            if stats[STANDING_FIELDS[header]] is None:
                issues.append({
                    "code": "standing_stat_unexpected_value",
                    "group": group,
                    "row_index": row_index,
                    "field": STANDING_FIELDS[header],
                    "raw_value": raw_value,
                })

        standings.append({
            "group": group,
            "position": _integer(position_raw),
            "position_raw": position_raw,
            "team_name": team_name,
            "team_season_id": team_season_id,
            "team_season_url": team_season_url,
            "stats": stats,
            "stats_raw": stats_raw,
            "source_row_index": row_index,
        })
    return standings, True


def _match_link(row: Tag, page_url: str) -> tuple[str | None, str | None]:
    for anchor in row.select("a[href]"):
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        absolute_url = urljoin(page_url, href)
        parsed = urlsplit(absolute_url)
        if parsed.path.endswith("/p/p.php"):
            match_id = parse_qs(parsed.query).get("id", [None])[0]
            if match_id:
                return match_id, absolute_url
    return None, None


def _parse_fixtures(
    soup: BeautifulSoup,
    page_url: str,
    group: str,
    team_by_name: dict[str, list[dict[str, object]]],
    issues: list[dict[str, object]],
    captured_at_utc: str | None,
) -> list[dict[str, object]]:
    table = soup.select_one("table.taula_estil-16")
    if not isinstance(table, Tag):
        issues.append({"code": "fixtures_table_missing", "group": group})
        return []

    fixtures: list[dict[str, object]] = []
    current_round: int | None = None
    for row_index, row in enumerate(table.find_all("tr")):
        cells = row.find_all(["th", "td"], recursive=False)
        cell_texts = [_text(cell) for cell in cells]
        if len(cells) == 1:
            round_match = _ROUND_RE.fullmatch(cell_texts[0])
            if round_match:
                current_round = int(round_match.group(1))
                continue
        if tuple(cell_texts) == FIXTURE_HEADERS:
            continue
        if len(cells) != 6:
            if cell_texts:
                issues.append({
                    "code": "fixture_row_unexpected_cell_count",
                    "group": group,
                    "row_index": row_index,
                    "cell_count": len(cells),
                    "raw_cells": cell_texts,
                })
            continue

        date_raw, home_name, score_raw, away_name, stadium_name, referee_name = cell_texts
        match_id, match_url = _match_link(row, page_url)
        stadium_id, stadium_url = _source_link(cells[4], page_url, _STADIUM_ID_RE)
        referee_id, referee_url = _source_link(cells[5], page_url, _REFEREE_ID_RE)
        date_iso, date_issue = _date(date_raw)
        if date_issue:
            issues.append({"code": date_issue, "group": group, "row_index": row_index, "raw_value": date_raw})

        score_match = _MATCH_SCORE_RE.fullmatch(score_raw.strip())
        is_not_played = score_raw.strip() in {"", "—", "-"}
        result_status = "available" if score_match else "not_available" if is_not_played else "unknown"
        if result_status == "unknown":
            issues.append({"code": "result_unexpected_value", "group": group, "row_index": row_index, "raw_value": score_raw})
        if current_round is None:
            issues.append({"code": "fixture_round_missing", "group": group, "row_index": row_index, "match_id": match_id})
        if match_id is None and result_status == "available":
            issues.append({"code": "fixture_match_link_missing", "group": group, "row_index": row_index})

        home_refs = team_by_name.get(home_name, [])
        away_refs = team_by_name.get(away_name, [])
        if len(home_refs) != 1:
            issues.append({"code": "home_team_reference_unresolved", "group": group, "row_index": row_index, "team_name": home_name})
        if len(away_refs) != 1:
            issues.append({"code": "away_team_reference_unresolved", "group": group, "row_index": row_index, "team_name": away_name})
        home_ref = home_refs[0] if len(home_refs) == 1 else {}
        away_ref = away_refs[0] if len(away_refs) == 1 else {}

        fixture = {
            "group": group,
            "season": "2026/27",
            "round": current_round,
            "date": date_iso,
            "date_raw": date_raw,
            "home_team_name": home_name,
            "home_team_season_id": home_ref.get("team_season_id"),
            "home_team_season_url": home_ref.get("team_season_url"),
            "home_team_reference_method": "exact_standings_name" if home_ref else None,
            "away_team_name": away_name,
            "away_team_season_id": away_ref.get("team_season_id"),
            "away_team_season_url": away_ref.get("team_season_url"),
            "away_team_reference_method": "exact_standings_name" if away_ref else None,
            "result_status": result_status,
            "result_raw": score_raw,
            "home_goals": int(score_match.group(1)) if score_match else None,
            "away_goals": int(score_match.group(2)) if score_match else None,
            "match_link_status": "present" if match_url else "not_published_by_source",
            "match_id": match_id,
            "match_url": match_url,
            "stadium_name": stadium_name or None,
            "stadium_id": stadium_id,
            "stadium_url": stadium_url,
            "referee_name": referee_name or None,
            "referee_id": referee_id,
            "referee_url": referee_url,
            "source_row_index": row_index,
        }
        match_status = assess_match_status(fixture, captured_at_utc=captured_at_utc)
        fixture["fixture_status"] = match_status["state"]
        fixture["match_state"] = match_status["state"]
        fixture["match_state_issues"] = match_status["issues"]
        fixture["match_state_evidence"] = match_status["evidence"]
        fixtures.append(fixture)
    return fixtures


def parse_competition_html(
    html: str,
    source_url: str,
    *,
    captured_at_utc: str | None = None,
) -> dict[str, object]:
    """Parse una clasificación y su tabla completa de calendario desde un HTML."""
    soup = BeautifulSoup(html, "lxml")
    title = _text(soup.title) if soup.title else ""
    competition = _parse_competition(source_url, title)
    group = str(competition["group"])
    issues: list[dict[str, object]] = []
    if competition["group_source"] != group:
        issues.append({
            "code": "competition_group_title_mismatch",
            "expected": group,
            "observed": competition["group_source"],
        })
    if competition["season_source"] != "2026-27":
        issues.append({
            "code": "competition_season_title_mismatch",
            "expected": "2026-27",
            "observed": competition["season_source"],
        })
    standings, headers_valid = _parse_standings(soup, source_url, group, issues)

    team_by_name: dict[str, list[dict[str, object]]] = {}
    for team in standings:
        team_by_name.setdefault(str(team["team_name"]), []).append(team)
    fixtures = _parse_fixtures(
        soup, source_url, group, team_by_name, issues, captured_at_utc,
    )
    return {
        "competition": competition,
        "standings": standings,
        "participants": [
            {
                "group": group,
                "team_name": team["team_name"],
                "team_season_id": team["team_season_id"],
                "team_season_url": team["team_season_url"],
                "standing_position": team["position"],
            }
            for team in standings
        ],
        "matches": fixtures,
        "diagnostics": {
            "standings_headers_valid": headers_valid,
            "issues": issues,
        },
    }
