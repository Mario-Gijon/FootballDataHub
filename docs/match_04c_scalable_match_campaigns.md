# MATCH-04C — Campañas escalables de detalles de partidos

## Alcance y límites

MATCH-04C añade inventario incremental, propuestas de tamaño variable y una vista unificada de progreso para Primera Federación 2026/27, Grupos I y II. Las operaciones nuevas son offline: no hacen HTTP, no inician navegador, no autorizan navegaciones, no publican documentos y no activan generaciones.

La campaña piloto MATCH-01C/MATCH-04A permanece inmutable en su esquema v1 y conserva los cinco candidatos originales. Las propuestas v2 se guardan, si el operador añade `--persist`, bajo `matches/details/campaign-proposals/`; no se colocan en el ledger operativo antiguo ni equivalen a autorización.

La generación usada en la auditoría local es `match-00-4ad1d610507e425d`, manifiesto SHA-256 `00166887b13413e3e6a5344fa1c64d52db8d38800f3ef9f282237584b3e65fbf`. Se validó mediante el cargador MATCH-00 existente. No hay un puntero de activación en este almacén y no se cambió la generación fijada por defecto. Si `matches/active-generation.json` existe, la CLI lo resuelve y valida; no elige el directorio más reciente.

## Arquitectura implementada

- `scalable_campaigns.py` construye registros para los 760 fixtures, incluidos los no disputados y cualquier encuentro disputado sin URL individual observada. Conserva generación, manifiesto, captura, snapshot y hash de `matches.json` por candidato.
- `classify_match_campaign_inventory()` combina la generación verificada con IDs de publicaciones cargadas por el lector público, estados revalidados del ledger, capturas verificadas por `MatchDetailStore`, borradores y recibos reconstruidos offline, y diagnósticos que exigen revisión.
- `build_match_campaign_proposal()` genera planes deterministas con cualquier número de candidatos, límites por grupo y jornada, exclusión de partidos publicados/gestionados/bloqueados y orden estable por jornada, fecha, ID fuente y grupo.
- Las propuestas tienen identidad derivada de la selección y de la generación. La escritura opcional usa un directorio temporal, `fsync` y renombrado atómico; los archivos instalados son inmutables e idempotentes. Al volver a leerse se validan manifiesto, hashes, contrato, IDs, URL y coherencia de la procedencia. La CLI vuelve a cargar la generación fuente de cada propuesta y comprueba sus candidatos contra ella.
- `scalable_campaign_cli.py` presenta progreso por estado, grupo y jornada. Valida las publicaciones mediante `load_published_match_details()`; no confía en nombres de archivos ni en la respuesta visual del dashboard.
- `--previous-generation-root` usa el diff de MATCH-04B para identificar `unplayed/incomplete → played`. Los candidatos nuevos siguen excluidos si carecen de URL verificada, están publicados, ya forman parte de una campaña o tienen un bloqueo.

Los estados primarios son `unplayed`, `played_without_verified_url`, `played_pending_acquisition`, `included_in_existing_campaign`, `authorized_not_executed`, `captured_pending_validation`, `validated_pending_approval`, `approved_pending_publication`, `published_approved`, `review_completed` y `blocked_requires_human_review`. `published_approved` y `review_completed` también se cuentan como hechos independientes: un registro publicado y con revisión completada aparece en ambos recuentos, aunque su estado primario es `review_completed`.

Una respuesta de descubrimiento sin parser semántico aprobado queda como captura pendiente de validación; un snapshot local `VALID` también requiere validación semántica. Una publicación aprobada no se considera que cierre automáticamente la revisión operativa: el estado `review_completed` solo procede del evento append-only de cierre existente.

## Auditoría de cobertura local

Se consultó la generación y el almacén externo sin modificar archivos:

| Estado | Total | Grupo I | Grupo II |
|---|---:|---:|---:|
| Fixtures en MATCH-00 | 760 | 380 | 380 |
| Disputados | 140 | 70 | 70 |
| Pendientes | 620 | 310 | 310 |
| Disputados sin URL individual explícita | 0 | 0 | 0 |
| Disputados pendientes de adquisición y no gestionados | 134 | 69 | 65 |
| Publicados y aprobados | 2 | 0 | 2 |
| Revisión completada | 2 | 0 | 2 |
| Incluidos en la campaña piloto sin autorización consumida | 3 | 1 | 2 |
| Bloqueados para revisión humana | 1 | 0 | 1 |

Los estados anteriores son categorías de ciclo de vida y se solapan intencionadamente en `published_approved`/`review_completed`. La campaña piloto contiene cinco IDs. `272525` y `272517` se verificaron con el lector de publicaciones completo y están publicados y revisados. Sus manifiestos publicados referenciados por el índice son `7d4982efc7f38e72de668d000486b9cdf3ac67554911172d63f84f5a20dffa58` y `c1b5010d0ff513359afde0030a451c32774019cd98a4e9cd20f8b313814de882`, respectivamente.

Los otros candidatos piloto permanecen `NOT_AUTHORIZED`, con cero navegaciones consumidas: `272577` (Grupo II), `272524` (Grupo II) y `269411` (Grupo I). El preflight histórico del ledger tiene cinco candidatos, dos `REVIEW_COMPLETED` y tres `NOT_AUTHORIZED`, sin bloqueos globales vigentes.

`272582` conserva intacto el diagnóstico histórico `IDENTITY_OR_CONTENT_UNVERIFIED` con `stop_acquisition=true`. Se clasifica como `blocked_requires_human_review`; su estado no se convierte en inexistente ni se reintenta. El checkpoint del almacén declara `active_stop=true`, pero no tiene corrupción (`integrity_blocked=false`); el diagnóstico se asocia al partido que lo originó y no paraliza los otros 134 candidatos. El contador de snapshots de captura válidos adicionales en el almacén MATCH-01B para ese inventario es cero; los dos partidos publicados se reconocen separadamente en el índice y sus paquetes.

## Uso offline

Desde el repositorio:

```bash
export DATA_ROOT="$HOME/FootballDataHub-data"
export PYTHONPATH=src:apps/api

# Estado de la generación activa verificada; si aún no hay puntero, usa G1 fijada.
.venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py status

# Mostrar el detalle de los 760 fixtures.
.venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py status --include-matches

# Propuesta ilustrativa de 10 IDs entre ambos grupos; imprime el plan y no escribe.
.venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py propose \
  --groups both --limit 10

# Ejemplo de propuesta de tres candidatos para revisar posteriormente; no navega.
.venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py propose \
  --groups both --limit 3

# Guardar una propuesta versionada, inmutable y no autorizante, si se necesita conservarla.
.venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py propose \
  --groups both --limit 3 --persist
```

El `propose` de ambos grupos con `--limit 10` se ejecutó como dry output (sin `--persist`): ofreció 10 candidatos ordenados desde la jornada 1, nueve del Grupo I y uno del Grupo II (`269408`–`269417` salvo `269411`, y `272516`), con 134 candidatos disponibles antes del límite. El informe incluye la cobertura total por estado/grupo antes de filtrar. No se crearon propuestas ni campañas externas.

Después de activar una generación con MATCH-04B, el operador debe apuntar el estado a la raíz de almacén que contiene `active-generation.json`; nunca se escoge el subdirectorio más reciente:

```bash
.venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --generation-root "$DATA_ROOT/matches" status

# Compara explícitamente una generación anterior con la activa y muestra nuevos disputados.
.venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --generation-root "$DATA_ROOT/matches" \
  --previous-generation-root "$DATA_ROOT/matches/generations/ID_ANTERIOR" status

# Solo candidatos que pasaron a disputados entre ambas capturas.
.venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --generation-root "$DATA_ROOT/matches" \
  --previous-generation-root "$DATA_ROOT/matches/generations/ID_ANTERIOR" \
  propose --newly-played-only --groups both --limit 3
```

El último comando exige que la generación anterior esté presente y verificada. El informe incremental enumera el cambio, si faltan detalles, el estado actual y la próxima operación segura. Los partidos `played` antiguos sin publicación también siguen visibles en `status`; nunca se vuelven a descargar solo por cambiar el ID de generación.

## Revisión, validación y publicación

La generación de propuestas no constituye autorización. Cada candidato futuro requiere revisión de la URL fuente observada y una autorización individual ligada al ID interno, generación, hashes y URL. El adaptador actual sigue siendo de una navegación por autorización y sin reintentos automáticos. MATCH-04C no añade autorización masiva ni habilita el ejecutor para planes v2.

Los pasos técnicos offline que la CLI agrupa en `status` son revalidar generación e inventario, reconstruir estados del ledger, rehash/reconciliar snapshots, reconstruir borradores y recibos locales y volver a validar todas las publicaciones con el lector público. Esos cálculos no aprueban documentos. Si existe un borrador semánticamente válido, la futura aprobación sigue siendo una decisión humana explícita, ligada a los hashes exactos. `publish` requiere el recibo explícito existente; `complete-review` sigue siendo una decisión del operador y conserva eventos anteriores.

La futura ejecución multi-partido deberá añadir un executor v2 separado, con reserva duradera individual antes de cada navegación, lock exclusivo, avance recuperable, una autorización individual por candidato, límites de ritmo aprobados, y parada inmediata ante 403/429, desafío, error HTTP no verificable o estructura inesperada. Tras cada navegación, captura, parser semántico, comparación de resultado/equipos y preparación de borradores deben continuar siendo pasos offline. No hay bucle de scraping en este hito.

## Actualizaciones y generaciones

El orden operativo recomendado después de una actualización es:

1. Construir una generación MATCH-00 nueva en un directorio separado.
2. Compararla con la generación anterior y revisar los cambios, las correcciones y partidos que pasan a `played`.
3. Activar explícitamente la nueva generación según MATCH-04B. MATCH-04C no activa nada.
4. Consultar `status` contra el puntero activo y revisar `incremental_update`.
5. Preparar una propuesta nueva basada en el manifiesto exacto y escoger candidatos disputados que tengan URL explícita.
6. Mantener publicaciones históricas asociadas a su fuente; la carga pública vuelve a comprobar identidad y resultado contra la generación activa.
7. Autorizar cada acceso remoto y revisar cada documento por separado; aprobar/publicar solamente después de revalidar HTML y hashes.

Un plan v2 conserva la captura original de grupo, generación, manifiesto, `matches.json` y URL individual. Una generación posterior no altera el plan antiguo. Los candidatos identificados por `internal_id` se excluyen si ya constan en publicaciones o en campañas gestionadas, aunque la generación activa avance.

## Intervención humana que sigue siendo necesaria

- Confirmar las condiciones de acceso y alcance antes de cualquier acceso automatizado real.
- Revisar y autorizar cada ID/URL de navegación. Una propuesta de diez candidatos no autoriza diez solicitudes.
- Revisar un desafío, denegación, timeout sin HTTP, interrupción, conflicto de identidad o manifiesto inválido; no reintentar automáticamente.
- Aprobar cada documento deportivo ligado al partido y sus hashes.
- Decidir la publicación final y el cierre explícito de revisión.
- Revisar el diff y activar manualmente cada generación de calendario.

Los overlays o elementos de HTML que el parser aún no reconozca requieren revisión semántica, no valores inferidos. Los horarios permanecen `null` cuando la fuente no los acredita y no se les asigna zona horaria.

## Servidor UJA y límites

No se usó ni configuró el servidor UJA. Para una futura instalación, montar el almacén externo con permisos y respaldo, instalar la versión del proyecto, verificar el manifiesto activo y los paquetes de publicación offline y ejecutar primero `status`. Los requisitos de Chromium, perfiles y disponibilidad del proveedor deben comprobarse aparte; esta CLI de status/propuesta no necesita navegador. No configurar tareas programadas hasta validar un lote pequeño autorizado y su recuperación.

MATCH-04C no implementa una campaña operativa v2 con autorizaciones ni adquisición real. Tampoco cambia la API, React, el índice de publicación, generaciones activas o capturas existentes.
