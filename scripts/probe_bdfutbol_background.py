#!/usr/bin/env python3
"""Probe autónomo de adquisición de BDFutbol.

Este script comprueba si FootballDataHub puede adquirir una página de BDFutbol
sin que el usuario tenga Brave abierto manualmente.

Arquitectura del probe
----------------------
1. Lanza Brave/Chrome/Chromium directamente como proceso normal.
2. Usa un perfil persistente independiente.
3. Expone un puerto Chrome DevTools Protocol (CDP).
4. Playwright se conecta DESPUÉS al navegador ya iniciado.
5. Navega a una única URL.
6. Guarda el DOM renderizado y metadatos de discovery.
7. Evalúa si el DOM final es una página BDFutbol utilizable.

No intenta resolver, falsificar ni evitar desafíos anti-bot.

Importante sobre Cloudflare
---------------------------
El HTTP status de la navegación NO se utiliza por sí solo para decidir si la
captura sirve. En nuestras pruebas BDFutbol puede dejar rastros de Cloudflare o
incluso devolver un status diagnóstico 403 mientras el navegador termina
conteniendo el DOM completo de la página.

La decisión final se basa principalmente en:
- título real de BDFutbol;
- contenido visible;
- estructura DOM útil;
- ausencia de un challenge visible dominante;
- textos esperados opcionales (--expect).

Perfil por defecto:
    ~/.football-data-hub-browser

El navegador manual que use ese mismo perfil debe estar cerrado antes de
ejecutar este script.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


DEFAULT_URL = "https://www.bdfutbol.com/es/t/t2026-271rf1.html"

VISIBLE_CHALLENGE_MARKERS = (
    "just a moment",
    "enable javascript and cookies to continue",
    "verificación de seguridad en curso",
    "verificacion de seguridad en curso",
    "verifique que es un ser humano",
    "verify you are human",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Lanza un navegador normal, se conecta por CDP y captura una página "
            "de BDFutbol."
        )
    )
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--name", default="group1_background")
    parser.add_argument(
        "--profile",
        default=str(Path.home() / ".football-data-hub-browser"),
        help="Perfil persistente del navegador.",
    )
    parser.add_argument(
        "--browser",
        choices=("auto", "brave", "chrome", "chromium"),
        default="auto",
    )
    parser.add_argument("--timeout-ms", type=int, default=45_000)
    parser.add_argument("--settle-ms", type=int, default=3_000)
    parser.add_argument(
        "--expect",
        action="append",
        default=[],
        help=(
            "Texto que debe aparecer en el contenido visible. Puede repetirse. "
            "Útil para verificar que se capturó el recurso esperado."
        ),
    )
    parser.add_argument(
        "--keep-browser",
        action="store_true",
        help="No cerrar el navegador al terminar (solo diagnóstico).",
    )
    return parser.parse_args()


def dump_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find_browser(preference: str) -> str | None:
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

    for binary in candidates[preference]:
        path = shutil.which(binary)
        if path:
            return path

    return None


def reserve_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_cdp(port: int, timeout_seconds: float = 20.0) -> dict[str, Any]:
    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None

    while time.monotonic() < deadline:
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

    raise RuntimeError(
        f"CDP no estuvo disponible en {url}. Último error: {last_error}"
    )


def build_browser_command(
    browser_path: str,
    *,
    port: int,
    profile: Path,
) -> tuple[list[str], bool]:
    browser_args = [
        browser_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--window-size=1440,1000",
        "about:blank",
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

    raise RuntimeError(
        "No existe DISPLAY y tampoco se encontró xvfb-run. "
        "En un servidor instala Xvfb o ejecuta este probe en una sesión gráfica."
    )


def visible_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=5_000)
    except Exception:
        return ""


def assess_page(page, expected_texts: list[str]) -> dict[str, Any]:
    """Evalúa el DOM final, no solo el status HTTP."""
    try:
        title = page.title().strip()
    except Exception:
        title = ""

    body = visible_text(page)
    body_lower = body.lower()
    title_lower = title.lower()

    table_count = page.locator("table").count()
    link_count = page.locator("a").count()
    image_count = page.locator("img").count()

    visible_challenge_markers = [
        marker
        for marker in VISIBLE_CHALLENGE_MARKERS
        if marker in body_lower or marker in title_lower
    ]

    expected_results = {
        text: text.lower() in body_lower
        for text in expected_texts
    }
    expected_ok = all(expected_results.values())

    title_looks_real = (
        "bdfutbol" in title_lower
        and "just a moment" not in title_lower
    )

    # Una página BDFutbol útil tiene contenido visible y estructura navegable.
    structural_content = (
        len(body.strip()) >= 200
        and link_count >= 10
    )

    # Un challenge visible dominante no debe considerarse captura válida.
    challenge_visible = bool(visible_challenge_markers)

    accessible = (
        title_looks_real
        and structural_content
        and not challenge_visible
        and expected_ok
    )

    return {
        "accessible": accessible,
        "title_looks_real": title_looks_real,
        "structural_content": structural_content,
        "visible_challenge": challenge_visible,
        "visible_challenge_markers": visible_challenge_markers,
        "body_text_chars": len(body),
        "table_count": table_count,
        "link_count": link_count,
        "image_count": image_count,
        "expected_texts": expected_results,
        "expected_texts_ok": expected_ok,
    }


def extract_links(page) -> list[dict[str, Any]]:
    return page.locator("a").evaluate_all(
        """nodes => nodes.map((a, index) => ({
            index,
            text: (a.innerText || a.textContent || '').trim(),
            href: a.href || null,
            href_raw: a.getAttribute('href'),
            title: a.getAttribute('title')
        }))"""
    )


def extract_images(page) -> list[dict[str, Any]]:
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


def extract_tables(page) -> list[dict[str, Any]]:
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


def terminate_process(process: subprocess.Popen[Any]) -> None:
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


def main() -> int:
    args = parse_args()

    project_root = Path(__file__).resolve().parents[1]
    output_dir = (
        project_root
        / "data"
        / "raw"
        / "discovery"
        / args.name
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    profile = Path(args.profile).expanduser().resolve()
    profile.mkdir(parents=True, exist_ok=True)

    browser_path = find_browser(args.browser)
    if not browser_path:
        print("[!] No se encontró Brave/Chrome/Chromium.", file=sys.stderr)
        return 2

    port = reserve_free_port()

    try:
        command, using_xvfb = build_browser_command(
            browser_path,
            port=port,
            profile=profile,
        )
    except RuntimeError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 2

    print(f"[+] Browser:  {browser_path}")
    print(f"[+] Profile:  {profile}")
    print(f"[+] CDP port: {port}")
    print(f"[+] Xvfb:     {using_xvfb}")
    print(f"[+] URL:      {args.url}")
    if args.expect:
        print(f"[+] Expect:   {args.expect}")
    print()
    print("[i] El perfil no puede estar abierto simultáneamente en otro Brave.")

    started_at = datetime.now(timezone.utc)

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        print(f"[!] No se pudo lanzar el navegador: {exc}", file=sys.stderr)
        return 2

    try:
        try:
            cdp_info = wait_for_cdp(port)
        except RuntimeError as exc:
            print(f"[!] {exc}", file=sys.stderr)
            return 2

        cdp_url = f"http://127.0.0.1:{port}"

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(cdp_url)
            except PlaywrightError as exc:
                print(f"[!] Error conectando por CDP: {exc}", file=sys.stderr)
                return 2

            contexts = browser.contexts
            if not contexts:
                print("[!] El navegador no expone ningún contexto.", file=sys.stderr)
                return 2

            context = contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_navigation_timeout(args.timeout_ms)

            navigation_error = None
            response_status = None

            try:
                response = page.goto(
                    args.url,
                    wait_until="domcontentloaded",
                    timeout=args.timeout_ms,
                )
                if response:
                    response_status = response.status
            except PlaywrightTimeoutError as exc:
                navigation_error = f"{type(exc).__name__}: {exc}"

            page.wait_for_timeout(args.settle_ms)

            assessment = assess_page(page, args.expect)

            html = page.content()
            links = extract_links(page)
            images = extract_images(page)
            tables = extract_tables(page)

            (output_dir / "page.html").write_text(html, encoding="utf-8")
            dump_json(output_dir / "links.json", links)
            dump_json(output_dir / "images.json", images)
            dump_json(output_dir / "tables.json", tables)

            screenshot_error = None
            try:
                page.screenshot(
                    path=str(output_dir / "screenshot.png"),
                    full_page=True,
                )
            except Exception as exc:
                screenshot_error = f"{type(exc).__name__}: {exc}"

            summary = {
                "probe_version": 2,
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "started_at_utc": started_at.isoformat(),
                "requested_url": args.url,
                "final_url": page.url,
                "title": page.title(),
                "browser_binary": browser_path,
                "profile": str(profile),
                "using_xvfb": using_xvfb,
                "http_status_diagnostic": response_status,
                "navigation_error": navigation_error,
                "html_bytes": len(html.encode("utf-8")),
                "assessment": assessment,
                "screenshot_error": screenshot_error,
                "cdp_browser": cdp_info.get("Browser"),
                "cdp_protocol_version": cdp_info.get("Protocol-Version"),
            }
            dump_json(output_dir / "summary.json", summary)

            print("\n=== RESULTADO AUTÓNOMO V1 ===")
            print(f"Accesible:       {assessment['accessible']}")
            print(f"Challenge visible: {assessment['visible_challenge']}")
            print(f"HTTP diagnóstico:  {response_status}")
            print(f"URL final:       {page.url}")
            print(f"Título:          {page.title()}")
            print(f"HTML:            {summary['html_bytes']} bytes")
            print(f"Texto visible:   {assessment['body_text_chars']} chars")
            print(f"Enlaces:         {assessment['link_count']}")
            print(f"Imágenes:        {assessment['image_count']}")
            print(f"Tablas:          {assessment['table_count']}")

            if args.expect:
                print("\nTextos esperados:")
                for text, found in assessment["expected_texts"].items():
                    print(f"  {'✅' if found else '❌'} {text}")

            print(f"\n[+] Captura: {output_dir}")

            if not assessment["accessible"]:
                print(
                    "\n[!] El DOM final no se considera una página BDFutbol "
                    "utilizable. Revisa summary.json y screenshot.png.",
                    file=sys.stderr,
                )
                return 3

            return 0

    finally:
        if not args.keep_browser:
            terminate_process(process)
        else:
            print(f"[i] Navegador mantenido abierto (PID {process.pid}).")


if __name__ == "__main__":
    raise SystemExit(main())
