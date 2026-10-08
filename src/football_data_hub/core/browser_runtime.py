"""Lifecycle de Brave/Chromium con CDP privado y pantalla Xvfb.

No resuelve desafíos del sitio: requiere que el acceso ya esté autorizado.
El lock solo coordina procesos FootballDataHub que utilicen este módulo.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import IO


class BrowserRuntimeError(RuntimeError):
    """No se pudo iniciar o detener el navegador administrado."""


class BrowserProfileInUse(BrowserRuntimeError):
    """Otro proceso FootballDataHub tiene reservado el perfil."""


@dataclass(frozen=True, slots=True)
class BrowserRuntimeConfig:
    profile_dir: Path
    browser: str = "brave"
    use_xvfb: bool = True
    screen: str = "1920x1080x24"
    start_url: str = "about:blank"
    startup_timeout_seconds: float = 35.0
    shutdown_timeout_seconds: float = 8.0
    browser_log_path: Path | None = None

    def __post_init__(self) -> None:
        if self.browser not in {"auto", "brave", "chrome", "chromium"}:
            raise ValueError(f"Navegador no soportado: {self.browser}")
        if self.startup_timeout_seconds <= 0 or self.shutdown_timeout_seconds <= 0:
            raise ValueError("Los tiempos de espera deben ser positivos")
        if not self.start_url.startswith(("about:blank", "https://")):
            raise ValueError("start_url debe ser about:blank o una URL HTTPS")


@dataclass(slots=True)
class BrowserRuntime:
    process: subprocess.Popen[bytes]
    browser_path: str
    profile_dir: Path
    cdp_port: int
    cdp_url: str
    uses_xvfb: bool
    _lock_fd: int
    _shutdown_timeout_seconds: float
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            stop_process_group(self.process, self._shutdown_timeout_seconds)
        finally:
            _release_profile_lock(self._lock_fd)

    def __enter__(self) -> BrowserRuntime:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


_BROWSER_NAMES: dict[str, tuple[str, ...]] = {
    "brave": ("brave", "brave-browser"),
    "chrome": ("google-chrome", "google-chrome-stable"),
    "chromium": ("chromium", "chromium-browser"),
    "auto": (
        "brave", "brave-browser", "google-chrome", "google-chrome-stable",
        "chromium", "chromium-browser",
    ),
}


def find_browser(preference: str) -> str:
    for name in _BROWSER_NAMES.get(preference, ()):
        result = shutil.which(name)
        if result:
            return result
    raise BrowserRuntimeError(f"No se encontró navegador instalado: {preference}")


def reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def build_command(config: BrowserRuntimeConfig, browser_path: str, port: int) -> list[str]:
    profile = config.profile_dir.expanduser().resolve()
    command = [
        browser_path,
        "--ozone-platform=x11",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--window-size=1440,1000",
        config.start_url,
    ]
    if not config.use_xvfb:
        # El navegador puede ejecutarse en DISPLAY existente; Ozone en X11 explícito.
        return command
    xvfb = shutil.which("xvfb-run")
    if not xvfb:
        raise BrowserRuntimeError("No se encontró xvfb-run; instala Xvfb en el servidor")
    return [xvfb, "-a", "-s", f"-screen 0 {config.screen}", *command]


def _acquire_profile_lock(profile_dir: Path) -> int:
    lock_path = profile_dir.parent / f".{profile_dir.name}.fdh.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise BrowserProfileInUse(
            f"Perfil reservado por otro proceso FootballDataHub: {profile_dir}"
        ) from exc
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"pid={os.getpid()}\n".encode())
    except OSError:
        _release_profile_lock(fd)
        raise
    return fd


def _release_profile_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def wait_for_cdp(port: int, process: subprocess.Popen[bytes], timeout_seconds: float) -> dict:
    endpoint = f"http://127.0.0.1:{port}/json/version"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout_seconds
    last_error = "sin respuesta"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise BrowserRuntimeError(
                f"Brave terminó antes de habilitar CDP (código {process.returncode})."
            )
        try:
            with opener.open(endpoint, timeout=1.0) as response:
                payload = json.load(response)
            if isinstance(payload, dict) and payload.get("webSocketDebuggerUrl"):
                return payload
            last_error = "CDP no ha publicado webSocketDebuggerUrl"
        except (OSError, ValueError, TimeoutError, urllib.error.URLError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.25)
    raise BrowserRuntimeError(f"CDP no disponible en {endpoint}: {last_error}")


def stop_process_group(process: subprocess.Popen[bytes], timeout_seconds: float) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=timeout_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        pass


def start_browser(config: BrowserRuntimeConfig) -> BrowserRuntime:
    profile = config.profile_dir.expanduser().resolve()
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_fd = _acquire_profile_lock(profile)
    process: subprocess.Popen[bytes] | None = None
    log_handle: IO[bytes] | None = None
    try:
        path = find_browser(config.browser)
        port = reserve_loopback_port()
        command = build_command(config, path, port)
        env = os.environ.copy()
        if config.use_xvfb:
            env.pop("WAYLAND_DISPLAY", None)
            env.pop("WAYLAND_SOCKET", None)
            env["XDG_SESSION_TYPE"] = "x11"
            env["GDK_BACKEND"] = "x11"
            env["OZONE_PLATFORM"] = "x11"
        stderr_target: int | IO[bytes] = subprocess.DEVNULL
        if config.browser_log_path is not None:
            log_path = config.browser_log_path.expanduser().resolve()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("ab")
            stderr_target = log_handle
        process = subprocess.Popen(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr_target,
            start_new_session=True,
        )
        wait_for_cdp(port, process, config.startup_timeout_seconds)
        return BrowserRuntime(
            process=process,
            browser_path=path,
            profile_dir=profile,
            cdp_port=port,
            cdp_url=f"http://127.0.0.1:{port}",
            uses_xvfb=config.use_xvfb,
            _lock_fd=lock_fd,
            _shutdown_timeout_seconds=config.shutdown_timeout_seconds,
        )
    except BaseException:
        try:
            if process is not None:
                stop_process_group(process, config.shutdown_timeout_seconds)
        finally:
            _release_profile_lock(lock_fd)
        raise
    finally:
        if log_handle is not None:
            log_handle.close()
