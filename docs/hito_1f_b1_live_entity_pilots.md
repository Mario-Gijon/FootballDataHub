# Hito 1F-B1 — Reanudación live y pilotos de fichas individuales

**Fecha:** 9 de octubre de 2026  
**Rama:** `rebuild/football-data-hub-v2`  
**Resultado:** `STOP — error de sesión antes de navegar`

## Comprobación de acceso

El árbol de trabajo estaba limpio en la rama solicitada. Se revisaron el smoke test, `BrowserSessionManager`, `BrowserRuntimeConfig` y `BDFutbolAccess`. El smoke está configurado para abrir una sola ficha, `https://www.bdfutbol.com/es/j/j209629.html`, con Brave/Xvfb/CDP y comprobarla mediante `BDFutbolAccess`.

Antes de ejecutarlo se comprobó que `/usr/bin/brave`, `xvfb-run` y el perfil persistente `~/.football-data-hub-v2-probe` existen; el perfil tiene permisos `700`. No se encontró un proceso activo que utilizara esa ruta ni un lock de FootballDataHub adquirido. Había symlinks `Singleton*` cuyo PID de destino no estaba activo. No se borraron ni modificaron esos locks.

Se ejecutó una vez, desde la raíz del repositorio, el comando solicitado:

```bash
PYTHONPATH=src .venv/bin/python scripts/smoke_bdfutbol_session.py --browser brave --profile ~/.football-data-hub-v2-probe --no-stats
```

El proceso terminó con código `3` antes de iniciar Brave o conectar CDP. `BrowserRuntime` no pudo crear su lock de coordinación en `/home/mario/..football-data-hub-v2-probe.fdh.lock`: el entorno devolvió `OSError: [Errno 30] Read-only file system`. El resumen generado por el propio smoke está en `data/analysis/bdfutbol/session_smoke/20261009T184641.175032Z/summary.json`; informa `results: []` y el mismo error fatal.

**No se realizó ninguna navegación ni petición HTTP a BDFutbol.** Por tanto, el estado actual de acceso al sitio es **NOT TESTED**; no se observó un desafío ni una respuesta HTTP. No se elevó el comando ni se repitió, conforme a la regla de detenerse ante un error de sesión.

## Adquisición y procesamiento

La fase de acceso no terminó en `VALID`, así que no se implementó ni ejecutó el colector live y no se intentaron los pilotos de partido `272569`, entrenador `l1865`, árbitro `602675` o estadio `38`. No se modificaron código, snapshots raw ni exports. Los parsers y las capturas anteriores quedan intactos.

| Concepto | Estado |
|---|---|
| Sesión Brave/Xvfb/CDP | No iniciada: lock de runtime no escribible |
| Acceso BDFutbol | `NOT TESTED` |
| Capturas nuevas | 0 |
| Entidades intentadas | Ninguna |
| Parsing/export nuevo | No ejecutado |
| Tests/Ruff | No ejecutados: no hubo cambios de código |

## Siguiente paso

Para reanudar este hito, el entorno de ejecución autorizado debe permitir al runtime crear su lock en el directorio hermano del perfil y usar el perfil existente. Después se podrá volver a evaluar el acceso con el smoke prescrito; este informe no concluye si BDFutbol permite o bloquea actualmente la sesión.
