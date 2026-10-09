# Hito 1D-C2 — Consolidación de partidos históricos

**Rama:** `rebuild/football-data-hub-v2` · **Modo:** offline · **Estado:** completado, con selección automática de competición en revisión explícita.

## Alcance

Se consolidaron las observaciones `P` ya guardadas en las 40 páginas canónicas de clubes. No hubo navegación ni peticiones de red. Se conservaron los snapshots raw y los exports previos; no se modificaron Dev Explorer ni el scraper de jugadores. El export final es inmutable, compacto y versionado con parser `1.7.0` y contrato deportivo `football_data_hub.bdfutbol.club_team_sports.v3`.

## Selección de la extracción de competición

El contexto de C1 describía que la extracción más reciente podía mostrar cero partidos jugados. El reanálisis correcto de los exports de Hito 1B demuestra que ambas fuentes contienen **119 partidos disputados**: Grupo I tiene 60 y Grupo II 59. El recuento debe usar el estado normalizado (`assess_match_status`), porque las etiquetas raw de la extracción posterior son `available`/`not_available` junto con `fixture_status`, y no siempre contienen literalmente `played`.

| Extracción | Captura I / II UTC | Grupo I | Grupo II |
|---|---|---:|---:|
| `044edc9b2ef3c6026c7f` | 12:10:34 / 12:10:36 | 60 disputados, 320 programados | 59 disputados, 321 programados |
| `d047191aa847be5c30d7` | 12:39:55 / 12:39:57 | 60 disputados, 320 programados | 59 disputados, 320 programados, 1 sin resolver |

La primera comparación de C2 solo alineaba filas con `match_id`. Eso probaba los 119 partidos disputados, pero ignoraba fixtures sin ID publicado. Se corrigió el alineamiento: usa grupo, temporada e IDs de los equipos-temporada local y visitante como identidad estable; compara el ID del partido, fecha, jornada, equipos, marcador, árbitro, estadio y estado normalizado. Así compara los **760 fixtures** de cada export, incluidos los no disputados.

Se confirmó una diferencia sin ID de partido: **Grupo II, FC Cartagena–Murcia, 27/09/2026, jornada 5**. El export `044…` lo clasifica como `scheduled`; `d047…` como `unresolved`. Sus demás campos comparables coinciden. Las capturas de clubes corroboran 119 partidos disputados en ambas extracciones, pero esa evidencia no decide el estado de este fixture no disputado. Por tanto la selección automática queda en `AMBIGUOUS_VALID_SOURCES`, sin fuente de competición seleccionada. No se usa la recencia para ocultar el conflicto.

La metadata conserva las dos candidatas, grupos, timestamps, hashes, diferencias y corroboración. `--competition-extraction-key` sigue disponible para una elección explícita. En tal caso el export identifica la decisión manual y conserva el conflicto para auditoría.

## Contrato de identidad y observaciones

Se mantienen separados:

- `embedded_match_observations`: las 52.904 filas originales, incluida cada observación duplicada entre dos clubes, la tupla raw de 19 posiciones, índice, club fuente, URL, timestamp y SHA-256.
- `matches_from_embedded_data`: 47.449 IDs únicos. Las 5.455 observaciones compartidas entre clubes se mantienen como fuentes del mismo partido y no se eliminan ni fusionan entre capturas.
- `matches_played`: partidos leídos de tablas de encuentros; es una vista separada y no se reconstruye a partir de totales ni de filas `P`.

`home_club_id`/`away_club_id` describen clubes permanentes. La temporada raw pertenece al encuentro. Los `team_season_id` de las capturas están bajo `acquisition_context`, no como identidad histórica del partido. Como no hay una fuente de competición automáticamente seleccionada, los 47.449 partidos del export llevan `team_season_identity_status=NOT_ESTABLISHED`; no se asignan IDs históricos ni se afirma una identidad de equipo-temporada actual sin cruce validado.

Cuando no hay una fuente de competición elegida, el nuevo contrato no convierte “no comparado” en “ausente”: `embedded_match_competition_crosscheck.status` es `NOT_RUN_NO_SELECTED_COMPETITION_SOURCE`; los conjuntos de IDs y contadores esperados de competición quedan `null`, y no se emiten diferencias. En `matches_played`, `competition_match_present` queda `null` y `competition_match_status=NOT_CHECKED_NO_SELECTED_SOURCE`. Una fuente elegida produce el cotejo normal o diferencias explícitas.

## Contrastes y datos conservados

- Las dos candidatas válidas comparan **MATCHED 119/119** frente a los partidos disputados observados en `P`, con procedencia por snapshot. Esta corroboración no desempata el estado de un fixture no disputado.
- El export final, al no seleccionar fuente automáticamente, conserva los **119 IDs únicos de 2026/27 1rf observados en `P`**, pero declara el cotejo con competición como no ejecutado; no declara que falten allí.
- Las variantes de tabla capturadas permiten contrastar tarjetas: **102 comparaciones, 102 coincidentes, 0 distintas y 136 no capturadas**. No se infieren las variantes ausentes.
- Se preservan los tres desacuerdos raw entre código de resultado y signo del marcador: `150715`/`e48` (raw `1`, resultado del marcador `-1`), `501020`/`e18` (raw `-1`, resultado del marcador `0`) y `150730`/`e119` (raw `1`, resultado del marcador `-1`). No se reescribieron.
- El historial observado cubre **109 temporadas**, de 1916-17 a 2026-27. Son 1.034 jugadores únicos y 1.039 pertenencias jugador/equipo-temporada en los datos de clubes; no se presentan como cobertura histórica completa.

El cotejo de IDs, fecha, temporada, competición, clubes/equipos, marcador, árbitro y jornada sigue conservando valores y referencias de ambos lados cuando existe una selección. Árbitro solo se compara si ambas fuentes tienen ID; jornada solo cuando su representación es verificable. No se inventan valores para ausencias.

## Recomendación de integración

Los consumidores deben leer `embedded_match_observations` como evidencia de cada fila fuente y `matches_from_embedded_data` como índice de IDs únicos; `matches_played` representa el subconjunto que procede de tablas de encuentros. La cobertura histórica observada y el estado del cotejo con competición deben mostrarse por separado. Mientras la selección sea ambigua, no inferir que los IDs `P` están ausentes de la competición ni completar `team_season_id` históricos. Una elección explícita posterior habilitará el cotejo versionado y dejará su extracción identificada en metadata.

## Export final y reproducción

El export final está en:

`data/parsed/bdfutbol/club_team_2026_27/compact/snapshot-7ffcbd5f11c8e83fdae4-parser-1.7.0/`

Tiene 555 archivos gzip, 103.174.787 bytes. La cobertura registra 480/480 vistas capturadas; los estados de pipeline contienen 240 `PARSED` y 240 `VALIDATED`. Hay 29 variantes observadas (28 completas), 40 páginas canónicas de clubes, 52.904 observaciones `P`, 47.449 IDs únicos, 5.455 duplicados compartidos y 109 temporadas.

La corrección de C2 no alteró el parser de páginas de clubes. En el reprocesamiento offline 1.6.0 se validaron y parsearon las 509 capturas locales (480 vistas base y 29 variantes). Para producir la salida final se reutilizaron esos objetos parseados y se regeneró la consolidación deportiva con el contrato 1.7.0. Los objetos de página conservan su `parser_version=1.6.0`; la versión global 1.7.0 identifica el nuevo contrato de consolidación. El comando habitual de reprocesamiento desde raw sigue siendo:

```bash
PYTHONPATH=src:scripts .venv/bin/python - <<'PY'
import json
from pathlib import Path
from scrape_bdfutbol_club_team import parse_args, run

root = Path("data/parsed/bdfutbol/primera_federacion_2026_27/")
root /= "snapshot-044edc9b2ef3c6026c7f-parser-1.0.0"
participants = json.loads((root / "participants.json").read_text())["items"]
arguments = ["offline", "--compact-export"]
for item in participants:
    arguments.extend(["--team-id", item["team_season_id"]])
raise SystemExit(run(parse_args(arguments)))
PY
```

Para fijar manualmente una candidata, añadir `--competition-extraction-key <extraction_key>` a `arguments`. En automático, la situación actual genera `AMBIGUOUS_VALID_SOURCES` y deja el cotejo sin ejecutar hasta que haya evidencia que resuelva el fixture pendiente.

## Límites

La evidencia de `P` y las tablas filtradas proviene de otras páginas capturadas de BDFutbol, no de un proveedor editorial independiente. Las variantes de tarjetas y tablas históricas siguen limitadas a lo archivado. La selección automática no establece cuál clasificación del fixture del 27/09/2026 representa mejor la fuente; se conserva como conflicto para una decisión posterior. El dataset describe las capturas locales, no garantiza cobertura completa de BDFutbol.

## Validación

- Reprocesamiento offline: se validaron y parsearon 509 capturas locales (480 vistas base y 29 variantes); no hubo navegación ni peticiones HTTP.
- Suite completa: **261 passed** en 29,32 s. La prueba de loopback local se ejecutó con permiso de socket local; no se hicieron conexiones externas.
- Ruff en los módulos y pruebas relacionados: **All checks passed**.
- `git diff --check`: correcto.
- Se retiraron solo dos exports intermedios 1.6.0 creados durante este hito y comprobados como obsoletos. El export C1 1.5.0 y los snapshots raw permanecen.
- No hubo commit ni push.
