from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Iterable
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag


_IMAGE_ATTRS = (
    "src",
    "data-src",
    "data-original",
    "data-lazy-src",
    "data-image",
)

_ENTITY_PATTERNS = (
    ("player", re.compile(r"^/(?:es/)?j/j(?P<id>\d+)\.html$")),
    ("coach", re.compile(r"^/(?:es/)?l/l(?P<id>\d+)\.html$")),
    ("team", re.compile(r"^/(?:es/)?e/e(?P<id>\d+)\.html$")),
    ("stadium", re.compile(r"^/(?:es/)?s/(?P<id>\d+)\.html$")),
)

_ALLOWED_MEDIA_HOSTS = {
    "bdfutbol.com",
    "www.bdfutbol.com",
}

_NOISE_TOKENS = (
    "/img/hero/",
    "rectangle",
    "logo16w",
    "logo-bd",
    "logo_bd",
    "/flags/",
    "/flag/",
    "/banderas/",
    "/bandera/",
    "spinner",
    "loading",
    "cargando",
    "loader",
    "cookie",
    "social",
    "facebook",
    "twitter",
    "instagram",
    "youtube",
    "whatsapp",
    "telegram",
    "ads/",
    "/ad/",
    "banner",
    "icon-",
    "/icons/",
    "/icon/",
    "sprite",
    "marker-icon",
    "marker-shadow",
)

_NOISE_ALT_TOKENS = (
    "cargando",
    "loading",
    "facebook",
    "twitter",
    "instagram",
    "youtube",
    "whatsapp",
    "telegram",
)

_TEAM_CREST_WORDS = (
    "escudo",
    "escut",
    "crest",
)

_PHOTO_WORDS = (
    "foto",
    "photo",
    "imatge",
    "imagen",
)

# When the exact same binary/URL is observed under multiple semantic roles,
# keep the most specific/current role as the canonical one while preserving
# every observed role in roles_observed.
_ROLE_PRIORITY = {
    "current_crest": 100,
    "historical_crest": 90,
    "portrait": 80,
    "stadium_photo": 70,
    "team_photo": 60,
    "team_media": 50,
    "photo": 10,
}


@dataclass(frozen=True, slots=True)
class MediaObservation:
    source_url: str
    source_page: str
    resource: str
    section: str | None
    alt: str | None
    title: str | None
    parent_href: str | None
    entity_type: str | None
    entity_id: int | None
    role: str | None
    decision: str
    confidence: str
    reason: str
    width: int | None = None
    height: int | None = None
    source_attribute: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.replace("\xa0", " ").split())
    return cleaned or None


def _int_attr(value: object) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def _absolute_url(value: str, base_url: str) -> str | None:
    value = value.strip()
    if not value or value.startswith(("data:", "javascript:", "#")):
        return None
    result = urljoin(base_url, value)
    parsed = urlsplit(result)
    if parsed.scheme not in {"http", "https"}:
        return None
    return result


def _srcset_urls(value: str, base_url: str) -> list[str]:
    result: list[str] = []
    for chunk in value.split(","):
        candidate = chunk.strip().split(" ", 1)[0].strip()
        if not candidate:
            continue
        absolute = _absolute_url(candidate, base_url)
        if absolute and absolute not in result:
            result.append(absolute)
    return result


def _image_sources(img: Tag, base_url: str) -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []

    def add(value: object, attr: str) -> None:
        if not isinstance(value, str):
            return
        absolute = _absolute_url(value, base_url)
        if absolute and (absolute, attr) not in sources:
            sources.append((absolute, attr))

    for attr in _IMAGE_ATTRS:
        add(img.get(attr), attr)

    for attr in ("srcset", "data-srcset"):
        value = img.get(attr)
        if isinstance(value, str):
            for url in _srcset_urls(value, base_url):
                if (url, attr) not in sources:
                    sources.append((url, attr))

    picture = img.find_parent("picture")
    if isinstance(picture, Tag):
        for source in picture.find_all("source"):
            if not isinstance(source, Tag):
                continue
            for attr in ("srcset", "data-srcset"):
                value = source.get(attr)
                if isinstance(value, str):
                    for url in _srcset_urls(value, base_url):
                        item = (url, f"picture:{attr}")
                        if item not in sources:
                            sources.append(item)

    return sources


def _nearest_anchor(img: Tag, base_url: str) -> str | None:
    anchor = img.find_parent("a")
    if not isinstance(anchor, Tag):
        return None
    href = anchor.get("href")
    if not isinstance(href, str):
        return None
    return _absolute_url(href, base_url)


def _entity_from_url(url: str | None) -> tuple[str | None, int | None]:
    if not url:
        return None, None

    path = urlsplit(url).path
    for entity_type, pattern in _ENTITY_PATTERNS:
        match = pattern.fullmatch(path)
        if match:
            return entity_type, int(match.group("id"))
    return None, None


def _nearest_section(img: Tag) -> str | None:
    for previous in img.find_all_previous(re.compile(r"^h[1-6]$")):
        if isinstance(previous, Tag):
            text = _clean(previous.get_text(" ", strip=True))
            if text:
                return text
    return None


def _text_blob(*values: str | None) -> str:
    return " ".join(value for value in values if value).casefold()


def _is_noise(
    url: str,
    alt: str | None,
    title: str | None,
) -> tuple[bool, str]:
    parsed = urlsplit(url)
    host = parsed.netloc.casefold().split(":", 1)[0]
    path = parsed.path.casefold()
    text = _text_blob(alt, title)

    # We only want media supplied by BDFutbol itself. This removes OSM map
    # tiles, Leaflet markers, ad networks and any other third-party asset.
    if host not in _ALLOWED_MEDIA_HOSTS:
        return True, f"external_host:{host or '-'}"

    for token in _NOISE_TOKENS:
        if token in path:
            return True, f"noise_path:{token}"

    for token in _NOISE_ALT_TOKENS:
        if token in text:
            return True, f"noise_text:{token}"

    return False, ""


def _classify(
    *,
    url: str,
    alt: str | None,
    title: str | None,
    section: str | None,
    parent_href: str | None,
    resource: str,
    team_id: int | None,
) -> tuple[str | None, int | None, str | None, str, str, str]:
    is_noise, noise_reason = _is_noise(url, alt, title)
    if is_noise:
        return None, None, None, "reject", "high", noise_reason

    linked_type, linked_id = _entity_from_url(parent_href)
    text = _text_blob(alt, title, section)
    path = urlsplit(url).path.casefold()

    if linked_type == "player":
        return (
            "player",
            linked_id,
            "portrait",
            "accept",
            "high",
            "image_linked_to_player_profile",
        )

    if linked_type == "coach":
        return (
            "coach",
            linked_id,
            "portrait",
            "accept",
            "high",
            "image_linked_to_coach_profile",
        )

    if linked_type == "stadium":
        return (
            "stadium",
            linked_id,
            "stadium_photo",
            "accept",
            "high",
            "image_linked_to_stadium_profile",
        )

    if linked_type == "team":
        if any(word in text for word in _TEAM_CREST_WORDS):
            return (
                "team",
                linked_id,
                "current_crest",
                "accept",
                "high",
                "team_link_with_crest_semantics",
            )
        return (
            "team",
            linked_id,
            "team_media",
            "review",
            "medium",
            "image_linked_to_team_profile",
        )

    section_cf = (section or "").casefold()

    if resource == "club_profile" and team_id is not None:
        if "otros escudos" in section_cf or "altres escuts" in section_cf:
            return (
                "team",
                team_id,
                "historical_crest",
                "accept",
                "high",
                "club_profile_historical_crest_section",
            )

        if any(word in _text_blob(alt, title) for word in _TEAM_CREST_WORDS):
            return (
                "team",
                team_id,
                "current_crest",
                "accept",
                "high",
                "club_profile_crest_semantics",
            )

        # BDFutbol team crests are served from /i/eg/. Outside the historical
        # section, the team profile image is the current crest.
        if path.startswith("/i/eg/"):
            return (
                "team",
                team_id,
                "current_crest",
                "accept",
                "medium",
                "club_profile_team_crest_path",
            )

    stadium_match = re.fullmatch(r"club_stadium_(\d+)", resource)
    if stadium_match:
        stadium_id = int(stadium_match.group(1))
        # Real stadium photographs observed in BDFutbol are under /i/c/.
        # Do NOT accept every <img> on a stadium page (maps, markers, logos).
        if path.startswith("/i/c/"):
            return (
                "stadium",
                stadium_id,
                "stadium_photo",
                "accept",
                "high",
                "bdfutbol_stadium_photo_path",
            )
        return (
            None,
            None,
            None,
            "reject",
            "high",
            "stadium_profile_non_photo_asset",
        )

    # Useful unlinked fallbacks observed in BDFutbol.
    player_match = re.fullmatch(
        r"/i/(?:m|j)/(?P<id>\d+)(?:[-_.].*)?",
        path,
    )
    if player_match:
        return (
            "player",
            int(player_match.group("id")),
            "portrait",
            "accept",
            "medium",
            "player_image_path_pattern",
        )

    coach_match = re.fullmatch(
        r"/i/lm/(?P<id>\d+)(?:[-_.].*)?",
        path,
    )
    if coach_match:
        return (
            "coach",
            int(coach_match.group("id")),
            "portrait",
            "accept",
            "medium",
            "coach_image_path_pattern",
        )

    if team_id is not None and path.startswith("/i/eg/"):
        return (
            "team",
            team_id,
            "current_crest",
            "review",
            "low",
            "team_crest_path_without_profile_context",
        )

    if any(word in text for word in _PHOTO_WORDS):
        return (
            None,
            None,
            "photo",
            "review",
            "low",
            "photo_semantics_without_entity_identity",
        )

    return (
        None,
        None,
        None,
        "reject",
        "medium",
        "no_entity_media_evidence",
    )


def discover_media(
    html: str,
    *,
    page_url: str,
    resource: str,
    team_id: int | None = None,
) -> list[MediaObservation]:
    soup = BeautifulSoup(html, "lxml")
    observations: list[MediaObservation] = []

    for img in soup.find_all("img"):
        if not isinstance(img, Tag):
            continue

        alt = _clean(
            img.get("alt") if isinstance(img.get("alt"), str) else None
        )
        title = _clean(
            img.get("title") if isinstance(img.get("title"), str) else None
        )
        section = _nearest_section(img)
        parent_href = _nearest_anchor(img, page_url)
        width = _int_attr(img.get("width"))
        height = _int_attr(img.get("height"))

        for source_url, source_attribute in _image_sources(img, page_url):
            (
                entity_type,
                entity_id,
                role,
                decision,
                confidence,
                reason,
            ) = _classify(
                url=source_url,
                alt=alt,
                title=title,
                section=section,
                parent_href=parent_href,
                resource=resource,
                team_id=team_id,
            )

            observations.append(
                MediaObservation(
                    source_url=source_url,
                    source_page=page_url,
                    resource=resource,
                    section=section,
                    alt=alt,
                    title=title,
                    parent_href=parent_href,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    role=role,
                    decision=decision,
                    confidence=confidence,
                    reason=reason,
                    width=width,
                    height=height,
                    source_attribute=source_attribute,
                )
            )

    return observations


def _canonical_role(roles: set[str]) -> str | None:
    if not roles:
        return None
    return max(
        roles,
        key=lambda role: (_ROLE_PRIORITY.get(role, 0), role),
    )


def deduplicate_observations(
    observations: Iterable[MediaObservation],
) -> list[dict[str, object]]:
    # Role is deliberately NOT part of the key. The same crest/photo may appear
    # in several sections with different semantics; keep one asset candidate and
    # preserve every observed role instead of duplicating it.
    grouped: dict[
        tuple[str, str | None, int | None, str],
        dict[str, object],
    ] = {}

    for item in observations:
        key = (
            item.source_url,
            item.entity_type,
            item.entity_id,
            item.decision,
        )
        occurrence = {
            "source_page": item.source_page,
            "resource": item.resource,
            "section": item.section,
            "alt": item.alt,
            "title": item.title,
            "parent_href": item.parent_href,
            "confidence": item.confidence,
            "reason": item.reason,
            "source_attribute": item.source_attribute,
            "width": item.width,
            "height": item.height,
            "role": item.role,
        }

        existing = grouped.get(key)
        if existing is None:
            roles = {item.role} if item.role else set()
            grouped[key] = {
                "source_url": item.source_url,
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
                "role": _canonical_role(roles),
                "roles_observed": sorted(roles),
                "decision": item.decision,
                "occurrences": [occurrence],
                "_roles": roles,
            }
        else:
            roles = existing["_roles"]
            assert isinstance(roles, set)
            if item.role:
                roles.add(item.role)
            existing["role"] = _canonical_role(roles)
            existing["roles_observed"] = sorted(roles)

            occurrences = existing["occurrences"]
            assert isinstance(occurrences, list)
            if occurrence not in occurrences:
                occurrences.append(occurrence)

    result: list[dict[str, object]] = []
    for item in grouped.values():
        item.pop("_roles", None)
        result.append(item)

    def sort_key(item: dict[str, object]) -> tuple[str, int, str, str]:
        entity_type = str(item.get("entity_type") or "")
        entity_id = int(item.get("entity_id") or 0)
        role = str(item.get("role") or "")
        url = str(item.get("source_url") or "")
        return entity_type, entity_id, role, url

    return sorted(result, key=sort_key)
