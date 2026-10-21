"""Read-only verifier for semantic parsing of campaign discovery artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .campaign import MatchDetailCampaignLedger, MatchCampaignIntegrityError
from .semantic_parser import (
    MatchDetailParserError,
    MatchDetailObservation,
    PARSER_VERSION,
    parse_match_detail_html,
)


class CampaignArtifactError(MatchDetailParserError):
    """A campaign artifact, ledger, or provenance link failed verification."""


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_symlinks(path: Path) -> None:
    current = path.expanduser().absolute()
    while current != current.parent:
        if current.is_symlink():
            raise CampaignArtifactError(f"No se permiten symlinks en el artefacto: {current}")
        current = current.parent


def _read_canonical_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise CampaignArtifactError(f"{label} no es un archivo regular: {path}")
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CampaignArtifactError(f"No se puede leer {label}: {path}") from exc
    if not isinstance(value, dict) or raw != _canonical(value):
        raise CampaignArtifactError(f"{label} no es un objeto JSON canónico: {path}")
    return value, raw


def _same_candidate(candidate: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    fields = (
        "internal_id",
        "source_match_id",
        "group",
        "source_match_url",
        "source_generation_id",
        "source_generation_manifest_sha256",
        "source_capture_id",
        "source_snapshot_sha256",
        "source_matches_sha256",
        "matchday",
        "matchday_date",
        "source_match_date",
        "home_team_id",
        "away_team_id",
    )
    if any(candidate.get(key) != expected.get(key) for key in fields):
        return False
    candidate_result = candidate.get("reference_result") or candidate
    expected_result = expected.get("reference_result") or expected
    return (
        candidate_result.get("home_goals") == expected_result.get("home_goals")
        and candidate_result.get("away_goals") == expected_result.get("away_goals")
    )


def _validate_discovery_event_sequence(events: list[dict[str, Any]], *, operational_v2: bool = False) -> None:
    """Keep acquisition evidence valid while allowing versioned offline lifecycle events."""

    event_types = [event.get("event_type") for event in events]
    allowed_authorizations = {"AUTHORIZED", "AUTO_POLICY_AUTHORIZED"} if operational_v2 else {"AUTHORIZED"}
    if (
        len(event_types) < 3
        or event_types[1:3] != ["STARTED", "DISCOVERY_REVIEW_REQUIRED"]
        or event_types[0] not in allowed_authorizations
    ):
        raise CampaignArtifactError("La secuencia del candidato no es la adquisición esperada")
    if operational_v2:
        transitions = {
            None: {"VALIDATED", "VALIDATION_FAILED"},
            "AUTO_POLICY_REVALIDATED": {"DRAFT_PREPARED"},
            "AUTO_POLICY_REVALIDATION_FAILED": {
                "AUTO_POLICY_REVALIDATED", "AUTO_POLICY_REVALIDATION_FAILED",
            },
            "VALIDATION_FAILED": {
                "REVALIDATED", "REVALIDATION_FAILED",
                "AUTO_POLICY_REVALIDATED", "AUTO_POLICY_REVALIDATION_FAILED",
            },
            "REVALIDATION_FAILED": {
                "REVALIDATED", "REVALIDATION_FAILED",
                "AUTO_POLICY_REVALIDATED", "AUTO_POLICY_REVALIDATION_FAILED",
            },
            "VALIDATED": {"DRAFT_PREPARED"},
            "REVALIDATED": {"DRAFT_PREPARED"},
            "DRAFT_PREPARED": {"DOCUMENT_APPROVED", "AUTO_POLICY_APPROVED"},
            "DOCUMENT_APPROVED": {"PUBLISHED"},
            "AUTO_POLICY_APPROVED": {"PUBLISHED"},
            "PUBLISHED": {"REVIEW_COMPLETED"},
            "REVIEW_COMPLETED": set(),
        }
        state = None
        for event_type in event_types[3:]:
            if event_type not in transitions.get(state, set()):
                raise CampaignArtifactError(
                    "La secuencia de validación/publicación v2 no es válida"
                )
            state = event_type
    elif event_types[3:] not in ([], ["REVIEW_COMPLETED"]):
        raise CampaignArtifactError("La secuencia del candidato no es la adquisición esperada")


def _inventory_for_generation(
    verified_generation: Any, verified_inventory: dict[str, Any] | None,
) -> dict[str, Any]:
    """Reuse a verified inventory inside one publication read, bound to MATCH-00."""
    if verified_inventory is None:
        from .inventory import build_match_detail_inventory

        return build_match_detail_inventory(verified_generation)
    source_generation = verified_inventory.get("source_generation", {})
    if (
        not isinstance(source_generation, dict)
        or source_generation.get("generation_id") != verified_generation.generation_id
        or source_generation.get("manifest_sha256") != verified_generation.manifest_sha256
    ):
        raise CampaignArtifactError("El inventario reutilizado no corresponde a MATCH-00 verificado")
    return verified_inventory


def parse_campaign_saved_artifact(
    artifact_dir: Path,
    *,
    expected_match: Mapping[str, Any],
    verified_generation: Any,
    data_root: Path,
    parser_version: str = PARSER_VERSION,
    verified_inventory: dict[str, Any] | None = None,
) -> MatchDetailObservation:
    """Verify a campaign artifact and parse its original metadata without conversion.

    The campaign ledger and source inventory are treated as read-only evidence.
    This function never authorizes, promotes, or writes a campaign record.
    """

    _reject_symlinks(artifact_dir)
    artifact = artifact_dir.expanduser().absolute().resolve(strict=True)
    if not artifact.is_dir() or artifact.parent.name != "artifacts":
        raise CampaignArtifactError("La ruta no apunta a un artefacto de campaña")
    candidate_dir = artifact.parent.parent
    candidates_root = candidate_dir.parent
    campaign_root = candidates_root.parent
    campaigns_root = campaign_root.parent
    if (
        candidate_dir.name != expected_match.get("internal_id")
        or candidates_root.name != "candidates"
        or campaigns_root.name != "campaigns"
        or campaign_root.is_symlink()
    ):
        raise CampaignArtifactError("La ubicación del artefacto no sigue el layout de campaña")

    resolved_data_root = data_root.expanduser().resolve(strict=True)
    expected_campaigns_root = resolved_data_root / "matches" / "details" / "campaigns"
    if campaigns_root.resolve(strict=True) != expected_campaigns_root:
        raise CampaignArtifactError("La campaña debe estar bajo el almacén local de detalles")
    try:
        artifact.relative_to(expected_campaigns_root)
    except ValueError as exc:
        raise CampaignArtifactError("El artefacto está fuera del almacén configurado") from exc

    try:
        initial_campaign, _ = _read_canonical_json(campaign_root / "campaign.json", "campaign.json")
        operational_v2 = initial_campaign.get("schema_version") == "football_data_hub.match_detail_operational_campaign.v2"
        if operational_v2:
            from .operational_campaign import OperationalMatchCampaignLedger

            campaign, preflight, events = OperationalMatchCampaignLedger(campaigns_root).inspect_artifact_evidence(
                campaign_root, internal_id=str(expected_match.get("internal_id"))
            )
        else:
            ledger = MatchDetailCampaignLedger(campaigns_root)
            campaign, preflight, events = ledger.inspect_persisted_campaign_read_only(
                campaign_root, internal_id=str(expected_match.get("internal_id"))
            )
    except MatchCampaignIntegrityError as exc:
        raise CampaignArtifactError(f"El ledger de campaña no es íntegro: {exc}") from exc

    campaign_source = campaign.get("source")
    if not isinstance(campaign_source, dict):
        raise CampaignArtifactError("La campaña no contiene procedencia de origen")
    if (
        verified_generation.generation_id != campaign_source.get("generation_id")
        or verified_generation.manifest_sha256
        != campaign_source.get("generation_manifest_sha256")
    ):
        raise CampaignArtifactError("MATCH-00 no coincide con la generación declarada por la campaña")

    inventory_id = campaign_source.get("inventory_id")
    inventory_root = resolved_data_root / "matches" / "details" / "inventories" / str(inventory_id)
    _reject_symlinks(inventory_root)
    inventory, inventory_raw = _read_canonical_json(
        inventory_root / "inventory.json", "inventario de partidos"
    )
    inventory_manifest, inventory_manifest_raw = _read_canonical_json(
        inventory_root / "manifest.json", "manifiesto de inventario"
    )
    rebuilt_inventory = _inventory_for_generation(verified_generation, verified_inventory)
    if inventory_raw != _canonical(rebuilt_inventory):
        raise CampaignArtifactError("El inventario persistido no coincide con MATCH-00 reconstruido")
    expected_inventory_manifest = {
        "schema_version": "football_data_hub.match_detail_inventory_manifest.v1",
        "inventory_id": rebuilt_inventory["inventory_id"],
        "inventory_sha256": _sha(inventory_raw),
        "record_count": len(rebuilt_inventory["matches"]),
        "source_generation": {
            "generation_id": verified_generation.generation_id,
            "manifest_path": (
                f"matches/generations/{verified_generation.generation_id}/manifest.json"
            ),
            "manifest_sha256": verified_generation.manifest_sha256,
        },
    }
    if (
        inventory["inventory_id"] != inventory_id
        or _sha(inventory_raw) != campaign_source.get("inventory_sha256")
        or _sha(inventory_manifest_raw) != campaign_source.get("inventory_manifest_sha256")
        or inventory_manifest != expected_inventory_manifest
        or campaign.get("campaign_basis", {}).get("inventory_id") != inventory_id
        or campaign.get("campaign_basis", {}).get("inventory_sha256")
        != campaign_source.get("inventory_sha256")
    ):
        raise CampaignArtifactError("Inventario, manifiesto y campaña discrepan")

    candidates = campaign.get("candidates")
    if not isinstance(candidates, list):
        raise CampaignArtifactError("La campaña no contiene candidatos")
    matches = [
        item
        for item in rebuilt_inventory["matches"]
        if item.get("internal_id") == expected_match.get("internal_id")
    ]
    campaign_candidates = [
        item
        for item in candidates
        if isinstance(item, dict)
        and item.get("internal_id") == expected_match.get("internal_id")
    ]
    if (
        len(matches) != 1
        or len(campaign_candidates) != 1
        or not _same_candidate(campaign_candidates[0], matches[0])
        or not _same_candidate(matches[0], expected_match)
    ):
        raise CampaignArtifactError("Identidad del candidato no coincide con el inventario MATCH-00")

    expected_relative = (
        f"candidates/{expected_match['internal_id']}/artifacts/{artifact.name}"
    )
    report_candidates = [
        item
        for item in preflight.get("candidates", [])
        if item.get("internal_id") == expected_match.get("internal_id")
    ]
    if (
        len(report_candidates) != 1
        or report_candidates[0].get("acquisition_state") != "DISCOVERY_REVIEW_REQUIRED"
        or report_candidates[0].get("authorization_consumed") is not True
        or report_candidates[0].get("navigation_count") != 1
        or report_candidates[0].get("capture_promoted") is not False
        or preflight.get("capture_promotion_enabled") is not False
    ):
        raise CampaignArtifactError("El ledger no acredita una única adquisición no promovida")
    _validate_discovery_event_sequence(events, operational_v2=operational_v2)
    authorization = events[0].get("authorization")
    started = events[1]
    resolved = events[2]
    attempt_id = started.get("attempt_id")
    if (
        not isinstance(authorization, dict)
        or authorization.get("internal_id") != expected_match.get("internal_id")
        or authorization.get("source_match_id") != expected_match.get("source_match_id")
        or authorization.get("source_match_url") != expected_match.get("source_match_url")
        or authorization.get("maximum_navigations") != 1
        or authorization.get("automatic_retries") != 0
        or authorization.get("capture_promotion_enabled") is not False
        or started.get("attempt_id") != resolved.get("attempt_id")
        or started.get("authorization_id") != authorization.get("authorization_id")
        or started.get("requested_url") != expected_match.get("source_match_url")
        or resolved.get("http_status") != 200
        or resolved.get("final_url") != expected_match.get("source_match_url")
        or resolved.get("access_classification") != "VALID"
        or resolved.get("access_diagnostic") is not None
        or resolved.get("capture_promoted") is not False
        or resolved.get("semantic_validation_performed") is not False
    ):
        raise CampaignArtifactError("Autorización, intento o resolución no concuerdan con el partido")

    artifact_reference = resolved.get("artifact")
    if not isinstance(artifact_reference, dict) or artifact_reference.get(
        "artifact_relative_path"
    ) != expected_relative:
        raise CampaignArtifactError("El ledger no referencia este artefacto")
    manifest, manifest_raw = _read_canonical_json(artifact / "manifest.json", "manifiesto del artefacto")
    metadata, metadata_raw = _read_canonical_json(artifact / "metadata.json", "metadata de campaña")
    discovery, discovery_raw = _read_canonical_json(artifact / "discovery.json", "informe discovery")
    manifest_sha = _sha(manifest_raw)
    if (
        artifact_reference.get("manifest_sha256") != manifest_sha
        or artifact_reference.get("source_html_sha256")
        != manifest.get("files", {}).get("source.html", {}).get("sha256")
        or manifest.get("campaign_id") != campaign.get("campaign_id")
        or manifest.get("internal_id") != expected_match.get("internal_id")
        or manifest.get("artifact_id") != artifact.name
    ):
        raise CampaignArtifactError("Referencia de artefacto y manifiesto no coinciden")

    actual_files = {
        path.relative_to(artifact).as_posix()
        for path in artifact.rglob("*")
        if path.is_file()
    }
    if actual_files != {"manifest.json", "metadata.json", "discovery.json", "source.html"}:
        raise CampaignArtifactError("El artefacto tiene archivos inesperados o ausentes")
    html_path = artifact / "source.html"
    if html_path.is_symlink() or not html_path.is_file():
        raise CampaignArtifactError("source.html no es un archivo regular")
    html = html_path.read_bytes()
    html_sha = _sha(html)
    html_spec = manifest.get("files", {}).get("source.html", {})
    if (
        len(html) != html_spec.get("bytes")
        or html_sha != html_spec.get("sha256")
        or html_sha != artifact_reference.get("source_html_sha256")
        or html_sha != discovery.get("source_html_sha256")
        or len(html) != discovery.get("source_html_bytes")
    ):
        raise CampaignArtifactError("Hash/tamaño HTML no coincide entre artefacto, ledger y discovery")
    if (
        manifest.get("files", {}).get("metadata.json", {}).get("sha256") != _sha(metadata_raw)
        or manifest.get("files", {}).get("metadata.json", {}).get("bytes") != len(metadata_raw)
        or manifest.get("files", {}).get("discovery.json", {}).get("sha256")
        != _sha(discovery_raw)
        or manifest.get("files", {}).get("discovery.json", {}).get("bytes")
        != len(discovery_raw)
    ):
        raise CampaignArtifactError("Hashes/tamaños de metadata/discovery no coinciden")

    if (
        metadata.get("schema_version")
        != "football_data_hub.match_detail_campaign_discovery.v1"
        or metadata.get("campaign_id") != campaign.get("campaign_id")
        or metadata.get("internal_id") != expected_match.get("internal_id")
        or metadata.get("source_match_id") != expected_match.get("source_match_id")
        or metadata.get("navigation_attempt_id") != attempt_id
        or metadata.get("requested_url") != expected_match.get("source_match_url")
        or metadata.get("final_url") != expected_match.get("source_match_url")
        or metadata.get("http_status") != 200
        or metadata.get("access_classification") != "VALID"
        or metadata.get("access_diagnostic") is not None
        or metadata.get("challenge_detected") is not False
        or metadata.get("denial_detected") is not False
        or metadata.get("capture_promoted") is not False
        or metadata.get("semantic_identity_verified") is not False
        or metadata.get("page_title") != discovery.get("document_title_observed")
        or discovery.get("schema_version") != "football_data_hub.match_detail_discovery.v1"
        or discovery.get("semantic_mapping_confirmed") is not False
        or resolved.get("artifact", {}).get("artifact_id") != artifact.name
        or metadata.get("captured_at_utc") is None
    ):
        raise CampaignArtifactError("Metadata/diagnóstico de acceso no corresponde al intento")

    observation = parse_match_detail_html(
        html,
        expected_match=expected_match,
        metadata=metadata,
        discovery_id=artifact.name,
        inventory_id=str(inventory_id),
        parser_version=parser_version,
        verified_sha256=html_sha,
    )
    return observation
