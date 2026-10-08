# Hito 1E-B1 — Primer piloto live de perfiles de jugadores

## Resultado

**NO-GO: el lote se detuvo antes de guardar la primera página.** La primera navegación de `j23751/profile` llegó a la URL solicitada y recibió HTTP 200, pero `BDFutbolAccess` la clasificó `INVALID_CONTENT`: la página no contenía el marcador semántico requerido por el colector. Según el criterio del hito, no se continuó con ninguna otra vista ni jugador.

Esto no fue un `CHALLENGE_REQUIRED`, un HTTP 403 ni un fallo del parser. No hay evidencia en esta ejecución para afirmar que Cloudflare estuviera bloqueando: la respuesta fue HTTP 200, pero no superó la validación de contenido. Tampoco se puede determinar con los artefactos de esta ejecución si el marcador faltaba en una página incompleta o si la regla de validación resulta demasiado estricta. No se relajó ni se reintentó.

## Preparación y dry-run

- Rama comprobada: `rebuild/football-data-hub-v2`.
- El árbol estaba limpio antes de la ejecución; no había proceso de adquisición activo.
- Se leyeron los informes de Hitos 1E-B0, 1E-A2 y 1E-A.
- El parser instalado es `0.2.1`. El comando `live` admite IDs repetidos mediante `--player-id`, `--profile`, `--browser`, `--settle-ms`, `--refresh` y `--screenshot`. No se pasó `--refresh`.
- Se usaron `BrowserSessionManager`, Brave, Xvfb, CDP y el perfil persistente existente `/home/mario/.football-data-hub-v2-probe`. No se usaron navegadores, perfiles ni rutas de acceso alternativos.

Comando offline ejecutado:

```bash
PYTHONPATH=src:scripts .venv/bin/python scripts/scrape_bdfutbol_players.py dry-run
```

El plan de 15 pilotos se filtró localmente para los tres IDs del lote: **12 vistas previstas, 0 snapshots disponibles y 12 pendientes**. El dry-run reportó `browser_started=false` y `network_requested=false`.

| Jugador | Perfil | Estadísticas | Partidos | Rivales |
|---|---|---|---|---|
| `j23751` | `https://www.bdfutbol.com/es/j/j23751.html` — URL de roster verificada | `https://www.bdfutbol.com/es/j/j23751.html?p=stats` — inferida | `https://www.bdfutbol.com/es/p/j23751.html` — inferida | `https://www.bdfutbol.com/es/p/jr23751.html` — inferida |
| `j26481` | `https://www.bdfutbol.com/es/j/j26481.html` — URL de roster verificada | `https://www.bdfutbol.com/es/j/j26481.html?p=stats` — inferida | `https://www.bdfutbol.com/es/p/j26481.html` — inferida | `https://www.bdfutbol.com/es/p/jr26481.html` — inferida |
| `j100160` | `https://www.bdfutbol.com/es/j/j100160.html` — URL de roster verificada | `https://www.bdfutbol.com/es/j/j100160.html?p=stats` — inferida | `https://www.bdfutbol.com/es/p/j100160.html` — inferida | `https://www.bdfutbol.com/es/p/jr100160.html` — inferida |

## Prueba de acceso y persistencia

El único recurso solicitado live fue:

| Campo | Resultado |
|---|---|
| Jugador/vista | `j23751/profile` |
| URL solicitada y final | `https://www.bdfutbol.com/es/j/j23751.html` |
| Resultado HTTP | `200` |
| Estado de BDFutbolAccess | `INVALID_CONTENT` |
| Validación semántica | No apareció el marcador requerido `Futbolista` |
| Captura raw válida | No |
| Capturas posteriores | Ninguna |
| Tiempo del comando live | 17,2 s aproximadamente, incluido el inicio/cierre de sesión |

El colector solo llama a `capture_dom_snapshot` después de obtener `VALID`; por tanto, no guardó como snapshot la respuesta que falló la validación. El run parcial queda registrado en:

`data/raw/bdfutbol/20261008T193505.376432Z/acquisition_state.json`

El archivo registra `j23751/profile`, HTTP 200, URL final, `INVALID_CONTENT`, hora UTC `2026-10-08T19:35:22.431658+00:00` y el error genérico de marcadores ausentes. El directorio contiene solo ese estado (636 bytes); no hay `rendered.html`, inventario ni metadata de snapshot. Los snapshots y exports anteriores no se modificaron.

## Auditoría de datos y cobertura

No se ejecutó el parser sobre `j23751` porque no existe un snapshot válido. No se pueden informar tablas, filas, columnas, celdas, hashes, trayectoria, estadísticas, relaciones ni estructuras nuevas para este jugador. Tampoco se consultaron `tpartits`, las otras pestañas o filtros. No se declara ninguna página adquirida.

`j23751` pertenece a UD Logroñés y UD Ibiza en grupos distintos. No se consultó ninguna de esas fichas individuales y no se infirió que esas pertenencias sean un traspaso. Los casos previstos para `j26481` (Sant Andreu/Huesca y una pertenencia sin apariciones) y `j100160` (Real Unión) siguen sin comprobarse en sus páginas personales.

| Jugador | Snapshot válido | Estado de acceso | Parser | Completitud histórica |
|---|---:|---|---|---|
| `j23751` | 0 de 4 | `INVALID_CONTENT` en perfil; 3 vistas no solicitadas | No ejecutado | No evaluada |
| `j26481` | 0 de 4 | Pendiente; no solicitado | No ejecutado | No evaluada |
| `j100160` | 0 de 4 | Pendiente; no solicitado | No ejecutado | No evaluada |

Tras la parada se volvió a ejecutar el dry-run offline. El resultado para el lote sigue en **0 disponibles / 12 pendientes**. La vista fallida permanece pendiente de snapshot base válido; el registro de adquisición conserva el fallo real para auditoría. La cobertura del HTML, controles y filtros de estos jugadores no pudo investigarse.

## Tests y revisión

- Suite completa: **218 pasaron**.
- Ruff para `bdfutbol_player.py`, `scrape_bdfutbol_players.py` y `player_pages.py`: **All checks passed**.
- `git diff --check`: sin errores.
- Dry-run posterior: correcto y sin navegador ni red.
- No se añadieron pruebas: en este hito no se observó una estructura deportiva nueva y no se cambió código.

La prueba de loopback de la suite requiere permiso para reservar un socket local. Esa ejecución no realizó solicitudes a BDFutbol ni a Internet.

## Decisión

**NO-GO para continuar con `j26481`, `j100160` o los otros 12 pilotos.** La parada fue deliberada ante el primer estado distinto de `VALID`. Aunque la respuesta fue HTTP 200 y su URL final coincidió, el contenido no superó el contrato de validación. Continuar ahora produciría datos sin verificación suficiente. No se ha cambiado el marcador, no se ha reintentado y no se ha intentado eludir un control de acceso.

El hito queda detenido sin capturas deportivas nuevas. Reanudar requiere una nueva instrucción después de resolver de forma autorizada la discrepancia entre el contenido observado y el marcador semántico esperado. Una ejecución futura deberá empezar otra vez por una prueba controlada y detenerse si no obtiene `VALID`.
