# Hito 1E-B1-F — Cierre del validador y preparación del scraper de jugadores

**Fecha:** 9 de octubre de 2026

**Rama:** `rebuild/football-data-hub-v2`

**Modo:** revisión y pruebas offline; sin navegador ni peticiones HTTP.

## Resultado

El colector de jugadores ya permite preparar un lote pequeño explícito, reutilizar snapshots válidos, refrescar sin sobrescribir raw, parar ante contenido inválido o desafíos, reanudar reutilizando lo que sí quedó capturado y reprocesar los archivos locales en exports versionados. Se cerraron dos huecos demostrables: el perfil ya no exige que los campos personales aparezcan en el texto visible del `body`, y un refresco registra si el HTML renderizado difiere byte a byte del snapshot válido anterior.

La observación manual facilitada para `j23751` no es un HTML raw y no demuestra qué contenido recibió el primer intento HTTP 200. La corrección valida el título y una estructura deportiva concreta, y extrae las etiquetas personales mediante la misma regla DOM que usa el parser. Las cuatro vistas reales de Morillas siguen pasando el contrato offline. **El acceso live continúa NO-GO:** la última navegación registrada devolvió HTTP 403 y `CHALLENGE_REQUIRED`; este hito no volvió a navegar.

## Estado inicial y procedencia revisada

Al iniciar este hito la rama era `rebuild/football-data-hub-v2`, con cambios y archivos sin commit del Hito 1E-C0. Se conservaron los catálogos y cambios de C0; este hito modificó el validador/colector pertinentes y añadió sus propias pruebas e informe. No se alteraron snapshots anteriores, los exports existentes, Dev Explorer, otras entidades, ni el código de los scripts CLI.

Se revisaron los seis informes solicitados (1E-A, 1E-A2, 1E-B0, 1E-B1, 1E-B1-D y 1E-B1-E), la auditoría inicial de Luna, el discovery 1E-C0, los scripts de adquisición y parsing, el export histórico de clubes/equipos, el parser de páginas individuales y el escritor de exports.

| Evidencia | Qué se puede afirmar |
|---|---|
| Export de plantillas 1.3.0 | 1.039 pertenencias jugador/equipo-temporada y 1.034 IDs de jugador; 179 pertenencias tienen cero apariciones. Cinco personas aparecen en más de una pertenencia. |
| Cuatro snapshots de Morillas | Artefactos anteriores con metadata `VALID`, HTTP 200 y hashes consistentes; se pueden parsear offline. No son navegación de este hito. |
| Manual de `j23751` | El título y el DOM exterior contienen `Futbolista`; `innerText` no contiene el término ni las etiquetas personales, mientras `textContent` sí contiene `Nombre completo` y `Demarcación`; se informaron `h1` y `.traject`. No hay raw local para ese jugador. |
| Última navegación almacenada | En 1E-C0, una apertura a `https://www.bdfutbol.com/es/j/j23751.html` recibió HTTP 403, título `Just a moment...` y `CHALLENGE_REQUIRED`. Se conservó evidencia diagnóstica mínima, no un snapshot deportivo. |

La causa del primer `INVALID_CONTENT` HTTP 200 continúa sin demostrarse porque su HTML fue descartado. La navegación posterior bloqueada no permite resolver retrospectivamente el contenido de aquella respuesta.

Los cuatro raws individuales preservados en `data/raw/bdfutbol/luna_audit/20261008T121250.991672Z/` tienen estos tamaños y hashes, comprobados en disco durante el reprocesamiento offline:

| Vista | URL capturada | Bytes HTML | SHA-256 |
|---|---|---:|---|
| Perfil/trayectoria | `https://www.bdfutbol.com/es/j/j209629.html` | 944.991 | `30a85e8692083b4a61650d6d462f9db071f65c36347d472c182fa97a20702cfe` |
| Estadísticas | `https://www.bdfutbol.com/es/j/j209629.html?p=stats` | 947.916 | `c907b8f4312a1d124eadc798b788acfd338291812e31b6e18b992d0e69926c6f` |
| Partidos | `https://www.bdfutbol.com/es/p/j209629.html` | 954.066 | `82e0145b2dbd8a83a4b7d9e40aebe90b251e9666116faca557a5b70522753cc0` |
| Rivales | `https://www.bdfutbol.com/es/p/jr209629.html` | 1.608.487 | `907bce9da53247b83dda9a927f9f0c8c1606b343e9709800082aed29029c738` |

## Contrato de validación de perfil

Antes de este cambio, el perfil se validaba con `Futbolista` en el título, `Trayectoria` en el body y una lectura acotada de `.hero .d-none.d-md-block` para `Nombre completo` y `Demarcación`. Ese contenedor provenía de Morillas; su uso como condición fija no estaba demostrado para cualquier perfil y podía dejar fuera campos presentes en el DOM pero fuera de ese bloque responsive.

Ahora el perfil requiere:

1. HTTPS y host BDFutbol permitidos, respuesta 2xx, URL final igual al recurso solicitado y ausencia de desafío/página de error según las comprobaciones existentes.
2. `Futbolista` en el título y `Trayectoria` en el texto del body.
3. Los selectores estructurales `h1` y `.traject`.
4. `Nombre completo` y `Demarcación` como pares etiqueta/valor reconocidos por `_find_profile_value`, la función ya usada por el parser para construir `personal_fields`.

El cuarto requisito analiza `page.content()` en memoria con esa regla de estructura y no depende de `inner_text()` ni busca las palabras sin contexto por todo el documento. Las faltas se informan como `missing_dom_evidence` y producen `INVALID_CONTENT`; no se escribe raw deportivo si falla la validación. No se conserva la respuesta rechazada. El callback es opcional en `BDFutbolAccess`; no cambia los criterios de estadísticas, partidos, rivales, clubes o competición.

El test que simula la distribución reportada para Manu Pedreño está etiquetado como **HTML sintético**. Su estructura de campos parte del patrón del parser y no afirma reproducir el HTML real de `j23751`. El test con Morillas usa los cuatro HTML raw disponibles, y esos tests ya no se omiten con `pytest.skip` si los archivos faltan.

## Datos de jugadores que el parser extrae hoy

El parser sigue en versión **0.2.1**, esquema `football_data_hub.bdfutbol.player_pages.v2`. La fuente observada es una muestra individual: no permite afirmar que esos campos estén disponibles idénticamente en todos los perfiles ni que una carrera esté completa.

| Vista | Evidencia real de Morillas | Interpretación disponible | Raw-only o pendiente |
|---|---|---|---|
| Perfil y trayectoria | `h1`, título, campos personales, `.traject` de 26 columnas; tres filas de temporadas y una fila Total. | Nombre completo, fecha ISO, edad mostrada, lugar y país de nacimiento, demarcación raw, altura en cm; temporadas, equipos, IDs de equipo-temporada y algunas edades/estadísticas enteras. La carrera se marca `NOT_CERTIFIED_COMPLETE`. | Celdas y encabezados literales, IDs y enlaces, estilos, `title`, `data-colid`, columnas ocultas/responsivas, valores `-`, celdas vacías y totales sin reinterpretar. Una referencia de foto está en el HTML; no se descarga. Peso y nacionalidad no aparecen en este snapshot, lo cual no demuestra que falten en el sitio. |
| Estadísticas | Tablas `table-estadistiques-competicions` (73 filas DOM), `table-estadistiques-equips` (23) y tres tablas de hitos. | 97 filas exportadas: 72 métricas por competición, 22 por equipo y tres registros de hitos. Se normalizan celdas decimales enteras. | Abreviaturas, títulos, columnas y valores de origen se preservan sin atribuirles significados no confirmados. Filtros/variantes no se probaron. |
| Partidos | Agregados por competición, temporada, equipo y rival; `#tpartits` con cabecera y sin filas de encuentros. | 51 filas agregadas. Cero filas individuales en esta captura. | Celdas, cabeceras, enlaces e IDs se conservan. No se inventan partidos desde los agregados. Los filtros disponibles están en raw, sin recorrer combinaciones. |
| Rivales | Tablas `t5`, `t6`, `t7`. | 533 registros: 474 jugadores, 30 entrenadores y 29 clubes/equipos en esta captura. IDs de recursos enlazados se extraen cuando la URL los permite. | Se conservan grupos de cabeceras, duplicados, orden, columnas, celdas y enlaces raw. No equivale a un historial exhaustivo. |

El export de roster conserva separadas las pertenencias: `j23751` aparece en `t2026-27178` y `t2026-27414`; `j26481`, en `t2026-27119` y `t2026-2779`, incluida una pertenencia con cero apariciones; `j100160` aparece en `t2026-2788`. No se colapsan dos equipos de una temporada como un traspaso confirmado.

Los controles observados en los snapshots de Morillas incluyen equipo y país en perfil; `cats_milestones` en estadísticas; competición, temporada, equipo, rival, estado de juego y resultado en partidos; y categoría, temporada y demarcación en rivales. El DOM conserva opciones, pero no se capturaron variantes filtradas. Las tablas y celdas raw permiten reparseo, aunque no prueban completitud por jugador ni por temporada.

## Cobertura y completitud

El export de jugadores generado en esta revisión tiene **1.034 jugadores, 1.039 pertenencias y 4.136 filas de cobertura** (cuatro vistas base por jugador). Solo las cuatro vistas de Morillas están capturadas y parseadas; quedan **4.132 vistas pendientes**. Una persona tiene las cuatro vistas disponibles, pero su historial completo no está certificado. Ninguna otra carrera tiene página individual capturada en los raw existentes.

El parser separa `CAPTURED_VALID`, parseo completo/parcial y datos interpretados/raw-only. `NOT_FOUND_IN_CAPTURED_SNAPSHOT` describe únicamente lo observado en una captura; una vista no capturada no se reporta como campo ausente. No se marcan como complete las carreras, la entidad jugador o los filtros que no se han comprobado.

## Auditoría del colector y herramientas existentes

| Componente | Estado comprobado |
|---|---|
| `collectors/bdfutbol_player.py` | Acepta IDs explícitos, limita cada piloto live a tres jugadores y enumera perfil, estadísticas, partidos y rivales. Clasifica rutas, crea un plan determinista y por defecto reutiliza snapshots válidos. |
| Validación por vista | Marcador deportivo por vista; en perfil, título, estructura y campos con el extractor compartido. Verifica URL/ID antes de guardar. Si falla una vista, registra el error y para ese lote. |
| Snapshots raw | Cada corrida usa carpeta nueva con timestamp. Se captura solo después de `VALID`; metadata comprueba URL, status, bytes y SHA-256. `--refresh` crea raw nuevo y deja intacta la versión previa. |
| Reanudación | Guarda `acquisition_state.json` después de cada recurso. Tras interrupción, repetir los mismos IDs vuelve a descubrir raw local y reutiliza páginas válidas; solo solicita las que falten. No requiere ni ofrece un flag `--resume`. |
| Reutilización | `REUSED_VALID` requiere snapshot base usable, hash correcto y URL solicitada/final coincidente. Las variantes filtradas no satisfacen una vista base. |
| Cambio en refresco | Se añadieron `previous_snapshot_directory`, `previous_snapshot_sha256` y `content_change_status`: `BASELINE_CAPTURE`, `UNCHANGED` o `CHANGED`, mediante comparación del SHA-256 del HTML renderizado. Es comparación byte a byte; no una comparación semántica de contenido. |
| `scripts/parse_bdfutbol_players_offline.py` | Lee el roster, snapshots, participantes y auditorías locales; no importa ni abre navegador. Produce JSON/CSV gzip deterministas, páginas parseadas compactas, cobertura y procedencia, sin copiar HTML raw. |
| `storage/player_exports.py` | Escribe en ruta identificada por digest y versión. Repetir la generación verifica el contenido existente; si la ruta inmutable fue alterada, falla en vez de sobrescribirla. La escritura usa archivos temporales y reemplazo atómico. |

No se modificaron los contratos del roster, el parser de salida, el CLI, el escritor de exports ni otra entidad. No se añadió scheduler, base de datos, proxy, dependencia o framework.

## Comandos reales comprobados

Se consultó `--help` de ambos scripts; los argumentos de abajo son los que admite el código actual. Ejecutar desde la raíz del repositorio:

```bash
# Plan local, sin navegador ni red; muestra vistas presentes, pendientes y parseo.
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py dry-run

# El plan solo marca las páginas válidas para recaptura; no ejecuta el refresco.
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py dry-run --refresh

# Lote live explícito, limitado a tres IDs; reutiliza raw válido por defecto.
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py live \
  --player-id j23751 --player-id j26481 --player-id j100160

# Refresco live explícito: crea snapshots timestamp nuevos, no sobrescribe los anteriores.
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py live \
  --player-id j23751 --player-id j26481 --player-id j100160 --refresh

# Reprocesamiento solo local del inventario y snapshots, con exports versionados.
PYTHONPATH=src .venv/bin/python scripts/parse_bdfutbol_players_offline.py
```

Opciones adicionales reales: dry-run acepta `--raw-root`, `--club-sports` y `--batch-size`; live acepta `--raw-root`, `--profile`, `--browser`, `--settle-ms` y `--screenshot`; el parser offline acepta `--raw-root`, `--club-sports`, `--competition-root`, `--participants` y `--output-root`. No se ejecutó ningún comando live. `--refresh` no elude controles: una respuesta de desafío o inválida sigue deteniendo la adquisición.

La ejecución local del dry-run devolvió 15 candidatos, 60 vistas, 4 snapshots válidos disponibles y 56 pendientes, con `browser_started=false` y `network_requested=false`. El procesamiento offline volvió a parsear cuatro snapshots y generó el nuevo export inmutable `data/parsed/bdfutbol/player_2026_27/compact/snapshot-d27b77fd5d7c449ec461-parser-0.2.1/`: 32 archivos, 900.153 bytes. Los exports anteriores continúan en sus directorios versionados.

## Pruebas y validaciones

- Pruebas focalizadas de acceso, colector y parser, con los cuatro snapshots reales de Morillas: **51 passed**; no se omitieron esos tests.
- Las pruebas sintéticas están marcadas en el test y solo verifican el contrato; no se presentan como nuevas capturas BDFutbol.
- Cobertura de test incluye rechazo de HTTP 200 erróneo/incompleto, desafío HTTP 403, URL final de otro jugador, rechazo sin snapshot, reuso, refresco sin/cambio de hash, interrupción y reanudación, parseo offline y protección de exports inmutables.
- Suite completa: **231 passed**. El primer intento dentro del sandbox tuvo un fallo ambiental al reservar un puerto loopback en una prueba existente; al repetir la suite permitiendo ese socket local, todas pasaron. No hubo conexión externa.
- Ruff en los seis archivos Python modificados: **All checks passed**.
- `git diff --check`: **sin errores**.

## Limitaciones y decisión

**Offline: GO** para continuar desarrollando y reparseando con el colector actual. Está preparado para repetir un lote manual de hasta tres IDs, mantener snapshots históricos, reanudar desde raw ya válido, comparar hashes al refrescar y generar exports nuevos.

**Live: NO-GO por acceso**, no por el parser. La última navegación automatizada conocida dio `CHALLENGE_REQUIRED`/HTTP 403. No se ha confirmado que BDFutbol vuelva a permitir la sesión autorizada y no se debe iniciar el primer lote hasta disponer de acceso válido. Cuando cambie esa condición, el siguiente piloto sigue limitado a `j23751`, `j26481` y `j100160`; validar perfil, identidad, estructura, parsing y cobertura antes de ampliar el alcance. La evidencia manual de `j23751` no certifica el raw, la validación completa del perfil ni su carrera histórica.

No se hizo commit ni push.
