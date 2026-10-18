# MATCH-04D — campañas operativas escalables de partidos

## Alcance

MATCH-04C produce planes inmutables y no autorizantes. MATCH-04D añade una campaña v2 que consume uno de esos planes y gestiona el ciclo operativo por candidato. El ledger v2 es append-only, comparte el lock exclusivo de campañas existente y conserva por separado plan, generación, inventario, intentos, artefactos, validaciones, revisión, aprobación y publicación.

Este cambio implementa el ejecutor real mediante el adaptador existente Brave/Pure CDP y `BrowserSessionManager`, pero no lo ejecuta. No se visitó BDFutbol, no se inició Chromium y no se escribieron datos reales durante MATCH-04D. Las pruebas de ciclo completo usan almacenes temporales y un adaptador simulado.

## Procedencia y esquemas

La propuesta persistida conserva su plan y manifiesto MATCH-04C. `initialize` vuelve a verificar los SHA, reabre la generación nombrada en el plan, compara cada candidato con el inventario reproducido y conserva el inventario oficial de detalles. La campaña se instala en un directorio atómico e idempotente; no crea autorizaciones.

La campaña usa `football_data_hub.match_detail_operational_campaign.v2`; su manifiesto vincula el hash de campaña, propuesta, plan, inventario y generación. Cada candidato tiene una cadena de eventos JSON canónicos con secuencia, hash del evento anterior y hash del payload. El lock exclusivo se mantiene durante autorización, reserva `STARTED`, una sola navegación, escritura del artefacto y resolución. Si el proceso cae después de `STARTED`, el estado resultante es `INTERRUPTED_REQUIRES_REVIEW`: no existe reintento ni desbloqueo automático.

Estados de adquisición/revisión más usados:

| Estado | Significado | Acción segura siguiente |
| --- | --- | --- |
| `NOT_AUTHORIZED` | Candidato incluido en campaña, sin permiso | Revisión humana individual |
| `AUTHORIZED` | Permiso explícito, aún no consumido | Ejecutar esa autorización una vez |
| `STARTED` | Reserva duradera previa a la navegación | Al releer se muestra `INTERRUPTED_REQUIRES_REVIEW` |
| `DISCOVERY_REVIEW_REQUIRED` | HTML íntegro guardado, aún no validado/promovido | Validar offline |
| `VALIDATED` | Parser semántico existente aceptó el encuentro | Preparar borrador |
| `DRAFT_PREPARED` | Borrador derivado, íntegro y pendiente de revisión humana | Revisar preview y aprobar hashes exactos |
| `DOCUMENT_APPROVED` | Recibo humano ligado al partido, HTML y documento | Publicar el borrador aprobado |
| `PUBLISHED` | Paquete/index publicados y legibles | Verificar publicación y completar revisión |
| `REVIEW_COMPLETED` | Cierre humano explícito, append-only | Sin operación adicional |
| `STOPPED` / `VALIDATION_FAILED` | Fallo de acceso, estructura o validación | Revisión manual; no reintentar |

La evidencia del navegador nunca promociona una captura al almacén normalizado. El paquete público solo se escribe tras la aprobación específica y vuelve a validarse con el publicador actual. La lectura de campaña rehashea el artefacto HTML, metadata, borrador y recibo; las referencias a generación e inventario conservan su origen aunque cambie la generación activa. Una contradicción de partido entre generaciones se bloquea para revisión.

## CLI

El punto de entrada sigue siendo:

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py --help
```

Las opciones comunes `--data-root`, `--generation-root`, `--store-root` y `--published-root` se ponen antes del subcomando. `status`, `campaign-preflight`, `candidates`, `inspect` y `preview` consultan datos; no autorizan, navegan ni publican. `status` puede filtrar con `--group`, `--matchday-from`, `--matchday-to`, `--campaign-id` y `--state`; use `--include-matches` para imprimir las filas filtradas.

### Preparar una propuesta de tres candidatos, ambos grupos

Ejemplo de forma; los IDs y recuentos se determinan en la ejecución local y no se fijan aquí:

```bash
FDH_DATA="$HOME/FootballDataHub-data"
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" \
  propose --groups both --limit 3 --persist
```

Copie `proposal_id` de la respuesta. La propuesta es una selección inmutable y no autoriza navegación. Inicializarla reserva sus candidatos para que futuras propuestas los excluyan:

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" initialize --proposal-id '<proposal_id>'
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" campaign-preflight --campaign-id '<campaign_id>'
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" candidates --campaign-id '<campaign_id>' --group II --state NOT_AUTHORIZED
```

### Autorizar y ejecutar un candidato real

Estas órdenes son ejemplos para uso futuro; **no se ejecutaron en MATCH-04D**. Antes de autorizar, revise el ID, grupo, jornada, URL, resultado de referencia y generación en `candidates`/`status`, así como el preflight. `--operator` identifica a la persona y la cadena obliga a una confirmación humana individual.

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" \
  authorize --campaign-id '<campaign_id>' --internal-id '<internal_id>' \
  --confirm-url 'https://www.bdfutbol.com/es/p/p.php?id=<source_match_id>' \
  --operator '<operador>' --confirm-authorization AUTHORIZE_ONE_MATCH_DISCOVERY_V2
```

La salida devuelve `authorization_id`. Solo después de esa autorización, y una vez confirmado que el navegador de adquisición de jugadores está inactivo, se puede ejecutar una única navegación:

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" \
  execute --campaign-id '<campaign_id>' --internal-id '<internal_id>' \
  --authorization-id '<authorization_id>' \
  --confirm-url 'https://www.bdfutbol.com/es/p/p.php?id=<source_match_id>' \
  --confirm-execution EXECUTE_ONE_MATCH_DISCOVERY_V2 \
  --player-browser-idle-confirmation PLAYER_BROWSER_IDLE_CONFIRMED
```

El comando conserva perfil temporal dedicado bajo `data-root/browser-profiles`, usa SeleniumBase Pure CDP con el `BrowserSessionManager` actual, no reintenta y se detiene ante error HTTP, desafío, denegación, URL inesperada o contenido inválido. Si queda `STARTED` sin resolución, no vuelva a ejecutar; conserve el artefacto/ledger para revisión manual.

### Validación, aprobación y publicación

Tras `DISCOVERY_REVIEW_REQUIRED`, el resto se procesa offline salvo la publicación local del paquete:

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" validate --campaign-id '<campaign_id>' --internal-id '<internal_id>'
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" prepare --campaign-id '<campaign_id>' --internal-id '<internal_id>'
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" preview --campaign-id '<campaign_id>' --internal-id '<internal_id>'
```

La persona revisora debe cotejar el documento deportivo. A continuación copie del borrador `source_html_sha256` y `details_sha256`; obtenga la confirmación con `APPROVE-<source_match_id>-<primeros 12 caracteres de source_html_sha256>-<primeros 12 caracteres de details_sha256>` y registre su identidad:

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" approve --campaign-id '<campaign_id>' --internal-id '<internal_id>' \
  --draft-path "$FDH_DATA/matches/details/review/v2/<campaign_id>/<source_match_id>-draft.json" \
  --approved-by '<revisor>' --confirm-internal-id '<internal_id>' \
  --confirm-source-html-sha256 '<sha256 HTML>' --confirm-details-sha256 '<sha256 documento>' \
  --confirm-action '<APPROVE-source_match_id-html12-details12>'
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" publish --campaign-id '<campaign_id>' --internal-id '<internal_id>'
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" verify --campaign-id '<campaign_id>' --internal-id '<internal_id>'
```

Para cerrar, calcule `COMPLETE-REVIEW-<source_match_id>-<primeros 12 caracteres de source_html_sha256>-<primeros 12 caracteres de details_sha256>` y ejecute `complete-review --campaign-id ... --internal-id ... --reviewer '<revisor>' --confirm-review '<token>'`. La operación verifica otra vez el paquete activo y añade un evento; no elimina ni reescribe `DISCOVERY_REVIEW_REQUIRED`.

## Campañas grandes e inventario

No hay límite de cinco candidatos en el esquema v2. El límite opcional de la propuesta se aplica antes de persistirla; cada permiso y cada navegación siguen siendo individuales. Iniciar una campaña reserva todos sus IDs aunque ninguno esté autorizado, por lo que no reaparecen en propuestas futuras. El inventario global integra ledgers v1 y v2, diagnósticos del almacén, capturas válidas, publicaciones y artefactos de revisión. Los estados v2 incluyen número de navegaciones, permiso consumido y estado operativo.

Los comandos de consulta aceptan filtros por grupo, jornada, campaña y estado. `status` agrega la cobertura global; sus totales siguen describiendo el inventario completo, mientras `filtered_count` refleja filtros aplicados y `--include-matches` muestra las filas correspondientes.

Si la generación activa avanza, la campaña mantiene su `generation_id`, hash del manifiesto e inventario. Las propuestas nuevas parten de la generación seleccionada actualmente. Un mismo ID interno con marcador/equipos/URL contradictorios no se reasigna silenciosamente: el estado global lo bloquea para revisión. El cambio de generación no provoca una nueva captura automática de partidos ya gestionados o publicados.

## Estado histórico e integración UJA

La campaña piloto v1 sigue siendo legible por su verificador y nunca se migra ni reescribe. `272525` y `272517` continúan siendo publicaciones existentes; los candidatos de piloto sin autorizar y el bloqueo histórico de `272582` se conservan. Las pruebas locales de regresión de esta entrega consultan esos estados sin escribir en ese almacén.

### Recuperación de una validación semántica fallida

`VALIDATION_FAILED` queda bloqueado para adquisición, pero puede revisarse offline mediante `revalidate-failed` cuando una corrección del parser justifique volver a evaluar el mismo HTML. El comando exige operador y `REVALIDATE_FAILED_ARTIFACT_V2`; rehasha artefacto/manifiesto, vuelve a comprobar el partido contra la generación histórica y añade `REVALIDATED` o `REVALIDATION_FAILED` al final del ledger. El evento original `VALIDATION_FAILED`, sus hashes y el artefacto no se sustituyen. Solo `REVALIDATED` permite preparar borrador; aprobación y publicación siguen requiriendo sus pasos humanos. `STOPPED` e `INTERRUPTED_REQUIRES_REVIEW` no admiten esta operación.

El parser semántico `match-detail-semantic-0.3.1` reconoce únicamente el par observado `class="TG2"` y `title="Doble Tarjeta Amarilla"` como `second_yellow`. Se conserva como expulsión por segunda amarilla, separada de `yellow_card` y de `red_card`; ante una segunda amarilla no se declara ausente una expulsión ni se inventa una roja directa. El adaptador de vista previa de FastAPI proyecta el tipo `second_yellow`, ya admitido por el contrato de respuesta. La versión del parser se toma de `observation.source.parser_version` (no de `SemanticValidation`, que no contiene ese campo), y se guarda también dentro de la evidencia de cada validación nueva.

Después de revisar el diagnóstico de `269408` y autorizar explícitamente esta recuperación offline, el comando previsto es:

```bash
FDH_DATA="$HOME/FootballDataHub-data"
: "${FDH_MATCH_REVIEWER:?Define FDH_MATCH_REVIEWER con la identidad del operador}"
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" \
  --store-root "$FDH_DATA/matches/details" \
  revalidate-failed \
  --campaign-id match-detail-campaign-v2-06aa2259b14b95a7 \
  --internal-id pf-2026-27-group-i-bdfutbol-269408 \
  --operator "$FDH_MATCH_REVIEWER" \
  --confirm-revalidation REVALIDATE_FAILED_ARTIFACT_V2
```

Este comando no se ejecutó sobre la campaña real durante el hotfix. La prueba real de parser se hizo de forma local y de solo lectura; no abrió navegador ni realizó HTTP.

Para una futura ejecución en servidor UJA deben validarse allí almacenamiento persistente con rename/fsync y locks POSIX, `data-root` y generaciones históricas, Chromium/SeleniumBase/Pure CDP/Xvfb disponibles, perfil aislado, dependencias de jugadores para publicar y accesibilidad local de índice/package. La adquisición real debe seguir siendo secuencial y aprobada por candidato. El servidor puede ejecutar el CLI con rutas configuradas; no debe suponer que el adaptador de navegador está instalado o autorizado sin esa comprobación. No se añade programación periódica ni despliegue.

## Validación de MATCH-04D

La integración temporal de `tests/test_match_detail_operational_campaign.py` recorre propuesta de tres partidos de ambos grupos, inicialización, preflight, autorización individual, adquisición simulada, artefacto inmutable, validación offline mediante parser sustituido en prueba, borrador, rechazo de publicación sin aprobación, recibo sintético temporal, publicación simulada, verificación, cierre e incorporación del estado al inventario. Los tests heredados de campañas v1, publicación MATCH-03 y MATCH-04C se ejecutan aparte. La sustitución del parser y del publicador en el test de ciclo valida el contrato/orquestación sin fingir que se adquirió un partido real ni aprobarlo.
