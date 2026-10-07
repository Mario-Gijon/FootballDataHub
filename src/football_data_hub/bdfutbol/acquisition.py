from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .browser import BrowserRuntimeError, start_browser, stop_browser
from .validation import PageAssessment, assess_page


class AcquisitionStatus(str, Enum):
    VALID = "VALID"
    BLOCKED = "BLOCKED"
    INVALID_CONTENT = "INVALID_CONTENT"
    NAVIGATION_ERROR = "NAVIGATION_ERROR"
    BROWSER_ERROR = "BROWSER_ERROR"


class LatestValidSnapshotError(ValueError):
    """Raised when a resource has no usable latest_valid snapshot pointer."""


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    number: int
    phase: str
    status: AcquisitionStatus
    directory: str
    http_status_diagnostic: int | None = None
    navigation_error: str | None = None
    assessment: dict[str, Any] | None = None
    browser_error: str | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    status: AcquisitionStatus
    run_directory: Path
    valid_snapshot_directory: Path | None
    attempts: tuple[AttemptRecord, ...]

    @property
    def ok(self) -> bool:
        return self.status is AcquisitionStatus.VALID


def resolve_latest_valid_snapshot(project_root: Path, snapshot_name: str) -> Path:
    """Return the page.html referenced by a resource's latest_valid.json.

    Both the absolute paths written by earlier versions and project-relative
    paths are accepted. Every resolved path must remain inside the resource's
    raw-data directory so a malformed pointer cannot escape the repository.
    """

    safe_name = BDFutbolAcquirer._safe_name(snapshot_name)
    if safe_name != snapshot_name:
        raise LatestValidSnapshotError(
            f"Nombre de snapshot no válido: {snapshot_name!r}."
        )

    root = Path(project_root).expanduser().resolve()
    resource_dir = root / "data" / "raw" / "bdfutbol" / safe_name
    pointer_path = resource_dir / "latest_valid.json"
    if not pointer_path.is_file():
        raise LatestValidSnapshotError(
            f"No existe latest_valid.json para el snapshot {safe_name!r}: "
            f"{pointer_path}"
        )

    try:
        payload = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LatestValidSnapshotError(
            f"latest_valid.json no se puede leer como JSON válido: {pointer_path}"
        ) from exc

    if not isinstance(payload, dict) or payload.get("status") != "VALID":
        raise LatestValidSnapshotError(
            f"latest_valid.json no apunta a un snapshot VALID: {pointer_path}"
        )

    snapshot_value = payload.get("snapshot_directory")
    page_value = payload.get("page_html")
    if not isinstance(snapshot_value, str) or not snapshot_value:
        raise LatestValidSnapshotError(
            f"latest_valid.json no contiene snapshot_directory: {pointer_path}"
        )
    if not isinstance(page_value, str) or not page_value:
        raise LatestValidSnapshotError(
            f"latest_valid.json no contiene page_html: {pointer_path}"
        )

    snapshot_dir = _resolve_latest_valid_path(
        snapshot_value,
        root=root,
        resource_dir=resource_dir,
        snapshot_name=safe_name,
    )
    page_path = _resolve_latest_valid_path(
        page_value,
        root=root,
        resource_dir=resource_dir,
        snapshot_name=safe_name,
    )

    if not snapshot_dir.is_dir():
        raise LatestValidSnapshotError(
            f"El snapshot indicado ya no existe: {snapshot_dir}"
        )
    if page_path != (snapshot_dir / "page.html").resolve():
        raise LatestValidSnapshotError(
            "page_html no corresponde al page.html del snapshot indicado: "
            f"{page_path}"
        )
    if not page_path.is_file():
        raise LatestValidSnapshotError(
            f"No existe el HTML del snapshot válido: {page_path}"
        )
    return page_path


def _resolve_latest_valid_path(
    value: str,
    *,
    root: Path,
    resource_dir: Path,
    snapshot_name: str,
) -> Path:
    recorded = Path(value).expanduser()
    if not recorded.is_absolute():
        candidate = root / recorded
        if not candidate.exists():
            candidate = resource_dir / recorded
    else:
        candidate = recorded

    resolved = candidate.resolve()
    resource_resolved = resource_dir.resolve()
    if resolved.is_relative_to(resource_resolved):
        return resolved

    # Older latest_valid files stored an absolute path. Recover its resource-
    # relative suffix if the repository has since moved to another location.
    parts = recorded.parts
    anchor = ("data", "raw", "bdfutbol", snapshot_name)
    for index in range(len(parts) - len(anchor) + 1):
        if tuple(part.casefold() for part in parts[index : index + len(anchor)]) == anchor:
            suffix = parts[index + len(anchor) :]
            relocated = (resource_dir / Path(*suffix)).resolve()
            if relocated.is_relative_to(resource_resolved):
                return relocated

    raise LatestValidSnapshotError(
        f"La ruta guardada en latest_valid.json queda fuera del recurso "
        f"{snapshot_name!r}: {value!r}"
    )


class BDFutbolAcquirer:
    """Adquisición automática con navegador real y perfil persistente.

    No intenta resolver ni interactuar con desafíos de Cloudflare. Si aparece
    una verificación, puede abrir una fase de warm-up con el mismo perfil,
    esperar a que la comprobación normal del navegador termine, cerrar Brave y
    reintentar una adquisición limpia.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        profile: Path | None = None,
        browser: str = "auto",
        timeout_ms: int = 45_000,
        settle_ms: int = 3_000,
        max_attempts: int = 3,
        warmup_seconds: float = 10.0,
        retry_delay_seconds: float = 1.5,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts debe ser >= 1")
        if warmup_seconds < 0:
            raise ValueError("warmup_seconds debe ser >= 0")

        self.project_root = project_root.resolve()
        self.profile = (
            profile.expanduser().resolve()
            if profile is not None
            else Path.home() / ".football-data-hub-browser"
        )
        self.browser = browser
        self.timeout_ms = timeout_ms
        self.settle_ms = settle_ms
        self.max_attempts = max_attempts
        self.warmup_seconds = warmup_seconds
        self.retry_delay_seconds = retry_delay_seconds

    def acquire(
        self,
        *,
        url: str,
        name: str,
        expected_texts: Iterable[str] = (),
    ) -> AcquisitionResult:
        safe_name = self._safe_name(name)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        base_dir = self.project_root / "data" / "raw" / "bdfutbol" / safe_name
        run_dir = base_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        attempts: list[AttemptRecord] = []
        final_status = AcquisitionStatus.INVALID_CONTENT
        valid_snapshot: Path | None = None

        for attempt_number in range(1, self.max_attempts + 1):
            attempt_dir = run_dir / f"attempt_{attempt_number:02d}"
            record = self._capture_attempt(
                url=url,
                output_dir=attempt_dir,
                attempt_number=attempt_number,
                expected_texts=tuple(expected_texts),
            )
            attempts.append(record)
            final_status = record.status

            if record.status is AcquisitionStatus.VALID:
                valid_snapshot = attempt_dir
                self._write_latest_valid(
                    base_dir=base_dir,
                    run_dir=run_dir,
                    snapshot_dir=attempt_dir,
                    url=url,
                )
                break

            if attempt_number >= self.max_attempts:
                break

            if record.status is AcquisitionStatus.BLOCKED:
                warmup_dir = run_dir / f"warmup_{attempt_number:02d}"
                warmup = self._warm_profile(
                    url=url,
                    output_dir=warmup_dir,
                    attempt_number=attempt_number,
                    expected_texts=tuple(expected_texts),
                )
                attempts.append(warmup)
                if warmup.status is AcquisitionStatus.VALID:
                    final_status = AcquisitionStatus.VALID
                    valid_snapshot = warmup_dir
                    self._write_latest_valid(
                        base_dir=base_dir,
                        run_dir=run_dir,
                        snapshot_dir=warmup_dir,
                        url=url,
                    )
                    break

            if self.retry_delay_seconds:
                time.sleep(self.retry_delay_seconds)

        result = AcquisitionResult(
            status=final_status,
            run_directory=run_dir,
            valid_snapshot_directory=valid_snapshot,
            attempts=tuple(attempts),
        )
        self._write_run_summary(url=url, name=safe_name, result=result)
        return result

    def _capture_attempt(
        self,
        *,
        url: str,
        output_dir: Path,
        attempt_number: int,
        expected_texts: tuple[str, ...],
    ) -> AttemptRecord:
        output_dir.mkdir(parents=True, exist_ok=False)

        try:
            runtime = start_browser(
                profile=self.profile,
                preference=self.browser,
                start_url="about:blank",
            )
        except BrowserRuntimeError as exc:
            record = AttemptRecord(
                number=attempt_number,
                phase="capture",
                status=AcquisitionStatus.BROWSER_ERROR,
                directory=str(output_dir),
                browser_error=str(exc),
            )
            self._dump_json(output_dir / "metadata.json", self._record_dict(record))
            return record

        try:
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.connect_over_cdp(runtime.cdp_url)
                except PlaywrightError as exc:
                    record = AttemptRecord(
                        number=attempt_number,
                        phase="capture",
                        status=AcquisitionStatus.BROWSER_ERROR,
                        directory=str(output_dir),
                        browser_error=f"CDP connect: {type(exc).__name__}: {exc}",
                    )
                    self._dump_json(
                        output_dir / "metadata.json",
                        self._record_dict(record),
                    )
                    return record

                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_navigation_timeout(self.timeout_ms)

                response_status: int | None = None
                navigation_error: str | None = None
                try:
                    response = page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=self.timeout_ms,
                    )
                    if response is not None:
                        response_status = response.status
                except PlaywrightTimeoutError as exc:
                    navigation_error = f"{type(exc).__name__}: {exc}"

                page.wait_for_timeout(self.settle_ms)
                assessment = assess_page(page, expected_texts)
                self._save_page_artifacts(page, output_dir, assessment)

                if assessment.accessible:
                    status = AcquisitionStatus.VALID
                elif assessment.challenge_visible:
                    status = AcquisitionStatus.BLOCKED
                elif navigation_error:
                    status = AcquisitionStatus.NAVIGATION_ERROR
                else:
                    status = AcquisitionStatus.INVALID_CONTENT

                record = AttemptRecord(
                    number=attempt_number,
                    phase="capture",
                    status=status,
                    directory=str(output_dir),
                    http_status_diagnostic=response_status,
                    navigation_error=navigation_error,
                    assessment=assessment.as_dict(),
                )
                metadata = {
                    **self._record_dict(record),
                    "requested_url": url,
                    "final_url": page.url,
                    "browser_binary": runtime.browser_path,
                    "profile": str(runtime.profile),
                    "using_xvfb": runtime.using_xvfb,
                    "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                }
                self._dump_json(output_dir / "metadata.json", metadata)
                return record
        finally:
            stop_browser(runtime)

    def _warm_profile(
        self,
        *,
        url: str,
        output_dir: Path,
        attempt_number: int,
        expected_texts: tuple[str, ...],
    ) -> AttemptRecord:
        """Abre la URL como navegador normal, espera y cierra el perfil.

        No hace clic, no rellena challenges y no ejecuta page.goto(). El objetivo
        es reproducir automáticamente el warm-up que antes se hacía a mano.
        """

        output_dir.mkdir(parents=True, exist_ok=False)

        try:
            runtime = start_browser(
                profile=self.profile,
                preference=self.browser,
                start_url=url,
            )
        except BrowserRuntimeError as exc:
            record = AttemptRecord(
                number=attempt_number,
                phase="warmup",
                status=AcquisitionStatus.BROWSER_ERROR,
                directory=str(output_dir),
                browser_error=str(exc),
            )
            self._dump_json(output_dir / "metadata.json", self._record_dict(record))
            return record

        try:
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.connect_over_cdp(runtime.cdp_url)
                except PlaywrightError as exc:
                    record = AttemptRecord(
                        number=attempt_number,
                        phase="warmup",
                        status=AcquisitionStatus.BROWSER_ERROR,
                        directory=str(output_dir),
                        browser_error=f"CDP connect: {type(exc).__name__}: {exc}",
                    )
                    self._dump_json(
                        output_dir / "metadata.json",
                        self._record_dict(record),
                    )
                    return record

                context = browser.contexts[0]
                page = self._find_target_page(context.pages, url)
                if page is None:
                    deadline = time.monotonic() + min(self.warmup_seconds, 5.0)
                    while time.monotonic() < deadline and page is None:
                        time.sleep(0.25)
                        page = self._find_target_page(context.pages, url)

                if page is None:
                    record = AttemptRecord(
                        number=attempt_number,
                        phase="warmup",
                        status=AcquisitionStatus.INVALID_CONTENT,
                        directory=str(output_dir),
                        browser_error="Brave no abrió una pestaña para la URL objetivo.",
                    )
                    self._dump_json(
                        output_dir / "metadata.json",
                        self._record_dict(record),
                    )
                    return record

                deadline = time.monotonic() + self.warmup_seconds
                assessment: PageAssessment | None = None
                while True:
                    assessment = assess_page(page, expected_texts)
                    if assessment.accessible or time.monotonic() >= deadline:
                        break
                    time.sleep(1.0)

                if assessment.accessible:
                    # Damos un instante al navegador para persistir cookies/storage.
                    time.sleep(1.0)
                    status = AcquisitionStatus.VALID
                elif assessment.challenge_visible:
                    status = AcquisitionStatus.BLOCKED
                else:
                    status = AcquisitionStatus.INVALID_CONTENT

                self._save_page_artifacts(page, output_dir, assessment)
                record = AttemptRecord(
                    number=attempt_number,
                    phase="warmup",
                    status=status,
                    directory=str(output_dir),
                    assessment=assessment.as_dict(),
                )
                metadata = {
                    **self._record_dict(record),
                    "requested_url": url,
                    "final_url": page.url,
                    "warmup_seconds": self.warmup_seconds,
                    "browser_binary": runtime.browser_path,
                    "profile": str(runtime.profile),
                    "using_xvfb": runtime.using_xvfb,
                    "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                    "note": (
                        "Warm-up pasivo: no se hizo click ni se intentó resolver "
                        "el challenge; solo se esperó al navegador real."
                    ),
                }
                self._dump_json(output_dir / "metadata.json", metadata)
                return record
        finally:
            stop_browser(runtime)

    @staticmethod
    def _find_target_page(pages: list[Any], url: str) -> Any | None:
        target_host = re.sub(r"^https?://", "", url).split("/", 1)[0].casefold()
        for page in pages:
            try:
                if target_host in page.url.casefold():
                    return page
            except Exception:
                continue
        return pages[0] if pages else None

    @staticmethod
    def _safe_name(name: str) -> str:
        value = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip())
        value = value.strip("._-")
        if not value:
            raise ValueError("name no puede quedar vacío")
        return value

    @staticmethod
    def _dump_json(path: Path, value: object) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _extract_links(page: Any) -> list[dict[str, Any]]:
        try:
            return page.locator("a").evaluate_all(
                """nodes => nodes.map((a, index) => ({
                    index,
                    text: (a.innerText || a.textContent || '').trim(),
                    href: a.href || null,
                    href_raw: a.getAttribute('href'),
                    title: a.getAttribute('title')
                }))"""
            )
        except Exception:
            return []

    @staticmethod
    def _extract_images(page: Any) -> list[dict[str, Any]]:
        try:
            return page.locator("img").evaluate_all(
                """nodes => nodes.map((img, index) => ({
                    index,
                    src: img.currentSrc || img.src || null,
                    src_raw: img.getAttribute('src'),
                    alt: img.getAttribute('alt'),
                    title: img.getAttribute('title'),
                    width: img.naturalWidth || null,
                    height: img.naturalHeight || null
                }))"""
            )
        except Exception:
            return []

    @staticmethod
    def _extract_tables(page: Any) -> list[dict[str, Any]]:
        try:
            return page.locator("table").evaluate_all(
                """tables => tables.map((table, tableIndex) => ({
                    index: tableIndex,
                    id: table.id || null,
                    class_name: table.className || null,
                    rows: Array.from(table.querySelectorAll('tr')).map((tr, rowIndex) => ({
                        row_index: rowIndex,
                        cells: Array.from(tr.querySelectorAll('th,td')).map(cell => ({
                            tag: cell.tagName.toLowerCase(),
                            text: (cell.innerText || cell.textContent || '').trim(),
                            html: cell.innerHTML,
                            colspan: cell.getAttribute('colspan'),
                            rowspan: cell.getAttribute('rowspan')
                        }))
                    }))
                }))"""
            )
        except Exception:
            return []

    def _save_page_artifacts(
        self,
        page: Any,
        output_dir: Path,
        assessment: PageAssessment,
    ) -> None:
        try:
            html = page.content()
        except Exception:
            html = ""
        (output_dir / "page.html").write_text(html, encoding="utf-8")

        self._dump_json(output_dir / "links.json", self._extract_links(page))
        self._dump_json(output_dir / "images.json", self._extract_images(page))
        self._dump_json(output_dir / "tables.json", self._extract_tables(page))
        self._dump_json(output_dir / "assessment.json", assessment.as_dict())

        screenshot_error = None
        try:
            page.screenshot(path=str(output_dir / "screenshot.png"), full_page=True)
        except Exception as exc:
            screenshot_error = f"{type(exc).__name__}: {exc}"
        if screenshot_error:
            self._dump_json(
                output_dir / "screenshot_error.json",
                {"error": screenshot_error},
            )

    @staticmethod
    def _record_dict(record: AttemptRecord) -> dict[str, Any]:
        data = asdict(record)
        data["status"] = record.status.value
        return data

    def _write_latest_valid(
        self,
        *,
        base_dir: Path,
        run_dir: Path,
        snapshot_dir: Path,
        url: str,
    ) -> None:
        relative_run_dir = run_dir.relative_to(self.project_root).as_posix()
        relative_snapshot_dir = snapshot_dir.relative_to(self.project_root).as_posix()
        payload = {
            "source": "bdfutbol",
            "url": url,
            "status": AcquisitionStatus.VALID.value,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "run_directory": relative_run_dir,
            "snapshot_directory": relative_snapshot_dir,
            "page_html": f"{relative_snapshot_dir}/page.html",
        }
        self._dump_json(base_dir / "latest_valid.json", payload)

    def _write_run_summary(
        self,
        *,
        url: str,
        name: str,
        result: AcquisitionResult,
    ) -> None:
        payload = {
            "source": "bdfutbol",
            "name": name,
            "url": url,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": result.status.value,
            "valid_snapshot_directory": (
                str(result.valid_snapshot_directory)
                if result.valid_snapshot_directory is not None
                else None
            ),
            "attempts": [self._record_dict(item) for item in result.attempts],
        }
        self._dump_json(result.run_directory / "run_summary.json", payload)
