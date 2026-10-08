# Hito 1D-A2 — Cierre de cobertura de clubes y equipos piloto

Fecha: 8 de octubre de 2026  
Rama: `rebuild/football-data-hub-v2`  
Alcance: Jaén (Grupo II), Villarreal B (Grupo II), Lugo (Grupo I) y Bilbao Athletic (Grupo I); temporada 2026/27.

## Conclusión

Se adquirieron las 24 vistas que faltaban en los cuatro pilotos. Las 24 respuestas nuevas y la variante filtrada de partidos de Jaén fueron `VALID`, HTTP 200, y no se encontró ningún desafío. Se reutilizaron las 24 capturas base ya existentes; no se sobrescribió ningún raw anterior. El inventario resultante contiene 48 vistas base, más una variante de partidos con alcance explícito.

La muestra demuestra que el parser conserva las filas de jugadores, las filas agregadas, los espacios de cabecera y las apariciones de relaciones con su procedencia. También explica por qué la tabla `tpartits` del club estaba vacía: la ruta sin filtros deja activa la vista de agregados. Una consulta de solo lectura por competición, temporada y resultado reveló tres partidos que concuerdan con el agregado de victorias de esa temporada.

**La ejecución técnica sobre 40 clubes aún no debe declararse libre de omisiones.** Las vistas base de los cuatro pilotos están capturadas, pero solo ocho vistas de plantilla/estadísticas se consideran completas; 28 vistas base siguen en estado `PARSED`, y solo se validó una de las muchas variantes filtradas. Las ocho entidades piloto permanecen `INCOMPLETE`.

## Evidencia de adquisición

- Se inspeccionaron primero los snapshots existentes y la documentación de Hito 1D-A. Los 24 URLs pendientes se adquirieron con `BrowserSessionManager`, `BDFutbolAccess`, Brave/Xvfb/CDP y el perfil persistente ya configurado.
- Las 24 capturas nuevas tienen estado `VALID` y HTTP 200. Se adquirió además una captura raw de la variante filtrada de partidos, también `VALID` y HTTP 200. No se intentó eludir Cloudflare ni se leyó o exportó información de sesión.
- La matriz distingue los snapshots con evidencia de captura (`VERIFIED`) de dos artefactos previos de `luna_audit` (`ARTIFACT_ONLY`). No hay vistas base `BLOCKED`.
- El directorio `data/raw/bdfutbol/20261008T145616.342283Z/` contiene las 24 capturas nuevas. La variante adicional está en `data/raw/bdfutbol/hito_1d_a2_interactions/20261008T150811.648308Z/club_matches_jaen_1rf_2026_27_wins/`. Su SHA-256 es `f1affd1d6de0b32eb4664f004e4e1c38db822d64bd8f14bdb0c151df94d391fe`.
- El snapshot filtrado conserva `rendered.html`, `inventory.json`, `metadata.json` y `summary.json`. Las capturas previas se reutilizaron de forma inmutable.

### Las 24 vistas pendientes adquiridas

| Piloto | Vistas de equipo | Vistas del club permanente |
|---|---|---|
| Villarreal B (`t2026-2794`, `e94`) | [Seguimiento](https://www.bdfutbol.com/es/t/t2026-2794.html?t=seg), [Traspasos](https://www.bdfutbol.com/es/t/t2026-2794.html?t=altas), [Partidos](https://www.bdfutbol.com/es/t/t2026-2794.html?tab=partits) | [Estadísticas](https://www.bdfutbol.com/es/e/e94.html?p=stats), [Jugadores](https://www.bdfutbol.com/es/e/egols94.html), [Entrenadores](https://www.bdfutbol.com/es/e/eentr94.html), [Partidos](https://www.bdfutbol.com/es/p/e94.html), [Rivales](https://www.bdfutbol.com/es/p/er94.html) |
| Lugo (`t2026-2776`, `e76`) | [Seguimiento](https://www.bdfutbol.com/es/t/t2026-2776.html?t=seg), [Traspasos](https://www.bdfutbol.com/es/t/t2026-2776.html?t=altas), [Partidos](https://www.bdfutbol.com/es/t/t2026-2776.html?tab=partits) | [Estadísticas](https://www.bdfutbol.com/es/e/e76.html?p=stats), [Jugadores](https://www.bdfutbol.com/es/e/egols76.html), [Entrenadores](https://www.bdfutbol.com/es/e/eentr76.html), [Partidos](https://www.bdfutbol.com/es/p/e76.html), [Rivales](https://www.bdfutbol.com/es/p/er76.html) |
| Bilbao Athletic (`t2026-2772`, `e72`) | [Seguimiento](https://www.bdfutbol.com/es/t/t2026-2772.html?t=seg), [Traspasos](https://www.bdfutbol.com/es/t/t2026-2772.html?t=altas), [Partidos](https://www.bdfutbol.com/es/t/t2026-2772.html?tab=partits) | [Estadísticas](https://www.bdfutbol.com/es/e/e72.html?p=stats), [Jugadores](https://www.bdfutbol.com/es/e/egols72.html), [Entrenadores](https://www.bdfutbol.com/es/e/eentr72.html), [Partidos](https://www.bdfutbol.com/es/p/e72.html), [Rivales](https://www.bdfutbol.com/es/p/er72.html) |

Jaén ya tenía las seis vistas de equipo y las seis vistas del club (`e49`) capturadas en el hito anterior. Los 48 URLs base se procesaron de nuevo offline; la variante con query se almacenó aparte y no se contó como una página base adicional.

## Inventario deportivo y conciliación

El parser produjo 48 JSON de página base y un JSON separado para la variante. Las 48 vistas base contienen 43.767 observaciones de filas tabulares. El CSV `table_rows.csv` retiene celdas y filas originales; sus filas no equivalen a registros normalizados únicos.

### Equipo-temporada

Las seis vistas conservan estas rutas para cada piloto:

| Vista | Ruta base | Estructura principal encontrada |
|---|---|---|
| Alineación | `/es/t/<team-id>.html` | `taulaplantilla`, relaciones con jugadores, club y temporada. |
| Plantilla | `?t=plantilla` | `c3p1` y tabla de entrenadores; dorsal, persona, nacimiento, demarcación, enlaces e imágenes. |
| Estadísticas | `?t=lista` | `c3p0`, controles de columnas, valores originales, jugadores y fila agregada. |
| Seguimiento | `?t=seg` | `taula-seguiment`, partidos/jornadas y selector de presentación. |
| Traspasos | `?t=altas` | Movimientos con equipo de origen/destino y referencias enlazadas. |
| Partidos | `?tab=partits` | `taula-resultats-plantilla`, tabla de jornadas/resultados y selector de competición. |

Los cuatro equipos exponen 22 posiciones de cabecera y 22 controles en `c3p0`: `#`, foto, país, `Apodo`, `Pos`, `PJ`, `PT`, `PC`, `PS`, `PX`, `C`, `Min`, `TA`, `TR`, `G`, `Minutos/G`, `GP`, `GPP`, `GE`, `PG`, `PE`, `PP`. Las filas de totales tienen `colspan`; el parser las alinea contra las posiciones lógicas de cabecera sin fabricar celdas.

| Equipo | Filas de plantilla | Filas de jugadores en estadísticas | Fila total adicional | Jugadores con cero apariciones | Entrenadores en plantilla |
|---|---:|---:|---:|---:|---:|
| Jaén | 25 | 25 | 1 | 4 | 1 |
| Villarreal B | 26 | 26 | 1 | 5 | 1 |
| Lugo | 30 | 30 | 1 | 6 | 1 |
| Bilbao Athletic | 28 | 28 | 1 | 5 | 1 |

Las cuatro parejas de plantilla/estadísticas reconcilian sus IDs: 109 membresías, 109 IDs de jugador distintos y cuatro IDs de entrenador. Los 20 jugadores con cero apariciones se mantienen como filas reales; no se eliminan por falta de minutos.

El selector `vista_jornades` de Seguimiento ofrece `Partidos` (`p`), `Tarjetas` (`t`), `Goles` (`go`) y `Todo` (`tot`). Se probaron esos modos en el piloto Jaén: conservaron el mismo número de filas y cambiaron los valores/columnas visibles. La interacción cambió la presentación de datos ya presentes; no añadió filas ni generó peticiones de datos deportivos. Se restauró el modo original.

### Club permanente

Cada club cuenta con estas seis rutas:

| Vista | Ruta | Contenido observado |
|---|---|---|
| Perfil/Trayectoria | `/es/e/e<id>.html` | Información del club y tablas de trayectoria, títulos, estadios/nombres y escudos cuando existen. |
| Estadísticas | `/es/e/e<id>.html?p=stats` | Tablas de hitos y eventos; pestañas/categorías internas embebidas en el HTML. |
| Jugadores | `/es/e/egols<id>.html` | Histórico de jugadores con temporadas, participación, resultados, goles, tarjetas y atributos personales. |
| Entrenadores | `/es/e/eentr<id>.html` | Histórico de entrenadores con resultados, temporadas y datos personales. |
| Partidos | `/es/p/e<id>.html` | `tpartits` más tablas agregadas de competición, temporada, resultado, rivales y árbitros. |
| Rivales | `/es/p/er<id>.html` | Históricos separados de rivales jugadores (`t5`), entrenadores (`t6`) y clubes (`t7`). |

En `Jugadores` hay 42 casillas de columna y 42 posiciones en la tabla; dos son estructurales/de presentación (`Posición`, `Bandera`) y las restantes describen identidad, nacionalidad, participación, resultados, minutos, tipos de goles, tarjetas, temporadas, edad, altura y peso. El panel de Jaén permitió ocultar y restaurar una columna: todos los datos seguían en el DOM y no hubo petición deportiva. El selector `Tabla/Listado` del perfil de Jaén ofreció dos modos; alternó tablas ya capturadas sin petición de red ni cambios guardados. No se pulsaron `Recordar` ni `Restablecer`.

`Entrenadores` presenta 25 cabeceras y 25 controles, pero cada fila observada de datos tiene 23 celdas. Las posiciones finales 23 y 24 corresponden a `Altura` y `Peso`, ausentes en el marcado de esas filas. El parser ahora documenta `TRAILING_COLUMNS_OMITTED` con los índices faltantes; no inventa valores nulos ni desplaza las 23 celdas existentes.

| Club | Jugadores históricos | Entrenadores históricos | Rivales jugadores (`t5`) | Rivales entrenadores (`t6`) | Rivales clubes (`t7`) | Opciones de competición en jugadores / entrenadores |
|---|---:|---:|---:|---:|---:|---:|
| Jaén (`e49`) | 918 | 68 | 9.903 | 682 | 251 | 13 / 13 |
| Villarreal B (`e94`) | 359 | 14 | 4.130 | 279 | 124 | 7 / 7 |
| Lugo (`e76`) | 706 | 52 | 8.253 | 572 | 201 | 9 / 9 |
| Bilbao Athletic (`e72`) | 676 | 33 | 9.498 | 663 | 210 | 9 / 9 |

Los listados de jugadores ofrecen filtros de competición y país; entrenadores, los mismos tipos de filtro; rivales, competición, temporada y demarcación. Los filtros tienen cantidades distintas por club (por ejemplo, las temporadas del filtro de partidos de club son 71 en Jaén, 21 en Villarreal B, 56 en Lugo y 60 en Bilbao Athletic). No se recorrieron sus combinaciones. Las vistas históricas de estadísticas también varían: los selectores `cats_stats` tienen 11, 5, 7 y 8 opciones respectivamente, además de 4, 3, 4 y 4 opciones de hitos.

## Caso crítico: partidos del club

En la vista base de Jaén, `tpartits` contiene cabecera pero ninguna fila deportiva. El HTML muestra varias secciones: el tab de partidos está oculto y la vista agregada es la activa por defecto. La inspección del JavaScript estático `scripts_partits.js` confirmó que el filtro lee datos deportivos embebidos en la página y construye la vista según `cat`, `temp` y `pgep`; no se observó XHR/JSON deportivo asociado a las interacciones de controles.

Se capturó la URL exacta [`https://www.bdfutbol.com/es/p/e49.html?cat=1rf&temp=2026-27&pgep=pg`](https://www.bdfutbol.com/es/p/e49.html?cat=1rf&temp=2026-27&pgep=pg). `tpartits` muestra tres victorias de Jaén en 2026/27 en `1rf` y una fila agregada con clase `filatotal`. La tabla base `t1` publica para esa temporada seis partidos y tres victorias (`PJ=6`, `PG=3`). El parser distinguió la fila `filatotal` de las tres filas de partido y la comprobación cruzada dio `VALIDATED`, tres filas, un total y cero filas fuera de los filtros.

La variante recibe `COMPLETE` **solo** dentro de `club=e49; cat=1rf; temp=2026-27; pgep=pg`. La vista canónica de partidos de Jaén, los filtros de empates/derrotas y los partidos filtrados de los otros tres clubes siguen incompletos. Una respuesta filtrada no se suma a las filas de jugadores, relaciones ni páginas canónicas.

## Relaciones, medios y navegación

### Relaciones

El parser reconoce enlaces deportivos con identidad explícita (jugadores, entrenadores, clubes, equipo-temporada, estadios y partidos cuando siguen los patrones conocidos). Excluye el mega-menú global del inventario deportivo. Las relaciones se agrupan por tipo de entidad, ID y URL dentro de cada página, pero cada observación conserva tabla, índice de fila/columna o raíz. El export conserva además URL de origen, hash del snapshot y `variant_id`; por ello el mismo jugador en plantilla actual y en un histórico no se transforma en una sola relación sin procedencia.

El export actual contiene 41.240 relaciones enlazadas y 5.807 observaciones de filas históricas en `club_people.csv`, correspondientes a 2.763 IDs de persona distintos en los cuatro registros de club. Las filas repetidas representan apariciones/filas históricas de origen; no son jugadores nuevos de 2026/27. No se fusionan con las 109 membresías de equipo. Los enlaces detectados son relaciones de procedencia, no una clasificación semántica automática de “fichaje”, “rival” o “participación”.

### Medios y gráficos

Las 48 páginas base contienen 1.887 referencias de imagen (con repeticiones entre vistas), distribuidas principalmente en `/i/eg/` (974), `/i/m/` (493), `/i/lm/` (223), `/img/icons/` (76), `/img/hero/` (48), `/i/t/` (48), `/i/c/` (13), `/i/tg/` (8) y cuatro referencias a `graphic_field.png`. Los prefijos de URL permiten identificar candidatos a escudos y fotos de personas; `/i/c/<club>.jpg` muestra `alt` de estadio (por ejemplo, `La Victoria`, `Lezama`, `Anxo Carro`); `/i/t/` incluye iconos con títulos de ascenso/descenso/competición; `img/icons` y `img/hero` son recursos de interfaz/decoración. La clasificación por prefijo es indicativa, no una inspección visual de cada archivo.

En las referencias observadas no aparecen `srcset`, `data-src` ni `data-lazy-src`; sí se conservan `src`, `alt`, `title`, dimensiones y URL absoluta. No se descargaron imágenes. No se detectaron candidatos a galería/carrusel en los DOM capturados. Se identificaron 56 candidatos gráficos/SVG/canvas, pero no se interpretaron series de datos ni sus fuentes. La existencia de galerías o variantes de foto fuera de estas páginas queda `NOT_TESTED`.

### Interacciones y red

| Control | Resultado observado | Clasificación |
|---|---|---|
| `vista_jornades` (Jaén) | Cuatro modos; mismos registros, representación/celdas visibles distintas. | Cambia presentación; no añade registros. |
| Columnas `egols49.html` | 42 casillas; al alternar `Apodo` cambió la visibilidad de la columna y se restauró. | Filtra columnas presentes; no añade datos. |
| Perfil `e49.html` | `Tabla`/`Listado` alterna las tablas disponibles. | Cambia presentación; no añade datos. |
| `cat=1rf&temp=2026-27&pgep=pg` | Respuesta filtrada con tres partidos y fila total. | Expone una subvista filtrada; los valores provienen del dataset embebido. |

En las interacciones de controles no se observó ninguna petición de datos deportivos; sí se registraron recursos auxiliares de manifest/reCAPTCHA. No se enviaron formularios ni se guardaron preferencias. En las páginas capturadas de jugadores y entrenadores no se encontraron controles de paginación; esto solo acredita las tablas completas del HTML observado, no futuras variantes filtradas.

## Cambios en los extractores y exports

- `collectors/bdfutbol_club_team.py`: la expresión del ID permanente de club ahora captura el grupo numérico que el constructor de URLs ya necesitaba; evita el fallo al derivar `e<id>` desde una página de equipo.
- `providers/bdfutbol/club_team.py` (parser 1.2.0): añade `row_role` (`header`, `data`, `total`, `subtotal`), posiciones lógicas de columna y alineación con `colspan`; reconoce `filatotal`; mantiene huecos de cabecera y filas con columnas finales omitidas. Cada relación incluye `occurrences` con la procedencia de todos sus enlaces repetidos.
- `parsers/club_team_coverage.py`: mantiene la variante filtrada fuera de la matriz de 48 vistas base; valida únicamente la combinación observada contra el agregado `t1`. Distingue estado de adquisición, parseo, validación, completitud de alcance y evidencia.
- `scripts/scrape_bdfutbol_club_team.py`: el modo offline separa URLs de partidos de club con filtros del endpoint canónico, asigna un `variant_id` determinista y pasa esa página como variante.
- `storage/club_team_exports.py`: escribe variantes en `variants/`, matrices de variante JSON/CSV, filas tabulares de variante y procedencia de relación (`source_url`, snapshot, variante y ocurrencias). `team_members` y `club_people` siguen usando solo las páginas canónicas; la variante no altera sus cantidades.
- No se añadieron dependencias, modelos nuevos, scraping de jugadores/entrenadores ni cambios al Dev Explorer.

## Matriz de cobertura

Export generado en `data/parsed/bdfutbol/club_team_2026_27/snapshot-b4450f3d0470d5f4f6aa-parser-1.2.0/`:

| Recurso | Capturadas | Validadas | Completas en alcance | Estado adicional |
|---|---:|---:|---:|---|
| Vistas base (6 de equipo + 6 de club por piloto) | 48/48 | 20/48 | 8/48 | 28 permanecen `PARSED`. |
| Variante partidos Jaén (victorias, `1rf`, `2026-27`) | 1 | 1 | 1 | Completa únicamente en esos filtros. |
| Entidades piloto | 8 | — | 0/8 | Todas `INCOMPLETE`; quedan otras vistas/filtros relevantes. |

Las 20 vistas base `VALIDATED` son: plantilla, estadísticas de equipo, jugadores, entrenadores y rivales para cada piloto. Solo las ocho vistas de plantilla y estadísticas de equipo reciben `COMPLETE`, pues sus filas e IDs se conciliaron en el alcance actual. Alineación, Seguimiento, Traspasos, Partidos de equipo, Perfil, Estadísticas del club y Partidos del club quedan `PARSED`, sin presentarse como completos. La vista base de Partidos de club conserva cero filas en `tpartits`; la variante probada prueba que esa ausencia era estado/filtro, no ausencia real de partidos.

Los indicadores `data_row_count` de tablas incluyen filas no jugador en algunos listados. La cobertura usa `row_role` para no contar el total como partido o jugador cuando se puede identificar. `variant_table_rows.csv` contiene 1.125 observaciones de todas las tablas presentes en la respuesta filtrada, incluidas tablas agregadas que se repiten en el mismo HTML; **no son 1.125 registros deportivos nuevos**. `records_observed=3` identifica los tres partidos filtrados.

## Pendiente antes de una corrida de 40 clubes

1. Probar variantes representativas de partidos (empates/derrotas además de victorias) y confirmar las diferencias entre grupo, temporada y competición en los otros tres clubes.
2. Accionar filtros de competición/temporada/país/posición de jugadores y entrenadores, filtros de temporada/competición/demarcación de rivales, categorías/pestañas de estadísticas y comparación de clubes. Registrar para cada uno si filtra filas locales, solicita otra página o añade datos.
3. Probar modos `Tarjetas`, `Goles` y `Todo` en al menos otro diseño de equipo; por ahora la interacción se verificó en Jaén y las otras tres páginas solo se capturaron.
4. Confirmar las columnas configurables de los otros clubes y estudiar si las columnas omitidas `Altura`/`Peso` de entrenadores se publican en otra vista. Mientras no haya evidencia, conservarlas como ausentes en esas filas, no rellenarlas.
5. Inspeccionar de forma selectiva enlaces de fotografía, variantes reales de retrato, banderas y posibles galerías. No se deben inferir fotografías completas a partir de una ruta de imagen.
6. Validar filas de perfil/estadísticas/partidos que siguen `PARSED` con reglas de reconciliación específicas de tabla; no elevarlas a `VALIDATED` por HTTP 200 o número de snapshots.
7. Revisar presupuesto de almacenamiento antes de los 40 clubes: este export de 48 páginas y una variante ocupa aproximadamente 618 MB porque conserva JSON completos y filas/celdas tabulares duplicadas en CSV, dominado por los históricos de jugadores y rivales. No se descargaron medios. Este tamaño debe medirse por piloto antes de extrapolarlo al lote.
8. Ejecutar un lote pequeño tras resolver los puntos anteriores y revisar todos los estados por club antes de aceptar una cobertura de temporada.

## Viabilidad y preparación

La vía de adquisición es viable con la infraestructura existente: Brave headless mediante Xvfb/CDP, perfil persistente, `BDFutbolAccess` y snapshots raw verificables. La extracción de las 24 vistas pendientes se completó sin desafío. El parser y CLI funcionan sin IA durante la ejecución, conservan valores raw y pueden procesar offline; los snapshots se conservan con hash y las variantes se separan del recurso canónico.

El código puede ejecutar IDs explícitos para más clubes, pero la evidencia de cuatro pilotos **no basta todavía para prometer cobertura sin omisiones en 40 clubes**. La razón concreta son las 28 vistas base que solo alcanzan `PARSED`, las variantes no exploradas y la falta de límites de almacenamiento para históricos extensos. El siguiente paso debería cerrar reglas de validación y filtros críticos y medir almacenamiento con un pequeño lote controlado, no iniciar una adquisición de 40 clubes completa.

## Pruebas

- Suite completa: `158 passed` (incluye una prueba existente que abre un socket loopback; el primer intento del sandbox fue denegado, la repetición con permiso de socket local pasó).
- Ruff en los seis archivos del extractor/CLI/tests modificados: `All checks passed`.
- CLI offline: 49 snapshots parseados (48 base + 1 variante), 109 IDs únicos de jugador, cuatro entrenadores y exports JSON/CSV regenerados.
- No se hizo commit ni push.
