# Hito 1E-B1-J — Ampliación controlada del piloto de jugadores

**Fecha:** 9 de octubre de 2026 · **Rama:** `rebuild/football-data-hub-v2`

**Alcance live:** `j26481` y `j100160`, cuatro vistas canónicas por jugador.
**Resultado:** ocho capturas `VALID`, parseadas y contrastadas; sin cambios al scraper ni al parser.

## Acceso y adquisición

Se revisaron los informes de los hitos 1E-B1-G, H e I, el CLI y el colector actuales. El inventario previo, comprobado con `dry-run`, contenía 15 jugadores y 60 vistas: las cuatro vistas de Manu (`j23751`) y Morillas (`j209629`) ya eran válidas. No había snapshots para los dos IDs de este hito. El dry-run confirmó `browser_started=false` y `network_requested=false`.

La adquisición se hizo con los comandos del proyecto, que usan `BrowserRuntimeConfig`, `BrowserSessionManager`, Brave externo bajo Xvfb, conexión Playwright CDP y `BDFutbolAccess`. Se utilizó el perfil existente `~/.football-data-hub-v2-probe` mediante el valor por defecto del CLI. Antes de abrirlo no se encontró Brave, Xvfb ni un scraper activo; el runtime obtuvo su lock normalmente. No se borraron locks ni se leyeron o exportaron cookies o credenciales. No se cambió navegador, IP, perfil ni identidad y no se usó un cliente HTTP alternativo.

Se adquirieron primero ambos perfiles y se validaron offline antes de pedir las demás vistas. Después se capturaron Estadísticas, Partidos y Rivales de cada jugador. Fueron ocho navegaciones de documentos deportivos, sin reintentos. Todas devolvieron HTTP 200, estado `VALID`, URL final exacta, ID de jugador coincidente, hash íntegro y tablas requeridas presentes. No apareció desafío ni respuesta inválida. `--screenshot` guardó una captura visual con cada perfil.

El intervalo entre la primera y la última captura fue de **2 min 49 s**. Los valores de fecha son UTC.

| Jugador / vista | URL | Captura UTC | HTML (bytes) | SHA-256 |
|---|---|---|---:|---|
| `j26481` · perfil | `https://www.bdfutbol.com/es/j/j26481.html` | `2026-10-09T10:42:53.349859Z` | 967.084 | `8e8ea798a7fc604bf39e2bf4bc609a2276fd4b680dd6d69875115e08b0c4ec9f` |
| `j26481` · estadísticas | `https://www.bdfutbol.com/es/j/j26481.html?p=stats` | `2026-10-09T10:43:54.965897Z` | 963.834 | `b718ab2948a3b0b10e2ca9a126d1e0e76fef7eef314498caf05d65a24a0692a2` |
| `j26481` · partidos | `https://www.bdfutbol.com/es/p/j26481.html` | `2026-10-09T10:43:57.019759Z` | 959.251 | `2343dae2112ccd43e94c49717b3786efd9d6f0ffd5363b78a219c803f7df32a3` |
| `j26481` · rivales | `https://www.bdfutbol.com/es/p/jr26481.html` | `2026-10-09T10:43:59.863715Z` | 1.996.911 | `a24f3ddf130b533920b0f48860391860415ae7da2c0417454323069176a7e26b` |
| `j100160` · perfil | `https://www.bdfutbol.com/es/j/j100160.html` | `2026-10-09T10:43:30.867918Z` | 1.068.070 | `1c564a32fab0b487e1ade60dc76bf9676357e5b360c9f6b7b5596e0dd8e250e7` |
| `j100160` · estadísticas | `https://www.bdfutbol.com/es/j/j100160.html?p=stats` | `2026-10-09T10:45:33.432854Z` | 1.011.658 | `4d01000c4a8c28e724c79a467dd65bcfc58689b81049e7e82f2afd84ef7257f8` |
| `j100160` · partidos | `https://www.bdfutbol.com/es/p/j100160.html` | `2026-10-09T10:45:35.689444Z` | 1.183.193 | `1f8ec5d27d4925beb0625db10208dbc9293644709689bacc192e38957e672561` |
| `j100160` · rivales | `https://www.bdfutbol.com/es/p/jr100160.html` | `2026-10-09T10:45:42.419288Z` | 6.754.693 | `a6ca9f42635c5504a9824a95224f9a263b9e97d2b63d1a70195a2937935642f3` |

Los raws están bajo `data/raw/bdfutbol/20261009T104245.896210Z/j26481/`, `data/raw/bdfutbol/20261009T104348.396472Z/j26481/`, `data/raw/bdfutbol/20261009T104323.296624Z/j100160/` y `data/raw/bdfutbol/20261009T104526.856113Z/j100160/`. Cada snapshot conserva `rendered.html`, inventario DOM, resumen y metadata. Los perfiles también conservan `screenshot.png`. Las ocho capturas suman **24.014.192 bytes** en **34 archivos**; el HTML suma 14.904.694 bytes. Todas las metadata marcan `BASELINE_CAPTURE`; no existía snapshot anterior para estos IDs.

## Resultados por jugador

### `j26481` — Sergi Armero Montané

**Perfil:** el título identifica a Sergi Armero y el `h1` muestra «Armero». El parser reconoce nombre completo, nacimiento `22/04/2002`, lugar `Lleida ( Lleida )`, país `España`, demarcación `Delantero`, altura `186 cm` y peso `75 kg`. `.traject` tiene seis filas de carrera y conserva valores `0`, guiones, cabeceras, celdas ocultas y enlaces a equipo-temporada. Las filas observadas son Lleida Esportiu (2019-20); Huesca y Recreativo de Huelva (2024-25); Tarazona (2025-26); Huesca y Sant Andreu (2026-27). El roster del Hito 1D confirma para 2026-27 Huesca con cero apariciones y Sant Andreu con cuatro. Son dos pertenencias de temporada; no se interpreta una como traspaso confirmado. El parser deja la carrera como `NOT_CERTIFIED_COMPLETE`. Se conservaron tres referencias a fotos del jugador; no se descargaron imágenes.

**Estadísticas:** las tablas requeridas están presentes. El parser conserva 64 filas por competición, 21 por equipo y cuatro filas de hitos (89 filas interpretadas en total). En `Partidos Jugados`, el HTML muestra 67 bajo `1ªRf` y 1 bajo Copa; los valores por equipo incluyen 4 para Sant Andreu y cero para Huesca. Las celdas raw, incluidos ceros y guiones, no se colapsan entre sí.

**Partidos:** `#tpartits` solo tiene cabecera; la vista base contiene `window.P` con **159 tuplas de 27 campos**. Se interpretaron 68 registros con flags de participación y 91 sin participación. Hay 158 IDs de partido distintos: el ID `272517` aparece dos veces con valores de lado/equipo diferentes. Ambas filas describen Huesca–Sant Andreu el 29/08/2026, se conservan separadas y no se deduplican; corresponden a las dos pertenencias observadas y ambas indican no participación. La página contiene resúmenes por competición (4 filas), temporada (4), equipo (5) y rival (32). Los 12 registros raw de 2026-27 —11 IDs únicos por la duplicación anterior— coinciden en fecha, equipos y marcador con el export de competición del Hito 1B. En el export de partidos de clubes del Hito 1D estaban disponibles dos de esos 12 registros; ambos coincidieron exactamente. Los otros diez no están en ese export conservado, por lo que esa comparación de equipos queda parcial.

**Rivales:** se interpretaron 672 filas enlazadas a jugadores, 48 a entrenadores y 27 a clubes. Todas tienen ID y no se detectaron IDs repetidos dentro de cada tabla de esta captura. Son ocurrencias de fuente, no certificación de cobertura completa.

### `j100160` — Unai Medina Pérez

**Perfil:** el `h1` identifica a Unai Medina. El parser reconoce nombre completo, nacimiento `16/02/1990`, lugar `Basauri ( Bizkaia )`, país `España`, demarcación `Lateral derecho`, altura `177 cm` y peso `78 kg`. `.traject` presenta 20 filas, desde 2008-09 hasta 2026-27, con clubes/equipos enlazados por temporada. En 2026-27 aparece Real Unión (`t2026-2788`). No se certifica que las 20 filas completen toda su carrera. Se conservaron nueve referencias a fotos del jugador, sin descargarlas.

El DOM tiene una tabla deportiva adicional que no aparecía en el perfil de Armero: una fila dice «1 Campeón absoluto de 1a RFEF: 2021-22». El parser la conserva como `additional_sports_table` raw, sin asignarle un contrato de premio. También aparece la columna raw `G5` en la tabla de estadísticas por competición; su código queda sin interpretar. Son diferencias de contenido, no una nueva forma de `window.P`.

**Estadísticas:** las tablas requeridas están presentes. Se conservan 66 filas por competición, 22 por equipo y 14 de hitos (102 filas interpretadas). La vista de temporada/equipo incluye Real Unión. La tabla de competición tiene columnas raw diferentes de las de Armero, incluyendo `G5`; no se infiere su significado.

**Partidos:** `#tpartits` conserva solo cabecera; `window.P` tiene **789 tuplas**, todas de 27 campos y con 789 IDs únicos. Los flags indican 463 registros con participación y 326 sin ella. Hay registros de 2008-09 a 2026-27; los códigos de competición permanecen raw. Los seis partidos de 2026-27 coinciden exactamente por ID, fecha, equipos y marcador con los exports de competición y de equipos. Cuatro indican participación, de acuerdo con las cuatro apariciones del roster de Real Unión. No se convierte la cantidad total de tuplas en partidos disputados.

**Rivales:** se interpretaron 3.216 filas enlazadas a jugadores, 223 a entrenadores y 115 a clubes. En esta captura todas las filas tienen ID y no se detectaron IDs repetidos dentro de las tres tablas.

## Comparación, estructura y límites

Los dos nuevos perfiles pasan por el mismo contrato que Manu y Morillas: identidad en URL, tablas de vista requeridas y hash verificado. El extractor leyó la misma anchura de 27 campos observada en los raws anteriores de `window.P`. Armero aporta 159 registros y Medina 789, frente a 259 de Manu y 81 de Morillas; la diferencia es cobertura histórica/contenido de cada ficha, no una diferencia de formato. Para los cuatro jugadores ya hay **1.288 filas** provenientes de `window.P` en el export 0.2.3.

La vista canónica no materializa filas de detalle en `#tpartits` para ninguno de los dos; el parser obtiene los encuentros de `window.P` y conserva las celdas de las tablas de resumen aparte. Las flags del jugador distinguen participación de no participación. Las filas duplicadas de Armero se conservan; no se corrigen como si fueran errores sin evidencia. No se abrieron filtros ni se capturaron variantes: los filtros ya investigados en Hito H no se repitieron.

No se descargaron fotos, no se recorrieron galerías ni se adquirieron perfiles relacionados. Las referencias de foto proceden del HTML, no prueban que cada recurso multimedia siga disponible. Los campos ausentes o los años no mostrados no se interpretan como inexistencia real. No se certifica la trayectoria completa de ninguno.

## Reuso, export y refresco

Se repitió el comando live de los dos IDs sin `--refresh`. El colector devolvió **ocho `REUSED_VALID`**, con las mismas rutas y SHA-256. Como no había vistas pendientes, la ruta de reuso termina antes de crear `BrowserSessionManager`; no abrió navegador ni generó tráfico.

El reprocesamiento se ejecutó offline con:

```bash
PYTHONPATH=src .venv/bin/python scripts/parse_bdfutbol_players_offline.py
```

Export inmutable creado:

`data/parsed/bdfutbol/player_2026_27/compact/snapshot-15f51d388babb50a2cc7-parser-0.2.3/`

Contiene 47 archivos y ocupa **6.197.831 bytes**. El resumen registra 16 páginas base parseadas, 1.288 encuentros de `window.P`, 364 filas agregadas de partidos, 382 estadísticas, 39 filas de trayectoria, 6.286 registros de rivales y una variante filtrada anterior. Los exports 0.2.2 y 0.2.3 previos siguen existiendo; no se sobrescribieron.

La planificación actual informa 15 pilotos, 60 vistas, 16 capturadas y **44 pendientes**. El dry-run con `--refresh` marca 16 vistas existentes como `REFRESH_PENDING` y 44 como `PENDING_CAPTURE`, sin navegador ni red. No se ejecutó un refresh live porque las capturas recién adquiridas no lo necesitan. El CLI admite `--refresh` para guardar un nuevo snapshot sin sobrescribir el anterior y clasificarlo como `UNCHANGED` o `CHANGED`; no se observaron esos estados en este hito porque las ocho capturas son baselines.

Comandos utilizados/reproducibles para estos dos jugadores:

```bash
# Capturar primero los perfiles y validar/parsing antes de continuar.
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py live \
  --player-id j26481 --view profile --screenshot
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py live \
  --player-id j100160 --view profile --screenshot

# Tras validar los perfiles, capturar las otras tres vistas.
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py live \
  --player-id j26481 --view statistics --view matches --view rivals
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py live \
  --player-id j100160 --view statistics --view matches --view rivals

# Forzar snapshots nuevos, siempre en directorios inmutables.
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py live \
  --player-id j26481 --view profile --refresh
```

El comando de reuso comprobado fue:

```bash
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py live \
  --player-id j26481 --player-id j100160
```

## Estado de los 15 pilotos

| ID | Estado de vistas base |
|---|---|
| `j23751` | 4/4 capturadas y parseadas |
| `j26481` | 4/4 capturadas y parseadas |
| `j100160` | 4/4 capturadas y parseadas |
| `j209629` | 4/4 capturadas y parseadas |
| `j100350` | 0/4; pendiente |
| `j100397` | 0/4; pendiente |
| `j101816` | 0/4; pendiente |
| `j102284` | 0/4; pendiente |
| `j103389` | 0/4; pendiente |
| `j108959` | 0/4; pendiente |
| `j304209` | 0/4; pendiente |
| `j304291` | 0/4; pendiente |
| `j402372` | 0/4; pendiente |
| `j1000865` | 0/4; pendiente |
| `j1014877` | 0/4; pendiente |

El conjunto de 1.034 jugadores conserva 4.136 vistas esperadas; el export actual informa 16 parseadas y 4.120 pendientes. La cobertura de carrera completa sigue sin certificarse.

## Validación y recomendación

No se detectó un fallo del colector, una identidad incorrecta, tablas requeridas ausentes ni cambios de ancho en `window.P`; por ello no se modificó código ni se añadieron pruebas con fixtures artificiales. Las variaciones observadas se conservaron raw.

**Recomendación: GO para el siguiente lote pequeño de dos jugadores**, empezando por `j100350` y `j100397`, que son los dos siguientes IDs del inventario y representan códigos raw de posición distintos (`10` y `3`). Mantener captura escalonada de perfil, validación offline, y luego las tres vistas restantes; detener ante cualquier desafío o respuesta inválida. Esto no autoriza adquisición masiva.

## Comprobaciones finales

- Suite completa con permiso para el socket loopback local: **241 passed**. El intento dentro del sandbox tuvo 240 pasadas y una falla ambiental (`PermissionError` en `test_loopback_port_valid`); la repetición autorizada no hizo peticiones externas.
- Ruff sobre el colector, parser, CLI y pruebas relacionadas con jugadores: **All checks passed**.
- `ruff check .` detecta seis incidencias preexistentes fuera de los archivos de este hito: `E713` en `scripts/probe_bdfutbol_headless.py` y cinco imports `F401` en `tests/test_bdfutbol_discovery.py`, `tests/test_browser_runtime.py` y `tests/test_browser_session.py`. No se modificaron esos archivos.
- `git diff --check`: sin errores.
- No se hizo commit ni push.
