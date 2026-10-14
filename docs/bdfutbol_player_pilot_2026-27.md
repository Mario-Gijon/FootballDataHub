# PLAYER-01B — piloto de fichas individuales (2026/27)

**Fecha de captura:** 14 de octubre de 2026  
**Estado:** piloto adquirido y derivación offline válida; no certifica cobertura completa de la carrera ni de partidos individuales.

## Alcance y selección

El piloto utiliza exclusivamente los cuatro IDs confirmados en el inventario offline de PLAYER-01A:

| ID BDFutbol | Nombre visible | Motivo representativo |
| ---: | --- | --- |
| 23751 | Manu Pedreño | Trayectoria larga y dos pertenencias verificadas en el inventario (UD Logroñés, Grupo I; UD Ibiza, Grupo II). |
| 28577 | Nacho Castillo | Jugador de Jaén, Grupo II; ficha con varias filas de carrera. |
| 209629 | Morillas | Carrera corta observada en la tabla de trayectoria. |
| 729168 | Mendinueta | Caso con información incompleta en el inventario; nacimiento y fotografía son nulos. |

No se deduplicó por nombre ni se completaron datos ausentes. El inventario utilizado fue `players.json`, temporada `2026-27`, SHA-256 `d0775229804588ea28d5452944048884ad2f401efcfe23e76fe4cfa3482d5bf4`. El manifiesto externo de la captura conserva esa ruta y huella.

## Navegación y evidencia de acceso

Se reutilizó SeleniumBase Pure CDP con `BrowserSessionManager`, Chromium y el Xvfb administrado por el runtime. El perfil configurado fue el perfil autorizado existente; no se creó un perfil alternativo ni se modificaron credenciales. La captura registra Chromium 152.0.7977.82, resolución 1920×1080 y `uses_xvfb=true`.

Las cuatro vistas consultadas por jugador fueron:

| Vista | URL |
| --- | --- |
| Trayectoria | `/es/j/j{player_id}.html` |
| Estadísticas | `/es/j/j{player_id}.html?p=stats` |
| Partidos | `/es/p/j{player_id}.html` |
| Rivales | `/es/p/jr{player_id}.html` |

Las 16 vistas base necesarias quedaron validadas con HTTP 200, URL final idéntica a la solicitada, título de BDFutbol e identidad comprobada por ID y nombre del inventario. Se hizo una visita base adicional a Partidos de Manu para completar la prueba de filtros: son **17 snapshots base**, no 17 vistas distintas. Además se guardaron **18 variantes de controles**, de las que cuatro conservan una opción «Todos/Todas» y no cuentan como prueba de filtro no predeterminado.

El libro de navegación registra 18 intentos en total: 17 con contenido válido y HTTP 200, y uno con HTTP 200 que el validador clasificó inicialmente como `INVALID_CONTENT`. No fue una denegación ni un desafío. En Rivales de Manu, el título contenía el nombre completo «Antonio Manuel Moñino Pedreño» y no el nombre visible corto; se amplió la validación de identidad para aceptar cualquiera de los dos nombres contrastados con el inventario y la navegación posterior pasó la validación. No se observaron CAPTCHA, desafíos ni respuestas 403/429.

## Controles observados

Los controles, sus valores y todas sus opciones se guardan en `controls_observed` en los metadatos de cada snapshot. En la vista de Manu se observaron estos selectores y cantidades de opciones:

| Vista | Control | Opciones observadas | Valores representativos |
| --- | --- | ---: | --- |
| Trayectoria | `dem` | 5 | `por`, `def`, `mig`, `dav` |
| Trayectoria | `pais` | 17 | `esp`, `eng`, `ger`, `ita` |
| Trayectoria | `sel-equip` | 8 | `209` Almería B, `140` Antequera, `40` Murcia, `451` Tarazona; `-` Todos |
| Trayectoria | `sel-pais` | 3 | España, Eslovenia; `-` Todos |
| Estadísticas | `cats_milestones` | 5 | `2aB`, `1rf`, `CHA`, `CNF`, `COP` |
| Partidos | `jug` | 2 | `si` Partidos jugados, `no` Partidos no jugados |
| Partidos | `pgep` | 3 | `pg`, `pe`, `pp` |
| Partidos | `rival` | 95 | `*` Todos y equipos identificados por valor interno, p. ej. `17` Gimnàstic de Tarragona |
| Partidos | `temp` | 8 | `*` Todas, `2026-27`, `2025-26`, `2024-25` |
| Partidos | `equip` | 8 | `*` Todos y equipos identificados por ID, p. ej. `451` Tarazona |
| Partidos | `comp` | 7 | `*` Todas, `1rf`, `2aB`, `CNF`, `PRF` |
| Rivales | `filtre-cat` | 7 | `2aB`, `PRF`, `1rf`, `COP` |
| Rivales | `filtre-temp` | 8 | `2018-19`, `2021-22`, `2022-23`, `2023-24` |
| Rivales | `filtre-dem` | 5 | `POR`, `DEF`, `MIG`, `DAV` |

También aparecen controles globales de demarcación y país en las vistas. Los filtros se seleccionaron individualmente mediante Playwright/CDP sobre el mismo documento; la URL permaneció igual y no se registraron nuevas entradas de recursos de red. La selección modifica el DOM/estado de controles en la página. En Rivales, los filtros de categoría, temporada y demarcación redujeron el contenido de las tablas en la captura: por ejemplo, categoría `2aB` redujo las filas DOM de `#t5/#t6/#t7` de `1305/90/73` a `501/34/33`; temporada `2018-19`, a `30/3/3`; demarcación `POR`, a `89/90/73`.

En Trayectoria se guardaron `sel-equip=209` y `sel-pais=España`; en Estadísticas, `cats_milestones=1rf`. En Partidos se guardaron selecciones representativas de `jug`, `pgep`, rival, temporada, equipo, competición, demarcación y país. Los metadatos preservan fila base/fila posterior y hash de HTML. Un cambio del hash por sí solo no prueba que cambien datos deportivos: `dem` y `pais` en Partidos cambiaron el estado serializado del documento, pero no las filas observadas. Las variantes con `rival/temp/equip/comp=*` son selecciones por defecto y no se presentan como filtros semánticamente probados.

La exploración demuestra controles y estados de filtro para **un jugador**; no certifica que todas las opciones se comporten igual en otros perfiles ni que cada filtro afecte a todos los paneles de la página.

## Datos normalizados del piloto

Cada snapshot se parsea con un contrato distinto (`PlayerTrajectoryPage`, `PlayerStatisticsPage`, `PlayerMatchesPage` o `PlayerRivalsPage`). Se conservan ID de jugador, URL solicitada y final, título original, tablas y celdas fuente, relaciones, controles, parámetros de filtro, cobertura y procedencia. La vista de Partidos mantiene separados los resúmenes agregados y los encuentros individuales.

| ID | Trayectoria: filas de carrera | Estadísticas: filas normalizadas | Partidos: filas de resumen | Encuentros individuales | Rivales normalizados |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 23751 | 10 | 93 | 114 | 0 | 1464 (1303 jugadores, 89 entrenadores, 72 clubes) |
| 28577 | 5 | 94 | 72 | 0 | 1077 (965 jugadores, 62 entrenadores, 50 clubes) |
| 209629 | 3 | 96 | 52 | 0 | 549 (488 jugadores, 31 entrenadores, 30 clubes) |
| 729168 | 1 | 79 | 4 | 0 | 0 observados en las tablas base |

En los cuatro HTML de Partidos, `#tpartits` sólo contenía encabezados; por eso no se inventaron encuentros y `individual_matches` queda vacío. Las tablas agregadas estaban presentes. El cero de Rivales de Mendinueta describe las tablas base capturadas y no demuestra ausencia universal: no se probaron variantes de sus filtros. Las estadísticas de hitos pueden no aparecer en todos los jugadores.

## Almacenamiento, integridad y recuperación

Los archivos se almacenan fuera de Git:

`$HOME/FootballDataHub-data/players/player-captures/20261014T133920.712440Z-bf7bc8e4/`

Cada snapshot tiene `raw/source.html.gz`, metadatos JSON y SHA-256 del HTML descomprimido. Los HTML originales no se modificaron. La derivación más reciente es:

`normalized/derivations/20261014T135805.075764Z-1.0.0-bb689492-4338c524/`

La derivación contiene un JSON por snapshot, `manifest.json` y `validation/results.json`. Resultado: **35/35 snapshots parseados, 0 errores, estado `valid`**, parser `1.0.0`. El validador verifica hash del HTML, identidad, ID, vista, URL, HTTP 200 y marcadores estructurales. El manifiesto conserva hashes, tiempos y eventos de navegación; el informe de validación distingue errores de contenido de respuestas de acceso.

La adquisición guarda el HTML antes de parsear; por eso un fallo posterior de parser no elimina la evidencia. Los runs usan un `capture_id` y se pueden reanudar sólo reutilizando snapshots con URL, estado y hash válidos. Cada exportación crea una derivación nueva, sin sobrescribir derivaciones anteriores.

## Ejecución

Desde la raíz del proyecto, el preflight offline de los cuatro IDs es:

```bash
PYTHONPATH=src .venv/bin/python scripts/acquire_bdfutbol_player_pilot.py \
  --dry-run --player-id 23751 --player-id 28577 \
  --player-id 209629 --player-id 729168
```

La adquisición real controlada —sólo si está autorizada y no hay una denegación— utiliza la misma CLI, sin `--dry-run`; por defecto es secuencial y espera cinco segundos entre navegaciones. Rutas configurables:

- `FDH_PLAYER_INVENTORY`
- `FDH_PLAYER_CAPTURE_ROOT`
- `FDH_BDFUTBOL_PROFILE`

La relectura y exportación offline de una captura se realiza así:

```bash
PYTHONPATH=src .venv/bin/python scripts/parse_bdfutbol_player_capture.py \
  --capture-id 20261014T133920.712440Z-bf7bc8e4
```

No requiere navegador ni red.

## Estado y límites

**Explorado y verificado:** cuatro vistas base de los cuatro IDs, controles y opciones observados en Manu, variantes seleccionadas sin navegación adicional, identidad, URL, HTTP, hashes, recuperación gzip y parsing offline de las 35 capturas.

**Parcial:** filtros sólo explorados en Manu; cobertura de trayectoria y estadísticas refleja el snapshot, no exhaustividad certificada; Rivales de Mendinueta tiene cero filas en la vista base.

**Pendiente:** ampliar filtros a otros perfiles; averiguar si la tabla de Partidos puede revelar encuentros individuales mediante una variante adicional autorizada; validar alcance temporal de cada resumen, enlaces/relaciones de cada tipo de fila y comportamiento de todas las opciones de controles. El piloto no implementa API, frontend ni adquisición de todos los jugadores.
