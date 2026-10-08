"""Hito 0A: inventario DOM de solo lectura de una página de BDFutbol.

No hace clic, no cambia selectores, no envía formularios ni sigue enlaces.
Un inventario DOM no equivale a cobertura exhaustiva de una entidad.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from football_data_hub.providers.bdfutbol.access import AccessAssessment, AccessStatus

SCHEMA_VERSION = "bdfutbol.discovery.dom.v1"

# Solo lectura. El código se ejecuta en la página YA validada por BDFutbolAccess.
# Si algo está detrás de un clic o una petición posterior, lo señalamos como PENDING.
DOM_INVENTORY_JS = r"""
(opts) => {
  const { maxLinks, maxTables, maxImages, maxControls, maxOptions, maxText } = opts;
  const normalize = (value, limit=maxText) => String(value ?? '')
    .replace(/\s+/g, ' ').trim().slice(0, limit);
  const attrs = (node, keys) => Object.fromEntries(keys.map(k =>
    [k, node.getAttribute(k)]).filter(([,v]) => v !== null));
  const href = (node, key) => {
    const value = node.getAttribute(key);
    if (!value) return null;
    try { return new URL(value, document.baseURI).href; }
    catch (_) { return value; }
  };
  const visible = node => {
    if (!node || node.hidden) return false;
    const s = getComputedStyle(node);
    if (s.display === 'none' || s.visibility === 'hidden' || s.visibility === 'collapse') return false;
    return node.getClientRects().length > 0;
  };
  const elements = (selector, cap, mapper) => {
    const nodes = [...document.querySelectorAll(selector)];
    return {
      total: nodes.length,
      truncated: nodes.length > cap,
      items: nodes.slice(0, cap).map((node, index) => {
        try { return mapper(node, index); }
        catch (error) { return { index, inspection_error: String(error).slice(0, 160) }; }
      })
    };
  };
  const label = node => normalize(node.getAttribute('aria-label') ||
    node.innerText || node.textContent || node.getAttribute('title'));
  const basics = (node, index) => ({
    index,
    tag: node.tagName.toLowerCase(),
    id: node.id || null,
    classes: normalize(node.getAttribute('class'), 250),
    text: label(node),
    visible: visible(node),
    ...attrs(node, ['role', 'aria-label', 'aria-selected', 'aria-expanded',
      'aria-controls', 'aria-hidden', 'aria-current', 'data-toggle',
      'data-target', 'data-bs-toggle', 'data-bs-target', 'data-fancybox',
      'data-lightbox', 'data-gallery', 'data-action', 'data-bs-slide',
      'data-slide', 'data-bs-parent', 'onclick', 'title'])
  });
  const tables = elements('table', maxTables, (t, index) => {
    const rows = [...t.querySelectorAll('tr')];
    const headings = [...t.querySelectorAll('thead th')];
    const first = rows[0] || null;
    const headingsFound = headings.length ? headings :
      first ? [...first.querySelectorAll('th,td')] : [];
    return {
      ...basics(t, index),
      caption: normalize(t.querySelector('caption')?.textContent),
      row_count: rows.length,
      column_count_first_row: first ? first.querySelectorAll('th,td').length : 0,
      headers: headingsFound.slice(0, 70).map(h => normalize(h.textContent)),
      sample_rows: rows.slice(0, 3).map((r, ri) => ({
        row_index: ri,
        cells: [...r.querySelectorAll('th,td')].slice(0, 18).map(c => ({
          tag: c.tagName.toLowerCase(), text: normalize(c.textContent),
          colspan: c.getAttribute('colspan'), rowspan: c.getAttribute('rowspan')
        }))
      }))
    };
  });
  const links = elements('a[href]', maxLinks, (a, index) => ({
    ...basics(a, index), href: a.href || href(a, 'href'),
    href_raw: a.getAttribute('href'), target: a.getAttribute('target'),
    rel: a.getAttribute('rel')
  }));
  const images = elements('img', maxImages, (img, index) => ({
    ...basics(img, index),
    src: img.getAttribute('src'), current_src: img.currentSrc || null,
    srcset: img.getAttribute('srcset'), sizes: img.getAttribute('sizes'),
    data_src: img.getAttribute('data-src'),
    data_lazy_src: img.getAttribute('data-lazy-src'),
    loading: img.getAttribute('loading'),
    alt: img.getAttribute('alt'), natural_width: img.naturalWidth,
    natural_height: img.naturalHeight,
    closest_gallery: !!img.closest('.carousel, .swiper, .splide, [class*="gallery"], [class*="galeria"]')
  }));
  const sources = elements('picture source, source[srcset]', maxImages,
    (s, index) => ({ ...basics(s, index), srcset: s.getAttribute('srcset'),
      type: s.getAttribute('type'), media: s.getAttribute('media') }));
  const selects = elements('select', maxControls, (s, index) => {
    const all = [...s.options];
    return {
      ...basics(s, index), name: s.name || null,
      multiple: s.multiple, disabled: s.disabled,
      option_count: all.length, options_truncated: all.length > maxOptions,
      options: all.slice(0, maxOptions).map((opt, oi) => ({
        index: oi, label: normalize(opt.textContent),
        value: opt.value, selected: opt.selected, disabled: opt.disabled
      }))
    };
  });
  const buttons = elements('button, input[type="button"], input[type="submit"], [role="button"]',
    maxControls, (b, index) => ({
      ...basics(b, index), type: b.getAttribute('type'),
      disabled: !!b.disabled, name: b.getAttribute('name')
    }));
  const tabs = elements('[role="tab"], [data-bs-toggle="tab"], [data-toggle="tab"], .nav-tabs a, .nav-pills a',
    maxControls, (node, index) => ({ ...basics(node, index),
      href: node.tagName.toLowerCase() === 'a' ? node.getAttribute('href') : null }));
  const panels = elements('[role="tabpanel"], .tab-pane, [data-tab-content]',
    maxControls, (node, index) => ({ ...basics(node, index) }));
  const custom_controls = elements(
    '[role="combobox"], [role="listbox"], [role="menu"], [aria-haspopup], .dropdown-toggle, .dropdown-menu, [data-bs-toggle="dropdown"], [data-bs-toggle="collapse"], [data-toggle="collapse"], [role="switch"]',
    maxControls, (node, index) => ({ ...basics(node, index),
      href: node.getAttribute('href'), disabled: !!node.disabled })
  );
  const collapsible_panels = elements('.collapse, [role="region"], [data-bs-parent]',
    maxControls, (node, index) => ({ ...basics(node, index) }));
  const details = elements('details', maxControls, (d, index) => ({
    ...basics(d, index), open: d.open,
    summary: normalize(d.querySelector('summary')?.textContent)
  }));
  const forms = elements('form', maxControls, (f, index) => ({
    index, id: f.id || null, method: f.method || null, action: f.action || null,
    visible: visible(f),
    fields: [...f.querySelectorAll('input, select, textarea, button')].slice(0, 70)
      .map(n => ({ tag: n.tagName.toLowerCase(), type: n.getAttribute('type'),
        name: n.getAttribute('name') }))
    // IMPORTANTE: nunca leer values de inputs (contraseñas, tokens, etc.).
  }));
  const galleries = elements('.carousel, .swiper, .splide, [class*="gallery"], [id*="gallery"], [data-fancybox], [data-lightbox], [data-gallery]',
    maxControls, (g, index) => ({ ...basics(g, index),
      gallery_image_count: g.querySelectorAll('img').length }));
  const gallery_triggers = elements('button, a', maxLinks,
    (node, index) => ({ ...basics(node, index), href: node.getAttribute('href') }))
    .items.filter(item => /fotos\s*\(\s*\d+\s*\)|galer[ií]a|photos\s*\(/i.test(item.text));
  const charts = elements('canvas, svg, [data-highcharts-chart], [class*="chart"], [id*="chart"], [class*="graph"], [id*="graph"]',
    maxControls, (node, index) => ({ ...basics(node, index),
      child_svg_count: node.querySelectorAll('svg').length,
      child_canvas_count: node.querySelectorAll('canvas').length }));
  const scripts = elements('script', maxControls, (s, index) => ({
    index, type: s.type || null, src: s.src || null,
    inline_length: (s.textContent || '').length,
    chart_library_hint: /highcharts|chart\.js|apexcharts|echarts|plotly|d3\./i
      .test((s.src || '') + ' ' + (s.textContent || '').slice(0, 15000))
  }));
  const iframes = elements('iframe', maxControls,
    (f, index) => ({ ...basics(f, index), src: f.getAttribute('src') }));
  const entries = (performance.getEntriesByType('resource') || [])
    .filter(e => ['xmlhttprequest', 'fetch'].includes(e.initiatorType));
  const xhr = {
    total: entries.length, truncated: entries.length > maxLinks,
    items: entries.slice(0, maxLinks).map(e => ({
      url: e.name, initiator_type: e.initiatorType
    }))
  };
  return {
    document: {
      url: location.href, title: document.title, lang: document.documentElement.lang || null,
      ready_state: document.readyState, base_uri: document.baseURI,
      total_elements: document.querySelectorAll('*').length
    },
    links, tables, images, sources, selects, buttons, tabs, panels,
    details, custom_controls, collapsible_panels, forms, galleries, gallery_triggers,
    charts, scripts, iframes, xhr,
    notes: [
      'Sin interacciones: controles y galerías pueden contener vistas ocultas.',
      'XHR incluye solo entradas Resource Timing todavía presentes; no representa toda la actividad de red.',
      'Gráficos SVG también pueden ser iconos; requieren clasificación posterior.'
    ]
  };
}
"""


@dataclass(frozen=True, slots=True)
class InventoryLimits:
    max_links: int = 1500
    max_tables: int = 180
    max_images: int = 500
    max_controls: int = 500
    max_options: int = 500
    max_text: int = 320

    def __post_init__(self) -> None:
        if any(value < 1 or value > 10000 for value in asdict(self).values()):
            raise ValueError("Los límites deben estar entre 1 y 10000")

    def as_js_options(self) -> dict[str, int]:
        return {
            "maxLinks": self.max_links,
            "maxTables": self.max_tables,
            "maxImages": self.max_images,
            "maxControls": self.max_controls,
            "maxOptions": self.max_options,
            "maxText": self.max_text,
        }


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def assert_safe_token(token: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", token):
        raise ValueError("Nombre de recurso no seguro; usa minúsculas, números, _ o -")
    return token


def classify_link(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        return "other_scheme"
    if parsed.hostname not in {"bdfutbol.com", "www.bdfutbol.com"}:
        return "external"
    segments = [s for s in parsed.path.split("/") if s]
    if len(segments) >= 2:
        return f"/{segments[0]}/{segments[1]}/"
    if segments:
        return f"/{segments[0]}/"
    return "/"


def summarize_inventory(inventory: dict[str, Any]) -> dict[str, Any]:
    collections = (
        "links", "tables", "images", "sources", "selects", "buttons", "tabs",
        "panels", "details", "custom_controls", "collapsible_panels",
        "forms", "galleries", "charts", "scripts", "iframes", "xhr"
    )
    counts: dict[str, int] = {}
    truncated: list[str] = []
    for key in collections:
        value = inventory.get(key, {})
        if not isinstance(value, dict) or not isinstance(value.get("items"), list):
            raise ValueError(f"Inventario DOM malformado en {key}")
        counts[key] = int(value.get("total", 0))
        if value.get("truncated"):
            truncated.append(key)
    family_counter = Counter()
    for item in inventory["links"]["items"]:
        if isinstance(item, dict) and isinstance(item.get("href"), str):
            family_counter[classify_link(item["href"])] += 1
    select_option_truncated = [
        item.get("id") or f"select_{i}"
        for i, item in enumerate(inventory["selects"]["items"])
        if isinstance(item, dict) and item.get("options_truncated")
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "DOM_SNAPSHOT_ONLY",
        "interaction_coverage": "NOT_TESTED",
        "complete": False,
        "document": inventory.get("document", {}),
        "counts": counts,
        "gallery_trigger_candidates": len(inventory.get("gallery_triggers", [])),
        "link_families_in_recorded_sample": dict(family_counter.most_common()),
        "truncated_collections": truncated,
        "truncated_select_options": select_option_truncated,
        "coverage_warnings": [
            "Este inventario no demuestra que las pestañas, filtros, gráficos o galerías estén capturados.",
            *(["Algunos elementos exceden los límites de inventario."] if truncated or select_option_truncated else []),
        ],
    }


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_json(path: Path, data: Any) -> None:
    _atomic_write_bytes(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def capture_dom_snapshot(
    *,
    page: Any,
    assessment: AccessAssessment,
    output_dir: Path,
    limits: InventoryLimits = InventoryLimits(),
    screenshot: bool = False,
) -> dict[str, Any]:
    """Archiva HTML renderizado y un inventario sin mutar la página.

    Solo debe invocarse tras haber validado AccessStatus.VALID.
    output_dir ha de ser nuevo: la captura histórica es inmutable.
    """
    if assessment.status is not AccessStatus.VALID:
        raise ValueError("No se guardan capturas de contenido bloqueado como válidas")
    if output_dir.exists():
        raise FileExistsError(f"Snapshot ya existente: {output_dir}")
    output_dir.mkdir(parents=True)
    try:
        inventory = page.evaluate(DOM_INVENTORY_JS, limits.as_js_options())
        if not isinstance(inventory, dict):
            raise ValueError("El navegador no devolvió un inventario DOM válido")
        summary = summarize_inventory(inventory)
        html = page.content()
        if not isinstance(html, str):
            raise ValueError("El navegador no devolvió HTML")
        html_bytes = html.encode("utf-8")
        _atomic_write_bytes(output_dir / "rendered.html", html_bytes)
        write_json(output_dir / "inventory.json", inventory)
        screenshot_error = None
        if screenshot:
            try:
                page.screenshot(path=str(output_dir / "screenshot.png"), full_page=True, timeout=20000)
            except Exception as exc:
                screenshot_error = f"{type(exc).__name__}: {exc}"[:350]
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "requested_url": assessment.requested_url,
            "final_url": assessment.final_url,
            "access_status": assessment.status.value,
            "http_status": assessment.http_status,
            "page_title": assessment.page_title,
            "rendered_html_bytes": len(html_bytes),
            "rendered_html_sha256": hashlib.sha256(html_bytes).hexdigest(),
            "screenshot_error": screenshot_error,
        }
        write_json(output_dir / "metadata.json", metadata)
        write_json(output_dir / "summary.json", summary)
        return {**metadata, "inventory_summary": summary}
    except Exception:
        # No dejar una captura parcial como aparentemente completa.
        (output_dir / "INCOMPLETE").write_text("Captura incompleta: revisar archivos del snapshot.\n", encoding="utf-8")
        raise
