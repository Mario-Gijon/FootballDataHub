# Hito 1B — Extractor de competición BDFutbol

## Alcance

Este extractor cubre las páginas de Primera Federación 2026/27, Grupos I y II:

- `https://www.bdfutbol.com/es/t/t2026-271rf1.html`
- `https://www.bdfutbol.com/es/t/t2026-271rf2.html`

Lee la clasificación y la tabla completa de calendario presente en el HTML, incluidos los partidos disputados y los programados. No abre fichas de clubes, jugadores, entrenadores, árbitros ni partidos. El parser es offline y no depende de Playwright.

## Estructura comprobada en los snapshots

Los snapshots de discovery usados como integración están en `data/raw/bdfutbol/luna_audit/20261008T121024.595861Z/`. El cargador comprueba que cada `metadata.json` marque `VALID`, que la URL solicitada sea la esperada para el grupo, que el documento responda con HTTP 2xx y que tamaño y SHA-256 de `rendered.html` coincidan con sus metadatos.

Hallazgos verificados directamente en esos HTML:

- `#classific` contiene una fila de encabezados y 20 equipos. Las columnas de puntos/estadísticas ocupan las celdas 5–13 y tienen encabezados `Pts.`, `PJ`, `PG`, `PE`, `PP`, `GF`, `GC`, `TA`, `TR`.
- La tabla `table.taula_estil-16` contiene 38 encabezados de jornada, 38 filas de encabezados de columna y 380 filas deportivas. Cada jornada tiene 10 partidos. Los encabezados no se emiten como partidos.
- Las filas clasificatorias enlazan la página de equipo de temporada (`/t/t2026-….html`). Es el identificador de equipo/temporada que preserva este hito; no se observó en esas filas un ID permanente de club.
- En partidos con resultado, el enlace `../p/p.php?id=…` proporciona el ID y URL del partido. El estadio y el árbitro se enlazan con `/s/{id}.html` y `/r/{id}.html` cuando la fuente los publica.
- Los participantes de cada partido se relacionan con los IDs de equipo/temporada de la clasificación mediante coincidencia exacta de nombre dentro del mismo grupo. La salida registra `exact_standings_name`; una coincidencia ausente o ambigua queda sin referencia y reduce la cobertura.
- El marcador `—` indica que la fuente no publica resultado. No se convierte en `0–0`: goles e ID/URL del partido quedan nulos. `result_status` registra `not_available`; `fixture_status` es `scheduled` si la fecha es posterior a la captura, `unresolved` si la fecha ya pasó, o `unconfirmed` si no se puede comparar. No se deduce que un encuentro sin resultado haya sido aplazado.
- En estos snapshots BDFutbol solo enlaza partidos con resultado. De los 641 partidos sin ID publicado, 640 tienen fecha futura y uno del Grupo II tiene fecha pasada; ese último se deja como `unresolved`.
- Los textos originales de fecha y marcador se preservan junto a las conversiones normalizadas. Una fecha vacía o no interpretable permanece como `null` con `date_raw` intacto. Los campos de estadio y árbitro son nulos cuando no hay enlace.

No se exploran aquí las pestañas alternativas de clasificación ni se comparan otras vistas. La cobertura estructural y el estado de acceso se publican en campos separados. `coverage_complete` describe únicamente la estructura de fixture esperada; no significa que la temporada o sus resultados estén completos.

## Módulos

- `providers/bdfutbol/competition.py`: parsea el HTML a diccionarios deterministas; no accede a red ni navegador.
- `collectors/bdfutbol_competition.py`: valida snapshots offline y, en modo live, captura mediante `BrowserSessionManager`, `BDFutbolAccess` y `capture_dom_snapshot` ya existentes.
- `parsers/competition_coverage.py`: compara filas observadas con expectativas, informa duplicados, jornadas, referencias y campos ausentes; no fabrica registros.
- `storage/competition_exports.py`: escribe JSON/CSV atómicamente en una carpeta derivada de los hashes de snapshots y de la versión del parser. Reprocesar los mismos snapshots reutiliza esa carpeta, sustituyendo salidas parsed en lugar de añadir filas; los snapshots raw no se modifican.
- `scripts/scrape_bdfutbol_competition.py`: interfaz de línea de comandos.

El modo live solo navega a las dos URLs anteriores, en orden. Si `BDFutbolAccess` no devuelve `VALID`, se detiene, informa el estado y no trata el HTML de desafío como datos. Un snapshot válido capturado antes de una interrupción se conserva. No se emplean `requests`, un navegador Playwright nuevo ni mecanismos para resolver o eludir desafíos.

## Ejecución

### Offline

No hace solicitudes de red. Con las capturas existentes:

```bash
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_competition.py offline \
  --group-i data/raw/bdfutbol/luna_audit/20261008T121024.595861Z/competition_group_i \
  --group-ii data/raw/bdfutbol/luna_audit/20261008T121024.595861Z/competition_group_ii
```

Se pueden pasar otros dos directorios snapshot con las mismas reglas de metadata.

### Live

El modo live usa el perfil persistente ya autorizado de Brave y el runtime externo con Xvfb/CDP. La dependencia Python opcional de Playwright se instala con `python -m pip install -e '.[browser]'` si todavía no está disponible; el navegador Brave debe existir en el sistema.

```bash
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_competition.py live \
  --profile ~/.football-data-hub-v2-probe \
  --raw-root data/raw/bdfutbol/competition_2026_27
```

Cada ejecución válida añade snapshots con timestamp bajo `data/raw/bdfutbol/competition_2026_27/`. Nunca reutiliza ni sobrescribe snapshots anteriores. Los snapshots contienen HTML renderizado, inventario DOM y metadata/hash; no se exportan cookies ni credenciales.

## Salidas

Por defecto se generan bajo `data/parsed/bdfutbol/primera_federacion_2026_27/snapshot-<hash>-parser-1.0.0/`:

- `dataset_metadata.json`: versión del parser, clave de extracción y fuente, URL, estado, fecha de captura y SHA-256 de cada snapshot.
- `competition_groups.json/.csv`: competición, temporada, grupo, etiqueta/título de origen, URL y clave de ruta.
- `participants.json/.csv`: grupo, nombre, ID/URL de equipo-temporada y puesto de clasificación. Evita copiar todas las estadísticas a un segundo listado.
- `standings_group_i.json/.csv` y `standings_group_ii.json/.csv`: posición, equipo y nueve estadísticas normalizadas con sus valores fuente. CSV aplana las estadísticas y conserva los valores raw en `stats_raw_json`.
- `matches_group_i.json/.csv` y `matches_group_ii.json/.csv`: jornada/fecha, referencias a equipos, `fixture_status`, `result_status` y resultado raw, goles si los publica la fuente, partido, estadio, árbitro y enlaces/IDs disponibles.
- `quality_coverage.json/.csv`: expectativas y conteos observados por grupo y total, IDs ausentes/duplicados, jornadas, referencias sin resolver, resultados programados y estado de cobertura.

Cada JSON incluye la fecha de captura y el SHA-256 por snapshot en su metadata, además de `parser_version`. Los CSV llevan columnas de procedencia. Los JSON son la salida estructurada completa; CSV es una representación de intercambio.

## Validación offline y live actual

Snapshots `VALID` capturados el 8 de octubre de 2026:

| Grupo | Equipos | Jornadas | Partidos | Disputados | Futuros programados | Fecha pasada sin resultado |
|---|---:|---:|---:|---:|---:|---:|
| I | 20 | 38 | 380 | 60 | 320 | 0 |
| II | 20 | 38 | 380 | 59 | 320 | 1 |
| Total | 40 | 76 | 760 | 119 | 640 | 1 |

Los 760 partidos tienen fecha. Los 640 futuros programados y el partido con fecha pasada sin resultado conservan `result_status=not_available`, goles `null` y `match_id=null`. La clasificación y las referencias de equipos cubren los 40 participantes. No se rellenan IDs ausentes. El informe señala `season_outcomes_complete=false` porque quedan partidos sin resultado.

El modo live también se ejecutó usando el perfil persistente de Brave, Xvfb y CDP. Las dos páginas respondieron `VALID` con HTTP 200; no apareció desafío. Se guardó un snapshot nuevo e inmutable en `data/raw/bdfutbol/competition_2026_27/20261008T123944.246639Z/` y se procesó a la salida `data/parsed/bdfutbol/primera_federacion_2026_27/snapshot-d047191aa847be5c30d7-parser-1.0.0/`. La captura live volvió a producir 20 equipos, 38 jornadas y 380 partidos en cada grupo. Solo se navegaron las dos páginas de competición objetivo.

Las pruebas unitarias incluyen marcador jugado, partido programado, fecha ausente/inválida, árbitro/estadio ausente, resultado inesperado, filas de encabezado, IDs duplicados y HTML sin tablas. Las pruebas de integración leen los snapshots raw reales, validan ambos grupos, y reprocesan dos veces para comprobar que las filas no se acumulan.

## Pendiente para los siguientes hitos

- Confirmar, con capturas nuevas, si BDFutbol mantiene esta estructura y cómo cambia el enlace de fixture cuando un partido pasa de programado a disputado.
- Comparar clasificación con otras vistas y registrar diferencias si aparecen.
- Investigar enlaces de perfil permanente de club, páginas individuales de partido, alineaciones, incidencias y relaciones históricas.
- Ampliar el colector y sus reglas de cobertura a plantillas, jugadores, entrenadores y otras entidades solo después de definir sus campos y evidencia.
