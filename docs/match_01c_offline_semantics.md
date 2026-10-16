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
