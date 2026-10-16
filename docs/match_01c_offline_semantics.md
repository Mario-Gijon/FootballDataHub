# MATCH-01C-A — Semántica offline del detalle de partido

## Alcance y estado

Este hito añade un parser semántico de solo lectura para una representación DOM
guardada de BDFutbol y una observación tipada separada del contrato de capturas
publicables. No contiene navegación, adquisición, exportación ni promoción.

El artefacto utilizado como regresión se conserva en el almacén local:

`matches/details/diagnostics/match-detail-inventory-8cf339654c80c0ef/20261016T163942.933046Z-eb9b59e1/`

Su SHA-256 declarado y comprobado para `raw/source.html` es
`9242edad00b43a4e83c649ddad006edb0d1172e0d88640082312a0fe1cf16997` (1.504.876
bytes). El manifiesto también verifica tamaño y SHA-256 de `discovery.json` y
`metadata.json`. La metadata histórica conserva `HTTP 200`,
`access_status=INVALID_CONTENT`, `artifact_type=discovery_only_unverified` y
`promotion_eligible=false`. Un resultado semántico correcto no cambia esos
valores ni autoriza a llamar a `store_valid_capture()`.

## Procedencia e identidad

El parser coteja la URL individual del inventario con su ID, y después valida en
el DOM:

| Evidencia | Selector o referencia | Resultado observado |
| --- | --- | --- |
| Canonical | `link[rel="canonical"][href]` | URL individual `p.php?id=272582` |
| ID de página | `input[name="codi"][value]` | `272582` |
| Equipos | `div.hero.hero-partit h1 .d-none.d-md-block .partit-equip a[href]` | Jaén `e49`, Villarreal B `e94` |
| Marcador | El mismo encabezado, dos `.resultat-partit` | 3–3; copia móvil cotejada por separado |
| Título | `title` | `Jaén - Villarreal B (3 - 3) 10/10/2026 | BDFutbol` |
| Competición y temporada | `.hero-partit .f14` → hermano `.f13`; enlace `/t/t2026-271rf2.html` | Primera Federación, temporada 2026-27 |
| Grupo | Inventario de MATCH-00 | II; no se rotula en la ficha del partido |
| Jornada | `.hero-partit .f14` → `.f13`, enlace con `jornada=7` | Jornada 7 |

El modelo llama `discovery_id` al identificador de diagnóstico; no lo confunde
con `capture_id`. `source_capture_id` y `source_generation_id` son referencias a
los datos de calendario usados para validar contexto, no una afirmación de que
el HTML del partido pertenezca a esa captura.

## Datos parseados en el artefacto 272582

La cabecera deportiva se limita a `.hero.hero-partit`; las alineaciones se
buscan en el contenedor `div.container` hermano posterior y en su fila
`div.row.pt-3.pb-2[style*=overflow]`. No se enumeran tablas de toda la página ni
se usan ordinales globales. Los encabezados `Suplentes` y `Entrenadores`
delimitan secciones; el orden de dos tablas dentro de cada sección conserva los
lados local y visitante observados en esta página.

| Campo | Estado | Valor comprobado |
| --- | --- | --- |
| Equipos e IDs | CONFIRMADO | Jaén `49`; Villarreal B `94` |
| Marcador y fecha | CONFIRMADO | 3–3; 10/10/2026 |
| Hora local | CONFIRMADO | 18:45; zona horaria no publicada |
| Competición, temporada, grupo y jornada | CONFIRMADO con procedencia | Competición/fecha/jornada en DOM; temporada contrastada con enlace y catálogo; grupo solo del catálogo |
| Estadio | CONFIRMADO | La Victoria, ID `100355`, enlace `/s/100355.html` |
| Árbitro | CONFIRMADO | Campos Salinas, ID `601083`, enlace `/r/r601083.html`; vínculo corroborado por `whistle-white.png` |
| Entrenadores | CONFIRMADO | Manolo Herrero y Albelda con enlaces de entrenador |
| Titulares | CONFIRMADO | 11 por lado; ID, nombre, dorsal, enlace/foto si disponible y clase de nacionalidad |
| Suplentes | CONFIRMADO | Jaén 12; Villarreal B 9; mismos campos de identidad; marca de entrada si aparece |
| Goles | CONFIRMADO | 6; goleador, equipo, minuto y marcador acumulado del resumen; penalti separado |
| Tarjetas amarillas | CONFIRMADO | Jaén 2; Villarreal B 5; identidad/minuto vinculados al jugador |
| Tarjetas rojas | AUSENTES en esta página | Sin iconos rojos en las celdas interpretadas y todos los iconos observados reconocidos |
| Sustituciones | CONFIRMADO como sucesos separados | 10 entradas y 10 salidas; se preservan minuto y futbolista, sin emparejarlos |
| Posiciones de jugadores | NO DETERMINADAS | No se publica un código de posición utilizable en las filas |
| Estadísticas agregadas del partido | AUSENTES | No se observó sección/tabla de estadísticas del encuentro |
| Zona horaria | NO DETERMINADA | La fuente muestra hora local sin offset |
| Efeméride | CONFIRMADA como nota adicional | Texto «Gol #1 de Álvaro Gol en 1ª RFEF», enlace al jugador; no se mezcla con eventos del partido |

Las tablas de titularidad y banquillo tienen filas ocultas vacías de presentación;
se ignoran solo cuando `display:none` y no contienen texto. Una fila oculta con
contenido, una fila visible sin enlace de jugador o una estructura distinta
produce error. Las clases originales de nacionalidad se conservan como dato de
fuente y no se convierten a una nacionalidad inferida.

## Eventos, duplicados y reglas

Los goles aparecen dos veces: en el resumen del marcador y como iconos `G` / `GP`
en la fila del jugador. El resumen aporta minuto, goleador y marcador tras el
gol; los iconos se usan para comprobar correspondencia, no se cuentan otra vez.
El icono y el `title` deben coincidir en una lista explícita (`G/Gol`,
`GP/Gol de Penalty`, `TG/Tarjeta Amarilla`, `TR/Tarjeta Roja`,
`Surt/Sale`, `Entra/Entra`). Una combinación desconocida se conserva en la
evidencia como `unknown` y hace fallar la validación semántica.

Los minutos retienen el literal fuente, incluyendo `45+N`/`90+N`, junto con
`minute_base` y `minute_added`. Las filas de entrada y salida son eventos
independientes: una coincidencia de minuto no demuestra qué jugador reemplazó a
cuál. La clase de penalti proviene del marcador `(pen)` y se contrasta con `GP`
en la fila del goleador. Efemérides y otros textos auxiliares quedan fuera de
`events`.

## JSON y contratos

Los dataclasses de `domain.matches.semantic_detail` modelan `source`, `context`,
equipos, lados, alineaciones, marcador, eventos, notas, evidencia y validación.
Los campos con procedencia usan un estado explícito (`observed`,
`explicitly_absent`, `not_observed`, `unresolved`); un cero deportivo no se usa
para representar ausencia. Cada evidencia incluye referencia DOM/catálogo,
valor original, valor normalizado, hash del HTML y versión del parser.

La función `parse_saved_artifact(path, expected_match=...)` verifica el
manifiesto antes de analizar. `parse_match_detail_html(...)` permite probar un
DOM en memoria, siempre cotejando el hash declarado. Ambas son funciones
offline y devuelven `MatchDetailObservation`; ninguna escribe archivos.
`observation_to_payload()` facilita una conversión JSON en memoria, sin
persistencia implícita.

`validation.semantic_valid` significa que la estructura y las reglas semánticas
de esta observación pasan. `source.artifact_access_status` mantiene el estado
histórico y `promotion_eligible` es siempre falso. El fixture real pasa el
parseo semántico, pero sigue siendo un artefacto de descubrimiento `INVALID_CONTENT`.

## Prueba de integración opcional

La prueba `tests/integration/test_match_detail_semantic_latest.py` se omite en
ejecuciones habituales. Cuando existe el almacén local, puede ejecutarse así:

```bash
FDH_MATCH_01C_INTEGRATION=1 \
FDH_MATCH_01C_DATA_ROOT="$HOME/FootballDataHub-data" \
PYTHONPATH=src .venv/bin/python -m pytest -p no:rerunfailures -q \
  tests/integration/test_match_detail_semantic_latest.py
```

Admite `FDH_MATCH_01C_ARTIFACT_DIR` para señalar el artefacto guardado. Si faltan
la generación o el artefacto, el test se omite con un motivo explícito; no
descarga ni recrea datos. Bloquea conexiones de red y comprueba hashes antes y
después del parseo sobre artefacto, generación, capturas fuente y estado de
MATCH-01B.

## Límites antes de MATCH-01C-B

- Se validó una sola página. Variaciones de plantilla, partido suspendido,
  alineación incompleta, doble amarilla, roja directa, autogol y eventos con
  otros iconos requieren muestras independientes antes de aceptarse.
- Los selectores `.hero-partit`, clases de Bootstrap, `.taula_estil`, `.cosa` y
  los títulos de icono son observaciones de un DOM serializado, no un contrato
  estable del proveedor.
- `BrowserDocument.html()` serializó el DOM y no se dispone de los bytes exactos
  del transporte. Scripts externos de anuncios/consentimiento inyectaron gran
  parte del ruido global. No se encontró JSON-LD ni bloque `application/json`
  con datos del partido; el `codi` embebido coincide, pero por sí solo no acredita
  identidad.
- El modelo de esta fase es un contrato de observación experimental y no se
  integra con el contrato promocionable de `details.py` ni con el store.
- Antes de promoción hará falta una segunda validación independiente de la
  identidad completa, política de acceso, variantes estructurales y reglas de
  conteo, seguida de pruebas sobre capturas nuevas autorizadas. Esta fase no
  cambia `INVALID_CONTENT` ni resuelve el bloqueo del piloto.

## Endurecimiento A1

La revisión MATCH-01C-A1 añade estas condiciones semánticas:

- El rótulo de competición debe ser `1ª RFEF`, `Primera RFEF` o
  `Primera Federación`; el enlace de temporada correcto por sí solo no basta.
- Cada gol, tarjeta y entrada/salida reconocida necesita un minuto interpretable.
  Si falta, el texto/evento original queda en `evidence`, su campo queda
  `unresolved` y la validación falla. Los literales `45+N` y `90+N` se conservan.
- No se aceptan IDs de jugador duplicados dentro de titulares o suplentes, entre
  ambas listas del mismo equipo, ni entre los dos equipos.
- Los marcadores parciales de los goles se validan cronológicamente. Los goles
  del mismo minuto se prueban en las ordenaciones posibles hasta encontrar una
  progresión que incremente únicamente al equipo goleador y alcance el resultado
  final. El parser no reordena la colección emitida ni publica una secuencia
  inferida.
- Se cuentan entradas y salidas por equipo. Un desequilibrio genera una
  advertencia verificable, sin emparejar futbolistas ni invalidar por sí solo la
  observación.
- Ninguna evidencia crítica de identidad, competición, temporada, jornada,
  resultado, fecha/hora o eventos puede quedar `unresolved` con
  `semantic_valid=true`.

La ruta personal absoluta `ARTIFACT_ROOT` se eliminó; las funciones del parser
reciben el directorio del artefacto explícitamente.

## MATCH-01C-B — generalización offline y límites de evidencia

Esta extensión amplía los tests sintéticos y corrige supuestos de parseo sin
cambiar el estado ni los bytes de la captura real. La versión del parser es
`match-detail-semantic-0.2.0`.

### Evidencia real, escenarios sintéticos y pendientes

| Estado | Casos |
| --- | --- |
| Confirmado con el único HTML real validado | Jaén 3–3 Villarreal B, 10/10/2026: encabezados responsive, 11 titulares por lado, 12/9 suplentes, entrenador en ambos lados, goles, amarillas, sustituciones y sus minutos. La integración valida el hash original `9242edad00b43a4e83c649ddad006edb0d1172e0d88640082312a0fe1cf16997`. |
| Cubierto solo por fixtures sintéticos | Marcadores 0–0, 1–0, 0–3 y 3–3; penalti añadido, goleador repetido, tiempo añadido, goles al mismo minuto y orden parcial imposible; resumen incompleto/ausente; dorsal vacío; columnas de jugador reordenadas; banquillo/entrenador ausentes; suplencias de cero, múltiples, descanso y añadido; eventos desequilibrados; tarjetas repetidas; clase/título discordantes; filas ocultas vacías/con contenido; URL de jugador ajena; alineación incompleta; ruido global, clases adicionales y atributos reordenados. |
| Requiere nueva evidencia real antes de soportarse | Goles en propia puerta y su iconografía/resumen; alineaciones que no sean de once sin causa identificada; tarjetas dobles con codificación distinta; partido suspendido/abandonado; otras plantillas de tablas, cambios de orden del resumen de goles, iconos de evento nuevos, traducciones u otras variantes responsive. |

Los tests sintéticos prueban cómo responde el parser ante los casos construidos;
no demuestran que BDFutbol publique esas variantes. Los autogoles no se modelan:
un marcador o icono desconocido deja el contenido sin validar en vez de asignar
un evento inferido.

### Reglas conservadoras añadidas

- Los enlaces de jugador se aceptan solo si resuelven a HTTPS, host
  `www.bdfutbol.com`, puerto normal/443 y ruta `/es/j/j<ID>.html`, sin query ni
  fragmento. Un enlace de otro host o forma produce error semántico.
- La celda de dorsal se localiza por su único contenido numérico simple; los
  eventos se inspeccionan en todas las celdas. Así un cambio cosmético de orden
  no desplaza el dorsal ni esconde eventos. Si no hay dorsal, se conserva `null`;
  varios candidatos numéricos hacen fallar la fila en lugar de adivinar.
- Una fila con `display: none` se ignora únicamente si está realmente vacía de
  texto, enlaces, imágenes e iconos semánticos. Se admiten espacios CSS y
  `!important`; una fila oculta con contenido es un error.
- El minuto se reconoce solo cuando el texto completo del evento tiene la forma
  numérica observada (`N`, `N+M`, con apóstrofo opcional; el resumen admite además
  `(pen)`). Un número dentro de una etiqueta como `Evento 17` no se convierte en
  minuto.
- La reconciliación pura de progresión de goles e identidad de alineaciones está
  aislada en `providers/bdfutbol/match_details/semantic_validation.py`. No
  resuelve jugadores por nombre ni modifica la lista de goles para aparentar un
  orden cronológico.

El parser sigue exigiendo dos tablas de titulares, 11 jugadores por equipo y un
resumen de goles estructuralmente reconocible. Un resumen presente pero vacío
puede representar un 0–0; si falta el bloque o no se reconocen sus dos lados, el
parseo falla cerrado. Un banquillo o bloque de entrenadores no observado se
conserva como `None` con advertencia; una tabla observada sin filas de jugadores
se conserva como lista vacía. Una sección desconocida nunca se reclasifica como
titulares/suplentes.

### Rendimiento observado

Se midió el parseo offline de ocho repeticiones del artefacto real de 1.504.876
bytes: mediana 655,73 ms, mínimo 619,75 ms y máximo 728,36 ms en este entorno.
Con `cProfile`, el tiempo instrumentado fue 1,796 s; la construcción del árbol
con `html.parser` consumió 1,395 s y las consultas CSS acumularon 0,315 s. La
instrumentación altera el tiempo absoluto. No se aplicó una optimización de
velocidad: domina la construcción del árbol, y no se establece un umbral a
partir de una sola captura.

La prueba de integración de 272582 continúa siendo optativa y de solo lectura.
Verifica hashes antes y después y mantiene el estado histórico
`INVALID_CONTENT`/`discovery_only_unverified`; el resultado semántico no autoriza
promoción. La cobertura sintética nueva no equivale a una validación de parser
con 140 páginas. Antes de adquirirlas seguirán pendientes muestras reales de
variantes, política y contrato de promoción independientes, además de revisar
los resultados individualmente sin automatizar inferencias.

Validación ejecutada para MATCH-01C-B: 49 tests del parser; 137 tests focalizados
de parser, store, discovery, inventory y adquisición de jugadores; otros 77
tests `test_bdfutbol_player_*.py`; y 1 integración optativa sobre 272582. Ruff y
`git diff --check` pasan. No se ejecutó la suite global del repositorio.
