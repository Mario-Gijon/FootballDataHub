"""Offline, view-specific parsers for player snapshots."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .html_parser import (
    PLAYER_PARSER_VERSION,
    PLAYER_SCHEMA_VERSION,
    PlayerSnapshotError,
    classify_player_view,
    parse_player_html as parse_source_html,
    soup_from_html,
)
from .models import (
    PlayerMatchesPage,
    PlayerRivalsPage,
    PlayerStatisticsPage,
    PlayerTrajectoryPage,
)


class PlayerCaptureParseError(ValueError):
    """A saved player capture failed provenance, identity or structural checks."""


PlayerPage = PlayerTrajectoryPage | PlayerStatisticsPage | PlayerMatchesPage | PlayerRivalsPage


def _identity_matches(html: str, names: tuple[str, ...]) -> bool:
    soup = soup_from_html(html)
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    heading = soup.find("h1")
    visible = f"{title} {heading.get_text(' ', strip=True) if heading else ''}".casefold()
    return any(name and name.casefold() in visible for name in names)


def _player_key(value: int | str) -> tuple[int, str]:
    digits = str(value).removeprefix("j")
    if not digits.isdigit():
        raise PlayerCaptureParseError(f"ID de jugador no válido: {value}")
    numeric = int(digits)
    return numeric, f"j{numeric}"


def _normalize_owner_ids(value: Any, source_key: str, player_id: int) -> Any:
    if isinstance(value, list):
        return [_normalize_owner_ids(item, source_key, player_id) for item in value]
    if isinstance(value, dict):
        return {
            key: player_id if key == "player_id" and item == source_key else (
                player_id if key == "player_identity_key" and item == source_key else
                _normalize_owner_ids(item, source_key, player_id)
            )
            for key, item in value.items()
        }
    return value


def _common(parsed: dict[str, Any], player_id: int, source_key: str) -> dict[str, Any]:
    source = dict(parsed["source"])
    source["parser_version"] = PLAYER_PARSER_VERSION
    source["schema_version"] = PLAYER_SCHEMA_VERSION
    return {
        "player_id": player_id,
        "source_player_key": source_key,
        "view": parsed["view"],
        "requested_url": source.get("requested_url") or parsed["url"],
        "final_url": source.get("final_url") or parsed["url"],
        "page_title_raw": parsed.get("page_title_raw"),
        "source": source,
        "filter_controls": parsed.get("filter_controls", []),
        "tables": parsed.get("tables", []),
        "relationships": parsed.get("relationships", []),
        "coverage": parsed.get("coverage", {}),
    }


def parse_player_html(
    html: str,
    metadata: dict[str, Any],
    *,
    expected_player_id: int | str,
    expected_names: tuple[str, ...] = (),
    snapshot_label: str | None = None,
) -> PlayerPage:
    """Parse one valid page while preserving source cells and view boundaries."""
    player_id, source_key = _player_key(expected_player_id)
    if metadata.get("player_id") not in {None, player_id, str(player_id)}:
        raise PlayerCaptureParseError("El player_id de metadata contradice el ID esperado")
    if metadata.get("access_status") != "VALID" or metadata.get("http_status") != 200:
        raise PlayerCaptureParseError("Solo se pueden parsear capturas VALID con HTTP 200")
    requested = str(metadata.get("requested_url") or "")
    final = str(metadata.get("final_url") or "")
    if not requested or not final or requested != final:
        raise PlayerCaptureParseError("La URL final no coincide exactamente con la solicitada")
    parts = urlsplit(requested)
    if parts.scheme != "https" or parts.hostname not in {"www.bdfutbol.com", "bdfutbol.com"}:
        raise PlayerCaptureParseError("La captura no es una URL HTTPS de BDFutbol")
    parsed_key, view = classify_player_view(final)
    if parsed_key != source_key:
        raise PlayerCaptureParseError(f"El ID de la URL es {parsed_key}, se esperaba {source_key}")
    if not _identity_matches(html, expected_names):
        raise PlayerCaptureParseError("El título y el encabezado no confirman la identidad esperada")
    expected_hash = metadata.get("html_sha256")
    if expected_hash and hashlib.sha256(html.encode("utf-8")).hexdigest() != expected_hash:
        raise PlayerCaptureParseError("El hash HTML no coincide con metadata")
    try:
        parsed = parse_source_html(
            html,
            metadata,
            snapshot_directory=snapshot_label,
            expected_player_id=source_key,
        )
    except PlayerSnapshotError as exc:
        raise PlayerCaptureParseError(str(exc)) from exc
    if isinstance(metadata.get("controls_observed"), list):
        parsed["filter_controls"] = metadata["controls_observed"]
    parsed = _normalize_owner_ids(parsed, source_key, player_id)
    base = _common(parsed, player_id, source_key)
    data = parsed["view_data"]
    if view == "profile":
        return PlayerTrajectoryPage(
            **base,
            profile=data,
            career_rows=data.get("career_rows", []),
            career_totals=data.get("career_totals_raw", []),
        )
    if view == "statistics":
        return PlayerStatisticsPage(**base, statistics_rows=data.get("statistics_rows", []))
    if view == "matches":
        return PlayerMatchesPage(
            **base,
            summary_rows=data.get("match_summary_rows", []),
            individual_matches=data.get("individual_match_rows", []),
            individual_matches_source=data.get("individual_match_rows_source"),
            window_p_parse_status=data.get("window_p_parse_status", "NOT_PRESENT"),
            window_p_record_count=data.get("window_p_record_count"),
            detail_coverage=data.get("match_detail_coverage", "UNKNOWN"),
            filter_parameters=data.get("filter_parameters", {}),
            filtered_view=bool(data.get("filtered_view", False)),
            exhaustiveness_status=data.get("exhaustiveness_status", "UNKNOWN"),
        )
    if view == "rivals":
        return PlayerRivalsPage(**base, rival_records=data.get("rival_records", []))
    raise PlayerCaptureParseError(f"Vista no soportada: {view}")


def parse_snapshot(
    capture_dir: Path,
    snapshot_record: dict[str, Any],
    *,
    expected_player_id: int | str,
    expected_names: tuple[str, ...] = (),
) -> PlayerPage:
    """Recover a page offline from one manifest record and verify its SHA-256."""
    root = capture_dir.expanduser().resolve()
    try:
        metadata_path = (root / str(snapshot_record["metadata_path"])).resolve()
        raw_path = (root / str(snapshot_record["raw_path"])).resolve()
    except KeyError as exc:
        raise PlayerCaptureParseError(f"Al manifiesto le falta {exc.args[0]}") from exc
    if root not in metadata_path.parents or root not in raw_path.parents:
        raise PlayerCaptureParseError("Ruta de snapshot fuera del directorio de captura")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        compressed = raw_path.read_bytes()
        html_bytes = gzip.decompress(compressed)
    except (OSError, ValueError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
        raise PlayerCaptureParseError(f"No se pudo recuperar el HTML comprimido: {exc}") from exc
    actual_hash = hashlib.sha256(html_bytes).hexdigest()
    if actual_hash != metadata.get("html_sha256"):
        raise PlayerCaptureParseError("SHA-256 del HTML descomprimido no coincide")
    if len(html_bytes) != metadata.get("html_uncompressed_bytes"):
        raise PlayerCaptureParseError("El tamaño HTML descomprimido no coincide con metadata")
    if snapshot_record.get("html_sha256") != actual_hash:
        raise PlayerCaptureParseError("El hash del manifiesto no coincide con el archivo raw")
    return parse_player_html(
        html_bytes.decode("utf-8"),
        metadata,
        expected_player_id=expected_player_id,
        expected_names=expected_names,
        snapshot_label=str(snapshot_record.get("metadata_path")),
    )


def player_page_to_dict(page: PlayerPage) -> dict[str, Any]:
    """Serialize one typed view contract without browser or filesystem objects."""
    return asdict(page)
