# MATCH-05A — Operaciones supervisadas de campañas de partidos

## Alcance y garantías

MATCH-05A añade colas y coordinación sobre las campañas v2 existentes de MATCH-04D. No introduce otro parser, ledger de candidatos, esquema de aprobación ni publicador. La validación usa `OperationalMatchCampaignLedger.validate_offline_artifact()` y el parser guardado oficial; los borradores se crean con `prepare_draft()`, la aprobación sigue siendo individual mediante `approve_draft()` y la publicación se delega al publicador y verificador existentes.

Las operaciones de consulta (`worklist`, `next`, `batch-preflight`, `review-queue`, `publish-queue`, `batch-report`) no navegan, no usan HTTP y no cambian campañas. `batch-offline` solo lee artefactos ya guardados y añade los eventos normales de validación/preparación. No convierte errores fallidos en reintentos: `VALIDATION_FAILED`, `REVALIDATION_FAILED`, `STOPPED` e `INTERRUPTED_REQUIRES_REVIEW` quedan para revisión individual. `publish-approved` solo considera documentos cuyo estado actual ya es `DOCUMENT_APPROVED`; no crea aprobaciones ni ejecuta `complete-review`.

Las propuestas nuevas siguen siendo planes MATCH-04C no autorizantes. La selección permanece determinista y excluye partidos publicados, ya reservados por campañas existentes, bloqueados, incompletos o sin URL verificada. `--persist` guarda el plan inmutable; `initialize` continúa siendo una operación separada y no autoriza navegación. Cada adquisición posterior sigue exigiendo una autorización humana individual y una sola navegación.

## Cola global y cobertura

`worklist` combina la generación seleccionada, propuestas, campañas v1/v2, snapshots, diagnósticos y publicaciones mediante los lectores existentes. Cada fila conserva `internal_id`, ID BDFutbol, grupo, jornada, equipos, marcador conocido, fechas de fuente/generación, URL, generación, campaña, estado operativo, próxima operación y causas de bloqueo. Los datos ausentes se conservan como `null`.

La salida incluye recuentos por estado, cobertura por grupo y jornada, y cobertura por campaña. Los estados de ledger se muestran literalmente (incluidos `REVALIDATION_FAILED`, `INTERRUPTED_REQUIRES_REVIEW` y `REVIEW_COMPLETED`); los partidos sin campaña se separan como `AVAILABLE_FOR_PROPOSAL`, `NOT_APPLICABLE` u otra situación derivada, no se presentan como campañas autorizadas. Los agregados distinguen partidos registrados/disputados/publicados/revisados, pendientes de adquisición/revisión y bloqueados.

Consultas típicas, solo lectura:

```bash
FDH_DATA="$HOME/FootballDataHub-data"
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" worklist

PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" worklist --group II --matchday-from 1 --matchday-to 7

PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" next --group I
```

`next` recomienda una única fila y operación permitida, pero no ejecuta esa operación. Si recomienda adquisición, el operador todavía debe revisar y usar `authorize` y `execute` individualmente.

## Preflight y lote offline

El preflight lee y verifica la cadena del ledger, los artefactos y los hashes. Informa por candidato si puede validar HTML guardado, preparar un borrador, si ya está preparado o si exige intervención humana. No escribe informes ni eventos.

```bash
FDH_DATA="$HOME/FootballDataHub-data"
CAMPAIGN_ID='<campaign_id_v2>'
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" batch-preflight --campaign-id "$CAMPAIGN_ID"
```

La ejecución offline exige la confirmación textual `PROCESS_SAVED_MATCH_ARTIFACTS_OFFLINE`:

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" batch-offline --campaign-id "$CAMPAIGN_ID" \
  --confirm-offline-batch PROCESS_SAVED_MATCH_ARTIFACTS_OFFLINE
```

Por cada `DISCOVERY_REVIEW_REQUIRED`, el coordinador valida el HTML guardado. Un resultado `VALIDATED` pasa a `prepare_draft`; un `VALIDATION_FAILED` queda registrado y el lote puede continuar con otros candidatos independientes. Los estados `VALIDATED` y `REVALIDATED` preparan el borrador; `DRAFT_PREPARED` no genera otro. Los estados fallidos, detenidos o interrumpidos no se revalidan ni se desbloquean automáticamente.

Un lock POSIX serializa dos operaciones por lotes. Las escrituras de ledger siguen utilizando sus locks existentes y vuelven a verificar los estados al anexar eventos. En particular, la validación vuelve a comprobar que el evento de descubrimiento no cambió mientras se ejecutaba el parser. Los informes de ejecución se guardan bajo `matches/details/operations/reports/<campaign_id>/`, con contrato versionado, SHA-256 del payload y escritura atómica/fsync. El informe se actualiza tras cada candidato; si el proceso se interrumpe, los eventos ya duraderos determinan la reanudación y la siguiente ejecución no repite validaciones ni borradores completos. Los nombres de informe incluyen una ejecución única y un informe preexistente de otra ejecución no se sobrescribe.

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" batch-report \
  --path "$FDH_DATA/matches/details/operations/reports/$CAMPAIGN_ID/<run_id>.json"
```

Un fallo semántico queda como `VALIDATION_FAILED` y el lote sigue. Una discrepancia de integridad de ledger, campaña o evidencia detiene el lote con `BLOCKED_INTEGRITY`; el coordinador no repara datos corruptos.

## Revisión humana

La cola de revisión solo contiene `DRAFT_PREPARED`. Cada elemento valida el SHA-256 del borrador frente al evento del ledger y muestra equipos, resultado de referencia y observado, fecha de partido y fecha/hora cuando existan, entrenadores, titulares, suplentes, eventos, avisos/comprobaciones de validación, campos ausentes, hashes y rutas al JSON, HTML, `metadata.json`, `discovery.json` y manifiesto.

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" review-queue --campaign-id "$CAMPAIGN_ID"

PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" preview --campaign-id "$CAMPAIGN_ID" \
  --internal-id '<internal_id>'
```

No existe aprobación por lote. Para aprobar, el revisor utiliza el comando individual `approve` con el `internal_id`, la persona aprobadora, el SHA del HTML, el SHA del documento y el token hash-específico devuelto por el flujo MATCH-04D. Superar la validación no equivale a aprobación.

## Cola de publicación

`publish-queue` es de solo lectura y lista únicamente `DOCUMENT_APPROVED`. La publicación en lote es una orden explícita, serial, confirmada y se limita a dichos documentos. Por cada uno invoca `publish()` y después `verify_publication()`; el verificador corregido comprueba el paquete real, manifiesto, índice, recibo y eventos. No crea aprobaciones, no publica borradores sin aprobación y nunca añade `REVIEW_COMPLETED`.

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" publish-queue --campaign-id "$CAMPAIGN_ID"

PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" publish-approved --campaign-id "$CAMPAIGN_ID" \
  --confirm-publish-approved PUBLISH_ONLY_INDIVIDUALLY_APPROVED_MATCH_DETAILS
```

El segundo comando escribe en el índice/paquetes locales publicados y debe tratarse como publicación operativa. No se ejecutó contra almacenes reales durante MATCH-05A. Para cerrar una revisión publicada se mantiene el comando individual `complete-review` con su confirmación explícita.

## Propuestas variables de candidatos

Se pueden solicitar tamaños de 10, 20, 30 o 50 y filtrar grupo/jornada. El límite también puede ser otro entero positivo para casos deliberados. La selección es estable por jornada, fecha, ID de origen y grupo; un límite reduce la lista después de contar los candidatos disponibles.

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" propose --groups I --matchday-from 1 --matchday-to 7 \
  --limit 20
```

Sin `--persist`, la salida es una propuesta no persistida. Con `--persist` se escribe un plan inmutable y no autorizante bajo `matches/details/campaign-proposals/`; ninguna propuesta persistida inicia una campaña o adquiere un partido. La inicialización sigue separada y, cuando se invoque, vuelve a comparar disponibilidad, campañas, publicaciones, capturas y bloqueos.

## Ejemplo reproducible con almacenamiento temporal

Las pruebas `test_offline_batch_uses_v2_parser_and_is_idempotent` y `test_offline_batch_handles_mixed_candidates_and_resumes_without_duplicate_effects` crean sus almacenes bajo `tmp_path`. La primera inicializa una campaña sintética, simula un artefacto guardado en almacenamiento temporal, sustituye el resultado del parser oficial por una respuesta semántica controlada de test, prepara el borrador y vuelve a correr el lote: el segundo recorrido no añade eventos. La prueba de 17 candidatos combina resultados válidos/fallidos (incluidos casos de HTML inválido, icono desconocido y TG2), estados de validación, borrador, autorización, bloqueo, interrupción, aprobación y publicación. Simula una interrupción después de persistir `VALIDATED`; al reanudar, solo prepara el borrador y no repite la validación. No usa BDFutbol ni un navegador.

Ejecutar esos ejemplos:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src:apps/api \
  .venv/bin/pytest -q -p no:rerunfailures \
  tests/test_match_detail_campaign_operations.py::test_offline_batch_handles_mixed_candidates_and_resumes_without_duplicate_effects \
  tests/test_match_detail_operational_campaign.py::test_offline_batch_uses_v2_parser_and_is_idempotent
```

Los tests semánticos existentes del parser cubren la interpretación real de iconos desconocidos y `TG2`; el coordinador no contiene reglas deportivas ni reemplaza esas comprobaciones.

## Consulta de los datos reales conocidos (solo lectura)

Estos comandos consultan el ledger de la campaña histórica indicada y muestran sus tres candidatos y los estados actuales sin modificar datos. No se ejecutaron comandos mutantes sobre ese almacén durante esta implementación.

```bash
FDH_DATA="$HOME/FootballDataHub-data"
CAMPAIGN_ID='match-detail-campaign-v2-06aa2259b14b95a7'
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" campaign-preflight --campaign-id "$CAMPAIGN_ID"

PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" candidates --campaign-id "$CAMPAIGN_ID"

PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" status --campaign-id "$CAMPAIGN_ID" --include-matches
```

IDs históricos que se solicitaron vigilar: `269408`, `269409`, `269410`, `272577`, `272524`, `269411` y el bloqueado `272582`. No debe inferirse su estado actual de esta lista: consúltese `worklist`/`candidates` antes de cualquier acción. El lote offline no procesa campañas v1; el ledger v1 se conserva con su lector y sus comandos individuales existentes.

## Compatibilidad, pruebas y límites

Se conserva el contenido de los ledgers v1/v2 y los contratos de publicación. Los tests adicionales verifican lote temporal, continuación tras interrupción, no duplicación, lock ocupado, fallo de integridad, preservación de informes ante un error de `rename`, hash de informe, revisión hash-checked, cola de publicación y requisito de confirmación. No se realizó adquisición, petición HTTP, inicio de Chromium, aprobación, publicación ni cierre sobre datos reales. Las propuestas, informes, decisiones humanas y paquetes posteriores quedan sujetos a las mismas verificaciones y límites por candidato; aún no se programa ninguna tarea periódica ni despliegue UJA.

## Dossier HTML local de revisión humana

`build_review_queue()` verifica el hash de cada borrador antes de producir una
ficha compacta. Para revisar varios sin abrir sus JSON completos se puede crear
un HTML estático, buscable y de solo lectura:

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/build_bdfutbol_match_review_html.py \
  --campaign-id <campaña-principal> \
  --include-campaign <campaña-adicional>
```

El dossier presenta resultado del catálogo y de la ficha, fecha, estadio,
árbitro, entrenadores, titulares, suplentes, eventos, advertencias y hashes de
procedencia. No incluye acciones de aprobación/publicación ni cambia el ledger.
Cada ejecución crea un HTML nuevo bajo `matches/details/review/human/` sin
reemplazar informes anteriores.
