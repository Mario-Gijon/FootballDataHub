# Diccionario semántico: clasificación BDFutbol, Primera Federación Grupo II

## Alcance y evidencia

- Recurso inspeccionado: <https://www.bdfutbol.com/es/t/t2026-271rf2.html>.
- Temporada declarada por la página: `2026-27`; competición visible: `1ª RFEF Grupo II`.
- Navegación de solo lectura realizada el 10-10-2026 con el `BrowserRuntimeConfig`, `BrowserSessionManager`, `BDFutbolAccess`, Brave y el perfil persistente existentes. Respuesta observada: HTTP 200, título `Clasificación 1ª RFEF Grupo II 2026-27 | BDFutbol`.
- La página mostró seis jornadas jugadas; la opción seleccionada era Jornada 6, fechada 04/10/2026. Se identificaron 20 filas de equipo y 20 valores distintos de `data-ideq`.
- El selector principal es `table#classific`, con clases `taula_classificacio` y `taula-classificacio-alineada`. No usar la primera tabla de la página: hay muchas tablas ajenas a la clasificación y una tabla extensa de partidos.
- La fila de encabezados es el primer `<tr>` de `#classific`; no hay `<thead>`. Las filas de equipos tienen `data-ideq`.
- Los filtros y el gráfico se probaron sobre el DOM cargado. No se observó recarga de documento ni petición de datos de clasificación al cambiar los filtros; la función JavaScript recalcula la tabla localmente a partir de estructuras embebidas. Se observó telemetría de Cloudflare y solicitudes de iconos, pero no contenían filas/series deportivas. Esta observación corresponde a la captura examinada, no garantiza que el sitio no cambie.

## Estado de exploración

| Funcionalidad | Estado | Evidencia y límite |
|---|---|---|
| Acceso y pertenencia al Grupo II | Verificada | HTTP 200, título con `Grupo II` y `2026-27`, tabla `#classific` y 20 equipos únicos. |
| Columnas y filas de clasificación | Verificada | Encabezados, atributos, celdas, enlaces y valores reales inspeccionados. |
| Local, visitante y general | Verificada | Se seleccionaron los tres valores y cambió la tabla; general se restauró. |
| Jornada anterior | Verificada | Se seleccionó Jornada 5 y cambió la tabla. Se inspeccionaron las 38 opciones. |
| Incluir/excluir aplazados | Regla del sitio verificada; caso real pendiente | Se cambiaron ambas opciones. La función define aplazado como fecha de partido posterior a la fecha de jornada + 3 días. En jornadas 1–6 no hubo una fila que cambiase al excluirlos; falta contrastar con una jornada que tenga un caso. |
| Rango de fechas | Verificada para un caso | Se probó 29/08/2026–27/09/2026 y la clasificación coincidió con los partidos jugados hasta Jornada 5. |
| Rango de jornadas | Verificada para un caso | Se probó Jornada 2–4 con Jornada 6 seleccionada como límite superior; la tabla se recalculó. |
| Métricas y datos del gráfico | Verificadas en la captura | Los cuatro selectores cambian los datos numéricos del proveedor del gráfico. Sus arreglos están embebidos en JavaScript. |
| Selección de equipos en la leyenda | Verificada | Un clic cambia `hidden` para el equipo en AmCharts; el segundo clic lo restaura. |
| Semántica completa de aplazamientos | Pendiente | Se identificó la llamada a `PartitPostposat`, pero no se pudo contrastar con un aplazado real de este corte. |
| Zonas deportivas de temporadas futuras | Pendiente | Se documenta lo que la leyenda y clases muestran en esta página; no debe generalizarse a otras temporadas o competiciones. |

## Tabla de clasificación

### Selección e identificación de la tabla

Selector fiable: `table#classific`. Comprobar que contiene una fila inicial de encabezados y 20 filas `tr[data-ideq]` con IDs únicos. Un HTTP 200 o el título por sí solos no validan el contenido. La captura explorada contiene otros elementos tabulares, por lo que no se debe elegir una tabla por posición en el documento.

Las columnas de estadísticas están en las celdas 4–12 (índice basado en cero). Las primeras cuatro celdas son movimiento, posición, escudo y equipo. Los encabezados tienen `title` descriptivos y algunos valores son enlaces JavaScript (`datp(...)`), pero el texto visible del enlace es el dato numérico.

| Campo normalizado | Encabezado | Tipo / unidad | Evidencia y extracción | Relación y significado |
|---|---|---|---|---|
| `position` | celda 1, sin texto de encabezado | entero, puesto | Texto numérico de la segunda celda de cada fila de equipo. | Puesto actual en la clasificación del contexto seleccionado. No depender del orden DOM: los encabezados permiten ordenar la tabla. |
| `team_id` | atributo `data-ideq` de `<tr>` | entero identificador | Ej. `tr[data-ideq="49"]`. Es el identificador BDFutbol más estable observado. | Identifica al equipo entre la tabla, enlaces y arreglos de progreso. No derivarlo del nombre. |
| `team_name` | celda 3, enlace `<a>` | texto | Texto del enlace de equipo, p. ej. `Jaén`. | Nombre visible en la fecha de captura; puede cambiar o abreviarse. |
| `team_url` | `href` del enlace en celda 3 | URL | Ej. `../t/t2026-2749.html`; resolver respecto a la URL de la página. | Ficha del equipo. El patrón contiene temporada e ID, pero se conserva el enlace observado. |
| `crest_url` | `src` de `img.escut-mini` en celda 2 | URL de imagen | Ej. `../../i/eg/49.png`; resolver respecto al documento. | Escudo observado. El `<img>` no aporta `alt` o `title` semánticos en esta tabla. |
| `points` | `PTS.` (`title="Puntos"`) | entero, puntos | Celda 4. | Puntos publicados por la fuente; validar contra `3*wins + draws`, sin corregir. |
| `matches_played` | `PJ` (`title="Partidos Jugados"`) | entero, partidos | Celda 5. | Partidos computados en el filtro de clasificación seleccionado. |
| `wins` | `PG` (`title="Ganados"`) | entero, partidos | Celda 6. | Victorias. |
| `draws` | `PE` (`title="Empatados"`) | entero, partidos | Celda 7. | Empates. |
| `losses` | `PP` (`title="Perdidos"`) | entero, partidos | Celda 8. | Derrotas. |
| `goals_for` | `GF` (`title="Goles a favor"`) | entero, goles | Celda 9. | Goles marcados por el equipo según el contexto. |
| `goals_against` | `GC` (`title="Goles en contra"`) | entero, goles | Celda 10. | Goles recibidos según el contexto. |
| `yellow_cards` | `TA` (`title="Tarjetas amarillas"`) | entero, tarjetas | Celda 11. | Tarjetas amarillas mostradas. En el JS de partidos se acumulan como `tg`. |
| `red_cards` | `TR` (`title="Tarjetas rojas"`) | entero, tarjetas | Celda 12. | Tarjetas rojas mostradas. En el JS de partidos se acumulan como `tv`. |
| `position_change` | imagen en celda 1 | enum `up`, `down`, `same`, o `null` | `src` termina en `up.png`, `dn.png` o `none.png`; `<img>` tiene `alt=""` y no tiene `title`. Se comprobó frente a `PRG` de la jornada anterior. | Cambio de puesto respecto a la jornada anterior en la clasificación de comparación. No expresa variación de puntos. En cortes donde no hay comparación fiable, conservar `null`. |
| `zone_code` | clase de la celda de posición | texto de origen | Conservar clases como `prom_puja1`, `prom_puja`, `res`, `prom_baixa`. | Código de zona de la fuente; no es un dato derivado del nombre del equipo. |
| `sports_zone` | leyenda asociada a clases de posición | enum semántico o `null` | La leyenda visible relaciona `prom_puja1` con Ascenso, `prom_puja` con Promoción Ascenso, `res` con Permanencia y `prom_baixa` con Descenso. | La asignación se observó en esta competición/captura. Preservar siempre `zone_code`; no extrapolar estas posiciones a otra edición. |

Las filas examinadas contenían números enteros explícitos, incluidos ceros. En otras capturas, texto vacío o marcador no numérico debe convertirse en `null`, nunca en cero. No apareció un campo que explique sanciones o ajustes de puntos. En el corte observado se cumplió la fórmula `PTS = 3 × PG + PE`; esto no prueba que la fuente nunca publique ajustes.

Los encabezados estadísticos tienen `title` que confirma el significado y enlaces de ordenación `ts_resortTable`. Los valores de estadísticas contienen enlaces `datp(nombre, código, evento)` que abren un panel junto al puntero, con jornada, fecha, equipo local, resultado y visitante. Al pulsar los PTS de Zaragoza se mostraron sus cinco partidos con al menos un punto hasta J6. La función recorre `#resultats`, una tabla oculta de resultados ya presente en el HTML; no hace una petición de datos. El código de `datp` filtra por victorias (1), derrotas (2), empates (3), puntos en partido (4), goles a favor (5), goles en contra (6), amarillas (7) y rojas (8). No usar esos códigos como nombres de columnas: el significado de cada campo se verifica con el encabezado `title` y el valor visible.

### Movimiento y zonas

En la captura actual las clases de posición observadas fueron:

- `prom_puja1`: primer puesto, leyenda Ascenso.
- `prom_puja`: puestos 2–5, leyenda Promoción Ascenso.
- `res`: puestos 6–15, leyenda Permanencia.
- `prom_baixa`: puestos 16–20, leyenda Descenso.

La imagen `up.png` significa que el equipo ganó puestos; `dn.png`, que perdió puestos; `none.png`, que conservó su puesto. Esto se comprobó comparando posiciones de jornadas consecutivas. Guardar el valor y la ruta de imagen original en el snapshot para auditoría; el HTML no contiene `title` explicativo para estas imágenes.

## Controles de clasificación

Todos los controles usan JavaScript de la página. `select_option` de Playwright dispara el cambio del `<select>`. Los controles visibles y sus nombres se deben localizar por ID, no por posición o texto cercano.

| Selector | Valores observados | Efecto y semántica | Interacción y observaciones |
|---|---|---|---|
| `select#classitip` | `1` Local, `2` Visitante, `3` General (inicial: `3`) | Filtra el resultado del equipo como local, visitante o ambos. Se conserva una tabla de 20 equipos y se acumulan partidos/estadísticas según condición local/visitante. | `onchange="recalcula_classificacio()"`; actualiza filas y orden. La leyenda del gráfico no cambió. |
| `select#jornada` | `1`–`38`; etiqueta `Jornada n (fecha)`; inicial observada `6` | Límite superior de jornadas incluidas en el cálculo y selector de clasificación histórica. La opción muestra fecha de calendario/listado de la jornada, no garantiza que un partido aplazado se disputase ese día. | `onchange="recalcula_classificacio()"`; se probó Jornada 5. Las 38 opciones estaban presentes aunque solo se habían jugado seis jornadas. |
| `select#postposat` | `1` Incluidos, `2` No incluidos (inicial: `1`) | La opción 2 pasa `postposats=false` y omite en el cálculo los partidos que `PartitPostposat(fecha, jornada)` identifica como aplazados. La función compara la fecha efectiva del partido con la fecha del selector de su jornada y devuelve aplazado si la primera es posterior a la segunda + 3 días. La fuente parte de listas de resultados `SP[jornada]`. | `onchange="recalcula_classificacio()"`. En J1–J6 no se detectó diferencia; la regla se leyó del JavaScript, pero falta validarla con una jornada que tenga un partido situado más de tres días después de la fecha listada. |
| `select#filtre_dates` | `1` Todas, `2` Filtrar fechas, `3` Filtrar jornadas (inicial: `1`) | El modo 1 no restringe por rango. El modo 2 restringe por fecha de partido. El modo 3 restringe por número de jornada. | `onchange="gestionaFiltres()"` muestra/oculta campos; `recalcula_classificacio()` recalcula la tabla. Las opciones no generaron navegación ni una petición de datos observada. |
| `input#date1`, `input#date2` | texto `dd/mm/aaaa`; `data-init`: 29/08/2026 y 23/05/2027 | Límites de fecha inclusivos: la función omite fechas `< date1` o `> date2`. Los partidos también quedan limitados por la Jornada elegida en `#jornada`. | Visibles con modo 2 (`#divcolumnes`). Los inputs no dispararon por sí solos la función al rellenarlos en la prueba; se llamó `recalcula_classificacio()` después de `fill`. |
| `input#jorn1`, `input#jorn2` | numéricos; `data-init`: 1 y 38 | Límites inclusivos de jornada. La función también limita el recorrido a la jornada seleccionada en `#jornada`; un rango posterior a esa jornada no agrega resultados. | Visibles con modo 3 (`#divcolumnes2`). El piloto 2–4 se probó con Jornada 6 seleccionada. |
| `select#vista_graf1` | `grf_pos` Posición, `grf_pts` Puntos, `grf_gf` Goles a favor, `grf_gc` Goles en contra | Cambia la métrica del gráfico, no la clasificación ni los filtros de la tabla. | `onchange` llama a `vista_graf_progres(...)`; cambian los valores del proveedor JavaScript de AmCharts sin petición de datos observada. |

### Calendario de jornadas publicado en el selector

Las fechas visibles en la captura fueron:

| Jornada | Fecha | Jornada | Fecha | Jornada | Fecha | Jornada | Fecha |
|---:|:---|---:|:---|---:|:---|---:|:---|
| 1 | 30/08/2026 | 11 | 08/11/2026 | 21 | 24/01/2027 | 31 | 04/04/2027 |
| 2 | 05/09/2026 | 12 | 15/11/2026 | 22 | 31/01/2027 | 32 | 11/04/2027 |
| 3 | 12/09/2026 | 13 | 22/11/2026 | 23 | 07/02/2027 | 33 | 18/04/2027 |
| 4 | 20/09/2026 | 14 | 29/11/2026 | 24 | 14/02/2027 | 34 | 25/04/2027 |
| 5 | 27/09/2026 | 15 | 06/12/2026 | 25 | 21/02/2027 | 35 | 02/05/2027 |
| 6 | 04/10/2026 | 16 | 13/12/2026 | 26 | 28/02/2027 | 36 | 09/05/2027 |
| 7 | 11/10/2026 | 17 | 20/12/2026 | 27 | 07/03/2027 | 37 | 16/05/2027 |
| 8 | 18/10/2026 | 18 | 03/01/2027 | 28 | 14/03/2027 | 38 | 23/05/2027 |
| 9 | 25/10/2026 | 19 | 10/01/2027 | 29 | 21/03/2027 |  |  |
| 10 | 01/11/2026 | 20 | 17/01/2027 | 30 | 28/03/2027 |  |  |

Las combinaciones probadas fueron General/Local/Visitante, jornada completa, aplazados incluidos/excluidos, rango de fecha, rango de jornadas y métrica de gráfico. Los controles se pueden combinar; jornada seleccionada es el techo efectivo del recorrido histórico. La captura no valida todos los cruces posibles. No se debe asumir que excluir aplazados es equivalente a recalcular una clasificación general oficial con jornada ya cerrada.

La función de cálculo local recorre los resultados `SP` desde la Jornada 1 hasta la opción seleccionada. En filtros, reconstruye PJ, PG, PE, PP, goles y puntos desde esos resultados y ordena por puntos, diferencia de goles, goles a favor y menor puntuación disciplinaria `rojas × 2 + amarillas`. Para la vista completa general de la última jornada con todos los aplazados incluidos, el código puede restaurar el HTML original, conservando el orden/valores publicados y sin recalcularlos. La presencia de sanciones no se deduce a partir de la fórmula.

## Gráfico «Progreso»

### Librería y controles

La página carga AmCharts 3 (el SVG declara `JavaScript chart by amCharts 3.15.2`), incluidos `amcharts.js`, `serial.js` y el complemento responsive. El contenedor es `#graf_progres1`; el gráfico de serie tiene `categoryField: "jornada"`.

`select#vista_graf1` selecciona Posición, Puntos, Goles a favor o Goles en contra. La leyenda representa los 20 equipos. Se comprobó con un clic real que el estado de una serie cambia de visible a `hidden` y vuelve a visible al repetir el clic. En la carga observada se mostraban inicialmente tres series y se ocultaban las demás.

### Datos numéricos y correspondencia

Los valores están en variables JavaScript embebidas, no en píxeles ni una respuesta JSON/XHR observada:

- `jornades_jugades`: número de jornadas jugadas disponibles para el gráfico; valor observado `6`.
- `PRG[jornada]`: lista ordenada de IDs de equipo, desde el primer puesto; el índice + 1 es la posición de ese equipo en la jornada. El gráfico `grf_pos` transforma la lista en valores numéricos por equipo.
- `PRGP[team_id][jornada - 1]`: puntos acumulados del equipo.
- `PRGGF[team_id][jornada - 1]`: goles a favor acumulados.
- `PRGGC[team_id][jornada - 1]`: goles en contra acumulados.
- En el proveedor de AmCharts la categoría tiene `jornada` y las series se identifican como `J1`, `J2`, etc.; el título de la serie enlaza el campo con el nombre visible. Ese índice de serie es una presentación basada en el orden de equipos y no un identificador estable; usar `team_id` en el modelo normalizado.

Los arreglos contienen valores numéricos reales, aunque no todos los equipos tienen todos los campos en cada jornada. Para Jaén (`team_id=49`) en las seis jornadas observadas: posición `[1, 3, 4, 2, 3, 5]`, puntos `[3, 4, 7, 10, 10, 11]`, GF `[3, 5, 6, 8, 8, 8]` y GC `[0, 2, 2, 3, 5, 5]`. Para Zaragoza (`team_id=39`), posición `[19, 12, 7, 4, 2, 1]` y puntos `[0, 3, 6, 9, 12, 15]`. En esta captura, `PRGGF[40]`, `PRGGC[40]`, `PRGGF[176]` y `PRGGC[176]` no tenían elemento para Jornada 6 (Murcia y FC Cartagena); esas cuatro celdas de progreso deben quedar `null`. No inferir la causa ni repetir el valor de Jornada 5.

Las filas de progreso se deben limitar a `1..jornades_jugades`. Algunas series como `PRGP` ya contienen posiciones futuras repetidas/rellenas; no significan jornadas disputadas. Otros arreglos pueden ser más cortos que el número de jornadas disponibles. Las fechas deben asociarse usando las opciones de `#jornada`, preservando el texto original y una fecha ISO normalizada.

El gráfico permanece igual cuando se cambian clasificación Local/Visitante/General, jornada, aplazados o rangos: es una serie general independiente de los controles de tabla en esta captura. Para el mismo corte general, sus puntos y goles acumulados coinciden con los valores de clasificación examinados. No se deben reutilizar series del gráfico para afirmar resultados de filtros local, visitante o rangos.

## Diferencias entre observado, calculado e inferido

- **Observado:** textos, atributos, clases, imágenes, enlaces, encabezados, opciones de filtros, valores de tabla y arreglos numéricos leídos de la página.
- **Derivado directamente de la fuente:** ID numérico desde `data-ideq`; URL absoluta al resolver `href`/`src`; posición de cada ID desde el orden de `PRG`; fecha ISO a partir del valor visible del selector.
- **Calculado para validar:** `matches_played == wins + draws + losses`; `points == 3*wins + draws`; diferencia y totales de goles. No sustituir valores de la fuente por cálculos.
- **Inferido con evidencia:** sentido de los iconos `up/dn/none` y la relación de clases de zona con la leyenda; ambos se comprobaron en el DOM/gráfico de esta página.
- **No afirmado:** causa de diferencias futuras en puntos, el efecto del umbral de aplazado contrastado con un caso real, ni zonas de otras competiciones/temporadas.

## Limitaciones de la fuente y reglas para el extractor

1. La página combina valores originales de la tabla y resultados recalculados para ciertos filtros; conservar el contexto de captura junto a cada fila.
2. La última jornada disponible se determina leyendo la página, no codificando Jornada 6. Ignorar o marcar como no disputadas las categorías futuras repetidas en arreglos de progreso.
3. No convertir celdas vacías, marcadores ni valores no interpretables en cero. Conservar el texto original en datos de diagnóstico si no se puede mapear.
4. Mantener `zone_code` e icono originales además de la interpretación normalizada.
5. Validar ID único, veinte equipos para una tabla completa, campos numéricos y coherencia deportiva; reportar excepciones de puntos como anomalías, no corregirlas.
6. Los límites de rango y los aplazamientos dependen del algoritmo embebido de BDFutbol. La regla de aplazado se inspeccionó en JavaScript, pero no se observó una jornada real que cumpliera el umbral de más de tres días.
7. Si el acceso devuelve un desafío/denegación, detener la adquisición. Esta exploración recibió HTTP 200 y no automatizó ni resolvió desafíos.
