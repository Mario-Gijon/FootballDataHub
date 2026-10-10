# Motor local de clasificación — Primera Federación Grupo II 2026/27

## Alcance y estado

Este hito convierte el calendario y los resultados embebidos en la página de clasificación en registros deportivos reutilizables y calcula tablas en Python. El dominio no importa Playwright, Brave, HTML ni el proveedor BDFutbol; la extracción del snapshot pertenece al proveedor.

| Área | Estado | Evidencia |
|---|---|---|
| Lectura de `SP` y `#resultats` | Explorada e implementada | Se compararon las 38 jornadas del snapshot guardado, 380 fixtures, sus fechas, equipos, marcadores, tarjetas e IDs visibles. |
| Normalización de partidos | Implementada y validada | JSON nuevo con 380 registros, 59 disputados y 321 sin resultado; IDs y referencias a las dos estructuras fuente. |
| Motor General/Local/Visitante | Implementado y validado | Cálculo puro; coincide por ID con los nueve estados recalculados por JavaScript de BDFutbol. |
| Filtros por jornada y rangos | Implementados y validados para los ejemplos documentados | Jornada 6, 5 y 3; jornadas 2–4; fechas 29/08–27/09, límites inclusivos. |
| Inclusión/exclusión por regla de aplazamiento | Implementada según el código fuente; validación real pendiente | La función compara fecha del partido con fecha de jornada + 3 días, pero esta captura no tiene ningún fixture que cruce el umbral. |
| Desempate final con igualdad de todos los criterios | Parcial | Se verifican los criterios publicados; el orden de equipos completamente empatados conserva el orden de catálogo de entrada. |
| Reproducción del gráfico | Fuera del alcance del motor | Se conservan intactos `progress.json` y sus `null`; este motor calcula tablas desde partidos. |

Captura de origen: `20261010T102656.252222Z-72f200ad`, recibida con HTTP 200 el 10/10/2026. El diagnóstico estructural confirmó el título de Grupo II y 20 equipos en `#classific`. Los filtros comparados se calcularon en un único documento del navegador, sin una navegación por escenario. El snapshot guardado fue suficiente para extraer los partidos; la sesión real solo se necesitó como referencia del JavaScript de clasificación.

## Origen y significado de los datos

### `SP`

`SP[jornada]` es una lista de diez registros por jornada. Cada elemento contiene:

| Campo de origen | Significado observado | Uso normalizado |
|---|---|---|
| `id` | ID numérico de partido BDFutbol. Único en los 380 registros; el enlace de `#resultats` lo confirma para los partidos disputados. | `match_id` como texto, con referencia `SP[jornada].push(id=...)`. |
| `d` | Fecha del encuentro mostrada también en `#resultats`. | `source_match_date`; fecha efectiva si se disputó y fecha programada/de referencia si no tiene marcador. |
| `a1`, `a2` | Índices internos de local y visitante en `SE`, no IDs de equipo. | Se resuelven por `SE` y se validan contra `#resultats`; luego se guardan como `home_team_id` y `away_team_id` del catálogo `#classific`. |
| `g1`, `g2` | Goles de local y visitante. En la captura `-1/-1` representa ausencia de resultado. | Enteros si se disputó; `null` si no. No se convierte `-1/-1` en 0-0. |
| `tg1`, `tg2` | Amarillas del local y visitante. | Enteros solo para partidos disputados; `null` para fixture sin resultado, aunque la fuente deje ceros placeholder en `SP`. |
| `tv1`, `tv2` | Rojas del local y visitante. | Igual criterio que las amarillas. |
| `r` | Para los 59 partidos disputados coincide con el signo del resultado visto desde el local: victoria `1`, empate `0`, derrota `-1`. En los fixtures sin marcador vale `0`. | Se conserva en `source_fields` para auditar; no se usa para calcular puntos ni victorias. |

El ID `a1/a2` se obtiene inicialmente del texto de `SE`, que se coteja con el nombre visible en la fila de partido y el catálogo con `data-ideq`. El nombre solo es una llave de reconciliación del proveedor; el modelo normalizado y las comparaciones utilizan siempre IDs numéricos de BDFutbol.

### `#resultats`

`#resultats` es una tabla oculta bajo `div#resultats`, con diez filas de partido por jornada. Cada fila expone jornada, fecha, local, marcador, visitante y, cuando están disponibles, estadio y árbitro. Este extractor no visita fichas de partido ni normaliza estadio/árbitro.

En filas disputadas, los dos elementos `.resultat-gols` exponen goles y `data-tg` (amarillas); `data-tv` aparece cuando hay expulsiones y puede omitirse para cero. Los enlaces `p.php?id=...` repiten el mismo ID varias veces dentro de la fila, no son partidos duplicados. En filas sin resultado, la tabla muestra una raya y no enlaza a una ficha; se identifica la fila por jornada, fecha y equipos contra `SP`.

Las dos estructuras coinciden en los 380 fixtures. Los campos con un enlace directo a partido solo aparecen en 59 disputados. En la captura hay 59 resultados completos y un encuentro de Jornada 5 que ya tiene fecha pasada pero marcador vacío; no se infiere que esté aplazado. Los 321 registros restantes son fixtures sin resultado al corte de captura.

No existe una fecha original planificada separada de `SP.d` en estas estructuras. Para disputados, `d` coincide con la fecha visible del encuentro; para el resto solo es la fecha publicada/programada. La fecha de jornada usada por la regla de aplazamiento viene del texto de `#jornada` y es independiente de `d`.

## Modelo y procedencia

El dominio define `Team`, `MatchResult`, `ClassificationFilter`, `CalculatedStanding` y `CalculatedTable` en `src/football_data_hub/domain/classification/`. Los partidos conservan:

- `match_id`, jornada y fecha publicada de esa jornada;
- `source_match_date`, IDs local/visitante, marcador y tarjetas nullable;
- estado `played`, `unplayed` o `incomplete`;
- `postponed_by_source_rule`, que describe la regla de BDFutbol y no afirma que exista una decisión oficial de aplazamiento;
- URL visible de partido cuando BDFutbol la muestra;
- referencias a `SP` y `#resultats`, además de todos los campos fuente en `source_fields`.

El estado deportivo se deriva solo del marcador: ambos valores no negativos significan disputado; ambos negativos, sin disputar; un solo marcador no negativo, incompleto. El estado sin disputar distingue además `scheduled` si la fecha de partido aún era futura al corte, `result_unavailable_at_capture` si no había marcador al corte, y `unknown` si no se proporcionó fecha de captura. En esta captura hay 320 programados a futuro y un resultado no disponible al corte (J5 del 27/09). El indicador `postponed_by_source_rule` queda separado: la función del sitio no detecta ningún fixture que supere su umbral y no se etiqueta ninguno como aplazado. Un partido incompleto o no disputado se omite de las estadísticas. Los equipos se conservan en la tabla aunque no tengan partidos en el contexto.

`normalized/matches.json` incluye el catálogo de equipos, los registros de partido, metadata de captura, versión del extractor, ruta relativa y SHA-256 del snapshot original. Los datos de clasificación y progreso de CLAS-01 no se sobrescriben. `validation/matches.json` registra integridad, cobertura de jornadas, IDs, fixtures y balance de goles.

El archivo de referencia de standings publicado por BDFutbol permanece en la captura original:

`data/exports/bdfutbol/group2_classification/20261010T102656.252222Z-72f200ad/normalized/classification.json`

El motor devuelve una tabla calculada separada. En el corte comparado, la clasificación General de Jornada 6 calculada coincide con los 200 campos de los 20 equipos de la clasificación publicada. Esta coincidencia para un corte no convierte ambas fuentes en un único dato ni garantiza que siempre coincidan ante sanciones o cambios de reglas.

## Algoritmo del motor

`calculate_standings(teams, matches, filters, ...)` es una función de dominio pura: no abre archivos, navegador ni sockets; no realiza peticiones. La carga JSON es responsabilidad del adaptador `classification/match_io.py`.

1. Valida IDs únicos de equipo/partido y que cada encuentro refiera al catálogo recibido.
2. Usa la jornada indicada como límite superior inclusivo; si se omite, toma la jornada más alta con al menos un resultado disputado.
3. Aplica los límites inclusivos del rango de fecha o de jornada, combinados con el límite superior. La fecha se compara con `source_match_date`.
4. Si `include_postponed=False`, excluye los registros que la fuente marca con `source_match_date > matchday_date + 3 días`. Un estado de aplazamiento desconocido se conserva y genera advertencia.
5. Solo contabiliza encuentros `played`. La clasificación local suma el lado local; visitante, el lado visitante; general, ambos equipos.
6. Calcula PJ, PG, PE, PP, puntos ordinarios `3 × PG + PE`, GF, GC, amarillas y rojas. Los datos originales no se modifican para encajar con los puntos calculados.
7. Ordena por puntos descendentes, diferencia de goles descendente, GF descendentes y puntuación disciplinaria ascendente (`rojas × 2 + amarillas`). Si todos los criterios empatan, conserva el orden del catálogo de entrada; ese último desempate no se presenta como una regla confirmada de BDFutbol.

Los datos disciplinarios agregados son `null` si falta alguna tarjeta de un partido disputado incluido. Los goles y puntos nunca se inventan. Un equipo sin partidos en el filtro conserva PJ/PG/PE/PP y estadísticas en cero, pues son totales calculados sobre un conjunto vacío, no valores faltantes de una fuente.

## Semántica de filtros y discrepancias posibles

| Filtro | Comportamiento reproducido | Validación |
|---|---|---|
| `classification_type` | `general`, `local`, `visitor`. | Jornada 6 y 5, para los tres tipos según la matriz descrita abajo. |
| `matchday_cap` | Incluye partidos de la jornada 1 hasta la seleccionada. Los resultados no disputados no incrementan estadísticas. | Jornada 6, 5 y 3. |
| `include_postponed` | La función fuente usa fecha del partido posterior a fecha de jornada + 3 días. | La regla se leyó del JS y se prueba unitariamente; no hay un caso real en el snapshot, así que su efecto real sigue pendiente. |
| `range_type=dates` | Límites de fecha inclusivos sobre `SP.d`; también respeta el límite superior de jornada. | 29/08/2026–27/09/2026, con J6 como límite. |
| `range_type=rounds` | Ambas jornadas se incluyen; el límite superior seleccionado no se rebasa. | Jornadas 2–4 con J6 como límite. |

El selector de jornada ofrece las 38 jornadas y su fecha. Los valores de clasificación son Local `1`, Visitante `2`, General `3`; aplazados Incluidos `1`, No incluidos `2`; rangos Todas `1`, Fechas `2`, Jornadas `3`. Cambiar esos controles recalcula filas en el mismo documento. `recalcula_classificacio()` define `completa` como General, última opción de jornada ofrecida y sin rango; en esa rama restaura el HTML original independientemente del selector de aplazados. Las comparaciones CLAS-01B usaron J3–J6, no esa última opción. Por eso se preserva la tabla publicada y no se asume que toda clasificación de BDFutbol sea generada por `SP`.

La función de aplazamiento se ejecuta sobre `SP` y el valor de fecha asociado a la jornada, no sobre el día de la semana ni una etiqueta inferreda por el extractor. La tabla publicada puede además reflejar sanciones o desempates no presentes en partidos; no se corrige automáticamente ninguna discrepancia.

## Comparación contra BDFutbol

La referencia real de JavaScript se guardó en:

`data/exports/bdfutbol/group2_classification/derived-clas01b-20261010T102656Z/validation/bdfutbol_js_reference.json`

El informe se regeneró con `scripts/compare_group2_classification.py` y contiene los escenarios y cualquier diferencia por ID/campo:

| Escenario | Equipos | Campos iguales | Diferencias |
|---|---:|---:|---:|
| General J6 | 20 | 200/200 | 0 |
| General J5 | 20 | 200/200 | 0 |
| Local J6 | 20 | 200/200 | 0 |
| Visitante J6 | 20 | 200/200 | 0 |
| General J3 | 20 | 200/200 | 0 |
| General J2–J4 (límite J6) | 20 | 200/200 | 0 |
| General 29/08–27/09 (límite J6) | 20 | 200/200 | 0 |
| Local J5 | 20 | 200/200 | 0 |
| Visitante J5 | 20 | 200/200 | 0 |
| **Total JS** | **180 filas** | **1.800/1.800** | **0** |

También se compararon los diez campos deportivos de las 20 filas de la tabla original guardada para General J6: 200/200 iguales. Las comparaciones no cambian la clasificación publicada ni las series del gráfico. No hubo diferencias que requiriesen explicación en esta captura; sanciones, jornada con aplazamiento real y un empate final en todos los criterios quedan como límites pendientes.

## Archivos y comandos

Normalización offline desde un snapshot existente, con salida exclusiva que falla si el archivo ya existe:

```bash
PYTHONPATH=src .venv/bin/python scripts/extract_bdfutbol_matches.py \
  --snapshot data/exports/bdfutbol/group2_classification/20261010T102656.252222Z-72f200ad/raw/source.html \
  --capture data/exports/bdfutbol/group2_classification/20261010T102656.252222Z-72f200ad/metadata/capture.json \
  --output /ruta/nueva/normalized/matches.json
```

Cálculo sin navegador ni red:

```bash
PYTHONPATH=src .venv/bin/python scripts/calculate_group2_standings.py \
  --matches data/exports/bdfutbol/group2_classification/derived-clas01b-20261010T102656Z/normalized/matches.json \
  --classification general --matchday 6 --output /tmp/group2-general-j6.json
```

Para local/visitante use `--classification local` o `--classification visitor`. Los rangos aceptan `--range dates --date-start 2026-08-29 --date-end 2026-09-27` o `--range rounds --round-start 2 --round-end 4`; `--exclude-postponed` aplica la política de exclusión. La ruta de salida debe ser nueva.

La futura API podrá cargar `matches.json`, convertir equipos/partidos a estos modelos y llamar al motor en memoria. No necesita importar el proveedor BDFutbol, abrir el snapshot ni iniciar Brave para responder a los filtros. La API aún deberá definir almacenamiento, recarga de capturas y políticas de discrepancias.
