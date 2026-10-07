from __future__ import annotations

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
from typing import Any


class BrowserRuntimeError(RuntimeError):
    pass


@dataclass(slots=True)
class BrowserProcess:
    process: subprocess.Popen[Any]
    browser_path: str
    profile: Path
    cdp_port: int
    cdp_url: str
    using_xvfb: bool
    start_url: str


def find_browser(preference: str = "auto") -> str | None:
    candidates = {
        "brave": ("brave", "brave-browser"),
        "chrome": ("google-chrome", "google-chrome-stable"),
        "chromium": ("chromium", "chromium-browser"),
        "auto": (
            "brave",
            "brave-browser",
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
        ),
    }
    if preference not in candidates:
        raise ValueError(f"Navegador no soportado: {preference!r}")

    for binary in candidates[preference]:
        path = shutil.which(binary)
        if path:
            return path
    return None


def reserve_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_cdp(
    port: int,
    *,
    process: subprocess.Popen[Any] | None = None,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None

    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise BrowserRuntimeError(
                f"El navegador terminó antes de exponer CDP (exit={process.returncode})."
            )

        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                return json.loads(response.read().decode("utf-8"))
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            json.JSONDecodeError,
        ) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.25)

    raise BrowserRuntimeError(
        f"CDP no estuvo disponible en {url}. Último error: {last_error}"
    )


def build_browser_command(
    browser_path: str,
    *,
    port: int,
    profile: Path,
    start_url: str = "about:blank",
) -> tuple[list[str], bool]:
    browser_args = [
        browser_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--window-size=1440,1000",
        start_url,
    ]

    if os.environ.get("DISPLAY"):
        return browser_args, False

    xvfb_run = shutil.which("xvfb-run")
    if xvfb_run:
        return [
            xvfb_run,
            "-a",
            "-s",
            "-screen 0 1440x1000x24",
            *browser_args,
        ], True

    raise BrowserRuntimeError(
        "No existe DISPLAY y tampoco se encontró xvfb-run. "
        "En servidor instala Xvfb para ejecutar Brave sin escritorio."
    )


def start_browser(
    *,
    profile: Path,
    preference: str = "auto",
    start_url: str = "about:blank",
    cdp_timeout_seconds: float = 20.0,
) -> BrowserProcess:
    browser_path = find_browser(preference)
    if not browser_path:
        raise BrowserRuntimeError("No se encontró Brave/Chrome/Chromium.")

    profile = profile.expanduser().resolve()
    profile.mkdir(parents=True, exist_ok=True)
    port = reserve_free_port()
    command, using_xvfb = build_browser_command(
        browser_path,
        port=port,
        profile=profile,
        start_url=start_url,
    )

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise BrowserRuntimeError(f"No se pudo lanzar el navegador: {exc}") from exc

    try:
        wait_for_cdp(
            port,
            process=process,
            timeout_seconds=cdp_timeout_seconds,
        )
    except Exception:
        stop_browser_process(process)
        raise

    return BrowserProcess(
        process=process,
        browser_path=browser_path,
        profile=profile,
        cdp_port=port,
        cdp_url=f"http://127.0.0.1:{port}",
        using_xvfb=using_xvfb,
        start_url=start_url,
    )


def stop_browser_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        try:
            process.terminate()
        except ProcessLookupError:
            return

    try:
        process.wait(timeout=8)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            process.kill()
        except ProcessLookupError:
            pass


def stop_browser(browser: BrowserProcess) -> None:
    stop_browser_process(browser.process)
