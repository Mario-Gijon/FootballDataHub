# Hito 1D-B0 — robustez y preparación para los 40 participantes

**Fecha:** 8 de octubre de 2026  
**Rama:** `rebuild/football-data-hub-v2`  
**Alcance:** Primera Federación 2026/27; seis equipos piloto (cuatro previos y dos nuevos).

## Decisión

**GO condicionado para empezar la captura de las 12 vistas base por participante de los 40 equipos**, usando lotes pequeños, `--reuse` por defecto, export compacto y revisión del estado de captura antes de reanudar. La captura debe parar al primer resultado distinto de `VALID`; no se debe tratar una parada por desafío como un lote completo.

**NO-GO para declarar las entidades completamente interpretadas.** En el piloto, las vistas base están presentes, pero quedan filtros, variantes, campos solo raw y relaciones sin reconciliar. `BASE_CAPTURED` describe que existen las vistas base; `COMPLETE` requiere que también se cierre el alcance semántico documentado. Ahora hay cero entidades `COMPLETE`.

Este GO autoriza iniciar la adquisición por lotes, no afirma que los exports resultantes cubran todas las vistas históricas o interacciones de BDFutbol.

## Cambios realizados

- `src/football_data_hub/parsers/club_team_coverage.py`: los estados de cobertura se calculan a partir de vistas capturadas, integridad de tablas, relaciones, campos raw-only y controles pendientes. Se separan `base_capture_status`, `interpretation_status` y estado de entidad. Los estados incluyen `BASE_CAPTURED`; una entidad solo queda `COMPLETE` cuando cierra los criterios del alcance. La cobertura de partido valida los resultados `all`, `pg`, `pe` y `pp` contra los agregados de temporada, IDs únicos y unión/disyunción de resultados. Un cero, como `PP=0`, es válido si la tabla filtrada está presente y concuerda con el agregado.
- `src/football_data_hub/collectors/bdfutbol_club_team.py` y `providers/bdfutbol/club_team.py`: los filtros son genéricos por club y competición. Los snapshots existentes válidos se reutilizan; las capturas refrescadas reciben directorios únicos y nunca reemplazan snapshots raw anteriores.
- `scripts/scrape_bdfutbol_club_team.py`: modos `live` con reutilización predeterminada, `live --refresh` explícito y `offline` sin red. Se puede solicitar la familia de variantes de resultado con `--match-result-filter all|pg|pe|pp`.
- `src/football_data_hub/storage/club_team_exports.py`: salida compacta opcional con gzip determinista y sin pérdida. JSON por página, celdas fuente, relaciones y procedencia se conservan; las filas tabulares duplicadas se omiten por defecto en compact y pueden añadirse con `--include-table-csv`. El export legacy sin compresión sigue disponible y los exports anteriores permanecen intactos.
- Se añadieron pruebas para filtros y reconciliación, cero resultados, cambios de estado, dos participantes de estructuras distintas, filas de sección con `colspan=100`, export gzip, colisión de directorio raw, reutilización, refresco y modos CLI.

No se modificaron scrapers ajenos a este alcance, el Dev Explorer, el Hito 1B ni los snapshots raw existentes. No se añadieron dependencias.

## Acceso y ejecución

Las adquisiciones live reutilizaron `BrowserSessionManager`, `BDFutbolAccess`, Brave/Xvfb/CDP y el perfil persistente configurado. No se leyeron ni exportaron cookies o credenciales, no se intentó eludir Cloudflare y no apareció `CHALLENGE_REQUIRED`. Las capturas nuevas fueron `VALID`, HTTP 200.

Los `capture_status.json` de ambas corridas están en `data/analysis/bdfutbol/club_team/20261008T155511.284304Z/` y `data/analysis/bdfutbol/club_team/20261008T155936.945089Z/`. El reprocesamiento consolidado quedó en `data/parsed/bdfutbol/club_team_2026_27/compact/snapshot-aeca1cd464382cc1ead1-parser-1.3.0/`.

### Dos participantes nuevos

La selección se hizo desde `participants.json` del Hito 1B:

| Grupo | Participante | Posición de la captura | ID equipo-temporada | ID de club |
|---|---|---:|---|---|
| I | Cacereño | 4 | `t2026-27149` | `e149` |
| II | Murcia | 4 | `t2026-2740` | `e40` |

Se capturaron sus seis rutas de equipo-temporada y seis del club permanente relacionado: **24 vistas base** en `data/raw/bdfutbol/20261008T155328.317550Z/` (96 archivos, 88 MiB según `du -sh`). Las seis vistas de cada club piloto anterior se reutilizaron desde snapshots válidos; no se volvieron a descargar ni sobrescribir.

### Filtros de partidos

En la segunda ejecución se pidieron `all`, `pg`, `pe` y `pp` para Jaén, Villarreal B, Lugo y Bilbao Athletic. Se procesaron 64 snapshots: 48 vistas base reutilizadas, la variante `pg` de Jaén reutilizada y 15 variantes de resultado capturadas en `data/raw/bdfutbol/20261008T155847.712281Z/` (60 archivos, 43 MiB según `du -sh`). La URL usa `cat=1rf&temp=2026-27`; `all` omite `pgep` y los otros valores son `pgep=pg|pe|pp`.

| Equipo | PJ en BDFutbol | Ganados | Empatados | Perdidos | IDs únicos recuperados |
|---|---:|---:|---:|---:|---:|
| Jaén | 6 | 3 | 2 | 1 | 6 |
| Villarreal B | 6 | 4 | 1 | 1 | 6 |
| Lugo | 6 | 5 | 1 | 0 | 6 |
| Bilbao Athletic | 6 | 3 | 2 | 1 | 6 |

Para los cuatro equipos, la unión de victorias, empates y derrotas coincide con la vista general `all` y con `PJ`; no hay IDs repetidos entre resultados. El caso Lugo confirma que un filtro de derrotas con cero filas deportivas es correcto porque `PP=0` en el agregado. No se capturaron variantes de resultado para Cacereño ni Murcia; sus alcances de partidos siguen incompletos.

Se cruzaron los **24 partidos disputados** con el calendario parsed de Hito 1B: **0 partidos ausentes, 0 IDs adicionales y 0 diferencias de ID o denominación de equipos**. Esta comparación solo cubre partidos disputados incluidos en las capturas, no los encuentros futuros todavía programados.

### Reutilización, refresco y modo offline

- `reuse`: ejecutado en ambas adquisiciones. Reutilizó snapshots válidos por URL y capturó únicamente las rutas/variantes que faltaban.
- `refresh`: `--refresh` fuerza una captura aunque haya una URL válida en caché. Las pruebas verifican que el directorio previo conserva su contenido y que la nueva corrida reserva un destino raw distinto. No se forzó una recaptura de red de páginas ya válidas durante esta auditoría.
- `offline`: el reprocesamiento de las 72 vistas base y 16 variantes se ejecutó sin red. Tardó **260,37 s** en la exportación compacta de seis pilotos. Una ejecución detenida por acceso no válido conserva lo ya capturado para este reprocesamiento.

## Cobertura de los seis pilotos

Cada participante tiene seis vistas de equipo-temporada y seis vistas del club: perfil/trayectoria, estadísticas, jugadores, entrenadores, partidos y rivales en el club; alineación, plantilla, estadísticas, seguimiento, altas/bajas y partidos en equipo-temporada. El export consolidado tiene **72/72 snapshots base accesibles y 16/16 variantes de resultado observadas**. Las seis vistas por entidad superan las comprobaciones estructurales de tabla; el pipeline marca **36 vistas `VALIDATED` y 36 `PARSED`**, y solo las 12 vistas de plantilla/estadísticas de los seis equipos quedan `COMPLETE` dentro del alcance 2026/27. Las 12 entidades quedan `BASE_CAPTURED`; ninguna es semánticamente `COMPLETE`. Las plantillas y estadísticas reconcilian cada ID de jugador de una vista con la otra. No se descargaron historiales de perfil individuales.

| Grupo | Equipo | Vistas base equipo/club | Jugadores en plantilla | Filas de estadísticas | Cero apariciones |
|---|---|---:|---:|---:|---:|
| II | Jaén | 6/6 + 6/6 | 25 | 25 | 4 |
| II | Villarreal B | 6/6 + 6/6 | 26 | 26 | 5 |
| I | Lugo | 6/6 + 6/6 | 30 | 30 | 6 |
| I | Bilbao Athletic | 6/6 + 6/6 | 28 | 28 | 5 |
| I | Cacereño | 6/6 + 6/6 | 25 | 25 | 4 |
| II | Murcia | 6/6 + 6/6 | 29 | 29 | 7 |
| **Total** | | **72 vistas** | **163** | **163** | **31** |

Se conservan 163 IDs de jugador y seis IDs de entrenador de temporada. La relación jugador-equipo de roster y estadísticas quedó reconciliada; las demás relaciones históricas no se consideran verificadas por extensión. Se encontró variación real entre páginas, procesada con los mismos extractores: Cacereño tiene 25 filas de seguimiento y siete columnas; Murcia, 29 filas y seis columnas. Ambos tienen vistas de altas/bajas con tablas deportivas, por lo que no se marcaron como ausentes.

## Comprobación de tablas y datos

- Las filas de plantilla y estadísticas 2026/27 coinciden con las filas deportivas del HTML; se excluye la fila de total al contar jugadores, pero se conserva en los artefactos de página. Los IDs de jugador de roster y estadísticas coinciden exactamente por equipo y no se detectaron filas estadísticas sin interpretar.
- Las tablas de alineación incluyen una fila de sección «Suplentes» con `colspan=100`. Se preserva como fila raw de sección; no se cuenta como jugador ni como 100 columnas deportivas. La comprobación cuenta filas de sección separadas de las filas deportivas.
- Los JSON por página guardan encabezados, filas/celdas, texto original, enlaces e imágenes junto al HTML raw. La cobertura diferencia `structured_source_headers` de `raw_only_headers`; conservar una tabla no se considera haber interpretado sus campos.
- En las páginas de entrenadores, el origen presenta 25 encabezados pero omite las dos celdas finales `Altura` y `Peso` en sus filas. La omisión se registra como `TRAILING_COLUMNS_OMITTED`; no se generan nulos ni se desplazan columnas. En las seis muestras hay 68, 14, 52, 33, 43 y 109 filas de entrenadores, respectivamente.
- En una fila secundaria de la tabla de transferencias de Cacereño y Murcia falta una celda al final sin encabezado fuente. Se conserva la omisión por índice y tabla; no se le asigna un significado deportivo inventado.
- Las 18 tablas de hitos y eventos, las tablas históricas, galerías/fotografías, gráficos y todas las variantes de filtros no quedan interpretadas por el mero hecho de estar contenidas en raw.

## Datos históricos y controles pendientes

Se conservaron en raw las páginas iniciales de histórico de jugadores, entrenadores, estadísticas, partidos y rivales. Recuento de filas históricas en las tablas principales de jugadores/entrenadores:

| Club | Jugadores históricos | Entrenadores históricos | Rivales: jugadores / entrenadores / clubes |
|---|---:|---:|---:|
| Jaén | 918 | 68 | 9.903 / 682 / 251 |
| Villarreal B | 359 | 14 | 4.130 / 279 / 124 |
| Lugo | 706 | 52 | 8.253 / 572 / 201 |
| Bilbao Athletic | 676 | 33 | 9.498 / 663 / 210 |
| Cacereño | 682 | 43 | 6.591 / 454 / 223 |
| Murcia | 1.422 | 109 | 14.164 / 973 / 261 |

Los selectores de competición, país, temporada, demarcación y categoría están presentes en el HTML, y sus opciones varían por club. En páginas del Hito 1D-A2 se observaron: 13/7/9/9/11/14 opciones de competición en históricos de jugadores; 5/3/5/2/3/10 países en entrenadores; y 12/6/8/8/10/13 combinaciones disponibles de competición en Rivales. Esas cifras describen opciones presentes, no combinaciones recorridas en este hito.

Los siguientes controles siguen pendientes o se sustentan solo en artefactos previos (`ARTIFACT_ONLY`):

- Aplicar filtros representativos de competición/país/posición para jugadores y entrenadores; comprobar explícitamente si producen datos nuevos en servidor.
- Probar una muestra de competición/temporada/demarcación de Rivales y categorías de Estadísticas del club.
- Seleccionar los modos de Seguimiento y temporadas históricas de equipo en una futura auditoría acotada.
- Completar reconciliación de relaciones de todas las vistas y decidir el alcance histórico final de `COMPLETE`.
- Las interacciones de columnas de Plantilla/Estadísticas y los modos de presentación previamente observados conservaron datos en el DOM y no mostraron petición deportiva; esto procede de la evidencia de Hito 1D-A2, no se repitió durante esta ejecución.

Por ello la matriz marca las entidades del piloto `BASE_CAPTURED` / `PARTIAL_RAW_PRESERVED`, no `COMPLETE`. Los campos cuyo valor no figura en el HTML se documentan como omisiones de origen y no como fallo de adquisición.

## Almacenamiento y compatibilidad

El export legacy de cuatro equipos de parser 1.2.0 ocupa **647.629.555 bytes (618 MiB)** y sigue intacto. Los componentes mayores son:

| Componente legacy | Bytes |
|---|---:|
| JSON completos por página | 384.762.219 |
| `table_rows.csv` con filas ya presentes en JSON de página | 193.658.619 |
| `relationships.json` | 33.276.869 |
| `relationships.csv` | 13.907.929 |

El export gzip de cuatro pilotos medido en `/tmp/fdh-b0-pilot-match-exports/compact/snapshot-704a16d33246aabc5b9a-parser-1.3.0/` ocupa **17.875.617 bytes (18 MB)**, con 48 vistas base y 16 variantes de partidos; esa ejecución también llevaba CSV tabular comprimido. Es una reducción aproximada de **36 veces (97,2 %)** frente al export legacy, aun llevando más variantes. El export compacto final de seis pilotos, en `data/parsed/bdfutbol/club_team_2026_27/compact/snapshot-aeca1cd464382cc1ead1-parser-1.3.0/`, mide **16.215.647 bytes (16 MB)** para 72 vistas base y 16 variantes; su tiempo offline fue **260,37 s (4 min 20 s)**. El writer compacto actual crea 101 archivos gzip y no incluye `table_rows.csv.gz` ni `variant_table_rows.csv.gz` redundantes por defecto. Esta segunda comparación tiene más entidades que el legacy, por lo que los tamaños no son una comparación de idéntico alcance.

La compresión gzip conserva los bytes serializados; los JSON de página siguen siendo la representación completa. El export compacto no emite los CSV de filas que duplican esos valores, salvo petición explícita con `--include-table-csv`. Las salidas se escriben en rutas derivadas de snapshots y versiones; el formato y las rutas legacy siguen compatibles. El 618 MiB antiguo no se borró.

## Tests y lint

- `.venv/bin/python -m pytest -q`: **168 passed**. Se permitió el socket loopback local que necesita `test_browser_runtime`; no se usó red externa.
- `.venv/bin/ruff check` en los seis archivos modificados: **All checks passed**.
- `.venv/bin/ruff check .`: informa seis problemas en archivos no modificados por este trabajo: E713 en `scripts/probe_bdfutbol_headless.py`; F401 en `tests/test_bdfutbol_discovery.py`, `tests/test_browser_runtime.py` (tres imports) y `tests/test_browser_session.py`. No se alteraron esas áreas ajenas al encargo.

## Conclusión operativa

**GO**: comenzar las capturas base de los 40 participantes por lotes pequeños, apoyándose en snapshots reutilizables, estados de captura, directorios raw únicos y procesamiento offline. Revisar el resultado de cada lote y reanudar desde snapshots válidos; ante desafío o cualquier estado no válido, detener la adquisición afectada.

**NO-GO**: marcar los clubes/equipos como completamente interpretados hasta explorar controles relevantes y cerrar las relaciones/campos pendientes. El estado `BASE_CAPTURED` evita confundir disponibilidad de snapshots con cobertura semántica.
