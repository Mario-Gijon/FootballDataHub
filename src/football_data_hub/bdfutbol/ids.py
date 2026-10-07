from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlsplit


PROVIDER = "bdfutbol"


@dataclass(frozen=True, slots=True)
class ProviderRef:
    """Stable provider-scoped identity.

    BDFutbol numeric IDs are not globally unique across entity types, so the
    entity type is part of the identity.
    """

    entity_type: str
    provider_id: int
    provider: str = PROVIDER

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.provider, self.entity_type, self.provider_id)


_PLAYER_RE = re.compile(r"/j/j(?P<id>\d+)\.html$")
_COACH_RE = re.compile(r"/l/l(?P<id>\d+)\.html$")
_REFEREE_RE = re.compile(r"/r/r(?P<id>\d+)\.html$")
_STADIUM_RE = re.compile(r"/s/(?P<id>\d+)\.html$")


def absolute_url(href: str, base_url: str = "https://www.bdfutbol.com/") -> str:
    return urljoin(base_url, href)


def _path_id(href: str | None, pattern: re.Pattern[str]) -> int | None:
    if not href:
        return None
    path = urlsplit(absolute_url(href)).path
    match = pattern.search(path)
    return int(match.group("id")) if match else None


def player_id_from_url(href: str | None) -> int | None:
    return _path_id(href, _PLAYER_RE)


def coach_id_from_url(href: str | None) -> int | None:
    return _path_id(href, _COACH_RE)


def referee_id_from_url(href: str | None) -> int | None:
    return _path_id(href, _REFEREE_RE)


def stadium_id_from_url(href: str | None) -> int | None:
    return _path_id(href, _STADIUM_RE)


def match_id_from_url(href: str | None) -> int | None:
    if not href:
        return None
    parsed = urlsplit(absolute_url(href))
    if not parsed.path.endswith("/p/p.php"):
        return None
    values = parse_qs(parsed.query).get("id")
    if not values or not values[0].isdigit():
        return None
    return int(values[0])


def team_season_id_from_url(href: str | None, season: str) -> int | None:
    """Extract the team ID from a team-season URL.

    Example: /es/t/t2026-27178.html -> 178 for season 2026-27.
    Competition URLs such as t2026-271rf1.html do not match.
    """

    if not href:
        return None
    name = urlsplit(absolute_url(href)).path.rsplit("/", 1)[-1]
    pattern = re.compile(rf"^t{re.escape(season)}(?P<id>\d+)\.html$")
    match = pattern.fullmatch(name)
    return int(match.group("id")) if match else None
