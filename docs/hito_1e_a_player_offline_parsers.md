# Hito 1E-A — Perfiles y trayectorias de jugadores (offline)

Fecha: 8 de octubre de 2026. Rama: `rebuild/football-data-hub-v2`.

## Alcance y resultado

Se añadieron parsers deterministas que leen exclusivamente snapshots guardados, un inventario pendiente para los jugadores de Hito 1D-B2, exports JSON/CSV gzip y auditorías locales para las discrepancias del calendario y Cacereño. No se hicieron peticiones HTTP, no se abrió Brave, no se descargaron imágenes y no se tocaron los scrapers, Dev Explorer ni los contratos de Hito 1D-B2. El código no llama a servicios externos.

El parser final es `0.1.4`. Ejecutar el generador desde la raíz del repositorio:

```bash
PYTHONPATH=src .venv/bin/python scripts/parse_bdfutbol_players_offline.py
```

## Snapshots Morillas usados

Las cuatro vistas pedidas están en `data/raw/bdfutbol/luna_audit/20261008T121250.991672Z/`:

| Vista | URL capturada | Captura UTC | SHA-256 de `rendered.html` |
|---|---|---|---|
| Trayectoria/perfil | `https://www.bdfutbol.com/es/j/j209629.html` | 2026-10-08 12:13:04.146178 | `30a85e8692083b4a61650d6d462f9db071f65c36347d472c182fa97a20702cfe` |
| Estadísticas | `https://www.bdfutbol.com/es/j/j209629.html?p=stats` | 2026-10-08 12:13:05.981621 | `c907b8f4312a1d124eadc798b788acfd338291812e31b6e18b992d0e69926c6f` |
| Partidos | `https://www.bdfutbol.com/es/p/j209629.html` | 2026-10-08 12:13:07.834192 | `82e0145b2dbd8a83a4b7d9e40aebe90b251e9666116faca557a5b70522753cc0` |
| Rivales | `https://www.bdfutbol.com/es/p/jr209629.html` | 2026-10-08 12:13:10.146942 | `907bce9da53247b83dda9a927f9f0c8c1606b343e9709800082aed29029c738` |

Los cuatro snapshots señalan `VALID`, HTTP 200 y hash de HTML coincidente con metadata. También existe una captura anterior de perfil en `data/raw/bdfutbol/discovery_0a/20261008T114243.890449Z/morillas`; se conserva en raw, pero el parser usa la captura válida posterior. Los raw no se modificaron. La auditoría de discovery previa está en [bdfutbol_primera_federacion_2026_27_luna_audit.md](bdfutbol_primera_federacion_2026_27_luna_audit.md).

## Hallazgos y parsing de Morillas

### Perfil y trayectoria

La ficha contiene apodo/nombre mostrado `Morillas`, nombre completo `Jaime Morillas Giménez`, fecha de nacimiento `10/08/2004` (la página muestra 22 años), lugar `Sa Pobla ( Islas Baleares )`, país de nacimiento `España`, demarcación `Portero` y altura `185 cm`. El snapshot no contiene etiquetas de peso ni nacionalidad; esto significa **no encontrado en esta captura**, no ausencia confirmada del sitio. Hay una referencia a `https://www.bdfutbol.com/i/j/209629.jpg?v=1731747658`; no se descargó el archivo.

La tabla `.traject` tiene 26 columnas, tres filas de trayectoria y una fila Total. Las filas observadas son 2024-25 Atlético Baleares (`2ªRf`, equipo-temporada `t2024-25130`), 2025-26 Jaén (`2ªRf`, `t2025-2649`) y 2026-27 Jaén (`1ªRf`, `t2026-2749`). Se preservan las columnas originales, celdas completas, títulos, enlaces, índices, estilos y valores ocultos/responsivos. `0`, `-` y celda ausente tienen estados distintos. La fila Total queda como registro raw separado. **Tres filas no certifican la carrera completa.**

### Estadísticas

Se parsean `table-estadistiques-competicions` (73 filas DOM: cabecera y 72 filas de métricas), `table-estadistiques-equips` (23 filas DOM: cabecera y 22 métricas) y tres tablas `.taula-fites-jugador` (una fila de dato cada una; en estas tablas la cabecera aparece después del dato). El export contiene 97 filas deportivas: 72 + 22 + 3. Las columnas de competición son `2ªB`, `1ªRf` y `COP`; las de equipo incluyen `ATL` y `JAÉ`. Los nombres de métricas, encabezados y abreviaturas se conservan literalmente. Solo se convierten a entero las celdas que son enteros decimales; `-` y cero no se colapsan. No se asigna significado nuevo a abreviaturas sin una definición respaldada por la fuente.

Hay diferencias de alcance entre vistas: en la tabla de estadísticas, PJ por competición aparece como 23 en 2ªB, 6 en 1ªRf y 1 en COP, mientras la tabla de trayectoria muestra otro total. No se reconcilian sumando filas ni se infiere que deban coincidir; sus filtros y definiciones requieren una futura comprobación interactiva.

### Partidos

El HTML tiene resúmenes por competición (`t2`, 4 filas de datos), temporada (`t1`, 3), equipo (`t55`, 2) y rival (`t5`, 42): 51 filas agregadas en el export. La tabla `tpartits` solo presenta encabezados y no contiene filas de encuentros. Por eso `individual_match_rows` queda vacío y la cobertura marca `AGGREGATE_ONLY`; **no se fabrican partidos individuales a partir de agregados**.

El snapshot muestra, entre otros, 23 partidos en 2ª RFEF, 6 en 1ª RFEF, 4 de promoción y 1 de Copa de España; por temporadas aparecen 6, 10 y 18, y por equipos 18 y 16. Esos números se mantienen como celdas de sus tablas de origen, no se cruzan para deducir apariciones. Hay controles para competición, temporada, equipo, rival, partidos jugados/no jugados y resultado (ganados/empatados/perdidos), además de filtros comunes de país/demarcación. Los valores y opciones capturados se exportan; no se accionaron.

### Rivales y pestañas

La vista de rivales contiene `t5` jugadores (474 filas de datos), `t6` entrenadores (30) y `t7` equipos/clubes (29): 533 relaciones agregadas. Se conservan encabezados jerárquicos como «Jugador»/«Rival», encabezados repetidos, celdas, URLs/IDs enlazados y filas duplicadas en su orden de origen. El catálogo de relaciones enlazadas reconoce jugadores, entrenadores, equipos de temporada, clubes, partidos, estadios y árbitros cuando las URLs identifican esos recursos.

Las cuatro páginas conservan enlaces de navegación Trayectoria, Estadísticas, Partidos y Rivales, con rutas de vistas distintas. Se corrigió la identificación de Rivales: su URL usa `jr<id>`, que no contiene literalmente `j<id>` como subcadena contigua. Los selectores de Rivales permiten competición, temporada y demarcación; sus opciones, al igual que las de otras vistas, están inventariadas pero no probadas.

## Parser, cobertura e inventario

Los parsers están en `src/football_data_hub/parsers/player_pages.py`; la auditoría de discrepancias, en `player_source_audit.py`; la escritura de exports gzip inmutables, en `src/football_data_hub/storage/player_exports.py`. El script `scripts/parse_bdfutbol_players_offline.py` lee el roster compactado de B2, metadata/raw locales y los participantes de Hito 1B. El script no contiene cliente de red.

Los datos usan `player_id` como clave de persona y cada vínculo jugador/equipo-temporada se conserva como pertenencia independiente. Una temporada puede aportar distintas filas/equipos/competiciones; las filas raw mantienen estadísticas desconocidas, campañas sin estadísticas y ceros sin obligar a una forma única para todos los jugadores. Cinco IDs aparecen en dos pertenencias cada uno; se mantienen como relaciones y **no se etiquetan automáticamente como traspasos**:

| `player_id` | Equipos-temporada |
|---|---|
| `j23751` | `t2026-27178`, `t2026-27414` |
| `j26481` | `t2026-27119`, `t2026-2779` |
| `j304209` | `t2026-2776`, `t2026-2781` |
| `j304291` | `t2026-27104`, `t2026-2758` |
| `j402372` | `t2026-2758`, `t2026-2776` |

Cobertura de entradas del export corregido `snapshot-f36c91119a98390766ff-parser-1.3.0`:

- 1.034 personas únicas y 1.039 pertenencias jugador/equipo-temporada.
- 4.136 requisitos de vista (1.034 × 4). Solo las cuatro vistas de Morillas tienen snapshots válidos y parseados; 4.132 siguen pendientes de captura.
- La URL de perfil procede del enlace de jugador del roster B2. Las URLs de estadísticas, partidos y rivales se generan con patrones vistos en Morillas. Para los otros 1.033 jugadores, solo la URL de perfil procede del roster; las demás rutas siguen **pendientes/no verificadas mediante navegación**.
- Solo Morillas tiene las cuatro vistas; no se descargó ninguna ficha de los otros jugadores.
- La carrera se marca `NOT_CERTIFIED_COMPLETE`, incluso si las cuatro vistas están disponibles.

Por cada jugador/vista, la cobertura distingue snapshot disponible, estado de parsing, campos normalizados, campos conservados raw, etiquetas no encontradas en esa captura, filtros pendientes y contenido aún no investigable sin snapshot. Una vista sin captura no se etiqueta como campo ausente; los selectores tienen estado `NOT_TESTED_OFFLINE_SNAPSHOT_ONLY`. Las capturas brutas no se copian a los exports compactos.

## Auditorías offline de fuentes

### Hito 1B: 119 resultados frente a cero

Se compararon `snapshot-044edc9b2ef3c6026c7f-parser-1.0.0` y `snapshot-d047191aa847be5c30d7-parser-1.0.0`. Cada export tiene 380 fixtures por grupo. Ambos raw de origen son VALID/HTTP 200; los SHA de HTML coinciden entre archivo, metadata y export; no hay IDs duplicados ni marcadores de score sin ID. El primer export registra `result_status=played/scheduled`; el segundo usa `available/not_available` y además `fixture_status=played/scheduled/unresolved`.

El conteo cero sale de contar únicamente `result_status == "played"` en el segundo vocabulario: no prueba que falten resultados. Con score `N N`, goles numéricos, `match_id` y un estado compatible, ambos candidatos contienen 119 partidos jugados: 60 del Grupo I y 59 del II. Sus 119 IDs coinciden y los campos principales comparados (fecha, jornada, equipos/IDs, goles/score, URL del partido, estadio y árbitro) tienen cero diferencias. El segundo candidato tiene además un fixture sin resolver como etiqueta de `fixture_status`; su resultado está sin marcar y no se añade al conteo de jugados.

La selección retenida es `044edc9b2ef3c6026c7f`, porque la metadata del export B2 lo referencia explícitamente. Los criterios son número esperado de filas por grupo, fuente y hash verificables, unicidad de IDs, coherencia entre score/goles/ID, equivalencia de datos entre exportaciones y procedencia. No se eligió por tener más filas marcadas literalmente `played`.

### Cacereño: PJ 8 frente a seis de 1ª RFEF

La tabla raw del equipo-temporada `t2026-27149` (`tab=partits`) contiene ocho filas con marcador: seis etiquetadas `Liga` y dos `Copa Federación`. La tabla agregada raw del club `e149`, fila 2026-27, indica PJ 8, PG 4, PE 2, PP 2, GF 9 y GC 5; coincide en esas columnas con el export B2. La variante B2 filtrada `cat=1rf` contiene los seis IDs de Liga: `269409`, `269423`, `269430`, `269440`, `269456`, `269461`.

Los dos adicionales son `09/09/2026`, Dieciseisavos de final, Cacereño 2–0 San Pedro (ID `427720`), y `16/09/2026`, Octavos de final, Recreativo de Huelva 2–1 Cacereño (ID `427726`). Por tanto la diferencia de alcance se explica con evidencia en raw: total de partidos de temporada frente a solo Liga. Los snapshots usados son `data/raw/bdfutbol/20261008T155328.317550Z/t2026-27149/team_matches/` (SHA `f17380247c7ad55dc7b73e8c0a14194989359a66cfbfce6c2e150e715fb0e26d`) y `club_matches/` (SHA `4f42d41ae795b68c47dbc84ffda08d0414bb4160a7870d2c20bb6c24289ceddf`).

## Exports y reproducibilidad

El export final está en `data/parsed/bdfutbol/player_2026_27/compact/snapshot-d93c3704475407ba6c67-parser-0.1.4/`. Incluye JSON y CSV gzip para `players`, `memberships`, `profiles`, `trajectory`, `statistics`, `matches`, `rivals`, `relationships`, `coverage`, `acquisition_manifest` y `source_audit`, más metadata/resumen y los cuatro JSON parseados por vista. Los JSON de una página son compactos; ningún HTML se incluye. La gzip se genera con timestamp cero y el destino es inmutable: si existe un snapshot con el mismo ID pero contenido distinto, el escritor falla en vez de sobrescribir.

El resumen exportado registra: 1.034 jugadores, 1.039 pertenencias, 4 snapshots parseados, 3 filas de trayectoria + una fila Total raw, 97 filas de estadísticas, 51 agregados de partidos, 533 registros de rivales y 551 ocurrencias de relaciones. No se declara cobertura histórica completa. Las carpetas anteriores `parser-0.1.1`, `parser-0.1.2` y `parser-0.1.3` se conservan como exports versionados intermedios; el resultado final y actualizado es `parser-0.1.4`.

## Pruebas, límites y siguiente piloto

Las pruebas offline cubren perfil y ausencia de campos en el snapshot, carrera con temporada repetida/equipos distintos/totales, columna oculta, cero frente a placeholder, cabecera de hitos posterior al dato, resumen agregado sin fixtures, filtros, tablas jerárquicas y duplicados, relaciones/IDs, membresías múltiples, export reproducible y mapeo de estados/integridad de las auditorías.

Comprobaciones ejecutadas:

- `PYTHONPATH=src .venv/bin/python -m pytest -q`: **190 passed**. El sandbox bloquea la prueba existente que abre loopback; la repetición local autorizada del suite completo pasó.
- Ruff en los seis archivos de este hito: **All checks passed**.
- `ruff check .` global todavía informa seis incidencias ajenas a este cambio, en `scripts/probe_bdfutbol_headless.py`, `tests/test_bdfutbol_discovery.py`, `tests/test_browser_runtime.py` y `tests/test_browser_session.py`; no se editaron esos archivos.

Para el siguiente piloto de adquisición, usar el manifiesto como lista esperada y seleccionar una muestra pequeña que incluya perfiles con posiciones distintas, al menos un jugador con apariciones cero y uno de los cinco IDs con más de una pertenencia. Capturar raw de las cuatro rutas por jugador, comparar filtros relevantes con snapshots nuevos y revisar que el parser preserve cada tabla/celda antes de ampliar el lote. Aún no están comprobadas las variantes filtradas, paginación, galerías adicionales, carga dinámica, partidos individuales desde Partidos, ni la totalidad de la carrera histórica. Ningún resultado actual demuestra que peso o nacionalidad estén ausentes de BDFutbol: solo faltan en el snapshot de Morillas inspeccionado.
