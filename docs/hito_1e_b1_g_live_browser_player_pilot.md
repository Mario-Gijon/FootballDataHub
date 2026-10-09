# Hito 1E-B1-G — Navegación real y piloto de j23751

**Fecha:** 9 de octubre de 2026
**Rama:** `rebuild/football-data-hub-v2`
**Alcance:** las cuatro vistas base de Manu Pedreño (`j23751`). Sin otros jugadores ni filtros capturados.

## Resultado

Se inició Brave con el runtime del repositorio, Xvfb y CDP, usando el perfil persistente autorizado `~/.football-data-hub-v2-probe`. La primera apertura de perfil fue **HTTP 200 / `VALID`** con el contrato corregido. El parser leyó el HTML real y reconoció el jugador, los campos personales y la trayectoria. Después se capturaron, en la misma sesión autorizada y sin desafío, Estadísticas, Partidos y Rivales. Las cuatro vistas quedaron con snapshots inmutables, hashes verificados y estado de parser `PARSED`.

El primer piloto de las cuatro vistas base de `j23751` terminó satisfactoriamente. No se probaron combinaciones de filtros ni se certificó una carrera completa. La adquisición de encuentros individuales sigue sin filas en `#tpartits` para esta captura.

## Inicio y comprobación del entorno

Se revisaron `core/browser_runtime.py`, `core/browser_session.py`, `scripts/smoke_bdfutbol_session.py` y el colector/CLI actual. Se usó el CLI del colector, no el smoke genérico, porque este último apunta a Morillas y su vista de estadísticas. El colector crea `BrowserRuntimeConfig(profile_dir=..., browser="brave")`; el runtime tiene `use_xvfb=True` por defecto, inicia Brave externo bajo `xvfb-run`, reserva CDP en loopback y Playwright se conecta mediante `connect_over_cdp`. La navegación la abrió `BrowserSessionManager`; `BDFutbolAccess` evaluó la respuesta deportiva.

Comprobaciones antes de abrir:

- `/usr/bin/brave`, `/usr/bin/xvfb-run` y Playwright del entorno virtual estaban disponibles.
- El perfil existía con permisos de directorio `0700`; el archivo coordinador del runtime tenía permisos `0600` y no estaba bloqueado.
- No había Brave, Chrome/Chromium, Xvfb, smoke ni scraper en ejecución. No se eliminó el archivo lock ni se interrumpió ningún proceso.
- El sandbox no permite escribir el perfil, que está fuera del repositorio. La ejecución autorizada del CLI necesitó acceso al perfil persistente del usuario. No se leyeron, exportaron ni copiaron cookies o credenciales.

No se cambió IP, perfil, identidad, navegador ni mecanismo de acceso. No se usaron `curl`, `requests` ni Chromium headless. Las sesiones se cerraron mediante el gestor después de cada lote.

## Procedimiento reproducible

El nuevo argumento opcional `--view` del CLI actual permite validar una vista antes de adquirir las siguientes. Si se omite, se conserva el comportamiento anterior de capturar las cuatro vistas base. Se ejecutaron, en este orden:

```bash
# Comprobación inicial y captura inmutable del perfil.
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py live \
  --player-id j23751 --view profile --screenshot

# Solo después de validar y parsear el perfil, capturar las otras tres vistas.
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py live \
  --player-id j23751 --view statistics --view matches --view rivals

# Reprocesar los snapshots locales y producir el export gzip versionado.
PYTHONPATH=src .venv/bin/python scripts/parse_bdfutbol_players_offline.py

# Consultar el plan de reutilización local; no inicia navegador ni red.
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py dry-run
```

La primera ejecución abrió solo el perfil. Al terminar `VALID`, se hizo el parseo offline del perfil y se comprobó identidad, tabla y campos antes de solicitar las otras tres rutas. El segundo lote abrió únicamente esas tres vistas. Total del hito: **cuatro páginas deportivas solicitadas**, sin reintentos. El CLI guarda un estado reanudable tras cada recurso; repetir una selección reutiliza snapshots válidos y no los sobrescribe.

## Evidencia de acceso y snapshots

`http_status` es el status del documento principal de navegación observado por `PageVisit`; es el que usa `BDFutbolAccess`. Cada documento fue HTTP 200, terminó en la URL exacta solicitada y pasó los marcadores/estructura de su vista. No apareció `CHALLENGE_REQUIRED` ni se detuvo el piloto.

| Vista | URL | Captura UTC | Bytes HTML | SHA-256 |
|---|---|---|---:|---|
| Perfil | `https://www.bdfutbol.com/es/j/j23751.html` | `2026-10-09T09:20:29.892590Z` | 990.863 | `b06394be5ffc6809b8f74f19871064d7e6ee7a347fdbf2b7e63da43cb4267752` |
| Estadísticas | `https://www.bdfutbol.com/es/j/j23751.html?p=stats` | `2026-10-09T09:21:21.987907Z` | 974.360 | `5a4b0aa36cba0898fcb7316e11051e1f24914dcf96cec76fd3ffa38959bec2b0` |
| Partidos | `https://www.bdfutbol.com/es/p/j23751.html` | `2026-10-09T09:21:24.098028Z` | 1.056.952 | `8e1c9aaf2c299390a6f54fcff0a6c850719ab87fbf240e5305b96961b801f29e` |
| Rivales | `https://www.bdfutbol.com/es/p/jr23751.html` | `2026-10-09T09:21:27.501266Z` | 2.938.404 | `1a006b47e8bf9fdc20616327909307899323c6c44278fb1aac6f147433ea4813` |

El perfil está en `data/raw/bdfutbol/20261009T092022.507033Z/j23751/profile/`; las otras vistas, en `data/raw/bdfutbol/20261009T092115.395034Z/j23751/`. Cada vista conserva `rendered.html`, `inventory.json`, `summary.json` y `metadata.json`; el perfil además conserva `screenshot.png` (657.758 bytes). El estado de adquisición indica `BASELINE_CAPTURE` para las cuatro. Se comprobó que el hash raw coincide con metadata y que `parse_player_snapshot(..., expected_player_id="j23751")` acepta el ID esperado.

## Validación y datos obtenidos

### Perfil y trayectoria

- Título: `Manu Pedreño, Antonio Manuel Moñino Pedreño - Futbolista | BDFutbol`; `h1`: `Manu Pedreño`.
- `BDFutbolAccess`: `VALID`; `h1` y `.traject` presentes; el extractor compartido con el parser encontró valores no vacíos para `Nombre completo` (`Antonio Manuel Moñino Pedreño`) y `Demarcación` (`Central`). El parser clasificó la vista como `PARSED`, sin roles requeridos ausentes.
- Campos de esta captura: nacimiento `09/10/2000` (26 años mostrados), lugar `Los Garres ( Murcia )`, país de nacimiento `España`, altura `190 cm`, peso `81 kg`. `Nacionalidad` no se encontró en esta captura; no se infiere que no exista en BDFutbol.
- `.traject`: 26 columnas, 10 filas de temporada y una fila Total. Hay 11 encabezados con `display:none` y 13 marcados como opcionales responsive; se preservaron raw junto con `title`, `data-colid`, estilos, índices, celdas y enlaces.
- Trayectoria observada: Almería B (2018-19); Antequera y Murcia (2021-22); Murcia (2022-23); Tarazona (2023-24); Olimpija (2024-25 y 2025-26); UD Ibiza (2025-26 y 2026-27); UD Logroñés (2026-27). Los IDs de equipo-temporada, incluidas las dos pertenencias 2026-27 `t2026-27414` y `t2026-27178`, se conservan como relaciones separadas. Esto no confirma un traspaso ni una carrera completa.
- El parser encontró tres referencias de foto: `23751.jpg`, `23751b.jpg` y `23751c.jpg`. No se descargaron imágenes. El inventario general de página incluye un candidato de galería; no se abrió ni recorrió el carrusel.

### Estadísticas

Estado `VALID`/`PARSED`; no faltan las tablas requeridas. Se encontraron 65 filas de datos por competición, 21 por equipo y 8 filas de hitos: **94 filas interpretadas**. Se conservan las columnas raw y códigos de competición/equipo sin asignar significados no respaldados.

### Partidos

Estado `VALID`/`PARSED`; las cuatro tablas agregadas requeridas están presentes. Se conservaron **114 filas agregadas** por competición (6), temporada (7), equipo (7) y rival (94), además de cabeceras y celdas. `#tpartits` tiene solo la fila de cabecera: **cero encuentros individuales** en este snapshot. La ausencia observada aquí no prueba que la fuente nunca publique filas individuales.

### Rivales

Estado `VALID`/`PARSED`; tablas `t5`, `t6` y `t7` presentes. Se interpretaron **1.452 registros enlazados**: 1.292 jugadores, 88 entrenadores y 72 clubes/equipos. El parser conserva columnas de Jugador/Rival, celdas, enlaces/IDs y ocurrencias; las filas no equivalen necesariamente a personas únicas.

## Controles e interacciones

Se inventariaron las opciones ya presentes en el DOM de las capturas. No se aplicaron filtros ni se enviaron formularios; por tanto, la cantidad de filas que devolvería cada variante sigue pendiente.

| Vista | Controles y opciones raw observadas | Alcance potencial aún no probado |
|---|---|---|
| Perfil | `sel-equip` (Todos y siete equipos); `sel-pais` (Todos, España y Eslovenia). | Recortar trayectoria por equipo o país; no se capturó otra variante. |
| Estadísticas | `cats_milestones`: Segunda División B, 1ª RFEF, Liga de Campeones, Conference League y Copa del Rey. | Seleccionar competición de hitos; no se comprobó si altera además otras métricas. |
| Partidos | `jug`: jugados/no jugados; `pgep`: ganados/empatados/perdidos; rival (94 opciones más Todos), ocho temporadas, siete equipos más Todos y seis competiciones más Todas. | Filtrar los resúmenes por dimensión. No hizo aparecer filas en `#tpartits` porque no se accionó. |
| Rivales | Siete categorías más Todas; ocho temporadas más Todas; cuatro demarcaciones más Todas. | Segmentar las tablas de jugadores, entrenadores y equipos por categoría, temporada o posición; efecto pendiente. |

También se observaron controles comunes `dem` y `pais` en las cuatro vistas; sus efectos no se probaron. No se exploraron combinaciones de filtros, paginación, columnas personalizables ni galerías adicionales.

## Documento principal y recursos auxiliares

El documento principal de cada visita terminó con HTTP 200 y `VALID`; los estados provienen de la respuesta de navegación del frame principal, no de un recurso secundario. El inventario de la página de perfil conserva una entrada `fetch` de telemetría Umami, pero no registra status HTTP por recurso. Por ello este piloto no atribuye éxito o error a cada script, anuncio, manifest o recurso auxiliar. El 403 histórico de `manifest.json` mencionado en auditorías anteriores es de otra observación y no cambia el HTTP 200 de estos documentos.

No se registró ningún error de recurso auxiliar en la metadata de este piloto, pero el formato actual no permite certificar que todos los recursos secundarios respondieran con éxito. Esa limitación se mantiene separada del resultado del documento deportivo.

## Export, cobertura e integración

Se ejecutó el parser offline existente, sin requests ni copia de HTML a la capa parsed. Export nuevo e inmutable:

`data/parsed/bdfutbol/player_2026_27/compact/snapshot-7eb4032e4dea66d10728-parser-0.2.1/`

Contiene 36 archivos comprimidos/metadata y ocupa 2.134.450 bytes. Incluye las páginas del piloto, JSON/CSV gzip, procedencia y cobertura. El resumen consolida las cuatro vistas previas de Morillas y las cuatro nuevas de Manu: ocho capturadas y parseadas, 1.034 jugadores de roster, 1.039 pertenencias y 4.128 vistas base todavía pendientes. Registra dos jugadores con cuatro vistas, 13 filas de trayectoria, 191 filas de estadísticas, 165 agregados, cero partidos individuales y 1.985 registros de rivales. La completitud histórica permanece no certificada.

El dry-run posterior no abrió navegador ni red; informó 15 candidatos, 60 vistas, ocho snapshots válidos y parseados y 52 pendientes. Las cuatro filas de `j23751` señalan `CAPTURED_VALID`, `PARSED` y sus directorios raw. Dev Explorer no se modificó; la salida existente tiene estructura apta para incorporarse más adelante y mantiene procedencia.

## Código y pruebas

Se modificaron únicamente el colector y el CLI de adquisición de jugadores para admitir `--view` repetible. Omitirlo mantiene las cuatro vistas. La opción habilita una validación escalonada y reutilizable; la prueba verifica que una selección `profile` abre y conserva solo esa vista. No hubo variación de DOM que requiriese modificar el parser ni se crearon reglas específicas para Manu.

Validaciones finales:

- Pruebas focalizadas de acceso, colector y parser: **53 passed** antes de la adquisición. La compatibilidad de las pruebas usa snapshots reales de Morillas; el parsing de Manu se comprobó directamente sobre sus cuatro snapshots nuevos.
- Se comprobaron hashes/bytes raw, `metadata.json`, el estado reanudable y el parsing real de las cuatro vistas.
- El fixture sintético de validación del perfil sigue etiquetado como sintético; el resultado de `j23751` procede de HTML raw capturado.
- Suite completa: **233 passed**. El primer intento en sandbox tuvo un fallo ambiental en `test_loopback_port_valid`; al repetir permitiendo ese socket loopback local, todas pasaron sin peticiones externas.
- Ruff sobre los archivos Python modificados: **All checks passed**.
- `git diff --check`: **sin errores**.

## Limitaciones y siguiente paso

El acceso automatizado fue válido durante estas cuatro solicitudes, aunque el antecedente 403/Cloudflare demuestra que puede cambiar. No se resolvieron desafíos ni se descargaron imágenes. No se aplicaron filtros; los agregados por rival y competición no se convierten en partidos individuales. Las cuatro vistas no certifican la carrera completa.

El piloto solicitado queda validado para `j23751`. Los siguientes jugadores no se adquirieron. Cualquier ampliación debe conservar el límite de IDs explícitos y la validación escalonada por vista; las futuras actualizaciones pueden reutilizar los snapshots válidos, usar `--refresh` para producir nuevos raws y volver a ejecutar el parser offline.

No se hizo commit ni push.
