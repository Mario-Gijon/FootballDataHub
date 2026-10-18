"""Explicit, read-only verification and append-only closure of published discovery reviews."""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from football_data_hub_api.match_details_dataset import (
    load_published_match_details,
)
from football_data_hub_api.match_results_dataset import load_match_results_dataset
from football_data_hub_api.player_dataset import load_player_directory

from .campaign import (
    MatchCampaignAuthorizationError,
    MatchCampaignIntegrityError,
    MatchDetailCampaignLedger,
    _campaign_spec,
    _is_sha,
    _reject_symlink_path,
    review_completion_confirmation,
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise MatchCampaignIntegrityError(f"{label} no es un archivo regular")
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatchCampaignIntegrityError(f"No se puede leer {label}") from exc
    if not isinstance(value, dict) or raw != _canonical(value):
        raise MatchCampaignIntegrityError(f"{label} no es JSON canónico")
    return value, raw


@contextmanager
def _published_index_read_lock(published_root: Path) -> Iterator[Path]:
    root = published_root.expanduser().absolute()
    _reject_symlink_path(root)
    if root.is_symlink() or not root.is_dir():
        raise MatchCampaignIntegrityError("La raíz publicada no es un directorio regular")
    lock_path = root / ".publication.lock"
    if lock_path.is_symlink() or not lock_path.is_file():
        raise MatchCampaignIntegrityError("Falta el lock del índice de publicación")
    with lock_path.open("rb") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MatchCampaignAuthorizationError(
                "El índice de publicación está cambiando; reintente la revisión manualmente"
            ) from exc
        try:
            yield root
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _active_publication_evidence(
    *,
    published_root: Path,
    internal_id: str,
    source_match_id: str,
    group: str,
    source_capture_id: str,
    campaign_id: str,
    inventory_id: str,
    source_generation_id: str,
    source_generation_manifest_sha256: str,
    attempt_id: str,
    artifact_id: str,
    artifact_manifest_sha256: str,
    source_html_sha256: str,
    verified_document: Any,
) -> dict[str, Any]:
    root = published_root.expanduser().absolute()
    index, _ = _read_json(root / "index.json", "Índice publicado")
    if (
        index.get("schema_version") != "football_data_hub.match_detail_publication_index.v1"
        or set(index) != {"schema_version", "publications"}
        or not isinstance(index.get("publications"), list)
    ):
        raise MatchCampaignIntegrityError("El índice publicado tiene un esquema inválido")
    matches = [
        item
        for item in index["publications"]
        if isinstance(item, dict) and item.get("internal_id") == internal_id
    ]
    if len(matches) != 1:
        raise MatchCampaignAuthorizationError(
            "El candidato no tiene exactamente una publicación activa aprobada"
        )
    indexed = matches[0]
    publication_id = indexed.get("publication_id")
    if (
        not isinstance(publication_id, str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,95}", publication_id)
        or indexed.get("package_path") != f"packages/{publication_id}"
        or not _is_sha(indexed.get("manifest_sha256"))
    ):
        raise MatchCampaignIntegrityError("La referencia publicada es inválida")
    package = root / "packages" / publication_id
    if package.is_symlink() or not package.is_dir():
        raise MatchCampaignIntegrityError("Falta el paquete publicado")
    manifest, manifest_raw = _read_json(package / "manifest.json", "Manifiesto publicado")
    approval, approval_raw = _read_json(package / "approval.json", "Aprobación publicada")
    details, details_raw = _read_json(package / "details.json", "Documento publicado")

    expected_manifest_identity = {
        "publication_id": publication_id,
        "internal_id": internal_id,
        "source_match_id": source_match_id,
        "group": group,
        "source_capture_id": source_capture_id,
        "campaign_id": campaign_id,
        "inventory_id": inventory_id,
        "source_generation_id": source_generation_id,
        "source_generation_manifest_sha256": source_generation_manifest_sha256,
        "navigation_attempt_id": attempt_id,
        "artifact_id": artifact_id,
        "artifact_manifest_sha256": artifact_manifest_sha256,
        "source_html_sha256": source_html_sha256,
    }
    if (
        _sha(manifest_raw) != indexed.get("manifest_sha256")
        or manifest.get("schema_version")
        != "football_data_hub.match_detail_campaign_publication.v1"
        or any(manifest.get(key) != value for key, value in expected_manifest_identity.items())
        or not _is_sha(manifest.get("details_sha256"))
        or not _is_sha(manifest.get("approval_sha256"))
        or _sha(approval_raw) != manifest.get("approval_sha256")
        or _sha(details_raw) != manifest.get("details_sha256")
        or approval.get("schema_version")
        != "football_data_hub.match_detail_campaign_approval.v1"
        or approval.get("publication_status") != "approved"
        or any(approval.get(key) != value for key, value in expected_manifest_identity.items())
        or approval.get("details_sha256") != manifest.get("details_sha256")
        or not isinstance(approval.get("approved_by"), str)
        or not approval["approved_by"].strip()
        or verified_document is None
        or getattr(verified_document, "publication_status", None) != "approved"
        or _canonical(verified_document.model_dump(mode="json")) != details_raw
    ):
        raise MatchCampaignIntegrityError(
            "La aprobación o el paquete no coincide con el intento y artefacto revisados"
        )
    return {
        "schema_version": "football_data_hub.match_detail_campaign_review_completion_evidence.v1",
        **expected_manifest_identity,
        "publication_manifest_sha256": _sha(manifest_raw),
        "approval_sha256": _sha(approval_raw),
        "details_sha256": _sha(details_raw),
    }


def complete_published_discovery_review(
    *,
    plan: dict[str, Any],
    ledger: MatchDetailCampaignLedger,
    internal_id: str,
    reviewer: str,
    confirmation: str,
    data_root: Path,
    generation_root: Path,
    published_root: Path,
    player_inventory_root: Path,
    player_compact_root: Path,
    player_team_captures_root: Path,
    player_published_index_path: Path,
    completed_at_utc: str | None = None,
) -> dict[str, Any]:
    """Append a review-completion event only for the exact active approved package.

    All evidence reads are local. This operation does not perform HTTP, browser
    access, capture promotion, or publication writes.
    """

    spec = _campaign_spec(plan)
    candidate = next(
        (item for item in spec["candidates"] if item["internal_id"] == internal_id), None
    )
    if candidate is None:
        raise MatchCampaignAuthorizationError("El candidato no pertenece al plan")
    if not reviewer.strip():
        raise MatchCampaignAuthorizationError("Debe identificarse al revisor")
    if confirmation == "":
        raise MatchCampaignAuthorizationError("Falta confirmación explícita de cierre")

    campaign_dir = ledger._campaign_dir(spec)
    if campaign_dir.is_symlink() or not campaign_dir.is_dir():
        raise MatchCampaignIntegrityError("La campaña no está inicializada")
    data_root = data_root.expanduser().resolve(strict=True)
    if ledger.root.resolve(strict=True) != data_root / "matches" / "details" / "campaigns":
        raise MatchCampaignIntegrityError("El ledger no pertenece al almacén de datos configurado")

    with ledger.exclusive_lock():
        ledger._verify_campaign_dir(campaign_dir, spec)
        preflight = ledger._preflight_locked(spec, campaign_dir)
        blocked = [
            reason
            for reason in preflight["blocked_reasons"]
            if reason != f"DISCOVERY_REVIEW_REQUIRED:{candidate['source_match_id']}"
        ]
        if blocked:
            raise MatchCampaignAuthorizationError(
                f"La campaña conserva bloqueos ajenos al cierre: {blocked}"
            )
        events = ledger._read_events(
            ledger._candidate_dir(campaign_dir, internal_id), spec["campaign_id"], internal_id
        )
        state = ledger._state_from_events(events)
        if state not in {"DISCOVERY_REVIEW_REQUIRED", "REVIEW_COMPLETED"}:
            raise MatchCampaignAuthorizationError(
                f"No existe una adquisición revisable para el candidato: {state}"
            )
        started = next((item for item in events if item["event_type"] == "STARTED"), None)
        discovery = next(
            (item for item in events if item["event_type"] == "DISCOVERY_REVIEW_REQUIRED"), None
        )
        if started is None or discovery is None or discovery.get("attempt_id") != started.get("attempt_id"):
            raise MatchCampaignIntegrityError("El intento y el resultado de descubrimiento no coinciden")
        artifact = discovery.get("artifact")
        if not isinstance(artifact, dict):
            raise MatchCampaignIntegrityError("El candidato no tiene artefacto de descubrimiento íntegro")

        generation_root = generation_root.expanduser().resolve(strict=True)
        player_inventory_root = player_inventory_root.expanduser().resolve(strict=True)
        player_compact_root = player_compact_root.expanduser().resolve(strict=True)
        player_team_captures_root = player_team_captures_root.expanduser().resolve(strict=True)
        player_published_index_path = player_published_index_path.expanduser().resolve(strict=True)
        with _published_index_read_lock(published_root) as stable_published_root:
            generation_bundle = load_match_results_dataset(
                generation_root, data_root=data_root
            )
            player_directory = load_player_directory(
                inventory_root=player_inventory_root,
                compact_root=player_compact_root,
                team_captures_root=player_team_captures_root,
                published_index_path=player_published_index_path,
            )
            published = load_published_match_details(
                stable_published_root,
                store_root=ledger.root.parent,
                generation_root=generation_root,
                data_root=data_root,
                match_bundle=generation_bundle,
                player_ids=set(player_directory.players_by_id),
            )
            verified_document = published.get(internal_id)
            evidence = _active_publication_evidence(
                published_root=stable_published_root,
                internal_id=internal_id,
                source_match_id=candidate["source_match_id"],
                group=candidate["group"],
                source_capture_id=candidate["source_capture_id"],
                campaign_id=spec["campaign_id"],
                inventory_id=spec["source"]["inventory_id"],
                source_generation_id=spec["source"]["generation_id"],
                source_generation_manifest_sha256=spec["source"]["generation_manifest_sha256"],
                attempt_id=started["attempt_id"],
                artifact_id=artifact["artifact_id"],
                artifact_manifest_sha256=artifact["manifest_sha256"],
                source_html_sha256=artifact["source_html_sha256"],
                verified_document=verified_document,
            )
            expected_confirmation = review_completion_confirmation(
                candidate["source_match_id"],
                evidence["source_html_sha256"],
                evidence["details_sha256"],
            )
            if confirmation != expected_confirmation:
                raise MatchCampaignAuthorizationError(
                    "La confirmación debe coincidir con el partido y los hashes publicados"
                )
            return ledger._append_review_completion_locked(
                campaign_dir,
                spec,
                internal_id=internal_id,
                reviewer=reviewer,
                confirmation=confirmation,
                publication_evidence=evidence,
                completed_at_utc=completed_at_utc,
            )
