# MATCH-05B — Adquisición supervisada de campañas MATCH v2

## Alcance y garantías

MATCH-05B añade una revisión explícita, autorización individual y ejecución secuencial para campañas operativas v2. Reutiliza las propuestas inmutables MATCH-04C, el ledger append-only v2, `OperationalMatchCampaignLedger.execute_real()` y los informes atómicos de MATCH-05A. No crea autorizaciones masivas, no cambia los contratos de publicación y no aprueba ni publica documentos.

## Revisión completa con una confirmación de campaña

Para campañas grandes se añadió una ruta simplificada que mantiene el mismo ledger y ejecutor. `campaign-run-plan` muestra la lista completa, el desglose por grupo/jornada y `candidate_set_sha256`, sin autorizar ni iniciar navegador/HTTP. El hash vincula el ID de campaña, propuesta y plan, generación y manifiesto de origen, y la identidad/URL/resultado de cada candidato. Si cambia cualquier dato, la confirmación anterior deja de ser válida.

Después de revisar la lista completa, `run-confirmed-campaign --confirm-candidate-set-sha256 <hash>` registra una autorización v2 independiente por cada candidato. Cada evento conserva su ID de autorización, partido y URL, y referencia el mismo ID de confirmación y hash de conjunto. No solicita pegar cada URL ni una cadena por partido. La revisión única no habilita otras campañas ni candidatos fuera de esa lista.

El comando reutiliza `run_authorized_batch` y `execute_real`: las navegaciones siguen siendo secuenciales, con máximo una por autorización y cero reintentos. Una denegación, desafío, error de acceso o estado inconsistente activa la parada global; no navega los candidatos siguientes. El lock de PLAYER-01C2 sigue comprobándose antes de abrir Chromium. Las capturas obtenidas se procesan luego con el lote offline existente para validar y preparar borradores; errores semánticos quedan para revisión humana. No se llama a `approve`, `publish` ni `complete-review`.

Comandos para una campaña preparada:

```bash
FDH_DATA="$HOME/FootballDataHub-data"
CAMPAIGN_ID='match-detail-campaign-v2-75ed7927119a7225'
GENERATION="$FDH_DATA/matches/generations/match-00-72d8a65d33be2ee8"

# Solo lectura: revisar las 131 filas y copiar candidate_set_sha256.
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" --generation-root "$GENERATION" \
  campaign-run-plan --campaign-id "$CAMPAIGN_ID"

# Solo después de la confirmación explícita de toda la lista revisada.
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" --generation-root "$GENERATION" \
  run-confirmed-campaign --campaign-id "$CAMPAIGN_ID" --operator '<nombre>' \
  --confirm-candidate-set-sha256 '<hash_completo_del_preflight>'
```

La generación se pasa explícitamente para que el preflight, las URLs y las autorizaciones usen el mismo origen de la campaña. Este flujo no modifica el puntero activo de FastAPI. La salida y los informes diferencian autorización, adquisición y procesamiento offline; solo los documentos posteriormente aprobados por una persona pueden publicarse.

La revisión (`authorize-reviewed`) no inicia navegador ni HTTP. Para cada candidato muestra competición, temporada, grupo, jornada, equipos, marcador y fechas de referencia; requiere que el operador copie la URL exacta y escriba `AUTHORIZE_ONE_MATCH_DISCOVERY_V2`. Cada confirmación autoriza exactamente un candidato.

La ejecución (`execute-authorized-batch`) selecciona únicamente autorizaciones individuales todavía en estado `AUTHORIZED`, comprueba de nuevo la generación, URL, publicación, capturas, bloqueos y eventos de autorización, y consume cada autorización con `execute_real()` una sola vez. El ledger escribe `STARTED` de forma duradera antes de `access.open()`. El navegador Pure CDP/Xvfb y el perfil temporal dedicado se crean únicamente al ejecutar este comando. Las navegaciones son secuenciales y no hay reintentos automáticos.

La sesión exige confirmación textual específica y un lock compartido con `PlayerBatchLock`. Si PLAYER-01C2 posee el lock exclusivo, la sesión de partidos termina antes de navegar. El lock se mantiene durante toda la sesión; cada partido usa un perfil aislado bajo `data_root/browser-profiles/`.

Un HTTP 403/429, desafío, denegación, respuesta sin validar o error de acceso deja el candidato detenido y activa una parada global de la sesión. Una campaña con un informe `stop_acquisition` o un candidato `STOPPED` no admite más navegaciones por este flujo: requiere revisión humana. Una interrupción con `STARTED` sin resultado deja ese candidato en `INTERRUPTED_REQUIRES_REVIEW`; no se repite. Al reanudar, el proceso puede continuar únicamente con otras autorizaciones aún no consumidas. No se borra ni desbloquea automáticamente ningún evento.

Los informes por sesión viven en `matches/details/operations/reports/<campaign_id>/acquisition-*.json`. Se actualizan atómicamente después de registrar el estado de sesión y cada candidato, e incluyen operador, candidato, URL, ID de autorización/intento, estado, progreso de campaña, errores y una marca persistida de invocación de navegador/HTTP/navegación (no una telemetría del proceso Chromium), además del número máximo de navegaciones por autorización. La opción de cancelar con Ctrl-C conserva el informe y el ledger. Una terminación abrupta se reconcilia con el ledger en la siguiente ejecución.

## Secuencia operativa

Los siguientes comandos son una guía para una ejecución futura supervisada; **no se ejecutaron durante MATCH-05B**. No se han iniciado Chromium, SeleniumBase, CDP, Xvfb ni conexiones HTTP, y no se han modificado campañas, capturas o publicaciones reales.

Primero, inspeccionar la fuente vigente y proponer una campaña no autorizante. El tamaño es una propuesta, no una aprobación:

```bash
FDH_DATA="$HOME/FootballDataHub-data"
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" worklist

PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" propose --groups both --matchday-from 1 --matchday-to 7 \
  --limit 20 --persist
```

El tamaño solicitado puede ser 10, 20 o mayor: cambiar únicamente `--limit 20` por `--limit 10` para una propuesta más pequeña. Inicializar la propuesta sigue sin autorizar candidatos. Sustituir `<proposal_id>` por el ID emitido por `propose`:

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" initialize --proposal-id '<proposal_id>'
```

Antes de cualquier navegación, revisar el preflight y los candidatos. Después, iniciar la revisión interactiva; decidir cada URL por separado y omitir cualquier candidato que no se quiera autorizar:

```bash
CAMPAIGN_ID='<campaign_id_v2>'
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" campaign-preflight --campaign-id "$CAMPAIGN_ID"

PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" candidates --campaign-id "$CAMPAIGN_ID" --state NOT_AUTHORIZED

PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" authorize-reviewed --campaign-id "$CAMPAIGN_ID" --operator '<nombre>'
```

Solo después de revisar el preflight, comprobar que el navegador de jugadores está inactivo y decidir expresamente ejecutar la sesión, se puede autorizar el lote supervisado. `--limit` es un máximo por sesión y nunca otorga autorizaciones. Mantener `--limit 10` para sesiones de diez; usar `--limit 20` para una sesión de veinte:

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" execute-authorized-batch \
  --campaign-id "$CAMPAIGN_ID" --operator '<nombre>' --limit 10 \
  --confirm-session EXECUTE_SUPERVISED_MATCH_CAMPAIGN_SESSION \
  --player-browser-idle-confirmation PLAYER_BROWSER_IDLE_CONFIRMED
```

El comando imprime progreso antes y después de cada candidato y termina con una ruta al informe. Para consultar el informe, usar el comando ya existente:

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" batch-report \
  --path "$FDH_DATA/matches/details/operations/reports/$CAMPAIGN_ID/<acquisition-run-id>.json"
```

Tras una captura, MATCH-05A permite validar solamente los HTML guardados y preparar borradores offline. Esa operación no autoriza, no navega, no aprueba y no publica:

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_detail_campaigns.py \
  --data-root "$FDH_DATA" batch-offline --campaign-id "$CAMPAIGN_ID" \
  --confirm-offline-batch PROCESS_SAVED_MATCH_ARTIFACTS_OFFLINE
```

La revisión, aprobación hash-específica, publicación y cierre siguen siendo acciones individuales de MATCH-04D/MATCH-05A. No se ejecuta `approve`, `publish-approved` ni `complete-review` implícitamente desde la campaña supervisada.

## Reanudación y revisión manual

- Un candidato que conserva estado `AUTHORIZED` y no tiene evento `STARTED` puede volver a aparecer en una sesión posterior: no se consumió su autorización ni se navegó.
- Un candidato con `STARTED` y sin resultado final queda en revisión manual y se excluye permanentemente de la selección automática.
- Los candidatos restantes se pueden reanudar con autorizaciones no consumidas después de una interrupción no relacionada con denegación de acceso.
- Un `STOPPED`, desafío o denegación bloquea la campaña completa. No hay comando de desbloqueo ni reintento automático en MATCH-05B.
- La política exige revisar manualmente la causa y decidir mediante el flujo de campaña aprobado cómo proceder; no se debe volver a autorizar el mismo intento detenido.

Los informes son registros de progreso, mientras que los eventos de ledger son la fuente de verdad sobre autorizaciones consumidas e intentos iniciados. Nunca se usa únicamente el estado del informe para permitir repetir una navegación.

## Verificación de MATCH-05B

Las pruebas son offline y usan `tmp_path`, un ledger controlado y `SimulatedMatchAccessAdapter`. Incluyen 20 candidatos, confirmaciones individuales, selección limitada y secuencial, bloqueo del lock de PLAYER-01C2, denegación con parada global, reanudación excluyendo el candidato interrumpido, conservación de progreso y confirmaciones explícitas. Las pruebas v2 existentes verifican que `STARTED` se persiste antes de llamar al adaptador y que desafíos, denegaciones e interrupciones consumen la autorización sin habilitar otra navegación.

No se realizó ninguna adquisición real ni se modificó una campaña real en este hito.
