"""Strict, read-only loader for separately approved match-detail publications."""

from __future__ import annotations

import hashlib
import json
import os
import re
import fcntl
import shutil
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any
from urllib.parse import urlsplit

from football_data_hub.domain.matches.details import (
    MatchDetail,
    MatchEvent,
    MatchPlayerAppearance,
    MatchTeam,
    validate_match_detail_contract,
)
from football_data_hub.providers.bdfutbol.match_details.inventory import (
    MatchDetailInventoryError,
    build_match_detail_inventory,
    load_verified_match_generation,
)
from football_data_hub.providers.bdfutbol.classification.generation_activation import (
    MatchGenerationActivationError,
    resolve_match_generation_root,
)
from football_data_hub.providers.bdfutbol.match_details.campaign_artifact import (
    parse_campaign_saved_artifact,
)
from football_data_hub.providers.bdfutbol.match_details.store import (
    MatchDetailStore,
    MatchDetailStoreError,
)
from football_data_hub.providers.bdfutbol.match_details.semantic_parser import (
    parse_saved_artifact,
)
from football_data_hub_api.match_results_dataset import MatchResultsBundle, build_match_page
from football_data_hub_api.schemas import (
    MatchPageRecordResponse,
    MatchPublishedDetailsResponse,
    MatchPublishedEventResponse,
    MatchPublishedPlayerResponse,
    MatchPublishedSideResponse,
    MatchPageResponse,
)

INDEX_SCHEMA = "football_data_hub.match_detail_publication_index.v1"
PACKAGE_SCHEMA = "football_data_hub.match_detail_publication.v1"
APPROVAL_SCHEMA = "football_data_hub.match_detail_publication_approval.v1"
DRAFT_SCHEMA = "football_data_hub.match_detail_publication_draft.v1"
CAMPAIGN_PACKAGE_SCHEMA = "football_data_hub.match_detail_campaign_publication.v1"
CAMPAIGN_APPROVAL_SCHEMA = "football_data_hub.match_detail_campaign_approval.v1"
AUTO_POLICY_RECEIPT_SCHEMA = "football_data_hub.match_detail_auto_policy_receipt.v1"
LEGACY_RECOVERY_PACKAGE_SCHEMA = "football_data_hub.match_detail_legacy_recovery_publication.v1"
LEGACY_RECOVERY_DRAFT_SCHEMA = "football_data_hub.match_detail_legacy_recovery_publication_draft.v1"
LEGACY_RECOVERY_AUTO_RECEIPT_SCHEMA = "football_data_hub.match_detail_legacy_recovery_auto_policy_receipt.v1"
CAMPAIGN_DRAFT_SCHEMA = "football_data_hub.match_detail_campaign_publication_draft.v1"
_PUBLICATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CAMPAIGN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ARTIFACT_ID = re.compile(r"^discovery-[A-Za-z0-9._-]{1,120}$")


class MatchDetailsLoadError(ValueError):
    """A publication is malformed, unapproved, corrupt, or mismatched."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _automatic_policy_validation_from_observation(observation: Any) -> dict[str, Any]:
    """Rebuild the exact validation envelope persisted by automatic campaigns."""
    validation = json.loads(_canonical_json(asdict(observation.validation)))
    parser_version = getattr(observation.source, "parser_version", None)
    if not isinstance(parser_version, str) or not parser_version:
        raise MatchDetailsLoadError("La observación no conserva la versión del parser.")
    validation["parser_version"] = parser_version
    return validation


def _legacy_recovery_canonical_json(value: Any) -> bytes:
    """Canonical encoding used by the immutable historical recovery bundle."""
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _atomic_bytes(path: Path, content: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatchDetailsLoadError(f"No se puede leer JSON de publicación: {path}") from exc
    if not isinstance(value, dict):
        raise MatchDetailsLoadError(f"El JSON de publicación debe ser un objeto: {path}")
    return value, raw


def _regular_file_bytes(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise MatchDetailsLoadError(f"{label} ausente o no es un archivo regular.")
    try:
        path.resolve(strict=True).relative_to(path.parent.resolve(strict=True))
        return path.read_bytes()
    except (OSError, ValueError) as exc:
        raise MatchDetailsLoadError(f"No se puede leer {label} de forma segura.") from exc


def _safe_root(root: Path) -> Path:
    absolute = root.expanduser().absolute()
    cursor = absolute
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise MatchDetailsLoadError(f"La ruta de publicación contiene un symlink: {cursor}")
        cursor = cursor.parent
    return absolute


def _published_match(bundle: MatchResultsBundle, internal_id: str) -> MatchPageRecordResponse:
    for group in bundle.bootstrap.groups.values():
        for match in group.matches:
            if match.internal_id == internal_id:
                home = next((team for team in group.teams if team.team_id == match.home_team_id), None)
                away = next((team for team in group.teams if team.team_id == match.away_team_id), None)
                if home is None or away is None:
                    raise MatchDetailsLoadError("El partido apunta a un equipo ausente de MATCH-00.")
                return MatchPageRecordResponse(
                    internal_id=match.internal_id,
                    source_match_id=match.source_match_id,
                    matchday=match.matchday,
                    matchday_date=match.matchday_date,
                    source_match_date=match.source_match_date,
                    home_team=home.model_dump(),
                    away_team=away.model_dump(),
                    home_goals=match.home_goals,
                    away_goals=match.away_goals,
                    status=match.status,
                    unplayed_state=match.unplayed_state,
                    stadium_name=match.stadium_name,
                    stadium_url=match.stadium_url,
                    referee_name=match.referee_name,
                    referee_url=match.referee_url,
                    source_match_url=match.source_match_url,
                )
    raise MatchDetailsLoadError("La publicación referencia un partido ausente de MATCH-00.")


def _source_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "www.bdfutbol.com" or parsed.username or parsed.password:
        raise MatchDetailsLoadError("Una ficha de detalle contiene un enlace externo no permitido.")
    return value


def _minute(event: MatchEvent) -> str | None:
    if event.minute_literal:
        return event.minute_literal
    if event.minute_base is None:
        return None
    return f"{event.minute_base}+{event.minute_added}" if event.minute_added is not None else str(event.minute_base)


def _player(
    appearance: MatchPlayerAppearance,
    *,
    expected_role: str,
    player_ids: set[int],
) -> MatchPublishedPlayerResponse:
    if appearance.role != expected_role:
        raise MatchDetailsLoadError("El rol de una aparición no coincide con su colección.")
    if not appearance.player_name:
        raise MatchDetailsLoadError("Una aparición publicada carece de nombre observado.")
    player_id = appearance.player_id
    return MatchPublishedPlayerResponse(
        player_id=player_id,
        display_name=appearance.player_name,
        profile_url=_source_url(appearance.profile_url),
        photo_url=_source_url(appearance.photo_url),
        shirt_number=appearance.shirt_number,
        position=None,
        role=expected_role,
        participation_status=appearance.participation_status,
        player_profile_available=player_id is not None and player_id in player_ids,
    )


def _side(
    team: MatchTeam,
    *,
    team_id: int,
    player_ids: set[int],
) -> MatchPublishedSideResponse:
    coach_id: int | None = None
    if team.coach_id is not None and team.coach_id.isdigit():
        coach_id = int(team.coach_id)
    coach = None
    if team.coach_name:
        from football_data_hub_api.schemas import MatchPublishedCoachResponse

        coach = MatchPublishedCoachResponse(
            coach_id=coach_id,
            display_name=team.coach_name,
            profile_url=_source_url(team.coach_profile_url),
            photo_url=_source_url(team.coach_photo_url),
        )
    starters = None if team.starters is None else [
        _player(item, expected_role="starter", player_ids=player_ids) for item in team.starters
    ]
    substitutes = None if team.substitutes is None else [
        _player(item, expected_role="substitute", player_ids=player_ids) for item in team.substitutes
    ]
    return MatchPublishedSideResponse(
        team_id=team_id,
        coach=coach,
        starters=starters,
        substitutes=substitutes,
    )


def project_verified_detail(
    detail: MatchDetail,
    *,
    source_html_sha256: str,
    player_ids: set[int],
    publication_status: str = "approved",
) -> MatchPublishedDetailsResponse:
    """Project a typed detail without deriving sports facts or player identities."""

    errors = validate_match_detail_contract(detail)
    if errors:
        raise MatchDetailsLoadError("El detalle fuente no cumple el contrato: " + ", ".join(errors))
    if detail.score.home_goals is None or detail.score.away_goals is None:
        raise MatchDetailsLoadError("Un detalle de partido requiere el marcador completo.")
    if detail.match_date is None:
        raise MatchDetailsLoadError("La fecha real del partido no está verificada.")
    identity = detail.identity
    home = _side(detail.home_team, team_id=identity.home_team_id, player_ids=player_ids)
    away = _side(detail.away_team, team_id=identity.away_team_id, player_ids=player_ids)
    events = None if detail.events is None else [
        MatchPublishedEventResponse(
            event_kind=(
                "own_goal" if item.is_own_goal is True
                else "penalty" if item.is_penalty is True and item.event_kind in {"goal", "penalty"}
                else item.event_kind
            ),
            minute=_minute(item),
            team_id=item.team_id,
            player_id=item.player_id,
            player_name=item.player_name,
            related_player_id=item.related_player_id,
            related_player_name=item.related_player_name,
            is_penalty=item.is_penalty,
            is_own_goal=item.is_own_goal,
            source_description=item.source_description,
            score_after_home=item.score_after_home,
            score_after_away=item.score_after_away,
            player_profile_available=item.player_id is not None and item.player_id in player_ids,
            related_player_profile_available=item.related_player_id is not None and item.related_player_id in player_ids,
        )
        for item in detail.events
    ]
    return MatchPublishedDetailsResponse(
        publication_status=publication_status,
        validation_status="valid",
        source="BDFutbol",
        internal_id=identity.internal_id,
        source_match_id=identity.source_match_id,
        source_generation_id=detail.source_generation_id,
        source_capture_id=detail.source_capture_id,
        source_html_sha256=source_html_sha256,
        match_date=date.fromisoformat(detail.match_date),
        home_team_id=identity.home_team_id,
        away_team_id=identity.away_team_id,
        home_goals=detail.score.home_goals,
        away_goals=detail.score.away_goals,
        home=home,
        away=away,
        events=events,
    )


def _validate_detail_against_match(
    document: MatchPublishedDetailsResponse,
    match: MatchPageRecordResponse,
    *,
    generation_id: str,
    generation_sha256: str,
    source_generation_manifest_sha256: str,
) -> None:
    if (
        document.internal_id != match.internal_id
        or document.source_match_id != match.source_match_id
        or document.source_generation_id != generation_id
        or document.home_team_id != match.home_team.team_id
        or document.away_team_id != match.away_team.team_id
        or document.home.team_id != match.home_team.team_id
        or document.away.team_id != match.away_team.team_id
        or document.home_goals != match.home_goals
        or document.away_goals != match.away_goals
        or (match.source_match_date is not None and document.match_date != match.source_match_date)
    ):
        raise MatchDetailsLoadError("La identidad, fecha o marcador no coincide con MATCH-00.")
    if source_generation_manifest_sha256 != generation_sha256:
        raise MatchDetailsLoadError("La captura no corresponde al manifiesto MATCH-00 cargado.")


def _validate_detail_against_active_fixture(
    document: MatchPublishedDetailsResponse,
    active_match: MatchPageRecordResponse,
) -> None:
    """Keep historical provenance while requiring exact current sports identity."""

    if (
        document.internal_id != active_match.internal_id
        or document.source_match_id != active_match.source_match_id
        or document.home_team_id != active_match.home_team.team_id
        or document.away_team_id != active_match.away_team.team_id
        or document.home.team_id != active_match.home_team.team_id
        or document.away.team_id != active_match.away_team.team_id
        or active_match.status != "played"
        or document.home_goals != active_match.home_goals
        or document.away_goals != active_match.away_goals
        or (active_match.source_match_date is not None and document.match_date != active_match.source_match_date)
    ):
        raise MatchDetailsLoadError(
            "Los detalles históricos contradicen la identidad, fecha o resultado del fixture activo."
        )


def _with_verified_kickoff(
    document: MatchPublishedDetailsResponse, observation: Any
) -> MatchPublishedDetailsResponse:
    """Add a read-time projection from the same already-hashed source HTML.

    The immutable package is not rewritten. The enrichment is returned only
    for an observed HH:MM and remains tied to the package's HTML hash and the
    semantic parser version.
    """

    kickoff = observation.kickoff_time_local
    if kickoff.state not in {"observed", "explicitly_absent", "not_observed", "unresolved"}:
        return document
    return MatchPublishedDetailsResponse.model_validate({
        **document.model_dump(mode="json"),
        "kickoff_time_local": kickoff.value if kickoff.state == "observed" else None,
        "kickoff_state": kickoff.state,
        "kickoff_timezone": observation.timezone.value,
        "kickoff_source_text": kickoff.raw_value,
        "kickoff_source_reference": kickoff.source_reference,
        "kickoff_parser_version": observation.source.parser_version,
        "kickoff_source_html_sha256": observation.source.source_html_sha256,
    })


def _historical_generation_context(
    manifest: dict[str, Any],
    *,
    generation_root: Path,
    data_root: Path,
    match_bundle: MatchResultsBundle,
    generation_contexts: dict[str, tuple[Path, Any, MatchResultsBundle]] | None = None,
) -> tuple[Path, Any, MatchResultsBundle]:
    """Resolve a publication's immutable source generation without guessing."""

    source_generation_id = manifest.get("source_generation_id")
    if not isinstance(source_generation_id, str) or not _PUBLICATION_ID.fullmatch(source_generation_id):
        raise MatchDetailsLoadError("La publicación no declara su generación histórica.")
    if generation_contexts is not None and source_generation_id in generation_contexts:
        source_root, source_generation, source_bundle = generation_contexts[source_generation_id]
        if (
            source_generation.manifest_sha256 != manifest.get("source_generation_manifest_sha256")
            or source_bundle.bootstrap.metadata.generation_sha256 != source_generation.manifest_sha256
        ):
            raise MatchDetailsLoadError("La publicación no coincide con su generación histórica en caché.")
        return source_root, source_generation, source_bundle
    if source_generation_id == match_bundle.bootstrap.metadata.generation_id:
        source_root = match_bundle.generation_root or generation_root
        source_bundle = match_bundle
        source_generation = load_verified_match_generation(source_root, data_root=data_root)
    else:
        try:
            source_root = (
                data_root.expanduser().resolve(strict=True)
                / "matches" / "generations" / source_generation_id
            )
            source_generation = load_verified_match_generation(source_root, data_root=data_root)
            if source_generation.generation_id != source_generation_id:
                raise MatchDetailsLoadError("La generación histórica resuelta tiene otro ID.")
            from football_data_hub_api.match_results_dataset import build_match_results_bundle

            source_bundle = build_match_results_bundle(source_generation, source_root)
        except (MatchDetailInventoryError, MatchGenerationActivationError, OSError, ValueError, KeyError, TypeError) as exc:
            raise MatchDetailsLoadError(
                f"No se puede revalidar la generación histórica {source_generation_id}: {exc}"
            ) from exc
    if (
        source_generation.generation_id != source_generation_id
        or source_generation.manifest_sha256 != manifest.get("source_generation_manifest_sha256")
        or source_bundle.bootstrap.metadata.generation_sha256 != source_generation.manifest_sha256
    ):
        raise MatchDetailsLoadError("La publicación no coincide con su manifiesto de generación histórica.")
    if generation_contexts is not None:
        generation_contexts[source_generation_id] = (source_root, source_generation, source_bundle)
    return source_root, source_generation, source_bundle


def _validate_detail_against_inventory(detail: MatchDetail, record: dict[str, Any]) -> None:
    """Require the complete source identity to match the verified MATCH-00 row."""

    identity = detail.identity
    expected_score = record.get("reference_result")
    if (
        identity.internal_id != record.get("internal_id")
        or identity.source_match_id != record.get("source_match_id")
        or identity.season != record.get("season")
        or identity.competition != record.get("competition")
        or identity.group != record.get("group")
        or identity.matchday != record.get("matchday")
        or identity.home_team_id != record.get("home_team_id")
        or identity.away_team_id != record.get("away_team_id")
        or detail.source_generation_id != record.get("source_generation_id")
        or expected_score != {
            "home_goals": detail.score.home_goals,
            "away_goals": detail.score.away_goals,
        }
        or (record.get("source_match_date") is not None and detail.match_date != record.get("source_match_date"))
    ):
        raise MatchDetailsLoadError("La identidad deportiva no coincide con el registro de MATCH-00.")


def _campaign_artifact_path(
    data_root: Path, *, campaign_id: str, internal_id: str, artifact_id: str
) -> Path:
    """Resolve one campaign artifact inside the configured store without symlinks."""

    if (
        not _CAMPAIGN_ID.fullmatch(campaign_id)
        or not _PUBLICATION_ID.fullmatch(internal_id)
        or not _ARTIFACT_ID.fullmatch(artifact_id)
    ):
        raise MatchDetailsLoadError("Identificadores de campaña o artefacto no válidos.")
    root = data_root.expanduser().absolute()
    path = (
        root / "matches/details/campaigns" / campaign_id / "candidates"
        / internal_id / "artifacts" / artifact_id
    )
    cursor = path
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise MatchDetailsLoadError(f"La ruta del artefacto contiene un symlink: {cursor}")
        cursor = cursor.parent
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to((root / "matches/details/campaigns").resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise MatchDetailsLoadError("El artefacto de campaña no está bajo el almacén configurado.") from exc
    if not resolved.is_dir():
        raise MatchDetailsLoadError("El artefacto de campaña no es un directorio regular.")
    return resolved


def _campaign_observation(
    *,
    campaign_id: str,
    artifact_id: str,
    internal_id: str,
    generation: Any,
    data_root: Path,
    record: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    """Reverify the immutable campaign evidence and return its observation/source refs."""

    artifact = _campaign_artifact_path(
        data_root, campaign_id=campaign_id, internal_id=internal_id, artifact_id=artifact_id
    )
    try:
        observation = parse_campaign_saved_artifact(
            artifact,
            expected_match=record,
            verified_generation=generation,
            data_root=data_root,
        )
        manifest, manifest_raw = _read_json(artifact / "manifest.json")
        metadata, _ = _read_json(artifact / "metadata.json")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MatchDetailsLoadError(f"El artefacto/ledger de campaña no superó la validación: {exc}") from exc
    if (
        manifest.get("campaign_id") != campaign_id
        or manifest.get("artifact_id") != artifact_id
        or manifest.get("internal_id") != internal_id
        or metadata.get("campaign_id") != campaign_id
        or metadata.get("navigation_attempt_id") is None
        or metadata.get("capture_promoted") is not False
        or metadata.get("access_classification") != "VALID"
        or metadata.get("http_status") != 200
        or metadata.get("challenge_detected") is not False
        or metadata.get("denial_detected") is not False
        or observation.source.artifact_access_status != "VALID"
        or observation.source.promotion_eligible is not False
        or observation.validation.promotion_eligible is not False
    ):
        raise MatchDetailsLoadError("El artefacto no acredita acceso válido de campaña sin promoción.")
    source = {
        "source_kind": "campaign_discovery",
        "campaign_id": campaign_id,
        "artifact_id": artifact_id,
        "source_match_id": observation.source.source_match_id,
        "navigation_attempt_id": metadata["navigation_attempt_id"],
        "artifact_manifest_sha256": _sha256(manifest_raw),
        "source_html_sha256": observation.source.source_html_sha256,
        "inventory_id": observation.source.inventory_id,
        "source_generation_id": observation.source.source_generation_id,
        "source_generation_manifest_sha256": record["source_generation_manifest_sha256"],
        "source_capture_id": observation.source.source_capture_id,
        "season": record["season"],
        "competition": record["competition"],
        "group": record["group"],
        "matchday": record["matchday"],
        "source_match_date": record["source_match_date"],
        "home_team_id": record["home_team_id"],
        "away_team_id": record["away_team_id"],
        "home_team_name": observation.home.team.name,
        "away_team_name": observation.away.team.name,
        "capture_promotion_enabled": False,
        "promotion_eligible": False,
        "access_status": "VALID",
        "semantic_valid": observation.validation.semantic_valid,
    }
    return observation, source


def _validate_campaign_observation_against_match(
    observation: Any, record: dict[str, Any], match_page: MatchPageResponse
) -> None:
    """Require all catalog identity/context and score facts before drafting."""

    source = observation.source
    context = observation.context
    expected = match_page.match
    if observation.validation.semantic_valid is not True:
        raise MatchDetailsLoadError("La validación semántica no es válida.")
    if (
        source.internal_id != record["internal_id"]
        or source.source_match_id != record["source_match_id"]
        or source.requested_url != record["source_match_url"]
        or source.final_url != record["source_match_url"]
        or source.source_generation_id != record["source_generation_id"]
        or source.source_capture_id != record["source_capture_id"]
        or context.season.value != record["season"]
        or context.competition.value != record["competition"]
        or context.group.value != record["group"]
        or context.matchday.value != record["matchday"]
        or observation.match_date.value != record["source_match_date"]
        or observation.home.team.team_id != record["home_team_id"]
        or observation.away.team.team_id != record["away_team_id"]
        or observation.home.team.name != expected.home_team.name
        or observation.away.team.name != expected.away_team.name
        or observation.score.home_goals != expected.home_goals
        or observation.score.away_goals != expected.away_goals
    ):
        raise MatchDetailsLoadError("La identidad/contexto/marcador no coincide exactamente con MATCH-00.")


def _load_campaign_publication_document(
    *,
    publication_id: str,
    indexed_internal_id: str,
    manifest: dict[str, Any],
    approval: dict[str, Any],
    approval_raw: bytes,
    details_payload: dict[str, Any],
    details_raw: bytes,
    data_root: Path,
    match_bundle: MatchResultsBundle,
    player_ids: set[int],
    generation: Any,
    source_record: dict[str, Any],
) -> tuple[MatchPublishedDetailsResponse, Any]:
    manifest_fields = {
        "schema_version", "publication_id", "source_kind", "internal_id", "inventory_id",
        "source_generation_id", "source_generation_manifest_sha256", "source_capture_id",
        "source_match_id", "season", "competition", "group", "matchday", "source_match_date",
        "home_team_id", "away_team_id", "home_team_name", "away_team_name",
        "campaign_id", "artifact_id", "navigation_attempt_id", "artifact_manifest_sha256",
        "source_html_sha256", "details_sha256", "approval_sha256",
    }
    approval_fields = {
        "schema_version", "publication_status", "approved_by", "approved_at_utc",
        "approval_confirmation",
        "publication_id", "source_kind", "internal_id", "inventory_id",
        "source_generation_id", "source_generation_manifest_sha256", "source_capture_id",
        "source_match_id", "season", "competition", "group", "matchday", "source_match_date",
        "home_team_id", "away_team_id", "home_team_name", "away_team_name",
        "campaign_id", "artifact_id", "navigation_attempt_id", "artifact_manifest_sha256",
        "source_html_sha256", "details_sha256",
    }
    if set(manifest) != manifest_fields or manifest.get("schema_version") != CAMPAIGN_PACKAGE_SCHEMA:
        raise MatchDetailsLoadError("El manifiesto de campaña no cumple el contrato exacto.")
    if manifest.get("publication_id") != publication_id or manifest.get("internal_id") != indexed_internal_id:
        raise MatchDetailsLoadError("La publicación de campaña no coincide con el índice.")
    human_receipt = approval.get("schema_version") == CAMPAIGN_APPROVAL_SCHEMA
    if human_receipt:
        if set(approval) != approval_fields:
            raise MatchDetailsLoadError("El recibo humano no cumple el contrato exacto.")
        if (
            approval.get("publication_status") != "approved"
            or approval.get("source_kind") != "campaign_discovery"
            or not isinstance(approval.get("approved_by"), str)
            or not approval["approved_by"].strip()
            or approval.get("approval_confirmation") != (
                f"APPROVE-{manifest.get('source_match_id')}-"
                f"{str(manifest.get('source_html_sha256', ''))[:12]}-"
                f"{str(manifest.get('details_sha256', ''))[:12]}"
            )
        ):
            raise MatchDetailsLoadError("La aprobación humana no corresponde al paquete.")
        approval_identity_fields = approval_fields - {
            "schema_version", "publication_status", "approval_confirmation", "approved_by", "approved_at_utc"
        }
    elif approval.get("schema_version") == AUTO_POLICY_RECEIPT_SCHEMA:
        from football_data_hub.providers.bdfutbol.match_details.automatic_publication_policy import (
            POLICY_ID,
            POLICY_VERSION,
            automatic_publication_decision,
        )

        auto_fields = {
            "schema_version", "publication_status", "approval_mode", "policy_id",
            "policy_version", "update_job_id", "candidate_set_sha256",
            "validation_event_sha256", "validation_evidence_sha256", "validation",
            "approved_at_utc", *approval_fields - {
                "schema_version", "publication_status", "approved_by", "approved_at_utc",
                "approval_confirmation",
            },
        }
        if set(approval) != auto_fields:
            raise MatchDetailsLoadError("El recibo de política automática no cumple el contrato exacto.")
        allowed, reason = automatic_publication_decision(approval.get("validation"))
        if (
            approval.get("publication_status") != "approved"
            or approval.get("approval_mode") != "automatic_policy"
            or approval.get("policy_id") != POLICY_ID
            or approval.get("policy_version") != POLICY_VERSION
            or not isinstance(approval.get("update_job_id"), str)
            or not re.fullmatch(r"[0-9a-f-]{36}", approval["update_job_id"])
            or not re.fullmatch(r"[a-f0-9]{64}", str(approval.get("candidate_set_sha256", "")))
            or not re.fullmatch(r"[a-f0-9]{64}", str(approval.get("validation_event_sha256", "")))
            or not re.fullmatch(r"[a-f0-9]{64}", str(approval.get("validation_evidence_sha256", "")))
            or not allowed
        ):
            raise MatchDetailsLoadError(
                f"El recibo automático no satisface la política publicada ({reason or 'evidencia inválida'})."
            )
        approval_identity_fields = auto_fields - {
            "schema_version", "publication_status", "approval_mode", "policy_id",
            "policy_version", "update_job_id", "candidate_set_sha256",
            "validation_event_sha256", "validation_evidence_sha256", "validation",
            "approved_at_utc",
        }
    else:
        raise MatchDetailsLoadError("Falta una aprobación humana o un recibo de política automática válido.")
    approved_at = approval.get("approved_at_utc")
    if not isinstance(approved_at, str):
        raise MatchDetailsLoadError("El recibo de campaña no tiene fecha de aprobación.")
    try:
        approved_at_value = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MatchDetailsLoadError("La fecha de aprobación de campaña no es válida.") from exc
    if approved_at_value.tzinfo is None:
        raise MatchDetailsLoadError("La aprobación de campaña debe tener zona horaria.")
    if approval_raw != _canonical_json(approval) or details_raw != _canonical_json(details_payload):
        raise MatchDetailsLoadError("Los JSON aprobados no usan la codificación canónica del paquete.")
    if manifest.get("approval_sha256") != _sha256(approval_raw):
        raise MatchDetailsLoadError("El hash del recibo de campaña no coincide.")
    for key in approval_identity_fields:
        if approval.get(key) != manifest.get(key):
            raise MatchDetailsLoadError(f"La aprobación no autoriza el campo exacto {key}.")
    if (
        manifest.get("source_kind") != "campaign_discovery"
        or not isinstance(manifest.get("inventory_id"), str)
        or not isinstance(manifest.get("source_generation_id"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", str(manifest.get("source_generation_manifest_sha256", "")))
        or not re.fullmatch(r"[a-f0-9]{64}", str(manifest.get("artifact_manifest_sha256", "")))
        or not re.fullmatch(r"[a-f0-9]{64}", str(manifest.get("source_html_sha256", "")))
        or not re.fullmatch(r"[a-f0-9]{64}", str(manifest.get("details_sha256", "")))
        or not isinstance(manifest.get("navigation_attempt_id"), str)
        or not manifest["navigation_attempt_id"]
        or _sha256(details_raw) != manifest.get("details_sha256")
    ):
        raise MatchDetailsLoadError("La procedencia o huella del paquete de campaña no es válida.")
    try:
        document = MatchPublishedDetailsResponse.model_validate(details_payload)
    except (ValueError, TypeError) as exc:
        raise MatchDetailsLoadError("El documento de campaña no cumple el contrato público.") from exc
    if document.publication_status != "approved":
        raise MatchDetailsLoadError("El documento público de campaña no está marcado aprobado.")
    draft, observation = _build_campaign_publication_draft_from_verified(
        internal_id=indexed_internal_id,
        campaign_id=str(manifest["campaign_id"]),
        artifact_id=str(manifest["artifact_id"]),
        publication_id=publication_id,
        data_root=data_root,
        match_bundle=match_bundle,
        player_ids=player_ids,
        generation=generation,
        record=source_record,
    )
    if (
        draft.get("schema_version") != CAMPAIGN_DRAFT_SCHEMA
        or not _campaign_published_document_matches_revalidated_evidence(
            document,
            details_payload,
            str(manifest.get("details_sha256", "")),
            draft,
        )
    ):
        raise MatchDetailsLoadError("El documento público no coincide con la evidencia de campaña revalidada.")
    if not human_receipt:
        from football_data_hub.providers.bdfutbol.match_details.automatic_publication_policy import (
            automatic_publication_decision,
        )

        # The policy receipt and campaign event bind the parser version in
        # addition to the semantic dataclass, so reconstruct the same envelope.
        rebuilt_validation = _automatic_policy_validation_from_observation(observation)
        eligible, reason = automatic_publication_decision(rebuilt_validation)
        if (
            not eligible
            or _sha256(_canonical_json(rebuilt_validation))
            != approval.get("validation_evidence_sha256")
            or _canonical_json(rebuilt_validation)
            != _canonical_json(approval.get("validation"))
        ):
            raise MatchDetailsLoadError(
                f"La validación reconstruida ya no autoriza la política automática ({reason or 'evidencia distinta'})."
            )
    for key in manifest_fields - {
        "schema_version", "publication_id", "approval_sha256", "details_sha256"
    }:
        if manifest.get(key) != draft.get(key):
            raise MatchDetailsLoadError(f"El manifiesto no coincide con la fuente revalidada: {key}.")
    return document, observation


def _load_legacy_recovery_publication_document(
    *,
    publication_id: str,
    indexed_internal_id: str,
    manifest: dict[str, Any],
    approval: dict[str, Any],
    approval_raw: bytes,
    details_payload: dict[str, Any],
    details_raw: bytes,
    data_root: Path,
    store_root: Path,
    generation_root: Path,
    active_match_bundle: MatchResultsBundle,
    source_match_bundle: MatchResultsBundle,
    source_generation: Any,
    source_record: dict[str, Any],
    player_ids: set[int],
) -> tuple[MatchPublishedDetailsResponse, Any]:
    """Read a recovered legacy match only after replaying its original evidence."""

    if (
        not isinstance(approval, dict)
        or approval.get("schema_version") != LEGACY_RECOVERY_AUTO_RECEIPT_SCHEMA
        or approval.get("approval_mode") != "automatic_policy"
        or approval.get("decision_scope") != "verified_offline_legacy_recovery"
        or approval.get("publication_status") != "approved"
    ):
        raise MatchDetailsLoadError("El paquete de recuperación carece de recibo automático específico.")
    try:
        draft, observation, validation = build_legacy_recovery_publication_draft(
            recovery_id=str(manifest.get("recovery_id", "")),
            update_job_id=str(approval.get("update_job_id", "")),
            store_root=store_root,
            data_root=data_root,
            generation_root=generation_root,
            match_bundle=active_match_bundle,
            player_ids=player_ids,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, MatchDetailsLoadError):
            raise
        raise MatchDetailsLoadError(f"La recuperación histórica no se pudo reconstruir: {exc}") from exc
    expected_receipt = build_legacy_recovery_auto_policy_receipt(
        draft,
        validation=validation,
        update_job_id=str(approval.get("update_job_id", "")),
        evaluated_at_utc=_parse_approval_timestamp(approval.get("evaluated_at_utc")),
    )
    expected_manifest = _legacy_recovery_manifest(draft, approval_raw)
    if (
        indexed_internal_id != draft["internal_id"]
        or publication_id != draft["publication_id"]
        or manifest != expected_manifest
        or approval != expected_receipt
        or approval_raw != _canonical_json(approval)
        or details_raw != _canonical_json(details_payload)
        or _sha256(details_raw) != draft["details_sha256"]
        or details_payload != draft["details"]
        or source_generation.generation_id != draft["source_generation_id"]
        or source_generation.manifest_sha256 != draft["source_generation_manifest_sha256"]
        or source_record.get("internal_id") != draft["internal_id"]
        or source_record.get("source_match_id") != draft["source_match_id"]
        or approval.get("receipt_sha256") != _sha256(
            _canonical_json({key: value for key, value in approval.items() if key != "receipt_sha256"})
        )
    ):
        raise MatchDetailsLoadError("Manifiesto, recibo, documento o recuperación no coinciden exactamente.")
    try:
        document = MatchPublishedDetailsResponse.model_validate(details_payload)
    except (ValueError, TypeError) as exc:
        raise MatchDetailsLoadError("El informe recuperado no cumple el contrato público.") from exc
    if document.publication_status != "approved":
        raise MatchDetailsLoadError("El informe de recuperación no está marcado como aprobado por el paquete.")
    _validate_detail_against_match(
        document,
        _published_match(source_match_bundle, indexed_internal_id),
        generation_id=source_generation.generation_id,
        generation_sha256=source_generation.manifest_sha256,
        source_generation_manifest_sha256=draft["source_generation_manifest_sha256"],
    )
    _validate_detail_against_active_fixture(
        document, _published_match(active_match_bundle, indexed_internal_id)
    )
    return document, observation


def load_published_match_details(
    published_root: Path,
    *,
    store_root: Path,
    generation_root: Path,
    data_root: Path,
    match_bundle: MatchResultsBundle,
    player_ids: set[int],
    internal_ids: set[str] | None = None,
) -> dict[str, MatchPublishedDetailsResponse]:
    """Load only immutable VALID captures explicitly approved in the publication index.

    An absent index means no detail is published. Diagnostics and discovery-only
    artifacts are never traversed by this reader.
    """

    root = _safe_root(published_root)
    index_path = root / "index.json"
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise MatchDetailsLoadError("La raíz de publicación no es un directorio regular.")
    if index_path.is_symlink():
        raise MatchDetailsLoadError("El índice de publicaciones no puede ser symlink.")
    if not index_path.exists():
        return {}
    if not index_path.is_file():
        raise MatchDetailsLoadError("La raíz o el índice de publicaciones no es regular.")
    index, _ = _read_json(index_path)
    if index.get("schema_version") != INDEX_SCHEMA or set(index) != {"schema_version", "publications"}:
        raise MatchDetailsLoadError("El índice de publicación no tiene un esquema conocido.")
    items = index.get("publications")
    if not isinstance(items, list):
        raise MatchDetailsLoadError("publications debe ser una lista.")
    if internal_ids is not None and any(not isinstance(item, str) for item in internal_ids):
        raise MatchDetailsLoadError("El filtro interno de partidos contiene IDs no válidos.")
    resolved_active_root = match_bundle.generation_root or generation_root
    generation = load_verified_match_generation(resolved_active_root, data_root=data_root)
    if (
        generation.generation_id != match_bundle.bootstrap.metadata.generation_id
        or generation.manifest_sha256 != match_bundle.bootstrap.metadata.generation_sha256
    ):
        raise MatchDetailsLoadError("La generación de detalles difiere de la cargada por Resultados.")
    store = MatchDetailStore(store_root)
    loaded: dict[str, MatchPublishedDetailsResponse] = {}
    seen: set[str] = set()
    generation_contexts: dict[str, tuple[Path, Any, MatchResultsBundle]] = {
        generation.generation_id: (resolved_active_root, generation, match_bundle)
    }
    inventory_contexts: dict[str, tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, str]]] = {}

    for item in items:
        if not isinstance(item, dict) or set(item) != {"internal_id", "publication_id", "package_path", "manifest_sha256"}:
            raise MatchDetailsLoadError("Entrada de publicación incompleta o con campos desconocidos.")
        internal_id = item["internal_id"]
        publication_id = item["publication_id"]
        package_path = item["package_path"]
        if (
            not isinstance(internal_id, str)
            or internal_id in seen
            or not isinstance(publication_id, str)
            or not _PUBLICATION_ID.fullmatch(publication_id)
            or package_path != f"packages/{publication_id}"
            or not isinstance(item["manifest_sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", item["manifest_sha256"])
        ):
            raise MatchDetailsLoadError("Referencia de paquete no válida o duplicada.")
        seen.add(internal_id)
        if internal_ids is not None and internal_id not in internal_ids:
            continue
        relative = PurePosixPath(package_path)
        if relative.is_absolute() or any(part in {".", ".."} for part in relative.parts):
            raise MatchDetailsLoadError("Ruta de paquete insegura.")
        packages_root = root / "packages"
        if packages_root.is_symlink() or not packages_root.is_dir():
            raise MatchDetailsLoadError("El directorio de paquetes publicado no es regular.")
        package = root.joinpath(*relative.parts)
        if package.is_symlink() or not package.is_dir():
            raise MatchDetailsLoadError("El paquete publicado falta o no es un directorio regular.")
        try:
            package.resolve(strict=True).relative_to(root.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise MatchDetailsLoadError("El paquete publicado sale de la raíz permitida.") from exc
        if any(path.is_symlink() for path in package.rglob("*")) or {
            path.relative_to(package).as_posix() for path in package.rglob("*")
        } != {"manifest.json", "approval.json", "details.json"}:
            raise MatchDetailsLoadError("El paquete contiene archivos ausentes o inesperados.")
        manifest_path = package / "manifest.json"
        approval_path = package / "approval.json"
        details_path = package / "details.json"
        manifest, manifest_raw = _read_json(manifest_path)
        approval, approval_raw = _read_json(approval_path)
        details_payload, details_raw = _read_json(details_path)
        if _sha256(manifest_raw) != item["manifest_sha256"]:
            raise MatchDetailsLoadError("El hash del manifiesto no coincide con el índice.")
        source_root, source_generation, source_bundle = _historical_generation_context(
            manifest,
            generation_root=resolved_active_root,
            data_root=data_root,
            match_bundle=match_bundle,
            generation_contexts=generation_contexts,
        )
        inventory_context = inventory_contexts.get(source_generation.generation_id)
        if inventory_context is None:
            source_inventory = build_match_detail_inventory(source_generation)
            source_records = {
                record["internal_id"]: record for record in source_inventory["matches"]
            }
            source_captures = {
                source["group"]: source["capture_id"]
                for source in source_generation.manifest_payload["source_captures"]
            }
            inventory_context = (source_inventory, source_records, source_captures)
            inventory_contexts[source_generation.generation_id] = inventory_context
        source_inventory, source_records, source_captures = inventory_context
        if manifest.get("schema_version") == CAMPAIGN_PACKAGE_SCHEMA:
            record = source_records.get(internal_id)
            if record is None:
                raise MatchDetailsLoadError("El partido de campaña no pertenece a su MATCH-00 histórico.")
            document, observation = _load_campaign_publication_document(
                publication_id=publication_id,
                indexed_internal_id=internal_id,
                manifest=manifest,
                approval=approval,
                approval_raw=approval_raw,
                details_payload=details_payload,
                details_raw=details_raw,
                data_root=data_root,
                match_bundle=source_bundle,
                player_ids=player_ids,
                generation=source_generation,
                source_record=record,
            )
            _validate_detail_against_match(
                document,
                _published_match(source_bundle, internal_id),
                generation_id=source_generation.generation_id,
                generation_sha256=source_generation.manifest_sha256,
                source_generation_manifest_sha256=str(
                    manifest["source_generation_manifest_sha256"]
                ),
            )
            _validate_detail_against_active_fixture(
                document, _published_match(match_bundle, internal_id)
            )
            document = _with_verified_kickoff(document, observation)
            loaded[internal_id] = document
            continue
        if manifest.get("schema_version") == LEGACY_RECOVERY_PACKAGE_SCHEMA:
            record = source_records.get(internal_id)
            if record is None:
                raise MatchDetailsLoadError("El partido de recuperación no pertenece a su MATCH-00 histórico.")
            document, observation = _load_legacy_recovery_publication_document(
                publication_id=publication_id,
                indexed_internal_id=internal_id,
                manifest=manifest,
                approval=approval,
                approval_raw=approval_raw,
                details_payload=details_payload,
                details_raw=details_raw,
                data_root=data_root,
                store_root=store_root,
                generation_root=resolved_active_root,
                active_match_bundle=match_bundle,
                source_match_bundle=source_bundle,
                source_generation=source_generation,
                source_record=record,
                player_ids=player_ids,
            )
            document = _with_verified_kickoff(document, observation)
            loaded[internal_id] = document
            continue
        allowed_manifest = {
            "schema_version", "publication_id", "internal_id", "inventory_id", "capture_id",
            "source_generation_id", "source_generation_manifest_sha256", "source_capture_id",
            "match_detail_sha256", "source_html_sha256", "details_sha256", "approval_sha256",
        }
        if set(manifest) != allowed_manifest or manifest.get("schema_version") != PACKAGE_SCHEMA:
            raise MatchDetailsLoadError("El manifiesto de publicación no cumple el contrato.")
        if manifest.get("publication_id") != publication_id:
            raise MatchDetailsLoadError("El ID del paquete no coincide con el índice.")
        allowed_approval = {
            "schema_version", "publication_status", "approved_by", "approved_at_utc",
            "publication_id", "source_capture_id",
            "internal_id", "inventory_id", "capture_id", "source_generation_id",
            "source_generation_manifest_sha256", "match_detail_sha256", "source_html_sha256", "details_sha256",
        }
        if set(approval) != allowed_approval or approval.get("schema_version") != APPROVAL_SCHEMA:
            raise MatchDetailsLoadError("Falta un recibo explícito de aprobación válido.")
        if approval.get("publication_status") != "approved" or not isinstance(approval.get("approved_by"), str) or not approval["approved_by"].strip():
            raise MatchDetailsLoadError("El paquete no tiene aprobación independiente.")
        approved_at = approval.get("approved_at_utc")
        if not isinstance(approved_at, str):
            raise MatchDetailsLoadError("El recibo de aprobación no tiene fecha.")
        try:
            approved_at_value = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MatchDetailsLoadError("La fecha del recibo de aprobación no es válida.") from exc
        if approved_at_value.tzinfo is None:
            raise MatchDetailsLoadError("La fecha de aprobación debe incluir zona horaria.")
        if manifest.get("approval_sha256") != _sha256(approval_raw):
            raise MatchDetailsLoadError("El hash del recibo de aprobación no coincide.")
        if any(approval.get(key) != manifest.get(key) for key in (
            "publication_id", "internal_id", "inventory_id", "capture_id", "source_capture_id", "source_generation_id",
            "source_generation_manifest_sha256", "match_detail_sha256", "source_html_sha256", "details_sha256",
        )):
            raise MatchDetailsLoadError("El recibo de aprobación no autoriza estos datos exactos.")
        record = source_records.get(internal_id)
        if record is None or manifest.get("internal_id") != internal_id:
            raise MatchDetailsLoadError("El partido publicado no pertenece a su inventario MATCH-00 histórico.")
        if (
            manifest.get("inventory_id") != source_inventory["inventory_id"]
            or manifest.get("source_generation_id") != source_generation.generation_id
            or manifest.get("source_generation_manifest_sha256") != source_generation.manifest_sha256
            or manifest.get("source_capture_id") != source_captures.get(record.get("group"))
        ):
            raise MatchDetailsLoadError("La procedencia del paquete no coincide con su MATCH-00 histórico.")
        try:
            verified_capture = store.verify_capture_read_only(source_inventory, str(manifest["capture_id"]))
        except (MatchDetailStoreError, KeyError, TypeError, ValueError) as exc:
            raise MatchDetailsLoadError("La captura fuente no supera la verificación íntegra.") from exc
        if (
            verified_capture["internal_id"] != internal_id
            or verified_capture["match_detail_sha256"] != manifest.get("match_detail_sha256")
            or verified_capture["source_html_sha256"] != manifest.get("source_html_sha256")
            or verified_capture["metadata"].get("source_generation_manifest_sha256") != source_generation.manifest_sha256
            or _sha256(details_raw) != manifest.get("details_sha256")
        ):
            raise MatchDetailsLoadError("Los hashes de captura no coinciden con la aprobación.")
        _validate_detail_against_inventory(verified_capture["detail"], record)
        projected = project_verified_detail(
            verified_capture["detail"],
            source_html_sha256=verified_capture["source_html_sha256"],
            player_ids=player_ids,
        )
        try:
            document = MatchPublishedDetailsResponse.model_validate(details_payload)
        except (ValueError, TypeError) as exc:
            raise MatchDetailsLoadError("El documento deportivo preparado no cumple el contrato.") from exc
        if _canonical_json(document.model_dump(mode="json", exclude_none=True)) != _canonical_json(projected.model_dump(mode="json", exclude_none=True)):
            raise MatchDetailsLoadError("El documento preparado no coincide con la captura verificada.")
        match = _published_match(match_bundle, internal_id)
        _validate_detail_against_match(
            document,
            _published_match(source_bundle, internal_id),
            generation_id=source_generation.generation_id,
            generation_sha256=source_generation.manifest_sha256,
            source_generation_manifest_sha256=str(manifest["source_generation_manifest_sha256"]),
        )
        _validate_detail_against_active_fixture(document, match)
        loaded[internal_id] = document
    return loaded


def build_match_detail_publication_draft(
    *,
    internal_id: str,
    capture_id: str,
    publication_id: str,
    store_root: Path,
    generation_root: Path,
    data_root: Path,
    match_bundle: MatchResultsBundle,
    player_ids: set[int],
) -> dict[str, Any]:
    """Prepare exact hashes and the API projection; this function does not write."""

    if not _PUBLICATION_ID.fullmatch(publication_id):
        raise MatchDetailsLoadError("publication_id no seguro")
    generation_root = match_bundle.generation_root or resolve_match_generation_root(
        generation_root, data_root=data_root
    )
    generation = load_verified_match_generation(generation_root, data_root=data_root)
    if (
        generation.generation_id != match_bundle.bootstrap.metadata.generation_id
        or generation.manifest_sha256 != match_bundle.bootstrap.metadata.generation_sha256
    ):
        raise MatchDetailsLoadError("La generación de detalles difiere de la cargada por Resultados.")
    inventory = build_match_detail_inventory(generation)
    record = next((item for item in inventory["matches"] if item["internal_id"] == internal_id), None)
    if record is None:
        raise MatchDetailsLoadError("El partido no está en el inventario disputado de MATCH-00.")
    verified_capture = MatchDetailStore(store_root).verify_capture_read_only(inventory, capture_id)
    _validate_detail_against_inventory(verified_capture["detail"], record)
    document = project_verified_detail(
        verified_capture["detail"],
        source_html_sha256=verified_capture["source_html_sha256"],
        player_ids=player_ids,
    )
    match = _published_match(match_bundle, internal_id)
    source_generation_manifest_sha256 = str(record["source_generation_manifest_sha256"])
    _validate_detail_against_match(
        document,
        match,
        generation_id=generation.generation_id,
        generation_sha256=generation.manifest_sha256,
        source_generation_manifest_sha256=source_generation_manifest_sha256,
    )
    details_raw = _canonical_json(document.model_dump(mode="json", exclude_unset=True))
    return {
        "schema_version": DRAFT_SCHEMA,
        "publication_id": publication_id,
        "internal_id": internal_id,
        "inventory_id": inventory["inventory_id"],
        "capture_id": capture_id,
        "source_generation_id": generation.generation_id,
        "source_generation_manifest_sha256": generation.manifest_sha256,
        "source_capture_id": record["source_capture_id"],
        "match_detail_sha256": verified_capture["match_detail_sha256"],
        "source_html_sha256": verified_capture["source_html_sha256"],
        "details_sha256": _sha256(details_raw),
        "details": document.model_dump(mode="json", exclude_unset=True),
    }


def build_campaign_publication_draft(
    *,
    internal_id: str,
    campaign_id: str,
    artifact_id: str,
    publication_id: str | None = None,
    generation_root: Path,
    data_root: Path,
    match_bundle: MatchResultsBundle,
    player_ids: set[int],
) -> dict[str, Any]:
    """Prepare a publication document from an unpromoted campaign artifact.

    This does not change campaign state, promote a capture, or write to the public
    index. Every call rechecks the campaign ledger, artifact hashes and MATCH-00.
    """

    generation_root = match_bundle.generation_root or resolve_match_generation_root(
        generation_root, data_root=data_root
    )
    generation = load_verified_match_generation(generation_root, data_root=data_root)
    if (
        generation.generation_id != match_bundle.bootstrap.metadata.generation_id
        or generation.manifest_sha256 != match_bundle.bootstrap.metadata.generation_sha256
    ):
        raise MatchDetailsLoadError("La generación de detalles difiere de la cargada por Resultados.")
    inventory = build_match_detail_inventory(generation)
    record = next((item for item in inventory["matches"] if item["internal_id"] == internal_id), None)
    if record is None:
        raise MatchDetailsLoadError("El partido no pertenece al inventario disputado de MATCH-00.")
    draft, _observation = _build_campaign_publication_draft_from_verified(
        internal_id=internal_id,
        campaign_id=campaign_id,
        artifact_id=artifact_id,
        publication_id=publication_id,
        data_root=data_root,
        match_bundle=match_bundle,
        player_ids=player_ids,
        generation=generation,
        record=record,
    )
    return draft


def _build_campaign_publication_draft_from_verified(
    *,
    internal_id: str,
    campaign_id: str,
    artifact_id: str,
    publication_id: str | None,
    data_root: Path,
    match_bundle: MatchResultsBundle,
    player_ids: set[int],
    generation: Any,
    record: dict[str, Any],
) -> tuple[dict[str, Any], Any]:
    """Build from generation evidence verified once by the enclosing read operation."""
    if record.get("internal_id") != internal_id:
        raise MatchDetailsLoadError("El registro resuelto del inventario no coincide con el partido.")
    observation, source = _campaign_observation(
        campaign_id=campaign_id,
        artifact_id=artifact_id,
        internal_id=internal_id,
        generation=generation,
        data_root=data_root,
        record=record,
    )
    match_page = build_match_page(match_bundle, internal_id)
    if match_page is None:
        raise MatchDetailsLoadError("El partido no está disponible en la respuesta de MATCH-00.")
    _validate_campaign_observation_against_match(observation, record, match_page)
    preview = build_discovery_preview(
        observation, match_page=match_page, player_ids=player_ids
    )
    document = MatchPublishedDetailsResponse.model_validate({
        **preview.model_dump(mode="json", exclude_unset=True),
        "publication_status": "approved",
    })
    _validate_detail_against_match(
        document,
        match_page.match,
        generation_id=generation.generation_id,
        generation_sha256=generation.manifest_sha256,
        source_generation_manifest_sha256=record["source_generation_manifest_sha256"],
    )
    details = document.model_dump(mode="json", exclude_unset=True)
    details_raw = _canonical_json(details)
    if publication_id is None:
        publication_id = (
            f"campaign-{record['source_match_id']}-{source['source_html_sha256'][:16]}"
        )
    if not _PUBLICATION_ID.fullmatch(publication_id):
        raise MatchDetailsLoadError("publication_id no seguro")
    draft = {
        "schema_version": CAMPAIGN_DRAFT_SCHEMA,
        "publication_id": publication_id,
        **source,
        "internal_id": internal_id,
        "details_sha256": _sha256(details_raw),
        "details": details,
    }
    return draft, observation


def _legacy_recovery_manifest(draft: dict[str, Any], receipt_raw: bytes) -> dict[str, Any]:
    fields = (
        "publication_id", "source_kind", "internal_id", "source_match_id", "season",
        "competition", "group", "matchday", "source_match_date", "home_team_id",
        "away_team_id", "home_team_name", "away_team_name", "recovery_id",
        "recovery_candidate_sha256", "recovery_source_receipt_sha256",
        "recovery_manifest_sha256", "inventory_id", "original_attempt_id", "artifact_id",
        "artifact_manifest_sha256", "source_html_sha256", "checkpoint_sha256",
        "diagnostic_sha256", "source_generation_id", "source_generation_manifest_sha256",
        "source_capture_id", "active_generation_id", "active_generation_manifest_sha256",
        "details_sha256",
    )
    return {
        "schema_version": LEGACY_RECOVERY_PACKAGE_SCHEMA,
        **{key: draft[key] for key in fields},
        "approval_sha256": _sha256(receipt_raw),
    }


def build_legacy_recovery_publication_draft(
    *,
    recovery_id: str,
    update_job_id: str,
    store_root: Path,
    data_root: Path,
    generation_root: Path,
    match_bundle: MatchResultsBundle,
    player_ids: set[int],
) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    """Reparse and project the single immutable 272582 recovery without HTTP."""

    if not re.fullmatch(r"legacy-recovery-272582-[a-f0-9]{16}", recovery_id):
        raise MatchDetailsLoadError("ID de recuperación legado no válido.")
    if not re.fullmatch(r"[0-9a-f-]{36}", update_job_id):
        raise MatchDetailsLoadError("El trabajo local de actualización no tiene un UUID válido.")
    from football_data_hub.providers.bdfutbol.match_details.historical_review import (
        HISTORICAL_272582_HTML_SHA256,
        verify_historical_recovery_candidate,
    )

    active_root = match_bundle.generation_root or resolve_match_generation_root(
        generation_root, data_root=data_root
    )
    active_generation = load_verified_match_generation(active_root, data_root=data_root)
    if (
        active_generation.generation_id != match_bundle.bootstrap.metadata.generation_id
        or active_generation.manifest_sha256 != match_bundle.bootstrap.metadata.generation_sha256
    ):
        raise MatchDetailsLoadError("La recuperación se evalúa contra una generación activa distinta de Resultados.")
    active_inventory = build_match_detail_inventory(active_generation)
    active_records = [
        row for row in active_inventory["matches"]
        if row.get("internal_id") == "pf-2026-27-group-ii-bdfutbol-272582"
    ]
    if len(active_records) != 1:
        raise MatchDetailsLoadError("272582 no figura como partido único en MATCH-00 activo.")
    active_record = active_records[0]
    store_root = store_root.expanduser().resolve(strict=True)
    recovery_root = store_root / "recoveries" / recovery_id
    verified_recovery = verify_historical_recovery_candidate(
        store_root,
        data_root=data_root,
        expected_match=active_record,
        active_generation_id=active_generation.generation_id,
        active_generation_manifest_sha256=active_generation.manifest_sha256,
    )
    if verified_recovery is None or verified_recovery.get("recovery_id") != recovery_id:
        raise MatchDetailsLoadError("No existe una recuperación legado válida para 272582.")
    candidate_raw = _regular_file_bytes(recovery_root / "candidate.json", "candidato de recuperación")
    source_receipt_raw = _regular_file_bytes(recovery_root / "receipt.json", "recibo original de recuperación")
    recovery_manifest_raw = _regular_file_bytes(recovery_root / "manifest.json", "manifiesto de recuperación")
    try:
        candidate = json.loads(candidate_raw)
        source_receipt = json.loads(source_receipt_raw)
        recovery_manifest = json.loads(recovery_manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatchDetailsLoadError("El bundle de recuperación no contiene JSON válido.") from exc
    if (
        not isinstance(candidate, dict)
        or not isinstance(source_receipt, dict)
        or not isinstance(recovery_manifest, dict)
        or _sha256(candidate_raw) != verified_recovery.get("candidate_sha256")
        or source_receipt.get("receipt_sha256") != verified_recovery.get("receipt_sha256")
        or source_receipt.get("candidate_sha256") != verified_recovery.get("candidate_sha256")
        or source_receipt.get("receipt_sha256") != _sha256(_legacy_recovery_canonical_json({
            key: value for key, value in source_receipt.items() if key != "receipt_sha256"
        }))
        or source_receipt.get("status") != "VALIDATED_PENDING_EXPLICIT_REVIEW"
        or source_receipt.get("publication_status") != "NOT_PUBLISHED"
        or recovery_manifest.get("recovery_id") != recovery_id
        or recovery_manifest_raw != _legacy_recovery_canonical_json(recovery_manifest)
        or recovery_manifest.get("files") != {
            "candidate.json": {"sha256": _sha256(candidate_raw), "bytes": len(candidate_raw)},
            "receipt.json": {"sha256": _sha256(source_receipt_raw), "bytes": len(source_receipt_raw)},
        }
    ):
        raise MatchDetailsLoadError("Los hashes o el estado histórico del bundle de recuperación cambiaron.")
    evidence = candidate["evidence"]
    historic_root = data_root.expanduser().resolve(strict=True) / "matches" / "generations" / evidence["generation_id"]
    historic_generation = load_verified_match_generation(historic_root, data_root=data_root)
    if (
        historic_generation.generation_id != evidence["generation_id"]
        or historic_generation.manifest_sha256 != evidence["generation_manifest_sha256"]
    ):
        raise MatchDetailsLoadError("La generación deportiva histórica de la recuperación no es íntegra.")
    historic_inventory = build_match_detail_inventory(historic_generation)
    historic_records = [
        row for row in historic_inventory["matches"]
        if row.get("internal_id") == active_record["internal_id"]
    ]
    if len(historic_records) != 1:
        raise MatchDetailsLoadError("La generación original no contiene un fixture 272582 único.")
    historic_record = historic_records[0]
    sporting_fields = (
        "internal_id", "source_match_id", "source_match_url", "season", "competition",
        "group", "matchday", "source_match_date", "home_team_id", "away_team_id",
        "reference_result",
    )
    if any(historic_record.get(key) != active_record.get(key) for key in sporting_fields):
        raise MatchDetailsLoadError("El fixture histórico de la recuperación difiere del MATCH-00 activo.")

    artifact = store_root / "diagnostics" / evidence["inventory_id"] / evidence["artifact_id"]
    if evidence.get("artifact_relative_path") != artifact.relative_to(store_root).as_posix():
        raise MatchDetailsLoadError("La ruta del HTML original no coincide con el recibo de recuperación.")
    try:
        observation = parse_saved_artifact(artifact, expected_match=historic_record)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MatchDetailsLoadError(f"El HTML original de 272582 no se pudo revalidar offline: {exc}") from exc
    if (
        observation.validation.semantic_valid is not True
        or observation.validation.errors
        or any(not check.passed for check in observation.validation.checks)
        or observation.source.source_html_sha256 != HISTORICAL_272582_HTML_SHA256
        or observation.source.artifact_access_status != "INVALID_CONTENT"
        or observation.source.promotion_eligible is not False
        or json.loads(_canonical_json(asdict(observation))) != candidate.get("observation")
        or json.loads(_canonical_json(asdict(observation.validation)))
        != candidate.get("semantic_validation")
    ):
        raise MatchDetailsLoadError("La nueva validación del HTML no coincide con la recuperación inmutable.")
    from football_data_hub.providers.bdfutbol.match_details.automatic_publication_policy import (
        RECOVERY_POLICY_ID,
        RECOVERY_POLICY_VERSION,
        legacy_recovery_publication_decision,
    )

    validation = json.loads(_canonical_json(asdict(observation.validation)))
    allowed, reason = legacy_recovery_publication_decision(validation)
    if not allowed:
        raise MatchDetailsLoadError(f"272582 no supera la política automática de recuperación ({reason}).")
    from football_data_hub_api.match_results_dataset import load_match_results_dataset

    historic_bundle = load_match_results_dataset(historic_root, data_root=data_root)
    historic_page = build_match_page(historic_bundle, active_record["internal_id"])
    if historic_page is None:
        raise MatchDetailsLoadError("La generación histórica no puede construir la ficha de 272582.")
    preview = build_discovery_preview(observation, match_page=historic_page, player_ids=player_ids)
    document = MatchPublishedDetailsResponse.model_validate({
        **preview.model_dump(mode="json", exclude_unset=True),
        "publication_status": "approved",
    })
    current_page = build_match_page(match_bundle, active_record["internal_id"])
    if current_page is None or current_page.match.status != "played":
        raise MatchDetailsLoadError("272582 no figura como partido disputado en MATCH-00 activo.")
    _validate_detail_against_match(
        document,
        historic_page.match,
        generation_id=historic_generation.generation_id,
        generation_sha256=historic_generation.manifest_sha256,
        source_generation_manifest_sha256=historic_generation.manifest_sha256,
    )
    _validate_detail_against_active_fixture(document, current_page.match)
    details = document.model_dump(mode="json", exclude_unset=True)
    details_raw = _canonical_json(details)
    candidate_sha = _sha256(candidate_raw)
    source_receipt_sha = _sha256(source_receipt_raw)
    recovery_manifest_sha = _sha256(recovery_manifest_raw)
    publication_id = f"recovery-272582-{_sha256(details_raw)[:16]}"
    draft = {
        "schema_version": LEGACY_RECOVERY_DRAFT_SCHEMA,
        "publication_id": publication_id,
        "source_kind": "offline_legacy_recovery",
        "internal_id": active_record["internal_id"],
        "source_match_id": "272582",
        "season": active_record["season"],
        "competition": active_record["competition"],
        "group": active_record["group"],
        "matchday": active_record["matchday"],
        "source_match_date": active_record["source_match_date"],
        "home_team_id": active_record["home_team_id"],
        "away_team_id": active_record["away_team_id"],
        "home_team_name": current_page.match.home_team.name,
        "away_team_name": current_page.match.away_team.name,
        "recovery_id": recovery_id,
        "recovery_candidate_sha256": candidate_sha,
        "recovery_source_receipt_sha256": source_receipt_sha,
        "recovery_manifest_sha256": recovery_manifest_sha,
        "inventory_id": evidence["inventory_id"],
        "original_attempt_id": evidence["original_attempt_id"],
        "artifact_id": evidence["artifact_id"],
        "artifact_manifest_sha256": evidence["artifact_manifest_sha256"],
        "source_html_sha256": observation.source.source_html_sha256,
        "checkpoint_sha256": evidence["checkpoint_sha256"],
        "diagnostic_sha256": evidence["diagnostic_sha256"],
        "source_generation_id": historic_generation.generation_id,
        "source_generation_manifest_sha256": historic_generation.manifest_sha256,
        "source_capture_id": observation.source.source_capture_id,
        "active_generation_id": active_generation.generation_id,
        "active_generation_manifest_sha256": active_generation.manifest_sha256,
        "parser_version": observation.source.parser_version,
        "policy_id": RECOVERY_POLICY_ID,
        "policy_version": RECOVERY_POLICY_VERSION,
        "semantic_valid": True,
        "details_sha256": _sha256(details_raw),
        "details": details,
    }
    return draft, observation, validation


def build_legacy_recovery_auto_policy_receipt(
    draft: dict[str, Any],
    *,
    validation: dict[str, Any],
    update_job_id: str,
    evaluated_at_utc: datetime | None = None,
) -> dict[str, Any]:
    """Build an auditable, non-human policy receipt for offline 272582 recovery."""

    from football_data_hub.providers.bdfutbol.match_details.automatic_publication_policy import (
        RECOVERY_POLICY_ID,
        RECOVERY_POLICY_VERSION,
        legacy_recovery_publication_decision,
    )

    eligible, reason = legacy_recovery_publication_decision(validation)
    if (
        draft.get("schema_version") != LEGACY_RECOVERY_DRAFT_SCHEMA
        or draft.get("source_kind") != "offline_legacy_recovery"
        or draft.get("source_match_id") != "272582"
        or draft.get("internal_id") != "pf-2026-27-group-ii-bdfutbol-272582"
        or draft.get("source_html_sha256") != "9242edad00b43a4e83c649ddad006edb0d1172e0d88640082312a0fe1cf16997"
        or draft.get("policy_id") != RECOVERY_POLICY_ID
        or draft.get("policy_version") != RECOVERY_POLICY_VERSION
        or draft.get("semantic_valid") is not True
        or _sha256(_canonical_json(draft.get("details"))) != draft.get("details_sha256")
        or not eligible
        or not re.fullmatch(r"[0-9a-f-]{36}", update_job_id)
    ):
        raise MatchDetailsLoadError(f"No se puede emitir recibo automático de recuperación ({reason or 'evidencia inválida'}).")
    evaluated_at_utc = evaluated_at_utc or datetime.now(timezone.utc)
    if evaluated_at_utc.tzinfo is None:
        raise MatchDetailsLoadError("La decisión automática debe incluir zona horaria.")
    candidate_set = {
        "schema_version": "football_data_hub.legacy_recovery_policy_candidate.v1",
        "policy_id": RECOVERY_POLICY_ID,
        "policy_version": RECOVERY_POLICY_VERSION,
        "update_job_id": update_job_id,
        **{
            key: draft[key]
            for key in (
                "internal_id", "source_match_id", "recovery_id",
                "recovery_candidate_sha256", "recovery_source_receipt_sha256",
                "recovery_manifest_sha256", "artifact_manifest_sha256",
                "source_html_sha256", "checkpoint_sha256", "diagnostic_sha256",
                "source_generation_id", "source_generation_manifest_sha256",
                "active_generation_id", "active_generation_manifest_sha256", "details_sha256",
            )
        },
        "acquisition_count": 0,
        "offline_revalidation_only": True,
    }
    receipt = {
        "schema_version": LEGACY_RECOVERY_AUTO_RECEIPT_SCHEMA,
        "publication_status": "approved",
        "approval_mode": "automatic_policy",
        "policy_id": RECOVERY_POLICY_ID,
        "policy_version": RECOVERY_POLICY_VERSION,
        "decision_scope": "verified_offline_legacy_recovery",
        "update_job_id": update_job_id,
        "candidate_set_sha256": _sha256(_canonical_json(candidate_set)),
        "validation_evidence_sha256": _sha256(_canonical_json(validation)),
        "validation": json.loads(_canonical_json(validation)),
        "evaluated_at_utc": evaluated_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        **{
            key: draft[key]
            for key in (
                "publication_id", "source_kind", "internal_id", "source_match_id", "season",
                "competition", "group", "matchday", "source_match_date", "home_team_id",
                "away_team_id", "home_team_name", "away_team_name", "recovery_id",
                "recovery_candidate_sha256", "recovery_source_receipt_sha256",
                "recovery_manifest_sha256", "inventory_id", "original_attempt_id", "artifact_id",
                "artifact_manifest_sha256", "source_html_sha256", "checkpoint_sha256",
                "diagnostic_sha256", "source_generation_id", "source_generation_manifest_sha256",
                "source_capture_id", "active_generation_id", "active_generation_manifest_sha256",
                "parser_version", "details_sha256",
            )
        },
    }
    receipt["receipt_sha256"] = _sha256(_canonical_json(receipt))
    return receipt


def campaign_approval_confirmation(draft: dict[str, Any]) -> str:
    """Return the exact confirmation token bound to this match and two content hashes."""

    if draft.get("schema_version") != CAMPAIGN_DRAFT_SCHEMA:
        raise MatchDetailsLoadError("No es un borrador de publicación de campaña.")
    return (
        f"APPROVE-{draft.get('source_match_id')}-"
        f"{str(draft.get('source_html_sha256', ''))[:12]}-"
        f"{str(draft.get('details_sha256', ''))[:12]}"
    )


def _normalize_legacy_campaign_event_fields(details: Any) -> Any:
    """Normalize only known nullable-field serialization drift in event DTOs.

    Older reviewed drafts serialized ``source_description`` as null and set
    ``is_own_goal`` to false on every non-own-goal event.  The current DTO may
    omit the former or serialize it as null, and uses null for the latter.
    ``event_kind`` is the authoritative event classification, so false/null is
    equivalent only when the event is explicitly not an own goal.  All other
    event fields remain byte-for-byte comparable after canonical JSON.
    """

    if not isinstance(details, dict):
        return details
    normalized = json.loads(_canonical_json(details))
    events = normalized.get("events")
    non_own_goal_kinds = {
        "goal", "penalty", "yellow_card", "red_card", "missed_penalty",
        "second_yellow", "substitution", "substitution_in", "substitution_out", "other",
    }
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict):
                continue
            if event.get("source_description", object()) is None:
                event.pop("source_description", None)
            if (
                event.get("event_kind") in non_own_goal_kinds
                and (
                    event.get("is_own_goal", object()) is None
                    or event.get("is_own_goal", object()) is False
                )
            ):
                event.pop("is_own_goal", None)
    return normalized


def _campaign_draft_matches_revalidated_evidence(
    saved_draft: dict[str, Any], rebuilt_draft: dict[str, Any]
) -> bool:
    """Check a saved reviewed draft against a fresh reconstruction.

    Draft content hashes are independently checked before comparison. Only
    the two documented nullable event-field serialization changes above are
    normalized; source IDs, artifact hashes, metadata and sports values must
    still match exactly. The caller must continue publishing ``saved_draft``
    so its original approval and document hash remain intact.
    """

    for candidate in (saved_draft, rebuilt_draft):
        details = candidate.get("details")
        details_hash = candidate.get("details_sha256")
        if (
            not isinstance(details, dict)
            or not isinstance(details_hash, str)
            or _sha256(_canonical_json(details)) != details_hash
        ):
            return False

    saved = json.loads(_canonical_json(saved_draft))
    rebuilt = json.loads(_canonical_json(rebuilt_draft))
    saved.pop("details_sha256", None)
    rebuilt.pop("details_sha256", None)
    saved["details"] = _normalize_legacy_campaign_event_fields(saved["details"])
    rebuilt["details"] = _normalize_legacy_campaign_event_fields(rebuilt["details"])
    return _canonical_json(saved) == _canonical_json(rebuilt)


def _campaign_published_document_matches_revalidated_evidence(
    document: MatchPublishedDetailsResponse,
    details_payload: dict[str, Any],
    details_sha256: str,
    rebuilt_draft: dict[str, Any],
) -> bool:
    """Verify a stored package against current source while retaining its hash.

    The package's raw JSON hash and its parsed public DTO must both match. The
    current reconstruction is then compared using the same narrow legacy
    nullable-field rules as publication. This never rewrites the package.
    """

    if _sha256(_canonical_json(details_payload)) != details_sha256:
        return False
    projected = document.model_dump(mode="json", exclude_unset=True)
    if _canonical_json(projected) != _canonical_json(details_payload):
        return False
    saved_draft = json.loads(_canonical_json(rebuilt_draft))
    saved_draft["details"] = projected
    saved_draft["details_sha256"] = details_sha256
    return _campaign_draft_matches_revalidated_evidence(saved_draft, rebuilt_draft)


def build_campaign_approval_receipt(
    draft: dict[str, Any],
    *,
    approved_by: str,
    confirm_internal_id: str,
    confirm_source_html_sha256: str,
    confirm_details_sha256: str,
    confirm_action: str,
    approved_at_utc: datetime | None = None,
) -> dict[str, Any]:
    """Create an approval receipt only after an explicit hash-specific confirmation."""

    if draft.get("schema_version") != CAMPAIGN_DRAFT_SCHEMA:
        raise MatchDetailsLoadError("No es un borrador de publicación de campaña.")
    if (
        not isinstance(approved_by, str)
        or not approved_by.strip()
        or confirm_internal_id != draft.get("internal_id")
        or confirm_source_html_sha256 != draft.get("source_html_sha256")
        or confirm_details_sha256 != draft.get("details_sha256")
        or confirm_action != campaign_approval_confirmation(draft)
        or draft.get("source_kind") != "campaign_discovery"
        or draft.get("capture_promotion_enabled") is not False
        or draft.get("promotion_eligible") is not False
        or draft.get("access_status") != "VALID"
        or draft.get("semantic_valid") is not True
        or _sha256(_canonical_json(draft.get("details"))) != draft.get("details_sha256")
    ):
        raise MatchDetailsLoadError("La aprobación no confirma el partido, HTML y documento exactos.")
    approved_at_utc = approved_at_utc or datetime.now(timezone.utc)
    if approved_at_utc.tzinfo is None:
        raise MatchDetailsLoadError("La fecha de aprobación debe incluir zona horaria.")
    fields = (
        "publication_id", "source_kind", "internal_id", "inventory_id",
        "source_generation_id", "source_generation_manifest_sha256", "source_capture_id",
        "source_match_id", "season", "competition", "group", "matchday", "source_match_date",
        "home_team_id", "away_team_id", "home_team_name", "away_team_name",
        "campaign_id", "artifact_id", "navigation_attempt_id", "artifact_manifest_sha256",
        "source_html_sha256", "details_sha256",
    )
    return {
        "schema_version": CAMPAIGN_APPROVAL_SCHEMA,
        "publication_status": "approved",
        "approval_confirmation": confirm_action,
        "approved_by": approved_by.strip(),
        "approved_at_utc": approved_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        **{key: draft[key] for key in fields},
    }


def build_auto_policy_receipt(
    draft: dict[str, Any],
    *,
    validation: dict[str, Any],
    update_job_id: str,
    candidate_set_sha256: str,
    validation_event_sha256: str,
    approved_at_utc: datetime | None = None,
) -> dict[str, Any]:
    """Create a machine-policy receipt distinct from human approval records."""

    from football_data_hub.providers.bdfutbol.match_details.automatic_publication_policy import (
        POLICY_ID,
        POLICY_VERSION,
        automatic_publication_decision,
    )

    eligible, reason = automatic_publication_decision(validation)
    if (
        draft.get("schema_version") != CAMPAIGN_DRAFT_SCHEMA
        or draft.get("source_kind") != "campaign_discovery"
        or draft.get("access_status") != "VALID"
        or draft.get("semantic_valid") is not True
        or draft.get("capture_promotion_enabled") is not False
        or draft.get("promotion_eligible") is not False
        or _sha256(_canonical_json(draft.get("details"))) != draft.get("details_sha256")
        or not eligible
        or not isinstance(update_job_id, str)
        or not re.fullmatch(r"[0-9a-f-]{36}", update_job_id)
        or not re.fullmatch(r"[a-f0-9]{64}", candidate_set_sha256)
        or not re.fullmatch(r"[a-f0-9]{64}", validation_event_sha256)
    ):
        raise MatchDetailsLoadError(
            f"El documento no cumple la política automática estricta ({reason or 'procedencia inválida'})."
        )
    approved_at_utc = approved_at_utc or datetime.now(timezone.utc)
    if approved_at_utc.tzinfo is None:
        raise MatchDetailsLoadError("La decisión automática debe incluir zona horaria.")
    identity_fields = (
        "publication_id", "source_kind", "internal_id", "inventory_id",
        "source_generation_id", "source_generation_manifest_sha256", "source_capture_id",
        "source_match_id", "season", "competition", "group", "matchday", "source_match_date",
        "home_team_id", "away_team_id", "home_team_name", "away_team_name",
        "campaign_id", "artifact_id", "navigation_attempt_id", "artifact_manifest_sha256",
        "source_html_sha256", "details_sha256",
    )
    return {
        "schema_version": AUTO_POLICY_RECEIPT_SCHEMA,
        "publication_status": "approved",
        "approval_mode": "automatic_policy",
        "policy_id": POLICY_ID,
        "policy_version": POLICY_VERSION,
        "update_job_id": update_job_id,
        "candidate_set_sha256": candidate_set_sha256,
        "validation_event_sha256": validation_event_sha256,
        "validation_evidence_sha256": _sha256(_canonical_json(validation)),
        "validation": json.loads(_canonical_json(validation)),
        "approved_at_utc": approved_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        **{key: draft[key] for key in identity_fields},
    }


def write_immutable_publication_json(path: Path, value: dict[str, Any]) -> Path:
    """Write one canonical derived record without replacing previous evidence."""

    target = path.expanduser().absolute()
    cursor = target
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise MatchDetailsLoadError(f"No se permiten symlinks en la salida: {cursor}")
        cursor = cursor.parent
    target.parent.mkdir(parents=True, exist_ok=True)
    cursor = target
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise MatchDetailsLoadError(f"No se permiten symlinks en la salida: {cursor}")
        cursor = cursor.parent
    if target.exists():
        raise MatchDetailsLoadError(f"No se sobrescribe un registro inmutable: {target}")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        raw = _canonical_json(value) + b"\n"
        with os.fdopen(fd, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError as exc:
        raise MatchDetailsLoadError(f"No se sobrescribe un registro inmutable: {target}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return target


def publish_match_detail_draft(
    draft: dict[str, Any],
    *,
    approval_receipt: dict[str, Any],
    published_root: Path,
    store_root: Path,
    generation_root: Path,
    data_root: Path,
    match_bundle: MatchResultsBundle,
    player_ids: set[int],
) -> dict[str, str]:
    """Atomically publish a reverified draft only with an exact explicit approval.

    This is an operator-invoked function, not called at startup. Prior packages
    and source captures remain immutable when a later publication replaces the
    active index reference.
    """

    if not isinstance(draft, dict) or not isinstance(approval_receipt, dict):
        raise MatchDetailsLoadError("Se requiere un borrador y un recibo de aprobación explícito.")
    expected_draft = build_match_detail_publication_draft(
        internal_id=str(draft.get("internal_id", "")),
        capture_id=str(draft.get("capture_id", "")),
        publication_id=str(draft.get("publication_id", "")),
        store_root=store_root,
        generation_root=generation_root,
        data_root=data_root,
        match_bundle=match_bundle,
        player_ids=player_ids,
    )
    if _canonical_json(draft) != _canonical_json(expected_draft):
        raise MatchDetailsLoadError("El borrador ya no coincide con la captura fuente verificada.")
    receipt_fields = {
        "schema_version", "publication_status", "approved_by", "approved_at_utc",
        "publication_id", "internal_id", "inventory_id", "capture_id",
        "source_generation_id", "source_generation_manifest_sha256", "source_capture_id",
        "match_detail_sha256", "source_html_sha256", "details_sha256",
    }
    if set(approval_receipt) != receipt_fields or approval_receipt.get("schema_version") != APPROVAL_SCHEMA:
        raise MatchDetailsLoadError("El recibo de aprobación no cumple el contrato exacto.")
    if (
        approval_receipt.get("publication_status") != "approved"
        or not isinstance(approval_receipt.get("approved_by"), str)
        or not approval_receipt["approved_by"].strip()
    ):
        raise MatchDetailsLoadError("Se requiere aprobación independiente identificada.")
    approved_at = approval_receipt.get("approved_at_utc")
    if not isinstance(approved_at, str):
        raise MatchDetailsLoadError("El recibo de aprobación no tiene fecha.")
    try:
        parsed_approval_date = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MatchDetailsLoadError("La fecha de aprobación no es válida.") from exc
    if parsed_approval_date.tzinfo is None:
        raise MatchDetailsLoadError("La fecha de aprobación debe incluir zona horaria.")
    for field in receipt_fields - {"schema_version", "publication_status", "approved_by", "approved_at_utc"}:
        if approval_receipt.get(field) != expected_draft.get(field):
            raise MatchDetailsLoadError(f"La aprobación no autoriza el campo exacto {field}.")

    root = _safe_root(published_root)
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise MatchDetailsLoadError("La raíz de publicación no puede ser symlink.")
    lock_path = root / ".publication.lock"
    if lock_path.is_symlink():
        raise MatchDetailsLoadError("El bloqueo de publicación no puede ser symlink.")
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            package_id = expected_draft["publication_id"]
            packages_root = root / "packages"
            packages_root.mkdir(exist_ok=True)
            if packages_root.is_symlink() or not packages_root.is_dir():
                raise MatchDetailsLoadError("El directorio de paquetes no puede ser symlink.")
            package = packages_root / package_id
            if package.exists() or package.is_symlink():
                raise MatchDetailsLoadError("Una publicación inmutable con ese ID ya existe.")
            index_path = root / "index.json"
            previous_index: bytes | None = None
            entries: list[dict[str, str]] = []
            if index_path.is_symlink():
                raise MatchDetailsLoadError("El índice actual no puede ser symlink.")
            if index_path.exists():
                if not index_path.is_file():
                    raise MatchDetailsLoadError("El índice actual no es regular.")
                current, previous_index = _read_json(index_path)
                if current.get("schema_version") != INDEX_SCHEMA or set(current) != {"schema_version", "publications"} or not isinstance(current.get("publications"), list):
                    raise MatchDetailsLoadError("El índice actual no se puede actualizar con seguridad.")
                entries = list(current["publications"])
                if any(
                    not isinstance(entry, dict)
                    or set(entry) != {"internal_id", "publication_id", "package_path", "manifest_sha256"}
                    or not isinstance(entry.get("internal_id"), str)
                    or not isinstance(entry.get("publication_id"), str)
                    or not isinstance(entry.get("package_path"), str)
                    or not isinstance(entry.get("manifest_sha256"), str)
                    or not _PUBLICATION_ID.fullmatch(entry["publication_id"])
                    or entry["package_path"] != f"packages/{entry['publication_id']}"
                    or not re.fullmatch(r"[a-f0-9]{64}", entry["manifest_sha256"])
                    for entry in entries
                ):
                    raise MatchDetailsLoadError("El índice actual contiene referencias inválidas.")
                if len({entry["internal_id"] for entry in entries}) != len(entries):
                    raise MatchDetailsLoadError("El índice actual contiene partidos duplicados.")

            approval_raw = _canonical_json(approval_receipt)
            details_raw = _canonical_json(expected_draft["details"])
            manifest = {
                "schema_version": PACKAGE_SCHEMA,
                "publication_id": package_id,
                "internal_id": expected_draft["internal_id"],
                "inventory_id": expected_draft["inventory_id"],
                "capture_id": expected_draft["capture_id"],
                "source_generation_id": expected_draft["source_generation_id"],
                "source_generation_manifest_sha256": expected_draft["source_generation_manifest_sha256"],
                "source_capture_id": expected_draft["source_capture_id"],
                "match_detail_sha256": expected_draft["match_detail_sha256"],
                "source_html_sha256": expected_draft["source_html_sha256"],
                "details_sha256": _sha256(details_raw),
                "approval_sha256": _sha256(approval_raw),
            }
            manifest_raw = _canonical_json(manifest)
            temporary_package = Path(tempfile.mkdtemp(prefix=f".{package_id}.", dir=packages_root))
            try:
                for filename, content in (("approval.json", approval_raw), ("details.json", details_raw), ("manifest.json", manifest_raw)):
                    with (temporary_package / filename).open("xb") as output:
                        output.write(content)
                        output.flush()
                        os.fsync(output.fileno())
                package_fd = os.open(temporary_package, os.O_RDONLY)
                try:
                    os.fsync(package_fd)
                finally:
                    os.close(package_fd)
                os.replace(temporary_package, package)
            finally:
                if temporary_package.exists():
                    shutil.rmtree(temporary_package)
            package_root_fd = os.open(packages_root, os.O_RDONLY)
            try:
                os.fsync(package_root_fd)
            finally:
                os.close(package_root_fd)

            entry = {
                "internal_id": expected_draft["internal_id"],
                "publication_id": package_id,
                "package_path": f"packages/{package_id}",
                "manifest_sha256": _sha256(manifest_raw),
            }
            entries = [entry for entry in entries if entry["internal_id"] != expected_draft["internal_id"]]
            entries.append(entry)
            entries.sort(key=lambda item: item["internal_id"])
            new_index_raw = _canonical_json({"schema_version": INDEX_SCHEMA, "publications": entries})
            if previous_index is not None:
                history = root / "indexes"
                history.mkdir(exist_ok=True)
                if history.is_symlink() or not history.is_dir():
                    raise MatchDetailsLoadError("El directorio de historial no puede ser symlink.")
                history_path = history / f"{_sha256(previous_index)}.json"
                if history_path.is_symlink():
                    raise MatchDetailsLoadError("El índice histórico no puede ser symlink.")
                if history_path.exists():
                    if history_path.read_bytes() != previous_index:
                        raise MatchDetailsLoadError("El archivo histórico existente no conserva el índice original.")
                else:
                    _atomic_bytes(history_path, previous_index)
            _atomic_bytes(index_path, new_index_raw)
            try:
                loaded = load_published_match_details(
                    root,
                    store_root=store_root,
                    generation_root=generation_root,
                    data_root=data_root,
                    match_bundle=match_bundle,
                    player_ids=player_ids,
                    internal_ids={draft["internal_id"]},
                )
                if expected_draft["internal_id"] not in loaded:
                    raise MatchDetailsLoadError("La publicación no aparece tras la validación final.")
            except BaseException:
                if previous_index is None:
                    index_path.unlink(missing_ok=True)
                else:
                    _atomic_bytes(index_path, previous_index)
                raise
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    return {"internal_id": expected_draft["internal_id"], "publication_id": package_id}


def publish_campaign_match_detail_draft(
    draft: dict[str, Any],
    *,
    approval_receipt: dict[str, Any],
    published_root: Path,
    store_root: Path,
    generation_root: Path,
    data_root: Path,
    match_bundle: MatchResultsBundle,
    player_ids: set[int],
) -> dict[str, str]:
    """Publish one freshly revalidated campaign discovery after human or policy approval."""

    if not isinstance(draft, dict) or not isinstance(approval_receipt, dict):
        raise MatchDetailsLoadError("Se requiere borrador y aprobación individual explícita.")
    expected = build_campaign_publication_draft(
        internal_id=str(draft.get("internal_id", "")),
        campaign_id=str(draft.get("campaign_id", "")),
        artifact_id=str(draft.get("artifact_id", "")),
        publication_id=str(draft.get("publication_id", "")),
        generation_root=generation_root,
        data_root=data_root,
        match_bundle=match_bundle,
        player_ids=player_ids,
    )
    if not _campaign_draft_matches_revalidated_evidence(draft, expected):
        raise MatchDetailsLoadError("El borrador ya no coincide con la evidencia de campaña revalidada.")
    if approval_receipt.get("schema_version") == CAMPAIGN_APPROVAL_SCHEMA:
        expected_approval = build_campaign_approval_receipt(
            draft,
            approved_by=str(approval_receipt.get("approved_by", "")),
            confirm_internal_id=str(approval_receipt.get("internal_id", "")),
            confirm_source_html_sha256=str(approval_receipt.get("source_html_sha256", "")),
            confirm_details_sha256=str(approval_receipt.get("details_sha256", "")),
            confirm_action=campaign_approval_confirmation(draft),
            approved_at_utc=_parse_approval_timestamp(approval_receipt.get("approved_at_utc")),
        )
    elif approval_receipt.get("schema_version") == AUTO_POLICY_RECEIPT_SCHEMA:
        expected_approval = build_auto_policy_receipt(
            draft,
            validation=approval_receipt.get("validation"),
            update_job_id=str(approval_receipt.get("update_job_id", "")),
            candidate_set_sha256=str(approval_receipt.get("candidate_set_sha256", "")),
            validation_event_sha256=str(approval_receipt.get("validation_event_sha256", "")),
            approved_at_utc=_parse_approval_timestamp(approval_receipt.get("approved_at_utc")),
        )
    else:
        raise MatchDetailsLoadError("El recibo no corresponde a un contrato humano o automático conocido.")
    if _canonical_json(approval_receipt) != _canonical_json(expected_approval):
        raise MatchDetailsLoadError("El recibo de aprobación no autoriza exactamente este borrador.")

    root = _safe_root(published_root)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".publication.lock"
    if lock_path.is_symlink():
        raise MatchDetailsLoadError("El bloqueo de publicación no puede ser symlink.")
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            # Publish the exact reviewed document. The rebuilt form above is
            # used only to revalidate provenance and semantic equivalence; it
            # must never replace the hash-bound draft or its receipt.
            package_id = draft["publication_id"]
            packages_root = root / "packages"
            packages_root.mkdir(exist_ok=True)
            if packages_root.is_symlink() or not packages_root.is_dir():
                raise MatchDetailsLoadError("El directorio de paquetes no es regular.")
            package = packages_root / package_id

            index_path = root / "index.json"
            previous_index: bytes | None = None
            entries: list[dict[str, str]] = []
            if index_path.is_symlink():
                raise MatchDetailsLoadError("El índice actual no puede ser symlink.")
            if index_path.exists():
                if not index_path.is_file():
                    raise MatchDetailsLoadError("El índice actual no es regular.")
                current, previous_index = _read_json(index_path)
                entries = _validated_index_entries(current)

            details_raw = _canonical_json(draft["details"])
            approval_raw = _canonical_json(approval_receipt)
            manifest = {
                "schema_version": CAMPAIGN_PACKAGE_SCHEMA,
                **{
                    key: draft[key]
                    for key in (
                        "publication_id", "source_kind", "internal_id", "inventory_id",
                        "source_generation_id", "source_generation_manifest_sha256",
                        "source_capture_id", "source_match_id", "season", "competition", "group",
                        "matchday", "source_match_date", "home_team_id", "away_team_id",
                        "home_team_name", "away_team_name",
                        "campaign_id", "artifact_id",
                        "navigation_attempt_id", "artifact_manifest_sha256", "source_html_sha256",
                        "details_sha256",
                    )
                },
                "approval_sha256": _sha256(approval_raw),
            }
            manifest_raw = _canonical_json(manifest)
            reuse_exact_orphan_package = False
            if package.exists() or package.is_symlink():
                active = next(
                    (entry for entry in entries if entry["internal_id"] == draft["internal_id"]),
                    None,
                )
                if (
                    package.is_symlink()
                    or not package.is_dir()
                    or any(path.is_symlink() for path in package.rglob("*"))
                    or {path.name for path in package.iterdir()} != {
                        "approval.json", "details.json", "manifest.json"
                    }
                ):
                    raise MatchDetailsLoadError("La publicación existente está incompleta o no es regular.")
                existing_bytes = {
                    name: (package / name).read_bytes()
                    for name in ("approval.json", "details.json", "manifest.json")
                }
                if (
                    existing_bytes["approval.json"] != approval_raw
                    or existing_bytes["details.json"] != details_raw
                    or existing_bytes["manifest.json"] != manifest_raw
                    or (active is not None and (
                        active["publication_id"] != package_id
                        or active["manifest_sha256"] != _sha256(manifest_raw)
                    ))
                    or any(
                        entry["publication_id"] == package_id
                        and entry["internal_id"] != draft["internal_id"]
                        for entry in entries
                    )
                ):
                    raise MatchDetailsLoadError("Una publicación inmutable con ese ID ya existe con contenido distinto o inactiva.")
                if active is not None:
                    loaded = load_published_match_details(
                        root,
                        store_root=store_root,
                        generation_root=generation_root,
                        data_root=data_root,
                        match_bundle=match_bundle,
                        player_ids=player_ids,
                        internal_ids={draft["internal_id"]},
                    )
                    if draft["internal_id"] not in loaded:
                        raise MatchDetailsLoadError("La publicación existente no supera su lectura final.")
                    return {"internal_id": draft["internal_id"], "publication_id": package_id}
                # A previous attempt may have completed the immutable package
                # files but failed before the index passed final verification.
                # Reuse only the exact hash-bound package; never replace it.
                reuse_exact_orphan_package = True
            if not reuse_exact_orphan_package:
                stage = Path(tempfile.mkdtemp(prefix=f".{package_id}.", dir=packages_root))
                try:
                    for filename, content in (
                        ("approval.json", approval_raw),
                        ("details.json", details_raw),
                        ("manifest.json", manifest_raw),
                    ):
                        with (stage / filename).open("xb") as output:
                            output.write(content)
                            output.flush()
                            os.fsync(output.fileno())
                    stage_fd = os.open(stage, os.O_RDONLY)
                    try:
                        os.fsync(stage_fd)
                    finally:
                        os.close(stage_fd)
                    # Reserve the immutable final name without replacing any existing package.
                    package.mkdir()
                    for filename in ("approval.json", "details.json", "manifest.json"):
                        os.rename(stage / filename, package / filename)
                    package_fd = os.open(package, os.O_RDONLY)
                    try:
                        os.fsync(package_fd)
                    finally:
                        os.close(package_fd)
                    packages_fd = os.open(packages_root, os.O_RDONLY)
                    try:
                        os.fsync(packages_fd)
                    finally:
                        os.close(packages_fd)
                finally:
                    shutil.rmtree(stage, ignore_errors=True)

            entry = {
                "internal_id": draft["internal_id"],
                "publication_id": package_id,
                "package_path": f"packages/{package_id}",
                "manifest_sha256": _sha256(manifest_raw),
            }
            entries = [item for item in entries if item["internal_id"] != draft["internal_id"]]
            entries.append(entry)
            entries.sort(key=lambda item: item["internal_id"])
            new_index = _canonical_json({"schema_version": INDEX_SCHEMA, "publications": entries})
            if previous_index is not None:
                history = root / "indexes"
                history.mkdir(exist_ok=True)
                if history.is_symlink() or not history.is_dir():
                    raise MatchDetailsLoadError("El historial de índices no es regular.")
                history_path = history / f"{_sha256(previous_index)}.json"
                if history_path.is_symlink():
                    raise MatchDetailsLoadError("Un índice histórico es symlink.")
                if history_path.exists():
                    if not history_path.is_file() or history_path.read_bytes() != previous_index:
                        raise MatchDetailsLoadError("El índice histórico existente difiere de su hash.")
                else:
                    _atomic_bytes(history_path, previous_index)
            _atomic_bytes(index_path, new_index)
            try:
                loaded = load_published_match_details(
                    root,
                    store_root=store_root,
                    generation_root=generation_root,
                    data_root=data_root,
                    match_bundle=match_bundle,
                    player_ids=player_ids,
                    internal_ids={draft["internal_id"]},
                )
                if draft["internal_id"] not in loaded:
                    raise MatchDetailsLoadError("La publicación no aparece en la recarga de verificación.")
            except BaseException:
                if previous_index is None:
                    index_path.unlink(missing_ok=True)
                    root_fd = os.open(root, os.O_RDONLY)
                    try:
                        os.fsync(root_fd)
                    finally:
                        os.close(root_fd)
                else:
                    _atomic_bytes(index_path, previous_index)
                raise
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    return {"internal_id": draft["internal_id"], "publication_id": package_id}


def publish_legacy_recovery_match_detail_by_policy(
    *,
    recovery_id: str,
    update_job_id: str,
    published_root: Path,
    store_root: Path,
    generation_root: Path,
    data_root: Path,
    match_bundle: MatchResultsBundle,
    player_ids: set[int],
) -> dict[str, Any]:
    """Publish 272582 only from its reverified offline recovery and specific policy receipt."""

    draft, _observation, validation = build_legacy_recovery_publication_draft(
        recovery_id=recovery_id,
        update_job_id=update_job_id,
        store_root=store_root,
        data_root=data_root,
        generation_root=generation_root,
        match_bundle=match_bundle,
        player_ids=player_ids,
    )
    receipt = build_legacy_recovery_auto_policy_receipt(
        draft, validation=validation, update_job_id=update_job_id
    )
    receipt_raw = _canonical_json(receipt)
    details_raw = _canonical_json(draft["details"])
    manifest = _legacy_recovery_manifest(draft, receipt_raw)
    manifest_raw = _canonical_json(manifest)

    root = _safe_root(published_root)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".publication.lock"
    if lock_path.is_symlink():
        raise MatchDetailsLoadError("El bloqueo de publicación no puede ser symlink.")
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            packages_root = root / "packages"
            packages_root.mkdir(exist_ok=True)
            if packages_root.is_symlink() or not packages_root.is_dir():
                raise MatchDetailsLoadError("El directorio de paquetes publicados no es regular.")
            index_path = root / "index.json"
            previous_index: bytes | None = None
            entries: list[dict[str, str]] = []
            if index_path.is_symlink():
                raise MatchDetailsLoadError("El índice publicado no puede ser symlink.")
            if index_path.exists():
                current, previous_index = _read_json(index_path)
                entries = _validated_index_entries(current)
            existing = next(
                (entry for entry in entries if entry["internal_id"] == draft["internal_id"]),
                None,
            )
            package_id = draft["publication_id"]
            package = packages_root / package_id
            if existing is not None:
                if existing["publication_id"] != package_id or existing["manifest_sha256"] != _sha256(manifest_raw):
                    raise MatchDetailsLoadError("272582 ya tiene una publicación distinta; no se reemplaza.")
                loaded = load_published_match_details(
                    root,
                    store_root=store_root,
                    generation_root=generation_root,
                    data_root=data_root,
                    match_bundle=match_bundle,
                    player_ids=player_ids,
                    internal_ids={draft["internal_id"]},
                )
                if draft["internal_id"] not in loaded:
                    raise MatchDetailsLoadError("La recuperación existente no supera la lectura final.")
                return {
                    "status": "ALREADY_PUBLISHED_VERIFIED",
                    "internal_id": draft["internal_id"],
                    "publication_id": package_id,
                    "manifest_sha256": _sha256(manifest_raw),
                }
            if any(entry["publication_id"] == package_id for entry in entries):
                raise MatchDetailsLoadError("El ID de publicación de recuperación ya pertenece a otro partido.")

            package_files = {
                "approval.json": receipt_raw,
                "details.json": details_raw,
                "manifest.json": manifest_raw,
            }
            if package.exists() or package.is_symlink():
                if (
                    package.is_symlink()
                    or not package.is_dir()
                    or any(path.is_symlink() for path in package.rglob("*"))
                    or {path.name for path in package.iterdir()} != set(package_files)
                    or any((package / name).read_bytes() != content for name, content in package_files.items())
                ):
                    raise MatchDetailsLoadError("Existe un paquete huérfano de recuperación con datos distintos.")
            else:
                stage = Path(tempfile.mkdtemp(prefix=f".{package_id}.", dir=packages_root))
                try:
                    for name, content in package_files.items():
                        with (stage / name).open("xb") as output:
                            output.write(content)
                            output.flush()
                            os.fsync(output.fileno())
                    stage_fd = os.open(stage, os.O_RDONLY)
                    try:
                        os.fsync(stage_fd)
                    finally:
                        os.close(stage_fd)
                    os.replace(stage, package)
                    packages_fd = os.open(packages_root, os.O_RDONLY)
                    try:
                        os.fsync(packages_fd)
                    finally:
                        os.close(packages_fd)
                finally:
                    if stage.exists():
                        shutil.rmtree(stage, ignore_errors=True)

            entry = {
                "internal_id": draft["internal_id"],
                "publication_id": package_id,
                "package_path": f"packages/{package_id}",
                "manifest_sha256": _sha256(manifest_raw),
            }
            entries.append(entry)
            entries.sort(key=lambda item: item["internal_id"])
            new_index_raw = _canonical_json({"schema_version": INDEX_SCHEMA, "publications": entries})
            if previous_index is not None:
                history = root / "indexes"
                history.mkdir(exist_ok=True)
                if history.is_symlink() or not history.is_dir():
                    raise MatchDetailsLoadError("El historial del índice publicado no es regular.")
                history_path = history / f"{_sha256(previous_index)}.json"
                if history_path.is_symlink():
                    raise MatchDetailsLoadError("El índice histórico no puede ser symlink.")
                if history_path.exists():
                    if not history_path.is_file() or history_path.read_bytes() != previous_index:
                        raise MatchDetailsLoadError("El índice histórico existente no conserva sus bytes.")
                else:
                    _atomic_bytes(history_path, previous_index)
            _atomic_bytes(index_path, new_index_raw)
            try:
                loaded = load_published_match_details(
                    root,
                    store_root=store_root,
                    generation_root=generation_root,
                    data_root=data_root,
                    match_bundle=match_bundle,
                    player_ids=player_ids,
                    internal_ids={draft["internal_id"]},
                )
                if draft["internal_id"] not in loaded:
                    raise MatchDetailsLoadError("El paquete recuperado no aparece tras la validación final.")
            except BaseException:
                if previous_index is None:
                    index_path.unlink(missing_ok=True)
                    root_fd = os.open(root, os.O_RDONLY)
                    try:
                        os.fsync(root_fd)
                    finally:
                        os.close(root_fd)
                else:
                    _atomic_bytes(index_path, previous_index)
                raise
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    return {
        "status": "PUBLISHED_VERIFIED",
        "internal_id": draft["internal_id"],
        "publication_id": package_id,
        "manifest_sha256": _sha256(manifest_raw),
        "details_sha256": draft["details_sha256"],
        "receipt_sha256": receipt["receipt_sha256"],
    }


def _parse_approval_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise MatchDetailsLoadError("El recibo de aprobación carece de fecha ISO.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MatchDetailsLoadError("La fecha de aprobación no es ISO válida.") from exc
    if result.tzinfo is None:
        raise MatchDetailsLoadError("La fecha de aprobación no incluye zona horaria.")
    return result


def _validated_index_entries(value: dict[str, Any]) -> list[dict[str, str]]:
    if (
        value.get("schema_version") != INDEX_SCHEMA
        or set(value) != {"schema_version", "publications"}
        or not isinstance(value.get("publications"), list)
    ):
        raise MatchDetailsLoadError("El índice actual no se puede actualizar con seguridad.")
    entries = value["publications"]
    if any(
        not isinstance(entry, dict)
        or set(entry) != {"internal_id", "publication_id", "package_path", "manifest_sha256"}
        or not all(isinstance(entry.get(key), str) for key in entry)
        or not _PUBLICATION_ID.fullmatch(entry["publication_id"])
        or entry["package_path"] != f"packages/{entry['publication_id']}"
        or not re.fullmatch(r"[a-f0-9]{64}", entry["manifest_sha256"])
        for entry in entries
    ):
        raise MatchDetailsLoadError("El índice actual contiene referencias inválidas.")
    if len({entry["internal_id"] for entry in entries}) != len(entries):
        raise MatchDetailsLoadError("El índice actual contiene partidos duplicados.")
    return list(entries)


def build_discovery_preview(
    observation: Any,
    *,
    match_page: Any,
    player_ids: set[int],
) -> MatchPublishedDetailsResponse:
    """Build a display-only DTO from the semantic observer; never publish it."""

    if observation.validation.semantic_valid is not True or observation.validation.promotion_eligible is not False:
        raise MatchDetailsLoadError("La observación no cumple el contrato de vista previa local.")
    if observation.source.artifact_access_status not in {"VALID", "INVALID_CONTENT"} or observation.source.promotion_eligible is not False:
        raise MatchDetailsLoadError("El artefacto no es un descubrimiento verificable.")
    if (
        observation.source.internal_id != match_page.match.internal_id
        or observation.source.source_match_id != match_page.match.source_match_id
        or observation.source.source_generation_id != match_page.metadata.generation_id
        or observation.source.source_capture_id != match_page.metadata.source_capture_id
        or observation.home.team.team_id != match_page.match.home_team.team_id
        or observation.away.team.team_id != match_page.match.away_team.team_id
        or observation.score.home_goals != match_page.match.home_goals
        or observation.score.away_goals != match_page.match.away_goals
    ):
        raise MatchDetailsLoadError("La observación local no coincide con el partido de MATCH-00.")

    def preview_side(side: Any) -> MatchPublishedSideResponse:
        def player(item: Any, role: str) -> MatchPublishedPlayerResponse:
            return MatchPublishedPlayerResponse(
                player_id=item.player_id,
                display_name=item.name,
                profile_url=_source_url(item.profile_url),
                photo_url=_source_url(item.photo_url),
                shirt_number=item.shirt_number,
                position=None,
                role=role,
                participation_status=(item.participation_status if role == "substitute" else "not_applicable"),
                player_profile_available=item.player_id in player_ids,
            )

        coach = None
        if side.coach is not None:
            from football_data_hub_api.schemas import MatchPublishedCoachResponse

            coach = MatchPublishedCoachResponse(
                coach_id=side.coach.coach_id,
                display_name=side.coach.name,
                profile_url=_source_url(side.coach.profile_url),
                photo_url=_source_url(side.coach.photo_url),
            )
        return MatchPublishedSideResponse(
            team_id=side.team.team_id,
            coach=coach,
            starters=None if side.starters is None else [player(item, "starter") for item in side.starters],
            substitutes=None if side.substitutes is None else [player(item, "substitute") for item in side.substitutes],
        )

    kind_map = {
        "goal": "goal",
        "penalty_goal": "penalty",
        "own_goal": "own_goal",
        "missed_penalty": "missed_penalty",
        "yellow_card": "yellow_card",
        "red_card": "red_card",
        "second_yellow": "second_yellow",
        "substitution_in": "substitution_in",
        "substitution_out": "substitution_out",
        "other": "other",
    }
    events = [
        MatchPublishedEventResponse(
            event_kind=kind_map[event.event_type],
            minute=event.minute_literal,
            team_id=event.team_id,
            player_id=event.player_id,
            player_name=event.player_name,
            related_player_id=None,
            related_player_name=None,
            is_penalty=event.is_penalty,
            is_own_goal=True if event.event_type == "own_goal" else None,
            source_description=(event.raw_icon_title if event.event_type == "other" else None),
            score_after_home=event.score_after_home,
            score_after_away=event.score_after_away,
            player_profile_available=event.player_id is not None and event.player_id in player_ids,
            related_player_profile_available=False,
        )
        for event in observation.events
        if event.event_type in kind_map
    ]
    match_date = observation.match_date.value
    return MatchPublishedDetailsResponse(
        publication_status="preview_only",
        validation_status="valid",
        source="BDFutbol",
        internal_id=observation.source.internal_id,
        source_match_id=observation.source.source_match_id,
        source_generation_id=observation.source.source_generation_id,
        source_capture_id=observation.source.source_capture_id,
        source_html_sha256=observation.source.source_html_sha256,
        match_date=date.fromisoformat(str(match_date)) if match_date else None,
        home_team_id=observation.home.team.team_id,
        away_team_id=observation.away.team.team_id,
        home_goals=observation.score.home_goals,
        away_goals=observation.score.away_goals,
        home=preview_side(observation.home),
        away=preview_side(observation.away),
        events=events,
    )


def safe_preview_artifact(path: Path) -> Path:
    """Resolve one explicitly configured local artifact without following symlinks."""

    candidate = path.expanduser().absolute()
    cursor = candidate
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise MatchDetailsLoadError("La ruta del artefacto de vista previa contiene un symlink.")
        cursor = cursor.parent
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        raise MatchDetailsLoadError("El artefacto de vista previa no es un directorio.")
    return resolved


def load_local_discovery_preview(
    artifact_path: Path,
    *,
    internal_id: str,
    generation_root: Path,
    data_root: Path,
    match_bundle: MatchResultsBundle,
    player_ids: set[int],
) -> MatchPageResponse:
    """Read one explicitly configured discovery artifact for a loopback preview."""

    artifact = safe_preview_artifact(artifact_path)
    generation_root = match_bundle.generation_root or resolve_match_generation_root(
        generation_root, data_root=data_root
    )
    generation = load_verified_match_generation(generation_root, data_root=data_root)
    if (
        generation.generation_id != match_bundle.bootstrap.metadata.generation_id
        or generation.manifest_sha256 != match_bundle.bootstrap.metadata.generation_sha256
    ):
        raise MatchDetailsLoadError("La vista previa usa una generación distinta de Resultados.")
    inventory = build_match_detail_inventory(generation)
    expected = next(
        (record for record in inventory["matches"] if record["internal_id"] == internal_id),
        None,
    )
    if expected is None:
        raise MatchDetailsLoadError("El partido no está en el inventario disputado de MATCH-00.")
    base = build_match_page(match_bundle, internal_id)
    if base is None:
        raise MatchDetailsLoadError("El partido no está disponible en MATCH-00.")
    try:
        artifact_manifest, _ = _read_json(artifact / "manifest.json")
    except (MatchDetailsLoadError, OSError, ValueError) as exc:
        raise MatchDetailsLoadError("No se puede leer el manifiesto del artefacto de vista previa") from exc
    if (
        artifact_manifest.get("schema_version")
        == "football_data_hub.match_detail_campaign_artifact_manifest.v1"
    ):
        try:
            observation = parse_campaign_saved_artifact(
                artifact,
                expected_match=expected,
                verified_generation=generation,
                data_root=data_root,
            )
        except (ValueError, OSError, KeyError, TypeError) as exc:
            raise MatchDetailsLoadError(
                f"El artefacto de campaña no superó la verificación offline: {exc}"
            ) from exc
    elif (
        artifact_manifest.get("schema_version")
        == "football_data_hub.match_detail_discovery_manifest.v1"
    ):
        observation = parse_saved_artifact(artifact, expected_match=expected)
    else:
        raise MatchDetailsLoadError("Tipo de artefacto de vista previa no soportado")
    details = build_discovery_preview(observation, match_page=base, player_ids=player_ids)
    return MatchPageResponse.model_validate({
        **base.model_dump(),
        "detail_status": "preview_only",
        "details": details.model_dump(),
    })
