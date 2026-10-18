# MATCH-04A — cierre de revisión y continuación controlada

## Auditoría local de partida

Se inspeccionaron en solo lectura el ledger bajo `$HOME/FootballDataHub-data/matches/details/campaigns/match-detail-sample-campaign-67fdc4b4fac66b82`, su artefacto y el índice de publicación. El plan sigue siendo el piloto original de cinco candidatos. El evento `DISCOVERY_REVIEW_REQUIRED` de `272525` es el tercer evento de su cadena; registra una navegación, HTTP 200, acceso `VALID`, el artefacto `discovery-20261018T112656Z-4543b211`, y `capture_promoted=false`. El candidato está validado y publicado por el flujo separado de MATCH-03, pero el ledger no tiene evento de cierre.

El índice local aprobado contiene exactamente `pf-2026-27-group-ii-bdfutbol-272525`, publicación `campaign-272525-9649b77712f8f259`. El manifiesto publicado enlaza el intento `c88b46383292846da1d8ec6a10b912b6`, el artefacto y el HTML SHA-256 `9649b77712f8f259dd4cc413ebc90c26305069a7cb96ab8829fed3aff4b01113`. El documento aprobado tiene SHA-256 `6382e831c5118052a7320b54e5f8e3c594653f881ae049943f21a5d520a5b009`; el manifiesto activo tiene SHA-256 `7d4982efc7f38e72de668d000486b9cdf3ac67554911172d63f84f5a20dffa58` y la aprobación `29d682fe6b5b016656cb4398b58b0bf5db6aaea16073c60cb2553cc1b24e9fb8`.

Se comprobó la disponibilidad pública **sin solicitudes HTTP**: se cargó la generación y el directorio publicados con los lectores locales usados por FastAPI, y `build_match_page()` devolvió `detail_status=available`, `publication_status=approved` para `272525`. El lector devolvió un único detalle publicado; no se encontró publicación activa de otro partido.

El preflight previo a este cambio devuelve `BLOCKED`, con la única razón `DISCOVERY_REVIEW_REQUIRED:272525`. El resto: `272517`, `272577`, `272524` y `269411` están `NOT_AUTHORIZED`, con cero navegaciones y sin promoción. El histórico de `272582` y su checkpoint no se modificaron.

## Cierre explícito

`complete-review` es una operación local, separada de adquisición y publicación. Requiere revisor y un token que incluye el ID del partido y los prefijos de los hashes del HTML y del documento aprobado. Bajo el lock exclusivo del ledger y un lock de lectura del índice de publicación, vuelve a validar el ledger/eventos/artefacto, usa el mismo lector integral que emplea FastAPI para validar el índice y el paquete aprobado, y vincula el recibo, el documento y el manifiesto al candidato y al intento originales. No acepta una aprobación de otro partido, un paquete no publicado, un artefacto alterado, ni referencias cruzadas inconsistentes.

El cierre añade `REVIEW_COMPLETED` al final de la cadena atómica. No reescribe ni elimina `DISCOVERY_REVIEW_REQUIRED`, no altera la captura ni la promoción. Repetir la misma operación con la misma persona y evidencia devuelve el evento ya existente; una petición distinta requiere revisión manual. `preflight` informa `state=REVIEW_COMPLETED` junto con `acquisition_state=DISCOVERY_REVIEW_REQUIRED`. Solo deja de bloquear por ese motivo concreto. Interrupciones, candidatos `STOPPED`, campañas con revisión histórica que bloquea, corrupción, artefactos huérfanos y cualquier otro bloqueo siguen fallando cerrados.

La revisión real de `272525` **no se ha cerrado** durante MATCH-04A y no se ha creado una aprobación humana ficticia. El operador que haya revisado el documento aprobado puede efectuarlo deliberadamente con:

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_campaign.py \
  complete-review \
  --internal-id pf-2026-27-group-ii-bdfutbol-272525 \
  --reviewer "NOMBRE DEL OPERADOR QUE HIZO LA REVISION" \
  --confirm-review-complete COMPLETE-REVIEW-272525-9649b77712f8-6382e831c511
```

Luego debe comprobar el estado, sin iniciar navegador:

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_campaign.py preflight
```

Si la revisión se completa, el primer candidato pendiente será `272517` (`pf-2026-27-group-ii-bdfutbol-272517`, URL del plan `https://www.bdfutbol.com/es/p/p.php?id=272517`). Quedará disponible **para autorización humana individual**, no autorizado ni navegado. Solo tras revisar la ficha de partido de MATCH-00 y aprobar expresamente ese candidato se ejecutaría:

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_campaign.py \
  authorize \
  --internal-id pf-2026-27-group-ii-bdfutbol-272517 \
  --reviewer "NOMBRE DEL OPERADOR QUE AUTORIZA" \
  --review-id legacy-stop-review-44d4114b224a43ca \
  --confirm-url https://www.bdfutbol.com/es/p/p.php?id=272517 \
  --confirm-authorization AUTHORIZE_ONE_DISCOVERY_NAVIGATION
```

La autorización no navega. La navegación requiere después el comando `run` con el perfil exclusivo, confirmación de una sola navegación y confirmación de que el navegador de jugadores está inactivo. Ninguno de esos comandos se ejecutó en MATCH-04A.

## Pruebas y garantías

Las pruebas nuevas usan únicamente almacenes temporales: cierre de candidato con publicación aprobada, adquisición sin publicación, artefacto corrupto, recibo de otro partido, confirmación incorrecta/incompleta, evento incompleto, idempotencia, conservación de eventos existentes y liberación del preflight para candidatos todavía no autorizados. Las pruebas existentes siguen comprobando una autorización por candidato, un intento por autorización y parada ante errores de acceso.

La finalización operativa registra referencias y hashes verificados por el cargador público actual. No es una firma criptográfica del revisor: es un evento local auditable bajo la misma confianza de filesystem y ledger que el resto de la campaña. El índice activo puede cambiar en una publicación posterior; el evento conserva qué paquete aprobado se revisó y el ledger no promueve datos.

## Extensión posterior desde MATCH-00

El plan actual conserva inmutable el máximo de cinco IDs `272525`, `272517`, `272577`, `272524` y `269411`; MATCH-04A no modifica ese plan ni su identidad. Para una campaña futura, construir un plan versionado desde una generación MATCH-00 verificada y su inventario de partidos disputados. Cada fila debe fijar `internal_id`, ID de BDFutbol, grupo, URL explícita, estado disputado, resultado de referencia, ID/hash de generación y captura de origen. Derivar el ID de campaña de un basis inmutable que incluya el inventario y la lista ordenada de candidatos.

Antes de crearla, excluir por ID —nunca por similitud de nombres— cada encuentro que ya esté presente en planes/ledgers, intentos iniciados, artefactos, capturas o índice de publicación. Ante un duplicado con procedencia contradictoria, bloquear y revisar; no reasignar el intento anterior. Las nuevas campañas mantienen autorización explícita por partido, una navegación sin reintentos y cierre/publicación separados. Nuevos marcadores requieren una nueva generación MATCH-00 validada y una campaña incremental; no se modifica una generación anterior.

Para el futuro servidor UJA, validar primero almacenamiento y permisos con `preflight`, instalar el mismo paquete y datos versionados, y comprobar si el adaptador de navegador autorizado funciona en ese host antes de adquirir. Guardar las capturas en almacenamiento local externo a Git, validar offline manifiestos, hashes, identidad y semántica, y preparar publicaciones inmutables en staging. Cambiar el índice activo atómicamente solo después de revisión; desplegar/reiniciar FastAPI para cargarlo y verificar la API local. Los datasets históricos se conservan. No se configura cron ni se habilita scraping masivo en este hito.
