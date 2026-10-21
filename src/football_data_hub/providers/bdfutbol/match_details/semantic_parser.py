"""Strict, offline semantic parser for saved BDFutbol match-detail DOMs.

This module reads local HTML only. It does not acquire pages, persist parse
results, or call the match-detail promotion store.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from football_data_hub.domain.matches.semantic_detail import (
    AdditionalSourceNote,
    Coach,
    MatchContext,
    MatchDetailObservation,
    MatchDetailSource,
    MatchEvent,
    MatchScore,
    MatchSide,
    PlayerAppearance,
    ProvenancedValue,
    SemanticEvidence,
    SemanticValidation,
    TeamIdentity,
    ValidationCheck,
)
from football_data_hub.providers.bdfutbol.match_details.semantic_validation import (
    goal_progression_is_consistent,
    roster_identity_errors,
)

PARSER_VERSION = "match-detail-semantic-0.3.3"
_TEAM_HREF = re.compile(r"(?:^|/)e/e(\d+)\.html$")
_COACH_HREF = re.compile(r"(?:^|/)l/l(\d+)\.html$")
_STADIUM_PATH = re.compile(r"^/es/s/([A-Za-z0-9_-]+)\.html$")
_REFEREE_HREF = re.compile(r"(?:^|/)r/r(\d+)\.html$")
_IMAGE_ID = re.compile(r"(?:^|/)i/m/(\d+)\.(?:png|webp|jpe?g)$", re.IGNORECASE)
_GOAL_SCORE = re.compile(r"^(\d+)\s*-\s*(\d+)$")
_MINUTE = re.compile(
    r"^\s*(\d+\s*(?:\+\s*\d+)?)\s*[’']?\s*(?:\(pen\)|\(pp\))?\s*$",
    re.IGNORECASE,
)
_DATE_ONLY = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")
_TIME_TOKEN = re.compile(r"(?<!\d)(\d{1,2}:\d{2})(?!\d)")


class MatchDetailParserError(ValueError):
    """The saved artifact or DOM cannot be parsed safely."""


@dataclass(frozen=True, slots=True)
class _RawRosterEvent:
    kind: str
    side: str
    team_id: int
    player_id: int
    player_name: str
    minute_literal: str | None
    icon_class: str | None
    icon_title: str | None
    raw_text: str
    source_reference: str


@dataclass(frozen=True, slots=True)
class _ArtifactSource:
    metadata: dict[str, Any]
    inventory_id: str
    manifest: dict[str, Any]
    html: bytes
    sha256: str


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _text(node: Tag | None) -> str:
    return " ".join(node.stripped_strings) if node is not None else ""


def _parse_date_and_kickoff(raw: str) -> tuple[str | None, str | None, str, str | None]:
    """Parse the observed match date independently from its optional local time."""

    dates = list(_DATE_ONLY.finditer(raw))
    if len(dates) != 1:
        return None, None, "unresolved", "date_missing_or_ambiguous"
    match = dates[0]
    day, month, year = (int(value) for value in match.groups())
    try:
        parsed_date = date(year, month, day).isoformat()
    except ValueError:
        return None, None, "unresolved", "date_format_unrecognized"

    suffix = raw[match.end():]
    parenthetical = re.findall(r"\(([^()]*)\)", suffix)
    tokens = list(_TIME_TOKEN.finditer(suffix))
    if not parenthetical and not tokens:
        return parsed_date, None, "explicitly_absent", None
    if len(parenthetical) != 1 or len(tokens) != 1:
        return parsed_date, None, "unresolved", "kickoff_time_ambiguous"
    token = parenthetical[0].strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", token):
        return parsed_date, None, "unresolved", "kickoff_time_format_unrecognized"
    hour, minute = (int(value) for value in token.split(":"))
    if hour > 23 or minute > 59:
        return parsed_date, None, "unresolved", "kickoff_time_out_of_range"
    return parsed_date, f"{hour:02d}:{minute:02d}", "observed", None


def _classes(node: Tag) -> list[str]:
    value = node.get("class", [])
    if isinstance(value, str):
        return value.split()
    return [str(item) for item in value]


def _reference(selector: str, detail: str | None = None) -> str:
    return f"css:{selector}" + (f"; {detail}" if detail else "")


class _EvidenceBuilder:
    def __init__(self, digest: str, parser_version: str) -> None:
        self.digest = digest
        self.parser_version = parser_version
        self.items: list[SemanticEvidence] = []

    def add(
        self,
        field_path: str,
        state: str,
        selector: str,
        raw_value: str | None,
        normalized_value: str | int | None,
    ) -> None:
        self.items.append(
            SemanticEvidence(
                field_path=field_path,
                state=state,  # type: ignore[arg-type]
                source_reference=selector,
                raw_value=raw_value,
                normalized_value=normalized_value,
                source_html_sha256=self.digest,
                parser_version=self.parser_version,
            )
        )


def _provenanced(
    value: str | int | None,
    *,
    state: str,
    origin: str,
    raw: str | None = None,
    reference: str | None = None,
) -> ProvenancedValue:
    return ProvenancedValue(
        value=value,
        state=state,  # type: ignore[arg-type]
        origin=origin,  # type: ignore[arg-type]
        raw_value=raw,
        source_reference=reference,
    )


def _expected_identity(expected: Mapping[str, Any]) -> tuple[str, str]:
    source_id = str(expected.get("source_match_id") or "")
    source_url = expected.get("source_match_url")
    if not source_id.isdigit() or not isinstance(source_url, str) or not source_url:
        raise MatchDetailParserError("El registro de catálogo no contiene URL/ID válido")
    parsed = urlsplit(source_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.bdfutbol.com"
        or parsed.path != "/es/p/p.php"
        or query.get("id") != [source_id]
        or set(query) != {"id"}
        or parsed.fragment
    ):
        raise MatchDetailParserError("La URL del catálogo no corresponde al ID de partido")
    if not isinstance(expected.get("internal_id"), str) or not expected["internal_id"]:
        raise MatchDetailParserError("El catálogo no contiene internal_id")
    if not re.fullmatch(r"\d{4}-\d{2}", str(expected.get("season") or "")):
        raise MatchDetailParserError("La temporada del catálogo no es YYYY-YY")
    if expected.get("competition") != "Primera Federación":
        raise MatchDetailParserError("La competición del catálogo no es Primera Federación")
    if expected.get("group") not in {"I", "II"}:
        raise MatchDetailParserError("El grupo del catálogo no es I o II")
    matchday = expected.get("matchday")
    if not isinstance(matchday, int) or isinstance(matchday, bool) or not 1 <= matchday <= 38:
        raise MatchDetailParserError("La jornada del catálogo no es válida")
    team_ids = (expected.get("home_team_id"), expected.get("away_team_id"))
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in team_ids):
        raise MatchDetailParserError("Los IDs de equipo del catálogo deben ser enteros positivos")
    if team_ids[0] == team_ids[1]:
        raise MatchDetailParserError("El catálogo asigna el mismo ID a ambos equipos")
    try:
        date.fromisoformat(str(expected.get("source_match_date")))
    except ValueError as exc:
        raise MatchDetailParserError("La fecha del catálogo no es ISO válida") from exc
    score = expected.get("reference_result")
    if not isinstance(score, Mapping) or any(
        not isinstance(score.get(key), int)
        or isinstance(score.get(key), bool)
        or score[key] < 0
        for key in ("home_goals", "away_goals")
    ):
        raise MatchDetailParserError("El resultado del catálogo está ausente o no es válido")
    if any(
        not isinstance(expected.get(key), str) or not expected[key]
        for key in ("source_generation_id", "source_capture_id")
    ):
        raise MatchDetailParserError("Falta la procedencia de generación/captura del catálogo")
    return source_id, source_url


def _verify_artifact(artifact_dir: Path, expected: Mapping[str, Any]) -> _ArtifactSource:
    candidate = artifact_dir.expanduser().absolute()
    if candidate.is_symlink() or not candidate.is_dir():
        raise MatchDetailParserError("El artefacto debe ser un directorio regular, sin symlink")
    root = candidate.resolve(strict=True)
    fixed_files = {
        "discovery.json": root / "discovery.json",
        "metadata.json": root / "metadata.json",
        "raw/source.html": root / "raw" / "source.html",
    }
    for path in fixed_files.values():
        if path.is_symlink() or not path.is_file():
            raise MatchDetailParserError(f"Archivo de artefacto ausente/no regular: {path.name}")
        try:
            path.resolve(strict=True).relative_to(root)
        except ValueError as exc:
            raise MatchDetailParserError("Ruta de artefacto fuera de su directorio") from exc
    manifest_path = root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise MatchDetailParserError("manifest.json ausente/no regular")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        metadata = json.loads(fixed_files["metadata.json"].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatchDetailParserError("No se puede leer el manifiesto o metadata") from exc
    if not isinstance(manifest, dict) or not isinstance(metadata, dict):
        raise MatchDetailParserError("El manifiesto y metadata deben ser objetos JSON")
    if (
        manifest.get("schema_version") != "football_data_hub.match_detail_discovery_manifest.v1"
        or manifest.get("artifact_type") != "discovery_only_unverified"
        or metadata.get("schema_version") != "football_data_hub.match_detail_discovery_artifact.v1"
        or metadata.get("artifact_type") != "discovery_only_unverified"
        or metadata.get("promotion_eligible") is not False
    ):
        raise MatchDetailParserError("El tipo/versión del artefacto no es discovery-only")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise MatchDetailParserError("El manifiesto no tiene el mapa de archivos")
    expected_files = {
        "discovery.json": fixed_files["discovery.json"],
        "metadata.json": fixed_files["metadata.json"],
        "raw/source.html": fixed_files["raw/source.html"],
    }
    file_bytes: dict[str, bytes] = {}
    for key, path in expected_files.items():
        spec = files.get(key)
        if not isinstance(spec, dict):
            raise MatchDetailParserError(f"El manifiesto no referencia {key}")
        raw = path.read_bytes()
        if (
            spec.get("sha256") != _sha256(raw)
            or spec.get("bytes") != len(raw)
        ):
            raise MatchDetailParserError(f"Hash/tamaño no coincide para {key}")
        file_bytes[key] = raw
    html = file_bytes["raw/source.html"]
    digest = _sha256(html)
    if (
        metadata.get("source_html_sha256") != digest
        or metadata.get("source_html_bytes") != len(html)
        or metadata.get("discovery_sha256") != _sha256(file_bytes["discovery.json"])
        or metadata.get("discovery_id") != manifest.get("discovery_id")
        or manifest.get("discovery_id") != root.name
        or metadata.get("inventory_id") != manifest.get("inventory_id")
    ):
        raise MatchDetailParserError("Metadata no coincide con el manifiesto/HTML")
    source_id, source_url = _expected_identity(expected)
    expected_meta = {
        "source_match_id": source_id,
        "requested_url": source_url,
        "final_url": source_url,
        "season": expected.get("season"),
        "competition": expected.get("competition"),
        "group": expected.get("group"),
        "matchday": expected.get("matchday"),
        "source_generation_id": expected.get("source_generation_id"),
        "source_capture_id": expected.get("source_capture_id"),
    }
    for key, value in expected_meta.items():
        if metadata.get(key) != value:
            raise MatchDetailParserError(f"Metadata/catalog mismatch: {key}")
    return _ArtifactSource(
        metadata=metadata,
        inventory_id=str(manifest["inventory_id"]),
        manifest=manifest,
        html=html,
        sha256=digest,
    )


def _profile_id(href: str, pattern: re.Pattern[str], label: str) -> int:
    match = pattern.search(href)
    if match is None:
        raise MatchDetailParserError(f"Enlace de {label} no reconocido: {href!r}")
    return int(match.group(1))


def _stadium_id(href: str, base_url: str) -> str:
    """Preserve BDFutbol's opaque stadium slug (which is not always numeric)."""

    resolved = urlsplit(urljoin(base_url, href))
    try:
        port = resolved.port
    except ValueError as exc:
        raise MatchDetailParserError(
            f"Enlace de estadio contiene un puerto no válido: {href!r}"
        ) from exc
    match = _STADIUM_PATH.fullmatch(resolved.path)
    if (
        resolved.scheme != "https"
        or resolved.hostname != "www.bdfutbol.com"
        or resolved.username is not None
        or resolved.password is not None
        or port not in {None, 443}
        or resolved.query
        or resolved.fragment
        or match is None
    ):
        raise MatchDetailParserError(f"Enlace de estadio no reconocido: {href!r}")
    return match.group(1)


def _minute(value: str) -> tuple[str | None, int | None, int | None]:
    # Match the complete event text. A number embedded in an unexpected label
    # must not be mistaken for a minute (for example, "Evento 17").
    match = _MINUTE.fullmatch(value)
    if match is None:
        return None, None, None
    literal = re.sub(r"\s+", "", match.group(1))
    parts = literal.split("+", 1)
    return literal, int(parts[0]), int(parts[1]) if len(parts) == 2 else None


def _player_profile_id(href: str, base_url: str, label: str) -> int:
    """Accept player IDs only from the expected BDFutbol profile URL shape."""

    resolved = urlsplit(urljoin(base_url, href))
    try:
        port = resolved.port
    except ValueError as exc:
        raise MatchDetailParserError(
            f"Enlace de {label} contiene un puerto no válido: {href!r}"
        ) from exc
    match = re.fullmatch(r"/es/j/j(\d+)\.html", resolved.path)
    if (
        resolved.scheme != "https"
        or resolved.hostname != "www.bdfutbol.com"
        or resolved.username is not None
        or resolved.password is not None
        or port not in {None, 443}
        or resolved.query
        or resolved.fragment
        or match is None
    ):
        raise MatchDetailParserError(
            f"Enlace de {label} no es un perfil BDFutbol válido: {href!r}"
        )
    return int(match.group(1))


def _single_unique(values: list[str], label: str) -> str:
    unique = list(dict.fromkeys(value for value in values if value))
    if len(unique) != 1:
        raise MatchDetailParserError(f"Se esperaba un valor único para {label}; encontrados {unique}")
    return unique[0]


def _field_value(hero: Tag, label: str, expected_values: list[str] | None = None) -> tuple[str, str, Tag]:
    matches: list[tuple[str, str, Tag]] = []
    for label_node in hero.select(".f14"):
        if _text(label_node).casefold() != label.casefold():
            continue
        wrapper = label_node.parent
        if not isinstance(wrapper, Tag):
            continue
        value_node = wrapper.find("div", class_="f13")
        if not isinstance(value_node, Tag):
            raise MatchDetailParserError(f"Campo {label} sin valor f13")
        raw = _text(value_node)
        anchor = value_node.find("a", href=True)
        href = str(anchor.get("href")) if isinstance(anchor, Tag) else ""
        matches.append((raw, href, value_node))
    if not matches:
        raise MatchDetailParserError(f"Campo obligatorio ausente en el DOM: {label}")
    unique = list(dict.fromkeys((raw, href) for raw, href, _ in matches))
    if len(unique) != 1:
        raise MatchDetailParserError(f"Campo duplicado discordante: {label}")
    raw, href = unique[0]
    if expected_values and raw not in expected_values:
        raise MatchDetailParserError(f"Valor inesperado para {label}: {raw!r}")
    return raw, href, matches[0][2]


def _team_identities(
    hero: Tag, base_url: str, expected: Mapping[str, Any], evidence: _EvidenceBuilder
) -> tuple[TeamIdentity, TeamIdentity]:
    header = hero.select_one("h1 .d-none.d-md-block .row.mt-3.mb-2")
    if not isinstance(header, Tag):
        raise MatchDetailParserError("No se encuentra el marcador de escritorio del encuentro")
    team_anchors: list[Tag] = []
    for node in header.select(".partit-equip a[href]"):
        if isinstance(node, Tag):
            team_anchors.append(node)
    if len(team_anchors) != 2:
        raise MatchDetailParserError("El encabezado debe contener dos equipos en el bloque principal")
    score_nodes = header.select(".resultat-partit")
    if len(score_nodes) != 2:
        raise MatchDetailParserError("El encabezado no contiene exactamente dos marcadores")
    mobile_header = hero.select_one("h1 .d-block.d-md-none")
    if not isinstance(mobile_header, Tag):
        raise MatchDetailParserError("No se encuentra la copia móvil del encabezado")
    mobile_anchors = mobile_header.select(".partit-equip a[href]")
    if len(mobile_anchors) != 2:
        raise MatchDetailParserError("La copia móvil no contiene exactamente dos equipos")
    desktop_pairs = [(str(node.get("href")), _text(node)) for node in team_anchors]
    mobile_pairs = [(str(node.get("href")), _text(node)) for node in mobile_anchors]
    if mobile_pairs != desktop_pairs:
        raise MatchDetailParserError("La identidad de equipos de la copia móvil discrepa")
    scores: list[int] = []
    for node in score_nodes:
        raw = _text(node)
        if not raw.isdigit():
            raise MatchDetailParserError(f"Marcador no numérico: {raw!r}")
        scores.append(int(raw))

    result: list[TeamIdentity] = []
    for side, anchor, expected_key in (
        ("home", team_anchors[0], "home_team_id"),
        ("away", team_anchors[1], "away_team_id"),
    ):
        href = str(anchor.get("href", ""))
        team_id = _profile_id(href, _TEAM_HREF, "equipo")
        if team_id != expected.get(expected_key):
            raise MatchDetailParserError(f"El ID del equipo {side} no coincide con el catálogo")
        name = _text(anchor)
        if not name:
            raise MatchDetailParserError(f"Equipo {side} sin nombre visible")
        parent = anchor.find_parent("span", class_="partit-equip")
        crest = parent.find("img", src=True) if isinstance(parent, Tag) else None
        crest_url = urljoin(base_url, str(crest.get("src"))) if isinstance(crest, Tag) else None
        result.append(
            TeamIdentity(
                side=side,  # type: ignore[arg-type]
                team_id=team_id,
                name=name,
                team_url=urljoin(base_url, href),
                crest_url=crest_url,
            )
        )
        evidence.add(
            f"{side}_team.team_id",
            "observed",
            _reference("div.hero.hero-partit h1 .partit-equip a[href]", f"href={href}"),
            href,
            team_id,
        )
        evidence.add(
            f"{side}_team.name",
            "observed",
            _reference("div.hero.hero-partit h1 .partit-equip a[href]", f"team_id={team_id}"),
            name,
            name,
        )
    if result[0].team_id == result[1].team_id:
        raise MatchDetailParserError("El DOM repite el mismo equipo en ambos lados")
    evidence.add(
        "score.home_goals",
        "observed",
        _reference("div.hero.hero-partit h1 .d-none.d-md-block .resultat-partit", "first score cell"),
        str(scores[0]),
        scores[0],
    )
    evidence.add(
        "score.away_goals",
        "observed",
        _reference("div.hero.hero-partit h1 .d-none.d-md-block .resultat-partit", "second score cell"),
        str(scores[1]),
        scores[1],
    )
    return result[0], result[1]


def _collect_section_tables(data_row: Tag) -> tuple[dict[str, list[Tag]], list[str]]:
    sections: dict[str, list[Tag]] = {"starters": [], "substitutes": [], "coaches": []}
    errors: list[str] = []
    current = "starters"
    heading_map = {"suplentes": "substitutes", "entrenadores": "coaches"}
    for child in data_row.find_all(recursive=False):
        if not isinstance(child, Tag):
            continue
        heading = child.find("h2")
        if isinstance(heading, Tag):
            heading_text = _text(heading).casefold()
            if heading_text not in heading_map:
                errors.append(f"unknown_section_heading:{_text(heading)}")
                continue
            current = heading_map[heading_text]
        tables = child.find_all("table", recursive=True)
        if tables:
            sections[current].extend(tables)
    return sections, errors


def _event_kind(icon: Tag) -> str:
    title = str(icon.get("title", "")).strip().casefold()
    classes = {value.casefold() for value in _classes(icon)}
    known = {
        ("surt", "sale"): "substitution_out",
        ("entra", "entra"): "substitution_in",
        ("g", "gol"): "goal",
        ("gp", "gol de penalty"): "penalty_goal",
        ("gpp", "gol en propia puerta"): "own_goal",
        ("l", "lesión"): "other",
        ("pf", "penalty fallado"): "missed_penalty",
        ("tg", "tarjeta amarilla"): "yellow_card",
        ("tg2", "doble tarjeta amarilla"): "second_yellow",
        ("tr", "tarjeta roja"): "red_card",
        ("tv", "expulsión"): "red_card",
    }
    for (class_name, title_name), kind in known.items():
        if class_name in classes and title == title_name:
            return kind
    return "unknown"


def _nationality_class(flag: Tag | None) -> str | None:
    if not isinstance(flag, Tag):
        return None
    classes = [name for name in _classes(flag) if name != "pais"]
    return classes[0] if len(classes) == 1 else None


def _parse_appearance_table(
    table: Tag,
    *,
    role: str,
    side: str,
    team_id: int,
    base_url: str,
    evidence: _EvidenceBuilder,
) -> tuple[list[PlayerAppearance], list[_RawRosterEvent], list[str]]:
    appearances: list[PlayerAppearance] = []
    events: list[_RawRosterEvent] = []
    errors: list[str] = []
    rows = table.find_all("tr")
    for row_index, row in enumerate(rows):
        if not isinstance(row, Tag):
            continue
        style = str(row.get("style", ""))
        cells = row.find_all(["th", "td"], recursive=False)
        links = row.select('a[href*="/j/j"]')
        source_row = (
            f"css:div.container > div.row.pt-3.pb-2[style*=overflow] "
            f"table.taula_estil.text-left; section={role}; side={side}; row={row_index}"
        )
        hidden = re.search(
            r"(?:^|;)\s*display\s*:\s*none(?:\s*!important)?\s*(?:;|$)",
            style,
            re.IGNORECASE,
        ) is not None
        if hidden:
            if (
                any(_text(cell) for cell in cells)
                or row.select_one("a[href], img[src], .cosa, .pais") is not None
            ):
                errors.append(f"hidden_nonempty_roster_row:{role}:{side}:{row_index}")
            continue
        if not links:
            if not any(_text(cell) for cell in cells):
                errors.append(f"unexpected_visible_empty_roster_row:{role}:{side}:{row_index}")
            else:
                errors.append(f"roster_row_without_player_link:{role}:{side}:{row_index}")
            continue
        if len(links) != 1 or len(cells) != 6:
            errors.append(f"unexpected_roster_row_shape:{role}:{side}:{row_index}")
            continue
        player_anchor = links[0]
        href = str(player_anchor.get("href", ""))
        try:
            player_id = _player_profile_id(href, base_url, "jugador")
        except MatchDetailParserError:
            errors.append(f"unknown_player_link:{role}:{side}:{row_index}")
            continue
        player_name = _text(player_anchor)
        if not player_name:
            errors.append(f"empty_player_name:{role}:{side}:{row_index}")
            continue
        player_cell = player_anchor.find_parent(["td", "th"])
        if not isinstance(player_cell, Tag) or player_cell not in cells:
            errors.append(f"player_link_outside_roster_cell:{role}:{side}:{row_index}")
            continue
        number_cells = [
            cell
            for cell in cells
            if _text(cell).isdigit()
            and cell.select_one("a[href], img[src], .cosa, .pais") is None
        ]
        if len(number_cells) > 1:
            errors.append(f"ambiguous_shirt_number_cell:{role}:{side}:{row_index}")
            continue
        number_raw = _text(number_cells[0]) if number_cells else ""
        shirt_number: int | None = None
        if number_raw:
            if not number_raw.isdigit():
                errors.append(f"invalid_shirt_number:{role}:{side}:{row_index}:{number_raw}")
            else:
                shirt_number = int(number_raw)
        photo = row.select_one("img.mini-foto-jugador[src]")
        photo_url = urljoin(base_url, str(photo.get("src"))) if isinstance(photo, Tag) else None
        if isinstance(photo, Tag):
            image_match = _IMAGE_ID.search(str(photo.get("src", "")))
            if image_match is not None and int(image_match.group(1)) != player_id:
                errors.append(f"player_photo_id_mismatch:{role}:{side}:{row_index}")
        nationality_node = row.select_one(".pais")
        nationality = _nationality_class(nationality_node)
        row_events: list[_RawRosterEvent] = []
        for cell_index, cell in enumerate(cells):
            for event_index, item in enumerate(cell.select(".cosa")):
                icon = item.find("div", recursive=False)
                if not isinstance(icon, Tag):
                    kind = "unknown"
                    icon_class = None
                    icon_title = None
                else:
                    kind = _event_kind(icon)
                    icon_class = " ".join(_classes(icon)) or None
                    icon_title = str(icon.get("title", "")) or None
                raw_event_text = _text(item)
                minute_literal, _, _ = _minute(raw_event_text)
                reference = (
                    f"{source_row}; event_cell={cell_index}; event={event_index}; "
                    f"icon_class={icon_class!r}; title={icon_title!r}"
                )
                event = _RawRosterEvent(
                    kind=kind,
                    side=side,
                    team_id=team_id,
                    player_id=player_id,
                    player_name=player_name,
                    minute_literal=minute_literal,
                    icon_class=icon_class,
                    icon_title=icon_title,
                    raw_text=raw_event_text,
                    source_reference=reference,
                )
                row_events.append(event)
                if kind == "unknown":
                    errors.append(f"unknown_event_icon:{side}:{player_id}:{icon_class}:{icon_title}")
                elif minute_literal is None:
                    errors.append(
                        f"recognized_event_missing_minute:{kind}:{side}:{player_id}"
                    )
                evidence.add(
                    f"events.{kind}[{side}.{player_id}]",
                    "observed"
                    if kind != "unknown" and minute_literal is not None
                    else "unresolved",
                    reference,
                    raw_event_text,
                    kind if minute_literal is not None else None,
                )
        incoming = any(item.kind == "substitution_in" for item in row_events)
        outgoing = any(item.kind == "substitution_out" for item in row_events)
        events.extend(row_events)
        if role == "starter" and incoming:
            errors.append(f"starter_has_incoming_marker:{side}:{player_id}")
        if role == "substitute" and outgoing and not incoming:
            errors.append(f"substitute_has_outgoing_marker:{side}:{player_id}")
        appearances.append(
            PlayerAppearance(
                role=role,  # type: ignore[arg-type]
                player_id=player_id,
                name=player_name,
                profile_url=urljoin(base_url, href),
                photo_url=photo_url,
                shirt_number=shirt_number,
                position_code=None,
                nationality_class=nationality,
                participation_status=(
                    "entered" if role == "substitute" and incoming
                    else "no_entry_marker" if role == "substitute"
                    else "not_applicable"
                ),
                source_row=source_row,
            )
        )
        evidence.add(
            f"{role}[{side}].player_id",
            "observed",
            f"{source_row}; a[href]",
            href,
            player_id,
        )
        evidence.add(
            f"{role}[{side}].name",
            "observed",
            f"{source_row}; a[href]",
            player_name,
            player_name,
        )
        evidence.add(
            f"{role}[{side}].photo_url",
            "observed" if photo_url is not None else "not_observed",
            f"{source_row}; img.mini-foto-jugador[src]",
            str(photo.get("src")) if isinstance(photo, Tag) else None,
            photo_url,
        )
        evidence.add(
            f"{role}[{side}].nationality_class",
            "observed" if nationality is not None else "not_observed",
            f"{source_row}; .pais[class]",
            " ".join(_classes(nationality_node)) if isinstance(nationality_node, Tag) else None,
            nationality,
        )
        evidence.add(
            f"{role}[{side}].position_code",
            "not_observed",
            f"{source_row}; no position-code field in the source row",
            None,
            None,
        )
        evidence.add(
            f"{role}[{side}].shirt_number",
            "observed" if shirt_number is not None else "explicitly_absent",
            f"{source_row}; identified numeric shirt-number cell",
            number_raw or None,
            shirt_number,
        )
    return appearances, events, errors


def _parse_coach_table(table: Tag, base_url: str, side: str) -> tuple[Coach | None, str | None]:
    rows = [row for row in table.find_all("tr") if isinstance(row, Tag)]
    visible_rows = [
        row for row in rows if "display:none" not in str(row.get("style", "")).replace(" ", "")
    ]
    if not visible_rows:
        return None, None
    coach_rows = [row for row in visible_rows if "entren" in _classes(row)]
    if len(coach_rows) != 1:
        if all(not _text(row) for row in visible_rows):
            return None, None
        return None, f"coach_row_shape_unverified:{side}"
    row = coach_rows[0]
    links = row.select('a[href*="/l/l"]')
    if len(links) != 1:
        return None, f"coach_link_unverified:{side}"
    href = str(links[0].get("href", ""))
    try:
        coach_id = _profile_id(href, _COACH_HREF, "entrenador")
    except MatchDetailParserError:
        return None, f"coach_id_unverified:{side}"
    photo = row.select_one("img.mini-foto-jugador[src]")
    return (
        Coach(
            coach_id=coach_id,
            name=_text(links[0]),
            profile_url=urljoin(base_url, href),
            photo_url=urljoin(base_url, str(photo.get("src"))) if isinstance(photo, Tag) else None,
            nationality_class=_nationality_class(row),
        ),
        None,
    )


def _parse_goal_summary(
    hero: Tag,
    base_url: str,
    teams: dict[str, TeamIdentity],
    evidence: _EvidenceBuilder,
) -> tuple[list[MatchEvent], list[str]]:
    errors: list[str] = []
    candidate = None
    for node in hero.find_all("div", class_=True, recursive=False):
        classes = set(_classes(node))
        if {"row", "pt-1", "pt-md-3", "pb-2", "text-center"}.issubset(classes):
            candidate = node
            break
    if not isinstance(candidate, Tag):
        raise MatchDetailParserError("No se encuentra el bloque de goles del encabezado")
    columns = [
        node for node in candidate.find_all("div", recursive=False)
        if {"col-6", "col-sm", "f14"}.issubset(set(_classes(node)))
    ]
    if len(columns) != 2:
        raise MatchDetailParserError("El resumen de goles no contiene lados local/visitante")
    result: list[MatchEvent] = []
    for side, column in (("home", columns[0]), ("away", columns[1])):
        goal_rows = column.select(".text-blanc")
        for row_index, row in enumerate(goal_rows):
            links = row.select('a[href*="/j/j"]')
            score_node = row.find("span")
            if len(links) != 1 or not isinstance(score_node, Tag):
                errors.append(f"goal_summary_row_unverified:{side}:{row_index}")
                continue
            score_match = _GOAL_SCORE.fullmatch(_text(score_node))
            if score_match is None:
                errors.append(f"goal_summary_score_unverified:{side}:{row_index}")
                continue
            href = str(links[0].get("href", ""))
            try:
                player_id = _player_profile_id(href, base_url, "goleador")
            except MatchDetailParserError:
                errors.append(f"goal_scorer_id_unverified:{side}:{row_index}")
                continue
            raw = _text(row)
            after_scorer = " ".join(str(value) for value in links[0].next_siblings)
            literal, base, added = _minute(after_scorer)
            if literal is None:
                errors.append(f"goal_minute_unverified:{side}:{row_index}")
                evidence.add(
                    f"events.goal[{side}.{player_id}].minute",
                    "unresolved",
                    f"css:.hero-partit .text-blanc; side={side}; row={row_index}",
                    raw,
                    None,
                )
                continue
            is_penalty = "(pen)" in raw.casefold()
            is_own_goal = "(pp)" in raw.casefold()
            event_type = (
                "own_goal" if is_own_goal
                else "penalty_goal" if is_penalty
                else "goal"
            )
            event = MatchEvent(
                event_type=event_type,
                side=side,  # type: ignore[arg-type]
                team_id=teams[side].team_id,
                player_id=player_id,
                player_name=_text(links[0]),
                minute_literal=literal,
                minute_base=base,
                minute_added=added,
                is_penalty=is_penalty,
                score_after_home=int(score_match.group(1)),
                score_after_away=int(score_match.group(2)),
                raw_icon_class=None,
                raw_icon_title="(pp)" if is_own_goal else "(pen)" if is_penalty else None,
                raw_text=raw,
                source_reference=(
                    f"css:div.hero.hero-partit > div.row.pt-1.pt-md-3.pb-2.text-center "
                    f".text-blanc; side={side}; row={row_index}; scorer_href={href}"
                ),
            )
            result.append(event)
            evidence.add(
                f"events.goal[{side}.{player_id}.{literal}]",
                "observed",
                event.source_reference,
                raw,
                event.event_type,
            )
    return result, errors


def _event_signature(event: MatchEvent | _RawRosterEvent) -> tuple[Any, ...]:
    if isinstance(event, MatchEvent):
        return (
            event.side,
            event.player_id,
            event.minute_literal,
            event.event_type == "penalty_goal",
            event.event_type in {"goal", "penalty_goal", "own_goal"},
            event.event_type == "own_goal",
        )
    return (
        event.side,
        event.player_id,
        event.minute_literal,
        event.kind == "penalty_goal",
        event.kind in {"goal", "penalty_goal", "own_goal"},
        event.kind == "own_goal",
    )


def _semantic_events(
    summary_goals: list[MatchEvent],
    roster_events: list[_RawRosterEvent],
    teams: dict[str, TeamIdentity],
    evidence: _EvidenceBuilder,
) -> tuple[tuple[MatchEvent, ...], list[str]]:
    errors: list[str] = []
    player_side_by_goal: dict[tuple[int, str | None], list[_RawRosterEvent]] = {}
    for event in roster_events:
        if event.kind == "own_goal":
            player_side_by_goal.setdefault(
                (event.player_id, event.minute_literal), []
            ).append(event)
    reconciled_goals: list[MatchEvent] = []
    for event in summary_goals:
        if event.event_type != "own_goal":
            reconciled_goals.append(event)
            continue
        markers = player_side_by_goal.get((event.player_id, event.minute_literal), [])
        if len(markers) != 1 or event.side == markers[0].side:
            errors.append(
                f"own_goal_summary_and_lineup_marker_disagree:{event.player_id}:{event.minute_literal}"
            )
            reconciled_goals.append(event)
            continue
        marker = markers[0]
        reconciled_goals.append(
            replace(event, side=marker.side, team_id=marker.team_id)
        )
    summary_goals = reconciled_goals
    summary_keys = sorted((_event_signature(event) for event in summary_goals), key=repr)
    icon_goals = [
        event for event in roster_events
        if event.kind in {"goal", "penalty_goal", "own_goal"}
    ]
    icon_keys = sorted(
        (
            (
                event.side,
                event.player_id,
                event.minute_literal,
                event.kind == "penalty_goal",
                True,
                event.kind == "own_goal",
            )
            for event in icon_goals
        ),
        key=repr,
    )
    if summary_keys != icon_keys:
        errors.append("goal_summary_and_lineup_markers_disagree")
    result_events = list(summary_goals)
    for event in roster_events:
        if event.kind in {"goal", "penalty_goal", "own_goal"}:
            evidence.add(
                f"events.goal_marker[{event.side}.{event.player_id}.{event.minute_literal}]",
                "observed",
                event.source_reference,
                event.raw_text,
                event.kind,
            )
            continue
        kind = event.kind
        literal, base, added = _minute(event.minute_literal or "")
        result_events.append(
            MatchEvent(
                event_type=kind,  # type: ignore[arg-type]
                side=event.side,  # type: ignore[arg-type]
                team_id=event.team_id,
                player_id=event.player_id,
                player_name=event.player_name,
                minute_literal=literal,
                minute_base=base,
                minute_added=added,
                is_penalty=None,
                score_after_home=None,
                score_after_away=None,
                raw_icon_class=event.icon_class,
                raw_icon_title=event.icon_title,
                raw_text=event.raw_text,
                source_reference=event.source_reference,
            )
        )
    return tuple(result_events), errors


def _ephemerides(soup: BeautifulSoup, base_url: str) -> tuple[AdditionalSourceNote, ...]:
    result: list[AdditionalSourceNote] = []
    for heading in soup.find_all("h2"):
        if _text(heading).casefold() != "efemérides":
            continue
        wrapper = heading.parent
        if not isinstance(wrapper, Tag):
            continue
        content = wrapper.find_next_sibling("div")
        if not isinstance(content, Tag):
            continue
        for index, note in enumerate(content.select(".alert")):
            link = note.select_one('a[href*="/j/j"]')
            linked_id = None
            if isinstance(link, Tag):
                try:
                    linked_id = _player_profile_id(
                        str(link.get("href", "")), base_url, "efeméride"
                    )
                except MatchDetailParserError:
                    linked_id = None
            result.append(
                AdditionalSourceNote(
                    note_type="ephemeris",
                    text=_text(note),
                    source_reference=f"css:h2 (text='Efemérides') + sibling .alert[{index}]",
                    linked_player_id=linked_id,
                )
            )
    return tuple(result)


def parse_match_detail_html(
    source_html: bytes,
    *,
    expected_match: Mapping[str, Any],
    metadata: Mapping[str, Any],
    discovery_id: str,
    inventory_id: str,
    parser_version: str = PARSER_VERSION,
    verified_sha256: str | None = None,
) -> MatchDetailObservation:
    """Parse a byte string and compare it to its catalog/provenance records.

    ``verified_sha256`` is normally passed by :func:`parse_saved_artifact` after
    manifest verification. Direct callers must still match the declared hash in
    metadata; this function never writes the parse result.
    """

    if not isinstance(source_html, bytes) or not source_html:
        raise MatchDetailParserError("El HTML fuente debe ser bytes no vacíos")
    digest = _sha256(source_html)
    if verified_sha256 is not None and digest != verified_sha256:
        raise MatchDetailParserError("El HTML cambió tras verificar el manifiesto")
    source_id, source_url = _expected_identity(expected_match)
    metadata_schema = metadata.get("schema_version")
    if metadata_schema == "football_data_hub.match_detail_discovery_artifact.v1":
        if metadata.get("source_html_sha256") != digest:
            raise MatchDetailParserError("El hash del HTML no coincide con metadata histórica")
        metadata_expectations = {
            "requested_url": source_url,
            "final_url": source_url,
            "source_match_id": source_id,
            "season": expected_match.get("season"),
            "competition": expected_match.get("competition"),
            "group": expected_match.get("group"),
            "matchday": expected_match.get("matchday"),
            "source_generation_id": expected_match.get("source_generation_id"),
            "source_capture_id": expected_match.get("source_capture_id"),
            "internal_id": expected_match.get("internal_id"),
        }
        if (
            metadata.get("artifact_type") != "discovery_only_unverified"
            or metadata.get("promotion_eligible") is not False
            or metadata.get("discovery_id") != discovery_id
            or metadata.get("inventory_id") != inventory_id
            or metadata.get("source_html_bytes") != len(source_html)
        ):
            raise MatchDetailParserError("Metadata no acredita un artefacto histórico discovery-only íntegro")
        access_status = metadata.get("access_status")
        source_not_promotable = (
            metadata.get("promotion_eligible") is False
            and metadata.get("artifact_type") == "discovery_only_unverified"
        )
    elif metadata_schema == "football_data_hub.match_detail_campaign_discovery.v1":
        if verified_sha256 is None:
            raise MatchDetailParserError(
                "Metadata de campaña requiere hash verificado desde su manifiesto"
            )
        metadata_expectations = {
            "requested_url": source_url,
            "final_url": source_url,
            "source_match_id": source_id,
            "internal_id": expected_match.get("internal_id"),
        }
        if (
            metadata.get("campaign_id") is None
            or metadata.get("access_classification") != "VALID"
            or metadata.get("http_status") != 200
            or metadata.get("challenge_detected") is not False
            or metadata.get("denial_detected") is not False
            or metadata.get("capture_promoted") is not False
            or metadata.get("semantic_identity_verified") is not False
            or not isinstance(metadata.get("navigation_attempt_id"), str)
            or not metadata.get("navigation_attempt_id")
        ):
            raise MatchDetailParserError("Metadata de campaña no acredita un descubrimiento íntegro y no promovido")
        access_status = metadata.get("access_classification")
        source_not_promotable = (
            metadata.get("capture_promoted") is False
            and metadata.get("semantic_identity_verified") is False
        )
    else:
        raise MatchDetailParserError("Versión de metadata de descubrimiento desconocida")
    for key, value in metadata_expectations.items():
        if metadata.get(key) != value:
            raise MatchDetailParserError(f"Metadata/catalog mismatch: {key}")
    html_text = source_html.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html_text, "lxml")
    hero = soup.select_one("div.hero.hero-partit")
    if not isinstance(hero, Tag):
        raise MatchDetailParserError("No se encuentra div.hero.hero-partit")
    evidence = _EvidenceBuilder(digest, parser_version)
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[ValidationCheck] = []

    canonical = soup.select_one('link[rel="canonical"][href]')
    canonical_url = urljoin(source_url, str(canonical.get("href"))) if isinstance(canonical, Tag) else ""
    canonical_query = parse_qs(urlsplit(canonical_url).query, keep_blank_values=True)
    canonical_id = canonical_query.get("id", [None])[0]
    hidden_ids = {
        str(node.get("value"))
        for node in soup.select('input[name="codi"][value]')
    }
    canonical_ok = canonical_url == source_url and canonical_id == source_id
    hidden_id_ok = hidden_ids == {source_id}
    if not canonical_ok:
        errors.append("canonical_identity_mismatch")
    if not hidden_id_ok:
        errors.append("embedded_source_id_mismatch")
    checks.extend(
        (
            ValidationCheck("canonical_matches_catalog_url_and_id", canonical_ok, canonical_url),
            ValidationCheck("hidden_codi_matches_catalog_id", hidden_id_ok, repr(sorted(hidden_ids))),
        )
    )
    evidence.add("identity.canonical_url", "observed" if canonical else "not_observed", "link[rel=canonical]", canonical_url or None, canonical_url or None)
    evidence.add("identity.hidden_codi", "observed" if hidden_ids else "not_observed", 'input[name="codi"]', ",".join(sorted(hidden_ids)) or None, source_id if hidden_id_ok else None)

    title = _text(soup.title)
    if metadata.get("page_title") != title:
        errors.append("metadata_title_mismatch")
    home, away = _team_identities(hero, source_url, expected_match, evidence)
    teams_by_side = {"home": home, "away": away}
    score_cells = hero.select("h1 .d-none.d-md-block .row.mt-3.mb-2 .resultat-partit")
    # The scoped parser above validates the desktop score. This second pass only
    # checks responsive score copies against it, rather than counting them twice.
    mobile_scores = hero.select("h1 .d-block.d-md-none .resultat-partit")
    desktop_scores = [
        int(_text(node)) for node in score_cells if _text(node).isdigit()
    ]
    mobile_values = [int(_text(node)) for node in mobile_scores if _text(node).isdigit()]
    if mobile_values != desktop_scores:
        errors.append("responsive_score_copy_disagrees")
    if len(desktop_scores) != 2:
        raise MatchDetailParserError("El marcador de escritorio no tiene dos celdas numéricas")
    home_goals, away_goals = desktop_scores
    score = MatchScore(home_goals=home_goals, away_goals=away_goals)
    catalog_score = expected_match.get("reference_result") or {}
    score_ok = (
        catalog_score.get("home_goals") == home_goals
        and catalog_score.get("away_goals") == away_goals
    )
    if not score_ok:
        errors.append("score_catalog_mismatch")
    checks.append(ValidationCheck("score_matches_catalog", score_ok, f"{home_goals}-{away_goals}"))

    expected_date = expected_match.get("source_match_date")
    expected_title_date = ""
    if isinstance(expected_date, str):
        try:
            expected_title_date = (
                f"{int(expected_date[8:10]):02d}/"
                f"{int(expected_date[5:7]):02d}/"
                f"{int(expected_date[:4]):04d}"
            )
        except (ValueError, IndexError):
            errors.append("catalog_date_format_invalid")
    title_ok = all(
        token.casefold() in title.casefold()
        for token in (
            home.name,
            away.name,
            f"{home_goals} - {away_goals}",
            expected_title_date,
        )
        if token
    )
    if not title_ok:
        errors.append("document_title_identity_mismatch")
    checks.append(ValidationCheck("title_matches_teams_score_date", title_ok, title))

    competition_raw, competition_href, _ = _field_value(hero, "Competición")
    matchday_raw, matchday_href, _ = _field_value(hero, "Jornada")
    stadium_raw, stadium_href, _ = _field_value(hero, "Estadio")
    date_raw, _, _ = _field_value(hero, "Fecha")
    comp_href_path = urlsplit(urljoin(source_url, competition_href)).path
    competition_label_ok = competition_raw.casefold() in {
        "1ª rfef",
        "primera rfef",
        "primera federación",
    }
    if not competition_label_ok:
        errors.append("competition_label_mismatch")
    checks.append(
        ValidationCheck(
            "competition_label_is_primera_federacion",
            competition_label_ok,
            competition_raw,
        )
    )
    season_href_match = re.search(r"/t/t(\d{4})-(\d{2})[^/]*\.html$", comp_href_path)
    season_href = (
        f"{season_href_match.group(1)}-{season_href_match.group(2)}"
        if season_href_match
        else None
    )
    season_ok = season_href == str(expected_match.get("season"))
    if not season_ok:
        errors.append("season_competition_link_mismatch")
    checks.append(ValidationCheck("competition_link_matches_catalog_season", season_ok, comp_href_path))
    season_context = _provenanced(
        str(expected_match.get("season")) if season_ok else None,
        state="observed" if season_ok else "unresolved",
        origin="match_catalog",
        raw=comp_href_path,
        reference="inventory.season; competition href corroborates 2026-27",
    )
    comp_context = _provenanced(
        "Primera Federación" if competition_label_ok else None,
        state="observed" if competition_label_ok else "unresolved",
        origin="match_detail_dom",
        raw=competition_raw,
        reference="div.hero.hero-partit .f14 label='Competición' + .f13",
    )
    group = _provenanced(
        str(expected_match.get("group")),
        state="not_observed",
        origin="match_catalog",
        raw=None,
        reference="inventory.group (la ficha no rotula el grupo)",
    )
    jornada_match = re.search(r"\b(\d+)\b", matchday_raw)
    jornada_value = int(jornada_match.group(1)) if jornada_match else None
    jornada_query = parse_qs(urlsplit(urljoin(source_url, matchday_href)).query).get("jornada", [])
    jornada_ok = (
        jornada_value == expected_match.get("matchday")
        and jornada_query == [str(expected_match.get("matchday"))]
    )
    if not jornada_ok:
        errors.append("matchday_catalog_mismatch")
    checks.append(ValidationCheck("matchday_text_and_link_match_catalog", jornada_ok, matchday_raw))
    matchday_context = _provenanced(
        jornada_value if jornada_ok else None,
        state="observed" if jornada_ok else "unresolved",
        origin="match_detail_dom",
        raw=matchday_raw,
        reference="div.hero.hero-partit .f14 label='Jornada' + href query jornada",
    )
    evidence.add("context.competition", "observed" if competition_label_ok else "unresolved", "div.hero.hero-partit .f14 label='Competición'", competition_raw, "Primera Federación" if competition_label_ok else None)
    evidence.add(
        "context.season",
        "observed" if season_ok else "unresolved",
        "inventory.season + competition href",
        competition_href,
        str(expected_match.get("season")) if season_ok else None,
    )
    evidence.add("context.group", "not_observed", "inventory.group", None, str(expected_match.get("group")))
    evidence.add("context.matchday", "observed" if jornada_ok else "unresolved", "div.hero.hero-partit .f14 label='Jornada'", matchday_raw, jornada_value if jornada_ok else None)

    match_date, kickoff, kickoff_state, kickoff_error = _parse_date_and_kickoff(date_raw)
    if match_date is None:
        errors.append(kickoff_error or "date_format_unrecognized")
    elif kickoff_error:
        warnings.append(kickoff_error)
    date_ok = match_date is not None and (expected_date is None or match_date == expected_date)
    if not date_ok:
        errors.append("date_catalog_mismatch")
    checks.append(ValidationCheck("date_matches_catalog", date_ok, date_raw))
    date_value = _provenanced(match_date, state="observed" if match_date else "unresolved", origin="match_detail_dom", raw=date_raw, reference="div.hero.hero-partit .f14 label='Fecha'")
    kickoff_value = _provenanced(kickoff, state=kickoff_state, origin="match_detail_dom", raw=date_raw, reference="div.hero.hero-partit .f14 label='Fecha'")
    timezone_value = _provenanced(None, state="not_observed", origin="match_detail_dom", raw=date_raw, reference="El HTML publica hora local sin zona horaria")
    evidence.add("match.match_date", "observed" if match_date else "unresolved", "div.hero.hero-partit .f14 label='Fecha'", date_raw, match_date)
    evidence.add("match.kickoff_time_local", kickoff_state, "div.hero.hero-partit .f14 label='Fecha'", date_raw, kickoff)
    evidence.add("match.timezone", "not_observed", "div.hero.hero-partit .f14 label='Fecha'", date_raw, None)

    stadium_id = _stadium_id(stadium_href, source_url)
    stadium_url = urljoin(source_url, stadium_href)
    stadium_name = stadium_raw
    stadium_id_value = _provenanced(stadium_id, state="observed", origin="match_detail_dom", raw=stadium_href, reference="div.hero.hero-partit .f14 label='Estadio' a[href]")
    stadium_url_value = _provenanced(stadium_url, state="observed", origin="match_detail_dom", raw=stadium_href, reference="div.hero.hero-partit .f14 label='Estadio' a[href]")
    stadium_name_value = _provenanced(stadium_name, state="observed", origin="match_detail_dom", raw=stadium_raw, reference="div.hero.hero-partit .f14 label='Estadio' + .f13")
    evidence.add("match.stadium", "observed", "div.hero.hero-partit .f14 label='Estadio'", stadium_raw, stadium_name)

    referee_links = hero.select('a[href*="/r/r"]')
    unique_referees: dict[str, Tag] = {str(node.get("href")): node for node in referee_links if isinstance(node, Tag)}
    if len(unique_referees) != 1:
        errors.append("referee_link_missing_or_ambiguous")
        referee_name = referee_url = None
        referee_id = None
    else:
        referee_href, referee_node = next(iter(unique_referees.items()))
        whistle_present = any("whistle-white.png" in str(img.get("src", "")) for img in referee_node.find_all("img"))
        if not whistle_present:
            errors.append("referee_role_icon_unverified")
        referee_id = _profile_id(referee_href, _REFEREE_HREF, "árbitro")
        referee_name = _text(referee_node)
        referee_url = urljoin(source_url, referee_href)
    referee_state = "observed" if referee_id is not None else "unresolved"
    referee_name_value = _provenanced(referee_name, state=referee_state, origin="match_detail_dom", raw=referee_name, reference="div.hero.hero-partit a[href^='../r/r'] + whistle-white.png")
    referee_id_value = _provenanced(referee_id, state=referee_state, origin="match_detail_dom", raw=next(iter(unique_referees), None), reference="div.hero.hero-partit a[href^='../r/r']")
    referee_url_value = _provenanced(referee_url, state=referee_state, origin="match_detail_dom", raw=next(iter(unique_referees), None), reference="div.hero.hero-partit a[href^='../r/r']")
    evidence.add("match.referee", referee_state, "div.hero.hero-partit a[href^='../r/r'] img[src*=whistle]", referee_name, referee_id)

    data_container = hero.find_next_sibling("div", class_="container")
    if not isinstance(data_container, Tag):
        raise MatchDetailParserError("No se encuentra el contenedor de las tablas del partido")
    data_row = None
    for row in data_container.find_all("div", recursive=False):
        if "row" in _classes(row) and "pt-3" in _classes(row) and "pb-2" in _classes(row) and "overflow" in str(row.get("style", "")):
            data_row = row
            break
    if not isinstance(data_row, Tag):
        raise MatchDetailParserError("No se encuentra el bloque de alineaciones/contexto")
    sections, heading_errors = _collect_section_tables(data_row)
    errors.extend(heading_errors)
    if len(sections["starters"]) != 2:
        errors.append(f"starter_tables_expected_two:{len(sections['starters'])}")
    if len(sections["substitutes"]) not in (0, 2):
        errors.append(f"substitute_tables_expected_zero_or_two:{len(sections['substitutes'])}")
    if len(sections["coaches"]) not in (0, 2):
        errors.append(f"coach_tables_expected_zero_or_two:{len(sections['coaches'])}")

    starters_by_side: dict[str, tuple[PlayerAppearance, ...] | None] = {"home": None, "away": None}
    subs_by_side: dict[str, tuple[PlayerAppearance, ...] | None] = {"home": None, "away": None}
    raw_roster_events: list[_RawRosterEvent] = []
    for section, role in (("starters", "starter"), ("substitutes", "substitute")):
        tables = sections[section]
        if not tables:
            if section == "substitutes":
                warnings.append("substitutes_section_not_observed")
            continue
        for index, (side, team) in enumerate((("home", home), ("away", away))):
            appearances, row_events, row_errors = _parse_appearance_table(
                tables[index],
                role=role,
                side=side,
                team_id=team.team_id,
                base_url=source_url,
                evidence=evidence,
            )
            errors.extend(row_errors)
            raw_roster_events.extend(row_events)
            if section == "starters":
                starters_by_side[side] = tuple(appearances)
                if len(appearances) != 11:
                    errors.append(f"starter_count_not_11:{side}:{len(appearances)}")
            else:
                subs_by_side[side] = tuple(appearances)
    identity_errors = roster_identity_errors(starters_by_side, subs_by_side)
    errors.extend(identity_errors)

    coach_by_side: dict[str, Coach | None] = {"home": None, "away": None}
    if sections["coaches"]:
        for index, (side, _) in enumerate((("home", home), ("away", away))):
            if index >= len(sections["coaches"]):
                warnings.append(f"coach_not_observed:{side}")
                continue
            coach, issue = _parse_coach_table(sections["coaches"][index], source_url, side)
            coach_by_side[side] = coach
            if issue:
                errors.append(issue)
            if coach:
                evidence.add(f"{side}.coach", "observed", "table.entren tr.entren a[href]", coach.name, coach.coach_id)
    else:
        warnings.append("coaches_section_not_observed")

    summary_goals, goal_errors = _parse_goal_summary(hero, source_url, teams_by_side, evidence)
    errors.extend(goal_errors)
    roster_player_ids = {
        (side, appearance.player_id)
        for side, values in starters_by_side.items()
        for appearance in values or ()
    } | {
        (side, appearance.player_id)
        for side, values in subs_by_side.items()
        for appearance in values or ()
    }
    events, event_errors = _semantic_events(summary_goals, raw_roster_events, teams_by_side, evidence)
    errors.extend(event_errors)
    for event in events:
        if event.player_id is None or (event.side, event.player_id) not in roster_player_ids:
            errors.append(f"event_player_not_in_roster:{event.side}:{event.player_id}")
    goal_events = [
        event for event in events
        if event.event_type in {"goal", "penalty_goal", "own_goal"}
    ]
    scored_sides = [
        ("away" if event.side == "home" else "home")
        if event.event_type == "own_goal"
        else event.side
        for event in goal_events
    ]
    goals_count_ok = (
        scored_sides.count("home") == home_goals
        and scored_sides.count("away") == away_goals
    )
    if not goals_count_ok:
        errors.append("goal_event_count_does_not_match_score")
    checks.append(ValidationCheck("goal_summary_count_matches_score", goals_count_ok, f"{len(summary_goals)} goals for {home_goals}-{away_goals}"))
    goal_progression_ok, goal_progression_detail = goal_progression_is_consistent(
        goal_events, home_goals, away_goals
    )
    if not goal_progression_ok:
        errors.append("goal_score_progression_invalid")
    checks.append(
        ValidationCheck(
            "goal_score_progression_is_chronologically_consistent",
            goal_progression_ok,
            goal_progression_detail,
        )
    )

    for side in ("home", "away"):
        if subs_by_side[side] is None:
            continue
        entries = sum(
            event.side == side and event.event_type == "substitution_in"
            for event in events
        )
        exits = sum(
            event.side == side and event.event_type == "substitution_out"
            for event in events
        )
        evidence.add(
            f"events.substitution_balance.{side}",
            "observed",
            f"all lineup/substitute event cells; side={side}",
            f"entries={entries}; exits={exits}",
            f"entries={entries}; exits={exits}",
        )
        if entries != exits:
            warnings.append(
                f"substitution_event_balance_mismatch:{side}:in={entries}:out={exits}"
            )

    red_cards = [event for event in events if event.event_type == "red_card"]
    second_yellows = [event for event in events if event.event_type == "second_yellow"]
    unknown_events = [event for event in raw_roster_events if event.kind == "unknown"]
    if second_yellows:
        evidence.add(
            "events.second_yellows",
            "observed",
            "recognized lineup/substitute event cells; icon=TG2; title='Doble Tarjeta Amarilla'",
            "; ".join(
                f"player_id={event.player_id}; minute={event.minute_literal}; text={event.raw_text}"
                for event in second_yellows
            ),
            len(second_yellows),
        )
    if not red_cards and not second_yellows and not unknown_events:
        evidence.add("events.red_cards", "explicitly_absent", "all lineup/substitute event cells; title='Tarjeta Roja'", None, None)
    elif not red_cards and second_yellows:
        # The direct-red marker is absent, but a second-yellow dismissal is
        # present. Keep those semantics distinct and avoid a misleading claim
        # that no dismissal happened in the match.
        evidence.add(
            "events.red_cards",
            "not_observed",
            "direct-red markers absent; second-yellow dismissal observed",
            "; ".join(event.raw_text for event in second_yellows),
            None,
        )
        warnings.append("direct_red_card_absence_not_asserted_second_yellow_present")
    elif not red_cards and unknown_events:
        evidence.add(
            "events.red_cards",
            "not_observed",
            "red-card absence cannot be established while event icons are unknown",
            None,
            None,
        )
    red_absence_verified = not unknown_events
    if not red_absence_verified and not red_cards:
        warnings.append("red_card_absence_not_proven_due_to_unknown_event_icons")
    checks.append(ValidationCheck("all_event_icons_recognized", not unknown_events, f"unknown={len(unknown_events)}"))

    # This page has no match-level aggregate statistics. Keep this as absence,
    # not zero; the check is scoped to the six lineup/substitute/coach tables.
    evidence.add("aggregate_statistics", "explicitly_absent", "match detail block: no aggregate-statistics section/table", None, None)
    notes = _ephemerides(soup, source_url)
    if notes:
        for note in notes:
            evidence.add("additional_notes.ephemeris", "observed", note.source_reference, note.text, note.text)
    else:
        warnings.append("ephemerides_not_observed")

    home_side = MatchSide(home, coach_by_side["home"], starters_by_side["home"], subs_by_side["home"])
    away_side = MatchSide(away, coach_by_side["away"], starters_by_side["away"], subs_by_side["away"])
    source = MatchDetailSource(
        provider="BDFutbol",
        internal_id=str(expected_match.get("internal_id")),
        requested_url=str(metadata.get("requested_url")),
        final_url=str(metadata.get("final_url")),
        canonical_url=canonical_url,
        source_match_id=source_id,
        discovery_id=discovery_id,
        inventory_id=inventory_id,
        source_capture_id=str(expected_match.get("source_capture_id")),
        source_generation_id=str(expected_match.get("source_generation_id")),
        source_html_sha256=digest,
        parser_version=parser_version,
        captured_at_utc=str(metadata.get("captured_at_utc")),
        artifact_access_status=str(access_status),
    )
    if metadata_schema == "football_data_hub.match_detail_campaign_discovery.v1":
        warnings.append("campaign_discovery_remains_unpromoted_pending_independent_review")
    elif access_status != "INVALID_CONTENT":
        warnings.append(f"historical_access_status:{access_status}")
    else:
        warnings.append("source_artifact_remains_INVALID_CONTENT_and_discovery_only")
    if not source_not_promotable:
        errors.append("artifact_promotion_flag_not_false")

    critical_evidence_paths = {
        "identity.canonical_url",
        "identity.hidden_codi",
        "home_team.team_id",
        "away_team.team_id",
        "score.home_goals",
        "score.away_goals",
        "context.competition",
        "context.season",
        "context.matchday",
        "match.match_date",
        "match.kickoff_time_local",
        "match.referee",
    }
    unresolved_critical = sorted(
        {
            item.field_path
            for item in evidence.items
            if item.state == "unresolved"
            and (
                item.field_path in critical_evidence_paths
                or item.field_path.startswith("events.")
            )
        }
    )
    for field_path in unresolved_critical:
        errors.append(f"critical_evidence_unresolved:{field_path}")
    checks.append(
        ValidationCheck(
            "critical_evidence_is_resolved",
            not unresolved_critical,
            ", ".join(unresolved_critical) or "all critical evidence resolved",
        )
    )

    checks.extend(
        (
            ValidationCheck("two_distinct_team_ids_match_catalog", home.team_id != away.team_id, f"{home.team_id},{away.team_id}"),
            ValidationCheck("eleven_starters_each", len(starters_by_side["home"] or ()) == 11 and len(starters_by_side["away"] or ()) == 11, f"{len(starters_by_side['home'] or ())},{len(starters_by_side['away'] or ())}"),
            ValidationCheck("roster_player_ids_are_unique", not identity_errors, "; ".join(identity_errors) or "unique within and across teams/roles"),
            ValidationCheck("unknown_event_icons_rejected", not unknown_events, f"unknown={len(unknown_events)}"),
            ValidationCheck(
                "source_not_promotable",
                source.promotion_eligible is False and source_not_promotable,
                str(metadata.get("schema_version")),
            ),
        )
    )
    valid = not errors and all(check.passed for check in checks)
    context = MatchContext(
        season=season_context,
        competition=comp_context,
        group=group,
        matchday=matchday_context,
    )
    return MatchDetailObservation(
        schema_version="football_data_hub.match_detail_observation.v1",
        source=source,
        context=context,
        match_date=date_value,
        kickoff_time_local=kickoff_value,
        timezone=timezone_value,
        home=home_side,
        away=away_side,
        score=score,
        stadium_name=stadium_name_value,
        stadium_id=stadium_id_value,
        stadium_url=stadium_url_value,
        referee_name=referee_name_value,
        referee_id=referee_id_value,
        referee_url=referee_url_value,
        events=events,
        additional_notes=notes,
        aggregate_statistics_state="explicitly_absent",
        evidence=tuple(evidence.items),
        validation=SemanticValidation(
            semantic_valid=valid,
            errors=tuple(dict.fromkeys(errors)),
            warnings=tuple(dict.fromkeys(warnings)),
            checks=tuple(checks),
            promotion_eligible=False,
        ),
    )


def parse_saved_artifact(
    artifact_dir: Path,
    *,
    expected_match: Mapping[str, Any],
    parser_version: str = PARSER_VERSION,
) -> MatchDetailObservation:
    """Verify the immutable discovery artifact and parse its HTML read-only."""

    artifact = _verify_artifact(artifact_dir, expected_match)
    return parse_match_detail_html(
        artifact.html,
        expected_match=expected_match,
        metadata=artifact.metadata,
        discovery_id=str(artifact.metadata["discovery_id"]),
        inventory_id=artifact.inventory_id,
        parser_version=parser_version,
        verified_sha256=artifact.sha256,
    )
