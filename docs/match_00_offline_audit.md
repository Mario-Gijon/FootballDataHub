# MATCH-00 — Auditoría offline de partidos 2026/27

## 1. Estado y aislamiento

- Checkout principal: `rebuild/browser-foundation-v1`, HEAD `5aa574171eab234e0c364b02204456f50b1a2c91`, limpio al empezar.
- Worktree de esta tarea: `/tmp/FootballDataHub-match-00-offline`.
- Rama: `feature/match-00-offline`, creada desde el HEAD indicado.
- Toda modificación de código y documentación de MATCH-00 está en este worktree.
- No se inició navegador, SeleniumBase, Playwright, Chromium o CDP; no se hizo HTTP. PLAYER-01C2 no se inspeccionó, detuvo ni modificó.
- Las capturas de origen se leyeron solamente. No se cambiaron HTML, JSON, manifiestos ni índices originales.

## 2. Fuentes inspeccionadas

### Capturas locales versionadas

| Grupo | Captura | Capturada | Partidos normalizados | Disputados | SHA-256 del HTML |
|---|---|---:|---:|---:|---|
| I | `data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f` | 10/10/2026 20:25 UTC | 380 | 60 | `54b25b054baca6417d0f0fe383944de151164d656b05031ff05d88c16fcbe732` |
| II | `data/exports/bdfutbol/group2_classification/20261010T102656.252222Z-72f200ad` | 10/10/2026 10:26 UTC | 380 | 59 | `3fc2c9ad35696705d4dda4347bb26b2a294e7e3ccc0b90e93cde3a79ed9e1180` |

La salida de Grupo II se encuentra en `derived-res01-20261010T102656Z/normalized/matches.json`; su HTML original sigue en la captura de clasificación. `derived-clas01b` y `derived-res01` son dos derivaciones del mismo `capture_id`, no dos observaciones remotas independientes.

### Capturas externas disponibles localmente

| Grupo | Captura | Capturada | Validadas | Disputados | SHA-256 HTML | SHA-256 `matches.json` |
|---|---|---:|---:|---:|---|---|
| I | `competition-candidates/group1_classification/20261013T103923.024344Z-b785fc3b` | 13/10/2026 10:39 UTC | sí | 68 | `6c1a4c5b30ae19a7e9345594a6c65f6e52b26b0b8086f2d6a8efdb569e85af20` | `39c143da25b40bdc0274c43ec7b9f06dc16eb0877b4794ac21fb4ae81675a474` |
| II | `competition-candidates/group2_classification/20261013T103943.038093Z-1ed28513` | 13/10/2026 10:39 UTC | sí | 68 | `3394b123c963ea4d5284c027c591159e183edfb85b43733516440d3dbd330daf` | `b85f573fe449cbfb3db34f0fd82f1c16fdb97c07f2edd0c698be744bc0e91e96` |
| I | `team03d/classification/group1/20261014T105436.115041Z-ab4f4a09` | 14/10/2026 10:54 UTC | sí | 70 | `11964ca1dd65fdb6e7ef3fe18adbd3af941927dca289356641f190173cfa79a9` | `214c821c0ed9a3bb142c884e185530582d97e3ced6b6abf762548ed5f13aff6` |
| II | `team03d/classification/group2/20261014T105457.351953Z-3bb27f9e` | 14/10/2026 10:54 UTC | sí | 70 | `ca6a6c906572325221a0937bf44009b4ef8c36cbadfb570f7f4f7e89a068f47d` | `4f352d519a7985f6c079b2f2866926d11d302212c5ae4c001829b84f5c983dc2` |

Los dos metadatos de captura del 14/10 dicen `access.status=VALID`, HTTP 200 y URL final igual a la solicitada. Sus `validation/matches.json` declaran `valid=true`. Los SHA del HTML fueron recalculados localmente y coinciden con `normalized/matches.json`.

El código que ya existía es la fuente de interpretación: `providers/bdfutbol/classification/parser.py`, `matches.py`, `match_io.py` y `scripts/extract_bdfutbol_matches.py`. La extracción combina el calendario JavaScript `SP`, el mapa `SE`, `#resultats` y el catálogo de equipos. No se añadió un segundo parser ni una segunda descarga.

## 3. Inventario y matriz de cobertura

La selección de referencia para este informe es la captura local más reciente, del 14/10/2026. Cada grupo tiene 20 equipos, 38 jornadas y diez fixtures por jornada: **380 partidos por grupo y 760 en total**. Los IDs de equipos son únicos entre los dos grupos (40 en total).

| Campo o señal | Grupo I | Grupo II | Total | Evidencia e interpretación |
|---|---:|---:|---:|---|
| Fixtures identificados | 380 | 380 | 760 | 38 × 10 registros de `SP`; sin IDs repetidos. |
| ID BDFutbol de partido | 380 | 380 | 760 | `SP.id`; cadena numérica única dentro del grupo. |
| Jornada | 380 | 380 | 760 | `SP`/posición de la serie, de 1 a 38. |
| Fecha de jornada (`matchday_date`) | 380 | 380 | 760 | Fecha de referencia de la jornada en la captura de clasificación. |
| Fecha del fixture (`source_match_date`) | 380 | 380 | 760 | `SP.d`, preservada como fecha y sin hora. Puede diferir de la fecha de referencia de jornada. |
| IDs de local y visitante | 380 | 380 | 760 | `SP.a1/a2` se resuelven mediante `SE` y el catálogo estable de equipos; la fila de `#resultats` valida local/visitante. |
| Estado parseable | 380 | 380 | 760 | `played` para ambos goles no negativos; `unplayed` para ambos negativos; `incomplete` si solo falta un lado. No es una etiqueta textual oficial. |
| Resultado con marcador | 70 | 70 | 140 | Dos goles numéricos presentes. Los ceros son valores reales. |
| URL individual explícita | 70 | 70 | 140 | Enlace `p.php?id=...` de la fila de resultado. Los 140 enlaces observados corresponden a partidos disputados. |
| Amarillas (local/visitante) | 70 pares | 70 pares | 140 pares | Códigos `tg1/tg2`; ausentes en fixtures sin disputar, nunca convertidos en cero. |
| Rojas (local/visitante) | 70 pares | 70 pares | 140 pares | Códigos `tv1/tv2`; ausentes en fixtures sin disputar. |
| Estadio y enlace | 70 | 70 | 140 | Datos de las filas de partidos disputados con enlace a estadio. |
| Árbitro y enlace | 70 | 70 | 140 | Datos de las filas de partidos disputados con enlace a árbitro. |
| HTML individual de partido guardado | 0 | 0 | 0 | No hay snapshots `p.php` individuales en las capturas de partidos inspeccionadas. El HTML de competición solo conserva los enlaces. |
| Hora y zona horaria | 0 | 0 | 0 | No están en el modelo extraído ni en los campos `SP` observados. |

Estado de la captura del 14/10: 70 disputados, 310 no disputados y 0 incompletos por grupo. El normalizador conserva `null` en marcador y tarjetas para encuentros no disputados. Hay 4 marcadores disputados 0–0 en Grupo I y 5 en Grupo II; no se confunden con un fixture pendiente.

**IDs y URLs no son equivalentes.** Hay 760 IDs `SP.id`, pero solo 140 URL explícitas recuperables del HTML. En los 620 fixtures sin disputar no se observó un enlace individual. No se debe fabricar o considerar válida una URL `p.php` para esos IDs sin evidencia posterior.

## 4. Comprobación del parser con HTML real local

Se repitió offline el parsing de los snapshots del 14/10 usando los módulos existentes y se comparó cada dataclass con el JSON normalizado guardado:

| Grupo | Equipos | Partidos | Disputados | No disputados | Incompletos | Igual al JSON existente | Goles GF/GC balanceados |
|---|---:|---:|---:|---:|---:|---|---|
| I | 20 | 380 | 70 | 310 | 0 | sí, registro por registro | 182 / 182 |
| II | 20 | 380 | 70 | 310 | 0 | sí, registro por registro | 188 / 188 |

La validación también confirma 38 jornadas, diez filas por jornada, referencias a equipos conocidos e IDs únicos. Se comprobó el ejemplo indicado por el usuario: `272582`, Real Jaén (`team_id=49`) 3–3 Villarreal B (`team_id=94`), jornada 7, fecha del partido 10/10/2026, URL explícita `https://www.bdfutbol.com/es/p/p.php?id=272582`.

## 5. Versiones, cambios y discrepancias

Los snapshots son observaciones fechadas, no una tabla que deba sobrescribirse en sitio:

- Grupo I pasó de 60 resultados en la captura del 10/10, a 68 el 13/10 y 70 el 14/10. Entre el 13 y el 14 se publicaron dos partidos de J7: Cultural Leonesa–Arenas de Getxo (ID `269471`, 4–1) y Lugo–UD Logroñés (`269473`, 3–1); en la versión del 13 figuraban sin disputar y con la fecha inicial 11/10.
- Grupo II pasó de 59 a 68 y luego 70. Entre las filas que cambiaron está FC Cartagena–Murcia (ID `272559`, J5): la versión anterior tenía fecha 27/09 y no tenía marcador; la última lo fecha el 07/10 y registra 1–0. Hércules–Sant Andreu (`272580`, J7) pasó a 1–0 el 12/10.
- No se mezclaron esos estados entre capturas ni se repararon los resultados manualmente. La generación MATCH-00 selecciona una captura explícita por grupo; las anteriores permanecen como evidencia con sus hashes y rutas.
- `postponed_by_source_rule` se calcula a partir de la diferencia entre fecha del fixture y fecha de referencia de jornada. No es una etiqueta oficial de aplazamiento. En el snapshot más reciente aparece en una fila del Grupo II, `272559`, cuyo fixture reprogramado ya está finalizado. Se conserva el indicador y la fecha observada, pero no se convierte en un estado oficial `postponed`.
- La fecha de jornada y la fecha del partido tienen semánticas distintas. No son discrepancias por sí solas. No se observó una diferencia irresuelta entre los valores de `SP` y `#resultats` dentro de las dos capturas del 14/10: el parser los contrastó y reprodujo el export guardado.

Los antiguos `derived-clas01b`/`derived-res01` de Grupo II comparten `source_capture_id` y SHA del HTML; la diferencia de extractor o de hora de derivación no equivale a una nueva adquisición.

## 6. ID, deduplicación y procedencia

La clave para un fixture actual debe ser compuesta y namespaced:

`primera-federacion:2026-27:grupo-{I|II}:bdfutbol:{source_match_id}`

MATCH-00 exporta además `internal_id` con ese namespace. El `source_match_id` conserva el ID de BDFutbol; local/visitante siguen referenciando `team_id`. Si en una futura fuente falta un ID, solo se puede proponer una clave auxiliar con temporada, competición, grupo, jornada e IDs de local/visitante cuando ese conjunto sea único. No se fusionarán registros por nombres aproximados.

Cada fila conserva `source_fields`, `source_references`, `source_match_url` (solo donde se vio), estadio y árbitro. La generación incluye por grupo `capture_id`, hora de captura, URL, título, HTTP validado y SHA-256 de `capture.json`, `source.html` y `matches.json`. Para resolver cambios temporales se conserva cada generación; la observación nueva no sustituye ni reescribe la anterior.

## 7. Modelo para MATCH

### Partido básico (`CompetitionMatch`)

Campos observados y ya disponibles: ID interno namespaced, ID de BDFutbol, temporada, competición, grupo, jornada, fecha nominal de jornada, fecha del fixture, IDs de local/visitante, marcador nullable, estado normalizado derivado, URL explícita nullable, snapshot de procedencia, referencias DOM/JavaScript, campos fuente y marcas de validación.

Campos futuros que deben permanecer nullable hasta obtener evidencia: hora, zona horaria, estado oficial (aplazado/suspendido/cancelado/en juego), fecha efectiva separada de fecha programada, alineaciones, dorsales, suplentes, entrenadores y eventos. No asignar `0-0`, hora local ni zona horaria por defecto.

Los tres estados del parser actual (`played`, `unplayed`, `incomplete`) describen la interpretación del marcador, no todos los estados deportivos. Un eventual adaptador de estados oficiales debe conservar también el valor original de la página y mapear solo textos verificados.

### Partido detallado (`MatchDetail` y `MatchEvent` futuros)

El detalle se guardará como una observación aparte ligada al fixture por ID, con su propio `capture_id`, URL, fecha de adquisición y SHA del HTML. Alineaciones, suplentes y entrenadores deben referenciar IDs originales de BDFutbol y resoluciones de entidad verificadas. Un participante sin correspondencia en el inventario conserva su ID/nombre fuente y estado pendiente de resolver.

Cada evento debería preservar tipo fuente, minuto literal (`45+2`, `90+6`), orden de aparición, equipo, jugador(es), texto/campos originales y procedencia. Se puede añadir minuto base y tiempo añadido como campos derivados sin descartar el texto original. Los eventos con autogol, penalti, doble amarilla y sustitución deben codificarse solo cuando la página permita distinguirlos.

### Enfrentamientos históricos

El histórico entre dos clubes se modelará en un dataset separado, con competición y temporada por partido y filtros propios. No se agregará al calendario 2026/27. En los snapshots actuales de clasificación no se encontró un listado de H2H ni un conjunto de IDs históricos; los IDs revisados corresponden a las jornadas de esta temporada.

## 8. Implementación MATCH-00

El parser de calendario/resultados ya existía y se reutilizó, sin modificar el motor de navegador ni las capturas. Se añadió:

- `src/football_data_hub/providers/bdfutbol/classification/generation.py`: revalida HTTP/URL/temporada/grupo, SHA del HTML, vuelve a extraer los registros offline, exige paridad exacta con el JSON, valida 20 equipos y 380 fixtures por grupo, y construye una generación determinista por contenido.
- `scripts/build_bdfutbol_match_generation.py`: CLI que recibe las raíces y JSON explícitos de los dos grupos. Escribe `matches.json`, `validation.json` y `manifest.json` bajo `generations/<generation_id>`; usa staging y rename atómico, no sobrescribe una generación existente y permite repetir la misma entrada de forma idempotente.
- `tests/test_match_generation.py`: prueba las capturas reales versionadas, paridad de cobertura y ceros/nulos; verifica el rechazo de un HTML con hash alterado, determinismo, preservación de entradas y que una generación alterada no se sobrescribe.

El export consolidado conserva el esquema normalizado existente por fixture y lo organiza bajo `groups.I` y `groups.II`. No incorpora API, frontend ni scraping individual. Los JSON originales permanecen como snapshots fuente; el export es un artefacto derivado e inmutable.

## 9. Export preparado

La generación validada y escrita fuera de Git con las capturas del 14/10 tiene ID `match-00-4ad1d610507e425d` en `$HOME/FootballDataHub-data/matches/generations/match-00-4ad1d610507e425d`. Incluye 40 equipos y 760 fixtures; de estos, 140 disputados con URLs individuales explícitas y 620 no disputados sin URL explícita. Los archivos son:

- `matches/generations/match-00-4ad1d610507e425d/matches.json`
- `matches/generations/match-00-4ad1d610507e425d/validation.json`
- `matches/generations/match-00-4ad1d610507e425d/manifest.json`

`manifest.json` fija los hashes y rutas relativos a `$HOME/FootballDataHub-data`. La exportación se hace en un directorio nuevo. No hay puntero `current` ni se publica en FastAPI en este hito.

SHA-256 de los artefactos publicados:

- `matches.json`: `ca8eb351177ed22b4a6e72892d1a8baa2289e6c44c77cc1ceabc9fb0bd64bc50`
- `validation.json`: `2d1a981c5a8df515f0b3c5dded1adc83db40d64831904dc5b06123ec707c300e`
- `manifest.json`: `00166887b13413e3e6a5344fa1c64d52db8d38800f3ef9f282237584b3e65fbf`

## 10. Datos que faltan y plan MATCH-01

Para la temporada actual hay **140 enlaces individuales explícitos**, todos de partidos disputados, pero **0 snapshots HTML de detalle**. Esos 140 partidos requerirían una nueva adquisición de detalle. Los otros **620 fixtures siguen sin disputar en las capturas de referencia y no tienen URL individual explícita**: no se incluyen en un lote de detalle ahora; se reconsideran cuando una captura posterior los marque disputados y muestre su enlace.

Plan recomendado:

1. Usar la generación MATCH-00 y seleccionar únicamente filas `played` con `source_match_url` presente.
2. Deduplificar por temporada/grupo/`source_match_id`; saltar solo capturas detalladas previamente verificadas con mismo ID y SHA.
3. Guardar cada HTML individual en un directorio nuevo, temporal primero; solo promoverlo con HTTP 200, URL final esperada, competición/temporada/grupo, ID, equipos, fecha y marcador contrastados y estructura validada.
4. Ante 403, 404, 429, desafío, CAPTCHA, error 5xx o identidad/estructura inválida: registrar URL, ID, estado, hora y diagnóstico; parar la adquisición; nunca marcar como inexistente/completa ni continuar automáticamente.
5. Conservar snapshots inmutables, hashes, metadatos y resultados de validación; escribir nuevas generaciones de forma atómica y exclusiva.
6. Relacionar jugadores únicamente por ID verificado. Una entidad desconocida se conserva sin vínculo interno; no usar coincidencia aproximada de nombres.
7. No abrir una sesión concurrente ni compartir el perfil mientras PLAYER-01C2 siga activo. La parte offline de MATCH-01 puede prepararse antes; la adquisición real debe esperar a que esa ejecución libere el recurso.

## 11. Pruebas y limitaciones

- Pytest focalizado para parser de clasificación, motor de resultados, exportador nuevo y gestión de sesión: **52 passed** (`7.18s`). Los tests de sesión usan dobles; no abrieron navegador.
- Pytest completo recogió 342 tests, pero no se completó: llegó al 63%, mostró un fallo y después dejó de emitir progreso durante varios minutos. Se interrumpió la ejecución propia con código 130 para no dejar un proceso bloqueado. Pytest no alcanzó a imprimir el nombre ni el traceback de ese fallo, por lo que no se afirma que la suite completa pase.
- Una ejecución aislada de `tests/test_group2_api.py` mostró dos tests y se atascó sin nuevo progreso; también se interrumpió. No se arrancó servidor. Esa suite queda pendiente de ejecutar en un entorno de tests sin la restricción observada.
- Ruff en todo el worktree: **All checks passed**.
- `git diff --check` no encontró errores en cambios rastreados; las cuatro incorporaciones sin seguimiento se comprobaron además con `git diff --no-index --check` y no mostraron errores de whitespace.
- El parser se ejecutó manualmente contra los HTML locales del 14/10, sin red, para ambos grupos y reprodujo exactamente los dos exports guardados. La generación completa pasó validación.

Limitaciones semánticas: no hay hora, zona horaria ni estados oficiales detallados; la URL de partido solo aparece explícitamente para 140 disputados; no hay HTML de detalle ni eventos/alineaciones; `postponed_by_source_rule` es heurístico. Las series son capturas con fecha, no un feed actualizado automáticamente.

Limitaciones semánticas: no hay hora, zona horaria ni estados oficiales detallados; la URL de partido solo aparece explícitamente para 140 disputados; no hay HTML de detalle ni eventos/alineaciones; `postponed_by_source_rule` es heurístico. Las series son capturas con fecha, no un feed actualizado automáticamente.
