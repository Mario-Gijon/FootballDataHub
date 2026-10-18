"""Strict, read-only loader for separately approved match-detail publications."""

from __future__ import annotations

import hashlib
import json
import os
import re
import fcntl
import shutil
from datetime import date, datetime
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
    build_match_detail_inventory,
    load_verified_match_generation,
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
_PUBLICATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class MatchDetailsLoadError(ValueError):
    """A publication is malformed, unapproved, corrupt, or mismatched."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


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


def load_published_match_details(
    published_root: Path,
    *,
    store_root: Path,
    generation_root: Path,
    data_root: Path,
    match_bundle: MatchResultsBundle,
    player_ids: set[int],
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
    generation = load_verified_match_generation(generation_root, data_root=data_root)
    if (
        generation.generation_id != match_bundle.bootstrap.metadata.generation_id
        or generation.manifest_sha256 != match_bundle.bootstrap.metadata.generation_sha256
    ):
        raise MatchDetailsLoadError("La generación de detalles difiere de la cargada por Resultados.")
    inventory = build_match_detail_inventory(generation)
    records = {record["internal_id"]: record for record in inventory["matches"]}
    source_captures = {
        source["group"]: source["capture_id"]
        for source in generation.manifest_payload["source_captures"]
    }
    store = MatchDetailStore(store_root)
    loaded: dict[str, MatchPublishedDetailsResponse] = {}
    seen: set[str] = set()

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
        record = records.get(internal_id)
        if record is None or manifest.get("internal_id") != internal_id:
            raise MatchDetailsLoadError("El partido publicado no pertenece al inventario MATCH-00.")
        if (
            manifest.get("inventory_id") != inventory["inventory_id"]
            or manifest.get("source_generation_id") != generation.generation_id
            or manifest.get("source_generation_manifest_sha256") != generation.manifest_sha256
            or manifest.get("source_capture_id") != source_captures.get(record.get("group"))
        ):
            raise MatchDetailsLoadError("La procedencia del paquete no coincide con MATCH-00.")
        try:
            verified_capture = store.verify_capture_read_only(inventory, str(manifest["capture_id"]))
        except (MatchDetailStoreError, KeyError, TypeError, ValueError) as exc:
            raise MatchDetailsLoadError("La captura fuente no supera la verificación íntegra.") from exc
        if (
            verified_capture["internal_id"] != internal_id
            or verified_capture["match_detail_sha256"] != manifest.get("match_detail_sha256")
            or verified_capture["source_html_sha256"] != manifest.get("source_html_sha256")
            or verified_capture["metadata"].get("source_generation_manifest_sha256") != generation.manifest_sha256
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
        if _canonical_json(document.model_dump(mode="json")) != _canonical_json(projected.model_dump(mode="json")):
            raise MatchDetailsLoadError("El documento preparado no coincide con la captura verificada.")
        match = _published_match(match_bundle, internal_id)
        _validate_detail_against_match(
            document,
            match,
            generation_id=generation.generation_id,
            generation_sha256=generation.manifest_sha256,
            source_generation_manifest_sha256=str(manifest["source_generation_manifest_sha256"]),
        )
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
    details_raw = _canonical_json(document.model_dump(mode="json"))
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
        "details": document.model_dump(mode="json"),
    }


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
        "missed_penalty": "missed_penalty",
        "yellow_card": "yellow_card",
        "red_card": "red_card",
        "substitution_in": "substitution_in",
        "substitution_out": "substitution_out",
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
            is_own_goal=None,
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
