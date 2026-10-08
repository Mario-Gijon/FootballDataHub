# Hito 1E-B1-E — Corrección de validación semántica de perfiles

**Fecha:** 2026-10-08  
**Rama:** `rebuild/football-data-hub-v2`  
**Modo:** offline; sin navegador ni peticiones HTTP.

## Causa

La ficha de `j23751` se comprobó manualmente en Brave, según la evidencia aportada para este hito: `document.title` y `outerHTML` contienen `Futbolista`, mientras que `document.body.innerText` no. La regla anterior del colector pasaba `Futbolista` como marcador obligatorio y `BDFutbolAccess` solo lo buscaba en el texto del `body`. Por tanto, una ficha legítima con esa distribución del término puede ser rechazada como `INVALID_CONTENT`.

Esto demuestra un defecto en el contrato título/cuerpo. **No demuestra que ese fuera el contenido de la respuesta HTTP 200 original**, cuyo HTML no se conservó. La última evidencia live anterior a este hito fue el desafío Cloudflare HTTP 403 / `CHALLENGE_REQUIRED` registrado en el diagnóstico 1E-B1-D. No se comprobó de nuevo el acceso live.

## Cambio aplicado

`BDFutbolAccess` ahora permite declarar separadamente:

- marcadores obligatorios en el cuerpo;
- marcadores obligatorios en el título;
- selectores estructurales obligatorios en el DOM.

La evaluación sigue exigiendo todos los marcadores declarados. La ausencia de un marcador de título o selector estructural queda detallada en `AccessAssessment` como `missing_title_markers` o `missing_selectors`.

El colector de perfiles ahora exige:

| Área | Condición de perfil |
|---|---|
| Título | `Futbolista` |
| Cuerpo | `Nombre completo` y `Demarcación` |
| DOM | `h1` y `.traject` |
| Recurso | HTTPS de BDFutbol y URL final coincidente con la solicitada, incluido el ID de jugador y la vista |

Así, `Futbolista` en el título no basta por sí solo. Una página HTTP 200 de error sin los campos y estructura de perfil se rechaza. Los marcadores del cuerpo de estadísticas, partidos y rivales permanecen iguales; no se modificaron validadores de clubes ni competición. El rechazo conserva su estado y ahora registra los marcadores y selectores ausentes en el estado de adquisición.

Los desafíos continúan prevaleciendo sobre la validación semántica. Se mantienen la validación HTTPS/dominio, la comprobación de URL final y la distinción entre `CHALLENGE_REQUIRED`, `HTTP_ERROR`, `INVALID_URL` e `INVALID_CONTENT`. `VALID` requiere un estado HTTP presente dentro del rango 2xx; un estado desconocido se rechaza como `HTTP_ERROR`.

## Evidencia y pruebas

- La prueba sintética `test_synthetic_profile_accepts_futbolista_in_title_but_not_body` representa únicamente el contrato título/cuerpo solicitado; no afirma ser HTML capturado de `j23751` ni demuestra estructura nueva del sitio.
- Pruebas sintéticas separadas verifican que un título con `Futbolista` no acepte contenido de error HTTP 200 y que falte estructura cuando no aparece `.traject`.
- La prueba de HTTP 403 comprueba que el desafío sigue rechazándose antes de evaluar marcadores deportivos.
- La prueba de estado HTTP ausente confirma que una respuesta sin código no se considera válida.
- La prueba de URL final para `j100160` comprueba que una ruta de otro jugador se clasifica como `INVALID_URL`.
- `test_real_morillas_snapshots_pass_all_four_view_access_contracts` valida offline las cuatro capturas raw históricas de Morillas contra los contratos por vista. No se modificaron esas capturas.
- La prueba del colector `test_invalid_content_http_200_stops_without_writing_a_snapshot` confirma que contenido semánticamente rechazado no produce snapshot deportivo.
- La prueba `test_access_open_profile_checks_title_body_and_dom_structure` cubre la lectura independiente de título, cuerpo y selectores por `BDFutbolAccess` usando un doble sintético.

Las pruebas sintéticas solo ejercitan las condiciones de validación; no se usan como evidencia del HTML de BDFutbol. La compatibilidad observada con el sitio se comprueba con los snapshots locales válidos de Morillas.

## Validación

- `PYTHONPATH=src .venv/bin/python -m pytest -q`: **229 passed**.
- Ruff sobre los archivos Python modificados: **All checks passed**.
- `git diff --check`: **sin errores**.
- No se abrió Brave/Xvfb/CDP, no se hicieron peticiones, no se inició adquisición y no se modificaron snapshots o exports.

## Límites y estado del acceso

El validador ya permite la distribución título/cuerpo observada manualmente para `j23751`, pero la ficha real no se volvió a capturar ni a parsear. La presencia de `.traject` se contrasta con snapshots reales de Morillas; no se dispone de raw local de `j23751` para verificar su DOM contra ese selector.

**Validador:** corregido y cubierto offline.  
**Acceso live:** bloqueado en la última comprobación conocida (`CHALLENGE_REQUIRED`, HTTP 403); permanece **sin revalidar** en este hito offline. La corrección no sortea ni resuelve el desafío. No se recomienda reanudar capturas live hasta que el acceso autorizado esté disponible.

No se hizo commit ni push.
