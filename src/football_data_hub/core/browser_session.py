"""Backend-agnostic browser documents for controlled source acquisition.

Providers receive only the small :class:`BrowserDocument` interface below.
The default backend is SeleniumBase Pure CDP; the former Brave/Playwright CDP
runtime remains available explicitly for regression checks.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .browser_runtime import (
    BrowserRuntime,
    BrowserRuntimeConfig,
    _acquire_profile_lock,
    _release_profile_lock,
    find_browser,
    start_browser,
)


class BrowserSessionError(RuntimeError):
    """No se pudo establecer o cerrar la sesión del navegador."""


class BrowserNavigationError(BrowserSessionError):
    """Falló la navegación; no implica por sí sola un desafío del sitio."""


@runtime_checkable
class BrowserDocument(Protocol):
    """Operaciones DOM compartidas por los proveedores de adquisición."""

    @property
    def url(self) -> str: ...

    def title(self) -> str: ...

    def html(self) -> str: ...

    def text(self, selector: str) -> str: ...

    def texts(self, selector: str) -> list[str]: ...

    def count(self, selector: str) -> int: ...

    def exists(self, selector: str) -> bool: ...

    def option_map(self, selector: str) -> dict[str, str]: ...

    def select(self, selector: str, value: str) -> None: ...

    def fill(self, selector: str, value: str) -> None: ...

    def value(self, selector: str) -> str: ...

    def evaluate(self, expression: str) -> Any: ...

    def wait(self, milliseconds: int) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class BrowserInfo:
    backend: str
    browser_name: str
    browser_executable: str
    browser_version: str | None
    automation_version: str | None
    display: str | None
    uses_xvfb: bool
    xvfb_external: bool


@dataclass(slots=True)
class PageVisit:
    document: BrowserDocument
    requested_url: str
    initial_response_status: int | None
    _closed: bool = False

    @property
    def response_status(self) -> int | None:
        current = getattr(self.document, "response_status", None)
        return current if isinstance(current, int) else self.initial_response_status

    @property
    def page(self) -> BrowserDocument:
        """Compatibility alias; this is a provider-neutral document adapter."""
        return self.document

    @property
    def final_url(self) -> str:
        return self.document.url

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self.document.close()
            except Exception:
                pass

    def __enter__(self) -> PageVisit:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class _PlaywrightDocument:
    """Translate the legacy Playwright page to the provider-neutral contract."""

    def __init__(self, page: Any) -> None:
        self._page = page
        self.response_status: int | None = None

    @property
    def url(self) -> str:
        return str(self._page.url)

    def title(self) -> str:
        return str(self._page.title())

    def html(self) -> str:
        return str(self._page.content())

    def text(self, selector: str) -> str:
        return str(self._page.locator(selector).inner_text(timeout=3000))

    def texts(self, selector: str) -> list[str]:
        return list(self._page.locator(selector).all_text_contents())

    def count(self, selector: str) -> int:
        return int(self._page.locator(selector).count())

    def exists(self, selector: str) -> bool:
        return self._page.locator(selector).count() > 0

    def option_map(self, selector: str) -> dict[str, str]:
        return self._page.locator(f"{selector} option").evaluate_all(
            "options => Object.fromEntries(options.map(option => "
            "[option.value, option.textContent.trim()]))"
        )

    def select(self, selector: str, value: str) -> None:
        self._page.locator(selector).select_option(value)

    def fill(self, selector: str, value: str) -> None:
        self._page.locator(selector).fill(value)

    def value(self, selector: str) -> str:
        return str(self._page.locator(selector).input_value())

    def evaluate(self, expression: str) -> Any:
        return self._page.evaluate(expression)

    def wait(self, milliseconds: int) -> None:
        self._page.wait_for_timeout(milliseconds)

    def close(self) -> None:
        self._page.close()


class _PureCDPDocument:
    def __init__(self, backend: _PureCDPBackend, tab: Any) -> None:
        self._backend = backend
        self._tab = tab
        self._closed = False

    def _run(self, operation):
        if self._closed:
            raise BrowserSessionError("El documento ya está cerrado")
        return self._backend.run_on_tab(self._tab, operation)

    @property
    def url(self) -> str:
        return str(self.evaluate("window.location.href"))

    def title(self) -> str:
        return str(self._run(self._backend.browser.get_title))

    def html(self) -> str:
        return str(self._run(
            lambda: self._backend.browser.get_page_source(include_shadow_dom=False)
        ))

    def text(self, selector: str) -> str:
        return str(self._run(lambda: self._backend.browser.get_text(selector)))

    def texts(self, selector: str) -> list[str]:
        expression = (
            "(() => Array.from(document.querySelectorAll("
            f"{json.dumps(selector)})).map(element => element.textContent || ''))()"
        )
        result = self.evaluate(expression)
        return [str(value) for value in result] if isinstance(result, list) else []

    def count(self, selector: str) -> int:
        result = self.evaluate(
            f"document.querySelectorAll({json.dumps(selector)}).length"
        )
        return int(result) if isinstance(result, (int, float)) else 0

    def exists(self, selector: str) -> bool:
        expression = f"document.querySelector({json.dumps(selector)}) !== null"
        return self.evaluate(expression) is True

    def option_map(self, selector: str) -> dict[str, str]:
        expression = (
            "(() => Object.fromEntries(Array.from(document.querySelectorAll("
            f"{json.dumps(selector)} + ' option')).map(option => ["
            "option.value, (option.textContent || '').trim()])))()"
        )
        result = self.evaluate(expression)
        return {str(key): str(value) for key, value in result.items()} if isinstance(result, dict) else {}

    def select(self, selector: str, value: str) -> None:
        expression = (
            "(() => { const element = document.querySelector("
            f"{json.dumps(selector)}); if (!element) throw new Error('Missing control'); "
            f"element.value = {json.dumps(value)}; "
            "element.dispatchEvent(new Event('input', {bubbles: true})); "
            "element.dispatchEvent(new Event('change', {bubbles: true})); return true; })()"
        )
        self.evaluate(expression)

    def fill(self, selector: str, value: str) -> None:
        expression = (
            "(() => { const element = document.querySelector("
            f"{json.dumps(selector)}); if (!element) throw new Error('Missing control'); "
            f"element.value = {json.dumps(value)}; "
            "element.dispatchEvent(new Event('input', {bubbles: true})); "
            "element.dispatchEvent(new Event('change', {bubbles: true})); return true; })()"
        )
        self.evaluate(expression)

    def value(self, selector: str) -> str:
        result = self.evaluate(
            f"document.querySelector({json.dumps(selector)})?.value ?? ''"
        )
        return str(result)

    def evaluate(self, expression: str) -> Any:
        return self._run(lambda: self._backend.browser.evaluate(expression))

    def wait(self, milliseconds: int) -> None:
        time.sleep(max(milliseconds, 0) / 1000)

    def close(self) -> None:
        # SeleniumBase owns one tab in this integration. Invalidating the
        # document is enough; the session closes the browser and tab together.
        self._closed = True


def _seleniumbase_browser(**kwargs: Any) -> Any:
    try:
        from seleniumbase import sb_cdp
    except ImportError as exc:
        raise BrowserSessionError(
            "Falta SeleniumBase Pure CDP. Instala las dependencias con "
            "`pip install -e '.[scraping]'`."
        ) from exc
    return sb_cdp.Chrome(**kwargs)


def _playwright_api():
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserSessionError(
            "Falta Playwright para el backend de regresión. "
            "Instala `pip install -e '.[scraping-playwright]'`."
        ) from exc
    return sync_playwright, PlaywrightError


def _browser_version(executable: str) -> str | None:
    try:
        result = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (result.stdout or result.stderr).strip() or None


def _seleniumbase_version() -> str | None:
    try:
        return version("seleniumbase")
    except PackageNotFoundError:
        return None


class _PureCDPBackend:
    def __init__(self, config: BrowserRuntimeConfig, navigation_timeout_ms: int) -> None:
        self.config = config
        self.navigation_timeout_ms = navigation_timeout_ms
        self.browser: Any | None = None
        self.info: BrowserInfo | None = None
        self._lock_fd: int | None = None
        self._profile: Path | None = None
        self._browser_pid: int | None = None

    def start(self) -> None:
        if not os.environ.get("DISPLAY"):
            if self.config.use_xvfb:
                raise BrowserSessionError(
                    "Pure CDP requiere un DISPLAY. En Linux sin escritorio, "
                    "inicia el comando con `xvfb-run -a -s '-screen 0 "
                    f"{self.config.screen}' ...`."
                )
            raise BrowserSessionError(
                "Pure CDP necesita un DISPLAY o Xvfb externo; no se inicia una pantalla oculta automáticamente."
            )
        if self.config.browser != "chromium":
            raise BrowserSessionError(
                "SeleniumBase Pure CDP está configurado para Chromium. "
                "Usa --browser chromium; Brave sigue disponible con el backend Playwright."
            )

        profile = self.config.profile_dir.expanduser().resolve()
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._profile = profile
        self._lock_fd = _acquire_profile_lock(profile)
        try:
            executable = (
                str(self.config.browser_executable_path.expanduser().resolve())
                if self.config.browser_executable_path
                else find_browser(self.config.browser)
            )
            if not Path(executable).is_file():
                raise BrowserSessionError(f"No existe Chromium en {executable}")
            started = time.monotonic()
            self.browser = _seleniumbase_browser(
                url="about:blank",
                user_data_dir=str(profile),
                headless=False,
                browser_executable_path=executable,
                browser_args=["--window-size=1440,1000"],
                xvfb=False,
                headed=True,
            )
            driver = self.browser.driver
            if hasattr(driver, "cdp_base"):
                driver = driver.cdp_base
            self._browser_pid = getattr(driver, "_process_pid", None)
            elapsed = time.monotonic() - started
            if elapsed > self.config.startup_timeout_seconds:
                raise BrowserSessionError(
                    "Pure CDP superó el timeout de arranque configurado "
                    f"({elapsed:.1f}s > {self.config.startup_timeout_seconds:.1f}s)."
                )
            self.info = BrowserInfo(
                backend="seleniumbase-pure-cdp",
                browser_name="Chromium",
                browser_executable=executable,
                browser_version=_browser_version(executable),
                automation_version=_seleniumbase_version(),
                display=os.environ.get("DISPLAY"),
                uses_xvfb=bool(self.config.use_xvfb),
                xvfb_external=True,
            )
        except BaseException:
            self.close()
            raise

    def run_on_tab(self, tab: Any, operation):
        if self.browser is None:
            raise BrowserSessionError("La sesión de navegador está cerrada")
        self.browser.switch_to_tab(tab)
        return operation()

    def open_page(self, url: str) -> tuple[BrowserDocument, int | None]:
        if self.browser is None:
            raise BrowserSessionError("Llama a start() antes de navegar")
        try:
            tab = self.browser.get_active_tab()
            timeout = self.navigation_timeout_ms / 1000
            self.browser.loop.run_until_complete(
                asyncio.wait_for(tab.get(url), timeout=timeout)
            )
            document = _PureCDPDocument(self, tab)
            try:
                response_status = document.evaluate(
                    "(() => { const entry = performance.getEntriesByType('navigation')[0]; "
                    "return entry && typeof entry.responseStatus === 'number' "
                    "? entry.responseStatus : null; })()"
                )
            except Exception:
                response_status = None
            if not isinstance(response_status, int):
                response_status = None
            return document, response_status
        except Exception as exc:
            raise BrowserNavigationError(
                f"No se pudo navegar a {url} con SeleniumBase Pure CDP: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def close(self) -> None:
        browser, self.browser = self.browser, None
        pid = self._browser_pid
        self._browser_pid = None
        close_error: Exception | None = None
        if browser is not None:
            try:
                browser.quit()
            except Exception as exc:
                close_error = exc
        if pid is not None and _pid_running(pid):
            if self._profile is not None and _owned_profile_process(pid, self._profile):
                _terminate_pid(pid, self.config.shutdown_timeout_seconds)
            if _pid_running(pid) and close_error is None:
                close_error = BrowserSessionError(
                    f"Chromium (PID {pid}) sigue activo tras cerrar Pure CDP."
                )
        if self._lock_fd is not None:
            _release_profile_lock(self._lock_fd)
            self._lock_fd = None
        if close_error is not None:
            raise BrowserSessionError(f"No se pudo cerrar Pure CDP limpiamente: {close_error}")


class _PlaywrightCDPBackend:
    def __init__(
        self,
        config: BrowserRuntimeConfig,
        *,
        cdp_timeout_ms: int,
        navigation_timeout_ms: int,
    ) -> None:
        self.config = config
        self.cdp_timeout_ms = cdp_timeout_ms
        self.navigation_timeout_ms = navigation_timeout_ms
        self.runtime: BrowserRuntime | None = None
        self.playwright: Any | None = None
        self.browser: Any | None = None
        self.context: Any | None = None
        self.info: BrowserInfo | None = None

    def start(self) -> None:
        sync_playwright, PlaywrightError = _playwright_api()
        self._playwright_error = PlaywrightError
        self.runtime = start_browser(self.config)
        try:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.connect_over_cdp(
                self.runtime.cdp_url,
                timeout=self.cdp_timeout_ms,
            )
            if not self.browser.contexts:
                raise BrowserSessionError("CDP no ha expuesto ningún contexto")
            self.context = self.browser.contexts[0]
            executable = self.runtime.browser_path
            try:
                playwright_version = version("playwright")
            except PackageNotFoundError:
                playwright_version = None
            self.info = BrowserInfo(
                backend="playwright-cdp",
                browser_name=Path(executable).name,
                browser_executable=executable,
                browser_version=_browser_version(executable),
                automation_version=playwright_version,
                display=os.environ.get("DISPLAY"),
                uses_xvfb=bool(self.config.use_xvfb),
                xvfb_external=False,
            )
        except Exception as exc:
            self.close()
            if isinstance(exc, BrowserSessionError):
                raise
            raise BrowserSessionError(
                f"Falló la conexión CDP con Playwright: {type(exc).__name__}: {exc}"
            ) from exc

    def open_page(self, url: str) -> tuple[BrowserDocument, int | None]:
        if self.context is None:
            raise BrowserSessionError("Llama a start() antes de navegar")
        page = self.context.new_page()
        document = _PlaywrightDocument(page)
        try:
            page.set_default_navigation_timeout(self.navigation_timeout_ms)

            def observe_document_response(response: Any) -> None:
                try:
                    if response.request.is_navigation_request() and response.frame == page.main_frame:
                        document.response_status = response.status
                except self._playwright_error:
                    return

            page.on("response", observe_document_response)
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.navigation_timeout_ms,
            )
            if document.response_status is None and response is not None:
                document.response_status = response.status
            return document, document.response_status
        except Exception as exc:
            try:
                page.close()
            except Exception:
                pass
            raise BrowserNavigationError(
                f"No se pudo navegar a {url}: {type(exc).__name__}: {exc}"
            ) from exc

    def close(self) -> None:
        if self.browser is not None:
            try:
                self.browser.close()
            except Exception:
                pass
            self.browser = None
        self.context = None
        if self.playwright is not None:
            try:
                self.playwright.stop()
            except Exception:
                pass
            self.playwright = None
        if self.runtime is not None:
            self.runtime.close()
            self.runtime = None


def _pid_running(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").rsplit(")", 1)[1].split()[0]
        return state != "Z"
    except (FileNotFoundError, IndexError, PermissionError):
        return False


def _owned_profile_process(pid: int, profile: Path) -> bool:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except (FileNotFoundError, PermissionError):
        return False
    expected = f"--user-data-dir={profile}".encode()
    return expected in raw


def _terminate_pid(pid: int, shutdown_timeout_seconds: float) -> None:
    for signum, timeout in (
        (signal.SIGTERM, shutdown_timeout_seconds),
        (signal.SIGKILL, 2.0),
    ):
        if not _pid_running(pid):
            return
        try:
            os.kill(pid, signum)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not _pid_running(pid):
                return
            time.sleep(0.05)


class BrowserSessionManager:
    """Own one browser session and expose only provider-neutral documents."""

    def __init__(
        self,
        config: BrowserRuntimeConfig,
        *,
        cdp_timeout_ms: int = 20_000,
        navigation_timeout_ms: int = 45_000,
    ) -> None:
        if cdp_timeout_ms <= 0 or navigation_timeout_ms <= 0:
            raise ValueError("Los timeouts deben ser positivos")
        self.config = config
        self.cdp_timeout_ms = cdp_timeout_ms
        self.navigation_timeout_ms = navigation_timeout_ms
        if config.backend == "seleniumbase-pure-cdp":
            self._backend: Any = _PureCDPBackend(config, navigation_timeout_ms)
        else:
            self._backend = _PlaywrightCDPBackend(
                config,
                cdp_timeout_ms=cdp_timeout_ms,
                navigation_timeout_ms=navigation_timeout_ms,
            )
        self._visits: list[PageVisit] = []

    @property
    def ready(self) -> bool:
        if isinstance(self._backend, _PureCDPBackend):
            return self._backend.browser is not None
        return self._backend.context is not None

    @property
    def runtime(self) -> BrowserRuntime | None:
        return getattr(self._backend, "runtime", None)

    @property
    def info(self) -> BrowserInfo | None:
        return self._backend.info

    @property
    def cdp_url(self) -> str | None:
        return self.runtime.cdp_url if self.runtime is not None else None

    def start(self) -> BrowserSessionManager:
        if self.ready:
            raise BrowserSessionError("La sesión ya está iniciada")
        try:
            self._backend.start()
            return self
        except Exception:
            self.close()
            raise

    def open_page(self, url: str) -> PageVisit:
        if not self.ready:
            raise BrowserSessionError("Llama a start() antes de navegar")
        document, response_status = self._backend.open_page(url)
        visit = PageVisit(document, url, response_status)
        self._visits.append(visit)
        return visit

    def close(self) -> None:
        for visit in self._visits:
            visit.close()
        self._visits.clear()
        self._backend.close()

    def __enter__(self) -> BrowserSessionManager:
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.close()
