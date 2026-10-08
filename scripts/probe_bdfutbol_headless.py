#!/usr/bin/env python3
"""Hito -1: small, auditable BDFutbol HTTP/headless feasibility probe.

No CAPTCHA solving, stealth patches, proxy rotation, credential storage, or bulk crawl.
Dependencies: standard library; Playwright is required only for headless/both modes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


TARGETS = {
    "player_morillas": "https://www.bdfutbol.com/es/j/j209629.html",
    "club_real_jaen": "https://www.bdfutbol.com/es/e/e49.html",
    "team_real_jaen_2026_27": "https://www.bdfutbol.com/es/t/t2026-2749.html",
    "match_europa_real_jaen": "https://www.bdfutbol.com/es/p/p.php?id=272523",
}
DOMAIN = "www.bdfutbol.com"
USER_AGENT = "FootballDataHub-FeasibilityProbe/0.1 (limited research; no bulk crawl)"
MAX_HTML_BYTES = 12 * 1024 * 1024
MAX_NETWORK_EVENTS = 150
SENSITIVE_QUERY = re.compile(r"(?:^|_)(?:token|key|password|secret|signature|session|authorization|auth|nonce|cf_clearance)(?:$|_)", re.I)
CHALLENGE_PHRASES = (
    "just a moment...",
    "checking your browser",
    "verify you are human",
    "attention required! | cloudflare",
    "cf-challenge",
    "challenge-platform",
    "cf-turnstile",
    "cf_chl_",
    "cloudflare ray id",
)
_BLOCKED_WORDS = (
    "eliminar", "borrar", "enviar", "comprar", "registrar", "login", "log in", "logout",
    "delete", "remove", "save", "submit", "purchase", "suscrib", "account",
)


def utcstamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def redact_url(url: str) -> str:
    """Avoid putting obvious authorization query parameters into log artifacts."""
    parts = urlsplit(url)
    query = [(k, "[REDACTED]" if SENSITIVE_QUERY.search(k) else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def is_allowed_url(url: str) -> bool:
    parts = urlsplit(url)
    return (parts.scheme == "https" and parts.hostname == DOMAIN
            and parts.username is None and parts.password is None
            and (parts.port in (None, 443)))


def classify_response(status: int | None, html: str, title: str = "") -> str:
    sample = (title + "\n" + html[:150_000]).lower()
    if any(marker in sample for marker in CHALLENGE_PHRASES):
        return "CHALLENGE_REQUIRED"
    if status in (401, 403, 429, 503):
        return "ACCESS_DENIED_OR_RATE_LIMITED"
    if status is None or status >= 400:
        return "HTTP_ERROR"
    if len(html) < 300:
        return "INCONCLUSIVE"
    if re.search(r"<(?:table|h1|h2|main|article)\b", html, re.I):
        return "CONTENT_RECEIVED"
    return "INCONCLUSIVE"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    temp.replace(path)


def write_text(path: Path, text: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) > MAX_HTML_BYTES:
        # Never claim we preserved a full page when it exceeded our evidence limit.
        return {"saved": False, "reason": "html_too_large", "bytes": len(encoded)}
    path.write_bytes(encoded)
    return {"saved": True, "bytes": len(encoded), "sha256": sha256(encoded).hexdigest(), "path": str(path)}


class PageSummaryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_depth = 0
        self.title_parts: list[str] = []
        self.tables = 0
        self.links = 0
        self.images = 0
        self.headings = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self.title_depth += 1
        if tag == "table":
            self.tables += 1
        if tag == "a":
            self.links += 1
        if tag == "img":
            self.images += 1
        if tag in ("h1", "h2", "h3"):
            self.headings += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.title_depth = max(0, self.title_depth - 1)

    def handle_data(self, data: str) -> None:
        if self.title_depth:
            self.title_parts.append(data)

    def summary(self) -> dict[str, Any]:
        return {"title": " ".join(" ".join(self.title_parts).split()), "tables": self.tables,
                "links": self.links, "images": self.images, "headings": self.headings}


def summarize_html(html: str) -> dict[str, Any]:
    parser = PageSummaryParser()
    parser.feed(html)
    return parser.summary()


class SameOriginRedirects(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> Request | None:
        if not is_allowed_url(newurl):
            raise URLError("Redirect fuera del origen permitido: " + redact_url(newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_probe(name: str, url: str, base_dir: Path, timeout_s: float) -> dict[str, Any]:
    """One standard HTTP GET, no retry or browser-session reuse."""
    result: dict[str, Any] = {"target": name, "requested_url": redact_url(url), "mode": "http"}
    opener = build_opener(SameOriginRedirects())
    started = time.monotonic()
    try:
        request = Request(url, headers={"User-Agent": USER_AGENT,
                                        "Accept": "text/html,application/xhtml+xml"})
        try:
            response = opener.open(request, timeout=timeout_s)
        except HTTPError as e:
            response = e
        with response:
            status = response.status
            final_url = response.geturl()
            mime = response.headers.get_content_type()
            encoding = response.headers.get_content_charset() or "utf-8"
            data = response.read(MAX_HTML_BYTES + 1)
        result.update({"status_code": status, "final_url": redact_url(final_url),
                       "content_type": mime, "response_bytes": len(data)})
        if len(data) > MAX_HTML_BYTES:
            result.update({"verdict": "INCONCLUSIVE", "error": "response_too_large"})
        elif not is_allowed_url(final_url):
            result.update({"verdict": "HTTP_ERROR", "error": "off_origin_redirect"})
        elif mime not in ("text/html", "application/xhtml+xml"):
            result.update({"verdict": "INCONCLUSIVE", "error": "non_html_response"})
        else:
            html = data.decode(encoding, errors="replace")
            info = summarize_html(html)
            result.update({"verdict": classify_response(status, html, info["title"]),
                           "dom": info, "evidence": write_text(base_dir / "http.html", html)})
    except (URLError, TimeoutError, OSError, ValueError) as e:
        result.update({"verdict": "NETWORK_ERROR", "error": str(e)[:500]})
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    write_json(base_dir / "http.json", result)
    return result


# Pure JS DOM inventory (no network, no clicks, no bypass techniques).
DOM_INVENTORY_JS = r"""() => {
  const txt = e => (e.innerText || e.textContent || '').trim().replace(/\s+/g,' ').slice(0,150);
  const visible = e => { const r=e.getBoundingClientRect(); const s=getComputedStyle(e);
    return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'; };
  const absolute = v => { try { return new URL(v, location.href).href; } catch { return null; } };
  const controls = [];
  const nodes = [...document.querySelectorAll('button,select,summary,[role="tab"],a,[aria-expanded]')].slice(0,1800);
  for (let i=0;i<nodes.length;i++) {
    const el=nodes[i]; if(!visible(el)) continue;
    const tag=el.tagName.toLowerCase(), label=(el.getAttribute('aria-label')||el.getAttribute('title')||txt(el)).slice(0,150);
    const href=el.getAttribute('href')||'';
    const ancestor=el.closest('[class*="gallery"],[class*="carousel"],[class*="swiper"],[class*="slider"],[id*="gallery"],[id*="carousel"]');
    let kind='other';
    if (tag==='select') kind='select';
    else if (el.getAttribute('data-bs-toggle')==='dropdown'||el.getAttribute('aria-haspopup')==='true'||/dropdown-toggle/.test(String(el.className))) kind='dropdown';
    else if (tag==='summary'||el.hasAttribute('aria-expanded')||el.getAttribute('data-bs-toggle')==='collapse') kind='accordion';
    else if (el.getAttribute('role')==='tab'||el.getAttribute('data-bs-toggle')==='tab'||el.getAttribute('data-toggle')==='tab') kind='tab';
    else if(ancestor && /siguiente|next|anterior|previous|prev|[›‹»«]/i.test(label+' '+el.className)) kind='gallery';
    else if(/^(tabla|gr[aá]fico|table|chart)$/i.test(label) && (tag==='button'||href==='#'||href.startsWith('#'))) kind='view';
    else if(tag==='a' && (href.startsWith('#') || href.startsWith('?'))) kind='internal_link';
    const id='fdhp-'+i;
    el.setAttribute('data-fdh-probe',id);
    controls.push({id,tag,kind,label,page_url:location.href,href:href?absolute(href):null,
      button_type:tag==='button'?el.type:null,form_method:el.form?.method||null,
      aria_expanded:el.getAttribute('aria-expanded'),aria_selected:el.getAttribute('aria-selected'),
      options:tag==='select'?[...el.options].slice(0,35).map(o=>({value:o.value,text:txt(o),disabled:o.disabled})):null,
      options_count:tag==='select'?el.options.length:null});
  }
  const images = [...document.images].slice(0,650).map((i)=>({src:i.getAttribute('src'),current_src:i.currentSrc,
       srcset:i.getAttribute('srcset'),data_src:i.getAttribute('data-src'),alt:i.getAttribute('alt')}));
  const links = [...document.querySelectorAll('a[href]')].slice(0,1000).map(a=>({text:txt(a).slice(0,90),url:absolute(a.getAttribute('href'))}));
  const backgrounds=[...document.querySelectorAll('[style*=background],[data-src],[data-image],[data-photo],source[srcset]')].slice(0,400).map(e=>({tag:e.tagName,background:getComputedStyle(e).backgroundImage.slice(0,350),data_src:e.getAttribute('data-src'),data_image:e.getAttribute('data-image'),data_photo:e.getAttribute('data-photo'),srcset:e.getAttribute('srcset')}));
  const tables = [...document.querySelectorAll('table')].slice(0,120).map(t=>({id:t.id,rows:t.rows.length,
      headers:[...t.querySelectorAll('thead th')].slice(0,60).map(txt)}));
  return {url:location.href,title:document.title,body_characters:document.body?.innerText?.length||0,
    headings:[...document.querySelectorAll('h1,h2,h3')].slice(0,80).map(e=>({tag:e.tagName,text:txt(e)})),
    controls,images,links,backgrounds,tables,counts:{controls:controls.length,images:document.images.length,
    links:document.querySelectorAll('a[href]').length,tables:document.querySelectorAll('table').length}};
}"""


def summarize_inventory(data: dict[str, Any]) -> dict[str, Any]:
    """Compact result; full inventory is stored in a separate artifact."""
    counts = data.get("counts") or {}
    types: dict[str, int] = {}
    for item in data.get("controls", []):
        kind = str(item.get("kind", "other"))
        types[kind] = types.get(kind, 0) + 1
    return {"counts": counts, "control_types": types, "headings": (data.get("headings") or [])[:30]}


def safe_action(control: dict[str, Any]) -> tuple[str, str] | None:
    """Explicit allow-list: no form submits, account buttons, or arbitrary anchors."""
    kind = control.get("kind")
    label = str(control.get("label") or "").strip().lower()
    if any(word in label for word in _BLOCKED_WORDS):
        return None
    tag = control.get("tag")
    # Never submit a form, including implicit HTML button submit types.
    if control.get("form_method", "").lower() == "post":
        return None
    if tag == "button" and control.get("form_method") and control.get("button_type") == "submit":
        return None
    if kind == "select":
        options = control.get("options") or []
        # Do not select from huge/unknown lists or options with an empty value.
        choices = [o for o in options[1:] if not o.get("disabled") and str(o.get("value") or "").strip()]
        if choices:
            return ("select", str(choices[0]["value"]))
    if kind in ("tab", "accordion", "gallery", "view", "dropdown") and tag in ("button", "summary", "a"):
        if tag == "a":
            href = control.get("href")
            current = control.get("page_url")
            if not isinstance(href, str) or not isinstance(current, str):
                return None
            # Only same-document anchors: do not follow other URLs/GET actions.
            if not is_allowed_url(href) or urlsplit(href)._replace(fragment="") != urlsplit(current)._replace(fragment=""):
                return None
            if not ("#" in href):
                return None
        return ("click", "")
    return None


def pick_actions(controls: list[dict[str, Any]], max_actions: int) -> list[dict[str, Any]]:
    """Sample distinct safe interactive controls, at most one native select."""
    if max_actions <= 0:
        return []
    picks: list[dict[str, Any]] = []
    seen_kinds: dict[str, int] = {}
    for control in controls:
        action = safe_action(control)
        if action is None:
            continue
        kind = str(control["kind"])
        per_kind_limit = 1 if kind == "select" else 3
        if seen_kinds.get(kind, 0) >= per_kind_limit:
            continue
        item = {"id": control["id"], "kind": kind, "label": control.get("label"),
                "action": action[0], "value": action[1]}
        picks.append(item)
        seen_kinds[kind] = seen_kinds.get(kind, 0) + 1
        if len(picks) >= max_actions:
            break
    return picks


def _redact_inventory_urls(inventory: dict[str, Any]) -> dict[str, Any]:
    for key in ("url",):
        if isinstance(inventory.get(key), str):
            inventory[key] = redact_url(inventory[key])
    for bucket in ("controls", "links"):
        for item in inventory.get(bucket, []):
            for key in ("href", "url"):
                if isinstance(item.get(key), str):
                    item[key] = redact_url(item[key])
    return inventory


def headless_probe(name: str, url: str, base_dir: Path, args: argparse.Namespace, browser: Any) -> dict[str, Any]:
    """One fresh isolated browser context per URL, no persistent auth cookies."""
    result: dict[str, Any] = {"target": name, "requested_url": redact_url(url), "mode": "headless",
                              "actions": [], "network": []}
    started = time.monotonic()
    context = None
    try:
        context = browser.new_context(locale="es-ES", viewport={"width": 1360, "height": 900},
                                      accept_downloads=False)
        page = context.new_page()
        # Lightweight network *metadata* only; never record cookies, request bodies or auth headers.
        def record_response(response: Any) -> None:
            try:
                if len(result["network"]) >= MAX_NETWORK_EVENTS:
                    return
                rurl = response.url
                if not is_allowed_url(rurl):
                    return
                req = response.request
                if req.resource_type not in ("xhr", "fetch"):
                    return
                result["network"].append({"url": redact_url(rurl),
                                          "status": response.status,
                                          "resource_type": req.resource_type,
                                          "content_type": response.headers.get("content-type", "")[:100]})
            except Exception:
                pass
        page.on("response", record_response)
        response = page.goto(url, wait_until="domcontentloaded", timeout=args.timeout_ms)
        page.wait_for_timeout(args.settle_ms)
        status = response.status if response else None
        html = page.content()
        title = page.title()
        verdict = classify_response(status, html, title)
        result.update({"status_code": status, "final_url": redact_url(page.url),
                       "verdict": verdict, "evidence": write_text(base_dir / "rendered_initial.html", html),
                       "dom": summarize_html(html)})
        if args.screenshots:
            try:
                page.screenshot(path=str(base_dir / "initial.png"), full_page=False, timeout=5_000)
            except Exception as e:
                result["screenshot_error"] = str(e)[:250]
        if verdict != "CONTENT_RECEIVED" or not is_allowed_url(page.url):
            result["actions_skipped"] = "no_valid_content_or_off_origin"
            return result

        inventory = _redact_inventory_urls(page.evaluate(DOM_INVENTORY_JS))
        write_json(base_dir / "inventory_initial.json", inventory)
        result["inventory_summary"] = summarize_inventory(inventory)
        actions = pick_actions(inventory.get("controls") or [], args.max_actions)
        html_baseline = page.content()
        for i, action in enumerate(actions, 1):
            event: dict[str, Any] = {"index": i, "kind": action["kind"], "label": action["label"],
                                     "action": action["action"], "status": "SKIPPED"}
            try:
                selector = '[data-fdh-probe="' + action["id"] + '"]'
                loc = page.locator(selector)
                if loc.count() != 1 or not loc.is_visible():
                    event["reason"] = "control_disappeared"
                elif action["action"] == "select":
                    loc.select_option(value=action["value"], timeout=3_000)
                    event["status"] = "EXECUTED"
                else:
                    loc.click(timeout=3_000)
                    event["status"] = "EXECUTED"
                if event["status"] == "EXECUTED":
                    page.wait_for_timeout(args.settle_ms)
                    after = page.content()
                    event["url_after"] = redact_url(page.url)
                    event["page_verdict"] = classify_response(None if not is_allowed_url(page.url) else 200,
                                                                 after, page.title())
                    event["evidence"] = write_text(base_dir / f"after_action_{i:02d}.html", after)
                    event["dom"] = summarize_html(after)
                    event["changed_dom"] = sha256(after.encode("utf-8")).hexdigest() != sha256(html_baseline.encode("utf-8")).hexdigest()
                    if is_allowed_url(page.url) and event["page_verdict"] == "CONTENT_RECEIVED":
                        detail = _redact_inventory_urls(page.evaluate(DOM_INVENTORY_JS))
                        write_json(base_dir / f"inventory_after_{i:02d}.json", detail)
                        event["inventory_summary"] = summarize_inventory(detail)
                        html_baseline = page.content()
                    else:
                        event["stop_reason"] = "challenge_or_navigation_outside_scope"
                        result["actions"].append(event)
                        break
            except Exception as e:
                event.update({"status": "ERROR", "error": str(e)[:500]})
            result["actions"].append(event)
    except Exception as e:
        result.update({"verdict": "NAVIGATION_ERROR", "error": str(e)[:500]})
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        write_json(base_dir / "headless.json", result)
    return result


def parse_target(s: str) -> tuple[str, str]:
    if "=" in s and not s.startswith("https://"):
        name, url = s.split("=", 1)
    else:
        url = s
        name = re.sub(r"[^a-z0-9]+", "_", urlsplit(url).path.lower()).strip("_")[:52]
    name = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_")[:70]
    if not name or not is_allowed_url(url):
        raise argparse.ArgumentTypeError("La URL debe pertenecer a https://www.bdfutbol.com/")
    return name, url


def build_targets(args: argparse.Namespace) -> list[tuple[str, str]]:
    if args.url:
        raw = [parse_target(item) for item in args.url]
    else:
        raw = list(TARGETS.items())
    seen_names = set()
    targets = []
    for name, url in raw:
        if name in seen_names:
            raise ValueError(f"Nombre de target repetido: {name}")
        seen_names.add(name)
        targets.append((name, url))
    return targets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("http", "headless", "both"), default="both")
    parser.add_argument("--output", type=Path, default=Path("data/analysis/bdfutbol/headless_probe"))
    parser.add_argument("--url", action="append", help="URL BDFutbol (o NOMBRE=https://...). Repetible; omitir para 4 targets conocidos")
    parser.add_argument("--max-actions", type=int, default=6, help="Máximo de interacciones seguras por página")
    parser.add_argument("--settle-ms", type=int, default=500)
    parser.add_argument("--timeout-ms", type=int, default=25_000)
    parser.add_argument("--between-pages-seconds", type=float, default=2.0)
    parser.add_argument("--screenshots", action="store_true", help="Guardar screenshot de cada página inicial")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 <= args.max_actions <= 20 or not 0 <= args.settle_ms <= 10_000 or args.timeout_ms < 1_000 or args.between_pages_seconds < 0:
        raise SystemExit("Parámetros de tiempo o acciones fuera del rango seguro")
    try:
        targets = build_targets(args)
    except (argparse.ArgumentTypeError, ValueError) as e:
        raise SystemExit(str(e)) from e

    run_dir = args.output / utcstamp()
    run_dir.mkdir(parents=True, exist_ok=False)
    summary: dict[str, Any] = {"schema_version": 1, "started_at": datetime.now(timezone.utc).isoformat(),
                               "mode": args.mode, "headless": True,
                               "javascript": True, "target_count": len(targets), "targets": [],
                               "policy": "No CAPTCHA solving, stealth, proxies or mass crawling."}
    write_json(run_dir / "plan.json", {"targets": [{"name": name, "url": redact_url(url)} for name, url in targets],
                                      "settings": {"mode": args.mode, "max_actions": args.max_actions, "settle_ms": args.settle_ms}})
    browser = None
    playwright = None
    if args.mode in ("headless", "both"):
        try:
            from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=True)
        except Exception as e:
            if playwright is not None:
                playwright.stop()
            print(f"No se pudo iniciar Chromium headless: {e}", file=sys.stderr)
            print("Instalación habitual: .venv/bin/python -m playwright install chromium", file=sys.stderr)
            return 2
    try:
        for i, (name, url) in enumerate(targets, 1):
            folder = run_dir / name
            folder.mkdir(parents=True, exist_ok=True)
            print(f"[{i}/{len(targets)}] {name}:", flush=True)
            item: dict[str, Any] = {"name": name, "url": redact_url(url)}
            if args.mode in ("http", "both"):
                item["http"] = http_probe(name, url, folder, args.timeout_ms / 1000)
                print(f"  HTTP: {item['http']['verdict']}", flush=True)
            if browser is not None:
                item["headless"] = headless_probe(name, url, folder, args, browser)
                h = item["headless"]
                executed = sum(a.get("status") == "EXECUTED" for a in h.get("actions", []))
                print(f"  Headless: {h['verdict']} | controles probados: {executed}", flush=True)
            summary["targets"].append(item)
            write_json(run_dir / "summary.json", summary)
            if i < len(targets):
                time.sleep(args.between_pages_seconds)
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_json(run_dir / "summary.json", summary)
    print(f"Informe: {run_dir / 'summary.json'}")
    blocked = any(any(v.get("verdict") == "CHALLENGE_REQUIRED" for k, v in item.items() if k in ("http", "headless"))
                  for item in summary["targets"])
    if blocked:
        return 3
    # A completed probe with no readable result is a failure, not a success.
    readable = any(
        any(v.get("verdict") == "CONTENT_RECEIVED" for k, v in item.items() if k in ("http", "headless"))
        for item in summary["targets"]
    )
    return 0 if readable else 1


if __name__ == "__main__":
    raise SystemExit(main())
