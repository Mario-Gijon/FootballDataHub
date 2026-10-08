# Hito 1D-A — Discovery y extractores de clubes/equipos-temporada

Fecha de investigación: 8 de octubre de 2026. El alcance live fue una muestra de cuatro participantes; no se ejecutó una adquisición masiva.

## Resultado

Se reutilizaron `BrowserSessionManager`, `BDFutbolAccess`, Brave, Xvfb, CDP y el perfil persistente existente. La carga y validación usaron la misma infraestructura que los hitos previos. No se usaron `requests`, un Chromium nuevo, ni un contexto persistente alternativo. No se leyeron ni exportaron cookies o credenciales.

Se hicieron **29 navegaciones reales**, todas con estado `VALID` y HTTP 200: 26 capturas raw (22 URLs únicas; cuatro capturas repetidas de vistas de Jaén) y tres visitas adicionales a Estadísticas para inspeccionar el panel de columnas. Dos snapshots de alineación y estadísticas de Jaén se reutilizaron desde la auditoría anterior y se etiquetaron `ARTIFACT_ONLY` en la matriz. No apareció `CHALLENGE_REQUIRED`.

Los únicos controles que se accionaron fueron abrir el panel de columnas de Estadísticas y desmarcar/marcar de nuevo una columna. Se dejó el valor seleccionado como estaba. No se pulsaron **Recordar** ni **Restablecer**, no se enviaron formularios y no se observaron peticiones de datos asociadas al cambio. En la ventana registrada solo aparecieron recursos `GET` de `/manifest.json` y del script estático de reCAPTCHA; no se identificó un endpoint JSON/XHR deportivo.

Los pilotos se eligieron de `participants.json` del Hito 1B:

| Grupo | Equipo | ID equipo/temporada | ID permanente del club | Vistas equipo capturadas | Vistas club capturadas |
|---|---|---|---|---:|---:|
| II | Jaén / Real Jaén | `t2026-2749` | `e49` | 6/6 | 6/6 |
| II | Villarreal B | `t2026-2794` | `e94` | 3/6 | 1/6 |
| I | Lugo | `t2026-2776` | `e76` | 3/6 | 1/6 |
| I | Bilbao Athletic | `t2026-2772` | `e72` | 3/6 | 1/6 |

La relación entre IDs se obtiene del enlace de club en la ficha de equipo-temporada. No se reutiliza el identificador temporal del equipo como identidad permanente.

## Evidencia y artefactos

- Capturas directas de este hito: `data/raw/bdfutbol/hito_1d_club_team/`. Las capturas conservan `rendered.html`, `inventory.json`, `metadata.json` y `summary.json`; los originales no se modificaron.
- Snapshots anteriores reutilizados: `data/raw/bdfutbol/luna_audit/20261008T121250.991672Z/team_season_jaen` y `data/raw/bdfutbol/luna_audit/20261008T121519.382702Z/team_season_statistics`.
- Export vigente tras parsear offline: `data/parsed/bdfutbol/club_team_2026_27/snapshot-1bb2c0015b03c077cb76-parser-1.1.0/`.
- Catálogo de campos y controles: `resource_catalog.json` dentro de ese export.
- Cobertura por entidad/vista: `coverage_matrix.json` y `coverage_matrix.csv` dentro de ese export.
- Captura de la interacción de columnas previa: `data/analysis/bdfutbol/luna_audit/20261008T121519.382702Z/column_panel_interaction.json` (artefacto previo, no evidencia de esta interacción concreta).

En la captura directa hay 26 directorios raw que ocupan aproximadamente 69 MB. El export parsed ocupa aproximadamente 173 MB por las tablas históricas extensas y por conservar tanto las páginas JSON como las filas tabulares CSV. El export es local e ignorado por Git; los datos no se añaden al repositorio versionado.

## Catálogo por familia

### Equipo-temporada

Las seis rutas verificadas para Jaén son:

| Vista | URL | Evidencia y contenido observado |
|---|---|---|
| Alineación | `https://www.bdfutbol.com/es/t/t2026-2749.html` | HTML con clasificación, entrenador y tabla `taulaplantilla`; se reconocieron los mismos IDs de jugadores que en la plantilla. |
| Plantilla | `https://www.bdfutbol.com/es/t/t2026-2749.html?t=plantilla` | Tabla `c3p1`, filas de jugadores y tabla `taulaentrenadors`. |
| Estadísticas | `https://www.bdfutbol.com/es/t/t2026-2749.html?t=lista` | Tabla `c3p0`, controles de columnas, totales de equipo y estadísticas individuales. |
| Seguimiento | `https://www.bdfutbol.com/es/t/t2026-2749.html?t=seg` | Tabla `taula-seguiment`, calendario por jornadas y selector de vista. |
| Traspasos | `https://www.bdfutbol.com/es/t/t2026-2749.html?t=altas` | Tabla de altas/bajas con equipo de origen y destino. |
| Partidos | `https://www.bdfutbol.com/es/t/t2026-2749.html?tab=partits` | Tabla `taula-resultats-plantilla`, progreso de liga y selector de competición. |

En Bilbao Athletic, Lugo y Villarreal B se verificaron directamente Alineación, Plantilla y Estadísticas. Sus páginas mostraron las mismas tablas principales, pero el resto de las vistas de equipo no se visitaron para esos equipos.

Campos observados en la plantilla `c3p1`: dorsal (`#`), imagen/escudo, apodo y nombre, fecha y lugar de nacimiento, provincia y demarcación (`Pos`). El HTML contiene los enlaces de perfil de cada jugador. `taulaentrenadors` contiene entrenador enlazado y, según la vista, fecha o edad, jornadas/partidos y tarjetas. Los valores de cada celda, atributos de presentación, imágenes y enlaces se conservan en el JSON de página.

Estadísticas `c3p0`: 22 posiciones de columna: `#`, foto, país, `Apodo`, `Pos`, `PJ`, `PT`, `PC`, `PS`, `PX`, `C`, `Min`, `TA`, `TR`, `G`, `Minutos/G`, `GP`, `GPP`, `GE`, `PG`, `PE`, `PP`. La página expone **22 casillas** de configuración, todas marcadas en el snapshot live. El inventario antiguo indicaba 15; el HTML/DOM actual de `?t=lista` prueba 22 en esta vista y los snapshots incluyen sus 22 celdas. La tabla incorpora además una fila `total` con `colspan`; el parser la almacena en `statistics_totals` y asigna sus celdas a las cabeceras sin confundirla con un jugador. Las demás filas no reconocibles se conservan en `statistics_unparsed_rows` y bloquean la validación estructural.

Filtros/vistas observados: selector de temporada (70 opciones en Jaén, 59 Bilbao Athletic, 55 Lugo y 20 Villarreal B), selector de presentación con Alineación/Plantilla/Estadísticas y selector de competición `Liga` (una opción en estas muestras). Seguimiento incluye selector `Partidos`, `Tarjetas`, `Goles`, `Todo` (cuatro opciones). El snapshot conserva el selector, todas sus opciones, checkboxes, pestañas y formularios sin sus valores de input.

### Club permanente

Las seis rutas fueron verificadas para Jaén:

| Vista | URL exacta |
|---|---|
| Perfil / Trayectoria | `https://www.bdfutbol.com/es/e/e49.html` |
| Estadísticas | `https://www.bdfutbol.com/es/e/e49.html?p=stats` |
| Jugadores | `https://www.bdfutbol.com/es/e/egols49.html` |
| Entrenadores | `https://www.bdfutbol.com/es/e/eentr49.html` |
| Partidos | `https://www.bdfutbol.com/es/p/e49.html` |
| Rivales | `https://www.bdfutbol.com/es/p/er49.html` |

También se visitó directamente el Perfil/Trayectoria de `e72` (Bilbao Athletic), `e76` (Lugo) y `e94` (Villarreal B). No se asumió que sus secciones históricas fueran idénticas: cambian títulos, temporadas, nombres, estadios, escudos, competiciones y cantidades de opciones.

El hero del perfil de Jaén muestra Nombre completo, Fundación, Localidad, País, Estadio y Aforo. Las secciones visibles incluyen Progreso, Títulos, Otros escudos, Estadios y Nombres; el perfil conserva tablas históricas de temporadas y competiciones. Controles observados: presentación Tabla/Listado (dos opciones), competición (ocho opciones en Jaén, variable por club) y comparación con club (947 opciones). No se probaron combinaciones ni vistas de comparación.

| Vista de Jaén | Contenido tabular observado | Controles relevantes sin aplicar |
|---|---|---|
| Jugadores | `llista`: 918 filas históricas. Campos: nombre/apodo, fecha, ciudad, país, nacionalidad, internacionalidad, posición, partidos, titularidades, completos/incompletos, suplencias, convocatorias, resultados, minutos, goles y tipos de goles, tarjetas, temporadas, edades, altura y peso. | 13 competiciones, 31 países; 40 opciones de columna en el HTML. |
| Entrenadores | `llista`: 68 filas. Nombre/apodo, nacimiento, ciudad/país/nacionalidad, internacionalidad, partidos, victorias/empates/derrotas y porcentajes, temporadas consecutivas/inicial/final, edad inicial/final, altura y peso. | 13 competiciones, cinco países; 25 opciones de columna en el HTML. |
| Estadísticas | 18 tablas `ttt*` con registros de gol, gol en contra, participación y partido ganado/perdido/empatado; filas de eventos enlazan temporada, fecha, partido y, cuando existe, jugador. | Dos selectores de competición (11 y 4 opciones) y pestañas internas por tipo de hito. No se activaron una a una. |
| Partidos | Índice `tpartits` vacío en el estado capturado; tablas agregadas de competiciones (11 filas), temporadas (70), resultados y rivales (251) y árbitros (705). Cabeceras incluyen PJ, PG/PE/PP, GF/GC, TA/TR y porcentaje. | Selectores para resultado, rival (252), temporada (71), competición (12) y nacionalidad (3); controles de estadísticas de local/visitante. |
| Rivales | `t5`: 9.903 filas de jugadores; `t6`: 682 entrenadores; `t7`: 251 clubes. Preserva sus enlaces e IDs. | 12 competiciones, 71 temporadas y cinco demarcaciones. |

La página de Partidos de club parece ofrecer agregados e índices; no se recorrieron las combinaciones que rellenan `tpartits`. Los partidos individuales del Hito 1B siguen siendo la fuente de fixtures. No se descargaron perfiles históricos de jugadores ni entrenadores.

### Recursos, medios y navegación

- Enlaces de jugadores, entrenadores, clubes, equipos-temporada, estadios y partidos que siguen los patrones reconocidos se convierten en relaciones con ID/URL y procedencia (tabla/fila/columna).
- Las imágenes y sus URL, texto alternativo, dimensiones y `srcset`/atributos lazy se inventarían. No se descargó ninguna imagen. Hay retratos, banderas, escudos e iconografía mezclados con la página; la ausencia de archivo de imagen local no significa que falte una fotografía en origen.
- No se detectaron carruseles/galerías en el DOM capturado (`gallery_candidates` vacío). La vista/enlace de Fotos y la galería de medios quedan `NOT_TESTED`.
- El inventario capturó candidatos gráficos, pero no se interpretaron series de gráficos ni se compararon sus datos con tablas. Estadísticas y vistas gráficas quedan `NOT_TESTED` como contenido dinámico.
- El sitio repite tablas de menú global en el DOM. El parser limita su inventario deportivo al contenido desde `.hero` y conserva esas tablas fuera del catálogo de página para evitar convertir navegación global en datos deportivos.

## Diferencias entre los pilotos

Los registros de `c3p1` y las estadísticas enlazadas se conciliaron por ID, no por nombre:

| Equipo | Filas de plantilla | Filas de estadísticas de jugadores | Fila total aparte | IDs sin estadísticas | Jugadores con 0 apariciones |
|---|---:|---:|---:|---:|---:|
| Jaén | 25 | 25 | 1 | 0 | 4 |
| Villarreal B | 26 | 26 | 1 | 0 | 5 |
| Lugo | 30 | 30 | 1 | 0 | 6 |
| Bilbao Athletic | 28 | 28 | 1 | 0 | 5 |

Hay 109 IDs únicos de jugadores (109 membresías en los cuatro equipos) y cuatro IDs distintos de entrenadores en las plantillas. Se preservaron también los 20 jugadores con cero apariciones. El registro histórico del club Jaén contiene 918 IDs de jugador y 68 de entrenador; no se suman a los 109 como si fueran el mismo conjunto temporal ni se descargaron sus perfiles.

## Cobertura y limitaciones

El export incluye **48 vistas esperadas** (seis por cada uno de cuatro equipos-temporada y seis por cada club permanente relacionado), **24 capturadas y parseadas** con acceso `VALID`. De estas, 11 vistas están `VALIDATED` mediante conciliación estructural de filas/IDs; ocho vistas (Plantilla y Estadísticas de cada piloto) además están `COMPLETE` dentro del alcance 2026/27 y de la vista actual. Las ocho entidades continúan `INCOMPLETE`: Jaén tiene sus seis rutas de equipo/club; cada otro equipo tiene tres vistas y cada otro club, solo el perfil. Las temporadas históricas, filtros, categorías y preferencias visuales fuera del alcance 2026/27 no se presentan como completados.

Estados del catálogo:

- `VERIFIED`: navegación directa de esta ejecución, URL, estado HTTP, contenido y marcadores deportivos observados.
- `ARTIFACT_ONLY`: snapshot previo reutilizado offline; no se cuenta como visita de esta ejecución.
- `INFERRED`: patrón de URL o relación derivado de un enlace, todavía no visitado.
- `NOT_TESTED`: selector/pestaña/vista reconocida cuyo efecto no se exploró.
- `BLOCKED`: no hubo recursos de esta muestra con este estado.
- `NOT_AVAILABLE_IN_SOURCE`: no se usa para información cuya ausencia todavía no se comprobó.

Pendiente antes de considerar las fichas completas:

1. Visitar Seguimiento, Traspasos y Partidos de Villarreal B, Lugo y Bilbao Athletic, y sus otras cinco vistas de club.
2. Probar los filtros representativos de jugadores/entrenadores/rivales/estadísticas/partidos, comparación y selector Tabla/Listado; comprobar si generan otra tabla, URL o solo una subvista.
3. Confirmar visualmente qué columnas oculta cada casilla. El HTML de Estadísticas contiene las 22 columnas y el panel se abrió; el toggle se revirtió, pero el selector de columnas del DOM usado para medir visibilidad no encontró un `thead` y no se afirma el efecto visual de cada columna.
4. Auditar los 20 registros de totales individuales: se conservan y sus `colspan` se alinean con cabeceras; su interpretación deportiva completa requiere comparar las sumas que la fuente publica.
5. Estudiar el recurso Fotos, galerías y datos subyacentes de gráficos. No se descargan medios hasta acordar almacenamiento y procedencia.
6. Revisar diferencias de estructura en más de cuatro equipos y en clubes con una sola temporada u otras rutas opcionales.

El catálogo reporta `DISCOVERED` para vistas sin snapshot, `PARSED` cuando el HTML se interpretó pero no se reconciliaron registros, `VALIDATED` solo donde coincidieron tablas, filas e IDs, `COMPLETE` para las dos vistas actuales de plantilla/estadísticas después de reconciliar sus IDs y registros, y `INCOMPLETE` para entidades con otras vistas aún pendientes. Ninguna entidad completa se declara.

## Extractores y formatos

- `providers/bdfutbol/club_team.py`: clasifica rutas; parsea HTML con BeautifulSoup/lxml sin navegador/red; guarda tablas completas, cabeceras, filas, celdas, valores originales, links, imágenes, formularios, pestañas, selectores, checkboxes, gráficos y relaciones. Incluye extracción conservadora de miembros, estadísticas individuales y totales con `colspan`.
- `collectors/bdfutbol_club_team.py`: valida snapshots por estado, URL, HTTP, bytes y SHA-256; descubre la última captura válida por URL; live captura solo IDs explícitos, usa el gestor actual y para en el primer estado no válido. Reutiliza snapshots válidos y no los sobrescribe.
- `parsers/club_team_coverage.py`: produce catálogo de campos/controles y matriz por entidad-vista. No eleva HTTP 200 ni una página parseada a `COMPLETE` automáticamente.
- `storage/club_team_exports.py`: exporta JSON por página y JSON/CSV de miembros, personas del club, relaciones, filas completas de tablas y cobertura; publica metadatos con hashes y versión.
- `scripts/scrape_bdfutbol_club_team.py`: CLI offline/live para IDs explícitos y repetibles.

No se añadieron dependencias. Los snapshots son raw inmutables; el parsing es offline y el export se versiona por hash de URL/snapshot y versión del parser. No hay scraping de jugadores, base de datos ni cambios en Dev Explorer o Hito 1B.

Uso:

```bash
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_club_team.py offline \
  --raw-root data/raw/bdfutbol \
  --team-id t2026-2749 --team-id t2026-2794

PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_club_team.py live \
  --profile ~/.football-data-hub-v2-probe --browser brave \
  --team-id t2026-2749 --team-id t2026-2794
```

`live` guarda estado por ejecución. Si `BDFutbolAccess` devuelve cualquier estado distinto de `VALID`, detiene la adquisición, registra el estado y permite procesar offline lo ya capturado. No intenta eludir Cloudflare. Una nueva ejecución reutiliza las URLs válidas que ya existan.

## Plan por lotes para los 40 participantes

1. Leer `participants.json` del Hito 1B y verificar 40 IDs `t2026-*`, grupo, nombre y URL antes de iniciar lotes.
2. Ejecutar cuatro u ocho equipos por lote con `--team-id` explícitos; conservar el manifiesto de cada corrida. Mantener ritmo conservador y parar en el primer desafío.
3. Si se detiene el lote, revisar `capture_status.json`, procesar offline los snapshots válidos y reanudar solo después de que el acceso autorizado esté disponible. La captura reutiliza las URLs válidas, por lo que no vuelve a descargarlas.
4. Revisar la matriz por equipo y club; resolver tablas sin reconciliar, rutas no disponibles y controles pendientes antes de etiquetar cualquier entidad completa.
5. Mantener los exports por snapshot/hash, conservar raw y no combinar identidades temporales con IDs permanentes.

Los extractores ya admiten lotes por ID y reanudación de vistas ya válidas. Están listos para ampliar el piloto tras revisar las seis vistas pendientes de los tres equipos distintos de Jaén y validar el funcionamiento de controles que no se activaron. Por eso no se recomienda iniciar todavía los 40 en una única corrida: las excepciones de layout/filtros y el tamaño de páginas históricas necesitan resolver primero el checklist anterior.

## Validación ejecutada

- Pruebas offline del extractor: `28 passed`.
- Suite completa: `151 passed`.
- CLI offline ejecutada con los cuatro IDs; procesó 24 páginas y generó el export JSON/CSV descrito arriba.
- Ruff sobre los archivos nuevos/modificados: `All checks passed`.
- `compileall` sobre los módulos y el CLI: completado sin errores.
- En la primera ejecución de pytest, el sandbox denegó el socket loopback requerido por una prueba existente de `BrowserRuntime`; la suite completa se repitió con permiso local y pasó sin fallos.
