"""Verificación offline de MATCH-00 e inventario determinista de fichas."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlsplit

from football_data_hub.providers.bdfutbol.classification.generation import (
    COMPETITION,
    SEASON,
    build_match_generation,
)

INVENTORY_SCHEMA = "football_data_hub.bdfutbol.match_detail_inventory.v1"


class MatchDetailInventoryError(ValueError):
    """La generación de origen no permite construir un plan de forma segura."""


@dataclass(frozen=True, slots=True)
class VerifiedGeneration:
    generation_id: str
    manifest_path: Path
    manifest_sha256: str
    matches_payload: dict[str, Any]
    validation_payload: dict[str, Any]
    manifest_payload: dict[str, Any]
    data_root: Path


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _load_json(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MatchDetailInventoryError(f"No se puede leer JSON válido: {path}") from exc
    if not isinstance(value, dict):
        raise MatchDetailInventoryError(f"Se esperaba un objeto JSON: {path}")
    return value, raw


def _data_file(data_root: Path, relative: str, *, label: str) -> Path:
    rel = PurePosixPath(relative)
    if (
        rel.is_absolute()
        or "\\" in relative
        or not rel.parts
        or any(part in {"", ".", ".."} for part in rel.parts)
    ):
        raise MatchDetailInventoryError(f"Ruta de procedencia no segura en {label}: {relative!r}")
    root = data_root.resolve(strict=True)
    current = root
    for part in rel.parts:
        current = current / part
        try:
            if current.is_symlink():
                raise MatchDetailInventoryError(
                    f"Ruta de procedencia contiene un symlink en {label}: {current}"
                )
            current.lstat()
        except OSError as exc:
            raise MatchDetailInventoryError(
                f"Falta el archivo de procedencia en {label}: {current}"
            ) from exc
    resolved = current.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise MatchDetailInventoryError(
            f"La ruta de procedencia escapa de data_root en {label}: {relative}"
        ) from exc
    if not resolved.is_file():
        raise MatchDetailInventoryError(f"Procedencia no es un archivo regular: {resolved}")
    return resolved


def _verify_digest(path: Path, item: dict[str, Any], *, label: str) -> bytes:
    raw = path.read_bytes()
    expected_hash = item.get("sha256")
    expected_size = item.get("bytes")
    if not isinstance(expected_hash, str) or _sha256(raw) != expected_hash:
        raise MatchDetailInventoryError(f"SHA-256 no coincide para {label}: {path}")
    if expected_size is not None and (not isinstance(expected_size, int) or len(raw) != expected_size):
        raise MatchDetailInventoryError(f"Tamaño no coincide para {label}: {path}")
    return raw


def _verify_source_capture(
    source: dict[str, Any], *, data_root: Path, group: str
) -> tuple[Path, Path]:
    if source.get("group") != group or source.get("http_status") != 200:
        raise MatchDetailInventoryError(f"Procedencia inválida para Grupo {group}")
    files = source.get("files")
    if not isinstance(files, dict):
        raise MatchDetailInventoryError(f"Faltan los archivos de procedencia para Grupo {group}")
    resolved: dict[str, Path] = {}
    for key in ("capture_metadata", "source_html", "normalized_matches"):
        item = files.get(key)
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise MatchDetailInventoryError(f"Referencia {key} ausente en Grupo {group}")
        path = _data_file(data_root, item["path"], label=f"{group}.{key}")
        _verify_digest(path, item, label=f"{group}.{key}")
        resolved[key] = path

    capture, _ = _load_json(resolved["capture_metadata"])
    if (
        capture.get("capture_id") != source.get("capture_id")
        or capture.get("source") != "BDFutbol"
        or capture.get("competition") != COMPETITION
        or capture.get("season") != SEASON
        or capture.get("group") != group
        or capture.get("url") != source.get("requested_url")
        or capture.get("final_url") != source.get("final_url")
        or capture.get("access", {}).get("http_status") != 200
        or capture.get("access", {}).get("status") != "VALID"
    ):
        raise MatchDetailInventoryError(f"capture.json no acredita el Grupo {group}")
    if capture.get("captured_at_utc") != source.get("captured_at_utc"):
        raise MatchDetailInventoryError(f"Fecha de captura discordante en Grupo {group}")
    source_hash = _sha256(resolved["source_html"].read_bytes())
    if source_hash != source.get("source_snapshot_sha256"):
        raise MatchDetailInventoryError(f"Hash de HTML fuente discordante en Grupo {group}")
    normalized, _ = _load_json(resolved["normalized_matches"])
    if (
        normalized.get("metadata", {}).get("source_capture_id") != source.get("capture_id")
        or normalized.get("metadata", {}).get("source_snapshot_sha256") != source_hash
        or normalized.get("metadata", {}).get("competition") != COMPETITION
        or normalized.get("metadata", {}).get("season") != SEASON
        or normalized.get("metadata", {}).get("group") != group
    ):
        raise MatchDetailInventoryError(f"matches.json de origen no coincide en Grupo {group}")
    return resolved["capture_metadata"].parent.parent, resolved["normalized_matches"]


def load_verified_match_generation(
    generation_root: Path, *, data_root: Path
) -> VerifiedGeneration:
    """Valida hashes/contratos y reproduce la generación con el parser existente.

    La reproducción se escribe en un temporal local; nunca modifica capturas ni
    la generación que se está verificando.
    """

    requested_data_root = data_root.expanduser().absolute()
    requested_generation_root = generation_root.expanduser().absolute()
    try:
        lexical_relative = requested_generation_root.relative_to(requested_data_root)
    except ValueError as exc:
        raise MatchDetailInventoryError(
            "La generación de origen debe permanecer dentro de data_root"
        ) from exc
    data_root = requested_data_root.resolve(strict=True)
    lexical_path = requested_data_root
    for part in lexical_relative.parts:
        lexical_path = lexical_path / part
        if lexical_path.is_symlink():
            raise MatchDetailInventoryError("La ruta de generación contiene un symlink")
    generation_root = requested_generation_root.resolve(strict=True)
    try:
        relative_generation = generation_root.relative_to(data_root)
    except ValueError as exc:
        raise MatchDetailInventoryError(
            "La generación de origen debe permanecer dentro de data_root"
        ) from exc
    current = data_root
    for part in relative_generation.parts:
        current = current / part
        if current.is_symlink():
            raise MatchDetailInventoryError("La ruta de generación contiene un symlink")

    manifest_path = generation_root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise MatchDetailInventoryError("manifest.json ausente o no es archivo regular")
    manifest, manifest_raw = _load_json(manifest_path)
    generation_id = manifest.get("generation_id")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("source") != "BDFutbol"
        or manifest.get("competition") != COMPETITION
        or manifest.get("season") != SEASON
        or generation_id != generation_root.name
    ):
        raise MatchDetailInventoryError("El manifiesto no identifica la generación MATCH-00 esperada")

    artifact_hashes = manifest.get("artifacts")
    if not isinstance(artifact_hashes, dict):
        raise MatchDetailInventoryError("El manifiesto no contiene hashes de artefactos")
    artifacts: dict[str, bytes] = {}
    for filename in ("matches.json", "validation.json"):
        spec = artifact_hashes.get(filename)
        if not isinstance(spec, dict):
            raise MatchDetailInventoryError(f"Falta el hash declarado para {filename}")
        path = generation_root / filename
        if path.is_symlink() or not path.is_file():
            raise MatchDetailInventoryError(f"Artefacto ausente o no regular: {path}")
        artifacts[filename] = _verify_digest(path, spec, label=filename)

    matches_payload, _ = _load_json(generation_root / "matches.json")
    validation_payload, _ = _load_json(generation_root / "validation.json")
    if (
        matches_payload.get("schema_version") != 1
        or matches_payload.get("metadata", {}).get("generation_id") != generation_id
        or matches_payload.get("metadata", {}).get("source") != "BDFutbol"
        or matches_payload.get("metadata", {}).get("competition") != COMPETITION
        or matches_payload.get("metadata", {}).get("season") != SEASON
        or validation_payload.get("valid") is not True
        or validation_payload.get("totals") != manifest.get("counts")
    ):
        raise MatchDetailInventoryError("Los contratos de la generación y validación no coinciden")

    source_captures = manifest.get("source_captures")
    if not isinstance(source_captures, list) or len(source_captures) != 2:
        raise MatchDetailInventoryError("El manifiesto debe referenciar las dos capturas de grupo")
    captures_by_group = {item.get("group"): item for item in source_captures if isinstance(item, dict)}
    if set(captures_by_group) != {"I", "II"}:
        raise MatchDetailInventoryError("Las capturas de origen no cubren Grupo I y Grupo II")

    capture_roots: dict[str, Path] = {}
    normalized_paths: dict[str, Path] = {}
    for group in ("I", "II"):
        capture_root, normalized_path = _verify_source_capture(
            captures_by_group[group], data_root=data_root, group=group
        )
        capture_roots[group] = capture_root
        normalized_paths[group] = normalized_path

    # Vuelve a ejecutar las validaciones fuente existentes, sin navegador ni red.
    with tempfile.TemporaryDirectory(prefix="fdh-match-detail-verify-") as temporary:
        rebuilt_root = Path(temporary) / "matches"
        rebuilt_dir = build_match_generation(
            group_i_root=capture_roots["I"],
            group_i_matches=normalized_paths["I"],
            group_ii_root=capture_roots["II"],
            group_ii_matches=normalized_paths["II"],
            output_root=rebuilt_root,
            data_root=data_root,
        )
        if rebuilt_dir.name != generation_id:
            raise MatchDetailInventoryError("La identidad determinista de la generación cambió")
        for filename, raw in artifacts.items():
            if (rebuilt_dir / filename).read_bytes() != raw:
                raise MatchDetailInventoryError(
                    f"La regeneración offline no reproduce {filename} byte por byte"
                )
        if (rebuilt_dir / "manifest.json").read_bytes() != manifest_raw:
            raise MatchDetailInventoryError(
                "La regeneración offline no reproduce manifest.json byte por byte"
            )

    return VerifiedGeneration(
        generation_id=generation_id,
        manifest_path=manifest_path,
        manifest_sha256=_sha256(manifest_raw),
        matches_payload=matches_payload,
        validation_payload=validation_payload,
        manifest_payload=manifest,
        data_root=data_root,
    )


def _validate_match_url(url: Any, source_match_id: str) -> str:
    if not isinstance(url, str):
        raise MatchDetailInventoryError(f"Falta URL individual para partido {source_match_id}")
    parsed = urlsplit(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.bdfutbol.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path != "/es/p/p.php"
        or set(query) != {"id"}
        or query["id"] != [source_match_id]
        or parsed.fragment
    ):
        raise MatchDetailInventoryError(
            f"URL individual no válida para partido {source_match_id}: {url!r}"
        )
    return url


def build_match_detail_inventory(verified: VerifiedGeneration) -> dict[str, Any]:
    """Selecciona partidos disputados con URL explícita, en orden estable."""

    payload = verified.matches_payload
    groups = payload.get("groups")
    if not isinstance(groups, dict) or set(groups) != {"I", "II"}:
        raise MatchDetailInventoryError("matches.json no contiene exactamente Grupo I y II")
    source_by_group = {
        item["group"]: item for item in verified.manifest_payload["source_captures"]
    }
    records: list[dict[str, Any]] = []
    seen_internal: set[str] = set()
    seen_source: set[str] = set()
    seen_urls: set[str] = set()
    omitted_played_without_url = 0

    for group in ("I", "II"):
        group_payload = groups[group]
        if group_payload.get("group") != group or len(group_payload.get("teams", [])) != 20:
            raise MatchDetailInventoryError(f"Catálogo de equipos inválido en Grupo {group}")
        team_ids = {team.get("team_id") for team in group_payload["teams"]}
        if len(team_ids) != 20 or None in team_ids:
            raise MatchDetailInventoryError(f"IDs de equipo duplicados o ausentes en Grupo {group}")
        source_capture = source_by_group[group]
        source_files = source_capture["files"]
        for match in group_payload.get("matches", []):
            if match.get("status") != "played":
                continue
            source_match_id = str(match.get("source_match_id") or "")
            url = match.get("source_match_url")
            if not url:
                omitted_played_without_url += 1
                continue
            if not source_match_id.isdigit():
                raise MatchDetailInventoryError("ID BDFutbol no numérico en un partido disputado")
            internal_id = match.get("internal_id")
            expected_internal = (
                f"pf-{SEASON}-group-{group.lower()}-bdfutbol-{source_match_id}"
            )
            if internal_id != expected_internal:
                raise MatchDetailInventoryError(
                    f"ID interno no namespaced o discordante: {internal_id!r}"
                )
            if internal_id in seen_internal or source_match_id in seen_source:
                raise MatchDetailInventoryError(f"ID de partido duplicado: {internal_id}")
            url = _validate_match_url(url, source_match_id)
            if url in seen_urls:
                raise MatchDetailInventoryError(f"URL individual duplicada: {url}")
            home_id = match.get("home_team_id")
            away_id = match.get("away_team_id")
            if home_id not in team_ids or away_id not in team_ids or home_id == away_id:
                raise MatchDetailInventoryError(f"Equipos no válidos para {internal_id}")
            home_goals = match.get("home_goals")
            away_goals = match.get("away_goals")
            if (
                not isinstance(home_goals, int)
                or isinstance(home_goals, bool)
                or not isinstance(away_goals, int)
                or isinstance(away_goals, bool)
                or home_goals < 0
                or away_goals < 0
            ):
                raise MatchDetailInventoryError(f"Marcador disputado incompleto para {internal_id}")
            matchday = match.get("matchday")
            if not isinstance(matchday, int) or not 1 <= matchday <= 38:
                raise MatchDetailInventoryError(f"Jornada inválida para {internal_id}")
            record = {
                "internal_id": internal_id,
                "source_match_id": source_match_id,
                "season": SEASON,
                "competition": COMPETITION,
                "group": group,
                "matchday": matchday,
                "home_team_id": home_id,
                "away_team_id": away_id,
                "source_match_date": match.get("source_match_date"),
                "matchday_date": match.get("matchday_date"),
                "reference_result": {
                    "home_goals": home_goals,
                    "away_goals": away_goals,
                },
                "source_match_url": url,
                "source_generation_id": verified.generation_id,
                "source_generation_manifest_sha256": verified.manifest_sha256,
                "source_capture_id": source_capture["capture_id"],
                "source_captured_at_utc": source_capture["captured_at_utc"],
                "source_snapshot_sha256": source_capture["source_snapshot_sha256"],
                "source_matches_sha256": source_files["normalized_matches"]["sha256"],
                "acquisition_status": "pending",
                "validation_status": "not_acquired",
            }
            records.append(record)
            seen_internal.add(internal_id)
            seen_source.add(source_match_id)
            seen_urls.add(url)

    records.sort(
        key=lambda item: (
            0 if item["group"] == "I" else 1,
            item["matchday"],
            int(item["source_match_id"]),
        )
    )
    if not records:
        raise MatchDetailInventoryError("No hay partidos disputados con URL explícita")
    base = {
        "schema_version": INVENTORY_SCHEMA,
        "source": "BDFutbol",
        "competition": COMPETITION,
        "season": SEASON,
        "source_generation": {
            "generation_id": verified.generation_id,
            "manifest_path": verified.manifest_path.relative_to(verified.data_root).as_posix(),
            "manifest_sha256": verified.manifest_sha256,
        },
        "selection_policy": "status=played and source_match_url is explicit and verified",
        "counts": {
            "matches": len(records),
            "groups": {"I": sum(item["group"] == "I" for item in records),
                       "II": sum(item["group"] == "II" for item in records)},
            "unique_internal_ids": len(seen_internal),
            "unique_source_ids": len(seen_source),
            "unique_urls": len(seen_urls),
            "played_without_explicit_url": omitted_played_without_url,
        },
        "matches": records,
    }
    inventory_id = "match-detail-inventory-" + _sha256(_canonical_json(base))[:16]
    return {"inventory_id": inventory_id, **base}


def write_inventory_immutable(path: Path, inventory: dict[str, Any]) -> Path:
    """Escribe JSON una sola vez; una repetición idéntica es idempotente."""

    path = path.expanduser().absolute()
    if any(component.is_symlink() for component in (path.parent, *path.parent.parents)):
        raise MatchDetailInventoryError("La ruta de salida del inventario contiene symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _canonical_json(inventory)
    if path.is_symlink():
        raise FileExistsError(f"No se sobrescribe un symlink de inventario: {path}")
    if path.exists():
        if path.is_file() and path.read_bytes() == content:
            return path
        raise FileExistsError(f"No se sobrescribe un inventario existente: {path}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_file() and path.read_bytes() == content:
                return path
            raise FileExistsError(f"No se sobrescribe un inventario existente: {path}")
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return path
