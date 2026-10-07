#!/usr/bin/env python3
"""Probe de BDFutbol conectándose a un Brave normal mediante CDP.

Este script NO abre el navegador, NO navega automáticamente y NO intenta
resolver ni evitar protecciones anti-bot.

Flujo esperado:
1. El usuario abre Brave manualmente con --remote-debugging-port.
2. El usuario entra normalmente en BDFutbol.
3. Este script se conecta al navegador ya abierto.
4. Localiza una pestaña de bdfutbol.com.
5. Captura el DOM renderizado y metadatos de discovery.

Esto nos permite comprobar si la sesión normal del navegador puede servir como
capa de adquisición para FootballDataHub sin construir todavía un crawler.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


DEFAULT_CDP_URL = "http://127.0.0.1:9222"
DEFAULT_HOST_FRAGMENT = "bdfutbol.com"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Captura la pestaña BDFutbol de un Brave ya abierto vía CDP."
    )
    parser.add_argument(
        "--cdp-url",
        default=DEFAULT_CDP_URL,
        help=f"Endpoint CDP. Default: {DEFAULT_CDP_URL}",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST_FRAGMENT,
        help=f"Texto que debe aparecer en la URL objetivo. Default: {DEFAULT_HOST_FRAGMENT}",
    )
    parser.add_argument(
        "--name",
        default="group1_cdp",
        help="Nombre de la captura bajo data/raw/discovery/. Default: group1_cdp",
    )
    return parser.parse_args()


def dump_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def extract_links(page) -> list[dict]:
    return page.locator("a").evaluate_all(
        """nodes => nodes.map((a, index) => ({
            index,
            text: (a.innerText || a.textContent || '').trim(),
            href: a.href || null,
            href_raw: a.getAttribute('href'),
            title: a.getAttribute('title'),
            target: a.getAttribute('target')
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
        """tables => tables.map((table, tableIndex) => ({
            index: tableIndex,
            id: table.id || null,
            class_name: table.className || null,
            rows: Array.from(table.querySelectorAll('tr')).map((tr, rowIndex) => ({
                row_index: rowIndex,
                cells: Array.from(tr.querySelectorAll('th,td')).map(cell => ({
                    tag: cell.tagName.toLowerCase(),
                    text: (cell.innerText || cell.textContent || '').trim(),
                    colspan: cell.getAttribute('colspan'),
                    rowspan: cell.getAttribute('rowspan')
                }))
            }))
        }))"""
    )


def classify_links(links: list[dict], current_host: str) -> dict[str, int]:
    counts: Counter[str] = Counter()

    for link in links:
        href = link.get("href")
        if not href:
            continue

        parsed = urlparse(href)

        if parsed.netloc and parsed.netloc != current_host:
            counts["external"] += 1
            continue

        parts = [part for part in parsed.path.split("/") if part]

        if len(parts) >= 2:
            # Ejemplos esperados:
            # /es/t/... -> /es/t/
            # /es/p/... -> /es/p/
            # /es/j/... -> /es/j/
            family = "/" + "/".join(parts[:2]) + "/"
        elif parts:
            family = "/" + parts[0] + "/"
        else:
            family = "/"

        counts[family] += 1

    return dict(counts.most_common())


def main() -> int:
    args = parse_args()

    project_root = Path(__file__).resolve().parents[1]
    output_dir = project_root / "data" / "raw" / "discovery" / args.name
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[+] CDP endpoint: {args.cdp_url}")
    print(f"[+] Buscando pestaña que contenga: {args.host}")

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.connect_over_cdp(args.cdp_url)
        except PlaywrightError as exc:
            print(
                "\n[!] No se pudo conectar al navegador por CDP.\n"
                f"    {exc}\n\n"
                "Comprueba que Brave sigue abierto y que se inició con:\n"
                "  --remote-debugging-port=9222\n",
                file=sys.stderr,
            )
            return 2

        try:
            pages = [
                page
                for context in browser.contexts
                for page in context.pages
            ]

            page_inventory = []
            target = None

            for index, page in enumerate(pages):
                try:
                    title = page.title()
                except Exception:
                    title = ""

                page_inventory.append(
                    {
                        "index": index,
                        "url": page.url,
                        "title": title,
                    }
                )

                if target is None and args.host.lower() in page.url.lower():
                    target = page

            dump_json(output_dir / "browser_pages.json", page_inventory)

            print(f"[+] Pestañas visibles por CDP: {len(pages)}")
            for item in page_inventory:
                print(
                    f"    [{item['index']}] "
                    f"{item['title'][:55]!r} -> {item['url']}"
                )

            if target is None:
                print(
                    f"\n[!] No encuentro ninguna pestaña cuya URL contenga "
                    f"{args.host!r}.\n"
                    "    Abre BDFutbol en el Brave conectado y vuelve a ejecutar.",
                    file=sys.stderr,
                )
                return 3

            print(f"\n[+] Pestaña BDFutbol encontrada: {target.url}")

            # Importante: no recargamos, no hacemos goto(), no hacemos clic.
            html = target.content()
            links = extract_links(target)
            images = extract_images(target)
            tables = extract_tables(target)

            (output_dir / "page.html").write_text(html, encoding="utf-8")
            dump_json(output_dir / "links.json", links)
            dump_json(output_dir / "images.json", images)
            dump_json(output_dir / "tables.json", tables)

            screenshot_error = None
            try:
                target.screenshot(
                    path=str(output_dir / "screenshot.png"),
                    full_page=True,
                )
            except Exception as exc:
                screenshot_error = f"{type(exc).__name__}: {exc}"

            current_host = urlparse(target.url).netloc
            body_text = ""
            try:
                body_text = target.locator("body").inner_text()
            except Exception:
                pass

            summary = {
                "probe_version": 1,
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "cdp_url": args.cdp_url,
                "page_url": target.url,
                "page_title": target.title(),
                "host": current_host,
                "html_bytes": len(html.encode("utf-8")),
                "body_text_chars": len(body_text),
                "link_count": len(links),
                "image_count": len(images),
                "table_count": len(tables),
                "path_families": classify_links(links, current_host),
                "screenshot_error": screenshot_error,
                "browser_page_count": len(pages),
            }
            dump_json(output_dir / "summary.json", summary)

            print("\n=== RESULTADO CDP ===")
            print(f"URL:       {summary['page_url']}")
            print(f"Título:    {summary['page_title']}")
            print(f"HTML:      {summary['html_bytes']} bytes")
            print(f"Texto:     {summary['body_text_chars']} caracteres")
            print(f"Enlaces:   {summary['link_count']}")
            print(f"Imágenes:  {summary['image_count']}")
            print(f"Tablas:    {summary['table_count']}")

            print("\nFamilias de enlaces:")
            for family, count in summary["path_families"].items():
                print(f"  {family:<12} {count}")

            print(f"\n[+] Captura guardada en: {output_dir}")
            print(
                "[+] No se ha navegado, recargado ni modificado la pestaña."
            )

            return 0
        finally:
            # Desconectamos Playwright del navegador. No cerramos Brave.
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
