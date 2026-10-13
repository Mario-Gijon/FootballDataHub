"""Verify Pure CDP stays on a private Xvfb using only about:blank."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from football_data_hub.core.browser_runtime import BrowserRuntimeConfig
from football_data_hub.core.browser_session import (
    BrowserSessionManager,
    _acquire_profile_lock,
    _pid_running,
    _process_display,
    _release_profile_lock,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path.home() / ".football-data-hub-chromium-pure-cdp",
    )
    parser.add_argument("--browser-executable", type=Path)
    parser.add_argument("--screen", default="1920x1080x24")
    args = parser.parse_args()

    executable = args.browser_executable
    if executable is None:
        chromium = shutil.which("chromium") or shutil.which("chromium-browser")
        if chromium is None:
            parser.error("No se encontró Chromium")
        executable = Path(chromium)

    config = BrowserRuntimeConfig(
        profile_dir=args.profile,
        backend="seleniumbase-pure-cdp",
        browser="chromium",
        browser_executable_path=executable,
        use_xvfb=True,
        screen=args.screen,
        start_url="about:blank",
    )
    session = BrowserSessionManager(config)
    info = None
    try:
        session.start()
        info = session.info
        with session.open_page("about:blank") as visit:
            page = {
                "url": visit.final_url,
                "title": visit.document.title(),
                "screen": visit.document.evaluate(
                    "({width: window.screen.width, height: window.screen.height})"
                ),
            }
        if not info or not info.browser_pid or not info.xvfb_pid:
            raise RuntimeError("La sesión no informó los PID de Chromium y Xvfb")
        if info.process_display != info.display:
            raise RuntimeError("El DISPLAY del proceso Chromium no coincide con Xvfb")
    finally:
        session.close()

    if not info or not info.browser_pid or not info.xvfb_pid:
        raise RuntimeError("No se capturaron los datos de los procesos")
    if _pid_running(info.browser_pid):
        raise RuntimeError(f"Quedó Chromium activo tras cerrar (PID {info.browser_pid})")
    if _pid_running(info.xvfb_pid):
        raise RuntimeError(f"Quedó Xvfb activo tras cerrar (PID {info.xvfb_pid})")
    if _process_display(info.browser_pid) is not None:
        raise RuntimeError("Se pudo leer DISPLAY tras cerrar Chromium; el proceso sigue presente")

    lock_fd = _acquire_profile_lock(config.profile_dir.expanduser().resolve())
    _release_profile_lock(lock_fd)
    print(json.dumps({
        "status": "ok",
        "backend": info.backend,
        "browser_executable": info.browser_executable,
        "browser_pid": info.browser_pid,
        "browser_display": info.process_display,
        "xvfb_pid": info.xvfb_pid,
        "xvfb_external": info.xvfb_external,
        "uses_xvfb": info.uses_xvfb,
        "about_blank": page,
        "browser_process_closed": True,
        "xvfb_process_closed": True,
        "profile_lock_reacquired": True,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
