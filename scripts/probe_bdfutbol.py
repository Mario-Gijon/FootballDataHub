#!/usr/bin/env python3
"""Probe de viabilidad de BDFutbol usando un navegador real.

No es el crawler definitivo. Abre una única página, detecta si Cloudflare sigue
activo y, si accedemos a la página real, guarda HTML, enlaces, imágenes, tablas
y tráfico de red para estudiar cómo construir la capa de adquisición.

No intenta saltarse Cloudflare. Si aparece un challenge en modo visible, puedes
completarlo normalmente en el navegador y pulsar ENTER en la terminal.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

DEFAULT_URL = "https://www.bdfutbol.com/es/t/t2026-271rf1.html"

CHALLENGE_MARKERS = (
    "just a moment",
    "enable javascript and cookies to continue",
    "/cdn-cgi/challenge-platform/",
    "cf-chl-",
)


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--name", default="group1")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--browser",
        choices=("auto", "brave", "chrome", "chromium"),
        default="auto",
    )
    parser.add_argument("--timeout-ms", type=int, default=45_000)
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


def is_challenge(page) -> bool:
    try:
        content = f"{page.title()}\n{page.content()}".lower()
    except Exception:
        return True

    return any(marker in content for marker in CHALLENGE_MARKERS)


def extract_links(page) -> list[dict]:
    return page.locator("a").evaluate_all(
        """nodes => nodes.map((a, index) => ({
            index,
            text: (a.innerText || a.textContent || '').trim(),
            href: a.href || null,
            href_raw: a.getAttribute('href'),
            title: a.getAttribute('title')
        }))"""
    )


def extract_images(page) -> list[dict]:
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


def extract_tables(page) -> list[dict]:
    return page.locator("table").evaluate_all(
        """tables => tables.map((table, index) => ({
            index,
            id: table.id || null,
            class_name: table.className || null,
            rows: Array.from(table.querySelectorAll('tr')).map(tr =>
                Array.from(tr.querySelectorAll('th,td')).map(cell =>
                    (cell.innerText || cell.textContent || '').trim()
                )
            )
        }))"""
    )


def path_families(links: list[dict], host: str) -> dict[str, int]:
    counts: Counter[str] = Counter()

    for link in links:
        href = link.get("href")
        if not href:
            continue

        parsed = urlparse(href)
        if parsed.netloc and parsed.netloc != host:
            continue

        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2:
            family = f"/{parts[0]}/{parts[1]}/"
        elif parts:
            family = f"/{parts[0]}/"
        else:
            family = "/"

        counts[family] += 1

    return dict(counts.most_common())


def main() -> int:
    cli = args()

    root = Path(__file__).resolve().parents[1]
    discovery = root / "data" / "raw" / "discovery"
    output = discovery / cli.name
    profile = discovery / "_browser_profile"

    output.mkdir(parents=True, exist_ok=True)
    profile.mkdir(parents=True, exist_ok=True)

    browser_path = find_browser(cli.browser)
    network: list[dict] = []

    print(f"[+] URL:     {cli.url}")
    print(f"[+] Output:  {output}")
    print(f"[+] Browser: {browser_path or 'Playwright Chromium'}")

    with sync_playwright() as playwright:
        launch_options = {
            "headless": cli.headless,
            "viewport": {"width": 1440, "height": 1000},
            "locale": "es-ES",
        }
        if browser_path:
            launch_options["executable_path"] = browser_path

        try:
            context = playwright.chromium.launch_persistent_context(
                str(profile),
                **launch_options,
            )
        except Exception as exc:
            print(f"[!] No se pudo abrir el navegador: {exc}", file=sys.stderr)
            print(
                "    Si hace falta Chromium de Playwright:\n"
                "    playwright install chromium",
                file=sys.stderr,
            )
            return 2

        try:
            page = context.pages[0] if context.pages else context.new_page()

            def record_response(response) -> None:
                network.append(
                    {
                        "url": response.url,
                        "status": response.status,
                        "resource_type": response.request.resource_type,
                        "content_type": response.headers.get("content-type"),
                    }
                )

            page.on("response", record_response)
            page.set_default_navigation_timeout(cli.timeout_ms)

            response = None
            navigation_error = None

            try:
                response = page.goto(
                    cli.url,
                    wait_until="domcontentloaded",
                    timeout=cli.timeout_ms,
                )
            except PlaywrightTimeoutError as exc:
                navigation_error = str(exc)

            page.wait_for_timeout(2_000)

            if is_challenge(page):
                if cli.headless:
                    print(
                        "[!] Cloudflare sigue activo en headless.",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "\n[!] Cloudflare ha mostrado un challenge.\n"
                        "    No vamos a intentar saltarlo.\n"
                        "    Si puedes continuar normalmente en la ventana abierta,\n"
                        "    hazlo y después vuelve aquí.\n"
                    )
                    input("Pulsa ENTER cuando veas la página real: ")
                    page.wait_for_timeout(2_000)

            accessible = not is_challenge(page)

            html = page.content()
            links = extract_links(page)
            images = extract_images(page)
            tables = extract_tables(page)

            (output / "page.html").write_text(html, encoding="utf-8")
            dump_json(output / "links.json", links)
            dump_json(output / "images.json", images)
            dump_json(output / "tables.json", tables)
            dump_json(output / "network.json", network)

            try:
                page.screenshot(
                    path=str(output / "screenshot.png"),
                    full_page=True,
                )
                screenshot_saved = True
            except Exception:
                screenshot_saved = False

            resource_types = Counter(
                item["resource_type"] for item in network
            )

            summary = {
                "probe_version": 1,
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "requested_url": cli.url,
                "final_url": page.url,
                "title": page.title(),
                "accessible": accessible,
                "challenge_remaining": is_challenge(page),
                "main_status": response.status if response else None,
                "navigation_error": navigation_error,
                "browser_executable": browser_path,
                "html_bytes": len(html.encode("utf-8")),
                "links": len(links),
                "images": len(images),
                "tables": len(tables),
                "network_responses": len(network),
                "network_resource_types": dict(resource_types),
                "xhr_or_fetch": sum(
                    resource_types[k] for k in ("xhr", "fetch")
                ),
                "path_families": path_families(
                    links,
                    urlparse(page.url or cli.url).netloc,
                ),
                "screenshot_saved": screenshot_saved,
            }
            dump_json(output / "summary.json", summary)

            print("\n=== RESULTADO ===")
            print(f"Accesible:         {summary['accessible']}")
            print(f"Título:            {summary['title']}")
            print(f"Status principal:  {summary['main_status']}")
            print(f"HTML:              {summary['html_bytes']} bytes")
            print(f"Enlaces:           {summary['links']}")
            print(f"Imágenes:          {summary['images']}")
            print(f"Tablas:            {summary['tables']}")
            print(f"Respuestas red:    {summary['network_responses']}")
            print(f"XHR/fetch:         {summary['xhr_or_fetch']}")

            print("\nFamilias de rutas:")
            for family, count in summary["path_families"].items():
                print(f"  {family:<12} {count}")

            print(f"\n[+] Artefactos guardados en {output}")

            if not accessible:
                print(
                    "[!] No hemos obtenido todavía la página real.",
                    file=sys.stderr,
                )
                return 3

            return 0
        finally:
            context.close()


if __name__ == "__main__":
    raise SystemExit(main())
