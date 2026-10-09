# Hito 1D-C1 — Partidos embebidos en páginas de clubes

**Rama:** `rebuild/football-data-hub-v2` · **Modo:** offline · **Estado:** `PARSED_AND_CROSSCHECKED`

## Resultado

Las 40 capturas canónicas `club_matches` contienen una asignación JavaScript `P` con registros individuales de partidos. Es una estructura distinta de las tuplas de 27 posiciones de las páginas de jugador: en los HTML de clubes revisados cada fila tiene 19 posiciones.

El parser existente ahora conserva cada tupla raw, emite observaciones con procedencia y genera un conjunto separado de partidos únicos por ID. El export nuevo incluye todas las observaciones de los 40 clubes, de 109 temporadas entre 1916/17 y 2026/27. No se cambió la interpretación de las variantes filtradas existentes ni se reconstruyeron partidos desde agregados.

| Medida | Resultado |
|---|---:|
| Páginas canónicas verificadas | 40/40 |
| Tuplas raw, 19 posiciones | 52.904 |
| Observaciones sin ID | 0 |
| IDs únicos entre los 40 clubes | 47.449 |
| Partidos compartidos por dos páginas | 5.455 |
| Conflictos entre observaciones duplicadas | 0 |
| Temporadas distintas | 109 |
| Observaciones `1rf`, 2026/27 | 238 |
| Partidos únicos `1rf`, 2026/27 | 119 |
| Comparación de esos 119 con Hito 1B | 119/119 coinciden en los campos comprobados |

La captura de 17 variantes `all` de Hito 1D-B2 contenía 68 partidos únicos. `P` recupera los otros 51 IDs de la competición disputada de 2026/27. Para cada uno de los 17 clubes con variante `all`, la matriz `P` de esa variante fue idéntica a la matriz de su página canónica.

## Estructura y semántica comprobada

La fuente está serializada dentro de un `<script>` de `rendered.html` como `P=[[...]]`. Las 40 páginas tienen una asignación interpretable, el mismo ancho de 19 posiciones y valores escalares JSON. No se necesita una navegación ni una petición adicional para recuperar estas filas.

| Posición | Uso conservado | Evidencia y alcance |
|---:|---|---|
| 0 | Año inicial de temporada, raw | Concuerda con `P[18]` en 52.904/52.904 tuplas. |
| 1 | Código de competición, raw | Se conserva el código sin traducirlo. |
| 2 | Raw sin interpretar | Está vacío en las 52.904 tuplas; no se le asigna significado. |
| 3 | Fecha raw y fecha ISO cuando encaja `DD/MM/YYYY` | Las fechas de los 119 partidos de 2026/27 coinciden con Hito 1B. |
| 4 | Indicador raw de localía del club fuente | Solo toma 0/1 y concuerda con los IDs local/visitante en las 52.904 observaciones. |
| 5–7 | Nombre del local y goles local/visitante | Coinciden en los 119 partidos actuales con Hito 1B; nombres, marcador y goles raw se conservan. |
| 8 | ID de partido raw, serializado como ID | Los 119 IDs actuales coinciden con Hito 1B. En los IDs repetidos de las páginas históricas, los datos neutrales también coinciden entre fuentes. |
| 9 | Nombre raw del visitante | Coincide con Hito 1B para los 119 partidos actuales. |
| 10–11 | IDs raw de los clubes local/visitante | El cruce a clubes permanentes y a sus equipos-temporada coincide para los 119 partidos. |
| 12 | Código de resultado relativo al club fuente, raw | Coincide con el signo derivado del marcador en 52.901/52.904 filas. Tres excepciones se conservan y se reportan, sin corregirlas. |
| 13 | ID raw de árbitro | Coincide con el ID de árbitro de Hito 1B en las 238 observaciones actuales. |
| 14 | Etiqueta raw de jornada/ronda | Se conserva como texto. |
| 15 | Código raw de jornada/ronda | Se conserva sin interpretar. |
| 16–17 | Valores raw de tarjetas del club fuente | Coinciden con las columnas `TA` y `TR` de `tpartits` en 102/102 observaciones disponibles de las variantes `all`. No se extrapoló esa comparación a páginas sin variante capturada. |
| 18 | Temporada raw | Se conserva como texto, por ejemplo `2026-27`. |

Las tres discrepancias entre el código de resultado relativo y el marcador son:

- `150715`, `e48`, 08/04/1951: Numancia 3–0 Ferrol; raw `1`, valor derivado del marcador `-1`.
- `501020`, `e18`, 07/09/2011: Hércules 0–0 Alcoyano; raw `-1`, valor derivado `0`.
- `150730`, `e119`, 22/04/1951: Numancia 3–1 San Andrés; raw `1`, valor derivado `-1`.

Los códigos raw no se sustituyen. La observación raw y el marcador quedan disponibles para una revisión posterior.

## Contrastes y duplicados

Se usó el export correcto de competición de Hito 1B, clave `044edc9b2ef3c6026c7f`: sus dos grupos contienen 760 fixtures y 119 partidos disputados. Los IDs de `P` para `2026-27`/`1rf` cubren exactamente esos 119. Para cada partido coinciden ID, fecha, equipos local y visitante, IDs de clubes, goles y árbitro; no hubo IDs extra, ausentes ni diferencias en esos campos.

También se contrastaron las 102 observaciones de tabla conservadas en el export correcto de Hito 1D-B2 (`snapshot-f36c91119a98390766ff-parser-1.3.0`). Las 102 encuentran su tupla en `P` del club fuente y coinciden en fecha, equipos, goles, `TA` y `TR`. No se usó el export intermedio `snapshot-ced99eb5e1d083b36fc8-parser-1.3.0`.

En el conjunto histórico de 52.904 observaciones, 5.455 IDs aparecen en dos páginas canónicas distintas; no hay IDs con más de dos fuentes. Las observaciones repetidas concuerdan en temporada, competición, fecha, equipos, goles, IDs de clubes, árbitro y ronda. Se mantienen ambas observaciones con su club, URL, índice de tupla, ruta raw, hash y timestamp. El archivo normalizado deduplica por ID y enlaza todas sus observaciones.

## Cambios del parser y export

- `parse_club_team_html` reconoce la asignación `P` solo en páginas `club_matches` y publica estado, ancho, recuento y tuplas raw bajo `club_data.embedded_match_data`.
- Las asignaciones ambiguas, no interpretables o de ancho no soportado no se interpretan parcialmente. El HTML raw original sigue intacto.
- `club_team_sports.py` genera observaciones por club y partidos normalizados únicos por ID. Los datos de `P` proceden solo de las 40 URLs canónicas sin query: las variantes no cuentan otra vez el mismo contenido.
- El export añade `embedded_match_observations`, `matches_from_embedded_data`, `duplicate_embedded_matches`, `embedded_match_coverage_by_club` y `embedded_match_competition_crosscheck`, en JSON/CSV gzip deterministas cuando aplica. Los partidos únicos incluyen referencias a todas las observaciones; los tuples raw completos quedan en el export de observaciones.
- El parser de clubes sube a `1.5.0`, el esquema de páginas a `football_data_hub.bdfutbol.club_team.v3` y el esquema deportivo a `football_data_hub.bdfutbol.club_team_sports.v2`.

Export creado, sin alterar versiones anteriores:

`data/parsed/bdfutbol/club_team_2026_27/compact/snapshot-23246882b5841a3afd25-parser-1.5.0/`

Tiene 554 archivos y 97.813.423 bytes (93,3 MiB). El parseo y la escritura tardaron 1.315,1 s (21 min 55 s). La salida `sports/` conserva 52.904 observaciones, 47.449 partidos únicos y el contraste por competición. El export anterior `f36c...` y el intermedio `ced99...` siguen disponibles.

La selección automática local habría elegido la extracción más reciente `d047191aa847be5c30d7`, que tiene cero resultados disputados. Para el cruce se eligió explícitamente `044edc9b2ef3c6026c7f`, después de validar su integridad, raw de procedencia y 119 resultados disputados. El comando reproducible, totalmente offline, es:

```bash
PYTHONPATH=src:scripts .venv/bin/python - <<'PY'
import json
from pathlib import Path
from scrape_bdfutbol_club_team import parse_args, run

root = Path("data/parsed/bdfutbol/primera_federacion_2026_27/")
root /= "snapshot-044edc9b2ef3c6026c7f-parser-1.0.0"
participants = json.loads((root / "participants.json").read_text())["items"]
arguments = ["offline", "--compact-export", "--competition-extraction-key", "044edc9b2ef3c6026c7f"]
for item in participants:
    arguments.extend(["--team-id", item["team_season_id"]])
raise SystemExit(run(parse_args(arguments)))
PY
```

## Pruebas y límites

- Pruebas específicas de clubes y deportes: **63 passed**.
- Suite completa: **251 passed**. El sandbox denegó inicialmente el bind local de loopback en `test_loopback_port_valid`; la prueba aislada y la suite completa pasaron al ejecutar el permiso local de loopback. No hubo conexiones externas.
- Ruff en los módulos y tests modificados: **All checks passed**.
- `git diff --check`: correcto.

La cobertura describe lo que traían estas 40 capturas; no certifica todos los partidos de BDFutbol ni una carrera completa de los clubes. Las comprobaciones históricas de árbitro y tarjetas siguen limitadas a las muestras señaladas. Los tres códigos de resultado discrepantes, la posición raw 2 y los códigos de ronda quedan pendientes de interpretación. El export de partidos basado en las 17 variantes filtradas sigue mostrando 51 ausencias de cobertura de tabla; el nuevo recurso `P` sí cruza los 119 encuentros de 2026/27. No hubo navegación, peticiones live, cambios de Dev Explorer o datos de jugadores, ni commit/push.
