# Hito 1F-A1 — Inventario offline de entidades y códigos deportivos

## Alcance y método

Auditoría realizada el 09/10/2026 exclusivamente con exports parsed, snapshots y metadatos locales. No se abrió Brave, no se usó CDP, no se hizo ninguna petición y no se ejecutó adquisición. El contexto recibido indica que el acceso live continúa detenido por `CHALLENGE_REQUIRED`; este hito no volvió a comprobar ese estado.

El generador elige los exports válidos más recientes disponibles: clubes/equipos parser 1.7.0 y jugadores parser 0.2.3. Recorre referencias de sus JSON gzip y metadatos `data/raw/bdfutbol/**/metadata.json`, deduplica por tipo e ID y conserva URLs observadas, fuentes, snapshots, hashes, capturas verificadas por metadata, relaciones y campos pendientes. No modifica exports ni snapshots. El manifiesto comprimido queda en `data/analysis`, ignorado por Git; este documento contiene el resumen versionable.

Artefacto completo: `data/analysis/bdfutbol/entity_coverage_audit/entity_inventory.json.gz` (30 MB). Incluye 101.353 entidades deduplicadas y evidencia por registro. El estado `CAPTURED_VALID` requiere metadata local con `VALID`, HTTP 200, hash registrado y `rendered.html` presente. Se conserva el SHA-256 publicado por metadata; el generador no vuelve a hashear todos los HTML raw. Las referencias y los enlaces no equivalen a páginas adquiridas.

## Inventario deduplicado

El manifiesto combina referencias de varias tablas; por eso se indican tanto IDs únicos como filas fuente relevantes. Sus `source_reference_records` son evidencias deduplicadas agrupadas por entidad y no deben interpretarse como el número de filas raw originales.

| Entidad | IDs únicos en el catálogo | Adquiridos válidos | Pendientes | Referencias fuente destacadas |
|---|---:|---:|---:|---|
| Partidos | 47.913 | 1 | 47.912 | 47.449 IDs del historial de clubes; 52.904 observaciones; 1.288 filas individuales de jugadores (1.241 IDs) y relaciones adicionales |
| Jugadores | 44.329 | 5 perfiles | 44.324 | 1.034 jugadores y 1.039 membresías actuales; 295.922 relaciones de club, 47.362 filas `club_people` y 5.654 relaciones desde fichas individuales |
| Entrenadores | 2.956 | 1 | 2.955 | 41 registros actuales; 19.617 relaciones de club, 4.278 filas `club_people` y 389 relaciones desde vistas de jugador |
| Árbitros | 2.091 | 1 | 2.090 | 47.449 partidos del export principal tienen un `referee_id_raw` |
| Estadios | 64 | 1 | 63 | 251 referencias de estadios desde fichas de club |
| Clubes | 876 | 40 | 836 | 8.098 relaciones de club y referencias de fichas de personas; 40 son los participantes actuales, todos con páginas base capturadas |
| Equipos-temporada | 3.124 | 40 | 3.084 | 21.616 enlaces desde clubes, 122 desde vistas de jugadores y 1.039 membresías actuales |

Los 876 clubes y 3.124 equipos-temporada reúnen referencias históricas enlazadas desde las páginas capturadas, además de los participantes actuales. Los 40 IDs actuales de club y sus 40 equipos-temporada 2026/27 están capturados. Los IDs históricos existen como referencias explícitas de la fuente; el catálogo no los deriva del nombre de un equipo ni los asigna retrospectivamente a partidos.

### Partidos y encuentros individuales

El export de clubes contiene 47.449 `match_id` únicos y 52.904 observaciones de fuente. Cada partido del índice tiene una URL observada con el patrón `/es/p/p.php?id={match_id}`. Las filas conservan fecha, IDs de club local/visitante, goles normalizados, código raw de competición/jornada/temporada y `referee_id_raw`. Para los partidos con dos lados capturados se mantienen ambas observaciones con URL de origen, club de captura, fecha y hash.

Las vistas de jugadores aportan 1.288 filas individuales de `window.P`, 1.241 IDs de partido, de los que 777 aparecen también en el historial de clubes y 464 añaden un ID al conjunto deduplicado. El catálogo final contiene 47.913 partidos únicos. No elimina filas de origen repetidas ni presupone que una fila sea una aparición del jugador.

Hay un snapshot raw válido de ficha de partido, `269462`. Las alineaciones, sustituciones, eventos detallados y los datos no conservados por las fuentes parsed siguen pendientes. El cruce con competición mantiene `AMBIGUOUS_VALID_SOURCES` y `NOT_RUN_NO_SELECTED_COMPETITION_SOURCE`; el manifiesto retiene la evidencia de la discrepancia. No se usa ese cotejo para marcar partidos como ausentes.

### Jugadores

Hay 1.034 IDs de jugadores del inventario actual distribuidos en 1.039 membresías jugador/equipo-temporada. El export 0.2.3 contiene cinco perfiles capturados: cuatro jugadores tienen las cuatro vistas base; Borja Valle tiene perfil y sus otras tres vistas pendientes. En total, de las 4.136 combinaciones jugador/vista actuales, hay 17 capturadas y parseadas y 4.119 pendientes. Son cinco perfiles válidos, no cobertura de carrera completa.

Las relaciones de clubes y jugadores elevan a 44.329 los IDs distintos de jugadores referenciados en los datos históricos disponibles. Solo cinco tienen ficha individual capturada localmente. Los otros 43.295 son referencias históricas fuera del inventario actual de 1.034; quedan en el manifiesto como candidatos pendientes, sin mezclarse con el lote inicial de jugadores.

Las URLs de perfil `/es/j/j{ID}.html` aparecen en las membresías. Las vistas de estadísticas, partidos y rivales están diferenciadas por `?p=stats`, `/es/p/j{ID}.html` y `/es/p/jr{ID}.html`. Las capturas y el estado de cada vista se registran por jugador.

### Entrenadores, árbitros y estadios

- **Entrenadores:** 41 IDs distintos aparecen como cuerpo técnico actual en el export; el conjunto de relaciones históricas amplía el inventario a 2.956. Se conservan `coach_id` (`l…`), nombre raw, fecha de nacimiento raw cuando existe y las relaciones de club/equipo-temporada respaldadas por cada fila. Existe una ficha individual raw válida para `l1835`; no hay carrera completa parseada para el resto.
- **Árbitros:** los 47.449 registros del export de partidos conservan un ID raw, con 2.091 IDs distintos. Solo `r602267` tiene una ficha individual local válida. Su ruta observada es `/es/r/r602267.html`; `/es/r/r{ID}.html` se guarda como URL candidata para otros IDs, no como URL individual verificada.
- **Estadios:** 251 referencias de fichas de club producen 64 IDs distintos, con nombre y enlace de fuente cuando existen. Una ficha de estadio (`s/81.html`) está capturada. La ruta `/es/s/{ID}.html` aparece directamente en las relaciones de club. Los partidos parsed no contienen `stadium_id`; no se asocia un estadio a un partido por proximidad, nombre de club o estadio mencionado en otra página.

### Clubes y equipos-temporada

El inventario incluye 876 clubes enlazados desde datos históricos y páginas de personas. Los 40 clubes participantes actuales tienen sus vistas base capturadas. `club_id` identifica al club permanente; `team_season_id` (`t…`) se mantiene separado. Las URLs `/es/e/e{ID}.html` y `/es/p/e{ID}.html` aparecen en fuentes locales y se preservan como rutas distintas.

Se encontraron 3.124 IDs de equipo-temporada enlazados, 40 actuales y 3.084 históricos. Las referencias históricas proceden principalmente de las trayectorias en las fichas de club; algunas también aparecen en trayectorias de jugadores. Son IDs publicados por la fuente, pero no permiten asignar con seguridad una identidad de equipo-temporada histórica a cada fila de partido. En concreto, el export consolidado marca esa identidad como `NOT_ESTABLISHED`.

## Códigos de posición

Se contrastó `position_raw` de las 1.039 membresías con `Demarcación` de perfiles individuales cuyo snapshot está capturado y válido. La asociación usa el mismo `player_id` y conserva hashes de ambos lados:

| Código raw | Etiqueta observada en perfil | Evidencia local | Estado |
|---:|---|---|---|
| `1` | `Portero` | `j209629`, una membresía | Verificado para el jugador observado |
| `2` | `Lateral derecho` | `j100160`, una membresía | Verificado para el jugador observado |
| `4` | `Central` | `j23751`, dos membresías | Verificado para el jugador observado |
| `10` | `Centrocampista Delantero`; `Delantero` | `j100350` y `j26481` | Etiquetas en conflicto; se conserva raw |
| `3`, `5`, `6`, `9` | Sin etiqueta enlazada a un perfil válido local | No hay muestra de perfil correspondiente | Sin verificar; se conserva raw |

Estas comprobaciones verifican pares concretos, no un diccionario global. El perfil de Borja Valle y el de Armero muestran etiquetas distintas asociadas al código `10`; el generador no elige una interpretación. El catálogo dentro del manifiesto guarda cada par, los IDs, las URLs y ambos SHA-256. No se inspeccionaron controles de páginas nuevas ni se inventaron nombres para códigos no muestreados.

## Relaciones y claves

- **Partido → clubes local/visitante:** `match_id` junto con `home_club_id` y `away_club_id`, tomados de cada fila de partido; nombres y marcador permanecen como evidencia auxiliar.
- **Partido → árbitro:** `match_id` → `referee_id_raw`; el ID procede del partido y puede usarse como clave de entidad árbitro en el inventario. La ficha objetivo queda pendiente salvo el árbitro capturado.
- **Partido → estadio:** no hay clave/ID de estadio en las filas históricas; no se crea esta relación.
- **Jugador → club/equipo-temporada:** `(player_id, team_season_id)` identifica la membresía actual conservada; la relación a `club_id` viene en la misma fila. Las trayectorias mantienen los IDs enlazados originales.
- **Entrenador → club/equipo-temporada:** `coach_id` enlazado en cuerpo técnico actual y en referencias históricas de fichas de club. Cada vínculo retiene la página/fila/hashes que lo acreditan.
- **Club → estadio:** solo se registra como enlace de ficha de club observado, sin reinterpretarlo como sede de un partido concreto.

Claves estables para el inventario: IDs del proveedor por entidad (`match_id` numérico, `player_id` `j…`, `coach_id` `l…`, `club_id` `e…`, `team_season_id` `t…`, árbitro y estadio en su representación de origen). No se fusionan registros por similitud nominal. Las relaciones incluyen dirección, rol, URL y procedencia de snapshot cuando la fuente la conserva.

## Pilotos recomendados para adquisición futura

Son candidatos desde el inventario, no capturas ni autorización para navegar. Elegidos para cubrir datos fuente representativos con más de una referencia local y sin snapshot individual válido:

1. **Ficha de partido:** `272569`, `https://www.bdfutbol.com/es/p/p.php?id=272569`, 03/10/2026, Hércules 0–0 Jaén, jornada raw `Jornada 6`, dos observaciones fuente. El export no establece grupo para esa fila. El detalle no está capturado.
2. **Entrenador:** `l1865`, Manuel Pablo, `https://www.bdfutbol.com/es/l/l1865.html`. Aparece como entrenador actual con relación a `e104`/`t2026-27104`; la ficha individual no está capturada.
3. **Árbitro:** `602675`, referido por el partido candidato. Se recomienda comprobar primero que la ruta candidata `https://www.bdfutbol.com/es/r/r602675.html` es correcta cuando el acceso vuelva a estar autorizado. Esa URL concreta no fue observada/capturada; solo hay un ejemplo local de ficha con el patrón `/r/r{ID}.html` (`r602267`).
4. **Estadio:** ID `38`, `Estadio de la Cerámica`, `https://www.bdfutbol.com/es/s/38.html`, enlace directo observado desde una ficha de club. No se afirma que sea el estadio del partido piloto; su página individual no está capturada.

Secuencia futura sugerida: primero comprobar el acceso autorizado y una sola página; validar identidad, estado y snapshot; después adquirir y parsear una entidad por vez; registrar cambios de estado en el manifiesto; pausar de inmediato ante desafío o contenido inválido. No arrancar lotes amplios hasta validar cada contrato y su procedencia.

## Reproducción offline

Desde la raíz del repositorio:

```bash
PYTHONPATH=src .venv/bin/python scripts/build_entity_coverage_audit.py
```

La ejecución selecciona los exports locales válidos más recientes y escribe el manifiesto en `data/analysis/bdfutbol/entity_coverage_audit/entity_inventory.json.gz`. Se puede elegir otro destino local con `--output RUTA`; `--repo-root RUTA` permite regenerarlo desde otra copia de los mismos exports y raw. Usa solo la biblioteca estándar más los validadores de export locales del proyecto. El gzip y el JSON se serializan de forma determinista para las mismas fuentes.

## Validación y límites

Las capturas directas se clasifican usando metadata raw (`access_status`, HTTP, SHA registrado y existencia de `rendered.html`). El generador no revalida semánticamente el DOM, no calcula de nuevo todos los SHA-256 raw y no convierte URLs candidatas en páginas adquiridas. Las referencias de estadios pueden venir de trayectorias y fichas, no de partidos. Las trayectorias fuente no certifican carreras completas. Los códigos de posición continúan raw cuando no hay correspondencia inequívoca.

Suite completa: `PYTHONPATH=src .venv/bin/python -m pytest -q` terminó con **275 passed in 57,26 s**. Las cinco pruebas nuevas cubren patrones/IDs URL, deduplicación, retención de procedencia en relaciones, clasificación conservadora de posiciones y estados pendientes/bloqueados.

`.venv/bin/ruff check src/football_data_hub/audits/entity_inventory.py scripts/build_entity_coverage_audit.py tests/test_entity_inventory.py` pasó sin incidencias. `ruff check .` mantiene seis incidencias preexistentes ajenas a este hito: una en `scripts/probe_bdfutbol_headless.py`, una en `tests/test_bdfutbol_discovery.py`, tres en `tests/test_browser_runtime.py` y una en `tests/test_browser_session.py`. No se modificaron. `git diff --check` terminó limpio.
