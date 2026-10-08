# Hito 1E-B1-D — Diagnóstico de `INVALID_CONTENT` en perfiles

**Fecha:** 2026-10-08  
**Rama:** `rebuild/football-data-hub-v2`

## Resultado y decisión

La causa del `INVALID_CONTENT` original de `j23751/profile` queda **sin determinar (E: evidencia insuficiente)**. El intento del Hito 1E-B1 registró HTTP 200, URL final correcta y ausencia del marcador `Futbolista`, pero no conservó el HTML rechazado ni una captura diagnóstica de su contenido. Por eso no es posible distinguir entre una página deportiva válida rechazada por el marcador, renderizado incompleto o una respuesta alternativa HTTP 200.

La única navegación diagnóstica autorizada en este hito encontró **CHALLENGE_REQUIRED (C: restricción de acceso)**: HTTP 403 y título `Just a moment...`. Se detuvo inmediatamente. Esta respuesta impide volver a diagnosticar el contenido, pero no demuestra cuál fue el contenido del intento HTTP 200 anterior.

**NO-GO para reintentar `j23751/profile`** mientras la única navegación nueva termine en desafío y no haya evidencia del HTML original. No se modificó código productivo ni se relajó ninguna validación.

## Regla de validación anterior

- `BDFutbolAccess.assess_bdfutbol_access` no fija el literal `Futbolista`. Exige que el llamador proporcione uno o más marcadores no vacíos y comprueba que **todos** aparezcan como subcadenas del texto del `body`, ignorando mayúsculas/minúsculas.
- El colector `collectors/bdfutbol_player.py` pasa un marcador obligatorio por vista:

  | Vista | Marcador obligatorio |
  |---|---|
  | `profile` | `Futbolista` |
  | `statistics` | `Estadísticas` |
  | `matches` | `Partidos` |
  | `rivals` | `Rivales` |

- `BrowserSessionManager.open_page` navega con `wait_until="domcontentloaded"` y timeout de navegación de 45 s. El colector usa `settle_ms=1200`; después `BDFutbolAccess` observa el título y texto del `body` cada 400 ms durante hasta 12 s para esperar contenido semántico o detectar un desafío. No recarga ni interactúa con la página.
- El colector escribe un snapshot solo tras `VALID`. También comprueba que la URL final clasifique como el mismo ID y vista antes de llamar a `capture_dom_snapshot`.
- El parser clasifica la vista desde la ruta. Para el perfil reconoce la tabla `.traject` con rol `career_trajectory`, extrae el `h1` y campos personales; si faltan tablas requeridas informa `PARSED_PARTIAL_TABLE_SET`. Su validación ocurre después de conservar una captura y no explica el rechazo de acceso del Hito 1E-B1.

## Evidencia offline de Morillas

Los cuatro HTML locales de Morillas tienen metadata histórica `VALID`, HTTP 200 y hashes coincidentes. Son **ARTIFACT_ONLY**: se inspeccionaron los artefactos existentes, sin navegación nueva para este análisis.

| Vista | Evidencia observada | Marcador de esa vista | ¿Contiene `Futbolista`? |
|---|---|---|---|
| Perfil `j209629.html` | Título con nombre, `h1` `Morillas`, campos personales y tabla `.traject`; la documentación previa registra 26 columnas, 3 filas de trayectoria y una fila Total | `Futbolista` | Sí |
| Estadísticas `?p=stats` | Título de estadísticas y tablas deportivas | `Estadísticas` | Sí |
| Partidos `/es/p/j209629.html` | `h1` `Morillas`; tablas agregadas y `#tpartits` sin filas individuales | `Partidos` | No |
| Rivales `/es/p/jr209629.html` | `h1` `Morillas`; tablas de estadísticas de jugadores, entrenadores y equipos | `Rivales` | No |

Esto confirma que las cuatro vistas tienen marcadores diferentes y que `Futbolista` no es un marcador global. **No** demuestra que una página de perfil válida pueda carecer de `Futbolista`: el perfil Morillas sí lo contiene y no hay una captura del perfil `j23751` para compararla.

## Navegación diagnóstica controlada

Se utilizó una vez la infraestructura existente `BrowserSessionManager` → Brave/Xvfb/CDP con el perfil persistente autorizado `~/.football-data-hub-v2-probe`, y `BDFutbolAccess` para abrir la URL exacta. No se cambiaron perfil, navegador, identidad o ruta de acceso; no se exportaron cookies ni credenciales.

| Campo | Observación |
|---|---|
| URL solicitada | `https://www.bdfutbol.com/es/j/j23751.html` |
| URL final | Igual a la solicitada |
| HTTP | `403` |
| Estado de acceso | `CHALLENGE_REQUIRED` |
| Título | `Just a moment...` |
| Marcadores | No evaluados después de detectar el desafío |
| HTML, hash y tablas | No inspeccionados ni conservados |
| Captura de pantalla | No generada; no era necesaria para confirmar el desafío |

La evidencia mínima se guardó separada de `data/raw` en `data/analysis/bdfutbol/player_profile_diagnostic/j23751_profile_diagnostic.json`. No es un snapshot deportivo y no contiene HTML, cookies, tokens ni credenciales. Al aparecer el desafío, no se hicieron más esperas, interacciones ni navegación.

## Clasificación de la causa

- **Intento original del Hito 1E-B1:** **E — evidencia insuficiente**. La metadata conservada permite confirmar HTTP 200, URL correcta y `INVALID_CONTENT`, pero no el documento que recibió el validador.
- **Única navegación de este hito:** **C — página alternativa/restricción de acceso**, confirmada por HTTP 403, título de desafío y `CHALLENGE_REQUIRED`.
- **A — página deportiva válida rechazada por regla estricta:** no demostrada.
- **B — página incompleta o renderizada prematuramente:** no demostrada. El flujo anterior observó hasta 12 s, pero no preservó estados del DOM ni HTML.
- **D — estructura desconocida:** no puede afirmarse; no se llegó a inspeccionar la página deportiva.

No se cambió el validador porque la evidencia no demuestra A ni B.

## Pruebas y cambios

Se añadieron únicamente pruebas offline:

- HTTP 200 con perfil sin el marcador obligatorio resulta `INVALID_CONTENT` y enumera el marcador ausente; no supone que tal página sea un perfil válido.
- Una respuesta `INVALID_CONTENT` HTTP 200 detiene el colector y no produce `rendered.html` ni directorio de snapshot.
- Una URL final con otro ID se rechaza antes de escribir un snapshot.

No se añadió una prueba de “perfil válido sin `Futbolista`”, porque no se ha observado esa estructura. La prueba existente de snapshots Morillas verifica compatibilidad con sus cuatro vistas; las pruebas de acceso existentes distinguen desafío de fallo semántico.

- `PYTHONPATH=src .venv/bin/python -m pytest -q`: **221 passed**.
- `.venv/bin/ruff check` sobre los dos archivos de tests modificados y los tres módulos relevantes: **All checks passed**.
- `git diff --check`: **sin errores**.
- La primera ejecución de pytest sin permisos elevados tuvo un único fallo ambiental: el sandbox denegó el socket local del test `test_loopback_port_valid`. Repetida con permiso para loopback local, la suite completa pasó; no se utilizó red externa para las pruebas.

## Archivos

- Modificados: `tests/test_bdfutbol_access.py`, `tests/test_bdfutbol_player_collector.py`.
- Creado: este informe.
- Evidencia diagnóstica local (ignorada por Git): `data/analysis/bdfutbol/player_profile_diagnostic/j23751_profile_diagnostic.json`.
- Sin cambios en colectores, parser, `BDFutbolAccess` ni snapshots históricos.

No se hizo commit ni push.
