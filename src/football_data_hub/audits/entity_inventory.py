"""Reusable primitives for deduplicating offline football entity references."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Iterable
from urllib.parse import parse_qs, urlsplit

_PLAYER_PROFILE = re.compile(r"^/es/j/(j\d+)\.html$")
_PLAYER_MATCHES = re.compile(r"^/es/p/j(\d+)\.html$")
_PLAYER_RIVALS = re.compile(r"^/es/p/jr(\d+)\.html$")
_CLUB = re.compile(r"^/es/(?:p|e)/e(\d+)\.html$")
_TEAM_SEASON = re.compile(r"^/es/t/(t\d{4}-\d+)\.html$")
_COACH = re.compile(r"^/es/l/(l\d+)\.html$")
_REFEREE = re.compile(r"^/es/r/(r\d+)\.html$")
_STADIUM = re.compile(r"^/es/s/(\d+)\.html$")


def identify_entity_url(url: str) -> dict[str, str] | None:
    """Identify entity ID and page view from a locally observed BDFutbol URL."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.netloc and parsed.netloc.casefold() not in {"www.bdfutbol.com", "bdfutbol.com"}:
        return None
    path = parsed.path
    query = parse_qs(parsed.query)

    if path == "/es/p/p.php":
        match_id = query.get("id", [""])[0]
        if match_id.isdigit():
            return {"entity_type": "match", "entity_id": match_id, "view": "match_detail"}
        return None

    for pattern, entity_type, view in (
        (_PLAYER_PROFILE, "player", "profile"),
        (_PLAYER_MATCHES, "player", "matches"),
        (_PLAYER_RIVALS, "player", "rivals"),
        (_CLUB, "club", "club_page"),
        (_TEAM_SEASON, "team_season", "team_alignment"),
        (_COACH, "coach", "profile"),
        (_REFEREE, "referee", "profile"),
        (_STADIUM, "stadium", "profile"),
    ):
        match = pattern.fullmatch(path)
        if match:
            view_name = view
            if entity_type == "player" and view == "profile" and query.get("p") == ["stats"]:
                view_name = "statistics"
            elif entity_type == "team_season" and query.get("t"):
                view_name = f"team_{query['t'][0]}"
            elif entity_type == "club" and query:
                view_name = "club_variant"
            entity_id = match.group(1)
            if entity_type == "referee":
                entity_id = entity_id[1:]
            if entity_type == "player" and view in {"matches", "rivals"}:
                entity_id = f"j{entity_id}"
            return {"entity_type": entity_type, "entity_id": entity_id, "view": view_name}
    return None


def acquisition_status(captures: Iterable[dict[str, Any]]) -> str:
    """Classify entity acquisition without promoting a reference to a capture."""
    snapshots = list(captures)
    valid = [
        item for item in snapshots
        if item.get("access_status") == "VALID"
        and item.get("http_status") == 200
        and item.get("rendered_html_sha256")
        and item.get("rendered_html_exists") is True
    ]
    if valid:
        return "CAPTURED_VALID"
    if snapshots:
        return "BLOCKED_OR_INVALID"
    return "PENDING_CAPTURE"


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class EntityInventoryBuilder:
    """Accumulate repeated source references under stable entity IDs."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], dict[str, Any]] = {}

    def add(
        self,
        entity_type: str,
        entity_id: str,
        *,
        url: str | None = None,
        source_reference: dict[str, Any] | None = None,
        relationship: dict[str, Any] | None = None,
        display_name_raw: str | None = None,
        fields_available: Iterable[str] = (),
        fields_pending: Iterable[str] = (),
    ) -> None:
        entity_id = str(entity_id).strip()
        if not entity_type or not entity_id:
            return
        key = (entity_type, entity_id)
        record = self._records.setdefault(key, {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "_urls": {},
            "_sources": {},
            "_relationships": {},
            "_names": set(),
            "_fields_available": set(),
            "_fields_pending": set(),
        })
        if url:
            record["_urls"][url] = url
        if source_reference:
            record["_sources"][_stable_json(source_reference)] = source_reference
        if relationship:
            record["_relationships"][_stable_json(relationship)] = relationship
        if display_name_raw:
            record["_names"].add(display_name_raw)
        record["_fields_available"].update(field for field in fields_available if field)
        record["_fields_pending"].update(field for field in fields_pending if field)

    def records(self) -> list[dict[str, Any]]:
        """Return deterministic, deduplicated records with provenance intact."""
        output = []
        for key in sorted(self._records):
            record = self._records[key]
            output.append({
                "entity_type": record["entity_type"],
                "entity_id": record["entity_id"],
                "observed_urls": sorted(record["_urls"].values()),
                "source_reference_count": len(record["_sources"]),
                "source_references": [record["_sources"][item] for item in sorted(record["_sources"])],
                "relationships": [record["_relationships"][item] for item in sorted(record["_relationships"])],
                "display_names_raw": sorted(record["_names"]),
                "fields_available": sorted(record["_fields_available"]),
                "fields_pending": sorted(record["_fields_pending"]),
            })
        return output


def deduplicate_entity_references(references: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group references by (type, ID) while keeping distinct provenance."""
    builder = EntityInventoryBuilder()
    for item in references:
        builder.add(
            str(item.get("entity_type") or ""),
            str(item.get("entity_id") or ""),
            url=item.get("url"),
            source_reference=item.get("source_reference"),
            relationship=item.get("relationship"),
            display_name_raw=item.get("display_name_raw"),
            fields_available=item.get("fields_available", ()),
            fields_pending=item.get("fields_pending", ()),
        )
    return builder.records()


def build_position_code_catalog(
    memberships: Iterable[dict[str, Any]],
    profiles: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Cross-tab raw roster codes only against valid, locally captured profiles."""
    profile_by_id = {
        str(profile.get("player_id")): profile
        for profile in profiles
        if profile.get("player_id")
        and profile.get("position_raw")
        and profile.get("source", {}).get("access_status") == "VALID"
    }
    labels_by_code: dict[str, set[str]] = defaultdict(set)
    evidence_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for membership in memberships:
        player_id = str(membership.get("player_id") or "")
        profile = profile_by_id.get(player_id)
        code = str(membership.get("position_raw") or "").strip()
        if not code:
            continue
        if profile is None:
            labels_by_code.setdefault(code, set())
            continue
        label = str(profile["position_raw"]).strip()
        labels_by_code[code].add(label)
        evidence_by_code[code].append({
            "player_id": player_id,
            "position_code_raw": code,
            "position_label_raw": label,
            "membership_url": membership.get("url"),
            "membership_snapshot_sha256": membership.get("snapshot_sha256"),
            "profile_url": profile.get("source", {}).get("final_url"),
            "profile_snapshot_sha256": profile.get("source", {}).get("rendered_html_sha256"),
        })

    result = []
    for code in sorted(labels_by_code, key=lambda item: (not item.isdigit(), int(item) if item.isdigit() else item)):
        labels = sorted(labels_by_code[code])
        status = (
            "UNVERIFIED_RAW" if not labels
            else "AMBIGUOUS_RAW_LABELS" if len(labels) > 1
            else "VERIFIED_FOR_OBSERVED_PLAYER"
        )
        result.append({
            "position_code_raw": code,
            "position_labels_observed": labels,
            "status": status,
            "sample_count": len(evidence_by_code[code]),
            "evidence": sorted(evidence_by_code[code], key=lambda item: (item["player_id"], item["membership_snapshot_sha256"] or "")),
            "general_mapping_asserted": False,
        })
    return result
