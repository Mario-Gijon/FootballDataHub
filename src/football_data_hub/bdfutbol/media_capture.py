from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
from pathlib import Path
import time
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


_ALLOWED_HOSTS = {"bdfutbol.com", "www.bdfutbol.com"}
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)


@dataclass(frozen=True, slots=True)
class FetchResult:
    requested_url: str
    final_url: str
    status: int
    mime_type: str | None
    data: bytes


@dataclass(frozen=True, slots=True)
class DownloadFailure:
    source_url: str
    entity_type: str | None
    entity_id: int | None
    role: str | None
    error: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _allowed_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = parsed.netloc.casefold().split(":", 1)[0]
    return (
        parsed.scheme in {"http", "https"}
        and host in _ALLOWED_HOSTS
    )


def _sniff_extension(data: bytes, mime_type: str | None) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"

    stripped = data.lstrip()
    if stripped.startswith(b"<svg") or (
        stripped.startswith(b"<?xml")
        and b"<svg" in stripped[:1024]
    ):
        return ".svg"

    if mime_type:
        clean = mime_type.split(";", 1)[0].strip().casefold()
        known = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/svg+xml": ".svg",
        }
        if clean in known:
            return known[clean]

        guessed = mimetypes.guess_extension(clean)
        if guessed in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
            return ".jpg" if guessed == ".jpeg" else guessed

    return None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object_path(object_root: Path, sha256: str, extension: str) -> Path:
    return object_root / "sha256" / sha256[:2] / f"{sha256}{extension}"


def _write_object(
    *,
    object_root: Path,
    sha256: str,
    extension: str,
    data: bytes,
) -> tuple[Path, bool]:
    target = _object_path(object_root, sha256, extension)
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        return target, False

    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_bytes(data)
    temp.replace(target)
    return target, True


def fetch_image_with_browser_page(
    page: Any,
    url: str,
    *,
    referer: str | None = None,
    timeout_seconds: float = 20.0,
    max_bytes: int = 20 * 1024 * 1024,
) -> FetchResult:
    """Fetch media through an already-valid browser session.

    This intentionally uses ordinary browser navigation in the same persistent
    BDFutbol context used by the HTML acquisition pipeline. It does not solve,
    bypass or automate any challenge. If the existing session is not valid,
    the caller must stop and report the blocked state.
    """

    if not _allowed_url(url):
        raise ValueError(f"Host de media no permitido: {url}")

    headers: dict[str, str] = {}
    if referer:
        headers["Referer"] = referer

    page.set_extra_http_headers(headers)

    response = page.goto(
        url,
        wait_until="commit",
        timeout=max(1, int(timeout_seconds * 1000)),
    )
    if response is None:
        raise RuntimeError("Navegación sin respuesta HTTP")

    status = int(response.status)
    final_url = str(response.url or page.url)

    response_headers = response.headers
    mime_type = response_headers.get("content-type")
    length = response_headers.get("content-length")
    if length:
        try:
            declared = int(length)
        except (TypeError, ValueError):
            declared = None
        if declared is not None and declared > max_bytes:
            raise ValueError(
                f"Imagen supera max_bytes ({declared} > {max_bytes})"
            )

    data = response.body()
    if len(data) > max_bytes:
        raise ValueError(
            f"Imagen supera max_bytes ({len(data)} > {max_bytes})"
        )

    return FetchResult(
        requested_url=url,
        final_url=final_url,
        status=status,
        mime_type=mime_type,
        data=data,
    )


def fetch_image(
    url: str,
    *,
    referer: str | None = None,
    timeout_seconds: float = 20.0,
    max_bytes: int = 20 * 1024 * 1024,
    user_agent: str = _DEFAULT_USER_AGENT,
) -> FetchResult:
    if not _allowed_url(url):
        raise ValueError(f"Host de media no permitido: {url}")

    headers = {
        "User-Agent": user_agent,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer

    request = Request(url, headers=headers)

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status = int(getattr(response, "status", 200))
            final_url = str(response.geturl())
            mime_type = response.headers.get("Content-Type")

            length = response.headers.get("Content-Length")
            if length:
                try:
                    if int(length) > max_bytes:
                        raise ValueError(
                            f"Imagen supera max_bytes ({length} > {max_bytes})"
                        )
                except ValueError as exc:
                    if "supera max_bytes" in str(exc):
                        raise

            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError(
                    f"Imagen supera max_bytes ({len(data)} > {max_bytes})"
                )

            return FetchResult(
                requested_url=url,
                final_url=final_url,
                status=status,
                mime_type=mime_type,
                data=data,
            )
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"URL error: {exc.reason}") from exc


def select_candidates(
    audit: dict[str, Any],
    *,
    include_review: bool = False,
) -> list[dict[str, Any]]:
    allowed = {"accept"}
    if include_review:
        allowed.add("review")

    candidates: list[dict[str, Any]] = []
    for item in audit.get("media") or []:
        if not isinstance(item, dict):
            continue
        if item.get("decision") not in allowed:
            continue

        url = item.get("source_url")
        if not isinstance(url, str) or not _allowed_url(url):
            continue

        candidates.append(item)

    return candidates


def _best_referer(item: dict[str, Any]) -> str | None:
    occurrences = item.get("occurrences") or []
    for occurrence in occurrences:
        if not isinstance(occurrence, dict):
            continue
        source_page = occurrence.get("source_page")
        if isinstance(source_page, str) and source_page:
            return source_page
    return None


def _relative(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def capture_candidates(
    *,
    audit: dict[str, Any],
    project_root: Path,
    source_audit: Path,
    object_root: Path,
    include_review: bool = False,
    timeout_seconds: float = 20.0,
    max_bytes: int = 20 * 1024 * 1024,
    delay_seconds: float = 0.05,
    fetcher: Callable[..., FetchResult] = fetch_image,
) -> dict[str, Any]:
    candidates = select_candidates(
        audit,
        include_review=include_review,
    )

    started_at = _utc_now()
    failures: list[DownloadFailure] = []

    # Binary-level dedupe. Multiple distinct URLs that return the same bytes
    # collapse into one object, while every source URL and entity association
    # is preserved.
    assets_by_sha: dict[str, dict[str, Any]] = {}
    successful_urls = 0
    new_objects = 0
    reused_objects = 0

    for index, item in enumerate(candidates):
        url = str(item["source_url"])
        referer = _best_referer(item)

        try:
            result = fetcher(
                url,
                referer=referer,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
            )

            if result.status < 200 or result.status >= 300:
                raise RuntimeError(f"HTTP {result.status}")

            extension = _sniff_extension(
                result.data,
                result.mime_type,
            )
            if extension is None:
                raise RuntimeError(
                    f"Respuesta no reconocida como imagen "
                    f"(mime={result.mime_type!r})"
                )

            digest = _sha256(result.data)
            object_path, created = _write_object(
                object_root=object_root,
                sha256=digest,
                extension=extension,
                data=result.data,
            )

            if created:
                new_objects += 1
            else:
                reused_objects += 1

            successful_urls += 1

            association = {
                "entity_type": item.get("entity_type"),
                "entity_id": item.get("entity_id"),
                "role": item.get("role"),
                "roles_observed": item.get("roles_observed") or [],
                "decision": item.get("decision"),
            }

            existing = assets_by_sha.get(digest)
            if existing is None:
                existing = {
                    "sha256": digest,
                    "mime_type": result.mime_type,
                    "extension": extension,
                    "bytes": len(result.data),
                    "object_path": _relative(
                        object_path,
                        project_root,
                    ),
                    "source_urls": [],
                    "final_urls": [],
                    "associations": [],
                    "occurrences": [],
                }
                assets_by_sha[digest] = existing

            source_urls = existing["source_urls"]
            assert isinstance(source_urls, list)
            if url not in source_urls:
                source_urls.append(url)

            final_urls = existing["final_urls"]
            assert isinstance(final_urls, list)
            if result.final_url not in final_urls:
                final_urls.append(result.final_url)

            associations = existing["associations"]
            assert isinstance(associations, list)
            if association not in associations:
                associations.append(association)

            occurrences = existing["occurrences"]
            assert isinstance(occurrences, list)
            for occurrence in item.get("occurrences") or []:
                if occurrence not in occurrences:
                    occurrences.append(occurrence)

        except Exception as exc:
            failures.append(
                DownloadFailure(
                    source_url=url,
                    entity_type=(
                        str(item.get("entity_type"))
                        if item.get("entity_type") is not None
                        else None
                    ),
                    entity_id=(
                        int(item["entity_id"])
                        if item.get("entity_id") is not None
                        else None
                    ),
                    role=(
                        str(item.get("role"))
                        if item.get("role") is not None
                        else None
                    ),
                    error=str(exc),
                )
            )

        if delay_seconds > 0 and index + 1 < len(candidates):
            time.sleep(delay_seconds)

    assets = sorted(
        assets_by_sha.values(),
        key=lambda item: str(item["sha256"]),
    )

    entity_index: dict[str, list[str]] = {}
    for asset in assets:
        sha = str(asset["sha256"])
        for association in asset["associations"]:
            if not isinstance(association, dict):
                continue
            entity_type = association.get("entity_type")
            entity_id = association.get("entity_id")
            if entity_type is None or entity_id is None:
                continue
            key = f"{entity_type}:{entity_id}"
            entity_index.setdefault(key, [])
            if sha not in entity_index[key]:
                entity_index[key].append(sha)

    return {
        "capture_version": 1,
        "started_at_utc": started_at,
        "finished_at_utc": _utc_now(),
        "source_audit": _relative(source_audit, project_root),
        "include_review": include_review,
        "candidates_selected": len(candidates),
        "urls_downloaded": successful_urls,
        "urls_failed": len(failures),
        "unique_binary_assets": len(assets),
        "new_objects_written": new_objects,
        "existing_objects_reused": reused_objects,
        "object_root": _relative(object_root, project_root),
        "assets": assets,
        "entity_index": {
            key: sorted(values)
            for key, values in sorted(entity_index.items())
        },
        "failures": [failure.to_dict() for failure in failures],
    }


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON raíz no es un objeto: {path}")
    return value
