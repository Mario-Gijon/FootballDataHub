# Seguimiento por jugador y jornada

## Alcance y fuente

La vista usa las capturas publicadas explícitamente en
`config/team_profiles_2026-27.json`. El índice identifica `capture_id`, ruta y
huellas SHA-256 de los JSON normalizados y snapshots necesarios. La API no
elige automáticamente una captura más reciente y no lee HTML ni hace
peticiones a BDFutbol durante las consultas.

Las capturas comparten la temporada 2026/27 y la competición Liga. Los partidos
se resuelven desde el bootstrap publicado para el grupo del equipo y se
referencian por `match_id`; no se copian a un dataset de fichas. La relación
con futbolistas usa `player_id`.

## Endpoint

`GET /api/v1/teams/{team_id}/seasons/2026-27/follow`

El contrato Pydantic `TeamFollowResponse` y el contrato Zod `TeamFollowSchema`
incluyen identidad/grupo/temporada, procedencia, jugadores, partidos y
jornadas, minutos, métricas positivas, cobertura por estado y advertencias.
El endpoint prepara y valida sus registros al iniciar FastAPI. Un error en una
captura de Seguimiento queda aislado de Plantilla y de los demás equipos. El
ETag incorpora versión de contrato, equipo, temporada y huella del contenido.

Estados de error diferenciados:

- `follow_not_captured`: equipo conocido sin perfil publicado.
- `follow_invalid`: el perfil seleccionado no supera hashes o cruces.
- `team_unknown`: ID que no pertenece a los dos catálogos.
- `season_not_available`: temporada fuera del alcance.

## Datos y significado

| Estado | Contenido normalizado | Disponibilidad actual |
|---|---|---|
| `p` · Partidos | `minutes_played`, conservando entero, `0` o `null`, más `source_value` | Jaén y Racing |
| `t` · Tarjetas | minutos de la celda y hechos positivos `yellow_cards` respaldados por `tg1` | Racing; Jaén pendiente |
| `go` · Goles | hechos positivos `goals` por jugador y `match_id`; se conservan valores mayores que uno | Racing; Jaén pendiente |
| `tot` · Todo | estado original combinado, comprobado como disponible, sin crear métricas duplicadas | Racing; Jaén pendiente |

Los valores de `player_statistics.json` no se usan para inventar eventos por
jornada. Los estados de métricas conservan los hechos positivos exportados en
`player_match_metrics.json`; la ausencia de un registro no se convierte en una
celda numérica cero. Las celdas sin minuto guardan el valor original vacío como
`null`; el cero publicado se conserva como `0`.

La agrupación Titulares/Suplentes de la vista Plantilla describe esa vista de
plantilla, no la participación en cada jornada. La captura no verifica una
categoría por jugador y partido (completo, titular, suplente o convocado sin
jugar), por lo que la matriz usa minutos neutrales y no muestra colores de
participación que aparenten esas categorías.

`tg2` y `tv` siguen sin interpretación positiva validada. No se normalizan
tarjetas rojas ni se derivan de estadísticas acumuladas. En Racing se
verificaron 10 amarillas `tg1` y 7 goles, coincidentes con la exploración
documentada en
[`bdfutbol_team_profiles_semantics.md`](bdfutbol_team_profiles_semantics.md).

## Cobertura de los pilotos

- Real Jaén, `team_id=49`, Grupo II: 25 jugadores, jornadas 1–6 y 150 celdas
  de minutos. Sólo está publicado `p`; Tarjetas, Goles y Todo se presentan como
  estados aún no capturados. Los ceros y nulos de la captura se mantienen.
- Racing de Ferrol, `team_id=48`, Grupo I: 25 jugadores, jornadas 1–6, 150
  celdas de minutos, 10 hechos amarillos y 7 goles; se capturaron `p`, `t`,
  `go` y `tot`.
- Los otros equipos aparecen en el catálogo de competición, pero no tienen
  captura de perfil publicada; el endpoint informa Seguimiento no adquirido.

La matriz crea una columna por jornada presente en registros verificados. No
completa las 38 jornadas ni crea combinaciones de jugador-partido que no estén
en los datos. En modo Todo, los minutos y eventos se combinan en una sola
celda; el recuento `tot` sólo acredita que la vista de origen fue capturada y
no genera filas de métricas duplicadas.

## Ejecución local

Desde la raíz del repositorio:

```bash
PYTHONPATH=src:apps/api .venv/bin/uvicorn football_data_hub_api.main:app --host 127.0.0.1 --port 8000
```

En desarrollo, Vite reenvía `/api` al puerto 8000. Para probar un API aislado,
se puede configurar `FDH_DEV_API_PROXY_TARGET=http://127.0.0.1:8001` al arrancar
Vite; el cliente del navegador sigue usando el mismo origen.

La ruta interactiva para cada perfil es `/teams/{team_id}/follow`. Los cambios
de modo se resuelven en React; cambiar de modo no realiza otra petición.

## Validaciones

El loader comprueba captura explícita, hash de cada documento, identidad,
temporada, grupo, Liga, validación guardada, estado de acceso y snapshot fuente.
También comprueba la relación de captura con el catálogo activo de partidos,
unicidad de jugadores/celdas/métricas, pertenencia de cada `match_id` al equipo,
consistencia de jornada y procedencia de `source_state`. Los snapshots de
estados adicionales se descomprimen y se comparan con las huellas incluidas en
los metadatos de la captura.
