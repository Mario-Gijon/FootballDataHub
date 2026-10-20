"""Offline verification and immutable recovery evidence for the MATCH-01B stop."""

from __future__ import annotations

import hashlib
import fcntl
import json
import os
import shutil
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
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


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _match_record(inventory: dict[str, Any], source_match_id: str) -> dict[str, Any]:
    matches = [
        item for item in inventory.get("matches", [])
        if isinstance(item, dict) and item.get("source_match_id") == source_match_id
    ]
    if len(matches) != 1:
        raise MatchCampaignAuthorizationError(
            f"El partido {source_match_id} no es único en el inventario verificado"
        )
    return matches[0]


def _verify_active_fixture_unchanged(
    historical_record: dict[str, Any],
    *,
    active_generation_root: Path,
    data_root: Path,
) -> dict[str, Any]:
    active_generation = load_verified_match_generation(
        active_generation_root, data_root=data_root
    )
    active_inventory = build_match_detail_inventory(active_generation)
    active_record = _match_record(active_inventory, "272582")
    sporting_fields = (
        "internal_id", "source_match_id", "source_match_url", "season",
        "competition", "group", "matchday", "source_match_date",
        "home_team_id", "away_team_id", "reference_result",
    )
    if any(historical_record.get(field) != active_record.get(field) for field in sporting_fields):
        raise MatchCampaignAuthorizationError(
            "El fixture histórico 272582 difiere del catálogo activo; no se crea candidato"
        )
    return {
        "generation_id": active_generation.generation_id,
        "generation_manifest_sha256": active_generation.manifest_sha256,
    }


def _existing_recovery_bundle(
    target: Path,
    *,
    expected_candidate_raw: bytes,
) -> dict[str, Any] | None:
    if not target.exists():
        return None
    if target.is_symlink() or not target.is_dir() or any(
        item.is_symlink() for item in target.rglob("*")
    ):
        raise MatchCampaignAuthorizationError("El candidato de recuperación existente no es regular")
    required = {"candidate.json", "receipt.json", "manifest.json"}
    if {item.name for item in target.iterdir()} != required:
        raise MatchCampaignAuthorizationError("El candidato de recuperación tiene archivos inesperados")
    candidate_raw = _regular_file(target / "candidate.json", "candidato de recuperación")
    receipt_raw = _regular_file(target / "receipt.json", "recibo de recuperación")
    manifest_raw = _regular_file(target / "manifest.json", "manifiesto de recuperación")
    try:
        receipt = json.loads(receipt_raw)
        manifest = json.loads(manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatchCampaignAuthorizationError("El bundle de recuperación no contiene JSON válido") from exc
    expected_files = {
        "candidate.json": {"sha256": _sha(expected_candidate_raw), "bytes": len(expected_candidate_raw)},
        "receipt.json": {"sha256": _sha(receipt_raw), "bytes": len(receipt_raw)},
    }
    if (
        candidate_raw != expected_candidate_raw
        or manifest != {
            "schema_version": "football_data_hub.match_detail_legacy_recovery_manifest.v1",
            "recovery_id": target.name,
            "files": expected_files,
        }
        or manifest_raw != _canonical(manifest)
        or receipt.get("schema_version")
        != "football_data_hub.match_detail_legacy_recovery_receipt.v1"
        or receipt.get("recovery_id") != target.name
        or receipt.get("candidate_sha256") != _sha(candidate_raw)
        or receipt.get("receipt_sha256") != _sha(_canonical({
            key: value for key, value in receipt.items() if key != "receipt_sha256"
        }))
    ):
        raise MatchCampaignAuthorizationError("Los hashes del candidato de recuperación no coinciden")
    return {
        "recovery_id": target.name,
        "path": str(target),
        "candidate_sha256": _sha(candidate_raw),
        "receipt_sha256": receipt["receipt_sha256"],
        "manifest_sha256": _sha(manifest_raw),
        "status": receipt["status"],
    }


def verify_historical_recovery_candidate(
    store_root: Path,
    *,
    data_root: Path,
    expected_match: dict[str, Any],
    active_generation_id: str | None,
    active_generation_manifest_sha256: str | None,
) -> dict[str, Any] | None:
    """Verify an offline recovery receipt against its original immutable inputs.

    Returns ``None`` when no recovery has been prepared. A valid receipt only
    changes the legacy stop to a review-pending evidence state; it does not
    authorize acquisition or publication.
    """

    recovery_root = store_root / "recoveries"
    if not recovery_root.exists():
        return None
    _reject_symlink_path(recovery_root, "Recuperaciones MATCH")
    bundles = sorted(
        item for item in recovery_root.iterdir()
        if item.name.startswith("legacy-recovery-272582-")
    )
    if not bundles:
        return None
    if len(bundles) != 1:
        raise MatchCampaignAuthorizationError(
            "Hay varios candidatos de recuperación para 272582; se requiere revisión de integridad"
        )
    target = bundles[0]
    if target.is_symlink() or not target.is_dir() or any(
        item.is_symlink() for item in target.rglob("*")
    ):
        raise MatchCampaignAuthorizationError("El bundle de recuperación no es regular")
    if {item.name for item in target.iterdir()} != {
        "candidate.json", "receipt.json", "manifest.json"
    }:
        raise MatchCampaignAuthorizationError("El bundle de recuperación está incompleto")
    candidate_raw = _regular_file(target / "candidate.json", "candidato de recuperación")
    receipt_raw = _regular_file(target / "receipt.json", "recibo de recuperación")
    manifest_raw = _regular_file(target / "manifest.json", "manifiesto de recuperación")
    try:
        candidate = json.loads(candidate_raw)
        receipt = json.loads(receipt_raw)
        manifest = json.loads(manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatchCampaignAuthorizationError("El bundle de recuperación no contiene JSON válido") from exc
    evidence = candidate.get("evidence") if isinstance(candidate, dict) else None
    candidate_sha256 = _sha(candidate_raw)
    expected_manifest = {
        "schema_version": "football_data_hub.match_detail_legacy_recovery_manifest.v1",
        "recovery_id": target.name,
        "files": {
            "candidate.json": {"sha256": candidate_sha256, "bytes": len(candidate_raw)},
            "receipt.json": {"sha256": _sha(receipt_raw), "bytes": len(receipt_raw)},
        },
    }
    if (
        not isinstance(evidence, dict)
        or candidate.get("schema_version")
        != "football_data_hub.match_detail_legacy_recovery_candidate.v1"
        or candidate.get("status") != "VALIDATED_PENDING_EXPLICIT_REVIEW"
        or candidate.get("publication_eligible") is not False
        or candidate.get("human_approval_required") is not True
        or candidate.get("source_access_status_original") != "INVALID_CONTENT"
        or candidate.get("source_promotion_eligible_original") is not False
        or candidate.get("source_kind") != "offline_revalidation_of_discovery_only_artifact"
        or candidate.get("parser_version") != PARSER_VERSION
        or evidence.get("source_match_id") != "272582"
        or evidence.get("internal_id") != "pf-2026-27-group-ii-bdfutbol-272582"
        or evidence.get("source_html_sha256") != HISTORICAL_272582_HTML_SHA256
        or expected_match.get("source_match_id") != "272582"
        or expected_match.get("internal_id") != "pf-2026-27-group-ii-bdfutbol-272582"
        or candidate.get("active_fixture")
        != (
            {
                "generation_id": active_generation_id,
                "generation_manifest_sha256": active_generation_manifest_sha256,
            }
            if active_generation_id is not None
            and active_generation_manifest_sha256 is not None
            else None
        )
        or manifest != expected_manifest
        or manifest_raw != _canonical(manifest)
        or receipt.get("schema_version")
        != "football_data_hub.match_detail_legacy_recovery_receipt.v1"
        or receipt.get("recovery_id") != target.name
        or receipt.get("status") != "VALIDATED_PENDING_EXPLICIT_REVIEW"
        or receipt.get("candidate_sha256") != candidate_sha256
        or receipt.get("source_html_sha256") != evidence.get("source_html_sha256")
        or receipt.get("artifact_manifest_sha256") != evidence.get("artifact_manifest_sha256")
        or receipt.get("checkpoint_sha256") != evidence.get("checkpoint_sha256")
        or receipt.get("diagnostic_sha256") != evidence.get("diagnostic_sha256")
        or receipt.get("source_generation_id") != evidence.get("generation_id")
        or receipt.get("source_generation_manifest_sha256")
        != evidence.get("generation_manifest_sha256")
        or receipt.get("active_generation") != candidate.get("active_fixture")
        or receipt.get("parser_version") != PARSER_VERSION
        or receipt.get("semantic_valid") is not True
        or receipt.get("all_semantic_checks_passed") is not True
        or receipt.get("source_access_status_preserved") != "INVALID_CONTENT"
        or receipt.get("publication_status") != "NOT_PUBLISHED"
        or receipt.get("human_approval_required") is not True
        or receipt.get("original_evidence_sha256") != _sha(_canonical(evidence))
        or receipt.get("receipt_sha256")
        != _sha(_canonical({key: value for key, value in receipt.items() if key != "receipt_sha256"}))
    ):
        raise MatchCampaignAuthorizationError("La evidencia del recibo de recuperación no coincide")

    checkpoint_path = store_root / "states" / f"{evidence['inventory_id']}.json"
    checkpoint_raw = _regular_file(checkpoint_path, "checkpoint original")
    if _sha(checkpoint_raw) != receipt["checkpoint_sha256"]:
        raise MatchCampaignAuthorizationError("El checkpoint original cambió tras la recuperación")
    try:
        checkpoint = json.loads(checkpoint_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatchCampaignAuthorizationError("El checkpoint original no es JSON válido") from exc
    original_diagnostics = [
        item for item in checkpoint.get("diagnostics", [])
        if isinstance(item, dict)
        and item.get("navigation_attempt_id") == evidence.get("original_attempt_id")
    ]
    if (
        checkpoint.get("status") != "stopped"
        or checkpoint.get("inventory_id") != evidence.get("inventory_id")
        or len(original_diagnostics) != 1
        or original_diagnostics[0].get("source_match_id") != "272582"
        or original_diagnostics[0].get("error_code") != "IDENTITY_OR_CONTENT_UNVERIFIED"
        or original_diagnostics[0].get("stop_acquisition") is not True
        or _sha(_canonical(original_diagnostics[0])) != receipt["diagnostic_sha256"]
    ):
        raise MatchCampaignAuthorizationError("El incidente histórico original no coincide")

    historical_generation_root = (
        data_root / "matches" / "generations" / evidence["generation_id"]
    )
    _reject_symlink_path(historical_generation_root, "Generación histórica")
    historical_manifest_path = historical_generation_root / "manifest.json"
    if historical_manifest_path.is_file() and not historical_manifest_path.is_symlink():
        historical_manifest_raw = _regular_file(
            historical_manifest_path, "manifiesto de generación histórica"
        )
        if _sha(historical_manifest_raw) != evidence.get("generation_manifest_sha256"):
            raise MatchCampaignAuthorizationError("La generación histórica de la recuperación cambió")
        try:
            historical_manifest = json.loads(historical_manifest_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MatchCampaignAuthorizationError("El manifiesto histórico no es JSON válido") from exc
        if historical_manifest.get("generation_id") != evidence.get("generation_id"):
            raise MatchCampaignAuthorizationError("El manifiesto histórico identifica otra generación")
        # The original receipt binds this manifest; source identity and all
        # sporting fields are compared with the active, already verified row.
        historical_match = dict(expected_match)
    else:
        # Keep the stricter generation loader for synthetic/offline fixtures and
        # fail closed if the referenced historical generation is unavailable.
        historical_generation = load_verified_match_generation(
            historical_generation_root, data_root=data_root
        )
        if (
            historical_generation.generation_id != evidence.get("generation_id")
            or historical_generation.manifest_sha256
            != evidence.get("generation_manifest_sha256")
        ):
            raise MatchCampaignAuthorizationError("La generación histórica de la recuperación cambió")
        historical_inventory = build_match_detail_inventory(historical_generation)
        historical_match = _match_record(historical_inventory, "272582")
        if any(
            historical_match.get(field) != expected_match.get(field)
            for field in (
                "internal_id", "source_match_id", "source_match_url", "season",
                "competition", "group", "matchday", "source_match_date",
                "home_team_id", "away_team_id", "reference_result",
            )
        ):
            raise MatchCampaignAuthorizationError(
                "El partido de la generación histórica difiere del catálogo activo"
            )
    observed_source = candidate.get("observation", {}).get("source", {})
    if (
        observed_source.get("source_generation_id") != evidence.get("generation_id")
        or not isinstance(observed_source.get("source_capture_id"), str)
        or not observed_source.get("source_capture_id")
    ):
        raise MatchCampaignAuthorizationError("El candidato no conserva su captura de origen")
    historical_match["source_generation_id"] = evidence["generation_id"]
    historical_match["source_generation_manifest_sha256"] = evidence["generation_manifest_sha256"]
    historical_match["source_capture_id"] = observed_source["source_capture_id"]

    artifact_dir = store_root / "diagnostics" / evidence["inventory_id"] / evidence["artifact_id"]
    if evidence.get("artifact_relative_path") != artifact_dir.relative_to(store_root).as_posix():
        raise MatchCampaignAuthorizationError("La ruta de evidencia del HTML es inconsistente")
    _reject_symlink_path(artifact_dir, "Artefacto histórico")
    artifact_manifest_raw = _regular_file(artifact_dir / "manifest.json", "manifiesto histórico")
    source_html_raw = _regular_file(artifact_dir / "raw" / "source.html", "HTML histórico")
    if (
        _sha(artifact_manifest_raw) != receipt["artifact_manifest_sha256"]
        or _sha(source_html_raw) != receipt["source_html_sha256"]
    ):
        raise MatchCampaignAuthorizationError("Los hashes del artefacto histórico cambiaron")
    observation = parse_saved_artifact(artifact_dir, expected_match=historical_match)
    if (
        observation.validation.semantic_valid is not True
        or observation.validation.errors
        or any(not check.passed for check in observation.validation.checks)
        or observation.source.artifact_access_status != "INVALID_CONTENT"
        or observation.source.promotion_eligible is not False
        or observation.source.source_match_id != "272582"
        or observation.source.source_html_sha256 != HISTORICAL_272582_HTML_SHA256
        or _canonical(asdict(observation)) != _canonical(candidate.get("observation"))
        or _canonical(asdict(observation.validation))
        != _canonical(candidate.get("semantic_validation"))
    ):
        raise MatchCampaignAuthorizationError("La revalidación del parser ya no coincide con el candidato")
    return {
        "source_match_id": "272582",
        "status": "VALIDATED_PENDING_EXPLICIT_REVIEW",
        "recovery_id": target.name,
        "candidate_sha256": candidate_sha256,
        "receipt_sha256": receipt["receipt_sha256"],
        "publication_status": "NOT_PUBLISHED",
    }


def prepare_historical_recovery_candidate(
    plan: dict[str, Any],
    *,
    data_root: Path,
    generation_root: Path,
    inventory_dir: Path,
    store_root: Path,
    active_generation_root: Path | None = None,
    verified_at_utc: datetime | None = None,
) -> dict[str, Any]:
    """Create a hash-bound, immutable review candidate from the saved HTML only.

    The original INVALID_CONTENT checkpoint and discovery artifact are read-only
    inputs. The derived candidate is explicitly non-publishable until a separate
    human approval and the existing publication contract accept it.
    """

    evidence = verify_historical_stop_evidence(
        plan,
        data_root=data_root,
        generation_root=generation_root,
        inventory_dir=inventory_dir,
        store_root=store_root,
    )
    generation = load_verified_match_generation(generation_root, data_root=data_root)
    inventory = build_match_detail_inventory(generation)
    expected_match = _match_record(inventory, "272582")
    active_fixture = (
        _verify_active_fixture_unchanged(
            expected_match,
            active_generation_root=active_generation_root,
            data_root=data_root,
        )
        if active_generation_root is not None
        else None
    )
    artifact_dir = store_root / "diagnostics" / evidence["inventory_id"] / evidence["artifact_id"]
    observation = parse_saved_artifact(artifact_dir, expected_match=expected_match)
    failed_checks = [check.check for check in observation.validation.checks if not check.passed]
    if (
        observation.validation.semantic_valid is not True
        or observation.validation.errors
        or failed_checks
        or observation.source.source_html_sha256 != evidence["source_html_sha256"]
        or observation.source.artifact_access_status != "INVALID_CONTENT"
        or observation.source.promotion_eligible is not False
    ):
        raise MatchCampaignAuthorizationError(
            "La revalidación offline no supera todas las comprobaciones semánticas"
        )

    candidate_body = {
        "schema_version": "football_data_hub.match_detail_legacy_recovery_candidate.v1",
        "source_kind": "offline_revalidation_of_discovery_only_artifact",
        "status": "VALIDATED_PENDING_EXPLICIT_REVIEW",
        "publication_eligible": False,
        "human_approval_required": True,
        "source_access_status_original": "INVALID_CONTENT",
        "source_promotion_eligible_original": False,
        "evidence": evidence,
        "active_fixture": active_fixture,
        "parser_version": PARSER_VERSION,
        "semantic_validation": asdict(observation.validation),
        "observation": asdict(observation),
    }
    candidate_raw = _canonical(candidate_body)
    candidate_sha256 = _sha(candidate_raw)
    recovery_id = f"legacy-recovery-272582-{candidate_sha256[:16]}"
    recovery_root = store_root / "recoveries"
    _reject_symlink_path(recovery_root, "Recuperaciones MATCH")
    recovery_root.mkdir(parents=True, exist_ok=True)
    lock_path = recovery_root / ".recovery.lock"
    if lock_path.is_symlink():
        raise MatchCampaignAuthorizationError("El bloqueo de recuperación no puede ser symlink")
    verified_at_utc = verified_at_utc or datetime.now(timezone.utc)
    if verified_at_utc.tzinfo is None:
        raise MatchCampaignAuthorizationError("La hora de revalidación debe incluir zona horaria")
    target = recovery_root / recovery_id

    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        existing = _existing_recovery_bundle(target, expected_candidate_raw=candidate_raw)
        if existing is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            return existing
        receipt_body = {
            "schema_version": "football_data_hub.match_detail_legacy_recovery_receipt.v1",
            "recovery_id": recovery_id,
            "status": "VALIDATED_PENDING_EXPLICIT_REVIEW",
            "verified_at_utc": verified_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "original_evidence_sha256": _sha(_canonical(evidence)),
            "candidate_sha256": candidate_sha256,
            "source_html_sha256": evidence["source_html_sha256"],
            "artifact_manifest_sha256": evidence["artifact_manifest_sha256"],
            "checkpoint_sha256": evidence["checkpoint_sha256"],
            "diagnostic_sha256": evidence["diagnostic_sha256"],
            "source_generation_id": evidence["generation_id"],
            "source_generation_manifest_sha256": evidence["generation_manifest_sha256"],
            "active_generation": active_fixture,
            "parser_version": PARSER_VERSION,
            "semantic_valid": True,
            "all_semantic_checks_passed": True,
            "source_access_status_preserved": "INVALID_CONTENT",
            "publication_status": "NOT_PUBLISHED",
            "human_approval_required": True,
        }
        receipt_body["receipt_sha256"] = _sha(_canonical(receipt_body))
        receipt_raw = _canonical(receipt_body)
        manifest = {
            "schema_version": "football_data_hub.match_detail_legacy_recovery_manifest.v1",
            "recovery_id": recovery_id,
            "files": {
                "candidate.json": {"sha256": candidate_sha256, "bytes": len(candidate_raw)},
                "receipt.json": {"sha256": _sha(receipt_raw), "bytes": len(receipt_raw)},
            },
        }
        manifest_raw = _canonical(manifest)
        staging = Path(tempfile.mkdtemp(prefix=".legacy-recovery-", dir=recovery_root))
        try:
            for name, content in (
                ("candidate.json", candidate_raw),
                ("receipt.json", receipt_raw),
                ("manifest.json", manifest_raw),
            ):
                with (staging / name).open("xb") as output:
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
            _fsync_directory(staging)
            os.rename(staging, target)
            _fsync_directory(recovery_root)
        except FileExistsError:
            existing = _existing_recovery_bundle(target, expected_candidate_raw=candidate_raw)
            if existing is None:
                raise MatchCampaignAuthorizationError("No se pudo crear el bundle de recuperación")
            return existing
        finally:
            if staging.exists():
                shutil.rmtree(staging)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    return {
        "recovery_id": recovery_id,
        "path": str(target),
        "candidate_sha256": candidate_sha256,
        "receipt_sha256": receipt_body["receipt_sha256"],
        "manifest_sha256": _sha(manifest_raw),
        "status": receipt_body["status"],
    }


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
