# Estadísticas de competición — BDFutbol, Grupo II 2026/27

## Alcance y estado

Este hito extrae la pestaña `?tab=stats` de Primera Federación 2026/27, Grupo II,
y calcula los agregados reproducibles desde el `matches.json` ya existente.
No crea un segundo dataset de partidos ni modifica FastAPI o React.

| Área | Estado |
| --- | --- |
| Acceso a la página Estadísticas | Verificado en una captura válida: HTTP 200, título 1ª RFEF Grupo II 2026-27, URL final correcta y contenido semántico presente. |
| Cobertura del catálogo | Verificada: 20 equipos, 380 fixtures en 38 jornadas, 59 disputados y 321 sin resultado. |
| Agregados generales | Calculados desde Resultados y comparados con la página. |
| Tarjetas rojas frente a «Expulsiones» | Los valores agregados coinciden numéricamente (15 y 0,25); su equivalencia conceptual completa queda pendiente. |
| Penaltis | Los tres totales se obtienen de la página y no pueden derivarse del modelo actual de partidos. |
| Récords | Calculados con todos los empates preservados y comparados con el partido que publica BDFutbol. |
| Rachas | Calculadas con IDs de partidos; se conservan máximos empatados. La equivalencia de la política ante aplazamientos sigue pendiente. |
| Gráfico por jornada | Se recuperó el `dataProvider` numérico de AmCharts. J5 tiene una discrepancia de goles sin causa demostrada. |
| Prueba offline | Implementada mediante snapshots con hashes y sin navegador ni peticiones HTTP. |

## Procedencia de la captura

La captura validada se conserva en:

`data/exports/bdfutbol/group2_statistics/20261010T182210.859321Z-28543363/`

- URL solicitada/final: `https://www.bdfutbol.com/es/t/t2026-271rf2.html?tab=stats`.
- Capturada: `2026-10-10T18:22:10.859321+00:00`.
- HTTP 200; título `Clasificación 1ª RFEF Grupo II 2026-27 | BDFutbol`.
- Backend: SeleniumBase Pure CDP, Chromium 152, Xvfb externo (`DISPLAY=:0`).
- SHA-256 del HTML: `b66485e2e090b1308620b44cbc337ac994e87fcda23af4a15c838db5d3565a85`.
- SHA-256 del snapshot del gráfico: `cf8a542df6b01349da13b78496cd784fe455365ab375315de23745680ba14fd5`.
- No se observó desafío ni denegación. La validación requiere el contenido deportivo y la estructura de Estadísticas; HTTP 200 por sí solo no basta.

En la exploración hubo navegaciones previas cuya comprobación local rechazó páginas normales por dos validadores demasiado estrictos: uno buscaba literalmente «Primera Federación» aunque el título utiliza «1ª RFEF», y otro buscaba `grf_stats` como texto en vez de elemento DOM. Se corrigió la validación; no se intentó resolver ni superar un desafío.

## Origen y cobertura de los datos

El motor reutiliza este conjunto existente:

`data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json`

La captura de partidos tiene ID `20261010T102656.252222Z-72f200ad`, fecha
`2026-10-10T10:26:56.252397+00:00`, 20 equipos y 380 encuentros. Su ruta, hash,
ID y fecha se registran en `metadata/capture.json` y dentro de los datos
derivados. El export STAT no copia `matches.json`.

El HTML de Estadísticas también contiene `SE`, `SP` y `#resultats`. Se reusó el
parser existente de Clasificación/Resultados para contrastar esos registros, no
para exportarlos de nuevo. Los 380 IDs y todos los campos comparados coinciden
con el dataset de Resultados: jornada, fecha fuente, IDs de local/visitante,
marcador, tarjetas amarillas/rojas y estado. El informe de alineación está en
`validation/reconciliation.json`.

| Dato publicado | Origen actual | Tratamiento |
| --- | --- | --- |
| Equipos, partidos, victorias locales/visitantes y empates | `MatchResult` y catálogo de Resultados | Recalculado sobre `status=played`. |
| Goles y promedio goleador | Marcadores de `MatchResult` | Recalculados sin redondeo interno; la comparación presenta dos decimales. |
| Amarillas | Campos de tarjetas por lado | Recalculadas; cobertura completa: 59 de 59 partidos disputados. |
| Rojas / expulsiones | Campos de tarjeta roja por lado y agregado «Expulsiones» de la fuente | Recuento derivado y comparación numérica; significado exacto de «Expulsiones» pendiente de confirmar. |
| Penaltis pitados, marcados y fallados | Exclusivamente la página Estadísticas | Guardados como totales de competición 24/21/3; no se asignan a partidos, equipos, jugadores ni jornadas. |
| Récords de partido | Marcadores y `match_id` | Calculados; la página aporta enlaces e IDs para contrastar el registro que presenta. |
| Rachas | Resultados ordenados por equipo | Calculadas; la página publica un equipo por categoría, mientras que el motor conserva todos los empates. |
| Goles/amarillas/rojas por jornada | Resultados existentes; la fuente expone además AmCharts `dataProvider` | Se calculan por jornada y se concilian con la serie original. |

No se encontraron en esta pestaña valores de penaltis por encuentro, equipo,
jornada, lanzador o resultado individual. La inspección se limitó a esta página;
no se recorrieron fichas de partidos ni jugadores.

## Modelos y reglas del motor

Los modelos puros viven en `src/football_data_hub/domain/statistics/` y no
importan Playwright, SeleniumBase ni código web. `calculate_competition_statistics`
recibe `Team`, `MatchResult` y `CompetitionContext` y devuelve agregados,
cobertura por jornada, récords y rachas.

- Solo `status=played` suma resultados y goles. Pendientes e incompletos no se
  convierten en empate, marcador 0-0 ni goles cero.
- Si falta alguna tarjeta local/visitante de cualquier partido contado, el total
  de esa métrica es `null` y `MetricCoverage` enumera partidos sin dato.
- Las jornadas 7–38 tienen cero partidos disputados en la captura, por lo que sus
  métricas son `null`, no cero. La jornada 5 es parcial: 9 de 10 partidos.
- El orden de partidos es jornada, fecha fuente y luego ID de partido (numérico
  cuando corresponde). Empates en récords y rachas se conservan todos.
- Para una racha, un fixture no disputado/incompleto se omite y no rompe la
  secuencia de resultados disputados. En esta captura no hay partidos marcados
  como aplazados por la regla fuente; la semántica de continuidad ante un
  aplazamiento real y fechas efectivas no está verificada. La salida incluye esta
  metodología para no presentarla como criterio oficial de BDFutbol.
- El motor no ordena una clasificación de equipos ni aplica desempates oficiales.

## Reconciliación de cifras generales

Para la captura actual, los valores derivados y publicados coinciden:

| Métrica | Calculado | BDFutbol | Estado |
| --- | ---: | ---: | --- |
| Equipos | 20 | 20 | Coincide |
| Partidos disputados | 59 | 59 | Coincide |
| Victorias locales | 28 | 28 | Coincide |
| Victorias visitantes | 16 | 16 | Coincide |
| Empates | 15 | 15 | Coincide |
| Goles | 155 | 155 | Coincide |
| Goles por partido | 2,63 | 2,63 | Coincide al presentar dos decimales |
| Amarillas | 290 | 290 | Coincide |
| Amarillas por partido | 4,92 | 4,92 | Coincide al presentar dos decimales |
| Tarjetas rojas / «Expulsiones» | 15 | 15 | Recuento coincide; equivalencia conceptual pendiente |
| Rojas por partido / «Expulsiones por partido» | 0,25 | 0,25 | Recuento coincide; equivalencia conceptual pendiente |

`validation/reconciliation.json` conserva ambas cifras, diferencia, estado y
causa. No transforma la igualdad de los dos totales de expulsiones en una
afirmación sobre los criterios de cómputo de la fuente.

## Récords y rachas

Los tres récords publicados están respaldados por IDs y marcadores:

| Tipo | Publicado | Cálculo local | Comparación |
| --- | --- | --- | --- |
| Mayor victoria local | Alcorcón 5–0 Juventud de Torremolinos, ID `272566` | Margen 5, ID `272566` | Coincide |
| Mayor victoria visitante | Europa 0–3 Jaén, ID `272523` | Margen 3, IDs `272523` y `272540` | La selección publicada pertenece al empate calculado |
| Partido con más goles | Juventud de Torremolinos 3–4 Zaragoza, ID `272542` | 7 goles, ID `272542` | Coincide |

Las cuatro rachas publicadas coinciden en equipo, número de partidos y jornadas:

| Tipo | Equipo publicado | Partidos | Jornadas | Resultado |
| --- | --- | ---: | --- | --- |
| Victorias | Zaragoza | 5 | 2–6 | Coincide |
| Derrotas | Juventud de Torremolinos | 5 | 2–6 | Coincide |
| Invicto | Alcorcón | 6 | 1–6 | Coincide |
| Sin ganar | Juventud de Torremolinos | 6 | 1–6 | Coincide, pero comparte el máximo calculado con Teruel |

El enlace de récord de visitante y la racha sin ganar muestran una sola entidad;
la fuente no explicita el desempate de esas categorías. El motor conserva los
dos partidos de margen visitante máximo y los dos equipos con seis jornadas sin
ganar. No se infiere un desempate fuente.

## Gráfico de progreso

La página renderiza el gráfico con **AmCharts 3.15.2**. Los valores numéricos
están en el objeto JavaScript del gráfico serial, `categoryField="jornada"`,
`dataProvider`, y no se reconstruyeron desde píxeles del SVG. Los campos de las
tres líneas son `VG` (Goles), `VTG` (Tarjetas amarillas) y `VTV` (Tarjetas rojas).

Las observaciones son totales de la jornada, no acumulados. Los seis puntos de
goles publicados para J1–J6 suman **153**, mientras que el resumen general de
BDFutbol publica **155**. Las tarjetas de las jornadas observadas coinciden con
las agregaciones de los partidos. J1–J6 publicados:

| Jornada | Goles fuente | Goles derivados | Amarillas fuente/derivadas | Rojas fuente/derivadas | Cobertura de partidos |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 29 | 29 | 46 / 46 | 3 / 3 | 10/10 |
| 2 | 21 | 21 | 48 / 48 | 5 / 5 | 10/10 |
| 3 | 31 | 31 | 50 / 50 | 0 / 0 | 10/10 |
| 4 | 21 | 21 | 51 / 51 | 1 / 1 | 10/10 |
| 5 | **19** | **21** | 45 / 45 | 3 / 3 | 9/10 |
| 6 | 32 | 32 | 50 / 50 | 3 / 3 | 10/10 |

Para J5, el HTML de Estadísticas y su `dataProvider` reportan 19 goles. El
dataset de partidos y el `SP/#resultats` embebido en la misma captura contienen
los mismos 380 registros por ID, y los 9 resultados disputados suman 21 goles.
Por tanto, la diferencia no se explica por un cambio en la selección de partidos
entre capturas; la causa dentro de la fuente sigue sin determinarse. Se conserva
como discrepancia de dos goles y no se corrige ninguna de las dos cifras. No se
ha atribuido una causa a la diferencia entre la suma gráfica (153) y el resumen
publicado (155).

AmCharts incluye las categorías 7–38 pero sin valor para las tres series. Se
normalizan como `null`; no son observaciones de cero. Las series calculadas
incluyen cobertura y número de partidos disputados por jornada.

## Export

Cada ejecución crea un directorio con `capture_id` propio, sin sobrescribir otro:

- `raw/source.html`: HTML completo validado.
- `raw/chart_data_provider.json`: objeto y valores numéricos AmCharts.
- `raw/access.json`: estado, URL, título y resultado de validación de acceso.
- `metadata/capture.json`: procedencia de la página y referencia/hash del dataset
  de partidos utilizado.
- `normalized/exclusive_statistics.json`: únicamente los penaltis de origen.
- `normalized/derived_statistics.json`: agregados, récords, rachas, cobertura,
  algoritmo y procedencia del dataset de partidos.
- `validation/results.json`: estructura, consistencia de la fuente y del set de
  partidos.
- `validation/reconciliation.json`: comparación con totales, récords, rachas y
  puntos del gráfico publicados.

El directorio se prepara temporalmente y se publica solo después de pasar la
validación estructural. El `matches.json` original queda intacto.

## Ejecución

Modo completamente offline con la captura guardada:

```bash
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_group2_statistics.py \
  --matches data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json \
  --snapshot data/exports/bdfutbol/group2_statistics/20261010T182210.859321Z-28543363/raw/source.html \
  --chart-snapshot data/exports/bdfutbol/group2_statistics/20261010T182210.859321Z-28543363/raw/chart_data_provider.json \
  --access-report data/exports/bdfutbol/group2_statistics/20261010T182210.859321Z-28543363/raw/access.json
```

Adquisición controlada por Pure CDP, cuando sea necesaria y autorizada:

```bash
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_group2_statistics.py \
  --profile "$HOME/.football-data-hub-chromium-pure-cdp"
```

La CLI permite cambiar rutas mediante `--matches`, `--output-root` y perfil;
también admite `FDH_GROUP2_MATCHES`, `FDH_STATISTICS_EXPORT_ROOT` y
`FDH_BDFUTOL_PROFILE`. En el modo offline el CLI verifica los hashes y no abre el
navegador. En modo online usa el `BrowserSessionManager` y `BDFutbolAccess`
existentes; una denegación o contenido inválido detiene la adquisición.

## Consumo posterior por STAT-02

FastAPI puede servir `normalized/derived_statistics.json` y
`normalized/exclusive_statistics.json` junto con `metadata/capture.json`. La API
debe exponer la fecha/ID de captura y la procedencia de Resultados; el dashboard
puede representar puntos `null` como no disponibles y mostrar la discrepancia
J5 sin sustituirla. Los filtros visuales no requieren peticiones a BDFutbol ni
un segundo almacén de marcadores.
