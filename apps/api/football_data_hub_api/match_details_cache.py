"""Content-addressed reuse of fully verified, immutable match publications.

The cache is disposable. Every hit rehashes the exact package, candidate,
inventory and MATCH-00 source files and checks the current fixture. A changed
or missing source falls back to the ordinary strict publication loader.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from football_data_hub_api.match_details_dataset import (
    CAMPAIGN_PACKAGE_SCHEMA,
    INDEX_SCHEMA,
    MatchDetailsLoadError,
    _published_match,
    _validate_detail_against_active_fixture,
    load_published_match_details,
)
from football_data_hub_api.match_results_dataset import MatchResultsBundle
from football_data_hub_api.schemas import MatchPublishedDetailsResponse

CACHE_SCHEMA = "football_data_hub.verified_match_details_cache.v1"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _code_fingerprint(project_root: Path) -> str:
    paths = [
        project_root / "pyproject.toml",
        project_root / "src/football_data_hub/domain/matches/details.py",
        project_root / "apps/api/football_data_hub_api/schemas.py",
        project_root / "apps/api/football_data_hub_api/match_details_dataset.py",
        project_root / "apps/api/football_data_hub_api/match_details_cache.py",
        project_root / "apps/api/football_data_hub_api/match_results_dataset.py",
        *sorted((project_root / "src/football_data_hub/providers/bdfutbol/match_details").glob("*.py")),
        *sorted((project_root / "src/football_data_hub/providers/bdfutbol/classification").glob("*.py")),
    ]
    digest = hashlib.sha256()
    digest.update(sys.version.encode())
    for name in ("beautifulsoup4", "lxml", "pydantic"):
        digest.update(f"{name}={importlib.metadata.version(name)}".encode())
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise MatchDetailsLoadError("No se puede verificar el código del caché de partidos.")
        digest.update(path.relative_to(project_root).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _safe_data_path(data_root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(part in {".", ".."} for part in path.parts):
        raise MatchDetailsLoadError("Ruta de fuente no segura en el caché de partidos.")
    target = data_root.joinpath(*path.parts)
    if not target.resolve().is_relative_to(data_root.resolve()):
        raise MatchDetailsLoadError("Una fuente sale del almacén de partidos.")
    return target


def _files(directory: Path) -> list[Path]:
    if directory.is_symlink() or not directory.is_dir():
        raise MatchDetailsLoadError("Falta una fuente íntegra para el caché de partidos.")
    files: list[Path] = []
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise MatchDetailsLoadError("Una fuente del caché contiene un symlink.")
        if path.is_file():
            files.append(path)
    return sorted(files)


def _file_digest(path: Path, known: dict[Path, str]) -> str:
    if path in known:
        return known[path]
    if path.is_symlink() or not path.is_file():
        raise MatchDetailsLoadError("Falta un archivo de procedencia de partido.")
    before = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise MatchDetailsLoadError("Una fuente cambió durante la comprobación del caché.")
    known[path] = digest
    return digest


def _publication_fingerprint(
    item: dict[str, Any], *, data_root: Path, published_root: Path,
    known: dict[Path, str],
) -> str | None:
    """Fingerprint only a campaign publication's own immutable dependencies."""
    publication_id = item.get("publication_id")
    internal_id = item.get("internal_id")
    if not isinstance(publication_id, str) or not _SAFE_ID.fullmatch(publication_id):
        raise MatchDetailsLoadError("publication_id no seguro en el caché.")
    if not isinstance(internal_id, str) or not _SAFE_ID.fullmatch(internal_id):
        raise MatchDetailsLoadError("internal_id no seguro en el caché.")
    if item.get("package_path") != f"packages/{publication_id}":
        raise MatchDetailsLoadError("Ruta de paquete incompatible en el caché.")
    package = published_root / "packages" / publication_id
    manifest_path = package / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise MatchDetailsLoadError("Manifiesto de paquete inseguro para el caché.")
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get("schema_version") != CAMPAIGN_PACKAGE_SCHEMA:
        return None  # Legacy packages keep their ordinary strict read path.
    campaign_id = manifest.get("campaign_id")
    inventory_id = manifest.get("inventory_id")
    generation_id = manifest.get("source_generation_id")
    if any(not isinstance(value, str) or not _SAFE_ID.fullmatch(value) for value in (campaign_id, inventory_id, generation_id)):
        raise MatchDetailsLoadError("Identidad de fuente inválida para el caché.")
    campaign = data_root / "matches" / "details" / "campaigns" / campaign_id
    candidate = campaign / "candidates" / internal_id
    inventory = data_root / "matches" / "details" / "inventories" / inventory_id
    generation = data_root / "matches" / "generations" / generation_id
    if campaign.is_symlink() or generation.is_symlink() or not campaign.is_dir():
        raise MatchDetailsLoadError("La fuente de campaña no es regular.")
    source_manifest = json.loads((generation / "manifest.json").read_bytes())
    paths = [
        *_files(package),
        *(path for path in campaign.iterdir() if path.is_file()),
        *_files(candidate), *_files(inventory), *_files(generation),
    ]
    for capture in source_manifest.get("source_captures", []):
        for file_spec in capture.get("files", {}).values():
            paths.append(_safe_data_path(data_root, file_spec["path"]))
    digest = hashlib.sha256(_canonical(item))
    for path in sorted(set(paths)):
        digest.update(str(path.relative_to(data_root)).encode())
        digest.update(_file_digest(path, known).encode())
    return digest.hexdigest()


def load_cached_published_match_details(
    published_root: Path, *, store_root: Path, generation_root: Path,
    data_root: Path, match_bundle: MatchResultsBundle, player_ids: set[int],
    cache_root: Path, project_root: Path,
) -> dict[str, MatchPublishedDetailsResponse]:
    """Reuse unchanged verified documents; strictly reload only cache misses."""
    cache_path = cache_root / "published-match-details.json"
    try:
        if cache_root.is_symlink():
            raise MatchDetailsLoadError("La ubicación del caché de partidos es un symlink.")
        code_fingerprint = _code_fingerprint(project_root)
        index_path = published_root / "index.json"
        index = json.loads(index_path.read_bytes())
        if index.get("schema_version") != INDEX_SCHEMA or not isinstance(index.get("publications"), list):
            raise MatchDetailsLoadError("Índice de publicaciones incompatible.")
        player_fingerprint = hashlib.sha256(_canonical(sorted(player_ids))).hexdigest()
        cached = json.loads(cache_path.read_bytes()) if cache_path.is_file() and not cache_path.is_symlink() else {}
        if (
            cached.get("schema_version") != CACHE_SCHEMA
            or cached.get("code_fingerprint") != code_fingerprint
            or cached.get("player_fingerprint") != player_fingerprint
            or not isinstance(cached.get("entries"), dict)
        ):
            cached = {"entries": {}}
        # The existing loader checks index identity, duplicates and active MATCH-00.
        load_published_match_details(
            published_root, store_root=store_root, generation_root=generation_root,
            data_root=data_root, match_bundle=match_bundle,
            player_ids=player_ids, internal_ids=set(),
        )
        known: dict[Path, str] = {}
        hits: dict[str, MatchPublishedDetailsResponse] = {}
        fingerprints: dict[str, str | None] = {}
        for item in index["publications"]:
            internal_id = item["internal_id"]
            fingerprint = _publication_fingerprint(
                item, data_root=data_root, published_root=published_root, known=known,
            )
            fingerprints[internal_id] = fingerprint
            entry = cached["entries"].get(internal_id)
            if fingerprint is None or not isinstance(entry, dict) or entry.get("fingerprint") != fingerprint:
                continue
            document_payload = entry.get("document")
            if hashlib.sha256(_canonical(document_payload)).hexdigest() != entry.get("document_sha256"):
                continue
            try:
                document = MatchPublishedDetailsResponse.model_validate(document_payload)
                _validate_detail_against_active_fixture(document, _published_match(match_bundle, internal_id))
            except (ValueError, TypeError, KeyError, MatchDetailsLoadError):
                continue
            hits[internal_id] = document
        missing = set(fingerprints) - set(hits)
        verified = load_published_match_details(
            published_root, store_root=store_root, generation_root=generation_root,
            data_root=data_root, match_bundle=match_bundle,
            player_ids=player_ids, internal_ids=missing,
        ) if missing else {}
        result = hits | verified
        if set(result) != set(fingerprints):
            raise MatchDetailsLoadError("El caché no cubre las publicaciones del índice.")
        entries = {}
        for internal_id, document in result.items():
            if fingerprints[internal_id] is None:
                continue
            payload = document.model_dump(mode="json")
            entries[internal_id] = {
                "fingerprint": fingerprints[internal_id],
                "document": payload,
                "document_sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
            }
        try:
            cache_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            payload = _canonical({
                "schema_version": CACHE_SCHEMA,
                "code_fingerprint": code_fingerprint,
                "player_fingerprint": player_fingerprint,
                "entries": entries,
            })
            with tempfile.NamedTemporaryFile(dir=cache_root, prefix=".match-details-", delete=False) as temp:
                temp.write(payload)
                temp.flush()
                os.fsync(temp.fileno())
                temporary = Path(temp.name)
            os.replace(temporary, cache_path)
        except OSError:
            # A read-only deployment simply performs the same strict reads next time.
            pass
        return result
    except (OSError, ValueError, TypeError, KeyError, MatchDetailsLoadError):
        return load_published_match_details(
            published_root, store_root=store_root, generation_root=generation_root,
            data_root=data_root, match_bundle=match_bundle, player_ids=player_ids,
        )
