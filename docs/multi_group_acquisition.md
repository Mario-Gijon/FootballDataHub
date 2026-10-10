# MULTI-01 — Adquisición reutilizable de Primera Federación

## Alcance y auditoría

MULTI-01 generaliza la adquisición de las cinco secciones existentes para Primera Federación 2026/27, grupos I y II. FastAPI y React siguen usando los contratos y datasets del Grupo II; su selección por grupo queda para MULTI-02.

| Área | Acoplamiento encontrado | Resultado |
|---|---|---|
| Clasificación | URL, grupo, export y marcadores de validación fijados al Grupo II en adquisición/CLI/export. | El contexto central deriva URL, código BDFutbol, etiqueta y export por grupo. Se conserva la validación estructural de 20 equipos/38 jornadas. |
| Resultados | Se extraen desde el HTML de Clasificación y se normalizan con el catálogo de esa misma captura. | El extractor y motor son únicos; `matches.json` hereda grupo, temporada, capture ID y hash de la fuente. No se suma un segundo scraper de marcadores. |
| Destacados | URL, título, catálogo de equipos y export fijados al Grupo II; los conteos eran específicos de aquella captura. | Una adquisición parametrizada exige el catálogo del mismo grupo. Se conservan conteos reales y variaciones fuente sin completar registros ausentes. |
| Estadísticas | URL, título, grupo y ruta predeterminada de resultados fijados al Grupo II. | El parser recibe contexto y las estadísticas se reconcilian solo con el dataset del mismo grupo. Se corrigió el formato de la envoltura del objeto AmCharts capturado. |
| Árbitros | La captura ya contenía `all`, `group1` y `group2`, aunque el informe de cruce original priorizaba Grupo II. | Se reutiliza la captura REF-01 y el cruce se filtra por ámbito e ID exacto de árbitro. No se vuelven a adquirir árbitros. |
| Navegador | Pure CDP, Chromium, perfil y Xvfb ya eran genéricos. | Se mantienen sin cambios arquitectónicos. El orquestador ejecuta cada navegación secuencialmente y usa un único perfil configurado. |
| API y React | Endpoints, loaders y contratos siguen seleccionando Grupo II. | Fuera de este hito; MULTI-02 deberá separar los bootstraps por grupo y validar sus procedencias. |

Las cifras de Grupo II (59 resultados disputados en la captura anterior, 217 jugadores, 101 extranjeros, 822 puntos de progreso, 42 árbitros y diferencias particulares de estadísticas) no se usan como expectativas de Grupo I. Los 20 equipos, 38 jornadas y 10 fixtures por jornada se mantienen como estructura de esta competición y se validan con la captura real.

## Contexto compartido

`src/football_data_hub/providers/bdfutbol/context.py` contiene `CompetitionContext` y `get_competition_context()`. Solo habilita la temporada `2026-27` y los grupos `1` y `2`; deriva `1rf1`/`1rf2`, URL base, etiqueta, clave de grupo, URLs de sección y raíz de export. Las rutas se construyen debajo de la raíz configurable, no de una ruta fija del usuario.

Los parsers conservan alias de compatibilidad del Grupo II para consumidores previos, pero los CLIs y el orquestador entregan explícitamente el contexto. El parser de Destacados requiere el catálogo de equipos del mismo grupo; Estadísticas requiere su `matches.json` correspondiente.

## Adquisición real y validación

Se verificó el flujo completo con Pure CDP, Chromium `/usr/bin/chromium`, el perfil persistente `/home/mario/.football-data-hub-chromium-pure-cdp` y Xvfb externo. Las tres páginas visitadas devolvieron HTTP 200, conservaron su URL exacta y el título identificó Grupo I 2026-27. Resultados se normalizó desde el HTML de Clasificación, sin otra navegación. El run completo quedó registrado en:

`data/analysis/bdfutbol/acquisition_runs/20261010T202500.201160Z-c7065ec5/manifest.json`

El manifiesto declara `status=complete`, `published_to_api=false`, y todas las visitas se ejecutaron en serie. La clasificación devolvió HTTP 200, URL final exacta `https://www.bdfutbol.com/es/t/t2026-271rf1.html`, título `Clasificación 1ª RFEF Grupo I 2026-27 | BDFutbol`, 20 equipos y 6 jornadas disputadas.

| Sección | Captura utilizada | Datos verificados |
|---|---|---|
| Clasificación | `https://www.bdfutbol.com/es/t/t2026-271rf1.html`; captura `20261010T202500.293648Z-b770724f` | 20 filas; 120 puntos de progreso (20 equipos × J1–J6); validación 8/8 sin fallos. |
| Resultados | Derivados de la captura de Clasificación anterior | 380 fixtures; 60 disputados, 320 programados, 0 incompletos y 0 identificados como aplazados. Validación: 20 equipos, 38 jornadas, 10 fixtures/jornada, IDs y equipos conocidos, marcadores completos y goles equilibrados (156 GF/156 GC). |
| Destacados | `https://www.bdfutbol.com/es/t/t2026-271rf1.html?tab=top`; captura `20261010T202506.237287Z-c92b19fb` | 6 categorías; 149 rankings (99 goles, 10 por cada otra categoría); 180 jugadores únicos; 129 series y 774 puntos; 59 filas de extranjeros y 36 opciones de país. Validación estructural correcta con dos advertencias fuente documentadas abajo. |
| Estadísticas | `https://www.bdfutbol.com/es/t/t2026-271rf1.html?tab=stats`; captura `20261010T202515.613199Z-6c6e0fd9` | Resumen de 60 partidos, 156 goles, 29 victorias locales, 16 visitantes, 15 empates, 273 amarillas y 20 expulsiones; 16 penaltis pitados, todos marcados; 38 puntos de gráfico. Los 380 registros de su tabla oculta coinciden por ID/campos con Resultados. Reconciliación: 0 métricas con diferencia. |
| Árbitros | REF-01 `20261010T171227.617128Z-4cfe71bc` | Captura compartida `all`/Grupo I/Grupo II reutilizada y validada por hashes. 43 árbitros de Grupo I; los 60 partidos disputados tienen `referee_id`; 43/43 IDs relacionados; 0 conflictos de identidad y 0 diferencias de estadísticas/tarjetas. |

El manifiesto del primer run exploratorio, `20261010T200928.825731Z-2f51581e`, conserva las fallas iniciales de parsing de Destacados y Estadísticas. No se reescribió: después de investigar esas diferencias, se corrigieron los supuestos y se completó el segundo run, que es la evidencia de aceptación del flujo final.

### Diferencias reales en Destacados

La página del Grupo I publica `Extranjeros 60`, mientras `table#tab_estran` contiene 59 filas de datos. Se conservan 59 registros y el `source_count=60`; no se genera una fila para el faltante. La diferencia queda como advertencia, no como error semántico del parser.

Además, el jugador BDFutbol `304291` aparece con equipo 58 (`Pontevedra`) en `DESTACATS_JS.LG` y equipo 104 (`Deportivo Fabril`) en `#tab_estran`. No se resuelve por nombre ni se elige uno: el catálogo normalizado deja los campos de equipo en `null` para ese jugador y `metadata/capture.json` preserva ambos IDs y sus fuentes en `affiliation_conflicts`. Los registros originales permanecen en el snapshot HTML.

Estas dos situaciones son propiedades observadas de esta captura del Grupo I, no reglas generales de la competición. MULTI-02 deberá decidir cómo presentar afiliaciones ambiguas y recuentos publicados diferentes de las filas visibles, sin ocultar las advertencias.

## Exports y procedencia

Cada ejecución crea un `capture_id` nuevo. Las capturas del Grupo II no se movieron ni sobrescribieron. El run aceptado de Grupo I quedó en:

- `data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f/` — snapshot, clasificación, progreso, partidos y validaciones.
- `data/exports/bdfutbol/group1_top/20261010T202506.237287Z-c92b19fb/` — snapshot, catálogo, rankings, progreso, extranjeros y validación.
- `data/exports/bdfutbol/group1_statistics/20261010T202515.613199Z-6c6e0fd9/` — snapshot, datos originales del gráfico, estadísticas publicadas/derivadas y reconciliación.
- La comparación de árbitros está en `group1_classification/.../validation/referee_reference.json` y referencia el hash de `matches.json` y la captura REF-01 compartida.

## Ejecución

Desde la raíz del repositorio, con el perfil autorizado disponible y Chromium/Xvfb instalado:

```bash
PYTHONPATH=src:scripts .venv/bin/python scripts/acquire_bdfutbol_competition.py \
  --season 2026-27 --group 1 \
  --profile "$HOME/.football-data-hub-chromium-pure-cdp" \
  --browser-executable /usr/bin/chromium
```

Para Grupo II o ambos grupos en serie, cambiar `--group 1` por `--group 2` o `--group both`. El grupo I y el II comparten el mismo perfil solo de forma secuencial; cada uno obtiene su propio catálogo, capturas y carpeta de salida. Los directorios de raíz, perfil, ejecutable y captura compartida de árbitros admiten argumentos o configuración por entorno. Un desafío o denegación se registra y cierra esa adquisición; no se reintenta para superar el bloqueo.

Las normalizaciones offline se pueden repetir desde los `raw/source.html` guardados. Destacados necesita `--team-catalog` del mismo grupo y Estadísticas necesita `--matches` del mismo grupo. La suite de pruebas no abre navegador ni solicita red.

## Verificación y límites

En MULTI-01 se han adquirido y normalizado las cinco áreas para Grupo I; el manifiesto de ejecución completo lo confirma. Las pruebas de regresión del Grupo II se mantienen. No se ejecuta una adquisición periódica ni se publica nada en FastAPI.

Solo se ha habilitado la temporada 2026/27. El Grupo I refleja la captura del 10/10/2026, con seis jornadas disputadas. El filtro de aplazados no se ha observado en un partido aplazado de este grupo. Destacados conserva un faltante visible frente al encabezado y una afiliación ambigua con procedencia explícita. Estadísticas valida campos agregados; la equivalencia conceptual de “Expulsiones” con tarjetas rojas sigue siendo la limitación documentada del módulo compartido.

## MULTI-02

FastAPI y React aún cargan contratos y bootstraps del Grupo II. MULTI-02 deberá:

1. Elegir un bootstrap/versionado de Grupo I o Grupo II y rechazar mezclas por `group`, temporada y hashes relacionados.
2. Añadir carga de los datasets TOP y Estadísticas del Grupo I sin copiar los del Grupo II.
3. Mantener Árbitros como catálogo común de temporada con estadísticas filtradas por `group_scope`.
4. Exponer las advertencias de afiliación ambigua y de conteo de extranjeros sin inventar registros.
