# PLAYER-01B2 — Recuperación de partidos individuales

**Fecha de exploración:** 14 de octubre de 2026  
**Rama:** `rebuild/browser-foundation-v1`  
**Jugador contrastado en vivo:** Manu Pedreño (`player_id=23751`)

## Resultado

Las vistas base no mostraban encuentros porque `#tpartits` se guarda con la cabecera, mientras los registros ya están serializados en `window.P`. BDFutbol crea las filas al abrir un contexto filtrado. La navegación autorizada a `?cat=1rf` devolvió HTTP 200, mantuvo la URL solicitada y mostró la tabla individual de Manu.

El parser anterior solo leía las filas presentes en el HTML inicial y por eso declaraba cero partidos individuales. El parser actualizado lee `window.P` en capturas base y lee las filas de `#tpartits` en snapshots filtrados. No interpreta los agregados de `#t2` como encuentros.

## Evidencia de la fuente

### Captura base

El HTML base de Partidos de los cuatro pilotos contiene una asignación JSON `P` con tuplas de 27 posiciones. La tabla `#tpartits` tiene únicamente su cabecera; las tablas de resumen `#t2`, `#t1`, `#t55` y `#t5` sí contienen agregados.

| Jugador | Registros `P` | Con flags de aparición | Sin flags de aparición | Categorías cubiertas |
|---|---:|---:|---:|---|
| Manu Pedreño (`23751`) | 261 | 108 | 153 | `2aB`, `PRF`, `1rf`, `COP`, `CNF`, `CHA` |
| Nacho Castillo (`28577`) | 174 | 88 | 86 | `2a`, `COP`, `1rf`, `FED` |
| Morillas (`209629`) | 82 | 35 | 47 | `2aB`, `PRF`, `COP`, `1rf` |
| Mendinueta (`729168`) | 7 | 0 | 7 | `1rf` |

Los indicadores `pt`, `pc` y `ps` determinan si la fuente marca una aparición. Un registro de `P` no equivale por sí solo a que el jugador haya disputado el encuentro. `pv` se conserva como indicador separado de convocatoria sin participación según el título de la tabla. En particular, los siete registros de Mendinueta no se convierten en siete partidos jugados: los siete carecen de flags de aparición, solo uno tiene `pv=1` y el resumen de la competición registra cero PJ.

Los recuentos de apariciones por competición coinciden con PJ publicados en los resúmenes de los cuatro pilotos. Para Manu, por ejemplo, `1rf` contiene 128 registros `P`, 67 con aparición y 61 sin ella; el resumen de 1.ª RFEF indica 67 PJ. Para Nacho, `1rf` contiene 121 registros, 72 con aparición; para Morillas, 7 y 7; para Mendinueta, 7 y 0.

### Una navegación filtrada

Se realizó **una navegación nueva** a `https://www.bdfutbol.com/es/p/j23751.html?cat=1rf`. No se visitaron los otros tres jugadores.

- HTTP 200, título e identidad de Manu válidos y URL final exacta.
- `window.P` presente: 261 tuplas, ancho 27, 261 IDs distintos.
- `#pest1` visible y `#pest2` oculto; el filtro seleccionado era `cat=1rf` y el selector `jug=si`.
- El script observado en el DOM fue `/js/scripts_partits.js?v=17.2.7`.
- `#tpartits` contenía 69 filas DOM: cabecera, 67 partidos y una fila final `Total 67`.
- Los 67 IDs de partido enlazados en la tabla coinciden exactamente con los 67 registros `1rf` de `P` cuyos flags indican aparición. No faltan ni sobran IDs.
- Fecha, temporada, competición, local, marcador y visitante están expuestos en celdas de `#tpartits`; por `match_id`, fecha, temporada, competición, local, visitante y ambos goles tuvieron **cero diferencias** frente a las tuplas de `P`.

La fila `Total 67` no es un encuentro. La detección de filas totales se amplió para reconocer etiquetas como `Total 67`; el parser real produce 67 filas de partido y una fila total aparte.

## Mapa semántico conservador de `window.P`

Los nombres de propiedades se conservan junto con el vector original completo. El código fuente histórico de `scripts_partits.js` presente en el repositorio (`v17.2.6`) documenta el orden de `get_data`; la captura actual referencia `v17.2.7`, cuyo cuerpo no se guardó. Por ello, las etiquetas del DOM actual, los valores de las tuplas y los resúmenes son la evidencia vigente; los códigos no completamente definidos siguen raw.

| Índice | Propiedad | Interpretación y estado |
|---:|---|---|
| 0 | `t` | Año inicial de temporada; conservar raw. |
| 1 | `cat` | Código raw de competición; `1rf` coincide con el filtro URL y la columna Competición. |
| 2 | `jor1` | Auxiliar raw; significado pendiente. |
| 3 | `dat` | Fecha raw `DD/MM/YYYY`; se normaliza a ISO cuando es válida. |
| 4 | `loc` | Lado del equipo del jugador: `1` local y `0` visitante, según el script histórico y la correspondencia de equipos observada. |
| 5 | `e1` | Nombre del equipo local. |
| 6–7 | `gc`, `gf` | Goles local y visitante, respectivamente; etiquetas y marcadores visibles concuerdan. |
| 8 | `id` | ID de partido; coincide con `p.php?id=…` en los 67 enlaces renderizados. |
| 9–11 | `pt`, `pc`, `ps` | Indicadores de partidos de titular, completos y como suplente, según los títulos actuales de las columnas. Se conservan raw y se usan juntos para aparición. |
| 12 | `min` | Minutos publicados. No se usa por sí solo para decidir si hubo aparición. |
| 13 | `pv` | Indicador de convocado sin jugar según el título actual `Convocado (sin jugar)`; permanece separado de la aparición. |
| 14 | `tg1` | Campo de tarjetas amarillas 1 según el encabezado actual. |
| 15 | `tg2` | Campo raw sin encabezado equivalente observado; significado pendiente. |
| 16 | `tv` | Tarjetas rojas según el encabezado actual. |
| 17 | `tg` | Campo asociado a Goles en la tabla; su codificación interna no se descompone. |
| 18 | `e2` | Nombre del equipo visitante. |
| 19–20 | `ce1`, `ce2` | IDs raw de los equipos local y visitante. |
| 21 | `gp` | Código raw que el script histórico utiliza en filtros/colores; no se traduce a victoria/empate/derrota. |
| 22 | `genc` | Campo de goles encajados según encabezado actual. |
| 23 | `px` | Indicador de partido sustituido según encabezado actual. |
| 24–25 | `jor2`, `jor` | Etiqueta y valor de jornada; se mantienen ambos raw. |
| 26 | `nomtemp` | Etiqueta de temporada, por ejemplo `2026-27`. |

Los registros guardan `source_values_raw`, nombres y orden de propiedades, ID/URL de partido, referencia al snapshot, estado del encuentro y estados separados de aparición/convocatoria. Los goles ausentes quedan `null`; no se crean marcadores 0-0. Los errores de forma, asignaciones ambiguas o anchos distintos de 27 no producen filas `P` normalizadas.

## Variantes y deduplicación

El sistema distingue `BASE_VIEW`, `URL_VARIANT` y `SELECTOR_VARIANT`; también lee `FILTERED_VARIANT` por compatibilidad con snapshots anteriores. Una URL con `?cat=1rf` nunca se trata como vista base. Su `filter_parameters` se conserva y sus encuentros salen de la tabla filtrada, no del `P` completo.

La deduplicación del export usa `(player_id, match_id)`. Mantiene la referencia de cada snapshot y señala divergencias de campos sin corregirlas. Los registros sin ID no se agrupan. Así, la salida consolidada de este run contiene 524 pares jugador-partido únicos a partir de 852 registros observados; 328 son observaciones repetidas entre dos capturas base de Manu y la variante filtrada, y no se detectaron conflictos de campos. No se deduplican encuentros de jugadores distintos entre sí.

## Parser y exports

- `html_parser.py` sube a parser `1.1.0`, contrato `football_data_hub.bdfutbol.player_pages.v2`.
- Las capturas base de Partidos generan filas desde `window.P`; las variantes URL/selector usan solo filas reales de `#tpartits`.
- Los encabezados y la fila `Total N` se clasifican por separado.
- `detail_coverage` informa el origen; `exhaustiveness_status` permanece `SNAPSHOT_SCOPE_ONLY_NOT_CERTIFIED_COMPLETE` para la base y `FILTERED_SNAPSHOT_NOT_EXHAUSTIVE` para una variante filtrada.
- `export.py` genera `individual_matches.json` con deduplicación y procedencia. El hash y URL del snapshot aparecen en cada fuente.
- La nota manual fija sobre la identidad de Manu se eliminó del export; el código no añade notas de revisión ajenas a los eventos que encuentra en el run.
- La CLI admite `--match-url-filter cat=1rf`; los fallos producen código de salida distinto de cero. Los errores de acceso se conservan en el checkpoint.
- El parser usa `lxml` cuando está instalado y mantiene `html.parser` como alternativa.

Export derivado generado offline desde el run `20261014T133920.712440Z-bf7bc8e4`:

`$HOME/FootballDataHub-data/players/player-captures/20261014T133920.712440Z-bf7bc8e4/normalized/derivations/20261014T144147.756726Z-1.1.0-7ba60b0a-8372f44f/`

Incluye 36/36 snapshots parseados, cero errores y `individual_matches.json` (524 claves únicas, 852 observaciones fuente, cero conflictos). Las derivaciones anteriores `1.0.0` se conservaron. Los HTML originales no se reescribieron.

## Inventario y reanudación

El índice externo de PLAYER-01A contiene 1.709 IDs: 1.065 con pertenencia a plantilla y 644 referenciados solo en Traspasos. El reconciliador verificó por ID, vista, URL base, HTTP 200, identidad del jugador y SHA-256 los 16 pares jugador-vista base únicos de los cuatro pilotos. Los cuatro jugadores tienen sus cuatro vistas base.

- Quedan 1.705 IDs con alguna vista base pendiente y **6.820 navegaciones base** (4 vistas × 1.709 − 16 vistas ya válidas).
- El JSON de progreso guarda los IDs pendientes, vistas pendientes, capturas reutilizables por vista, cohorte, grupo, SHA-256 del inventario y errores de acceso/estructura.
- La adquisición consulta el índice antes de abrir Chromium y registra las referencias reutilizadas en el nuevo manifiesto. Cada snapshot se confirma de forma atómica; una interrupción puede reconciliarse offline con `scripts/build_bdfutbol_player_acquisition_progress.py`.
- La ejecución sigue usando SeleniumBase Pure CDP, `BrowserSessionManager`, el perfil existente y Xvfb del runtime; secuencial, con pausa y parada ante denegación. No hay reintentos para superar bloqueos.

Índice actual:

`$HOME/FootballDataHub-data/players/player-captures/acquisition-progress-2026-27.json`

SHA-256 del índice generado: `ad87aa6bd76ac228140d19c88dde03be6f2189045d99cc1ec3940f8ba626497c` (sin manifests corruptos ni vistas bloqueadas en la reconciliación actual).

El sondeo anterior mostró 17 navegaciones canónicas válidas y una mediana de 9,2 segundos entre sus marcas de captura; el intervalo tuvo mucha variación y solo 16 intervalos. Los 6.820 viajes restantes requieren como mínimo 9 h 28 min de pausas de cinco segundos. La mediana piloto proyecta unas 17,4 h de trabajo activo; reservaría 18–24 h, sin asumir que los bloqueos o cortes se repiten a un ritmo fijo.

Para 16 vistas base, los HTML gzip ocuparon 2,20 MB y sus metadatos 1,78 MB. Extrapolado linealmente a las 6.836 vistas base totales, el origen comprimido y sus metadatos serían aproximadamente 1,7 GB, antes del tamaño de manifests y cualquier variante. El export verbose del piloto ocupó 130,6 MB para 36 snapshots; solo las 16 vistas base únicas sumaron 78,6 MB de JSON normalizado. Esa escala daría unos 33,6 GB para 6.836 vistas si se conserva el JSON de depuración completo. Antes de la adquisición general conviene publicar contratos normalizados compactos y mantener los HTML raw como evidencia, en lugar de multiplicar las tablas DOM completas por cada jugador.

No se ejecutó la adquisición general ni se visitaron otros jugadores en este hito.

## Validación

- Comparación offline por ID de los cuatro snapshots base y la variante filtrada de Manu.
- Coincidencia exacta de los 67 IDs renderizados y los flags de aparición de `P` para `1rf`.
- Comparación de apariciones por competición con los PJ de `#t2` en los cuatro pilotos.
- `pytest` offline: regresiones de P de 27 campos, header-only, filtros URL, filas totales, convocatorias sin aparición, deduplicación/procedencia, reutilización inter-run, hashes e identidad y salida CLI no cero.
- Ruff pasó. La suite completa se intentó, pero no terminó dentro del límite de tres minutos: seguía en tests heredados de inspección de capturas de equipos; no se considera una suite completa aprobada.
- La navegación nueva de Manu se efectuó una sola vez y fue válida.

Los datos son los contenidos en capturas fechadas; ni `P` ni el export certifican toda la trayectoria histórica del jugador. Los filtros de temporada, equipo, rival, resultado y jornada no se recorrieron en lote; solo se verificó el filtro de competición `cat=1rf`.
