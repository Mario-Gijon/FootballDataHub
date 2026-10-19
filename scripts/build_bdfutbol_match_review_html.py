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
from football_data_hub.providers.bdfutbol.match_details.campaign_artifact import (
    parse_campaign_saved_artifact,
)
from football_data_hub.providers.bdfutbol.match_details.inventory import (
    build_match_detail_inventory,
    load_verified_match_generation,
)
from football_data_hub.providers.bdfutbol.match_details.operational_campaign import (
    OperationalMatchCampaignLedger,
)

_ADMINISTRATIVE_WARNING = "campaign_discovery_remains_unpromoted_pending_independent_review"
_PAGE_SIZE = 15


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


def _review_anomalies(row: dict[str, Any]) -> list[str]:
    warnings = [
        warning for warning in (row.get("warnings") or [])
        if warning != _ADMINISTRATIVE_WARNING
    ]
    reference = row.get("reference_result") or {}
    observed = row.get("observed_result") or {}
    if (reference.get("home_goals"), reference.get("away_goals")) != (
        observed.get("home_goals"), observed.get("away_goals")
    ):
        warnings.append("El marcador de la ficha no coincide con el catálogo de partidos")
    if row.get("match_date") and row.get("source_match_date") and row["match_date"] != row["source_match_date"]:
        warnings.append("La fecha de la ficha no coincide con la fecha del catálogo")
    source_context = row.get("source_context") or {}
    for key, label in (("stadium_name", "estadio"), ("referee_name", "árbitro")):
        if source_context.get(key) is None:
            warnings.append(f"El HTML fuente no publica un {label} identificable")
    missing = [field for field in (row.get("missing_fields") or []) if field != "kickoff_time_local"]
    warnings.extend(f"Campo ausente: {field}" for field in missing)
    return list(dict.fromkeys(warnings))


def _record_card(row: dict[str, Any], review_code: str) -> str:
    reference = row.get("reference_result") or {}
    observed = row.get("observed_result") or {}
    expected_score = f"{reference.get('home_goals', '—')}–{reference.get('away_goals', '—')}"
    observed_score = f"{observed.get('home_goals', '—')}–{observed.get('away_goals', '—')}"
    score_flag = "" if expected_score == observed_score else '<span class="flag">Resultado distinto al catálogo</span>'
    date_flag = "" if not row.get("match_date") or row.get("match_date") == row.get("source_match_date") else '<span class="flag">Fecha distinta al catálogo</span>'
    source_context = row.get("source_context") or {}
    anomalies = _review_anomalies(row)
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
    source_kickoff = source_context.get("kickoff_time_local")
    context_notes = []
    if not source_kickoff:
        context_notes.append("Hora local no observada en el HTML fuente")
    if _ADMINISTRATIVE_WARNING in (row.get("warnings") or []):
        context_notes.append("Descubrimiento pendiente de revisión independiente (estado de campaña)")
    category = "flagged" if anomalies else "clean"
    return f'''<article class="match-card" data-category="{category}" data-group="{_e(row.get('group'))}" data-search="{_e(' '.join(str(row.get(k) or '') for k in ('source_match_id','home_team_name','away_team_name','group','matchday'))).lower()}">
  <header><div><span class="seq">{_e(review_code)}</span> <span class="badge">Grupo {_e(row.get('group'))}</span> <span class="badge">Jornada {_e(row.get('matchday'))}</span> <span class="badge">Borrador validado</span>
    <h2>{_e(row.get('home_team_name'))} <span class="score">{_e(observed_score)}</span> {_e(row.get('away_team_name'))}</h2>
    <p>Partido { _e(row.get('source_match_id')) } · Fecha: {_e(row.get('match_date') or row.get('source_match_date'))} · Hora {_e(source_kickoff or 'no observada')} {score_flag} {date_flag}</p>
  </div><button type="button" aria-expanded="false">Ver ficha</button></header>
  <div class="details" hidden>
    <div class="summary"><b>Resultado catálogo:</b> {_e(expected_score)} · <b>Resultado ficha:</b> {_e(observed_score)} · <b>Estadio:</b> {_e(source_context.get('stadium_name'))} · <b>Árbitro:</b> {_e(source_context.get('referee_name'))} · <b>Fecha catálogo:</b> {_e(row.get('source_match_date'))}</div>
    <p class="source-links"><b>Referencias verificadas:</b> {_source_link(source_context.get('stadium_url'), source_context.get('stadium_name'))} · {_source_link(source_context.get('referee_url'), source_context.get('referee_name'))}</p>
    <div class="sides">{_side_detail({**(lineups.get('home') or {}), 'coach': coaches.get('home')}, 'Local')}{_side_detail({**(lineups.get('away') or {}), 'coach': coaches.get('away')}, 'Visitante')}</div>
    <section><h3>Eventos</h3><ol class="events">{event_list}</ol></section>
    <section class="anomalies"><h3>Advertencias de contenido</h3>{anomaly_html}</section>
    <section class="context-notes"><h3>Notas comunes de captura</h3><ul>{''.join(f'<li>{_e(note)}</li>' for note in context_notes) or '<li>Sin notas adicionales.</li>'}</ul></section>
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


def _source_link(url: Any, label: Any) -> str:
    if not isinstance(url, str) or not url.startswith("https://www.bdfutbol.com/"):
        return _e(label)
    return f'<a href="{_e(url)}" target="_blank" rel="noreferrer">{_e(label)}</a>'


def _verified_source_context(observation: Any) -> dict[str, Any]:
    """Project source-only metadata after rechecking the immutable HTML artifact."""

    values = {}
    for field in ("stadium_name", "stadium_id", "stadium_url", "referee_name", "referee_id", "referee_url"):
        value = getattr(observation, field)
        values[field] = value.value if value.state == "observed" else None
    kickoff = observation.kickoff_time_local
    values.update({
        "kickoff_time_local": kickoff.value if kickoff.state == "observed" else None,
        "kickoff_state": kickoff.state,
        "kickoff_source_text": kickoff.raw_value,
        "parser_version": observation.source.parser_version,
    })
    return values


def _verify_source_context(
    rows: list[dict[str, Any]],
    ledger: OperationalMatchCampaignLedger,
    data_root: Path,
) -> None:
    """Verify generation and every source HTML before showing its metadata."""

    generations: dict[str, tuple[Any, dict[str, dict[str, Any]]]] = {}
    for row in rows:
        campaign_id = row["campaign_id"]
        if campaign_id not in generations:
            preflight = ledger.preflight(campaign_id)
            generation_id = preflight["source_generation_id"]
            generation = load_verified_match_generation(
                data_root / "matches" / "generations" / generation_id,
                data_root=data_root,
            )
            matches = {
                match["internal_id"]: match
                for match in build_match_detail_inventory(generation)["matches"]
            }
            generations[campaign_id] = (generation, matches)
        generation, matches = generations[campaign_id]
        expected = matches.get(row["internal_id"])
        if expected is None:
            raise ValueError(f"{row['internal_id']} no existe en la generación verificada")
        observation = parse_campaign_saved_artifact(
            Path(row["artifact_manifest_path"]).parent,
            expected_match=expected,
            verified_generation=generation,
            data_root=data_root,
        )
        if observation.source.source_html_sha256 != row["source_html_sha256"]:
            raise ValueError(f"El HTML de {row['internal_id']} no coincide con la cola hash-verificada")
        row["source_context"] = _verified_source_context(observation)


def render_review_html(rows: list[dict[str, Any]]) -> str:
    clean_index = 0
    flagged_index = 0
    cards_list = []
    for row in rows:
        if _review_anomalies(row):
            flagged_index += 1
            review_code = f"A-{flagged_index:03d}"
        else:
            clean_index += 1
            review_code = f"L-{clean_index:03d}"
        cards_list.append(_record_card(row, review_code))
    cards = "\n".join(cards_list)
    clean_count = clean_index
    flagged_count = flagged_index
    kickoff_observed_count = sum(
        bool((row.get("source_context") or {}).get("kickoff_time_local"))
        for row in rows
    )
    kickoff_missing_count = len(rows) - kickoff_observed_count
    return f'''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Revisión local de borradores de partidos</title>
<style>
  :root{{color-scheme:dark;font:15px/1.45 system-ui,sans-serif;background:#111316;color:#edf0f2}}
  *{{box-sizing:border-box}}body{{margin:0 auto;max-width:1200px;padding:24px}}
  h1{{font-size:1.5rem;margin:0 0 6px}}h2{{font-size:1.2rem;margin:10px 0 4px}}h3{{font-size:1rem}}
  .notice{{color:#cbd0d5;margin:0 0 18px}}.toolbar{{position:sticky;top:0;background:#111316ee;padding:12px 0;display:flex;gap:8px;z-index:2;flex-wrap:wrap}}
  input,select,button{{background:#24282d;color:inherit;border:1px solid #42474e;border-radius:7px;padding:9px 12px}}input{{flex:1}}
  .match-card{{background:#1b1e22;border:1px solid #30343a;border-radius:12px;margin:12px 0;overflow:hidden}}
  .match-card>header{{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:16px}}
  .match-card p{{margin:4px 0;color:#b8bec5}}.badge{{font-size:.75rem;color:#d8c4ed;background:#392a49;border-radius:99px;padding:3px 8px}}
  .score{{color:#ad86d3;font-variant-numeric:tabular-nums}}.details{{border-top:1px solid #30343a;padding:16px}}
  .seq{{font-size:.78rem;color:#fff;background:#363b42;border-radius:6px;padding:3px 7px;font-variant-numeric:tabular-nums}}
  .summary{{padding:10px;background:#24282d;border-radius:8px}}.sides{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}}
  .side{{background:#202328;border:1px solid #30343a;border-radius:8px;padding:12px}}.rosters{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
  ol{{padding-left:22px}}li{{margin:3px 0}}small{{color:#b9c0c8}}section{{margin-top:15px}}.anomalies{{color:#e5c59c}}
  .clear{{color:#97c6a3}}.flag{{color:#f0ba7a}}.hashes{{color:#bfc6ce}}.source-links a{{color:#c7a5e9}}
  .context-notes{{color:#c1c7ce}}.pagination{{display:flex;align-items:center;gap:8px;padding:8px 0}}#page-status,#page-status-bottom{{min-width:115px;text-align:center}}
  .counter{{color:#aeb5bd}}#cards{{min-height:20vh}}dl{{display:grid;grid-template-columns:max-content 1fr;gap:4px 12px;overflow-wrap:anywhere}}dd{{margin:0}}
  @media(max-width:700px){{body{{padding:12px}}.sides,.rosters{{grid-template-columns:1fr}}.match-card>header{{align-items:flex-start}}input{{min-width:100%}}}}
</style><body><h1>Revisión local de borradores de partidos</h1>
<p class="notice">{len(rows)} borradores con fuente y generación verificadas. <b>{clean_count}</b> sin discrepancias deportivas específicas; <b>{flagged_count}</b> con advertencias que requieren atención. Hora de inicio verificada en el HTML fuente: {kickoff_observed_count} de {len(rows)}; no observada en {kickoff_missing_count}. Se muestra por partido cuando está verificada. Vista solo de lectura: no aprueba ni publica.</p>
<div class="toolbar"><select id="category"><option value="clean">Sin discrepancias ({clean_count})</option><option value="flagged">Con advertencias ({flagged_count})</option></select><select id="group"><option value="">Ambos grupos</option><option>I</option><option>II</option></select><input id="search" type="search" placeholder="Buscar equipo, partido o jornada"></div>
<p class="counter" id="batch-status">Bloques de hasta {_PAGE_SIZE} fichas por categoría.</p>
<div class="pagination"><button id="previous" type="button">Anterior</button><span id="page-status"></span><button id="next" type="button">Siguiente</button></div>
<main id="cards">{cards}</main>
<div class="pagination"><button id="previous-bottom" type="button">Anterior</button><span id="page-status-bottom"></span><button id="next-bottom" type="button">Siguiente</button></div>
<script>
const search=document.querySelector('#search'), group=document.querySelector('#group'), category=document.querySelector('#category');
const cards=[...document.querySelectorAll('.match-card')], pageSize={_PAGE_SIZE}; let page=0;
function filter(){{const q=search.value.toLowerCase();const visible=cards.filter(card=>card.dataset.category===category.value&&(!group.value||card.dataset.group===group.value)&&card.dataset.search.includes(q));const pages=Math.max(1,Math.ceil(visible.length/pageSize));page=Math.min(page,pages-1);cards.forEach(card=>card.hidden=true);visible.slice(page*pageSize,(page+1)*pageSize).forEach(card=>card.hidden=false);const text='Bloque '+(visible.length?Math.floor(page/pageSize)+1:0)+' de '+pages+' · '+visible.length+' fichas en este filtro';document.querySelector('#batch-status').textContent=text;document.querySelector('#page-status').textContent=(page+1)+' / '+pages;document.querySelector('#page-status-bottom').textContent=(page+1)+' / '+pages;document.querySelectorAll('#previous,#previous-bottom').forEach(button=>button.disabled=page===0);document.querySelectorAll('#next,#next-bottom').forEach(button=>button.disabled=page>=pages-1);}}
function changePage(delta){{page+=delta;filter();window.scrollTo({{top:0,behavior:'smooth'}});}}
search.addEventListener('input',()=>{{page=0;filter();}});group.addEventListener('change',()=>{{page=0;filter();}});category.addEventListener('change',()=>{{page=0;filter();}});
document.querySelectorAll('#previous,#previous-bottom').forEach(button=>button.addEventListener('click',()=>changePage(-1)));
document.querySelectorAll('#next,#next-bottom').forEach(button=>button.addEventListener('click',()=>changePage(1)));
document.querySelectorAll('.match-card>header button').forEach(button=>button.addEventListener('click',()=>{{const box=button.closest('.match-card').querySelector('.details');const opening=box.hidden;box.hidden=!opening;button.setAttribute('aria-expanded',String(opening));button.textContent=opening?'Ocultar ficha':'Ver ficha';}}));
filter();
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
    _verify_source_context(rows, ledger, data_root)

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
