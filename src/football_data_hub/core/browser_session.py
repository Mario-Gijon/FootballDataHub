"""Backend-agnostic browser documents for controlled source acquisition.

Providers receive only the small :class:`BrowserDocument` interface below.
The default backend is SeleniumBase Pure CDP; the former Brave/Playwright CDP
runtime remains available explicitly for regression checks.
"""

from __future__ import annotations

import asyncio
import json
import os
import select
import signal
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
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
    browser_pid: int | None = None
    xvfb_pid: int | None = None
    process_display: str | None = None
    screen_size: tuple[int, int] | None = None


@dataclass(slots=True)
class _ManagedXvfb:
    process: subprocess.Popen[bytes]
    display: str
    shutdown_timeout_seconds: float
    _closed: bool = False

    @property
    def pid(self) -> int:
        return self.process.pid

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        from .browser_runtime import stop_process_group

        stop_process_group(self.process, self.shutdown_timeout_seconds)


_BROWSER_ENV_LOCK = threading.RLock()
_RAW_CHROMIUM_BINARIES = (
    Path("/usr/lib/chromium/chromium"),
    Path("/usr/lib64/chromium/chromium"),
    Path("/usr/lib/chromium-browser/chromium-browser"),
    Path("/opt/chromium/chrome"),
)
_DISPLAY_ENV_KEYS = (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "WAYLAND_SOCKET",
    "XDG_SESSION_TYPE",
    "GDK_BACKEND",
    "OZONE_PLATFORM",
    "XAUTHORITY",
)


@contextmanager
def _browser_display_environment(display: str):
    """Give the browser launch only the selected X11 display environment."""

    updates = {
        "DISPLAY": display,
        "XDG_SESSION_TYPE": "x11",
        "GDK_BACKEND": "x11",
        "OZONE_PLATFORM": "x11",
    }
    with _BROWSER_ENV_LOCK:
        previous = {key: os.environ.get(key) for key in _DISPLAY_ENV_KEYS}
        for key in _DISPLAY_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ.update(updates)
        try:
            yield
        finally:
            for key in _DISPLAY_ENV_KEYS:
                os.environ.pop(key, None)
            for key, value in previous.items():
                if value is not None:
                    os.environ[key] = value


def _start_xvfb(screen: str, timeout_seconds: float) -> _ManagedXvfb:
    """Start an owned, TCP-disabled Xvfb and receive its allocated display."""

    executable = shutil.which("Xvfb")
    if not executable:
        raise BrowserSessionError(
            "Pure CDP necesita Xvfb para mantener Chromium fuera del escritorio; "
            "no se encontró el ejecutable Xvfb."
        )
    read_fd, write_fd = os.pipe()
    process: subprocess.Popen[bytes] | None = None
    try:
        env = os.environ.copy()
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "XAUTHORITY"):
            env.pop(key, None)
        env.update({"XDG_SESSION_TYPE": "x11", "GDK_BACKEND": "x11"})
        process = subprocess.Popen(
            [
                executable,
                "-displayfd",
                str(write_fd),
                "-screen",
                "0",
                screen,
                "-nolisten",
                "tcp",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            pass_fds=(write_fd,),
            start_new_session=True,
        )
        os.close(write_fd)
        write_fd = -1
        ready, _, _ = select.select([read_fd], [], [], timeout_seconds)
        if not ready:
            raise BrowserSessionError(
                f"Xvfb no asignó DISPLAY dentro de {timeout_seconds:.1f}s."
            )
        display_number = os.read(read_fd, 64).decode("ascii", errors="strict").strip()
        if process.poll() is not None:
            raise BrowserSessionError(
                f"Xvfb terminó durante el arranque (código {process.returncode})."
            )
        if not display_number.isdigit():
            raise BrowserSessionError(
                f"Xvfb devolvió un identificador DISPLAY inválido: {display_number!r}."
            )
        return _ManagedXvfb(
            process=process,
            display=f":{display_number}",
            shutdown_timeout_seconds=min(timeout_seconds, 8.0),
        )
    except BaseException:
        if process is not None:
            from .browser_runtime import stop_process_group

            stop_process_group(process, min(timeout_seconds, 8.0))
        raise
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


def _process_display(pid: int) -> str | None:
    """Read the DISPLAY inherited by a real process from procfs."""

    try:
        entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None
    for entry in entries:
        if entry.startswith(b"DISPLAY="):
            return entry.partition(b"=")[2].decode("utf-8", errors="replace")
    return None


def _process_command_line(pid: int) -> list[str]:
    try:
        values = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return []
    return [value.decode("utf-8", errors="replace") for value in values if value]


def _process_start_identity(pid: int) -> str | None:
    """Stable kernel start tick used to distinguish an owned PID from reuse."""

    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").rsplit(")", 1)[1].split()
        return fields[19]
    except (FileNotFoundError, PermissionError, IndexError):
        return None


@contextmanager
def _capture_browser_process_launch(executable: str):
    """Record the exact inherited display environment at Chromium exec time."""

    launches: list[dict[str, Any]] = []
    original = asyncio.create_subprocess_exec
    expected_executable = str(Path(executable).resolve())

    async def monitored_create_subprocess_exec(program, *args, **kwargs):
        try:
            actual_executable = str(Path(os.fspath(program)).resolve())
        except (TypeError, ValueError, OSError):
            actual_executable = ""
        if actual_executable == expected_executable:
            launch = {
                "display": os.environ.get("DISPLAY"),
                "wayland_display": os.environ.get("WAYLAND_DISPLAY"),
                "wayland_socket": os.environ.get("WAYLAND_SOCKET"),
                "ozone_platform": os.environ.get("OZONE_PLATFORM"),
                "argv": [str(program), *(str(arg) for arg in args)],
            }
            process = await original(program, *args, **kwargs)
            launch["pid"] = process.pid
            launch["start_identity"] = _process_start_identity(process.pid)
            launches.append(launch)
            return process
        return await original(program, *args, **kwargs)

    with _BROWSER_ENV_LOCK:
        asyncio.create_subprocess_exec = monitored_create_subprocess_exec
        try:
            yield launches
        finally:
            asyncio.create_subprocess_exec = original


def _resolve_chromium_executable(configured: Path | None) -> str:
    requested = configured.expanduser().resolve() if configured else Path(find_browser("chromium")).resolve()
    # Arch's /usr/bin/chromium launcher reads ~/.config/chromium-flags.conf,
    # which can force Wayland even when Xvfb was selected. Use the packaged
    # browser binary directly when available so desktop-only flags stay out.
    if requested.name in {"chromium", "chromium-browser"}:
        for candidate in _RAW_CHROMIUM_BINARIES:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate.resolve())
    return str(requested)


def _profile_process_pids(profile: Path) -> list[int]:
    """Find Chromium processes already using this exact profile, without touching them."""

    expected = f"--user-data-dir={profile.resolve()}".encode()
    matches: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == os.getpid():
            continue
        try:
            state = (entry / "stat").read_text(encoding="ascii").rsplit(")", 1)[1].split()[0]
            args = (entry / "cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, PermissionError, IndexError):
            continue
        if state != "Z" and expected in b"\0".join(args):
            matches.append(pid)
    return matches


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
        self._browser_start_identity: str | None = None
        self._xvfb: _ManagedXvfb | None = None
        self._browser_display: str | None = None

    def start(self) -> None:
        if not self.config.use_xvfb and not os.environ.get("DISPLAY"):
            raise BrowserSessionError(
                "Pure CDP sin Xvfb necesita un DISPLAY existente. "
                "La ejecución segura predeterminada inicia una pantalla Xvfb propia."
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
            existing = _profile_process_pids(profile)
            if existing:
                raise BrowserSessionError(
                    "No se iniciará otra instancia ni se conectará a Chromium existente "
                    f"que usa el perfil autorizado {profile} (PID: {existing})."
                )
            executable = _resolve_chromium_executable(
                self.config.browser_executable_path
            )
            if not Path(executable).is_file():
                raise BrowserSessionError(f"No existe Chromium en {executable}")
            if self.config.use_xvfb:
                self._xvfb = _start_xvfb(
                    self.config.screen,
                    self.config.startup_timeout_seconds,
                )
                self._browser_display = self._xvfb.display
            else:
                self._browser_display = os.environ.get("DISPLAY")
            if not self._browser_display:
                raise BrowserSessionError(
                    "No se pudo seleccionar un DISPLAY para Chromium; no se abrirán páginas."
                )
            started = time.monotonic()
            with (
                _browser_display_environment(self._browser_display),
                _capture_browser_process_launch(executable) as browser_launches,
            ):
                self.browser = _seleniumbase_browser(
                    url="about:blank",
                    user_data_dir=str(profile),
                    headless=False,
                    browser_executable_path=executable,
                    browser_args=[
                        "--window-size=1440,1000",
                        "--ozone-platform=x11",
                    ],
                    xvfb=False,
                    headed=True,
                )
            driver = self.browser.driver
            if hasattr(driver, "cdp_base"):
                driver = driver.cdp_base
            self._browser_pid = getattr(driver, "_process_pid", None)
            process_display = self._browser_display
            screen_size: tuple[int, int] | None = None
            if self.config.use_xvfb:
                if self._browser_pid is None:
                    raise BrowserSessionError(
                        "SeleniumBase no expuso el PID de Chromium; no es posible "
                        "verificar el DISPLAY efectivo, así que la sesión se cerrará."
                    )
                if not browser_launches:
                    raise BrowserSessionError(
                        "No se pudo observar la creación del proceso Chromium; "
                        "no se permitirá navegar sin verificar su entorno."
                    )
                for launch in browser_launches:
                    if (
                        launch["display"] != self._browser_display
                        or launch["wayland_display"] is not None
                        or launch["wayland_socket"] is not None
                        or launch["ozone_platform"] != "x11"
                        or "--ozone-platform=x11" not in launch["argv"]
                        or any(
                            argument.startswith("--ozone-platform=wayland")
                            for argument in launch["argv"]
                        )
                    ):
                        raise BrowserSessionError(
                            "Aislamiento gráfico no verificado: el entorno o los "
                            "argumentos del Chromium no fuerzan X11 en el DISPLAY Xvfb."
                        )
                matching_launch = next(
                    (
                        launch
                        for launch in browser_launches
                        if launch.get("pid") == self._browser_pid
                    ),
                    None,
                )
                expected_profile_arg = f"--user-data-dir={profile}"
                if (
                    matching_launch is None
                    or matching_launch.get("start_identity") is None
                    or "--ozone-platform=x11" not in matching_launch["argv"]
                    or expected_profile_arg not in matching_launch["argv"]
                ):
                    raise BrowserSessionError(
                        "Aislamiento gráfico no verificado: no se pudo vincular el PID "
                        "de Chromium con la ejecución en Xvfb, el perfil solicitado y X11."
                    )
                self._browser_start_identity = matching_launch["start_identity"]
                process_display = matching_launch["display"]
                if not _pid_running(self._browser_pid):
                    raise BrowserSessionError(
                        "El proceso Chromium terminó antes de poder verificar su aislamiento."
                    )
                screen = self.browser.evaluate(
                    "({width: window.screen.width, height: window.screen.height})"
                )
                expected_screen = tuple(
                    int(value) for value in self.config.screen.split("x")[:2]
                )
                if (
                    not isinstance(screen, dict)
                    or screen.get("width") != expected_screen[0]
                    or screen.get("height") != expected_screen[1]
                ):
                    raise BrowserSessionError(
                        "Aislamiento gráfico no verificado: Chromium no informa el "
                        f"tamaño de pantalla Xvfb esperado {expected_screen!r} (recibido {screen!r})."
                    )
                screen_size = expected_screen
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
                display=self._browser_display,
                uses_xvfb=bool(self.config.use_xvfb),
                xvfb_external=False,
                browser_pid=self._browser_pid,
                xvfb_pid=self._xvfb.pid if self._xvfb else None,
                process_display=process_display,
                screen_size=screen_size,
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
            if (
                self._browser_start_identity is not None
                and _process_start_identity(pid) == self._browser_start_identity
            ):
                _terminate_pid(pid, self.config.shutdown_timeout_seconds)
            if _pid_running(pid) and close_error is None:
                close_error = BrowserSessionError(
                    f"Chromium (PID {pid}) sigue activo tras cerrar Pure CDP."
                )
        xvfb, self._xvfb = self._xvfb, None
        if xvfb is not None:
            xvfb.close()
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
