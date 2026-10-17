"""Read-only verification of the historical MATCH-01B stop evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .campaign import MatchCampaignAuthorizationError, _campaign_spec
from .inventory import build_match_detail_inventory, load_verified_match_generation
from .semantic_parser import PARSER_VERSION, parse_saved_artifact

HISTORICAL_272582_HTML_SHA256 = (
    "9242edad00b43a4e83c649ddad006edb0d1172e0d88640082312a0fe1cf16997"
)


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _regular_file(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise MatchCampaignAuthorizationError(f"{label} ausente o no es archivo regular: {path}")
    return path.read_bytes()


def _reject_symlink_path(path: Path, label: str) -> None:
    current = path.expanduser().absolute()
    while current != current.parent:
        if current.is_symlink():
            raise MatchCampaignAuthorizationError(f"{label} contiene symlink: {current}")
        current = current.parent


def verify_historical_stop_evidence(
    plan: dict[str, Any],
    *,
    data_root: Path,
    generation_root: Path,
    inventory_dir: Path,
    store_root: Path,
) -> dict[str, Any]:
    """Rebuild and verify 272582 from its source generation, checkpoint and artifact.

    This is strictly offline and read-only. Paths are derived from the verified
    inventory/checkpoint references; callers cannot substitute arbitrary HTML
    bytes plus a self-asserted digest.
    """

    spec = _campaign_spec(plan)
    source = spec["source"]
    inventory_id = source["inventory_id"]
    generation = load_verified_match_generation(generation_root, data_root=data_root)
    if (
        generation.generation_id != source["generation_id"]
        or generation.manifest_sha256 != source["generation_manifest_sha256"]
    ):
        raise MatchCampaignAuthorizationError("La generación verificada no coincide con el plan")
    rebuilt = build_match_detail_inventory(generation)
    if rebuilt["inventory_id"] != inventory_id:
        raise MatchCampaignAuthorizationError("El inventario reconstruido no coincide")

    _reject_symlink_path(inventory_dir, "Inventario")
    _reject_symlink_path(store_root, "Almacén MATCH")
    inventory_root = inventory_dir.expanduser().resolve(strict=True)
    try:
        inventory_root.relative_to(data_root.expanduser().resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise MatchCampaignAuthorizationError(
            "El inventario debe estar bajo data_root verificado"
        ) from exc
    inventory_path = inventory_dir / "inventory.json"
    manifest_path = inventory_dir / "manifest.json"
    inventory_raw = _regular_file(inventory_path, "inventory.json")
    inventory_manifest_raw = _regular_file(manifest_path, "manifest.json")
    if (
        inventory_dir.is_symlink()
        or inventory_dir.name != inventory_id
        or inventory_raw != _canonical(rebuilt)
        or _sha(inventory_raw) != source["inventory_sha256"]
        or _sha(inventory_manifest_raw) != source["inventory_manifest_sha256"]
    ):
        raise MatchCampaignAuthorizationError("Inventario persistido/manifiesto no íntegro")
    try:
        inventory_manifest = json.loads(inventory_manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatchCampaignAuthorizationError("Manifiesto del inventario ilegible") from exc
    expected_inventory_manifest = {
        "schema_version": "football_data_hub.match_detail_inventory_manifest.v1",
        "inventory_id": inventory_id,
        "inventory_sha256": _sha(inventory_raw),
        "record_count": len(rebuilt["matches"]),
        "source_generation": rebuilt.get("source_generation"),
    }
    if inventory_manifest != expected_inventory_manifest or inventory_manifest_raw != _canonical(
        expected_inventory_manifest
    ):
        raise MatchCampaignAuthorizationError("El manifiesto del inventario no coincide")

    matches = [
        item
        for item in rebuilt["matches"]
        if item.get("source_match_id") == "272582"
    ]
    if len(matches) != 1:
        raise MatchCampaignAuthorizationError("El partido histórico no es único en el inventario")
    expected_match = matches[0]
    if (
        expected_match.get("internal_id") != "pf-2026-27-group-ii-bdfutbol-272582"
        or expected_match.get("source_match_url")
        != "https://www.bdfutbol.com/es/p/p.php?id=272582"
    ):
        raise MatchCampaignAuthorizationError("Identidad del partido histórico discordante")

    checkpoint_path = store_root / "states" / f"{inventory_id}.json"
    checkpoint_raw = _regular_file(checkpoint_path, "checkpoint MATCH-01B")
    legacy = spec["legacy_stop_review_reference"]
    if _sha(checkpoint_raw) != legacy["checkpoint_sha256"]:
        raise MatchCampaignAuthorizationError("El hash actual del checkpoint cambió")
    try:
        checkpoint = json.loads(checkpoint_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatchCampaignAuthorizationError("El checkpoint histórico no es JSON legible") from exc
    if (
        checkpoint.get("schema_version") != "football_data_hub.match_detail_state.v1"
        or checkpoint.get("inventory_id") != inventory_id
        or checkpoint.get("status") != "stopped"
        or checkpoint.get("revision") != legacy["checkpoint_revision"]
        or checkpoint.get("active_navigation_attempt_id") is not None
    ):
        raise MatchCampaignAuthorizationError("El estado/revisión del checkpoint no coincide")

    expected_diagnostic = legacy["original_diagnostic"]
    diagnostics = checkpoint.get("diagnostics")
    if not isinstance(diagnostics, list):
        raise MatchCampaignAuthorizationError("El checkpoint no conserva diagnósticos")
    matched_diagnostics = [
        item
        for item in diagnostics
        if isinstance(item, dict)
        and item.get("navigation_attempt_id") == legacy["original_attempt_id"]
    ]
    if matched_diagnostics != [expected_diagnostic]:
        raise MatchCampaignAuthorizationError("El diagnóstico histórico no coincide byte a byte")

    artifacts = checkpoint.get("discovery_artifacts")
    if not isinstance(artifacts, list):
        raise MatchCampaignAuthorizationError("El checkpoint no conserva referencias al artefacto")
    artifact_refs = [
        item
        for item in artifacts
        if isinstance(item, dict)
        and item.get("navigation_attempt_id") == legacy["original_attempt_id"]
    ]
    if len(artifact_refs) != 1:
        raise MatchCampaignAuthorizationError("La referencia del artefacto histórico no es única")
    artifact_ref = artifact_refs[0]
    expected_artifact_id = artifact_ref.get("discovery_id")
    if (
        artifact_ref.get("internal_id") != expected_match["internal_id"]
        or artifact_ref.get("source_html_sha256")
        != HISTORICAL_272582_HTML_SHA256
        or not isinstance(expected_artifact_id, str)
    ):
        raise MatchCampaignAuthorizationError("La referencia histórica del HTML no coincide")
    attempts = checkpoint.get("navigation_attempts")
    matching_attempts = [
        item
        for item in attempts or []
        if isinstance(item, dict) and item.get("attempt_id") == legacy["original_attempt_id"]
    ]
    if (
        len(matching_attempts) != 1
        or matching_attempts[0].get("inventory_id") != inventory_id
        or matching_attempts[0].get("source_match_id") != "272582"
        or matching_attempts[0].get("requested_url")
        != "https://www.bdfutbol.com/es/p/p.php?id=272582"
        or matching_attempts[0].get("status") != "resolved"
        or matching_attempts[0].get("resolution_evidence") != "diagnostic"
        or matching_attempts[0].get("outcome_code") != "IDENTITY_OR_CONTENT_UNVERIFIED"
    ):
        raise MatchCampaignAuthorizationError("El intento original no conserva su diagnóstico")

    artifact_dir = (
        store_root
        / "diagnostics"
        / inventory_id
        / expected_artifact_id
    )
    _reject_symlink_path(artifact_dir, "Artefacto histórico")
    manifest_raw = _regular_file(artifact_dir / "manifest.json", "manifiesto del artefacto histórico")
    if _sha(manifest_raw) != artifact_ref.get("manifest_sha256"):
        raise MatchCampaignAuthorizationError("Hash del manifiesto del artefacto no coincide")
    observation = parse_saved_artifact(artifact_dir, expected_match=expected_match)
    if (
        observation.source.source_match_id != "272582"
        or observation.validation.semantic_valid is not True
        or observation.validation.promotion_eligible is not False
        or observation.source.promotion_eligible is not False
        or observation.source.source_html_sha256 != artifact_ref["source_html_sha256"]
        or observation.source.artifact_access_status != "INVALID_CONTENT"
    ):
        raise MatchCampaignAuthorizationError(
            "El parser semántico no confirma la identidad histórica discovery-only"
        )

    return {
        "evidence_schema": "football_data_hub.match_detail_legacy_stop_evidence.v1",
        "inventory_id": inventory_id,
        "generation_id": generation.generation_id,
        "generation_manifest_sha256": generation.manifest_sha256,
        "source_match_id": "272582",
        "internal_id": expected_match["internal_id"],
        "original_attempt_id": legacy["original_attempt_id"],
        "checkpoint_sha256": _sha(checkpoint_raw),
        "checkpoint_revision": checkpoint["revision"],
        "diagnostic_sha256": legacy["original_diagnostic_sha256"],
        "artifact_relative_path": artifact_dir.relative_to(store_root).as_posix(),
        "artifact_id": expected_artifact_id,
        "artifact_manifest_sha256": _sha(manifest_raw),
        "source_html_sha256": observation.source.source_html_sha256,
        "parser_version": PARSER_VERSION,
        "semantic_valid": True,
        "promotion_eligible": False,
    }
