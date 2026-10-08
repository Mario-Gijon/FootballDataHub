# Hito 1E-A2 — Robustez offline y preparación del parser de jugadores

**Fecha:** 2026-10-08  
**Alcance:** procesamiento exclusivamente local. No se realizaron peticiones HTTP, navegación ni descargas.

## Cambios

- Se centralizó la clasificación de partidos en `parsers.match_status`. La decisión combina las etiquetas de resultado y fixture con el marcador original, los goles numéricos, el ID y la fecha respecto a la captura. `played` requiere marcador y goles coherentes, ID y ausencia de contradicción temporal. Los partidos futuros con indicios de resultado quedan como `inconsistent`, nunca como disputados.
- Competition, coverage, source audit, observaciones de clubes y la selección de Hito 1B usan la clasificación compartida. Los registros inconsistentes producen incidencias y no se consolidan como disputados.
- La carga de competición valida una única extracción completa: esquema y temporada, 380 filas por grupo, procedencia y URLs, snapshot raw `VALID`/HTTP 200, hashes coincidentes, IDs únicos y ausencia de estados inconsistentes. Sin clave explícita elige la extracción elegible más reciente; `--competition-extraction-key` permite seleccionar una por su clave. No mezcla grupos de extracciones distintas y conserva timestamp y hash por grupo. El export de club/equipo registra selección, criterio, conteos normalizados y procedencia.
- El parser de jugadores reconoce `#tpartits`, conserva todas sus celdas y cabeceras, separa filas de partido, cabecera, total, sección y filas vacías, y normaliza IDs/URLs, temporada, competición, fecha, equipos y marcador cuando la evidencia permite hacerlo. También registra parámetros de URL para identificar vistas filtradas y no declararlas exhaustivas. Una tabla ausente o solo con cabecera no genera partidos.
- La salida de jugadores incorpora `individual_matches` y `player_pilot_candidates`. La versión del parser/esquema subió a `0.2.0`/`v2`; los exports previos permanecen en su ruta `0.1.4`/`v1`. La clave de salida incluye inventario, snapshots, auditoría y versión; un directorio ya existente con contenido distinto se rechaza en vez de sobrescribirse. Se mantiene gzip determinista y sin pérdida.
- El manifiesto diferencia URL del perfil verificada desde el roster de URLs de vistas inferidas desde rutas observadas; snapshot válido, pendiente o que requiere revalidación; estado por vista y variantes no investigadas. Una captura válida filtrada queda registrada como variante, pero no satisface la vista base. La completitud de carrera sigue sin certificarse.

## Evidencia de datos reales locales

### Hito 1B

Se validaron localmente las dos extracciones `044edc9b2ef3c6026c7f` y `d047191aa847be5c30d7`. Cada una contiene 760 fixtures y **119 partidos disputados**:

| Extracción | Grupo I | Grupo II | Total disputados |
|---|---:|---:|---:|
| `044edc9b2ef3c6026c7f` | 60 | 59 | 119 |
| `d047191aa847be5c30d7` | 60 | 59 | 119 |

En ambas, Grupo I quedó en 320 programados; Grupo II, en 320 programados y 1 sin resolver. Ninguna produjo fixtures inconsistentes. La selección automática escoge `d047191aa847be5c30d7` por fecha de captura entre candidatas que pasan los controles, no por el número de etiquetas `played`. El source audit del export B2 de clubes conserva `044edc9b2ef3c6026c7f` como vínculo explícito de procedencia; no se cambia retroactivamente esa fuente.

### Morillas

Se volvieron a parsear offline cuatro snapshots válidos de `j209629`:

- Trayectoria: 3 filas observadas; completitud histórica no certificada.
- Estadísticas: 97 filas.
- Partidos: 51 filas agregadas; `tpartits` contiene únicamente cabecera y no aporta encuentros individuales.
- Rivales: 533 registros.

La tabla `tpartits` sí aparece en el HTML capturado, con columnas identificadas por `data-colid`, títulos y columnas opcionales responsive. La captura local no contiene filas de partido; no se presentan como datos obtenidos.

### Roster y manifiesto

El export local de plantillas mantiene 1.034 IDs únicos y 1.039 pertenencias. El manifiesto contiene 4.136 filas (cuatro vistas por jugador): 4 capturadas y 4.132 pendientes. El shortlist de 15 pilotos se prepara sin adquisición a partir de Morillas como baseline, códigos de posición raw distintos (`1`, `2`, `3`, `4`, `5`, `6`, `9`, `10`), una pertenencia con cero apariciones y las pertenencias múltiples existentes. Los códigos no se interpretan semánticamente. Solo la trayectoria ya parseada de Morillas tiene recuento; para los demás pilotos permanece pendiente.

## Fixtures de prueba sintéticos

Los fixtures HTML añadidos prueban filas con marcador, sin marcador, fila malformada, cabecera, total y fila vacía; preservación de valores/celdas y URL de partido; parámetros de vista filtrada; y ausencia de filas inventadas. Otros tests cubren vocabularios de estado antiguos y nuevos, discrepancias entre score y goles, falta de ID, evidencia futura contradictoria, posición raw distinta, cero apariciones, varias pertenencias, hashes ausentes y selección/rechazo de exports incompletos.

Estos casos artificiales verifican el comportamiento del parser; no son evidencia de que esas variantes existan en páginas BDFutbol no capturadas.

## Ejecución offline y exports

Se ejecutó `scripts/parse_bdfutbol_players_offline.py` con sus inputs locales. Export generado:

`data/parsed/bdfutbol/player_2026_27/compact/snapshot-137e17d1f77d753e3da6-parser-0.2.0`

Resumen verificado en los gzip: cuatro páginas, 3 filas de trayectoria, 97 de estadísticas, 51 agregadas, 0 individuales reales, 533 de rivales, 551 relaciones, 1.034 jugadores, 1.039 pertenencias y 4.132 vistas pendientes. Los datos raw no se modificaron ni se copiaron a los exports normalizados.

## Límites pendientes

- La navegación anterior terminó con `CHALLENGE_REQUIRED`/HTTP 403. Este hito no comprobó si el acceso cambió y no intentó eludir el desafío.
- No hay filas individuales reales de `tpartits` en los snapshots disponibles; la extracción de filas nuevas se prueba con HTML sintético.
- Solo existe una muestra de páginas individuales de jugador. Posiciones, temporadas, filtros, paginación, columnas ocultas y variantes de carrera de los demás jugadores siguen pendientes de capturas.
- Cuatro páginas base de un jugador no demuestran la completitud de su carrera, sus estadísticas ni sus variantes.
- Los datos posteriores de filtros pueden ser parciales; el parser conserva los parámetros y marca el alcance de una URL filtrada como no exhaustivo.

## Validación

- Parser offline: completado con los recuentos anteriores.
- Pruebas dirigidas de estados, jugadores, competición, auditoría y clubes/equipos: **96 pasaron**.
- Suite completa: **210 pasaron**. El test de puerto loopback necesitó permiso para abrir un socket local; no se usó red externa.
- Ruff sobre todos los archivos Python modificados: **sin incidencias**.
