#!/usr/bin/env python3
"""Build a read-only, searchable HTML dossier from hash-verified match drafts."""

from __future__ import annotations

import argparse
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from football_data_hub.providers.bdfutbol.match_details.campaign_operations import (
    build_review_queue,
)
from football_data_hub.providers.bdfutbol.match_details.operational_campaign import (
    OperationalMatchCampaignLedger,
)


def _e(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return html.escape(str(value), quote=True)


def _event_label(event: dict[str, Any]) -> str:
    kind = event.get("event_kind", "evento")
    labels = {
        "goal": "Gol",
        "penalty": "Gol de penalti",
        "own_goal": "Gol en propia puerta",
        "missed_penalty": "Penalti fallado",
        "yellow_card": "Amarilla",
        "red_card": "Expulsión",
        "second_yellow": "Segunda amarilla",
        "substitution_in": "Entró",
        "substitution_out": "Salió",
        "substitution": "Sustitución",
    }
    return str(event.get("source_description") or labels.get(kind, kind.replace("_", " ")))


def _player_line(player: dict[str, Any]) -> str:
    number = f"#{_e(player.get('shirt_number'))} " if player.get("shirt_number") is not None else ""
    name = _e(player.get("display_name"))
    events = player.get("events") or []
    event_text = ", ".join(
        f"{_e(_event_label(event))} {_e(event.get('minute'))}"
        for event in events
    )
    return f"<li>{number}{name}{f' <small>{event_text}</small>' if event_text else ''}</li>"


def _side_detail(side: dict[str, Any] | None, label: str) -> str:
    side = side or {}
    coach = side.get("coach") or {}
    starters = side.get("starters") or []
    substitutes = side.get("substitutes") or []
    coach_line = f"<p>Entrenador: {_e(coach.get('display_name'))}</p>" if coach else "<p>Entrenador: no publicado</p>"
    starter_list = "".join(_player_line(player) for player in starters) or "<li>Sin datos</li>"
    substitute_list = "".join(_player_line(player) for player in substitutes) or "<li>Sin datos</li>"
    return (
        f'<section class="side"><h4>{label}</h4>{coach_line}'
        f'<div class="rosters"><div><b>Titulares ({len(starters)})</b><ol>{starter_list}</ol></div>'
        f'<div><b>Suplentes ({len(substitutes)})</b><ol>{substitute_list}</ol></div></div></section>'
    )


def _record_card(row: dict[str, Any]) -> str:
    reference = row.get("reference_result") or {}
    observed = row.get("observed_result") or {}
    expected_score = f"{reference.get('home_goals', '—')}–{reference.get('away_goals', '—')}"
    observed_score = f"{observed.get('home_goals', '—')}–{observed.get('away_goals', '—')}"
    score_flag = "" if expected_score == observed_score else '<span class="flag">Resultado distinto al catálogo</span>'
    date_flag = "" if not row.get("match_date") or row.get("match_date") == row.get("source_match_date") else '<span class="flag">Fecha distinta al catálogo</span>'
    warnings = row.get("warnings") or []
    missing = row.get("missing_fields") or []
    anomalies = list(dict.fromkeys([*warnings, *(f"Campo ausente: {item}" for item in missing)]))
    anomaly_html = (
        "<ul>" + "".join(f"<li>{_e(item)}</li>" for item in anomalies) + "</ul>"
        if anomalies else '<p class="clear">Sin advertencias de validación registradas.</p>'
    )
    events = row.get("events") or []
    lineups = row.get("lineups") or {}
    coaches = row.get("coaches") or {}
    team_names = {
        row.get("home_team_id"): row.get("home_team_name"),
        row.get("away_team_id"): row.get("away_team_name"),
    }
    event_list = "".join(
        f"<li>{_e(event.get('minute'))} · {_e(_event_label(event))} · {_e(event.get('player_name'))} · {_e(team_names.get(event.get('team_id')) or event.get('team_id'))}</li>"
        for event in events
    ) or "<li>Eventos: no publicados</li>"
    return f'''<article class="match-card" data-group="{_e(row.get('group'))}" data-search="{_e(' '.join(str(row.get(k) or '') for k in ('source_match_id','home_team_name','away_team_name','group','matchday'))).lower()}">
  <header><div><span class="badge">Grupo {_e(row.get('group'))}</span> <span class="badge">Jornada {_e(row.get('matchday'))}</span> <span class="badge">Borrador validado</span>
    <h2>{_e(row.get('home_team_name'))} <span class="score">{_e(observed_score)}</span> {_e(row.get('away_team_name'))}</h2>
    <p>Partido { _e(row.get('source_match_id')) } · Fecha ficha: {_e(row.get('match_date') or row.get('source_match_date'))} · Hora {_e(row.get('kickoff_time_local'))} {score_flag} {date_flag}</p>
  </div><button type="button" aria-expanded="false">Ver ficha</button></header>
  <div class="details" hidden>
    <div class="summary"><b>Resultado catálogo:</b> {_e(expected_score)} · <b>Resultado ficha:</b> {_e(observed_score)} · <b>Estadio:</b> {_e(row.get('stadium_name'))} · <b>Árbitro:</b> {_e(row.get('referee_name'))} · <b>Fecha catálogo:</b> {_e(row.get('source_match_date'))}</div>
    <div class="sides">{_side_detail({**(lineups.get('home') or {}), 'coach': coaches.get('home')}, 'Local')}{_side_detail({**(lineups.get('away') or {}), 'coach': coaches.get('away')}, 'Visitante')}</div>
    <section><h3>Eventos</h3><ol class="events">{event_list}</ol></section>
    <section class="anomalies"><h3>Advertencias y campos incompletos</h3>{anomaly_html}</section>
    <details class="hashes"><summary>Procedencia e integridad</summary><dl>
      <dt>Campaña</dt><dd>{_e(row.get('campaign_id'))}</dd>
      <dt>ID interno</dt><dd>{_e(row.get('internal_id'))}</dd>
      <dt>HTML SHA-256</dt><dd><code>{_e(row.get('source_html_sha256'))}</code></dd>
      <dt>Documento SHA-256</dt><dd><code>{_e(row.get('details_sha256'))}</code></dd>
      <dt>Borrador SHA-256</dt><dd><code>{_e(row.get('draft_sha256'))}</code></dd>
      <dt>Archivo de borrador</dt><dd><code>{_e(row.get('draft_path'))}</code></dd>
    </dl></details>
  </div>
</article>'''


def render_review_html(rows: list[dict[str, Any]]) -> str:
    cards = "\n".join(_record_card(row) for row in rows)
    return f'''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Revisión local de borradores de partidos</title>
<style>
  :root{{color-scheme:dark;font:15px/1.45 system-ui,sans-serif;background:#111316;color:#edf0f2}}
  *{{box-sizing:border-box}}body{{margin:0 auto;max-width:1200px;padding:24px}}
  h1{{font-size:1.5rem;margin:0 0 6px}}h2{{font-size:1.2rem;margin:10px 0 4px}}h3{{font-size:1rem}}
  .notice{{color:#cbd0d5;margin:0 0 18px}}.toolbar{{position:sticky;top:0;background:#111316ee;padding:12px 0;display:flex;gap:8px;z-index:2}}
  input,select,button{{background:#24282d;color:inherit;border:1px solid #42474e;border-radius:7px;padding:9px 12px}}input{{flex:1}}
  .match-card{{background:#1b1e22;border:1px solid #30343a;border-radius:12px;margin:12px 0;overflow:hidden}}
  .match-card>header{{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:16px}}
  .match-card p{{margin:4px 0;color:#b8bec5}}.badge{{font-size:.75rem;color:#d8c4ed;background:#392a49;border-radius:99px;padding:3px 8px}}
  .score{{color:#ad86d3;font-variant-numeric:tabular-nums}}.details{{border-top:1px solid #30343a;padding:16px}}
  .summary{{padding:10px;background:#24282d;border-radius:8px}}.sides{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}}
  .side{{background:#202328;border:1px solid #30343a;border-radius:8px;padding:12px}}.rosters{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
  ol{{padding-left:22px}}li{{margin:3px 0}}small{{color:#b9c0c8}}section{{margin-top:15px}}.anomalies{{color:#e5c59c}}
  .clear{{color:#97c6a3}}.flag{{color:#f0ba7a}}.hashes{{color:#bfc6ce}}dl{{display:grid;grid-template-columns:max-content 1fr;gap:4px 12px;overflow-wrap:anywhere}}dd{{margin:0}}
  @media(max-width:700px){{body{{padding:12px}}.sides,.rosters{{grid-template-columns:1fr}}.match-card>header{{align-items:flex-start}}.toolbar{{flex-wrap:wrap}}input{{min-width:100%}}}}
</style><body><h1>Revisión local de borradores de partidos</h1>
<p class="notice">{len(rows)} borradores con hashes verificados. Vista de solo lectura: aquí no se aprueba ni se publica ningún partido.</p>
<div class="toolbar"><input id="search" type="search" placeholder="Buscar equipo, partido o jornada"><select id="group"><option value="">Ambos grupos</option><option>I</option><option>II</option></select></div>
<main id="cards">{cards}</main>
<script>
const search=document.querySelector('#search'), group=document.querySelector('#group');
function filter(){{const q=search.value.toLowerCase();document.querySelectorAll('.match-card').forEach(card=>{{card.hidden=!(card.dataset.search.includes(q)&&(!group.value||card.dataset.group===group.value));}})}}
search.addEventListener('input',filter);group.addEventListener('change',filter);
document.querySelectorAll('.match-card>header button').forEach(button=>button.addEventListener('click',()=>{{const box=button.closest('.match-card').querySelector('.details');const opening=box.hidden;box.hidden=!opening;button.setAttribute('aria-expanded',String(opening));button.textContent=opening?'Ocultar ficha':'Ver ficha';}}));
</script></body></html>'''


def main() -> int:
    default_root = Path(os.getenv("FDH_LOCAL_DATA_ROOT", Path.home() / "FootballDataHub-data")).expanduser()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=default_root)
    parser.add_argument("--campaign-id", required=True, help="Campaña principal con borradores revisables")
    parser.add_argument("--include-campaign", action="append", default=[], help="Añade otra campaña, por ejemplo la del partido 269409")
    parser.add_argument("--output-dir", type=Path, help="Directorio externo para el HTML inmutable")
    args = parser.parse_args()

    data_root = args.data_root.expanduser().resolve(strict=True)
    store_root = data_root / "matches" / "details"
    ledger = OperationalMatchCampaignLedger(store_root / "campaigns")
    campaign_ids = [args.campaign_id, *args.include_campaign]
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for campaign_id in campaign_ids:
        for row in build_review_queue(ledger, campaign_id, data_root):
            key = (campaign_id, row["internal_id"])
            if key in seen:
                raise SystemExit(f"Entrada duplicada en la cola: {key}")
            seen.add(key)
            rows.append({"campaign_id": campaign_id, **row})
    rows.sort(key=lambda row: (row.get("group", ""), row.get("matchday") or 0, row.get("source_match_date") or "", row.get("source_match_id", "")))

    output_dir = args.output_dir or store_root / "review" / "human"
    output_dir = output_dir.expanduser().absolute()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = output_dir / f"match-review-{stamp}.html"
    raw = render_review_html(rows).encode("utf-8")
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": "CREATED_READ_ONLY_REVIEW", "count": len(rows), "path": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
