"""Versioned, append-only operational campaigns for MATCH-04D.

The v2 ledger is deliberately separate from the fixed five-candidate v1 pilot.
It consumes immutable MATCH-04C proposals and delegates semantic parsing and
publication to the existing MATCH detail pipeline. Importing this module never
starts a browser or performs HTTP.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .campaign import (
    CAMPAIGN_ARTIFACT_MANIFEST_SCHEMA,
    CAMPAIGN_ARTIFACT_SCHEMA,
    MatchCampaignAuthorizationError,
    MatchCampaignIntegrityError,
    MatchDetailCampaignLedger,
    SimulatedMatchAccessAdapter,
    _atomic_create,
    _atomic_directory,
    _canonical,
    _is_sha,
    _mkdirs_durable,
    _now,
    _read_json,
)
from .inventory import build_match_detail_inventory, load_verified_match_generation
from .scalable_campaigns import (
    ScalableCampaignError,
    _load_match_campaign_proposal,
    _validate_plan_payload,
    build_match_campaign_inventory,
)
from .store import MatchDetailStore

OPERATIONAL_CAMPAIGN_SCHEMA = "football_data_hub.match_detail_operational_campaign.v2"
OPERATIONAL_MANIFEST_SCHEMA = (
    "football_data_hub.match_detail_operational_campaign_manifest.v2"
)
OPERATIONAL_EVENT_SCHEMA = (
    "football_data_hub.match_detail_operational_campaign_event.v2"
)
AUTHORIZE_CONFIRMATION = "AUTHORIZE_ONE_MATCH_DISCOVERY_V2"
EXECUTE_CONFIRMATION = "EXECUTE_ONE_MATCH_DISCOVERY_V2"
PLAYER_IDLE_CONFIRMATION = "PLAYER_BROWSER_IDLE_CONFIRMED"
REVALIDATE_CONFIRMATION = "REVALIDATE_FAILED_ARTIFACT_V2"
_CAMPAIGN_ID = re.compile(r"^match-detail-campaign-v2-[0-9a-f]{16}$")
_INTERNAL_ID = re.compile(r"^pf-2026-27-group-(?:i|ii)-bdfutbol-[0-9]{5,10}$")
_EVENT_FILE = re.compile(r"^[0-9]{6}-[0-9a-f]{32}\.json$")
_TRANSITIONS = {
    "NOT_AUTHORIZED": {"AUTHORIZED"},
    "AUTHORIZED": {"STARTED"},
    "STARTED": {"DISCOVERY_REVIEW_REQUIRED", "STOPPED"},
    "DISCOVERY_REVIEW_REQUIRED": {"VALIDATED", "VALIDATION_FAILED"},
    "VALIDATED": {"DRAFT_PREPARED"},
    "DRAFT_PREPARED": {"DOCUMENT_APPROVED"},
    "DOCUMENT_APPROVED": {"PUBLISHED"},
    "PUBLISHED": {"REVIEW_COMPLETED"},
    "STOPPED": set(),
    "VALIDATION_FAILED": {"REVALIDATED", "REVALIDATION_FAILED"},
    "REVALIDATION_FAILED": {"REVALIDATED", "REVALIDATION_FAILED"},
    "REVALIDATED": {"DRAFT_PREPARED"},
    "REVIEW_COMPLETED": set(),
}


class OperationalCampaignError(ValueError):
    """A v2 campaign or transition is invalid."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _campaign_dir(root: Path, campaign_id: str) -> Path:
    if not _CAMPAIGN_ID.fullmatch(campaign_id):
        raise OperationalCampaignError("campaign_id v2 inválido")
    return root / campaign_id


def _source_candidate(candidate: dict[str, Any], source: dict[str, Any]) -> bool:
    keys = (
        "internal_id",
        "source_match_id",
        "group",
        "matchday",
        "source_match_date",
        "matchday_date",
        "home_team_id",
        "away_team_id",
        "home_team_name",
        "away_team_name",
        "source_match_url",
        "source_generation_id",
        "source_generation_manifest_sha256",
        "source_capture_id",
        "source_snapshot_sha256",
        "source_matches_sha256",
    )
    if any(candidate.get(key) != source.get(key) for key in keys):
        return False
    return candidate.get("reference_result") == source.get("reference_result")


def _file_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise MatchCampaignIntegrityError(f"Falta el archivo de evidencia: {path}")
    return _sha(path.read_bytes())


class OperationalMatchCampaignLedger:
    """Append-only v2 ledger sharing MATCH-03/04 campaign locking primitives."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().absolute()
        # Shares the established lock file with v1; schema interpretation remains
        # separate and the v1 pilot is never rewritten.
        self.lock = MatchDetailCampaignLedger(self.root)

    def _read_campaign(
        self, directory: Path
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        if directory.is_symlink() or not directory.is_dir():
            raise MatchCampaignIntegrityError("Campaña v2 ausente o no regular")
        campaign, campaign_raw = _read_json(
            directory / "campaign.json", label="campaign.json v2"
        )
        manifest, manifest_raw = _read_json(
            directory / "manifest.json", label="manifest v2"
        )
        plan, plan_raw = _read_json(directory / "plan.json", label="plan v2")
        try:
            _validate_plan_payload(plan)
        except (ScalableCampaignError, KeyError, TypeError) as exc:
            raise MatchCampaignIntegrityError(
                f"Plan MATCH-04C inválido: {exc}"
            ) from exc
        plan_digest = plan.get("plan_sha256")
        campaign_source = campaign.get("source")
        if not isinstance(campaign_source, dict):
            raise MatchCampaignIntegrityError("Falta la procedencia de la campaña v2")
        inventory_id = campaign_source.get("inventory_id")
        if not isinstance(inventory_id, str) or not re.fullmatch(
            r"match-detail-inventory-[0-9a-f]{16}", inventory_id
        ):
            raise MatchCampaignIntegrityError(
                "inventory_id de la campaña v2 no es válido"
            )
        store_root = self.root.parent
        inventory_dir = store_root / "inventories" / inventory_id
        inventory, inventory_raw = _read_json(
            inventory_dir / "inventory.json", label="inventario MATCH"
        )
        inventory_manifest, inventory_manifest_raw = _read_json(
            inventory_dir / "manifest.json", label="manifiesto inventario MATCH"
        )
        expected_inventory_manifest = {
            "schema_version": "football_data_hub.match_detail_inventory_manifest.v1",
            "inventory_id": inventory_id,
            "inventory_sha256": _sha(inventory_raw),
            "record_count": len(inventory.get("matches", [])),
            "source_generation": inventory.get("source_generation"),
        }
        expected_source = {
            **plan.get("source", {}),
            "inventory_id": inventory_id,
            "inventory_sha256": _sha(inventory_raw),
            "inventory_manifest_sha256": _sha(inventory_manifest_raw),
        }
        if (
            inventory.get("inventory_id") != inventory_id
            or inventory_manifest != expected_inventory_manifest
            or inventory_manifest_raw != _canonical(expected_inventory_manifest)
            or inventory.get("source_generation", {}).get("generation_id")
            != plan.get("source", {}).get("generation_id")
            or inventory.get("source_generation", {}).get("manifest_sha256")
            != plan.get("source", {}).get("generation_manifest_sha256")
            or campaign_source != expected_source
        ):
            raise MatchCampaignIntegrityError(
                "Inventario oficial y procedencia de campaña v2 no coinciden"
            )
        expected_campaign = {
            "schema_version": OPERATIONAL_CAMPAIGN_SCHEMA,
            "campaign_version": 2,
            "campaign_id": plan.get("campaign_id"),
            "proposal_id": plan.get("proposal_id"),
            "proposal_sha256": _sha(plan_raw),
            "plan_sha256": plan_digest,
            "candidate_count": plan.get("candidate_count"),
            "source": expected_source,
            "campaign_basis": {
                "proposal_id": plan.get("proposal_id"),
                "proposal_sha256": _sha(plan_raw),
                "plan_sha256": plan.get("plan_sha256"),
                "inventory_id": inventory_id,
                "inventory_sha256": _sha(inventory_raw),
                "source_generation_id": plan.get("source", {}).get("generation_id"),
                "source_generation_manifest_sha256": plan.get("source", {}).get(
                    "generation_manifest_sha256"
                ),
                "selected_internal_ids": [
                    item["internal_id"] for item in plan.get("candidates", [])
                ],
            },
            "selection": plan.get("selection"),
            "candidates": plan.get("candidates"),
            "capture_promotion_enabled": False,
            "automatic_retries": 0,
            "maximum_navigations_per_authorization": 1,
        }
        expected_manifest = {
            "schema_version": OPERATIONAL_MANIFEST_SCHEMA,
            "campaign_id": plan.get("campaign_id"),
            "campaign_sha256": _sha(_canonical(expected_campaign)),
            "proposal_id": plan.get("proposal_id"),
            "proposal_sha256": _sha(plan_raw),
            "plan_sha256": plan_digest,
            "candidate_count": plan.get("candidate_count"),
            "source_generation_id": plan.get("source", {}).get("generation_id"),
            "source_generation_manifest_sha256": plan.get("source", {}).get(
                "generation_manifest_sha256"
            ),
        }
        if (
            campaign != expected_campaign
            or campaign_raw != _canonical(expected_campaign)
            or manifest != expected_manifest
            or manifest_raw != _canonical(expected_manifest)
            or directory.name != plan.get("campaign_id")
            or set(item.name for item in directory.iterdir())
            != {"campaign.json", "manifest.json", "plan.json", "candidates"}
            or (directory / "candidates").is_symlink()
            or not (directory / "candidates").is_dir()
            or (directory / "candidates" / ".ledger-version").is_symlink()
            or not (directory / "candidates" / ".ledger-version").is_file()
            or (directory / "candidates" / ".ledger-version").read_bytes() != b"2\n"
        ):
            raise MatchCampaignIntegrityError(
                "Hashes, estructura o procedencia de campaña v2 inválidos"
            )
        return campaign, manifest, plan

    def _candidate(self, campaign: dict[str, Any], internal_id: str) -> dict[str, Any]:
        if not _INTERNAL_ID.fullmatch(internal_id):
            raise OperationalCampaignError("internal_id inválido")
        matches = [
            item
            for item in campaign["candidates"]
            if item.get("internal_id") == internal_id
        ]
        if len(matches) != 1:
            raise MatchCampaignAuthorizationError(
                "El partido no pertenece de forma única a la campaña"
            )
        return matches[0]

    def _read_events(
        self, directory: Path, campaign: dict[str, Any], internal_id: str
    ) -> list[dict[str, Any]]:
        event_dir = directory / "candidates" / internal_id / "events"
        if event_dir.is_symlink():
            raise MatchCampaignIntegrityError("El ledger contiene symlink")
        if not event_dir.exists():
            return []
        if not event_dir.is_dir():
            raise MatchCampaignIntegrityError("events no es directorio")
        files = sorted(event_dir.iterdir(), key=lambda item: item.name)
        if any(
            item.is_symlink()
            or not item.is_file()
            or not _EVENT_FILE.fullmatch(item.name)
            for item in files
        ):
            raise MatchCampaignIntegrityError("El ledger contiene eventos inesperados")
        events: list[dict[str, Any]] = []
        previous = None
        state = "NOT_AUTHORIZED"
        for sequence, path in enumerate(files, 1):
            envelope, raw = _read_json(path, label="evento v2")
            payload = envelope.get("payload")
            event_type = (
                payload.get("event_type") if isinstance(payload, dict) else None
            )
            if (
                path.name != f"{sequence:06d}-{envelope.get('event_id')}.json"
                or envelope.get("schema_version") != OPERATIONAL_EVENT_SCHEMA
                or envelope.get("campaign_id") != campaign["campaign_id"]
                or envelope.get("internal_id") != internal_id
                or envelope.get("sequence") != sequence
                or envelope.get("previous_event_sha256") != previous
                or not isinstance(payload, dict)
                or payload.get("campaign_id") != campaign["campaign_id"]
                or payload.get("internal_id") != internal_id
                or envelope.get("payload_sha256") != _sha(_canonical(payload))
                or event_type not in _TRANSITIONS.get(state, set())
            ):
                raise MatchCampaignIntegrityError(
                    f"Cadena o transición inválida para {internal_id}"
                )
            self._validate_event_payload(payload, campaign, internal_id, events)
            previous = _sha(raw)
            events.append({**payload, "sequence": sequence, "event_sha256": previous})
            state = event_type
            if event_type == "DISCOVERY_REVIEW_REQUIRED":
                self._verify_artifact(directory, campaign, internal_id, payload)
            elif event_type in {"DRAFT_PREPARED", "DOCUMENT_APPROVED"}:
                self._verify_review_record(campaign, internal_id, payload, events)
        return events

    @staticmethod
    def _verify_artifact(
        directory: Path,
        campaign: dict[str, Any],
        internal_id: str,
        event: dict[str, Any],
    ) -> None:
        reference = event.get("artifact")
        relative = (
            f"candidates/{internal_id}/artifacts/{reference.get('artifact_id')}"
            if isinstance(reference, dict)
            else ""
        )
        if not relative or reference.get("artifact_relative_path") != relative:
            raise MatchCampaignIntegrityError(
                "La referencia del artefacto v2 no es canónica"
            )
        artifact = directory / relative
        if artifact.is_symlink() or not artifact.is_dir():
            raise MatchCampaignIntegrityError("Artefacto v2 ausente o no regular")
        manifest, manifest_raw = _read_json(
            artifact / "manifest.json", label="manifest artefacto v2"
        )
        if (
            manifest.get("schema_version") != CAMPAIGN_ARTIFACT_MANIFEST_SCHEMA
            or manifest.get("artifact_id") != reference.get("artifact_id")
            or manifest.get("campaign_id") != campaign["campaign_id"]
            or manifest.get("internal_id") != internal_id
            or _sha(manifest_raw) != reference.get("manifest_sha256")
        ):
            raise MatchCampaignIntegrityError("Manifiesto de artefacto v2 no coincide")
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != {
            "source.html",
            "metadata.json",
            "discovery.json",
        }:
            raise MatchCampaignIntegrityError(
                "El manifiesto de artefacto v2 tiene estructura inesperada"
            )
        for name, specification in files.items():
            path = artifact / name
            if path.is_symlink() or not path.is_file():
                raise MatchCampaignIntegrityError(
                    f"Archivo de artefacto no regular: {name}"
                )
            raw = path.read_bytes()
            if _sha(raw) != specification.get("sha256") or len(
                raw
            ) != specification.get("bytes"):
                raise MatchCampaignIntegrityError(
                    f"Hash inválido en artefacto v2: {name}"
                )
        if files["source.html"].get("sha256") != reference.get("source_html_sha256"):
            raise MatchCampaignIntegrityError(
                "El HTML del artefacto no coincide con el ledger v2"
            )
        metadata, _ = _read_json(
            artifact / "metadata.json", label="metadata de artefacto v2"
        )
        if (
            metadata.get("schema_version") != CAMPAIGN_ARTIFACT_SCHEMA
            or metadata.get("campaign_id") != campaign["campaign_id"]
            or metadata.get("internal_id") != internal_id
            or metadata.get("source_match_id") != event.get("source_match_id")
            or metadata.get("navigation_attempt_id") != event.get("attempt_id")
            or metadata.get("requested_url")
            != next(
                item["source_match_url"]
                for item in campaign["candidates"]
                if item["internal_id"] == internal_id
            )
            or metadata.get("http_status") != 200
            or metadata.get("final_url") != event.get("final_url")
            or metadata.get("access_classification") != "VALID"
            or metadata.get("challenge_detected") is not False
            or metadata.get("denial_detected") is not False
            or metadata.get("capture_promoted") is not False
        ):
            raise MatchCampaignIntegrityError(
                "La metadata de artefacto contradice la resolución v2"
            )

    def _verify_review_record(
        self,
        campaign: dict[str, Any],
        internal_id: str,
        event: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> None:
        """Rehash and bind immutable draft/approval files on every ledger read."""

        candidate = self._candidate(campaign, internal_id)
        data_root = self.root.parent.parent.parent
        review_root = (
            data_root
            / "matches"
            / "details"
            / "review"
            / "v2"
            / campaign["campaign_id"]
        )
        draft_path = review_root / f"{candidate['source_match_id']}-draft.json"
        prepared = next(
            (item for item in events if item.get("event_type") == "DRAFT_PREPARED"),
            None,
        )
        if prepared is None:
            raise MatchCampaignIntegrityError(
                "La aprobación v2 no tiene borrador registrado"
            )
        if event["event_type"] == "DRAFT_PREPARED":
            expected_relative = draft_path.relative_to(data_root).as_posix()
            if event.get("draft_path") != expected_relative:
                raise MatchCampaignIntegrityError(
                    "La ruta del borrador v2 no es canónica"
                )
        else:
            approval_path = (
                review_root / f"{candidate['source_match_id']}-approval.json"
            )
            expected_relative = approval_path.relative_to(data_root).as_posix()
            if event.get("approval_path") != expected_relative:
                raise MatchCampaignIntegrityError(
                    "La ruta del recibo v2 no es canónica"
                )

        cursor = data_root
        for part in draft_path.relative_to(data_root).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise MatchCampaignIntegrityError(
                    "No se permiten symlinks en artefactos de revisión"
                )
        if not draft_path.is_file() or _file_hash(draft_path) != prepared.get(
            "draft_sha256"
        ):
            raise MatchCampaignIntegrityError("El borrador cambió desde su registro")
        try:
            draft = json.loads(draft_path.read_bytes())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MatchCampaignIntegrityError("Borrador de campaña ilegible") from exc
        discovery = next(
            (
                item
                for item in events
                if item.get("event_type") == "DISCOVERY_REVIEW_REQUIRED"
            ),
            None,
        )
        if (
            not isinstance(draft, dict)
            or discovery is None
            or draft.get("internal_id") != internal_id
            or draft.get("campaign_id") != campaign["campaign_id"]
            or draft.get("source_match_id") != candidate["source_match_id"]
            or draft.get("artifact_id") != discovery["artifact"]["artifact_id"]
            or draft.get("source_html_sha256")
            != discovery["artifact"]["source_html_sha256"]
            or draft.get("source_html_sha256") != prepared.get("source_html_sha256")
            or draft.get("details_sha256") != prepared.get("details_sha256")
            or draft.get("semantic_valid") is not True
            or draft.get("capture_promotion_enabled") is not False
        ):
            raise MatchCampaignIntegrityError(
                "El borrador no está ligado a la adquisición validada"
            )
        if event["event_type"] != "DOCUMENT_APPROVED":
            return
        approval_path = review_root / f"{candidate['source_match_id']}-approval.json"
        if not approval_path.is_file() or _file_hash(approval_path) != event.get(
            "approval_sha256"
        ):
            raise MatchCampaignIntegrityError(
                "El recibo de aprobación no coincide con el ledger"
            )
        try:
            receipt = json.loads(approval_path.read_bytes())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MatchCampaignIntegrityError("Recibo de aprobación ilegible") from exc
        fields = (
            "publication_id",
            "source_kind",
            "internal_id",
            "inventory_id",
            "source_generation_id",
            "source_generation_manifest_sha256",
            "source_capture_id",
            "source_match_id",
            "season",
            "competition",
            "group",
            "matchday",
            "source_match_date",
            "home_team_id",
            "away_team_id",
            "home_team_name",
            "away_team_name",
            "campaign_id",
            "artifact_id",
            "navigation_attempt_id",
            "artifact_manifest_sha256",
            "source_html_sha256",
            "details_sha256",
        )
        if (
            not isinstance(receipt, dict)
            or receipt.get("schema_version")
            != "football_data_hub.match_detail_campaign_approval.v1"
            or receipt.get("publication_status") != "approved"
            or receipt.get("approved_by") != event.get("approved_by")
            or receipt.get("approval_confirmation")
            != event.get("approval_confirmation")
            or any(receipt.get(key) != draft.get(key) for key in fields)
            or event.get("source_html_sha256") != draft.get("source_html_sha256")
            or event.get("details_sha256") != draft.get("details_sha256")
        ):
            raise MatchCampaignIntegrityError(
                "El recibo no aprueba exactamente el borrador"
            )

    @staticmethod
    def _validate_event_payload(
        event: dict[str, Any],
        campaign: dict[str, Any],
        internal_id: str,
        previous: list[dict[str, Any]],
    ) -> None:
        candidate = next(
            item
            for item in campaign["candidates"]
            if item["internal_id"] == internal_id
        )
        kind = event["event_type"]
        if kind == "AUTHORIZED":
            authorization = event.get("authorization")
            if (
                not isinstance(authorization, dict)
                or authorization.get("internal_id") != internal_id
                or authorization.get("source_match_id") != candidate["source_match_id"]
                or authorization.get("source_match_url")
                != candidate["source_match_url"]
                or authorization.get("proposal_sha256") != campaign["proposal_sha256"]
                or authorization.get("maximum_navigations") != 1
                or authorization.get("automatic_retries") != 0
                or authorization.get("capture_promotion_enabled") is not False
                or not isinstance(authorization.get("operator"), str)
                or not authorization["operator"].strip()
                or authorization.get("human_confirmation") != AUTHORIZE_CONFIRMATION
            ):
                raise MatchCampaignIntegrityError(
                    "Autorización v2 inválida o incongruente"
                )
            campaign_authorization_id = authorization.get("campaign_authorization_id")
            campaign_candidate_set_sha256 = authorization.get(
                "campaign_candidate_set_sha256"
            )
            if (campaign_authorization_id is None) != (
                campaign_candidate_set_sha256 is None
            ) or (
                campaign_authorization_id is not None
                and (
                    not isinstance(campaign_authorization_id, str)
                    or not campaign_authorization_id.startswith(
                        "campaign-authorization-"
                    )
                    or not _is_sha(campaign_candidate_set_sha256)
                )
            ):
                raise MatchCampaignIntegrityError(
                    "La referencia a la autorización de campaña es inválida"
                )
        elif kind == "STARTED":
            auth = previous[-1].get("authorization") if previous else None
            if (
                not isinstance(auth, dict)
                or event.get("authorization_id") != auth.get("authorization_id")
                or event.get("requested_url") != candidate["source_match_url"]
                or event.get("source_match_id") != candidate["source_match_id"]
                or not isinstance(event.get("attempt_id"), str)
                or not event.get("attempt_id")
                or event.get("maximum_navigations") != 1
            ):
                raise MatchCampaignIntegrityError(
                    "Reserva STARTED no corresponde a su autorización"
                )
        elif kind == "DISCOVERY_REVIEW_REQUIRED":
            started = previous[-1] if previous else {}
            artifact = event.get("artifact")
            if (
                event.get("attempt_id") != started.get("attempt_id")
                or event.get("source_match_id") != candidate["source_match_id"]
                or event.get("http_status") != 200
                or event.get("final_url") != candidate["source_match_url"]
                or event.get("access_classification") != "VALID"
                or event.get("capture_promoted") is not False
                or event.get("semantic_validation_performed") is not False
                or not isinstance(artifact, dict)
                or not _is_sha(artifact.get("manifest_sha256"))
                or not _is_sha(artifact.get("source_html_sha256"))
            ):
                raise MatchCampaignIntegrityError(
                    "Resolución o artefacto de descubrimiento inválido"
                )
        elif kind == "STOPPED":
            started = previous[-1] if previous else {}
            if (
                not isinstance(event.get("error_code"), str)
                or not event["error_code"]
                or event.get("attempt_id") != started.get("attempt_id")
                or event.get("authorization_id") != started.get("authorization_id")
                or event.get("source_match_id") != candidate["source_match_id"]
                or event.get("requested_url") != candidate["source_match_url"]
                or (
                    event.get("http_status") is not None
                    and (
                        type(event.get("http_status")) is not int
                        or event["http_status"] < 100
                    )
                )
            ):
                raise MatchCampaignIntegrityError("STOPPED requiere un código de error")
        elif kind == "VALIDATED":
            discovery = next(
                (
                    row
                    for row in previous
                    if row["event_type"] == "DISCOVERY_REVIEW_REQUIRED"
                ),
                None,
            )
            if (
                discovery is None
                or event.get("semantic_valid") is not True
                or event.get("source_html_sha256")
                != discovery["artifact"]["source_html_sha256"]
                or not _is_sha(event.get("evidence_sha256"))
            ):
                raise MatchCampaignIntegrityError(
                    "Validación no vinculada al HTML aprobado"
                )
        elif kind == "VALIDATION_FAILED":
            discovery = next(
                (
                    row
                    for row in previous
                    if row["event_type"] == "DISCOVERY_REVIEW_REQUIRED"
                ),
                None,
            )
            if (
                event.get("semantic_valid") is not False
                or discovery is None
                or event.get("source_html_sha256")
                != discovery["artifact"]["source_html_sha256"]
                or not _is_sha(event.get("evidence_sha256"))
            ):
                raise MatchCampaignIntegrityError(
                    "VALIDATION_FAILED no contiene evidencia"
                )
        elif kind in {"REVALIDATED", "REVALIDATION_FAILED"}:
            discovery = next(
                (
                    row
                    for row in previous
                    if row["event_type"] == "DISCOVERY_REVIEW_REQUIRED"
                ),
                None,
            )
            failed = previous[-1] if previous else {}
            validation = event.get("validation")
            if (
                failed.get("event_type")
                not in {"VALIDATION_FAILED", "REVALIDATION_FAILED"}
                or failed.get("semantic_valid") is not False
                or discovery is None
                or event.get("based_on_event_sha256")
                != failed.get("event_sha256")
                or event.get("artifact_id")
                != discovery["artifact"].get("artifact_id")
                or event.get("source_html_sha256")
                != discovery["artifact"].get("source_html_sha256")
                or not isinstance(event.get("operator"), str)
                or not event["operator"].strip()
                or event.get("human_confirmation") != REVALIDATE_CONFIRMATION
                or not isinstance(event.get("parser_version"), str)
                or not event["parser_version"].strip()
                or not isinstance(validation, dict)
                or validation.get("parser_version") != event.get("parser_version")
                or validation.get("semantic_valid")
                is not (kind == "REVALIDATED")
                or not _is_sha(event.get("evidence_sha256"))
            ):
                raise MatchCampaignIntegrityError(
                    "La revalidación no conserva fallo, artefacto y confirmación"
                )
            if kind == "REVALIDATED":
                errors = validation.get("errors")
                checks = validation.get("checks")
                if (
                    errors not in ([], ())
                    or not isinstance(checks, (list, tuple))
                    or any(
                        not isinstance(check, dict) or check.get("passed") is not True
                        for check in checks
                    )
                ):
                    raise MatchCampaignIntegrityError(
                        "REVALIDATED contiene errores o comprobaciones fallidas"
                    )
            evidence = {
                key: event[key]
                for key in (
                    "based_on_event_sha256",
                    "artifact_id",
                    "source_html_sha256",
                    "semantic_valid",
                    "validation",
                    "parser_version",
                    "operator",
                    "human_confirmation",
                    "validated_at_utc",
                )
            }
            if event.get("evidence_sha256") != _sha(_canonical(evidence)):
                raise MatchCampaignIntegrityError(
                    "El hash de evidencia de revalidación no coincide"
                )
        elif kind == "DRAFT_PREPARED":
            if (
                not _is_sha(event.get("draft_sha256"))
                or not isinstance(event.get("draft_path"), str)
                or not _is_sha(event.get("source_html_sha256"))
                or not _is_sha(event.get("details_sha256"))
            ):
                raise MatchCampaignIntegrityError("Borrador v2 sin hash o ubicación")
        elif kind == "DOCUMENT_APPROVED":
            if (
                not _is_sha(event.get("approval_sha256"))
                or not isinstance(event.get("approved_by"), str)
                or not event["approved_by"].strip()
                or event.get("human_confirmation") is not True
                or not isinstance(event.get("approval_path"), str)
                or not _is_sha(event.get("source_html_sha256"))
                or not _is_sha(event.get("details_sha256"))
            ):
                raise MatchCampaignIntegrityError("Aprobación v2 inválida")
        elif kind == "PUBLISHED":
            approved = next(
                (row for row in previous if row["event_type"] == "DOCUMENT_APPROVED"),
                None,
            )
            if (
                not _is_sha(event.get("publication_manifest_sha256"))
                or approved is None
                or event.get("approval_sha256") != approved.get("approval_sha256")
                or event.get("details_sha256") != approved.get("details_sha256")
                or not isinstance(event.get("publication_id"), str)
            ):
                raise MatchCampaignIntegrityError(
                    "Publicación v2 sin manifiesto verificado"
                )
        elif kind == "REVIEW_COMPLETED":
            if (
                not isinstance(event.get("reviewer"), str)
                or not event["reviewer"].strip()
                or not isinstance(event.get("human_confirmation"), str)
                or not _is_sha(event.get("publication_manifest_sha256"))
                or event.get("historic_acquisition_state")
                != "DISCOVERY_REVIEW_REQUIRED"
                or event.get("capture_promoted") is not False
                or event.get("publication_manifest_sha256")
                != previous[-1].get("publication_manifest_sha256")
            ):
                raise MatchCampaignIntegrityError("Cierre de revisión v2 incompleto")

    def _append(
        self,
        directory: Path,
        campaign: dict[str, Any],
        internal_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._candidate(campaign, internal_id)
        events = self._read_events(directory, campaign, internal_id)
        state = events[-1]["event_type"] if events else "NOT_AUTHORIZED"
        if payload.get("event_type") not in _TRANSITIONS.get(state, set()):
            raise MatchCampaignAuthorizationError(
                f"Transición v2 no permitida desde {state}"
            )
        self._validate_event_payload(payload, campaign, internal_id, events)
        event_dir = directory / "candidates" / internal_id / "events"
        _mkdirs_durable(event_dir)
        event_id = uuid.uuid4().hex
        envelope = {
            "schema_version": OPERATIONAL_EVENT_SCHEMA,
            "campaign_id": campaign["campaign_id"],
            "internal_id": internal_id,
            "sequence": len(events) + 1,
            "event_id": event_id,
            "previous_event_sha256": events[-1]["event_sha256"] if events else None,
            "payload_sha256": _sha(_canonical(payload)),
            "payload": payload,
        }
        _atomic_create(
            event_dir / f"{len(events) + 1:06d}-{event_id}.json", _canonical(envelope)
        )
        return {
            **payload,
            "sequence": len(events) + 1,
            "event_sha256": _sha(_canonical(envelope)),
        }

    @staticmethod
    def _state(events: list[dict[str, Any]]) -> str:
        if not events:
            return "NOT_AUTHORIZED"
        event = events[-1]["event_type"]
        if event == "STARTED":
            return "INTERRUPTED_REQUIRES_REVIEW"
        return event

    def _all_campaign_ids(self) -> set[str]:
        if not self.root.exists():
            return set()
        result: set[str] = set()
        for directory in self.root.iterdir():
            if directory.name == "campaign-ledger.lock":
                continue
            if directory.is_symlink() or not directory.is_dir():
                raise MatchCampaignIntegrityError(
                    "Entrada inesperada en ledger de campañas"
                )
            path = directory / "campaign.json"
            if path.is_symlink() or not path.is_file():
                raise MatchCampaignIntegrityError("Campaña sin fichero de identidad")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema_version") == OPERATIONAL_CAMPAIGN_SCHEMA:
                campaign, _manifest, _plan = self._read_campaign(directory)
                result.update(item["internal_id"] for item in campaign["candidates"])
            else:
                # Existing pilot v1 is immutable and read through its established validator.
                legacy = MatchDetailCampaignLedger(self.root)
                spec, _report, _events = legacy.inspect_persisted_campaign_read_only(
                    directory,
                    internal_id=str(
                        payload.get("candidates", [{}])[0].get("internal_id", "")
                    ),
                )
                result.update(item["internal_id"] for item in spec["candidates"])
        return result

    def initialize(
        self,
        *,
        proposal_dir: Path,
        generation_root: Path,
        data_root: Path,
        published_ids: set[str] = frozenset(),
        captured_ids: set[str] = frozenset(),
        blocked_ids: set[str] = frozenset(),
    ) -> dict[str, Any]:
        plan = _load_match_campaign_proposal(proposal_dir)
        verified = load_verified_match_generation(generation_root, data_root=data_root)
        if (
            verified.generation_id != plan["source"]["generation_id"]
            or verified.manifest_sha256 != plan["source"]["generation_manifest_sha256"]
        ):
            raise MatchCampaignIntegrityError(
                "La generación de origen de la propuesta ya no coincide"
            )
        campaign_inventory = build_match_campaign_inventory(verified)
        source_matches = {
            row["internal_id"]: row for row in campaign_inventory["matches"]
        }
        for candidate in plan["candidates"]:
            source = source_matches.get(candidate["internal_id"])
            if (
                source is None
                or source["status"] != "played"
                or not _source_candidate(candidate, source)
            ):
                raise MatchCampaignIntegrityError(
                    f"Candidato contradictorio con MATCH-00: {candidate['internal_id']}"
                )
        detail_inventory = build_match_detail_inventory(verified)
        detail_by_id = {row["internal_id"]: row for row in detail_inventory["matches"]}
        if any(
            candidate["internal_id"] not in detail_by_id
            or detail_by_id[candidate["internal_id"]]["source_match_url"]
            != candidate["source_match_url"]
            for candidate in plan["candidates"]
        ):
            raise MatchCampaignIntegrityError(
                "Falta URL individual explícita en inventario verificado"
            )

        directory = _campaign_dir(self.root, plan["campaign_id"])
        plan_raw = _canonical(plan)
        proposal_sha = _sha(plan_raw)
        campaign = {
            "schema_version": OPERATIONAL_CAMPAIGN_SCHEMA,
            "campaign_version": 2,
            "campaign_id": plan["campaign_id"],
            "proposal_id": plan["proposal_id"],
            "proposal_sha256": proposal_sha,
            "plan_sha256": plan["plan_sha256"],
            "candidate_count": plan["candidate_count"],
            "source": {
                **plan["source"],
                "inventory_id": detail_inventory["inventory_id"],
                "inventory_sha256": _sha(_canonical(detail_inventory)),
                "inventory_manifest_sha256": "",  # Set from the official store manifest below.
            },
            "campaign_basis": {
                "proposal_id": plan["proposal_id"],
                "proposal_sha256": proposal_sha,
                "plan_sha256": plan["plan_sha256"],
                "inventory_id": detail_inventory["inventory_id"],
                "inventory_sha256": _sha(_canonical(detail_inventory)),
                "source_generation_id": plan["source"]["generation_id"],
                "source_generation_manifest_sha256": plan["source"][
                    "generation_manifest_sha256"
                ],
                "selected_internal_ids": [
                    item["internal_id"] for item in plan["candidates"]
                ],
            },
            "selection": plan["selection"],
            "candidates": plan["candidates"],
            "capture_promotion_enabled": False,
            "automatic_retries": 0,
            "maximum_navigations_per_authorization": 1,
        }
        # Check duplicate campaign membership before creating any files.
        unsafe = set(published_ids) | set(captured_ids) | set(blocked_ids)
        unsafe.update(
            row["internal_id"]
            for row in plan["candidates"]
            if row["detail_status"] != "played_pending_acquisition"
        )
        overlap = unsafe.intersection(
            item["internal_id"] for item in plan["candidates"]
        )
        if overlap:
            raise MatchCampaignAuthorizationError(
                f"Candidatos publicados/capturados/bloqueados: {sorted(overlap)}"
            )

        store = MatchDetailStore(self.root.parent)
        with self.lock.exclusive_lock():
            with store.exclusive_lock():
                reconciliation = store.reconcile(detail_inventory)
                newly_captured = set(
                    reconciliation["verified_by_internal_id"]
                ).intersection(item["internal_id"] for item in plan["candidates"])
                stopped = {
                    item.get("internal_id")
                    for item in reconciliation["diagnostics"]
                    if item.get("stop_acquisition", True)
                }
                stopped.intersection_update(
                    item["internal_id"] for item in plan["candidates"]
                )
                if reconciliation["integrity_blocked"] or newly_captured or stopped:
                    raise MatchCampaignAuthorizationError(
                        "El almacén MATCH contiene conflicto/bloqueo para la propuesta"
                    )
                inventory_dir = store._prepare_inventory_locked(detail_inventory)
                inventory_manifest, _raw = _read_json(
                    inventory_dir / "manifest.json", label="manifiesto de inventario"
                )
                campaign["source"]["inventory_manifest_sha256"] = _sha(
                    _canonical(inventory_manifest)
                )
                campaign["campaign_basis"]["inventory_sha256"] = campaign["source"][
                    "inventory_sha256"
                ]
                manifest = {
                    "schema_version": OPERATIONAL_MANIFEST_SCHEMA,
                    "campaign_id": campaign["campaign_id"],
                    "campaign_sha256": _sha(_canonical(campaign)),
                    "proposal_id": campaign["proposal_id"],
                    "proposal_sha256": proposal_sha,
                    "plan_sha256": campaign["plan_sha256"],
                    "candidate_count": campaign["candidate_count"],
                    "source_generation_id": campaign["source"]["generation_id"],
                    "source_generation_manifest_sha256": campaign["source"][
                        "generation_manifest_sha256"
                    ],
                }
                if directory.exists():
                    persisted, _manifest, _persisted_plan = self._read_campaign(
                        directory
                    )
                    if persisted != campaign:
                        raise MatchCampaignIntegrityError(
                            "La campaña concurrente difiere"
                        )
                    return {
                        "status": "CAMPAIGN_ALREADY_INITIALIZED",
                        "campaign_id": plan["campaign_id"],
                        "candidate_count": plan["candidate_count"],
                    }
                existing_ids = self._all_campaign_ids()
                collision = existing_ids.intersection(
                    item["internal_id"] for item in plan["candidates"]
                )
                if collision:
                    raise MatchCampaignAuthorizationError(
                        f"Candidatos ya gestionados en otra campaña: {sorted(collision)}"
                    )
                _atomic_directory(
                    self.root,
                    plan["campaign_id"],
                    {
                        "campaign.json": _canonical(campaign),
                        "manifest.json": _canonical(manifest),
                        "plan.json": plan_raw,
                        "candidates/.ledger-version": b"2\n",
                    },
                )
        return {
            "status": "CAMPAIGN_INITIALIZED_NOT_AUTHORIZED",
            "campaign_id": plan["campaign_id"],
            "candidate_count": plan["candidate_count"],
        }

    def _events(
        self, campaign_id: str, internal_id: str
    ) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
        directory = _campaign_dir(self.root, campaign_id)
        campaign, _manifest, _plan = self._read_campaign(directory)
        self._candidate(campaign, internal_id)
        events = self._read_events(directory, campaign, internal_id)
        return directory, campaign, events

    def candidate(self, campaign_id: str, internal_id: str) -> dict[str, Any]:
        return next(
            row
            for row in self.preflight(campaign_id)["candidates"]
            if row["internal_id"] == internal_id
        )

    def source_inventory(self, campaign_id: str) -> dict[str, Any]:
        directory = _campaign_dir(self.root, campaign_id)
        campaign, _manifest, _plan = self._read_campaign(directory)
        inventory, _raw = _read_json(
            self.root.parent
            / "inventories"
            / campaign["source"]["inventory_id"]
            / "inventory.json",
            label="inventario v2",
        )
        return inventory

    def candidate_events(
        self, campaign_id: str, internal_id: str
    ) -> list[dict[str, Any]]:
        _directory, _campaign, events = self._events(campaign_id, internal_id)
        return events

    def generation_root(self, campaign_id: str, data_root: Path) -> Path:
        directory = _campaign_dir(self.root, campaign_id)
        campaign, _manifest, _plan = self._read_campaign(directory)
        generation_root = (
            data_root.expanduser().resolve(strict=True)
            / "matches"
            / "generations"
            / campaign["source"]["generation_id"]
        )
        verified = load_verified_match_generation(generation_root, data_root=data_root)
        if verified.manifest_sha256 != campaign["source"]["generation_manifest_sha256"]:
            raise MatchCampaignIntegrityError(
                "La generación histórica no coincide con la campaña"
            )
        return generation_root

    def inspect(
        self, directory: Path, *, internal_id: str
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        with self.lock.shared_lock():
            campaign, _manifest, _plan = self._read_campaign(directory)
            self._candidate(campaign, internal_id)
            events = self._read_events(directory, campaign, internal_id)
            report = self.preflight(campaign["campaign_id"], acquire_lock=False)
            return campaign, report, events

    def inspect_artifact_evidence(
        self, directory: Path, *, internal_id: str
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        """Read one candidate's complete chain for immutable artifact validation.

        Artifact parsing only needs to establish the selected match's one-use
        authorization and discovery chain. A global preflight here rereads
        every other candidate each time a published document is loaded. The
        campaign manifest and candidate list are still verified, and every
        event for this candidate is validated by ``_read_events``. Callers
        needing campaign-wide status continue to use ``preflight``/``inspect``.
        """

        with self.lock.shared_lock():
            campaign, _manifest, _plan = self._read_campaign(directory)
            candidate = self._candidate(campaign, internal_id)
            events = self._read_events(directory, campaign, internal_id)
            state = self._state(events)
            authorization = next(
                (
                    event.get("authorization")
                    for event in events
                    if event["event_type"] == "AUTHORIZED"
                ),
                None,
            )
            discovery = next(
                (
                    event
                    for event in events
                    if event["event_type"] == "DISCOVERY_REVIEW_REQUIRED"
                ),
                None,
            )
            row = {
                **candidate,
                "campaign_id": campaign["campaign_id"],
                "campaign_version": 2,
                "state": state,
                "acquisition_state": "DISCOVERY_REVIEW_REQUIRED"
                if discovery
                else state,
                "authorization_consumed": authorization is not None,
                "authorization_id": authorization.get("authorization_id")
                if authorization
                else None,
                "navigation_count": 1
                if any(event["event_type"] == "STARTED" for event in events)
                else 0,
                "capture_promoted": False,
                "event_count": len(events),
                "artifact": discovery.get("artifact") if discovery else None,
                "next_operation": self._next_operation(state),
            }
            report = {
                "campaign_id": campaign["campaign_id"],
                "candidate_count": campaign["candidate_count"],
                "candidates": [row],
                "capture_promotion_enabled": False,
                "automatic_retries": 0,
                "http_enabled": False,
                "browser_started": False,
                "navigation_enabled": False,
            }
            return campaign, report, events

    def preflight(
        self, campaign_id: str, *, acquire_lock: bool = True
    ) -> dict[str, Any]:
        directory = _campaign_dir(self.root, campaign_id)
        context = self.lock.shared_lock() if acquire_lock else _null_context()
        with context:
            campaign, _manifest, _plan = self._read_campaign(directory)
            rows = []
            counts: dict[str, int] = {}
            for candidate in campaign["candidates"]:
                events = self._read_events(
                    directory, campaign, candidate["internal_id"]
                )
                state = self._state(events)
                counts[state] = counts.get(state, 0) + 1
                auth = next(
                    (
                        event.get("authorization")
                        for event in events
                        if event["event_type"] == "AUTHORIZED"
                    ),
                    None,
                )
                discovery = next(
                    (
                        event
                        for event in events
                        if event["event_type"] == "DISCOVERY_REVIEW_REQUIRED"
                    ),
                    None,
                )
                rows.append(
                    {
                        **candidate,
                        "campaign_id": campaign_id,
                        "campaign_version": 2,
                        "state": state,
                        "acquisition_state": "DISCOVERY_REVIEW_REQUIRED"
                        if discovery
                        else state,
                        "authorization_consumed": auth is not None,
                        "authorization_id": auth.get("authorization_id")
                        if auth
                        else None,
                        "navigation_count": 1
                        if any(item["event_type"] == "STARTED" for item in events)
                        else 0,
                        "capture_promoted": False,
                        "event_count": len(events),
                        "artifact": discovery.get("artifact") if discovery else None,
                        "next_operation": self._next_operation(state),
                    }
                )
            return {
                "schema_version": OPERATIONAL_CAMPAIGN_SCHEMA,
                "campaign_id": campaign_id,
                "campaign_version": 2,
                "proposal_id": campaign["proposal_id"],
                "proposal_sha256": campaign["proposal_sha256"],
                "plan_sha256": campaign["plan_sha256"],
                "source_generation_id": campaign["source"]["generation_id"],
                "source_generation_manifest_sha256": campaign["source"][
                    "generation_manifest_sha256"
                ],
                "candidate_count": campaign["candidate_count"],
                "candidate_states": counts,
                "candidates": rows,
                "capture_promotion_enabled": False,
                "automatic_retries": 0,
                "http_enabled": False,
                "browser_started": False,
                "navigation_enabled": False,
            }

    @staticmethod
    def _next_operation(state: str) -> str:
        return {
            "NOT_AUTHORIZED": "review_candidate_then_authorize_individually",
            "AUTHORIZED": "execute_one_authorized_navigation",
            "INTERRUPTED_REQUIRES_REVIEW": "manual_review_no_retry",
            "DISCOVERY_REVIEW_REQUIRED": "validate_offline_artifact",
            "VALIDATED": "prepare_offline_draft",
            "REVALIDATED": "prepare_offline_draft",
            "VALIDATION_FAILED": "revalidate_failed_artifact_offline_with_operator_confirmation",
            "REVALIDATION_FAILED": "revalidate_failed_artifact_offline_with_operator_confirmation",
            "DRAFT_PREPARED": "human_document_review_and_approval",
            "DOCUMENT_APPROVED": "publish_approved_document",
            "PUBLISHED": "verify_then_complete_review",
            "REVIEW_COMPLETED": "none",
            "STOPPED": "manual_review_no_retry",
        }.get(state, "manual_review_required")

    def authorize(
        self,
        *,
        campaign_id: str,
        internal_id: str,
        confirmed_url: str,
        operator: str,
        confirmation: str,
        current_status: dict[str, Any],
        published: bool = False,
        captured: bool = False,
        blocked: bool = False,
        campaign_authorization_id: str | None = None,
        campaign_candidate_set_sha256: str | None = None,
        data_root: Path,
    ) -> str:
        if not operator.strip() or confirmation != AUTHORIZE_CONFIRMATION:
            raise MatchCampaignAuthorizationError(
                "Se requiere operador y confirmación humana de una sola adquisición"
            )
        directory = _campaign_dir(self.root, campaign_id)
        with self.lock.exclusive_lock():
            campaign, _manifest, _plan = self._read_campaign(directory)
            candidate = self._candidate(campaign, internal_id)
            source_generation_root = (
                data_root
                / "matches"
                / "generations"
                / campaign["source"]["generation_id"]
            )
            generation = load_verified_match_generation(
                source_generation_root, data_root=data_root
            )
            if (
                generation.manifest_sha256
                != campaign["source"]["generation_manifest_sha256"]
            ):
                raise MatchCampaignIntegrityError(
                    "No se puede revalidar la generación de origen"
                )
            current_state = (
                current_status.get("campaign", {})
                if isinstance(current_status.get("campaign"), dict)
                else current_status
            )
            current_eligible = current_status.get(
                "detail_status"
            ) == "played_pending_acquisition" or (
                current_status.get("detail_status") == "included_in_existing_campaign"
                and current_state.get("campaign_id") == campaign_id
                and current_state.get("campaign_version") == 2
                and current_state.get("state") == "NOT_AUTHORIZED"
            )
            same_match = all(
                current_status.get(key) == candidate.get(key)
                for key in (
                    "internal_id",
                    "source_match_id",
                    "group",
                    "home_team_id",
                    "away_team_id",
                    "reference_result",
                    "source_match_url",
                )
            )
            if (
                not current_eligible
                or not same_match
                or current_status.get("source_match_url")
                != candidate["source_match_url"]
                or confirmed_url != candidate["source_match_url"]
                or published
                or captured
                or blocked
            ):
                raise MatchCampaignAuthorizationError(
                    "El candidato ya no es elegible o la URL no coincide"
                )
            events = self._read_events(directory, campaign, internal_id)
            if events:
                raise MatchCampaignAuthorizationError(
                    "La autorización o el intento ya se consumió"
                )
            authorization_id = "match-detail-authorization-v2-" + uuid.uuid4().hex
            auth = {
                "authorization_id": authorization_id,
                "campaign_id": campaign_id,
                "proposal_id": campaign["proposal_id"],
                "proposal_sha256": campaign["proposal_sha256"],
                "plan_sha256": campaign["plan_sha256"],
                "inventory_id": campaign["source"]["inventory_id"],
                "inventory_sha256": campaign["source"]["inventory_sha256"],
                "source_generation_id": campaign["source"]["generation_id"],
                "source_generation_manifest_sha256": campaign["source"][
                    "generation_manifest_sha256"
                ],
                "internal_id": internal_id,
                "source_match_id": candidate["source_match_id"],
                "source_match_url": confirmed_url,
                "operator": operator.strip(),
                "authorized_at_utc": _now(),
                "maximum_navigations": 1,
                "automatic_retries": 0,
                "capture_promotion_enabled": False,
                "human_confirmation": confirmation,
            }
            if campaign_authorization_id is not None or campaign_candidate_set_sha256 is not None:
                if (
                    not isinstance(campaign_authorization_id, str)
                    or not campaign_authorization_id.startswith(
                        "campaign-authorization-"
                    )
                    or not _is_sha(campaign_candidate_set_sha256)
                ):
                    raise MatchCampaignAuthorizationError(
                        "La autorización de campaña requiere ID y hash completos"
                    )
                auth["campaign_authorization_id"] = campaign_authorization_id
                auth["campaign_candidate_set_sha256"] = (
                    campaign_candidate_set_sha256
                )
            self._append(
                directory,
                campaign,
                internal_id,
                {
                    "event_type": "AUTHORIZED",
                    "campaign_id": campaign_id,
                    "internal_id": internal_id,
                    "authorization": auth,
                },
            )
            return authorization_id

    def _execute(
        self,
        *,
        campaign_id: str,
        internal_id: str,
        authorization_id: str,
        confirmed_url: str,
        adapter: Any,
        store_root: Path,
        store_inventory: dict[str, Any],
        current_status: dict[str, Any],
        published: bool,
        captured: bool,
        blocked: bool,
    ) -> dict[str, Any]:
        directory = _campaign_dir(self.root, campaign_id)
        store = MatchDetailStore(store_root)
        with self.lock.exclusive_lock():
            with store.exclusive_lock():
                campaign, _manifest, _plan = self._read_campaign(directory)
                candidate = self._candidate(campaign, internal_id)
                events = self._read_events(directory, campaign, internal_id)
                if self._state(events) != "AUTHORIZED" or len(events) != 1:
                    raise MatchCampaignAuthorizationError(
                        "Solo se puede consumir una autorización nueva y no usada"
                    )
                auth = events[0]["authorization"]
                current_state = (
                    current_status.get("campaign", {})
                    if isinstance(current_status.get("campaign"), dict)
                    else current_status
                )
                current_eligible = current_status.get("detail_status") in {
                    "played_pending_acquisition",
                    "authorized_not_executed",
                } or (
                    current_status.get("detail_status")
                    == "included_in_existing_campaign"
                    and current_state.get("campaign_id") == campaign_id
                    and current_state.get("campaign_version") == 2
                    and current_state.get("state") == "AUTHORIZED"
                )
                same_match = all(
                    current_status.get(key) == candidate.get(key)
                    for key in (
                        "internal_id",
                        "source_match_id",
                        "group",
                        "home_team_id",
                        "away_team_id",
                        "reference_result",
                        "source_match_url",
                    )
                )
                if (
                    auth["authorization_id"] != authorization_id
                    or confirmed_url != auth["source_match_url"]
                    or confirmed_url != candidate["source_match_url"]
                    or not current_eligible
                    or not same_match
                    or current_status.get("source_match_url") != confirmed_url
                    or published
                    or captured
                    or blocked
                ):
                    raise MatchCampaignAuthorizationError(
                        "Autorización, URL o elegibilidad ya no válida"
                    )
                reconciliation = store.reconcile(store_inventory)
                if reconciliation.get("integrity_blocked"):
                    raise MatchCampaignIntegrityError(
                        "El almacén de capturas tiene corrupción"
                    )
                if internal_id in reconciliation.get("verified_by_internal_id", {}):
                    raise MatchCampaignAuthorizationError(
                        "Ya existe una captura válida para este partido"
                    )
                if any(
                    item.get("internal_id") == internal_id
                    and item.get("stop_acquisition", True)
                    for item in reconciliation.get("diagnostics", [])
                ):
                    raise MatchCampaignAuthorizationError(
                        "El candidato está detenido por un diagnóstico previo"
                    )
                attempt_id = uuid.uuid4().hex
                self._append(
                    directory,
                    campaign,
                    internal_id,
                    {
                        "event_type": "STARTED",
                        "campaign_id": campaign_id,
                        "internal_id": internal_id,
                        "attempt_id": attempt_id,
                        "authorization_id": authorization_id,
                        "started_at_utc": _now(),
                        "source_match_id": candidate["source_match_id"],
                        "requested_url": confirmed_url,
                        "maximum_navigations": 1,
                    },
                )
                try:
                    response = adapter.open(confirmed_url)
                except Exception as exc:
                    self._append(
                        directory,
                        campaign,
                        internal_id,
                        {
                            "event_type": "STOPPED",
                            "campaign_id": campaign_id,
                            "internal_id": internal_id,
                            "source_match_id": candidate["source_match_id"],
                            "requested_url": confirmed_url,
                            "authorization_id": authorization_id,
                            "attempt_id": attempt_id,
                            "stopped_at_utc": _now(),
                            "error_code": "ACCESS_EXCEPTION",
                            "error_type": type(exc).__name__,
                            "diagnostic": str(exc)[:1000],
                            "http_status": None,
                        },
                    )
                    return {
                        "status": "STOPPED",
                        "attempt_id": attempt_id,
                        "error_code": "ACCESS_EXCEPTION",
                    }
                errors = MatchDetailCampaignLedger._security_errors(candidate, response)
                if response.access_classification != "VALID":
                    errors.insert(0, "CONTENT_NOT_VERIFIED")
                if errors:
                    code = errors[0]
                    self._append(
                        directory,
                        campaign,
                        internal_id,
                        {
                            "event_type": "STOPPED",
                            "campaign_id": campaign_id,
                            "internal_id": internal_id,
                            "source_match_id": candidate["source_match_id"],
                            "requested_url": confirmed_url,
                            "authorization_id": authorization_id,
                            "attempt_id": attempt_id,
                            "stopped_at_utc": _now(),
                            "error_code": code,
                            "diagnostics": errors,
                            "http_status": response.http_status,
                            "final_url": response.final_url,
                            "access_classification": response.access_classification,
                        },
                    )
                    return {
                        "status": "STOPPED",
                        "attempt_id": attempt_id,
                        "error_code": code,
                    }
                if not isinstance(response.html, bytes) or not response.html.strip():
                    self._append(
                        directory,
                        campaign,
                        internal_id,
                        {
                            "event_type": "STOPPED",
                            "campaign_id": campaign_id,
                            "internal_id": internal_id,
                            "source_match_id": candidate["source_match_id"],
                            "requested_url": confirmed_url,
                            "authorization_id": authorization_id,
                            "attempt_id": attempt_id,
                            "stopped_at_utc": _now(),
                            "error_code": "EMPTY_HTML",
                            "http_status": response.http_status,
                            "final_url": response.final_url,
                        },
                    )
                    return {
                        "status": "STOPPED",
                        "attempt_id": attempt_id,
                        "error_code": "EMPTY_HTML",
                    }
                helper = MatchDetailCampaignLedger(self.root)
                artifact = helper._store_discovery_artifact_locked(
                    directory,
                    {
                        "campaign_id": campaign_id,
                        "source": {"inventory_id": campaign["source"]["inventory_id"]},
                    },
                    candidate,
                    response,
                    attempt_id,
                )
                self._append(
                    directory,
                    campaign,
                    internal_id,
                    {
                        "event_type": "DISCOVERY_REVIEW_REQUIRED",
                        "campaign_id": campaign_id,
                        "internal_id": internal_id,
                        "source_match_id": candidate["source_match_id"],
                        "attempt_id": attempt_id,
                        "resolved_at_utc": _now(),
                        "http_status": response.http_status,
                        "final_url": response.final_url,
                        "access_classification": response.access_classification,
                        "artifact": artifact,
                        "capture_promoted": False,
                        "semantic_validation_performed": False,
                    },
                )
                return {
                    "status": "DISCOVERY_REVIEW_REQUIRED",
                    "attempt_id": attempt_id,
                    "artifact": artifact,
                    "capture_promoted": False,
                }

    def execute_simulated(self, **kwargs: Any) -> dict[str, Any]:
        adapter = kwargs.get("adapter")
        if not isinstance(adapter, SimulatedMatchAccessAdapter):
            raise MatchCampaignAuthorizationError(
                "El modo simulado requiere SimulatedMatchAccessAdapter"
            )
        return self._execute(**kwargs)

    def execute_real(
        self,
        *,
        campaign_id: str,
        internal_id: str,
        authorization_id: str,
        confirmed_url: str,
        data_root: Path,
        profile_dir: Path,
        confirmation: str,
        player_browser_idle_confirmation: str,
        store_root: Path,
        store_inventory: dict[str, Any],
        current_status: dict[str, Any],
        published: bool,
        captured: bool,
        blocked: bool,
        session_factory: Any = None,
        access_runner: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        if (
            confirmation != EXECUTE_CONFIRMATION
            or player_browser_idle_confirmation != PLAYER_IDLE_CONFIRMATION
        ):
            raise MatchCampaignAuthorizationError(
                "Faltan confirmaciones explícitas para una navegación v2 única"
            )
        directory, campaign, _events = self._events(campaign_id, internal_id)
        candidate = self._candidate(campaign, internal_id)
        if confirmed_url != candidate["source_match_url"]:
            raise MatchCampaignAuthorizationError(
                "La URL no coincide con la propuesta inmutable"
            )
        data_root = data_root.expanduser().resolve(strict=True)
        requested = profile_dir.expanduser().absolute()
        cursor = requested
        while cursor != cursor.parent:
            if cursor.is_symlink():
                raise MatchCampaignAuthorizationError(
                    "El perfil dedicado no puede atravesar symlinks"
                )
            cursor = cursor.parent
        profile = requested.resolve()
        try:
            profile.relative_to(data_root)
        except ValueError as exc:
            raise MatchCampaignAuthorizationError(
                "El perfil del navegador debe estar bajo data_root"
            ) from exc
        if (
            profile == data_root
            or profile.name != f"match-detail-v2-{candidate['source_match_id']}"
        ):
            raise MatchCampaignAuthorizationError(
                "Se requiere un perfil aislado y dedicado al partido"
            )
        from football_data_hub.core.browser_runtime import BrowserRuntimeConfig
        from football_data_hub.core.browser_session import BrowserSessionManager
        from .real_acquisition import _open_real_once

        config = BrowserRuntimeConfig(
            profile_dir=profile,
            backend="seleniumbase-pure-cdp",
            browser="chromium",
            use_xvfb=True,
            start_url="about:blank",
        )
        runner = access_runner or _open_real_once
        factory = session_factory or BrowserSessionManager

        class OneShotAdapter:
            def open(self, url: str):
                if url != confirmed_url:
                    raise MatchCampaignAuthorizationError("URL no autorizada")
                return runner(config, url=url, session_factory=factory)

        return self._execute(
            campaign_id=campaign_id,
            internal_id=internal_id,
            authorization_id=authorization_id,
            confirmed_url=confirmed_url,
            adapter=OneShotAdapter(),
            store_root=store_root,
            store_inventory=store_inventory,
            current_status=current_status,
            published=published,
            captured=captured,
            blocked=blocked,
        )

    def validate_offline_artifact(
        self, *, campaign_id: str, internal_id: str, data_root: Path
    ) -> dict[str, Any]:
        from .campaign_artifact import parse_campaign_saved_artifact
        from .semantic_parser import PARSER_VERSION

        directory, campaign, events = self._events(campaign_id, internal_id)
        if self._state(events) != "DISCOVERY_REVIEW_REQUIRED":
            raise MatchCampaignAuthorizationError(
                "No hay artefacto pendiente de validación"
            )
        discovery = events[-1]
        artifact = directory / discovery["artifact"]["artifact_relative_path"]
        data_root = data_root.expanduser().resolve(strict=True)
        generation_root = (
            data_root / "matches" / "generations" / campaign["source"]["generation_id"]
        )
        generation = load_verified_match_generation(
            generation_root, data_root=data_root
        )
        inventory = build_match_detail_inventory(generation)
        candidates = [
            row for row in inventory["matches"] if row["internal_id"] == internal_id
        ]
        if len(candidates) != 1:
            raise MatchCampaignIntegrityError("MATCH-00 no contiene un candidato único")
        try:
            observation = parse_campaign_saved_artifact(
                artifact,
                expected_match=candidates[0],
                verified_generation=generation,
                data_root=data_root,
                parser_version=PARSER_VERSION,
            )
            validation = dataclasses.asdict(observation.validation)
            valid = observation.validation.semantic_valid is True
            diagnostic = None
            parser_version = observation.source.parser_version
        except Exception as exc:
            validation = {
                "error_type": type(exc).__name__,
                "diagnostic": str(exc)[:1000],
            }
            valid = False
            diagnostic = str(exc)[:500]
            parser_version = PARSER_VERSION
        validation["parser_version"] = parser_version
        evidence = {
            "source_html_sha256": discovery["artifact"]["source_html_sha256"],
            "semantic_valid": valid,
            "validation": validation,
            "parser_version": parser_version,
            "validated_at_utc": _now(),
        }
        evidence["evidence_sha256"] = _sha(_canonical(evidence))
        if diagnostic:
            evidence["diagnostic"] = diagnostic
        event_type = "VALIDATED" if valid else "VALIDATION_FAILED"
        with self.lock.exclusive_lock():
            current_directory, current_campaign, current_events = self._events(
                campaign_id, internal_id
            )
            if (
                self._state(current_events) != "DISCOVERY_REVIEW_REQUIRED"
                or not current_events
                or current_events[-1].get("event_sha256")
                != events[-1].get("event_sha256")
            ):
                raise MatchCampaignAuthorizationError(
                    "El estado o artefacto cambió durante la validación offline"
                )
            self._append(
                current_directory,
                current_campaign,
                internal_id,
                {
                    "event_type": event_type,
                    "campaign_id": campaign_id,
                    "internal_id": internal_id,
                    **evidence,
                },
            )
        return {"status": event_type, "internal_id": internal_id, **evidence}

    def revalidate_failed_artifact(
        self,
        *,
        campaign_id: str,
        internal_id: str,
        data_root: Path,
        operator: str,
        confirmation: str,
    ) -> dict[str, Any]:
        """Re-run semantic validation on the immutable saved artifact only.

        This operation is deliberately separate from initial validation: it
        requires an operator confirmation, binds the new result to the latest
        failed event and original HTML hash, and can never consume navigation
        authorization or alter the capture.
        """

        from .campaign_artifact import parse_campaign_saved_artifact
        from .semantic_parser import PARSER_VERSION

        operator = operator.strip() if isinstance(operator, str) else ""
        if not operator or confirmation != REVALIDATE_CONFIRMATION:
            raise MatchCampaignAuthorizationError(
                "La revalidación requiere operador y confirmación explícita"
            )
        data_root = data_root.expanduser().resolve(strict=True)
        with self.lock.exclusive_lock():
            directory, campaign, events = self._events(campaign_id, internal_id)
            state = self._state(events)
            if state not in {"VALIDATION_FAILED", "REVALIDATION_FAILED"}:
                raise MatchCampaignAuthorizationError(
                    f"Solo se revalidan fallos semánticos sin resolver; estado={state}"
                )
            failure = events[-1]
            if (
                failure.get("semantic_valid") is not False
                or not _is_sha(failure.get("evidence_sha256"))
            ):
                raise MatchCampaignIntegrityError(
                    "El último fallo no contiene evidencia semántica verificable"
                )
            discovery = next(
                (
                    item
                    for item in events
                    if item["event_type"] == "DISCOVERY_REVIEW_REQUIRED"
                ),
                None,
            )
            if discovery is None:
                raise MatchCampaignIntegrityError(
                    "No existe adquisición original para revalidar"
                )
            artifact_reference = discovery["artifact"]
            if failure.get("source_html_sha256") != artifact_reference.get(
                "source_html_sha256"
            ):
                raise MatchCampaignIntegrityError(
                    "El fallo no está ligado al HTML de la captura original"
                )
            artifact = directory / artifact_reference["artifact_relative_path"]
            failure_event_sha256 = failure["event_sha256"]
            source_generation_id = campaign["source"]["generation_id"]
            source_generation_sha256 = campaign["source"][
                "generation_manifest_sha256"
            ]

        # Parse outside the campaign lock. parse_campaign_saved_artifact reads
        # the same ledger for integrity and acquires its own lock while doing so.
        # We compare the failure event again before appending to reject a racing
        # revalidation without serializing the parser behind a nested flock.
        generation_root = (
            data_root / "matches" / "generations" / source_generation_id
        )
        generation = load_verified_match_generation(
            generation_root, data_root=data_root
        )
        if (
            generation.generation_id != source_generation_id
            or generation.manifest_sha256 != source_generation_sha256
        ):
            raise MatchCampaignIntegrityError(
                "La generación histórica de la campaña no coincide"
            )
        inventory = build_match_detail_inventory(generation)
        candidates = [
            row for row in inventory["matches"] if row["internal_id"] == internal_id
        ]
        if len(candidates) != 1:
            raise MatchCampaignIntegrityError(
                "La generación histórica no contiene un candidato único"
            )
        parser_version = PARSER_VERSION
        try:
            observation = parse_campaign_saved_artifact(
                artifact,
                expected_match=candidates[0],
                verified_generation=generation,
                data_root=data_root,
                parser_version=parser_version,
            )
            validation = dataclasses.asdict(observation.validation)
            valid = observation.validation.semantic_valid is True
            diagnostic = None
            parser_version = observation.source.parser_version
        except Exception as exc:
            validation = {
                "error_type": type(exc).__name__,
                "diagnostic": str(exc)[:1000],
                "semantic_valid": False,
            }
            valid = False
            diagnostic = str(exc)[:500]
        validation["parser_version"] = parser_version
        evidence = {
            "based_on_event_sha256": failure_event_sha256,
            "artifact_id": artifact_reference["artifact_id"],
            "source_html_sha256": artifact_reference["source_html_sha256"],
            "semantic_valid": valid,
            "validation": validation,
            "parser_version": parser_version,
            "operator": operator,
            "human_confirmation": confirmation,
            "validated_at_utc": _now(),
        }
        evidence["evidence_sha256"] = _sha(_canonical(evidence))
        if diagnostic:
            evidence["diagnostic"] = diagnostic
        event_type = "REVALIDATED" if valid else "REVALIDATION_FAILED"
        with self.lock.exclusive_lock():
            current_directory, current_campaign, current_events = self._events(
                campaign_id, internal_id
            )
            current_state = self._state(current_events)
            if (
                current_state not in {"VALIDATION_FAILED", "REVALIDATION_FAILED"}
                or not current_events
                or current_events[-1].get("event_sha256") != failure_event_sha256
            ):
                raise MatchCampaignAuthorizationError(
                    "El fallo cambió durante la revalidación; no se añadió ningún evento"
                )
            self._append(
                current_directory,
                current_campaign,
                internal_id,
                {
                    "event_type": event_type,
                    "campaign_id": campaign_id,
                    "internal_id": internal_id,
                    **evidence,
                },
            )
        return {"status": event_type, "internal_id": internal_id, **evidence}

    def _publication_inputs(
        self,
        *,
        data_root: Path,
        generation_root: Path,
        player_inventory_root: Path,
        player_compact_root: Path,
        player_team_captures_root: Path,
        player_published_index_path: Path,
    ):
        from football_data_hub_api.match_results_dataset import (
            load_match_results_dataset,
        )
        from football_data_hub_api.player_dataset import load_player_directory

        data_root = data_root.expanduser().resolve(strict=True)
        generation_root = generation_root.expanduser().resolve(strict=True)
        bundle = load_match_results_dataset(generation_root, data_root=data_root)
        players = load_player_directory(
            inventory_root=player_inventory_root,
            compact_root=player_compact_root,
            team_captures_root=player_team_captures_root,
            published_index_path=player_published_index_path,
        )
        return data_root, generation_root, bundle, set(players.players_by_id)

    def prepare_draft(
        self,
        *,
        campaign_id: str,
        internal_id: str,
        data_root: Path,
        generation_root: Path,
        player_inventory_root: Path,
        player_compact_root: Path,
        player_team_captures_root: Path,
        player_published_index_path: Path,
    ) -> dict[str, Any]:
        from football_data_hub_api.match_details_dataset import (
            _canonical_json,
            build_campaign_publication_draft,
            write_immutable_publication_json,
        )

        directory, campaign, events = self._events(campaign_id, internal_id)
        state = self._state(events)
        if state not in {"VALIDATED", "REVALIDATED", "DRAFT_PREPARED"}:
            raise MatchCampaignAuthorizationError(
                f"No se puede preparar borrador desde {state}"
            )
        data_root, generation_root, bundle, player_ids = self._publication_inputs(
            data_root=data_root,
            generation_root=generation_root,
            player_inventory_root=player_inventory_root,
            player_compact_root=player_compact_root,
            player_team_captures_root=player_team_captures_root,
            player_published_index_path=player_published_index_path,
        )
        discovery = next(
            item for item in events if item["event_type"] == "DISCOVERY_REVIEW_REQUIRED"
        )
        draft = build_campaign_publication_draft(
            internal_id=internal_id,
            campaign_id=campaign_id,
            artifact_id=discovery["artifact"]["artifact_id"],
            generation_root=generation_root,
            data_root=data_root,
            match_bundle=bundle,
            player_ids=player_ids,
            internal_ids={internal_id},
        )
        validated = next(
            item
            for item in reversed(events)
            if item["event_type"] in {"VALIDATED", "REVALIDATED"}
        )
        if draft.get("semantic_valid") is not True or draft.get(
            "source_html_sha256"
        ) != validated.get("source_html_sha256"):
            raise MatchCampaignIntegrityError(
                "El borrador no coincide con la validación semántica"
            )
        review_root = self.root.parent / "review" / "v2" / campaign_id
        source_match_id = self._candidate(campaign, internal_id)["source_match_id"]
        path = review_root / f"{source_match_id}-draft.json"
        expected_raw = _canonical_json(draft) + b"\n"
        with self.lock.exclusive_lock():
            directory, campaign, current_events = self._events(campaign_id, internal_id)
            current_state = self._state(current_events)
            if current_state not in {"VALIDATED", "REVALIDATED", "DRAFT_PREPARED"}:
                raise MatchCampaignAuthorizationError(
                    f"No se puede guardar borrador desde {current_state}"
                )
            if path.exists():
                if (
                    path.is_symlink()
                    or not path.is_file()
                    or path.read_bytes() != expected_raw
                ):
                    raise MatchCampaignIntegrityError(
                        "El borrador inmutable existente difiere"
                    )
            else:
                write_immutable_publication_json(path, draft)
            raw = path.read_bytes()
            event = {
                "event_type": "DRAFT_PREPARED",
                "campaign_id": campaign_id,
                "internal_id": internal_id,
                "draft_path": path.relative_to(data_root).as_posix(),
                "draft_sha256": _sha(raw),
                "source_html_sha256": draft["source_html_sha256"],
                "details_sha256": draft["details_sha256"],
            }
            if current_state in {"VALIDATED", "REVALIDATED"}:
                self._append(directory, campaign, internal_id, event)
            elif current_events[-1].get("draft_sha256") != event["draft_sha256"]:
                raise MatchCampaignIntegrityError(
                    "El borrador anterior difiere y no se sobrescribe"
                )
        return {
            "status": "DRAFT_PREPARED",
            "draft_path": str(path),
            "draft_sha256": event["draft_sha256"],
            "details_sha256": draft["details_sha256"],
        }

    def approve_draft(
        self,
        *,
        campaign_id: str,
        internal_id: str,
        draft_path: Path,
        approved_by: str,
        confirm_internal_id: str,
        confirm_source_html_sha256: str,
        confirm_details_sha256: str,
        confirm_action: str,
        data_root: Path,
    ) -> dict[str, Any]:
        from football_data_hub_api.match_details_dataset import (
            build_campaign_approval_receipt,
            campaign_approval_confirmation,
            write_immutable_publication_json,
        )

        data_root = data_root.expanduser().resolve(strict=True)
        with self.lock.exclusive_lock():
            directory, campaign, events = self._events(campaign_id, internal_id)
            state = self._state(events)
            if state == "DOCUMENT_APPROVED":
                prior = events[-1]
                if (
                    prior.get("approved_by") == approved_by.strip()
                    and confirm_internal_id == internal_id
                    and prior.get("source_html_sha256") == confirm_source_html_sha256
                    and prior.get("details_sha256") == confirm_details_sha256
                    and prior.get("approval_confirmation") == confirm_action
                    and prior.get("human_confirmation") is True
                ):
                    return {
                        "status": "DOCUMENT_ALREADY_APPROVED",
                        "idempotent": True,
                        "approval_path": str(data_root / prior["approval_path"]),
                        "approval_sha256": prior["approval_sha256"],
                    }
                raise MatchCampaignAuthorizationError(
                    "La aprobación ya fue registrada con otra evidencia"
                )
            if state != "DRAFT_PREPARED":
                raise MatchCampaignAuthorizationError(
                    "El borrador no está pendiente de aprobación"
                )
            prepared = events[-1]
            path = data_root / prepared["draft_path"]
            if (
                path.resolve(strict=True)
                != draft_path.expanduser().resolve(strict=True)
                or _file_hash(path) != prepared["draft_sha256"]
            ):
                raise MatchCampaignIntegrityError(
                    "El borrador cambió desde su preparación"
                )
            draft = json.loads(path.read_text(encoding="utf-8"))
            output = path.with_name(
                path.name.removesuffix("-draft.json") + "-approval.json"
            )
            if output.exists():
                if output.is_symlink() or not output.is_file():
                    raise MatchCampaignIntegrityError(
                        "El recibo de aprobación existente no es regular"
                    )
                try:
                    existing = json.loads(output.read_bytes())
                    approved_at = datetime.fromisoformat(
                        str(existing["approved_at_utc"]).replace("Z", "+00:00")
                    )
                except (
                    OSError,
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                    KeyError,
                    ValueError,
                ) as exc:
                    raise MatchCampaignIntegrityError(
                        "El recibo pendiente no se puede verificar"
                    ) from exc
                receipt = build_campaign_approval_receipt(
                    draft,
                    approved_by=approved_by,
                    confirm_internal_id=confirm_internal_id,
                    confirm_source_html_sha256=confirm_source_html_sha256,
                    confirm_details_sha256=confirm_details_sha256,
                    confirm_action=confirm_action,
                    approved_at_utc=approved_at,
                )
                if existing != receipt:
                    raise MatchCampaignIntegrityError(
                        "El recibo huérfano no coincide con esta aprobación explícita"
                    )
            else:
                receipt = build_campaign_approval_receipt(
                    draft,
                    approved_by=approved_by,
                    confirm_internal_id=confirm_internal_id,
                    confirm_source_html_sha256=confirm_source_html_sha256,
                    confirm_details_sha256=confirm_details_sha256,
                    confirm_action=confirm_action,
                )
                write_immutable_publication_json(output, receipt)
            raw = output.read_bytes()
            self._append(
                directory,
                campaign,
                internal_id,
                {
                    "event_type": "DOCUMENT_APPROVED",
                    "campaign_id": campaign_id,
                    "internal_id": internal_id,
                    "approval_path": output.relative_to(data_root).as_posix(),
                    "approval_sha256": _sha(raw),
                    "approved_by": receipt["approved_by"],
                    "human_confirmation": True,
                    "approval_confirmation": campaign_approval_confirmation(draft),
                    "details_sha256": receipt["details_sha256"],
                    "source_html_sha256": receipt["source_html_sha256"],
                },
            )
        return {
            "status": "DOCUMENT_APPROVED",
            "approval_path": str(output),
            "approval_sha256": _sha(raw),
        }

    def publish(
        self,
        *,
        campaign_id: str,
        internal_id: str,
        data_root: Path,
        generation_root: Path,
        published_root: Path,
        store_root: Path,
        player_inventory_root: Path,
        player_compact_root: Path,
        player_team_captures_root: Path,
        player_published_index_path: Path,
    ) -> dict[str, Any]:
        from football_data_hub_api.match_details_dataset import (
            load_published_match_details,
            publish_campaign_match_detail_draft,
        )

        directory, campaign, events = self._events(campaign_id, internal_id)
        if self._state(events) != "DOCUMENT_APPROVED":
            raise MatchCampaignAuthorizationError(
                "No se puede publicar sin aprobación humana individual"
            )
        prepared = next(
            item for item in events if item["event_type"] == "DRAFT_PREPARED"
        )
        approved = next(
            item for item in events if item["event_type"] == "DOCUMENT_APPROVED"
        )
        data_root, generation_root, bundle, player_ids = self._publication_inputs(
            data_root=data_root,
            generation_root=generation_root,
            player_inventory_root=player_inventory_root,
            player_compact_root=player_compact_root,
            player_team_captures_root=player_team_captures_root,
            player_published_index_path=player_published_index_path,
        )
        draft_path, approval_path = (
            data_root / prepared["draft_path"],
            data_root / approved["approval_path"],
        )
        if (
            _file_hash(draft_path) != prepared["draft_sha256"]
            or _file_hash(approval_path) != approved["approval_sha256"]
        ):
            raise MatchCampaignIntegrityError("Borrador o aprobación alterados")
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        result = publish_campaign_match_detail_draft(
            draft,
            approval_receipt=approval,
            published_root=published_root,
            store_root=store_root,
            generation_root=generation_root,
            data_root=data_root,
            match_bundle=bundle,
            player_ids=player_ids,
        )
        loaded = load_published_match_details(
            published_root,
            store_root=store_root,
            generation_root=generation_root,
            data_root=data_root,
            match_bundle=bundle,
            player_ids=player_ids,
            internal_ids={internal_id},
        )
        if internal_id not in loaded:
            raise MatchCampaignIntegrityError(
                "La publicación no es legible tras su escritura"
            )
        entry = next(
            item
            for item in json.loads((published_root / "index.json").read_bytes())[
                "publications"
            ]
            if item["internal_id"] == internal_id
        )
        manifest_path = published_root / entry["package_path"] / "manifest.json"
        manifest_sha = _file_hash(manifest_path)
        with self.lock.exclusive_lock():
            directory, campaign, current_events = self._events(campaign_id, internal_id)
            current_state = self._state(current_events)
            if current_state in {"PUBLISHED", "REVIEW_COMPLETED"}:
                prior = next(
                    item for item in current_events if item["event_type"] == "PUBLISHED"
                )
                if (
                    prior.get("publication_manifest_sha256") == manifest_sha
                    and prior.get("details_sha256") == approved["details_sha256"]
                ):
                    return {
                        "status": "PUBLISHED_ALREADY_RECORDED",
                        "idempotent": True,
                        **result,
                        "publication_manifest_sha256": manifest_sha,
                    }
                raise MatchCampaignIntegrityError(
                    "La publicación existente difiere del ledger v2"
                )
            if current_state != "DOCUMENT_APPROVED":
                raise MatchCampaignAuthorizationError(
                    f"La campaña cambió durante la publicación: {current_state}"
                )
            self._append(
                directory,
                campaign,
                internal_id,
                {
                    "event_type": "PUBLISHED",
                    "campaign_id": campaign_id,
                    "internal_id": internal_id,
                    "publication_id": result["publication_id"],
                    "publication_manifest_sha256": manifest_sha,
                    "details_sha256": approved["details_sha256"],
                    "approval_sha256": approved["approval_sha256"],
                    "published_at_utc": _now(),
                },
            )
        return {
            "status": "PUBLISHED",
            **result,
            "publication_manifest_sha256": manifest_sha,
        }

    def verify_publication(
        self, *, campaign_id: str, internal_id: str, **kwargs: Any
    ) -> dict[str, Any]:
        directory, campaign, events = self._events(campaign_id, internal_id)
        if self._state(events) not in {"PUBLISHED", "REVIEW_COMPLETED"}:
            raise MatchCampaignAuthorizationError(
                "No hay publicación registrada para verificar"
            )
        expected = next(item for item in events if item["event_type"] == "PUBLISHED")
        result = self._load_publication(
            campaign_id=campaign_id, internal_id=internal_id, **kwargs
        )
        if (
            result["publication_manifest_sha256"]
            != expected["publication_manifest_sha256"]
        ):
            raise MatchCampaignIntegrityError("El paquete publicado difiere del ledger")
        return {"status": "PUBLISHED_VERIFIED", **result}

    def _load_publication(
        self,
        *,
        campaign_id: str,
        internal_id: str,
        data_root: Path,
        generation_root: Path,
        published_root: Path,
        store_root: Path,
        player_inventory_root: Path,
        player_compact_root: Path,
        player_team_captures_root: Path,
        player_published_index_path: Path,
    ) -> dict[str, Any]:
        from football_data_hub_api.match_details_dataset import (
            CAMPAIGN_PACKAGE_SCHEMA,
            MatchDetailsLoadError,
            _read_json,
            _validated_index_entries,
            load_published_match_details,
        )

        _directory, _campaign, events = self._events(campaign_id, internal_id)
        approved_events = [
            event for event in events if event["event_type"] == "DOCUMENT_APPROVED"
        ]
        published_events = [
            event for event in events if event["event_type"] == "PUBLISHED"
        ]
        if len(approved_events) != 1 or len(published_events) != 1:
            raise MatchCampaignIntegrityError(
                "La publicación no tiene una aprobación y un evento PUBLISHED únicos"
            )
        approved = approved_events[0]
        published = published_events[0]
        if (
            approved.get("internal_id") != internal_id
            or published.get("internal_id") != internal_id
        ):
            raise MatchCampaignIntegrityError(
                "La identidad del partido no coincide con los eventos del ledger"
            )

        data_root, generation_root, bundle, player_ids = self._publication_inputs(
            data_root=data_root,
            generation_root=generation_root,
            player_inventory_root=player_inventory_root,
            player_compact_root=player_compact_root,
            player_team_captures_root=player_team_captures_root,
            player_published_index_path=player_published_index_path,
        )
        try:
            loaded = load_published_match_details(
                published_root,
                store_root=store_root,
                generation_root=generation_root,
                data_root=data_root,
                match_bundle=bundle,
                player_ids=player_ids,
                internal_ids={internal_id},
            )
        except Exception as exc:
            raise MatchCampaignIntegrityError(
                f"El paquete publicado no supera su carga íntegra: {exc}"
            ) from exc
        if internal_id not in loaded:
            raise MatchCampaignIntegrityError("Partido ausente del índice publicado")
        document = loaded[internal_id]
        if (
            getattr(document, "internal_id", None) != internal_id
            or getattr(document, "publication_status", None) != "approved"
            or getattr(document, "source", None) != "BDFutbol"
        ):
            raise MatchCampaignIntegrityError(
                "El documento cargado no corresponde a la publicación aprobada"
            )

        try:
            index, _index_raw = _read_json(Path(published_root) / "index.json")
            entries = _validated_index_entries(index)
            rows = [item for item in entries if item["internal_id"] == internal_id]
            if len(rows) != 1:
                raise MatchCampaignIntegrityError(
                    "El índice no contiene una referencia única para el partido"
                )
            row = rows[0]
            if row["publication_id"] != published.get("publication_id"):
                raise MatchCampaignIntegrityError(
                    "El publication_id no coincide entre índice y evento PUBLISHED"
                )
            if (
                row["manifest_sha256"]
                != published.get("publication_manifest_sha256")
            ):
                raise MatchCampaignIntegrityError(
                    "El hash del manifiesto difiere entre índice y evento PUBLISHED"
                )

            package = Path(published_root) / "packages" / row["publication_id"]
            manifest_path = package / "manifest.json"
            details_path = package / "details.json"
            approval_path = package / "approval.json"
            if any(
                path.is_symlink() or not path.is_file()
                for path in (manifest_path, details_path, approval_path)
            ):
                raise MatchCampaignIntegrityError(
                    "Falta un archivo regular del paquete publicado"
                )
            manifest, manifest_raw = _read_json(manifest_path)
            details_payload, details_raw = _read_json(details_path)
            approval_receipt, approval_raw = _read_json(approval_path)
        except MatchCampaignIntegrityError:
            raise
        except (MatchDetailsLoadError, OSError, TypeError, ValueError, KeyError) as exc:
            raise MatchCampaignIntegrityError(
                f"No se puede verificar el índice o paquete publicado: {exc}"
            ) from exc

        manifest_sha = _sha(manifest_raw)
        details_sha = manifest.get("details_sha256")
        if (
            manifest_sha != row["manifest_sha256"]
            or manifest_sha != published.get("publication_manifest_sha256")
        ):
            raise MatchCampaignIntegrityError(
                "El hash del manifiesto del paquete no coincide con índice y ledger"
            )
        if (
            manifest.get("schema_version") != CAMPAIGN_PACKAGE_SCHEMA
            or manifest.get("internal_id") != internal_id
            or manifest.get("publication_id") != row["publication_id"]
            or getattr(document, "source_match_id", None)
            != manifest.get("source_match_id")
            or not _is_sha(details_sha)
            or details_sha != _sha(details_raw)
            or details_sha != published.get("details_sha256")
            or details_sha != approved.get("details_sha256")
            or approval_receipt.get("publication_id") != row["publication_id"]
            or approval_receipt.get("internal_id") != internal_id
            or approval_receipt.get("details_sha256") != details_sha
            or approval_receipt.get("approved_by") != approved.get("approved_by")
            or approval_receipt.get("approval_confirmation")
            != approved.get("approval_confirmation")
            or approval_receipt.get("source_html_sha256")
            != approved.get("source_html_sha256")
            or manifest.get("approval_sha256") != _sha(approval_raw)
            or details_payload.get("internal_id") != internal_id
        ):
            raise MatchCampaignIntegrityError(
                "El manifiesto, recibo, documento y eventos del ledger no coinciden"
            )
        return {
            "internal_id": internal_id,
            "publication_id": row["publication_id"],
            "publication_manifest_sha256": manifest_sha,
            "details_sha256": details_sha,
        }

    def complete_review(
        self,
        *,
        campaign_id: str,
        internal_id: str,
        reviewer: str,
        confirmation: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from .campaign import review_completion_confirmation

        directory, campaign, events = self._events(campaign_id, internal_id)
        state = self._state(events)
        if state not in {"PUBLISHED", "REVIEW_COMPLETED"}:
            raise MatchCampaignAuthorizationError(
                "Solo se cierra una publicación verificada"
            )
        verified = self.verify_publication(
            campaign_id=campaign_id, internal_id=internal_id, **kwargs
        )
        discovery = next(
            item for item in events if item["event_type"] == "DISCOVERY_REVIEW_REQUIRED"
        )
        expected = review_completion_confirmation(
            str(
                next(
                    item
                    for item in campaign["candidates"]
                    if item["internal_id"] == internal_id
                )["source_match_id"]
            ),
            discovery["artifact"]["source_html_sha256"],
            next(item for item in events if item["event_type"] == "DOCUMENT_APPROVED")[
                "details_sha256"
            ],
        )
        if not reviewer.strip() or confirmation != expected:
            raise MatchCampaignAuthorizationError(
                "El revisor y confirmación hash-específica son obligatorios"
            )
        if state == "REVIEW_COMPLETED":
            prior = events[-1]
            if (
                prior.get("reviewer") == reviewer.strip()
                and prior.get("human_confirmation") == confirmation
            ):
                return {
                    **verified,
                    "status": "REVIEW_ALREADY_COMPLETED",
                    "idempotent": True,
                }
            raise MatchCampaignAuthorizationError(
                "El cierre previo tiene otra identidad/evidencia"
            )
        with self.lock.exclusive_lock():
            directory, campaign, current_events = self._events(campaign_id, internal_id)
            current_state = self._state(current_events)
            if current_state == "REVIEW_COMPLETED":
                prior = current_events[-1]
                if (
                    prior.get("reviewer") == reviewer.strip()
                    and prior.get("human_confirmation") == confirmation
                ):
                    return {
                        **verified,
                        "status": "REVIEW_ALREADY_COMPLETED",
                        "idempotent": True,
                    }
                raise MatchCampaignAuthorizationError(
                    "El cierre concurrente tiene otra identidad/evidencia"
                )
            if current_state != "PUBLISHED":
                raise MatchCampaignAuthorizationError(
                    f"La campaña cambió durante el cierre: {current_state}"
                )
            self._append(
                directory,
                campaign,
                internal_id,
                {
                    "event_type": "REVIEW_COMPLETED",
                    "campaign_id": campaign_id,
                    "internal_id": internal_id,
                    "reviewer": reviewer.strip(),
                    "human_confirmation": confirmation,
                    "publication_manifest_sha256": verified[
                        "publication_manifest_sha256"
                    ],
                    "completed_at_utc": _now(),
                    "historic_acquisition_state": "DISCOVERY_REVIEW_REQUIRED",
                    "capture_promoted": False,
                },
            )
        return {**verified, "status": "REVIEW_COMPLETED"}


class _null_context:
    def __enter__(self):
        return None

    def __exit__(self, *_args):
        return False
