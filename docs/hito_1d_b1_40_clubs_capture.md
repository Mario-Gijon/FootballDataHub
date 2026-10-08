# Hito 1D-B1 — Captura de los 40 participantes

**Fecha:** 8 de octubre de 2026 · **Rama:** `rebuild/football-data-hub-v2` · **Estado:** `BASE_CAPTURED`

## Resultado

Se capturaron las 12 vistas base conocidas para los 40 participantes de Primera Federación 2026/27, Grupos I y II: **480 de 480 vistas**, con 40 IDs de equipo-temporada únicos y 40 IDs de club permanente únicos, enlazados desde `team_alignment`. No hubo URL inválidas ni interrupciones de acceso. Cada uno de los 496 snapshots que entró en la consolidación (480 vistas base y 16 variantes de resultados que ya existían de los pilotos) figura como `VALID`, HTTP 200 y pasó la validación de SHA-256/tamaño al cargarse desde raw. Las 480 vistas base tienen `table_integrity_status=VALIDATED`, incluidas las comprobaciones de conservación de celdas raw.

El estado de esta fase es `BASE_CAPTURED`. El export informa **0 entidades `COMPLETE`** a nivel semántico y 80 todavía incompletas para el conjunto de interacciones, temporadas y variantes conocido. La captura de las vistas base no implica cobertura exhaustiva de BDFutbol.

## Fuente y procedimiento

- Participantes y URLs iniciales proceden del `participants.json` real de Hito 1B: `data/parsed/bdfutbol/primera_federacion_2026_27/snapshot-044edc9b2ef3c6026c7f-parser-1.0.0/participants.json` (SHA-256 `e7ebe9121d8f3daf6d2e356b5a51acbc8a4d073d97e7e980ab825211ec5cd4c0`). Comprobado: 20 equipos por grupo, 40 IDs únicos y 40 URLs distintas.
- Adquisición con el `BrowserSessionManager`, `BDFutbolAccess` y Brave/Xvfb/CDP existentes, usando `--reuse --compact-export`. No se leyó ni exportó ninguna cookie o credencial.
- De los 480 URLs base, **408 se capturaron en esta fase** y **72 snapshots se reutilizaron** de los seis pilotos: Lugo, Bilbao Athletic, Cacereño, Villarreal B, Murcia y Jaén (12 por club/equipo-temporada).
- Se usaron diez lotes de cuatro. El intervalo entre la primera y última captura nueva fue 00:46:55 (UTC). El procesamiento sumado de los exports por lote fue 20.9 min; la consolidación final offline tardó 20.8 min.
- No se pidieron filtros de resultados ni se ejecutaron capturas nuevas de sus variantes. Los **16 snapshots de variantes** de filtros de resultados de los pilotos que ya estaban en raw se leyeron y aparecieron en algunos exports de lote y en el consolidado; no son adquisiciones de esta fase.
- No se adquirieron perfiles individuales de jugadores o entrenadores ni fotografías de forma masiva. Las referencias y celdas fuente permanecen en las páginas raw. No se modificó ningún scraper ajeno a clubes/equipos.

## Participantes y correspondencia verificada

### Grupo I

| Pos. | Participante | Equipo-temporada | Club permanente | Vistas base |
|---:|---|---|---|---:|
| 1 | UD Logroñés | `t2026-27178` | `e178` | 12/12 |
| 2 | Lugo | `t2026-2776` | `e76` | 12/12 |
| 3 | Bilbao Athletic | `t2026-2772` | `e72` | 12/12 |
| 4 | Cacereño | `t2026-27149` | `e149` | 12/12 |
| 5 | Ponferradina | `t2026-2762` | `e62` | 12/12 |
| 6 | Mirandés | `t2026-27145` | `e145` | 12/12 |
| 7 | Zamora | `t2026-2795` | `e95` | 12/12 |
| 8 | Racing de Ferrol | `t2026-2748` | `e48` | 12/12 |
| 9 | Real Unión | `t2026-2788` | `e88` | 12/12 |
| 10 | Deportivo Fabril | `t2026-27104` | `e104` | 12/12 |
| 11 | Pontevedra | `t2026-2758` | `e58` | 12/12 |
| 12 | Cultural Leonesa | `t2026-2784` | `e84` | 12/12 |
| 13 | CD Extremadura | `t2026-27515` | `e515` | 12/12 |
| 14 | Mérida AD | `t2026-27359` | `e359` | 12/12 |
| 15 | Unionistas de Salamanca | `t2026-27411` | `e411` | 12/12 |
| 16 | Barakaldo | `t2026-2799` | `e99` | 12/12 |
| 17 | Avilés Industrial | `t2026-2781` | `e81` | 12/12 |
| 18 | CD Coria | `t2026-27473` | `e473` | 12/12 |
| 19 | UD Ourense | `t2026-27510` | `e510` | 12/12 |
| 20 | Arenas de Getxo | `t2026-2787` | `e87` | 12/12 |
### Grupo II

| Pos. | Participante | Equipo-temporada | Club permanente | Vistas base |
|---:|---|---|---|---:|
| 1 | Zaragoza | `t2026-2739` | `e39` | 12/12 |
| 2 | Villarreal B | `t2026-2794` | `e94` | 12/12 |
| 3 | Alcorcón | `t2026-27107` | `e107` | 12/12 |
| 4 | Murcia | `t2026-2740` | `e40` | 12/12 |
| 5 | Jaén | `t2026-2749` | `e49` | 12/12 |
| 6 | Hércules | `t2026-2718` | `e18` | 12/12 |
| 7 | Antequera | `t2026-27140` | `e140` | 12/12 |
| 8 | UD Ibiza | `t2026-27414` | `e414` | 12/12 |
| 9 | Huesca | `t2026-2779` | `e79` | 12/12 |
| 10 | FC Cartagena | `t2026-27176` | `e176` | 12/12 |
| 11 | Atlético Madrileño | `t2026-2767` | `e67` | 12/12 |
| 12 | Real Madrid Castilla | `t2026-2761` | `e61` | 12/12 |
| 13 | Sant Andreu | `t2026-27119` | `e119` | 12/12 |
| 14 | Gimnàstic de Tarragona | `t2026-2717` | `e17` | 12/12 |
| 15 | Algeciras | `t2026-2755` | `e55` | 12/12 |
| 16 | Águilas FC | `t2026-27482` | `e482` | 12/12 |
| 17 | Rayo Majadahonda | `t2026-27227` | `e227` | 12/12 |
| 18 | Europa | `t2026-2789` | `e89` | 12/12 |
| 19 | Teruel | `t2026-27204` | `e204` | 12/12 |
| 20 | Juventud de Torremolinos | `t2026-27488` | `e488` | 12/12 |

## Lotes, tamaños y tiempos

Los tamaños raw de la tabla son el incremento de snapshots nuevos del lote (no vuelven a contar los snapshots reutilizados). El tamaño parsed es el export compacto generado por el CLI para ese lote; sus contenidos pueden incluir vistas reutilizadas y variantes históricas que correspondan a los equipos del lote.

| Lote | IDs de equipo-temporada | Nuevos | Reutilizados | Raw nuevo | Parsed lote | Procesamiento | Variantes históricas leídas |
|---|---|---:|---:|---:|---:|---:|---:|
| batch-01 | `t2026-27178`, `t2026-2762`, `t2026-2739`, `t2026-27107` | 48 | 0 | 150.2 MiB | 7.9 MiB | 130.1 s | 0 |
| batch-02 | `t2026-2776`, `t2026-2772`, `t2026-27149`, `t2026-27145` | 12 | 36 | 35.6 MiB | 9.1 MiB | 160.9 s | 8 |
| batch-03 | `t2026-2795`, `t2026-2748`, `t2026-2788`, `t2026-27104` | 48 | 0 | 151.5 MiB | 8.6 MiB | 148.0 s | 0 |
| batch-04 | `t2026-2758`, `t2026-2784`, `t2026-27515`, `t2026-27359` | 48 | 0 | 138.6 MiB | 7.0 MiB | 121.4 s | 0 |
| batch-05 | `t2026-27411`, `t2026-2799`, `t2026-2781`, `t2026-27473` | 48 | 0 | 130.2 MiB | 6.0 MiB | 102.0 s | 0 |
| batch-06 | `t2026-27510`, `t2026-2787`, `t2026-2794`, `t2026-2740` | 24 | 24 | 53.2 MiB | 6.7 MiB | 113.2 s | 4 |
| batch-07 | `t2026-2749`, `t2026-2718`, `t2026-27140`, `t2026-27414` | 36 | 12 | 102.2 MiB | 8.0 MiB | 138.9 s | 4 |
| batch-08 | `t2026-2779`, `t2026-27176`, `t2026-2767`, `t2026-2761` | 48 | 0 | 154.9 MiB | 8.9 MiB | 147.4 s | 0 |
| batch-09 | `t2026-27119`, `t2026-2717`, `t2026-2755`, `t2026-27482` | 48 | 0 | 142.4 MiB | 7.4 MiB | 124.1 s | 0 |
| batch-10 | `t2026-27227`, `t2026-2789`, `t2026-27204`, `t2026-27488` | 48 | 0 | 109.9 MiB | 3.8 MiB | 66.9 s | 0 |

Total de raw nuevo adquirido: **1168.7 MiB**, en 1632 archivos. La suma de los diez exports por lote es **73.5 MiB**. Estos exports se conservan como resultados de auditoría, junto con versiones previas.

## Cobertura de las vistas y estructura

Las doce vistas base procesadas por participante son:

- **Equipo-temporada:** `team_alignment`, `team_roster`, `team_statistics`, `team_tracking`, `team_transfers`, `team_matches`.
- **Club permanente:** `club_profile`, `club_statistics`, `club_players`, `club_coaches`, `club_matches`, `club_rivals`.

Cada tipo de vista aparece 40 veces en el catálogo global. Las rutas observadas siguen los selectores de vista existentes: en equipo-temporada, `?t=plantilla`, `?t=lista`, `?t=seg`, `?t=altas` y `?tab=partits`; en club, ficha y estadísticas (`?p=stats`), jugadores, entrenadores, partidos y rivales. Los IDs de temporada y permanentes se conservan separados.

Encabezados relevantes comprobados directamente en las tablas raw:

- `team_roster`: dorsal/posición, apodo y nombre, fecha, lugar y provincia de nacimiento; la vista incluye además tabla de entrenadores.
- `team_statistics`: dorsal, apodo, posición, PJ, PT, PC, PS, PX, C, Min, TA, TR, G, Minutos/G, GP, GPP, GE, PG, PE y PP, con fila de totales.
- `team_alignment`: plantel, entrenador y clasificación; `team_matches`: calendario/partidos; `team_tracking`: seguimiento por columnas numeradas; `team_transfers`: movimientos de temporada.
- Las seis vistas de club contienen ficha, estadísticas, goleadores/jugadores, entrenadores, partidos y rivales. La profundidad de tablas y temporadas cambia por club. El `resource_catalog.json.gz` conserva por página los IDs de tablas, encabezados, filas, controles y fuentes.

### Reconciliación de plantillas y excepciones observadas

- **1.039** filas de pertenencia jugador-equipo-temporada; **1.034 IDs de jugador únicos**. Cinco IDs aparecen en más de un equipo-temporada, sin duplicados dentro de una misma plantilla/tabla estadística; se conservan como relaciones independientes, pendientes de una auditoría de transferencias.
- Las plantillas y estadísticas coinciden en IDs para los 40 equipos: cero IDs de roster sin estadísticas, cero IDs de estadísticas sin roster, cero duplicados intraequipo y cero filas estadísticas sin interpretar en las comprobaciones de cobertura.
- Se conservan **179 pertenencias con cero apariciones** (178 IDs de jugador únicos). No se filtraron.
- Se observaron **41 filas/IDs de entrenador actual** entre los 40 equipos: 39 tienen uno y un equipo tiene dos.
- `team_tracking` presenta una variante de encabezado en `t2026-27176` (FC Cartagena) y `t2026-2740` (Murcia): el encabezado numérico contiene `1, 2, 3, 4, 6`, sin columna `5`. Se revisó la estructura raw de ambas páginas: el inventario y las filas están presentes y pasan la integridad raw, pero la vista queda raw-only y su significado no está normalizado. Registrar como variante pendiente para el parsing posterior; no se observó pérdida de celdas ni filas.
- Las tablas de `club_profile` y `club_statistics` presentan diferencias reales entre clubes. Se guardó su contenido fuente y catálogo por página, sin imponer una estructura común ni declarar completitud semántica.

## Relaciones, raw y export consolidado

- El catálogo consolidado cuenta **350,221 entidades de relación** y **401,125 ocurrencias** de procedencia. Las ocurrencias retienen tabla, fila y columna fuente cuando existe.
- El consolidado registra **370,552 filas tabulares** de vistas base y **13,520** de las variantes antiguas. `table_rows.csv.gz` no se generó para evitar un CSV redundante; las páginas HTML renderizadas originales y sus inventarios siguen en raw, y las filas exportadas están en JSON gzip lossless.
- Los 496 directorios de snapshot del alcance (480 vistas base más 16 variantes previas) ocupan **1.42 GiB / 1,524,918,337 bytes**, en 1,986 archivos. La raíz completa `data/raw/bdfutbol/`, que también incluye capturas anteriores ajenas a este lote, ocupa **1.47 GiB**.
- Export global listo para consumo: `data/parsed/bdfutbol/club_team_2026_27/compact/snapshot-142147043b69c03705e8-parser-1.3.0` (**73.3 MiB**). Contiene JSON/CSV gzip compactos, matriz de cobertura, catálogo, relaciones y miembros. La carpeta completa `data/parsed/bdfutbol/club_team_2026_27/` ocupa **1.60 GiB** porque conserva exports y versiones anteriores.
- Manifiesto persistente de este hito: `data/analysis/bdfutbol/club_team/hito_1d_b1_40_clubs/manifest.json` (ignorado por Git, según la política de resultados). Registra estado, lotes, URL nuevas/reutilizadas, rutas de export, IDs, conteos, hashes de origen y medidas por lote.

## Pendiente y límites

Quedan pendientes la normalización semántica completa de varias vistas, la auditoría de temporadas históricas, filtros y controles interactivos, todas las familias de perfiles individuales, imágenes/galerías y las variantes de resultados que no están entre los 16 snapshots antiguos. La columna 5 ausente en dos vistas `team_tracking` requiere determinar si refleja una omisión de categoría de la fuente o una variante por datos disponibles. Las 16 variantes históricas ya detectadas no se consideran cobertura exhaustiva de combinaciones. No se afirma que todas las tablas, temporadas o recursos de BDFutbol estén cubiertos.

## Robustez corregida y comprobaciones

Antes de capturar, se corrigió `discover_latest_snapshots`: ahora valida candidatos del más reciente al más antiguo y recurre al snapshot anterior válido si el último tiene SHA incorrecto, falta de archivos o marca `INCOMPLETE`. Raw no se sobrescribe. La CLI offline/live comprueba vistas, estado `VALID`, relación con club permanente, integridad de tablas y conservación de celdas; una captura parcial falla con estado/exit code distinto de éxito. Esto mantiene separado `BASE_CAPTURED` de cobertura semántica `COMPLETE`.

`capture_status.json` distingue ahora `base_views_raw_integrity_validated` (integridad y celdas raw), `base_views_validated` (vistas semanticamente reconciliadas) y `base_view_pipeline_states` (`PARSED`/`VALIDATED`). Así, una vista que sigue raw-only no reduce el conteo de adquisición válida ni se confunde con una vista interpretada.

- `pytest -q`: **172 passed**.
- Ruff en `scripts/scrape_bdfutbol_club_team.py`, `src/football_data_hub/collectors/bdfutbol_club_team.py` y `tests/test_bdfutbol_club_team.py`: **All checks passed**.
- No se hizo commit ni push.
