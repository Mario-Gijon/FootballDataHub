from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import json
import re
from typing import Any, Iterable
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

_SEASON_RE = re.compile(r"^\d{4}-\d{2}$")
_DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
_HEIGHT_RE = re.compile(r"\b(\d{2,3})\s*cm\b", re.I)
_AGE_RE = re.compile(r"\((\d{1,3})\s*años?\)", re.I)
_SCORE_RE = re.compile(r"^\s*(\d+)\s+(\d+)\s*$")
_POSITIONS = ("Portero", "Defensa", "Centrocampista", "Delantero")


@dataclass(frozen=True, slots=True)
class PlayerIdentity:
    provider: str
    provider_id: int
    display_name: str | None
    full_name: str | None
    birth_date: str | None
    age_displayed: int | None
    birth_place: str | None
    birth_region: str | None
    position: str | None
    height_cm: int | None
    source_url: str


@dataclass(frozen=True, slots=True)
class PlayerSeasonRecord:
    season: str
    team_name: str | None
    team_provider_id: int | None
    country: str | None
    division: str | None
    age: int | None
    appearances: int | None
    starts: int | None
    complete_matches: int | None
    substitute_appearances: int | None
    substituted: int | None
    incomplete_matches: int | None
    callups_without_playing: int | None
    total_callups: int | None
    wins: int | None
    draws: int | None
    losses: int | None
    minutes: int | None
    yellow_cards: int | None
    red_cards: int | None
    goals: int | None
    penalty_goals: int | None
    own_goals: int | None
    goals_conceded: int | None
    squad_number: int | None
    provenance: str
    source_url: str
    provider_season_id: int | None = None
    provider_player_alias_id: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PlayerAggregateMetric:
    metric: str
    values: tuple[str | None, ...]
    raw_links: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class PlayerAggregateMatrix:
    scope: str
    headers: tuple[str, ...]
    header_titles: tuple[str | None, ...]
    rows: tuple[PlayerAggregateMetric, ...]
    provenance: str
    source_url: str


@dataclass(frozen=True, slots=True)
class PlayerMatchAppearance:
    # Canonical BDFutbol matches (/es/p/p.php?id=...) have a true numeric
    # provider match id. Community/manager matches use /es/p/partido.html
    # where ``id`` is the provider season id, not a match id, so this field
    # must remain nullable.
    match_provider_id: int | None
    match_provider_key: str
    provider_season_id: int | None
    match_url: str
    date: str | None
    season: str | None
    competition: str | None
    round_or_type: str | None
    home_team: str | None
    score_text: str | None
    home_goals: int | None
    away_goals: int | None
    away_team: str | None
    started_raw: str | None
    complete_raw: str | None
    substitute_raw: str | None
    substituted_raw: str | None
    incomplete_raw: str | None
    unused_callup_raw: str | None
    minutes: int | None
    # These cells can contain event minutes such as ``'54`` rather than
    # counts. Preserve the provider value verbatim instead of fabricating
    # numeric card/goal totals.
    yellow_cards_raw: str | None
    red_cards_raw: str | None
    goals_raw: str | None
    goals_conceded: int | None
    provenance: str
    source_url: str
    raw_cells: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PlayerSnapshot:
    identity: PlayerIdentity
    canonical_career: tuple[PlayerSeasonRecord, ...]
    manager_career: tuple[PlayerSeasonRecord, ...]
    competition_stats: PlayerAggregateMatrix | None
    team_stats: PlayerAggregateMatrix | None
    match_appearances: tuple[PlayerMatchAppearance, ...]
    source_run: str | None = None
    warnings: tuple[str, ...] = ()


def _norm(value: str | None) -> str:
    return " ".join((value or "").split())


def _int_or_none(value: str | None) -> int | None:
    text = _norm(value)
    if not text or text in {"-", "—", "–"}:
        return None
    match = re.search(r"-?\d+", text.replace(".", ""))
    return int(match.group(0)) if match else None


def _first_int_attr(tag: Tag, *keys: str) -> int | None:
    for key in keys:
        parsed = _int_or_none(str(tag.get(key) or ""))
        if parsed not in (None, 0):
            return parsed
    return None


def _cell_text(cell: Tag) -> str:
    text = _norm(cell.get_text(" ", strip=True))
    if text:
        return text
    for node in cell.find_all(["img", "abbr"]):
        if not isinstance(node, Tag):
            continue
        for attr in ("title", "alt", "aria-label"):
            candidate = _norm(node.get(attr))
            if candidate:
                return candidate
    return ""


def _table_rows(table: Tag) -> tuple[list[str], list[list[Tag]]]:
    headers: list[str] = []
    rows: list[list[Tag]] = []
    for tr in table.find_all("tr"):
        if not isinstance(tr, Tag):
            continue
        cells = tr.find_all(["th", "td"], recursive=False) or tr.find_all(["th", "td"])
        cells = [c for c in cells if isinstance(c, Tag)]
        if not cells:
            continue
        if not headers and any(c.name == "th" for c in cells):
            headers = [_cell_text(c) for c in cells]
            continue
        rows.append(cells)
    return headers, rows


def _identity_candidates(soup: BeautifulSoup, label: str) -> list[str]:
    result: list[str] = []
    pattern = re.compile(rf"^\s*{re.escape(label)}\s*:?\s*$", re.I)
    for text_node in soup.find_all(string=pattern):
        parent = text_node.parent
        if not isinstance(parent, Tag):
            continue
        candidates = [parent]
        current = parent
        for _ in range(3):
            current = current.parent
            if isinstance(current, Tag):
                candidates.append(current)
            else:
                break
        for container in candidates:
            context = _norm(container.get_text(" ", strip=True))
            remainder = re.sub(rf"^\s*{re.escape(label)}\s*:?\s*", "", context, count=1, flags=re.I)
            remainder = _norm(remainder)
            if remainder and remainder not in result:
                result.append(remainder)
    return result


def _pick_identity_value(
    soup: BeautifulSoup,
    label: str,
    *,
    regex: re.Pattern[str] | None = None,
    allowed: Iterable[str] | None = None,
    max_len: int = 160,
) -> str | None:
    allowed_values = tuple(allowed or ())
    for candidate in _identity_candidates(soup, label):
        if len(candidate) > max_len:
            continue
        if regex:
            match = regex.search(candidate)
            if match:
                return match.group(0)
        elif allowed_values:
            hits = [v for v in allowed_values if v.casefold() in candidate.casefold()]
            if len(hits) == 1:
                return hits[0]
        else:
            return candidate
    return None


def _parse_birth_place(value: str | None) -> tuple[str | None, str | None]:
    value = _norm(value)
    if not value:
        return None, None
    match = re.match(r"^(.*?)\s*\(\s*(.*?)\s*\)\s*$", value)
    if not match:
        return value, None
    return _norm(match.group(1)) or None, _norm(match.group(2)) or None


def parse_player_identity(html: str, *, player_id: int, source_url: str) -> PlayerIdentity:
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    display_name = _norm(h1.get_text(" ", strip=True)) if isinstance(h1, Tag) else None
    display_name = display_name or None

    full_name = _pick_identity_value(soup, "Nombre completo", max_len=100)
    if not full_name and soup.title:
        title = _norm(soup.title.get_text(" ", strip=True))
        match = re.match(r"^[^,]+,\s*(.*?)\s+-\s+Futbolista\b", title)
        if match:
            full_name = _norm(match.group(1)) or None

    birth_context = next((c for c in _identity_candidates(soup, "Fecha de nacimiento") if _DATE_RE.search(c)), None)
    birth_date = None
    age_displayed = None
    if birth_context:
        match = _DATE_RE.search(birth_context)
        birth_date = match.group(1) if match else None
        age_match = _AGE_RE.search(birth_context)
        age_displayed = int(age_match.group(1)) if age_match else None

    birth_place, birth_region = _parse_birth_place(
        _pick_identity_value(soup, "Lugar de nacimiento", max_len=120)
    )
    position = _pick_identity_value(soup, "Demarcación", allowed=_POSITIONS, max_len=80)
    height_raw = _pick_identity_value(soup, "Altura", regex=_HEIGHT_RE, max_len=80)
    height_cm = int(_HEIGHT_RE.search(height_raw).group(1)) if height_raw and _HEIGHT_RE.search(height_raw) else None

    return PlayerIdentity(
        provider="bdfutbol",
        provider_id=player_id,
        display_name=display_name,
        full_name=full_name,
        birth_date=birth_date,
        age_displayed=age_displayed,
        birth_place=birth_place,
        birth_region=birth_region,
        position=position,
        height_cm=height_cm,
        source_url=source_url,
    )


def _find_career_table(soup: BeautifulSoup) -> Tag | None:
    for table in soup.find_all("table"):
        if not isinstance(table, Tag):
            continue
        classes = table.get("class") or []
        if isinstance(classes, str):
            classes = classes.split()
        if "traject" in classes:
            return table
    return None


def parse_player_career(html: str, *, provenance: str, source_url: str) -> tuple[PlayerSeasonRecord, ...]:
    soup = BeautifulSoup(html, "lxml")
    table = _find_career_table(soup)
    if table is None:
        return ()
    headers, rows = _table_rows(table)
    records: list[PlayerSeasonRecord] = []
    for cells in rows:
        values = [_cell_text(c) for c in cells]
        if not values or not _SEASON_RE.fullmatch(values[0]):
            continue
        def v(i: int) -> str | None:
            return values[i] if i < len(values) else None
        first = cells[0]
        team_cell = cells[1] if len(cells) > 1 else first
        team_id = _first_int_attr(team_cell, "data-codi") or _first_int_attr(first, "data-idclub")
        records.append(PlayerSeasonRecord(
            season=values[0], team_name=_norm(v(1)) or None, team_provider_id=team_id,
            country=_norm(v(2)) or None, division=_norm(v(4)) or None, age=_int_or_none(v(5)),
            appearances=_int_or_none(v(6)), starts=_int_or_none(v(7)), complete_matches=_int_or_none(v(8)),
            substitute_appearances=_int_or_none(v(9)), substituted=_int_or_none(v(10)),
            incomplete_matches=_int_or_none(v(11)), callups_without_playing=_int_or_none(v(12)),
            total_callups=_int_or_none(v(13)), wins=_int_or_none(v(14)), draws=_int_or_none(v(15)),
            losses=_int_or_none(v(16)), minutes=_int_or_none(v(17)), yellow_cards=_int_or_none(v(18)),
            red_cards=_int_or_none(v(19)), goals=_int_or_none(v(20)), penalty_goals=_int_or_none(v(21)),
            own_goals=_int_or_none(v(22)), goals_conceded=_int_or_none(v(23)), squad_number=_int_or_none(v(24)),
            provenance=provenance, source_url=source_url,
            provider_season_id=_first_int_attr(first, "data-temporadaid"),
            provider_player_alias_id=_first_int_attr(first, "data-idjug"),
            raw={"headers": headers, "values": values,
                 "first_cell_data": {k: val for k, val in first.attrs.items() if isinstance(k, str) and k.startswith("data-")}},
        ))
    return tuple(records)


def parse_aggregate_matrix(
    html: str, *, table_id: str, scope: str, provenance: str, source_url: str
) -> PlayerAggregateMatrix | None:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id=table_id)
    if not isinstance(table, Tag):
        return None
    headers, rows = _table_rows(table)
    if not headers:
        return None
    header_titles: list[str | None] = []
    first_row = table.find("tr")
    if isinstance(first_row, Tag):
        for cell in first_row.find_all(["th", "td"], recursive=False):
            header_titles.append(_norm(cell.get("title")) or None)
    while len(header_titles) < len(headers):
        header_titles.append(None)
    parsed_rows: list[PlayerAggregateMetric] = []
    for cells in rows:
        values = [_cell_text(c) for c in cells]
        if not values or not _norm(values[0]):
            continue
        links: list[tuple[str, ...]] = []
        for cell in cells[1:]:
            hrefs = tuple(urljoin(source_url, a.get("href")) for a in cell.find_all("a", href=True) if isinstance(a.get("href"), str))
            links.append(hrefs)
        parsed_rows.append(PlayerAggregateMetric(
            metric=_norm(values[0]),
            values=tuple(_norm(x) or None for x in values[1:]),
            raw_links=tuple(links),
        ))
    return PlayerAggregateMatrix(
        scope=scope, headers=tuple(headers), header_titles=tuple(header_titles[:len(headers)]),
        rows=tuple(parsed_rows), provenance=provenance, source_url=source_url,
    )


def _match_identity_from_cells(
    cells: list[Tag],
    *,
    source_url: str,
    provenance: str,
) -> tuple[int | None, str, int | None, str] | None:
    """Return a stable provider-native locator for one ``tpartits`` row.

    Canonical BDFutbol rows link to ``/es/p/p.php?id=<match_id>`` and expose
    a genuine numeric match id.

    Manager/community rows link to ``/es/p/partido.html``. There, ``id`` is
    the season id (e.g. 5742), while the match is identified by the provider's
    composite locator: season id + home team + away team + date. We preserve
    that distinction instead of pretending the season id is a match id.
    """
    base_url = source_url or "https://www.bdfutbol.com/es/p/"

    for cell in cells:
        for anchor in cell.find_all("a", href=True):
            href = anchor.get("href")
            if not isinstance(href, str):
                continue

            absolute = urljoin(base_url, href)
            parsed = urlsplit(absolute)
            query = parse_qs(parsed.query)

            if parsed.path == "/es/p/p.php":
                ids = query.get("id") or []
                if not ids or not str(ids[0]).isdigit():
                    continue
                match_id = int(ids[0])
                return (
                    match_id,
                    f"bdfutbol:match:{match_id}",
                    None,
                    absolute,
                )

            if parsed.path == "/es/p/partido.html":
                season_ids = query.get("id") or []
                homes = query.get("l") or []
                aways = query.get("v") or []
                dates = query.get("d") or []
                if (
                    not season_ids
                    or not str(season_ids[0]).isdigit()
                    or not homes
                    or not aways
                    or not dates
                ):
                    continue

                provider_season_id = int(season_ids[0])
                normalized_query = urlencode(
                    sorted(
                        parse_qsl(
                            parsed.query,
                            keep_blank_values=True,
                        )
                    )
                )
                key = (
                    "bdfutbol_manager:"
                    f"{parsed.path}?{normalized_query}"
                )
                normalized_url = (
                    f"{parsed.scheme}://{parsed.netloc}"
                    f"{parsed.path}?{normalized_query}"
                )
                return (
                    None,
                    key,
                    provider_season_id,
                    normalized_url,
                )

    return None


def parse_player_match_appearances(html: str, *, provenance: str, source_url: str) -> tuple[PlayerMatchAppearance, ...]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="tpartits")
    if not isinstance(table, Tag):
        return ()
    headers, rows = _table_rows(table)
    result: list[PlayerMatchAppearance] = []
    for cells in rows:
        identity = _match_identity_from_cells(
            cells,
            source_url=source_url,
            provenance=provenance,
        )
        if identity is None:
            continue
        (
            match_id,
            match_provider_key,
            provider_season_id,
            match_url,
        ) = identity
        values = [_cell_text(c) for c in cells]
        def v(i: int) -> str | None:
            return _norm(values[i]) or None if i < len(values) else None
        score = v(6)
        home_goals = away_goals = None
        if score and (m := _SCORE_RE.fullmatch(score)):
            home_goals, away_goals = int(m.group(1)), int(m.group(2))
        raw_cells: dict[str, str] = {}
        for i, cell in enumerate(cells):
            key = headers[i] if i < len(headers) and headers[i] else f"col_{i}"
            raw_cells[key] = str(cell)
        result.append(PlayerMatchAppearance(
            match_provider_id=match_id,
            match_provider_key=match_provider_key,
            provider_season_id=provider_season_id,
            match_url=match_url,
            date=v(1),
            season=v(2),
            competition=v(3),
            round_or_type=v(4),
            home_team=v(5),
            score_text=score,
            home_goals=home_goals,
            away_goals=away_goals,
            away_team=v(7),
            started_raw=v(8),
            complete_raw=v(9),
            substitute_raw=v(10),
            substituted_raw=v(11),
            incomplete_raw=v(12),
            unused_callup_raw=v(13),
            minutes=_int_or_none(v(14)),
            yellow_cards_raw=v(15),
            red_cards_raw=v(16),
            goals_raw=v(17),
            goals_conceded=_int_or_none(v(18)),
            provenance=provenance,
            source_url=source_url,
            raw_cells=raw_cells,
        ))
    return tuple(result)


def _latest_attempt(resource_dir: Path) -> Path | None:
    attempts = sorted(p for p in resource_dir.glob("attempt_*") if p.is_dir())
    if not attempts:
        return None
    valid: list[Path] = []
    for attempt in attempts:
        try:
            metadata = json.loads((attempt / "metadata.json").read_text(encoding="utf-8"))
        except Exception:
            metadata = {}
        if metadata.get("status") == "VALID":
            valid.append(attempt)
    return valid[-1] if valid else attempts[-1]


def _load_resource(run_dir: Path, name: str) -> tuple[str, dict[str, Any]] | None:
    resource_dir = run_dir / name
    attempt = _latest_attempt(resource_dir) if resource_dir.is_dir() else None
    if attempt is None:
        return None
    try:
        html = (attempt / "page.html").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    try:
        metadata = json.loads((attempt / "metadata.json").read_text(encoding="utf-8"))
    except Exception:
        metadata = {}
    return html, metadata


def parse_player_full_run(run_dir: str | Path, *, player_id: int) -> PlayerSnapshot:
    run_dir = Path(run_dir)
    loaded = _load_resource(run_dir, "player_profile")
    if loaded is None:
        raise FileNotFoundError(run_dir / "player_profile")
    profile_html, profile_meta = loaded
    profile_url = str(profile_meta.get("final_url") or profile_meta.get("requested_url") or f"https://www.bdfutbol.com/es/j/j{player_id}.html")
    identity = parse_player_identity(profile_html, player_id=player_id, source_url=profile_url)
    canonical_career = parse_player_career(profile_html, provenance="bdfutbol", source_url=profile_url)

    manager_career: tuple[PlayerSeasonRecord, ...] = ()
    if (mgr := _load_resource(run_dir, "player_profile_manager")) is not None:
        mgr_html, mgr_meta = mgr
        mgr_url = str(mgr_meta.get("final_url") or mgr_meta.get("requested_url") or profile_url)
        manager_career = parse_player_career(mgr_html, provenance="bdfutbol_manager", source_url=mgr_url)

    competition_stats = team_stats = None
    if (stats := _load_resource(run_dir, "player_stats")) is not None:
        stats_html, stats_meta = stats
        stats_url = str(stats_meta.get("final_url") or stats_meta.get("requested_url") or f"{profile_url}?p=stats")
        competition_stats = parse_aggregate_matrix(stats_html, table_id="table-estadistiques-competicions", scope="competition", provenance="bdfutbol", source_url=stats_url)
        team_stats = parse_aggregate_matrix(stats_html, table_id="table-estadistiques-equips", scope="team", provenance="bdfutbol", source_url=stats_url)

    appearances: list[PlayerMatchAppearance] = []
    seen: set[str] = set()
    for resource_dir in sorted(p for p in run_dir.iterdir() if p.is_dir() and p.name.startswith("player_matches_season_")):
        loaded = _load_resource(run_dir, resource_dir.name)
        if loaded is None:
            continue
        html, meta = loaded
        provenance = str(meta.get("provenance") or "bdfutbol")
        source_url = str(meta.get("final_url") or meta.get("requested_url") or "")
        for appearance in parse_player_match_appearances(html, provenance=provenance, source_url=source_url):
            if appearance.match_provider_key in seen:
                continue
            seen.add(appearance.match_provider_key)
            appearances.append(appearance)
    appearances.sort(key=lambda x: (datetime.strptime(x.date, "%d/%m/%Y") if x.date and _DATE_RE.fullmatch(x.date) else datetime.min, x.match_provider_key))

    warnings: list[str] = []
    if not canonical_career:
        warnings.append("player_profile sin filas de trayectoria")
    if competition_stats is None:
        warnings.append("sin table-estadistiques-competicions")
    if team_stats is None:
        warnings.append("sin table-estadistiques-equips")
    if not appearances:
        warnings.append("sin apariciones de partido parseadas")

    return PlayerSnapshot(
        identity=identity,
        canonical_career=canonical_career,
        manager_career=manager_career,
        competition_stats=competition_stats,
        team_stats=team_stats,
        match_appearances=tuple(appearances),
        source_run=run_dir.as_posix(),
        warnings=tuple(warnings),
    )
