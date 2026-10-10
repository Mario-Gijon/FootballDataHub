#!/usr/bin/env python3
"""Offline browser smoke test: HTML, JavaScript, HTTP status and profile reuse.

Run on a Linux host without a desktop under ``xvfb-run``. This test serves only
localhost and is independent of BDFutbol and its access policy.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from football_data_hub.core.browser_runtime import BrowserRuntimeConfig
from football_data_hub.core.browser_session import BrowserSessionManager


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        status = 404 if self.path == "/missing" else 200
        body = b"""<!doctype html><html><head><title>FDH local browser smoke</title></head>
<body><h1 id="expected">Local test document</h1><output id="stored"></output>
<script>if (location.pathname === '/write') localStorage.setItem('fdh-smoke', 'saved');
document.querySelector('#stored').textContent = localStorage.getItem('fdh-smoke') || 'empty';
window.fdhSmoke = () => 'javascript-ready';</script></body></html>"""
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        return


def _has_live_profile_process(profile: Path) -> bool:
    expected = f"--user-data-dir={profile}".encode()
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            arguments = (process / "cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, PermissionError):
            continue
        if expected in arguments:
            return True
    return False


def _read_visit(session: BrowserSessionManager, url: str) -> dict[str, object]:
    with session.open_page(url) as visit:
        document = visit.document
        return {
            "requested_url": visit.requested_url,
            "final_url": visit.final_url,
            "http_status": visit.response_status,
            "title": document.title(),
            "html_has_expected": "Local test document" in document.html(),
            "javascript": document.evaluate("window.fdhSmoke()"),
            "local_storage": document.text("#stored"),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend",
        choices=("seleniumbase-pure-cdp", "playwright-cdp"),
        default="seleniumbase-pure-cdp",
    )
    parser.add_argument("--browser", choices=("chromium", "brave", "chrome"), default="chromium")
    args = parser.parse_args()
    if not os.environ.get("DISPLAY"):
        parser.error("Falta DISPLAY; en Linux sin escritorio ejecuta el script con xvfb-run")

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = Path(tempfile.mkdtemp(prefix="fdh-browser-smoke-"))
    profile = root / "chromium-profile"
    base_url = f"http://127.0.0.1:{server.server_port}"
    config = BrowserRuntimeConfig(
        profile_dir=profile,
        backend=args.backend,
        browser=args.browser,
        use_xvfb=True,
    )
    try:
        with BrowserSessionManager(config) as session:
            write_result = _read_visit(session, base_url + "/write")
            missing_result = _read_visit(session, base_url + "/missing")
        if not profile.is_dir():
            raise RuntimeError("El perfil persistente fue eliminado al cerrar el navegador")
        with BrowserSessionManager(config) as session:
            read_result = _read_visit(session, base_url + "/read")
        report = {
            "backend": args.backend,
            "display": os.environ.get("DISPLAY"),
            "write": write_result,
            "http_404": missing_result,
            "profile_reopen": read_result,
            "profile_preserved_after_close": profile.is_dir(),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        valid = (
            write_result["http_status"] == 200
            and write_result["html_has_expected"] is True
            and write_result["javascript"] == "javascript-ready"
            and missing_result["http_status"] == 404
            and read_result["local_storage"] == "saved"
            and report["profile_preserved_after_close"] is True
        )
        return 0 if valid else 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        # Never remove even a temporary profile while a browser still uses it.
        if _has_live_profile_process(profile):
            print(f"Perfil temporal conservado porque Chromium sigue activo: {profile}")
        else:
            import shutil

            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
