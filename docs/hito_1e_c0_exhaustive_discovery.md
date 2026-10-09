# Hito 1E-C0 — Discovery exhaustivo de BDFutbol

**Alcance:** Primera Federación 2026/27, Grupos I y II.

**Fecha:** 8 de octubre de 2026.

**Rama:** `rebuild/football-data-hub-v2`.

## 1. Resumen ejecutivo

La auditoría offline cubrió los snapshots raw, inventarios DOM y exports existentes. Hay 531 directorios raw con metadata y HTML renderizado, todos marcados `VALID`/HTTP 200 **en el momento de su captura**. El export consolidado de clubes/equipos contiene 480 recursos base —12 vistas para cada uno de 40 clubes y equipos de temporada—; los exports de competición y jugadores complementan esa cobertura.

La única navegación nueva autorizada fue a `https://www.bdfutbol.com/es/j/j23751.html`, mediante `BrowserSessionManager` + `BDFutbolAccess` y Brave/Xvfb/CDP con el perfil persistente ya autorizado. Dio HTTP 403, título `Just a moment...` y `CHALLENGE_REQUIRED`. No hice otra solicitud live ni guardé el contenido de desafío como snapshot deportivo. El acceso actual queda **bloqueado**, aunque varias páginas se verificaron en navegaciones reales anteriores.

La investigación confirma que buena parte de la estructura de competición, clubes y equipos se puede volver a procesar offline. La cobertura individual de jugadores, carreras de entrenadores/árbitros, detalles de partidos y medios originales es parcial. Ningún snapshot base demuestra por sí solo que una carrera o entidad esté completa.

## 2. Método, procedencia y límites de la evidencia

Leí los informes de Hitos 1B, 1D-B1, 1D-B2, 1E-A, 1E-A2, 1E-B0, 1E-B1, 1E-B1-D y 1E-B1-E, el informe anterior de Discovery Luna, el catálogo de recursos, los inventarios DOM, los manifests de captura y los exports inmutables de competición, clubes/equipos y jugadores. No modifiqué snapshots ni exports.

| Evidencia | Qué significa | Qué no significa |
|---|---|---|
| `VERIFIED` en el catálogo Luna | La página/control se comprobó durante la auditoría real anterior, con su evidencia enlazada. | No asegura que el acceso siga disponible hoy. |
| `ARTIFACT_ONLY` | La observación actual procede de snapshots, exports o informes previos. | No es una navegación live de este Hito. |
| Estado `VALID` en metadata raw | La captura obtuvo HTTP 200 y pasó su contrato en la fecha registrada. | No es una evaluación del estado actual de BDFutbol. |
| `DOM_ONLY` en filtros | El control y sus opciones aparecen en el DOM preservado. | No demuestra qué filas aparecen al aplicarlo. |
| Conteos agregados de inventario | Recuento de candidatos en todos los snapshots DOM. | No son recuentos de entidades ni de activos únicos: navegación, anuncios y widgets se repiten. |

Los HTML disponibles son HTML renderizados por navegador. No se conserva para cada captura el cuerpo de respuesta previo a JavaScript, por lo que no es posible comparar sistemáticamente DOM original frente a DOM renderizado. Los inventarios guardan atributos DOM, pero algunas colecciones están truncadas por límites configurados.

### Inventario local

`data/raw/bdfutbol/` contiene 531 archivos `rendered.html`, 531 `inventory.json`, 531 `metadata.json`, 531 `summary.json` y 15 capturas PNG; 2.140 archivos en total, **1.616.108.338 bytes**. Los HTML ocupan 1.078.698.058 bytes y los inventarios JSON 527.097.196 bytes. Las 531 metadata históricas reportan `VALID`/HTTP 200; esto no invalida el bloqueo live actual. El total agregado de inventario cuenta 9.197.305 links, 32.942 tablas, 150.539 candidatos de imagen, 3.469 selects, 31.442 botones, 3.487 tabs, 4.345 candidatos de gráfico y 529 entradas XHR. Son conteos repetidos entre páginas, no filas deportivas únicas.

Exports de referencia existentes:

- Competición: `data/parsed/bdfutbol/primera_federacion_2026_27/snapshot-044edc9b2ef3c6026c7f-parser-1.0.0/` — 1.158.959 bytes.
- Clubes/equipos: `data/parsed/bdfutbol/club_team_2026_27/compact/snapshot-f36c91119a98390766ff-parser-1.3.0/` — 546 archivos, 78.727.482 bytes.
- Jugadores: `data/parsed/bdfutbol/player_2026_27/compact/snapshot-d27b77fd5d7c449ec461-parser-0.2.1/` — 32 archivos, 900.153 bytes.

El catálogo 1.3.0 registra 480 páginas base y 29 variantes de resultados de club. Su matriz contiene 240 páginas en pipeline `PARSED` y 240 en `VALIDATED`; 80 registros de vista tienen estado de cobertura `COMPLETE` (las 40 vistas `team_roster` y las 40 `team_statistics`), pero **0 de 80 entidades club/equipo** tienen todas sus vistas completas. Las 240 vistas de club figuran `INCOMPLETE` y no declaran campos de registro interpretados en la matriz. El raw completo tiene 22 directorios adicionales de auditoría, pruebas previas y páginas suplementarias. En el export 1.3.0 hay 17 variantes `all` para 40 clubes; las variantes por resultado registran cuatro `pg`, cuatro `pe` y cuatro `pp`. Las capturas antiguas adicionales no se contaron como páginas base nuevas.

## 3. Recursos y campos deportivos encontrados

El catálogo [`resource_catalog.json`](../data/analysis/bdfutbol/discovery/resource_catalog.json) conserva las 480 referencias página/ID/URL/hash y las navegaciones históricas. El [`field_catalog.json`](../data/analysis/bdfutbol/discovery/field_catalog.json) contiene firmas de tablas por vista, encabezados observados, filas y variaciones entre páginas.

### Competiciones y clasificaciones

Rutas principales: `/es/t/t2026-271rf1.html` y `/es/t/t2026-271rf2.html`. Hay dos grupos, 20 equipos por grupo, 38 jornadas y 380 fixtures por grupo. Los exports de Hito 1B guardan 760 filas de calendario por extracción, con 119 partidos disputados por grupo en la fecha de captura. Una extracción previa distinta no tiene resultados disputados; se debe usar la clave `044edc9b2ef3c6026c7f` para los datos contrastados que se citan aquí.

La tabla de clasificación `#classific` muestra Posición/equipo y los encabezados raw `Pts.`, `PJ`, `PG`, `PE`, `PP`, `GF`, `GC`, `TA`, `TR`. El HTML inicial también contiene la tabla larga de calendario: 456 filas DOM por grupo (38 separadores de jornada, 38 encabezados y 380 partidos), incluso cuando está oculta en la vista de clasificación. Los campos de partido observados son fecha, local, marcador, visitante, estadio y árbitro; los enlaces pueden contener IDs de equipo, partido, estadio y árbitro.

En Grupo I se comprobaron vistas con `tab=results`, `tab=top`, `tab=referees` y `tab=stats`. Resultados incluye un selector de jornada y una matriz equipo-contra-equipo. Destacados cambia entre goles, minutos, tarjetas, más joven y más veterano, y ofrece país. Árbitros presenta temporada y grupo. Estadísticas muestra agregados, rachas y mayores victorias. Las pestañas alternativas de Grupo II no se abrieron y quedan pendientes.

### Clubes permanentes y equipos por temporada

El export 1.3.0 contiene 40 recursos para cada una de estas 12 vistas:

| Entidad | Vistas base | Estructuras/campos reconocidos |
|---|---|---|
| Equipo-temporada | `team_alignment`, `team_roster`, `team_statistics`, `team_tracking`, `team_transfers`, `team_matches` | `taulaplantilla`, `c3p1`, `c3p0`, `taula-seguiment`, tabla de movimientos, tablas de partidos y `taulaentrenadors`. Plantilla: dorsal, foto/país, alias/nombre, posición, edad, partidos, titularidades, completos, suplencias, convocatorias sin jugar, minutos, tarjetas y goles. Estadísticas incluye además `PX`, `C`, `Minutos/G`, `GP`, `GPP`, `GE`, `PG`, `PE`, `PP`. |
| Club | `club_profile`, `club_statistics`, `club_players`, `club_coaches`, `club_matches`, `club_rivals` | Perfil e historial (`ltemporades`, palmarés y tablas de temporadas); estadísticas con múltiples tablas `ttt*`; personas en `llista`; partidos en `tpartits`, `t1`…; rivales en `t5`, `t6`, `t7`. En la matriz actual esas 240 vistas se clasifican `INCOMPLETE`; tablas, celdas y relaciones están preservadas, pero la extracción estructurada y su interpretación siguen pendientes. |

Se observan nombre, fundación, ubicación, país, estadio y aforo en perfiles de club; las vistas de club también contienen listas de jugadores/técnicos, partidos y rivales. En páginas de jugadores y entrenadores las tablas tienen columnas opcionales que pueden cambiar por club y página. Los inventarios de recursos preservan variantes de encabezado, filas raw, IDs enlazados y procedencia.

El parser no resuelve todos los significados abreviados. En `team_statistics`, por ejemplo, los valores y cabeceras quedan preservados aunque algunas métricas sigan pendientes de interpretación. En `team_tracking`, las columnas numeradas representan jornadas y sus celdas se conservan raw; dos páginas carecen de encabezado `5`. No se imputó ni se atribuyó significado a ese hueco. Filas subtotal, encabezados de sección y tablas de layout tampoco se cuentan como entidades.

### Jugadores, trayectoria, estadísticas, partidos y rivales

Solo Morillas (`j209629`) tiene las cuatro vistas individuales preservadas: `/es/j/j209629.html`, `?p=stats`, `/es/p/j209629.html` y `/es/p/jr209629.html`. El parser 0.2.1 da 3 filas de trayectoria más total, 97 filas estadísticas, 51 filas de partidos agregadas, cero filas individuales en `#tpartits` y 533 filas de rivales. El cero de `#tpartits` solo describe esa captura, no la fuente completa.

Trayectoria muestra temporada, equipo, país/división, edad, partidos y estadísticas de juego. Estadísticas agrupa temporadas/equipos/competiciones y métricas de partidos, minutos, goles, porterías a cero, goles encajados y tarjetas. Partidos contiene agregados por competición/temporada/equipo/rival y controles para distintas dimensiones. Rivales conserva jugador rival, posición, PJ, PG/PE/PP, porcentaje, goles y tarjetas. Una vista de jugador no equivale a historial completo: el export deja `career_completeness` sin certificar.

Una comparación pendiente de definición es que Morillas muestra PJ=29 en trayectoria, frente a 23+6+1 en el agregado por competición. No se deben sumar ni reconciliar esas cifras sin saber el alcance de cada vista. En plantillas hay 1.034 IDs únicos y 1.039 pertenencias; los ejemplos `j23751`, `j26481` y `j100160` siguen siendo pertenencias raw separadas. Un cero de apariciones no elimina una pertenencia, y dos equipos en una temporada no prueban por sí solos un traspaso confirmado.

### Partidos, entrenadores, árbitros, estadios y relaciones

Hay una ficha individual de partido capturada: Avilés Industrial–Lugo, ID `269462`, con jornada, fecha, marcador, estadio, eventos de gol, alineaciones, suplentes, sustituciones y entrenadores enlazados. Solo es una muestra; no demuestra que toda ficha tenga idénticas secciones. Los exports de competición ofrecen 760 fixtures y los snapshots `all` de club contrastan 68 IDs de partidos disputados con la lista de 119: 51 no aparecen en las variantes de club que se pudieron capturar. No es evidencia de pérdida del parser.

Se conservan 41 filas/IDs de entrenador de equipos, pero solo un perfil de carrera fue abierto (Manolo Herrero, `l1835`). Hay una ficha de árbitro (`r602267`) y una vista de ranking de árbitros de Grupo I; los arbitrajes históricos completos y Grupo II no se auditaron. Hay una ficha de estadio (`81`, Suárez Puerta), con nombre, aforo, inauguración, arquitecto, dimensiones y localidad. El resto de los perfiles relacionados queda pendiente.

Los enlaces observados relacionan competición↔equipo-temporada/partido, equipo-temporada↔club/plantilla/técnico, partido↔equipos/estadio/árbitro, jugador↔equipos históricos y jugador↔rivales, y club↔historial/equipos/rivales. El catálogo de relaciones distingue ID del proveedor, pertenencia y ocurrencia de enlace; sus recuentos no son necesariamente cantidades de entidades únicas.

### Fotografías, galerías y gráficos

Los inventarios conservan referencias de imagen como `src`, `currentSrc`, `srcset`, `data-src`, `alt`, dimensiones y, cuando aplica, URL enlazada. No se hizo descarga masiva de fotografías ni escudos. Hay 15 PNG de capturas de pantalla, pero no un archivo de originales descargados. En Morillas el carrusel del perfil contenía una imagen y el área comunitaria indicaba `Fotos (0)`; no se inspeccionaron todas las galerías.

Los gráficos se observan como elementos SVG/AmCharts en vistas de competición y trayectoria. Cambiar la métrica de clasificación redibuja el gráfico en cliente. La serie subyacente no está exportada como campo normalizado. Los conteos agregados de imágenes/gráficos del DOM incluyen widgets comunes, anuncios y duplicados entre páginas; no equivalen a activos o estadísticas deportivas únicos.

## 4. Inspección DOM y contenido no visible

En la captura de perfil de Morillas hay 58 tablas: la tabla `table.traject` con la trayectoria y muchas tablas de selector histórico con clases `d-none d-md-block`. En el DOM revisado, esas tablas ocultas representan navegación de temporadas; no deben contarse automáticamente como filas de carrera. Las tablas responsive, columnas opcionales y estilos/clases son parte de la evidencia, no prueba de un dato adicional.

Los parsers preservan atributos de celdas, cuando disponibles: `class`, `style`, `title`, `data-colid`, tag, `rowspan`, `colspan`, índices de fila/columna y enlaces `href_raw` con URL resuelta. Inventarios generales preservan atributos de imágenes, controles, tablas y enlaces dentro de sus límites. No se encontró evidencia offline suficiente para afirmar que todos los datos embebidos en scripts o todas las respuestas XHR estén cubiertos por el parser.

### Contrato de validación del perfil

La inspección manual facilitada para `j23751` indica `Futbolista` en `document.title` y `outerHTML`, pero no en `document.body.innerText`; las etiquetas `Nombre completo` y `Demarcación` aparecen en `textContent` del DOM. La respuesta HTTP 200 que falló originalmente no se guardó, así que su causa exacta no está demostrada. La inspección raw de Morillas sí confirma que los campos personales aparecen dentro de `.hero .d-none.d-md-block`, junto con `h1` y la trayectoria `.traject`.

La corrección mínima separa marcadores de body, título, selectores y texto DOM acotado. Para perfil comprueba:

- HTTP válido, HTTPS BDFutbol, ausencia de marcadores de desafío y URL final del mismo recurso;
- `Futbolista` en el título;
- `Trayectoria` en el body;
- `h1`, `.traject` y `.hero .d-none.d-md-block` presentes;
- `Nombre completo` y `Demarcación` dentro de ese contenedor DOM específico.

No usa `textContent` global como única prueba. Estadísticas, Partidos y Rivales conservan sus marcadores anteriores. El HTTP 403 live de esta fase se clasificó como `CHALLENGE_REQUIRED`, separado del error semántico anterior. La prueba live no confirma si el nuevo contrato pasaría una respuesta deportiva de j23751 porque no se recibió esa página.

## 5. Filtros e interacciones

| Vista | Control y evidencia | Resultado observado | Estado / pendiente |
|---|---|---|---|
| Clasificación Grupo I | Local/Visitante/General, fecha/jornada, aplazados y métrica de gráfico. | Tabla cambia en cliente, fecha revela `date1/date2`, gráfico SVG se redibuja. URL no cambia y no se observó fetch/XHR en las acciones probadas. | `VERIFIED`; no se probaron todos los valores ni Grupo II. |
| Pestañas de competición | `tab=results/top/referees/stats`. | Variantes de página capturadas con URL de consulta. | Grupo I `VERIFIED`; Grupo II `NOT_TESTED`. |
| Equipo-temporada | Selector de temporadas, Alineación/Plantilla/Estadísticas y competición. | Opciones preservadas en DOM; vistas base/`t=lista` capturadas. | `DOM_ONLY`; no se recorrieron temporadas o competencias exhaustivamente. |
| Columnas de plantilla | Disclosure con 15 checkboxes, Recordar y Restablecer. | Se abrió el panel y se leyeron etiquetas/estados. No se cambió preferencia. | Panel `VERIFIED`; efecto de cada checkbox y persistencia `NOT_TESTED`. |
| Club | Tabla/Listado, competición, comparación con 947 clubes. | Controles/opciones presentes en el snapshot. | `DOM_ONLY`; resultados de selección sin probar. |
| Partidos de club | `cat=1rf`, `temp=2026-27`, `pgep=pg|pe|pp` o sin `pgep`. | 29 capturas de variantes; subconjuntos de resultado contrastados con totales cuando disponible. | `VERIFIED` en capturas existentes; 23 clubes aún no tienen variante `all` válida. |
| Jugador | Equipo/país/gráfico/columnas; competición; temporada/equipo/rival/resultado; filtros de rivales. | Opciones aparecen en las cuatro vistas de Morillas. | `DOM_ONLY`; no se adquirieron variantes filtradas. |
| Paginación/orden | Algunas tablas tienen clases `sortable`/`configurable`. | No hay prueba de transición de página ni cambio ordenado. | `NOT_TESTED`. |

En las observaciones históricas también aparecieron recursos secundarios de Cloudflare JS Detection, reCAPTCHA, telemetría y un 403 para `/manifest.json` mientras el documento principal era válido. Ese estado de recurso secundario no debe confundirse con el estado del documento deportivo; tampoco se atribuyen todas las solicitudes retrasadas al último control abierto.

## 6. Matriz de cobertura demostrada

| Familia | Estado de evidencia/cobertura | Cobertura que sí existe | Pendiente principal |
|---|---|---|---|
| Clasificación/calendario | `NORMALIZED`, `RAW_PRESERVED`, `FILTER_PENDING` | Ambos grupos, 40 equipos, 760 fixtures por extracción. | Grupo II tabs, variantes de aplazados/fechas y actualización de resultados. |
| Clubes permanentes | `RAW_PRESERVED`, `PARSER_MISSING`, `FILTER_PENDING` | 40 × 6 vistas base; tablas, celdas y relaciones conservadas. | La matriz 1.3.0 marca las 240 vistas `INCOMPLETE`, sin campos estructurados interpretados; faltan extracción tipada, filtros y columnas opcionales. |
| Equipos-temporada | `NORMALIZED`, `RAW_PRESERVED`, `PARSER_MISSING`, `FILTER_PENDING` | 40 × 6 vistas; 40 roster y 40 estadísticas están `COMPLETE` a nivel de vista; 160 vistas restantes `INCOMPLETE`; ninguna entidad completa. | Columnas abreviadas/raw-only, hueco tracking nº 5 y temporadas alternativas. |
| Identidades/pertenencias de jugador | `NORMALIZED`, `RAW_PRESERVED` | 1.034 IDs, 1.039 filas de pertenencia, 179 con cero apariciones. | Mantener pertenencias distintas; no confundir con historia individual completa. |
| Perfil/trayectoria de jugador | `RAW_PRESERVED`, `CAPTURE_PENDING`, `ACCESS_BLOCKED` | Morillas solamente; el check live de j23751 fue bloqueado. | 1.033 perfiles restantes, carrera completa y reintento autorizado. |
| Estadísticas y rivales de jugador | `NORMALIZED`, `RAW_PRESERVED`, `FILTER_PENDING`, `CAPTURE_PENDING` | 97 estadísticas y 533 rivales de Morillas. | Otros jugadores, filtros y discrepancia de ámbito entre vistas. |
| Partidos individuales de jugador | `SOURCE_ABSENT` en `#tpartits` de Morillas; global `UNKNOWN` | 51 agregados de Morillas; tabla de encuentros sin filas de datos en ese snapshot. | Confirmar disponibilidad en otras vistas/jugadores; no inferir partidos desde totales. |
| Partidos | `NORMALIZED`, `RAW_PRESERVED`, `CAPTURE_PENDING` | Fixture completo; 68 IDs observados de club; una ficha de partido. | Detalle de 118 partidos disputados restantes y cobertura de alineaciones/eventos. |
| Entrenadores | `RAW_PRESERVED`, `CAPTURE_PENDING` | 41 filas/IDs de plantillas, un perfil. | Historial de los demás y variantes de perfil. |
| Árbitros | `RAW_PRESERVED`, `CAPTURE_PENDING`, `FILTER_PENDING`, `ACCESS_BLOCKED` | Ranking Grupo I y un perfil histórico. | Grupo II, designaciones completas y perfiles restantes. |
| Estadios | `RAW_PRESERVED`, `CAPTURE_PENDING`, `UNKNOWN` | Una ficha y referencias enlazadas. | Inventario de IDs, historial de sedes y otras fichas. |
| Rivales/historial cruzado | `NORMALIZED`, `RAW_PRESERVED`, `FILTER_PENDING` | 40 vistas de club y una vista de jugador. | Alcance histórico, filtros y completitud global. |
| Fotos/escudos/galerías/gráficos | `RAW_PRESERVED`, `CAPTURE_PENDING`, `UNKNOWN` | Referencias DOM y 15 screenshots; un carrusel de perfil revisado. | Binarios originales, deduplicación, galerías adicionales y datos de series. |
| Rankings globales/otras secciones | `NOT_TESTED`, `UNKNOWN`, `CAPTURE_PENDING` | Solo enlaces/navegación general. | Destinos globales y familias nuevas. |

Los estados completos por familia, métricas y evidencia están en `coverage_gaps.json`. `SOURCE_ABSENT` solo se usa para el ámbito exacto de la tabla Morillas revisada; no implica ausencia en el proveedor.

## 7. Qué puede hacerse offline y qué requiere nuevas capturas

### Recuperable ahora desde raw y exports

- Reprocesar sin navegar los 480 recursos de club/equipo, las 29 variantes catalogadas y sus relaciones, conservando el raw original.
- Revalidar integridad y cruces de 40 equipos, 1.039 pertenencias, 1.034 IDs y estados de cero apariciones.
- Conciliar los 760 fixtures de competición y los resultados disponibles con las 68 observaciones de las páginas `all` capturadas.
- Revisar filas/celdas/headers raw de tracking, plantillas, movimientos, tablas de club y filtros ya presentes.
- Reparsear las cuatro vistas de Morillas y auditar sus 97 estadísticas, 51 agregados, 533 rivales y tres filas de trayectoria.
- Ampliar parsers offline solo cuando una discrepancia se pueda reproducir desde HTML guardado y con fixture real versionado.

### Requiere acceso autorizado futuro

- Reintentar `j23751/profile` y luego cualquier piloto individual; ahora el acceso live está bloqueado.
- Capturar historiales de los otros jugadores, entrenadores, árbitros y estadios.
- Abrir páginas de detalle de partidos y variantes de filtros que no estén ya en raw.
- Explorar Grupo II en pestañas alternativas, historial temporal, ordenaciones y paginación.
- Descargar fotografías o escudos originales, una vez definida una estrategia de procedencia, licitud y deduplicación.

## 8. Corrección aplicada y garantías

Se actualizó solo el contrato de validación del perfil en `access.py` y `bdfutbol_player.py`, con regresiones offline en `tests/test_bdfutbol_access.py`. Los marcadores de título, body, estructura y texto DOM acotado se reportan por separado. Morillas pasa las cuatro vistas reales existentes; una palabra en el título sin contenido/estructura deportiva sigue produciendo `INVALID_CONTENT`. La ruta final de otro jugador sigue siendo `INVALID_URL`, y un 403 con desafío sigue siendo `CHALLENGE_REQUIRED` antes de comprobar semántica. Un response rechazado no se guarda como snapshot deportivo mediante el colector.

El ajuste no demuestra acceso a j23751: la única navegación real de esta fase terminó en Cloudflare 403. El HTML del check live no se guardó; el diagnóstico separado conserva URL, título, estado HTTP, readiness, conteo de tablas, tamaño/hash del DOM y marcadores booleanos, sin cookies ni tokens.

## 9. Viabilidad y próximos hitos sugeridos

La extracción determinista offline es viable: HTML renderizado, metadata/hash y tablas raw suficientes permiten construir parsers reproducibles y auditar celdas. Para adquisición desatendida la viabilidad es **condicional**: ahora hay un bloqueo HTTP 403, y los informes históricos muestran intermitencia entre capturas válidas y desafíos. Ninguna arquitectura debe asumir que una sesión browser equivale a acceso permanente.

Prioridades posteriores, sujetas a una instrucción nueva:

1. Hito offline de cobertura: reconciliar manifest esperado/observado por grupo, club, vista, tabla, fila y columna sin abrir red.
2. Hito de acceso autorizado: cuando esté disponible, repetir solo la prueba mínima y detenerse en cualquier desafío; no ampliar lote hasta resolver la disponibilidad autorizada.
3. Hito de detalle de partidos: diseñar piloto pequeño desde los IDs ya normalizados, con validación raw/parsed y sin generar encuentros desde agregados.
4. Hitos de entidades históricas y filtros: fijar inventarios por página, estados de completitud y límites de cobertura por fuente.
5. Medios y gráficos: descubrir relaciones semánticas y procedencia antes de descargar recursos.

## 10. Entregables y validaciones

Se crearon este informe y los seis catálogos indicados. El esquema y el significado de `VERIFIED`/`ARTIFACT_ONLY` y los estados de cobertura están documentados en `discovery_manifest.json`. El diagnóstico de acceso live separado está en `data/analysis/bdfutbol/discovery/live_access_check/20261008T212243.699473Z.json` (local e ignorado por Git).

Validación final: `PYTHONPATH=src .venv/bin/python -m pytest -q` pasó **229 pruebas**; Ruff pasó en `access.py`, `bdfutbol_player.py` y `test_bdfutbol_access.py`; `git diff --check` terminó sin errores. El primer intento de pytest dentro del sandbox solo falló porque el sandbox bloqueó la reserva loopback de una prueba; la suite completa repetida con permiso de ejecución local pasó. No se realizó commit ni push. No se iniciaron capturas de jugadores, adquisición masiva ni cambios en Dev Explorer.
