# MATCH-03 — Publicación aprobada de detalles descubiertos en campaña

## Por qué la ficha no llegaba a la API pública

MATCH-02 publica únicamente capturas `VALID` verificadas por `MatchDetailStore`. El artefacto de `272525` pertenece a una campaña de descubrimiento: tiene acceso `VALID`, HTTP 200 y semántica deportiva válida, pero su ledger mantiene `capture_promotion_enabled=false`, `promotion_eligible=false` y `capture_promoted=false`. Su estado es `DISCOVERY_REVIEW_REQUIRED`, no una captura válida del almacén tradicional. Promoverlo mediante `store_valid_capture()` o relajar esa política sería incorrecto.

MATCH-03 conserva esa barrera y añade un contrato distinto: un paquete `campaign_discovery` solo puede entrar en el índice público después de volver a validar su evidencia y recibir una aprobación explícita, ligada al ID del partido, al hash del HTML y al hash del documento deportivo. Este proceso no promueve la captura ni modifica el ledger, el intento, el checkpoint o el artefacto. No es una aprobación criptográfica ni una sustitución del criterio del revisor: el recibo registra quién tomó la decisión y qué contenido exacto autorizó.

El checkpoint histórico de `272582` permanece detenido y su diagnóstico `INVALID_CONTENT` no se altera. La ruta nueva no busca ni publica candidatos de forma automática.

## Evidencia revisada para 272525

La integración offline utilizó el artefacto local:

`$FDH_LOCAL_DATA_ROOT/matches/details/campaigns/match-detail-sample-campaign-67fdc4b4fac66b82/candidates/pf-2026-27-group-ii-bdfutbol-272525/artifacts/discovery-20261018T112656Z-4543b211/`

El HTML tiene SHA-256 `9649b77712f8f259dd4cc413ebc90c26305069a7cb96ab8829fed3aff4b01113`. La validación releyó ledger, autorización, intento, manifiesto y hashes; confirmó Teruel 0–0 Real Madrid Castilla, J1, fecha 2026-08-31, IDs 204 y 61, 11 titulares por equipo, 7/10 suplentes, ambos entrenadores y 24 eventos. Entre ellos hay nueve entradas y nueve salidas, cuatro amarillas, una expulsión observada y un penalti fallado; se conserva sin atribuir una causa no demostrada para la expulsión, y no se fabrican parejas de sustitución.

En la ejecución MATCH-03 no se creó recibo de aprobación, no se escribió en `$FDH_LOCAL_DATA_ROOT/matches/details/published`, y el partido sigue sin publicar. `272582` tampoco se publicó.

## Flujo de operación

El CLI es `scripts/manage_bdfutbol_match_publication.py`. La ausencia de subcomando muestra ayuda y no escribe. Las acciones siguientes no realizan HTTP ni inician un navegador.

1. **Inspeccionar y validar**. `inspect` y `validate` son de solo lectura; `inspect` identifica además `read_only=true`:

   ```bash
   PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_publication.py \
     inspect \
     --internal-id pf-2026-27-group-ii-bdfutbol-272525 \
     --campaign-id match-detail-sample-campaign-67fdc4b4fac66b82 \
     --artifact-id discovery-20261018T112656Z-4543b211
   ```

2. **Preparar un borrador inmutable**, después de verificar identidad, alineaciones, eventos y el documento completo. El archivo se escribe una sola vez y no reemplaza uno existente:

   ```bash
   PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_publication.py \
     prepare \
     --internal-id pf-2026-27-group-ii-bdfutbol-272525 \
     --campaign-id match-detail-sample-campaign-67fdc4b4fac66b82 \
     --artifact-id discovery-20261018T112656Z-4543b211 \
     --output "$HOME/FootballDataHub-data/matches/details/review/272525-draft.json"
   ```

3. **Revisar la vista previa** con `preview --draft <ruta>`. Antes de aprobar, comparar el documento entero con la evidencia y verificar los dos hashes que imprime `inspect`/`prepare`. Ninguna de estas acciones cambia el estado de la campaña.

4. **Registrar aprobación humana específica**. Solo el operador que haya revisado el borrador debe ejecutar `approve`, con el nombre del revisor, el ID, ambos hashes y la cadena `approval_confirmation` que devuelve el borrador. El recibo también es inmutable. No se generó uno durante MATCH-03.

5. **Publicar**. `publish --draft <ruta> --approval <ruta>` vuelve a validar todos los datos fuente y la autorización antes de crear un paquete inmutable. Esta acción sí cambia el índice público y requiere decisión humana explícita; no se ejecutó en este hito.

6. **Verificar** con `verify --internal-id <id>`. El lector público valida otra vez el paquete y la evidencia de campaña.

Las rutas de MATCH-00, el almacén y los datos de jugadores se pueden configurar con los argumentos globales del CLI y las variables de entorno `FDH_LOCAL_DATA_ROOT`, `FDH_PLAYER_INVENTORY_ROOT`, `FDH_PLAYER_COMPACT_ROOT`, `FDH_PLAYER_TEAM_CAPTURES_ROOT` y `FDH_PLAYER_PUBLISHED_INDEX`. Para preparar/publicar, esas entradas deben corresponder a los mismos datos cargados por la API.

## Contrato e integridad

- Los paquetes tradicionales `football_data_hub.match_detail_publication.v1` siguen usando su contrato y validador originales.
- Los paquetes de campaña tienen contrato separado `football_data_hub.match_detail_campaign_publication.v1` y requieren recibo `football_data_hub.match_detail_campaign_approval.v1`.
- Se vuelve a ejecutar `parse_campaign_saved_artifact()` y se valida el ledger, la autorización, la identidad del intento, manifiestos, hashes, acceso `VALID`, HTTP 200, ausencia de desafío/denegación, y la no promoción.
- La semántica debe ser `semantic_valid=true`. La fecha, temporada, competición, grupo, jornada, equipos, marcador y generación deben coincidir con MATCH-00.
- La proyección usa `MatchPublishedDetailsResponse` y la misma validación contra el calendario que MATCH-02. Se verifican los IDs de jugadores presentes en el inventario.
- El recibo confirma explícitamente `internal_id`, `source_html_sha256`, `details_sha256` y un token derivado de esos valores. Publicar un borrador cambiado, una aprobación para otro contenido o un paquete cuyo origen ya cambió falla cerrado.
- `details.json`, `approval.json` y `manifest.json` se escriben una sola vez. El índice se cambia atómicamente bajo bloqueo; el índice previo se conserva en `indexes/<sha256>.json`. Se ejecuta una recarga del paquete antes de aceptar el nuevo índice y se restaura el índice previo ante fallo de validación.
- Repetir exactamente una publicación ya activa es idempotente. Un paquete inmutable existente pero distinto o inactivo no se sobrescribe.
- Si el proceso se interrumpe después de escribir el paquete y antes del índice, queda un paquete huérfano no publicado; no se descubre ni sirve automáticamente. Requiere revisión operativa.

## API y ficha React

La ruta pública existente `/api/v1/matches/{internal_id}` consume el mismo modelo publicado; no se añadió una excepción para Teruel–Castilla ni se modificó el frontend. Antes de que exista una publicación aprobada, el estado sigue siendo `not_available`. Después de una publicación válida, el lector devuelve `detail_status=available` y la ficha normal usa el endpoint público: entrenadores, titulares, suplentes, eventos y enlaces internos de jugadores disponibles. La vista previa local permanece como una funcionalidad distinta y rotulada.

FastAPI carga el índice al iniciar su lifespan. Después de una publicación manual hay que reiniciar FastAPI para cargar el nuevo índice; no hace falta una solicitud a BDFutbol. React no requiere reinicio y al abrir la ficha consulta la API como de costumbre.

## Verificación de MATCH-03

La integración optativa `tests/integration/test_match_campaign_publication.py`, habilitada con `FDH_MATCH_03_INTEGRATION=1` y `FDH_MATCH_03_DATA_ROOT`, usa el artefacto guardado, pero dirige borrador, aprobación de prueba, paquete e índice a `pytest` `tmp_path`. Comprueba rechazo sin aprobación, borrador alterado, ciclo de publicación, idempotencia y lectura HTTP del endpoint de producción envuelto en una app ASGI de prueba. El índice temporal devuelve el documento `available`; el almacén real no se toca. También verifica que `272525` y `272582` no se publican por ese ciclo real.

La aprobación generada dentro del test es un fixture técnico aislado y no representa una aprobación humana ni se conserva fuera del directorio temporal.

## Bloqueos y próximos pasos

No queda un bloqueo contractual para ofrecer esta vía: es un contrato independiente de publicación por aprobación, no una promoción de captura. `272525` **sigue sin publicar** hasta que una persona revise el documento y ejecute deliberadamente `approve` y `publish`. No hay publicación real ni aprobación automática en MATCH-03. Otros candidatos deben seguir el mismo proceso uno a uno; aprobar uno no autoriza a los demás.
