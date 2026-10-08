# Hito 1D-B2 — Consolidación deportiva de los 40 clubes

**Fecha:** 8 de octubre de 2026 · **Rama:** `rebuild/football-data-hub-v2` · **Estado:** `PARTIAL — CHALLENGE_REQUIRED`

## Resultado

Se generó un export deportivo normalizado sobre las capturas de Hito 1D-B1 y las vistas de partidos que ya existían. La consolidación estructuró las estadísticas de plantilla, sus relaciones con equipo-temporada, los entrenadores, las referencias de movimientos y los partidos observados. El acceso de lectura a BDFutbol se detuvo al recibir HTTP 403 con un desafío en la vista `all` de Barakaldo. No se intentó eludir el desafío.

La cobertura de partidos está **incompleta para el objetivo de 40 clubes**: hay variantes `all` válidas para 17 clubes, 16 con agregados contrastados y una diferencia de alcance pendiente. No se declara completo el dataset ni ninguna entidad en sentido semántico.

| Métrica | Resultado |
|---|---:|
| Participantes incluidos | 40 |
| Vistas `all` válidas | 17/40 |
| Vistas `all` nuevas / reutilizadas | 13 / 4 |
| Partidos observados desde clubes | 68 únicos; 102 observaciones |
| Partidos contrastados con Hito 1B | 68/68, mismo ID, fecha, local, visitante y marcador |
| Partidos de Hito 1B no observados en esas vistas | 51/119 |
| Clubes con agregados PJ/PG/PE/PP validados | 16 |
| Clubes con diferencia de alcance del agregado | 1 |
| Pertenencias jugador-equipo-temporada | 1.039 |
| IDs de jugador / filas con cero apariciones | 1.034 / 179 |
| Membresías de entrenador | 41 |

## Acceso y método de adquisición

Se reutilizó el flujo existente `BrowserSessionManager` + `BDFutbolAccess` conectado a Brave/Xvfb/CDP y su perfil persistente. Las vistas se solicitaron con el selector conocido `cat=1rf&temp=2026-27` y sin `pgep`, es decir, la variante `all`. Se usó `reuse_existing=True` y lotes conservadores de cinco equipos. Las páginas base de B1 se reutilizaron; no se refrescaron.

Los tres lotes completados cubrieron 15 clubes y procesaron 195 resultados de snapshot: 182 reutilizados y 13 adquiridos. Cuatro de las 17 variantes `all` válidas ya existían de los pilotos de B1. La captura se detuvo en el primer acceso no válido:

- URL bloqueada: `https://www.bdfutbol.com/es/p/e99.html?cat=1rf&temp=2026-27`.
- Resultado: `CHALLENGE_REQUIRED`, HTTP 403.
- `challenge_bypass_attempted`: `false`.
- No se reintentó ni se continuó navegando después del desafío.

No se descargaron perfiles individuales, historiales, fotografías ni se exportaron cookies o credenciales. No se modificó Dev Explorer. Los artefactos raw nuevos se conservaron bajo `data/raw/`; las capturas preexistentes y snapshots anteriores permanecen intactos.

### URLs de variantes `all` adquiridas en este hito

Todas usan la URL exacta con `cat=1rf&temp=2026-27`:

| Club | URL |
|---|---|
| Deportivo Fabril | `https://www.bdfutbol.com/es/p/e104.html?cat=1rf&temp=2026-27` |
| Mirandés | `https://www.bdfutbol.com/es/p/e145.html?cat=1rf&temp=2026-27` |
| Cacereño | `https://www.bdfutbol.com/es/p/e149.html?cat=1rf&temp=2026-27` |
| UD Logroñés | `https://www.bdfutbol.com/es/p/e178.html?cat=1rf&temp=2026-27` |
| Mérida AD | `https://www.bdfutbol.com/es/p/e359.html?cat=1rf&temp=2026-27` |
| Unionistas de Salamanca | `https://www.bdfutbol.com/es/p/e411.html?cat=1rf&temp=2026-27` |
| Racing de Ferrol | `https://www.bdfutbol.com/es/p/e48.html?cat=1rf&temp=2026-27` |
| CD Extremadura | `https://www.bdfutbol.com/es/p/e515.html?cat=1rf&temp=2026-27` |
| Pontevedra | `https://www.bdfutbol.com/es/p/e58.html?cat=1rf&temp=2026-27` |
| Ponferradina | `https://www.bdfutbol.com/es/p/e62.html?cat=1rf&temp=2026-27` |
| Cultural Leonesa | `https://www.bdfutbol.com/es/p/e84.html?cat=1rf&temp=2026-27` |
| Real Unión | `https://www.bdfutbol.com/es/p/e88.html?cat=1rf&temp=2026-27` |
| Zamora | `https://www.bdfutbol.com/es/p/e95.html?cat=1rf&temp=2026-27` |

Las cuatro variantes existentes y reutilizadas proceden de Jaén (`e49`), Bilbao Athletic (`e72`), Lugo (`e76`) y Villarreal B (`e94`). Se reutilizaron además las vistas base capturadas en B1; no se pidieron las variantes redundantes `pg`, `pe` y `pp` a los 40 clubes.

## Partidos y cruce con Hito 1B

El cruce utilizó el export de competición `044edc9b2ef3c6026c7f`: 760 fixtures, 119 con resultado jugado. Se seleccionó esa extracción porque contiene resultados disputados; había otra extracción posterior, `d047191aa847be5c30d7`, con 760 fixtures pero cero resultados jugados. El proceso ahora elige primero por número de resultados disponibles, luego por enlaces de partido y finalmente por fecha, en vez de tomar ciegamente la extracción más reciente.

Los 17 snapshots `all` producen 102 observaciones de fichas de club, reducidas a **68 partidos únicos** por ID de partido. Cada partido observado coincide con Hito 1B en ID, fecha, equipo local, equipo visitante y marcador. Los encuentros que aparecen en las dos fichas conservan ambas observaciones y sus procedencias; el export de partidos no duplica el encuentro. No se detectaron discrepancias temporales entre las observaciones de club capturadas para esta consolidación.

De los 119 partidos jugados de Hito 1B, 51 IDs no aparecen en las variantes de club que pudieron capturarse. Esto es una diferencia de cobertura de fuente en esta ejecución, no una prueba de pérdida del parser: 23 clubes siguen sin una variante `all` válida por el corte de acceso. Entre los 68 cruces observados no hay campos deportivos discrepantes.

### Resultado por club

`Esperados` es el número de partidos jugados que el export Hito 1B contiene para ese participante; `vistos` cuenta las filas disputadas de su variante `all`. `VALIDATED` también exige que PJ/PG/PE/PP de la tabla se reconcilien con los resultados. `INCOMPLETE` indica que no había una variante `all` válida en el export de este hito.

| Grupo | Club | Equipo-temporada | Club ID | Esperados | Vistos | Estado |
|---|---|---|---|---:|---:|---|
| I | Deportivo Fabril | `t2026-27104` | `e104` | 6 | 6 | `VALIDATED` |
| II | Alcorcón | `t2026-27107` | `e107` | 6 | 0 | `INCOMPLETE` |
| II | Sant Andreu | `t2026-27119` | `e119` | 6 | 0 | `INCOMPLETE` |
| II | Antequera | `t2026-27140` | `e140` | 6 | 0 | `INCOMPLETE` |
| I | Mirandés | `t2026-27145` | `e145` | 6 | 6 | `VALIDATED` |
| I | Cacereño | `t2026-27149` | `e149` | 6 | 6 | `SCOPE_DIFFERENCE` |
| II | Gimnàstic de Tarragona | `t2026-2717` | `e17` | 6 | 0 | `INCOMPLETE` |
| II | FC Cartagena | `t2026-27176` | `e176` | 5 | 0 | `INCOMPLETE` |
| I | UD Logroñés | `t2026-27178` | `e178` | 6 | 6 | `VALIDATED` |
| II | Hércules | `t2026-2718` | `e18` | 6 | 0 | `INCOMPLETE` |
| II | Teruel | `t2026-27204` | `e204` | 6 | 0 | `INCOMPLETE` |
| II | Rayo Majadahonda | `t2026-27227` | `e227` | 6 | 0 | `INCOMPLETE` |
| I | Mérida AD | `t2026-27359` | `e359` | 6 | 6 | `VALIDATED` |
| II | Zaragoza | `t2026-2739` | `e39` | 6 | 0 | `INCOMPLETE` |
| II | Murcia | `t2026-2740` | `e40` | 6 | 0 | `INCOMPLETE` |
| I | Unionistas de Salamanca | `t2026-27411` | `e411` | 6 | 6 | `VALIDATED` |
| II | UD Ibiza | `t2026-27414` | `e414` | 6 | 0 | `INCOMPLETE` |
| I | CD Coria | `t2026-27473` | `e473` | 6 | 0 | `INCOMPLETE` |
| I | Racing de Ferrol | `t2026-2748` | `e48` | 6 | 6 | `VALIDATED` |
| II | Águilas FC | `t2026-27482` | `e482` | 6 | 0 | `INCOMPLETE` |
| II | Juventud de Torremolinos | `t2026-27488` | `e488` | 6 | 0 | `INCOMPLETE` |
| II | Jaén | `t2026-2749` | `e49` | 6 | 6 | `VALIDATED` |
| I | UD Ourense | `t2026-27510` | `e510` | 6 | 0 | `INCOMPLETE` |
| I | CD Extremadura | `t2026-27515` | `e515` | 6 | 6 | `VALIDATED` |
| II | Algeciras | `t2026-2755` | `e55` | 6 | 0 | `INCOMPLETE` |
| I | Pontevedra | `t2026-2758` | `e58` | 6 | 6 | `VALIDATED` |
| II | Real Madrid Castilla | `t2026-2761` | `e61` | 6 | 0 | `INCOMPLETE` |
| I | Ponferradina | `t2026-2762` | `e62` | 6 | 6 | `VALIDATED` |
| II | Atlético Madrileño | `t2026-2767` | `e67` | 6 | 0 | `INCOMPLETE` |
| I | Bilbao Athletic | `t2026-2772` | `e72` | 6 | 6 | `VALIDATED` |
| I | Lugo | `t2026-2776` | `e76` | 6 | 6 | `VALIDATED` |
| II | Huesca | `t2026-2779` | `e79` | 6 | 0 | `INCOMPLETE` |
| I | Avilés Industrial | `t2026-2781` | `e81` | 6 | 0 | `INCOMPLETE` |
| I | Cultural Leonesa | `t2026-2784` | `e84` | 6 | 6 | `VALIDATED` |
| I | Arenas de Getxo | `t2026-2787` | `e87` | 6 | 0 | `INCOMPLETE` |
| I | Real Unión | `t2026-2788` | `e88` | 6 | 6 | `VALIDATED` |
| II | Europa | `t2026-2789` | `e89` | 6 | 0 | `INCOMPLETE` |
| II | Villarreal B | `t2026-2794` | `e94` | 6 | 6 | `VALIDATED` |
| I | Zamora | `t2026-2795` | `e95` | 6 | 6 | `VALIDATED` |
| I | Barakaldo | `t2026-2799` | `e99` | 6 | 0 | `INCOMPLETE — HTTP 403` |

Cartagena tiene cinco fixtures jugados en Hito 1B, mientras que la tabla agregada del equipo muestra PJ=5. La vista individual de partidos no se capturó aquí, así que su `0` en “vistos” significa cobertura no disponible, no ausencia de esos partidos en BDFutbol.

### Diferencia de alcance: Cacereño

La variante `all` de Cacereño (snapshot `2026-10-08T17:58:00.161314Z`) expone seis partidos de `1rf`, con resultados 3 victorias, 2 empates y 1 derrota. Sus IDs coinciden exactamente con los seis partidos del equipo en Hito 1B. La fila de agregados de la página muestra PJ=8, PG=4, PE=2 y PP=2. La página de partido y la tabla agregada no comparten el mismo alcance observable; queda como `COMPETITION_CROSSCHECKED_SCOPE_DIFFERENCE`, no como fallo de parsing. No se ha determinado si el agregado incluye partidos de otra competición u otro alcance.

## Estadísticas individuales, plantillas y relaciones

Se conservaron las **22 posiciones** de cada fila de `team_statistics`, incluido encabezado vacío, aunque algunas celdas no tienen etiqueta. Encabezados observados:

`#`, ``, ``, `Apodo`, `Pos`, `PJ`, `PT`, `PC`, `PS`, `PX`, `C`, `Min`, `TA`, `TR`, `G`, `Minutos/G`, `GP`, `GPP`, `GE`, `PG`, `PE`, `PP`.

El export por jugador preserva el encabezado original, índice de columna, valor raw y procedencia; convierte a entero únicamente cadenas compuestas por dígitos. Las celdas vacías, guiones y rayas se normalizan como nulas conservando el valor raw. Se marcan **19 columnas deportivas para interpretación pendiente**. Se mantienen textuales las columnas de etiqueta (`#`, `Apodo`, `Pos`); no se han expandido abreviaturas como `PT`, `PC`, `PS`, `PX`, `C`, `GP`, `GPP` o `GE` por inferencia.

| Control | Resultado |
|---|---:|
| Filas de plantilla / estadísticas | 1.039 / 1.039 |
| Diferencias roster frente a estadísticas | 0 en los 40 equipos |
| IDs únicos | 1.034 |
| Filas de cero apariciones conservadas | 179 (178 IDs distintos) |
| Celdas de estadísticas preservadas | 22.858 |
| Valores con forma numérica convertidos | 19.730 |
| Valores ausentes/placeholders conservados como raw y normalizados nulos | 2.089 |
| Valores textuales de alias conservados | 1.039 |

Cinco IDs de jugador aparecen en dos equipo-temporada. Se conservan ambas relaciones; no se interpretan por sí solas como transferencias:

| Jugador | Equipo-temporada |
|---|---|
| `j23751` | `t2026-27178`, `t2026-27414` |
| `j26481` | `t2026-27119`, `t2026-2779` |
| `j304209` | `t2026-2776`, `t2026-2781` |
| `j304291` | `t2026-27104`, `t2026-2758` |
| `j402372` | `t2026-2758`, `t2026-2776` |

Se exportan 41 membresías de entrenadores con 41 IDs distintos. Europa (`t2026-2789`) tiene dos IDs de entrenador (`l111357`, `l300127`); ambos permanecen asociados. Las tablas de movimientos producen 5.370 referencias: 1.549 a jugadores, 3.781 a equipo-temporada y 40 a clubes. Son enlaces y relaciones de página, no transacciones confirmadas ni una secuencia histórica de fichajes.

## Seguimiento: columna 5

Los 40 snapshots de `team_tracking` conservan encabezados y celdas raw. FC Cartagena (`t2026-27176`) y Murcia (`t2026-2740`) presentan encabezados `"", 1, 2, 3, 4, 6`: falta la columna 5. El fixture de la jornada 5 entre ambos equipos figura en Hito 1B sin resultado (`result_raw=—`, estado programado), mientras los equipos vecinos sí tienen ronda 5 disputada. La evidencia respalda una omisión dependiente de la disponibilidad de partido en esa jornada; no implica que la columna sea una categoría vacía de estadísticas. No se inventó una columna 5 ni se imputaron valores.

Se conservan las variantes de encabezado, las filas, las celdas y los enlaces fuente. Hay 1.039 filas de seguimiento de jugador en el export, pero el significado de las celdas por jornada queda raw-only cuando no puede vincularse a una interpretación deportiva segura.

## Artefactos y procedencia

Export final recomendado para consumo:

`data/parsed/bdfutbol/club_team_2026_27/compact/snapshot-f36c91119a98390766ff-parser-1.3.0/`

Incluye los JSON/CSV gzip compactos previos y la carpeta `sports/` con rosters, player statistics, coaches, partidos únicos y observaciones, referencias de movimientos, incidencias, tracking, duplicados, cobertura y resumen. El snapshot final contiene **546 archivos**, **78.727.482 bytes** en total; `sports/` ocupa **688.812 bytes**. Su `dataset_metadata.json.gz` registra el cruce de competición con extracción `044edc9b2ef3c6026c7f`, 760 fixtures, 119 jugados y las marcas temporales fuente.

Los snapshots y exports son inmutables. Durante la validación quedó una exportación intermedia `snapshot-ced99eb5e1d083b36fc8-parser-1.3.0` que tomó por error la extracción Hito 1B más reciente, sin resultados jugados. Se conserva por inmutabilidad, pero **no debe usarse** para este consolidado. El export corregido `snapshot-f36c91119a98390766ff-parser-1.3.0` selecciona el origen con los 119 resultados disputados y es la referencia del informe.

El estado operacional y la lista de URLs capturadas se guardan en el archivo ignorado por Git `data/analysis/bdfutbol/club_team/hito_1d_b2/capture_status.json`. Raw conserva HTML renderizado, inventarios, metadatos y hashes. No se editaron los artefactos de B1 ni los snapshots anteriores.

## Cobertura y limitaciones

- Las 40 parejas de roster/estadísticas concuerdan en sus IDs, con todas las columnas disponibles preservadas.
- Partidos: solo 17/40 vistas `all` válidas por la detención ante HTTP 403; 16 agregados contrastados, 1 diferencia de alcance, 23 clubes sin variante válida.
- Los 51 IDs de partidos Hito 1B aún no observados por fichas de club deben reauditarse cuando el acceso permitido se recupere. No constituyen una lista de IDs definitivamente ausentes de BDFutbol.
- La cobertura de equipo-temporada sigue `BASE_CAPTURED`; esta fase no declara perfiles, temporadas históricas, transferencias ni entidades semánticamente completas.
- No se pidió ninguna variante `pg`, `pe` ni `pp` en esta fase porque `all` es la fuente principal prevista. La comparación sistemática de filtros sigue pendiente.
- No se han normalizado semánticamente las 19 abreviaturas de estadísticas. Los cero apariciones sí están conservados.
- Las cinco membresías de jugador repetidas requieren una auditoría temporal de las páginas de jugador y de sus vínculos, fuera de alcance de B2.
- Las relaciones de movimiento no establecen por sí solas fecha, dirección, naturaleza o confirmación de un fichaje.
- La ronda 5 ausente en Cartagena/Murcia se representa como no publicada/no disponible en esas tablas; no se fabrica dato.

## Recomendaciones para el scraper de perfiles de jugador

1. Reutilizar `player_id` como clave estable y mantener separadas la entidad jugador y cada membresía `player_id` + `team_season_id`.
2. Llevar la URL, snapshot, instante, hash y filas/columnas de origen por cada dato, incluidos alias, dorsal, posición y celdas estadísticas.
3. Tratar la tabla c3p0 como matriz posicional versionada: detectar y conservar encabezados opcionales/vacíos antes de asignar semántica a abreviaturas.
4. Mantener las filas con cero apariciones y representar faltantes como ausentes con valor raw, en lugar de convertirlos a cero.
5. Resolver clubes repetidos con historial de perfil y relaciones fechadas; no colapsar una membresía solo porque un ID aparece en otra plantilla.
6. El descubrimiento de vistas de perfil debe ser un hito independiente: primero catálogo de pestañas/temporadas/filtros y una muestra acotada; no automatizar aún la descarga masiva.

## Comprobaciones

- `PYTHONPATH=src .venv/bin/python -m pytest -q`: **181 passed**.
- Ruff en los archivos modificados: **All checks passed**.
- Ruff global: quedan seis observaciones preexistentes en archivos no modificados (`scripts/probe_bdfutbol_headless.py` E713; imports sin uso en `tests/test_bdfutbol_discovery.py`, `tests/test_browser_runtime.py` y `tests/test_browser_session.py`). No se cambiaron por estar fuera del alcance.
- No se realizó commit ni push.

## Conclusión del hito

La consolidación de plantilla y estadísticas queda estructurada para los 40 equipo-temporada y el cruce de los 68 partidos observados es exacto con Hito 1B. La adquisición de partidos no alcanza 40/40: el desafío HTTP 403 detuvo el flujo tras 17 variantes `all` válidas. Por tanto, el hito queda documentado como **parcial**, con el resto de la cobertura pendiente para cuando exista una vía de acceso autorizada y no bloqueada. No se inicia el siguiente hito.
