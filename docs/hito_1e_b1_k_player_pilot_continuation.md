# Hito 1E-B1-K — Continuación del piloto de jugadores

**Fecha:** 9 de octubre de 2026 · **Rama:** `rebuild/football-data-hub-v2`
**HEAD al iniciar:** `7c0c1c3` (`Hito 1E B1 K`)
**Resultado:** una vista de perfil válida para `j100350`; `j100397/profile` detenido con `CHALLENGE_REQUIRED` HTTP 403. No se solicitaron más páginas después del desafío.

## Alcance y acceso

Se comprobó la rama y el árbol de trabajo antes de empezar: estaban limpios y sincronizados con `origin/rebuild/football-data-hub-v2`. Se revisaron el CLI y el colector existentes y se ejecutó el dry-run offline. El plan enumeraba los dos IDs y sus cuatro vistas: ambos tenían cero snapshots previos y ocho vistas pendientes. El dry-run no abrió navegador ni solicitó red.

La adquisición usó el flujo ya configurado por el proyecto: `BrowserRuntimeConfig` y `BrowserSessionManager`, Brave bajo Xvfb mediante CDP, `BDFutbolAccess` y el perfil persistente autorizado `~/.football-data-hub-v2-probe`. No se cambiaron navegador, perfil, identidad, IP ni mecanismo; no se exportaron cookies ni credenciales. No se encontró un navegador o scraper activo que impidiera iniciar el runtime. No hubo reintentos.

La primera navegación, al perfil de `j100350`, resultó válida. La siguiente navegación solicitada, al perfil de `j100397`, devolvió HTTP 403 y `CHALLENGE_REQUIRED`. El colector registró «Desafío de acceso detectado; no se intenta resolver». Se detuvo ahí: no se abrieron Estadísticas, Partidos o Rivales de ninguno de los dos jugadores después del desafío.

## `j100350` — perfil válido

| Propiedad | Valor observado |
|---|---|
| URL solicitada/final | `https://www.bdfutbol.com/es/j/j100350.html` |
| HTTP / acceso | `200` / `VALID` |
| Captura UTC | `2026-10-09T11:07:01.933782+00:00` |
| Snapshot | `data/raw/bdfutbol/20261009T110653.464860Z/j100350/profile/` |
| HTML | 1.072.016 bytes |
| SHA-256 | `e5e23cac27f4fd09ed58ae02b031c0549b13578ffd3b9194714206cdb06a17e8` |
| Estado de cambio | `BASELINE_CAPTURE` |

El snapshot conserva `rendered.html`, `inventory.json`, `metadata.json`, `summary.json` y `screenshot.png`. Se comprobó que la metadata identifica la URL exacta, el HTTP 200, el estado `VALID` y el mismo hash del HTML. El documento tenía `readyState=complete`, título «Borja Valle, Borja Valle Balonga - Futbolista | BDFutbol», 59 tablas DOM y los elementos `.traject` y `h1` esperados. El parser aceptó el ID solicitado y no señaló roles requeridos ausentes.

### Identidad y datos personales

La ficha identifica a **Borja Valle**, nombre completo raw **Borja Valle Balonga**. Se conservaron fecha de nacimiento `09/07/1992 (34 años)` (normalizada a `1992-07-09` y edad mostrada 34), lugar `Ponferrada ( León )`, país de nacimiento `España`, demarcación `Centrocampista Delantero`, altura `177 cm` y peso `67 kg`. Nacionalidad no aparece en este snapshot; se registra como no encontrada, no como una nacionalidad inferida.

`.traject` contiene 20 filas, de 2009-10 a 2026-27, y la fila raw de 2026-27 enlaza a Ponferradina / `t2026-2762`. La fuente muestra dos filas en 2011-12 (Ponferradina y Celta de Vigo B) y dos en 2016-17 (Deportivo de La Coruña y Elche); se mantienen como filas independientes y no se interpretan como traspasos confirmados. El roster del Hito 1D da seis apariciones para esta pertenencia y posición raw `10`; esto es contraste con un artefacto local previo, no un conteo obtenido de la vista Partidos de este hito. El parser deja la carrera en `NOT_CERTIFIED_COMPLETE`.

La tabla de trayectoria tiene 26 columnas expandidas; el HTML contiene celdas marcadas inline como ocultas y el inventario del perfil registra 242. Los valores raw, enlaces, ceros, guiones y placeholders se conservan. La página tiene siete controles `<select>`; entre los controles deportivos inventariados aparecen `dem` (5 opciones), `pais` (17), `sel-equip` (9) y `sel-pais` (2). No se manipularon filtros. Se conservaron nueve referencias a imágenes del jugador (`/i/j/100350.jpg` y variantes `b` a `i`); no se descargó ninguna imagen ni se verificó su disponibilidad remota.

El DOM también contiene una tabla deportiva adicional de tres filas que el análisis previo identificó como `additional_sports_table`; se conserva como evidencia raw y no se le asigna semántica nueva. El inventario señala además 20 candidatos a gráficos, una galería y cuatro pestañas, pero esta captura de perfil no demuestra el contenido de vistas alternativas ni que esos controles se hayan activado.

### Vistas no adquiridas y partidos

Para `j100350` solo se capturó `profile` (1/4). Estadísticas, Partidos y Rivales siguen pendientes; por tanto, no hay estadísticas por vista, registros de rivales ni `window.P` de este jugador que auditar. No se puede evaluar para él el número de tuplas de 27 posiciones, IDs de partidos, participaciones/no participaciones, duplicados ni coherencia con agregados. Tampoco se pueden contrastar sus partidos de 2026/27 con los exports de Hitos 1B y 1D sin inventar encuentros a partir de los seis apariciones del roster.

## `j100397` — acceso bloqueado

| Propiedad | Valor observado |
|---|---|
| URL solicitada/final | `https://www.bdfutbol.com/es/j/j100397.html` |
| HTTP / acceso | `403` / `CHALLENGE_REQUIRED` |
| Registro | `data/raw/bdfutbol/20261009T110714.482363Z/acquisition_state.json` |

El registro contiene la razón del colector y no identifica marcadores deportivos. En ese directorio de ejecución solo se guardó `acquisition_state.json`; no hay HTML presentado como snapshot deportivo válido. La identidad, trayectoria, fotos, estadísticas, rivales y partidos de esta página no se verificaron live. El roster local del Hito 1D asocia el ID con Nacho José Ignacio Martínez García, equipo-temporada `t2026-27176` y cuatro apariciones; se trata únicamente de evidencia previa de roster, no de una identidad confirmada en esta navegación.

## Reprocesamiento, reuse y export

Se reprocesaron los raws disponibles en modo offline con:

```bash
PYTHONPATH=src .venv/bin/python scripts/parse_bdfutbol_players_offline.py
```

El export inmutable generado es:

`data/parsed/bdfutbol/player_2026_27/compact/snapshot-03c756259f97bb953fc9-parser-0.2.3/`

Tiene parser `0.2.3`, esquema v3, 48 archivos y 6.232.845 bytes. El resumen registra 1.034 jugadores, 1.039 pertenencias, 17 snapshots parseados, 17 vistas capturadas/parseadas, 4 jugadores con sus cuatro vistas, 43 vistas piloto pendientes, 4.119 vistas de jugador pendientes en el total del dataset, 59 filas de trayectoria, 382 filas de estadísticas, 364 filas agregadas de partidos, 1.288 registros individuales de `window.P` y 6.286 registros de rivales. Los 1.288 registros individuales pertenecen a capturas anteriores; `j100350` no aporta filas de Partidos en este hito. La completitud histórica continúa sin certificarse.

Después del desafío se ejecutó un dry-run, que confirmó `browser_started=false` y `network_requested=false`. La vista de perfil válida de `j100350` se volvió a seleccionar con el comando live sin `--refresh`; el colector devolvió `REUSED_VALID` con la misma ruta y SHA, antes de iniciar una sesión de navegador. No se recapturó ni sobrescribió el snapshot. El CLI admite `--refresh` para crear un snapshot nuevo inmutable, pero no se usó: no había motivo para refrescar el perfil recién capturado y el desafío impide continuar ahora.

Comandos reproducibles para una reanudación futura, solo cuando el acceso autorizado vuelva a ser válido:

```bash
# Plan sin navegador ni red
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py dry-run

# Reutilizar capturas válidas y pedir las vistas pendientes de un jugador
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py live \
  --player-id j100350 --player-id j100397

# Refrescar creando snapshots nuevos, sin sobrescribir los anteriores
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py live \
  --player-id j100350 --view profile --refresh

# Reprocesar los raws offline
PYTHONPATH=src .venv/bin/python scripts/parse_bdfutbol_players_offline.py
```

No se recomienda reintentar ahora. Al reanudar, mantener captura escalonada: primero validar el perfil y después solicitar las tres vistas restantes; detenerse ante cualquier nuevo estado inválido o desafío.

## Cobertura de los 15 pilotos

| ID | Vistas base válidas | Estado |
|---|---:|---|
| `j23751` | 4/4 | Capturadas y parseadas |
| `j26481` | 4/4 | Capturadas y parseadas |
| `j100160` | 4/4 | Capturadas y parseadas |
| `j209629` | 4/4 | Capturadas y parseadas |
| `j100350` | 1/4 | Perfil válido; tres pendientes |
| `j100397` | 0/4 | Perfil bloqueado por desafío; tres pendientes |
| `j101816` | 0/4 | Pendientes |
| `j102284` | 0/4 | Pendientes |
| `j103389` | 0/4 | Pendientes |
| `j108959` | 0/4 | Pendientes |
| `j304209` | 0/4 | Pendientes |
| `j304291` | 0/4 | Pendientes |
| `j402372` | 0/4 | Pendientes |
| `j1000865` | 0/4 | Pendientes |
| `j1014877` | 0/4 | Pendientes |

Total: **17/60 vistas base válidas**; no son 6 jugadores completos ni 24/60 vistas. Los dos IDs de este hito no permiten avanzar al siguiente lote de forma segura mientras la última navegación haya recibido un desafío.

## Código, validaciones y recomendación

No se modificaron colectores, parsers, contratos ni Dev Explorer, y no se añadieron pruebas: el único HTML deportivo nuevo satisface el parser existente; la segunda respuesta se clasificó correctamente como desafío y no produjo snapshot deportivo. Se preservaron el raw inmutable, su hash y la procedencia; el reprocesamiento generó un export separado y versionado.

- Tests específicos de jugador: **35 passed**.
- Suite completa dentro del sandbox: **240 passed, 1 falla ambiental** (`test_loopback_port_valid` no pudo abrir un socket local por `PermissionError`).
- Suite completa con permiso limitado para la prueba de loopback local: **241 passed**.
- Ruff en colector, parser, CLI y pruebas relacionadas: **All checks passed**.
- `ruff check .` mantiene seis incidencias preexistentes fuera del alcance: `E713` en `scripts/probe_bdfutbol_headless.py` y cinco `F401` en pruebas de Discovery/Browser Runtime/Browser Session. No se editaron.
- `git diff --check`: sin errores.
- No se hizo commit ni push.

**Recomendación: NO-GO para el siguiente lote y para completar ahora las vistas restantes.** El motivo no es un fallo del parser: `j100350/profile` fue válido y parseable, pero la petición siguiente a `j100397/profile` recibió 403/`CHALLENGE_REQUIRED`. El hito queda parcial, se conserva el raw válido y la ejecución puede reanudarse con reuse después de que el acceso autorizado esté disponible.
