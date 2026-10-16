# MATCH-01A — Infraestructura offline de detalle de partidos

## Alcance y prohibiciones

MATCH-01A prepara la selección, los contratos y el almacenamiento para una adquisición posterior. No incluye parser de páginas individuales, cliente HTTP, SeleniumBase, Playwright, Chromium ni ejecución de navegación. La CLI solo lee la generación local MATCH-00 y, de forma optativa, persiste un plan inmutable.

La adquisición debe esperar a que PLAYER-01C2 libere el perfil autorizado. No se comparte ni se abre un segundo navegador dentro de este hito.

## Origen verificado e inventario

La generación de referencia es match-00-4ad1d610507e425d, bajo ~/FootballDataHub-data/matches/generations/. El inventario verifica:

- SHA-256 y tamaños de matches.json y validation.json según manifest.json.
- Identidad de temporada, competición, grupos y generación.
- SHA-256, rutas contenidas en data_root, captura de metadata, HTML original y JSON normalizado de ambos grupos.
- Reproducción offline con build_match_generation() existente. Los artefactos regenerados deben coincidir byte por byte con los publicados.
- Solo se incluyen filas played que tengan una URL individual observada y válida. Se comprueban IDs namespaced y originales, equipos pertenecientes al grupo y unicidad de URLs. Se rechazan rutas externas, symlinks, URLs ajenas al dominio/ruta esperados y discrepancias entre ID de partido y parámetro URL.

Resultado inspeccionado: 760 partidos fuente, 40 equipos, 140 partidos elegibles (70 por grupo), 140 IDs fuente únicos y 140 URLs explícitas únicas. No se inventan enlaces para los 620 partidos no disputados. El inventory_id deriva del contenido canónico del inventario; orden y bytes son reproducibles. Cada fila preserva la generación, hash de su manifiesto, captura de grupo y hash de HTML/JSON fuente. La fecha y el marcador se etiquetan como referencia del calendario, no como sustitutos de lo que publique una ficha futura.

Estados iniciales por partido: acquisition_status=pending, validation_status=not_acquired.

## Contratos de detalle

football_data_hub.domain.matches.details define modelos congelados y versionados independientes del navegador:

- Identidad: ID interno namespaced, ID BDFutbol, temporada, competición, grupo, jornada y IDs locales/visitantes.
- Fecha, hora y zona horaria; estadio y árbitro; equipos, entrenadores, alineaciones y suplentes; dorsales y participación; marcador y eventos.
- Eventos con tipo semántico, banderas opcionales de penalti/autogol, jugadores fuente e involucrados y minuto literal. parse_literal_minute() obtiene componentes derivados de literales como 45+2 o 90+6 sin reemplazar el literal.
- FieldEvidence distingue observado, explícitamente ausente, no observado y pendiente de resolver. raw_value conserva 0 y ""; None no se usa para representar un cero.
- Las diferencias con fecha, goles, estadio o árbitro del calendario se conservan como MatchDiscrepancy. Nunca se corrige silenciosamente la observación original.

No se afirma que estos campos hayan sido observados en fichas individuales. Aún no existe un parser de esos HTML.

## Promoción y parada

assess_capture() comprueba HTTP 200, URL solicitada y final exactas, identidad/equipos normalizados, contexto, los marcadores estructurales declarados y la validación. Esos flags por sí solos no autorizan la promoción.

store_valid_capture() exige además cuatro registros FieldEvidence observados: structure.match_detail_root, identity.source_match_id, home_team.team_id y away_team.team_id. Cada uno debe incluir referencia de origen, valor literal presente en los bytes HTML, SHA-256 de esos mismos bytes y versión del parser usada. Los valores de identidad deben coincidir con el inventario. Al reconciliar un snapshot se repiten estas comprobaciones contra el HTML guardado. Si falta evidencia, se registra SOURCE_EVIDENCE_UNVERIFIED, se detiene el checkpoint y no se escribe el snapshot.

Estas comprobaciones vinculan evidencia auditable a la captura y hacen insuficiente marcar identity_verified o structural_evidence sin más. No prueban que el parser haya interpretado correctamente el significado de una ubicación del DOM. MATCH-01B debe inspeccionar una página real autorizada, definir referencias de origen a partir de su estructura observada y demostrar que cada valor se extrae del elemento/dato que representa la identidad o estructura requerida. No se fijan selectores HTML antes de esa exploración. Las discrepancias de observaciones se registran y nunca sustituyen silenciosamente al calendario.

Todo estado HTTP que no sea 200 (incluidos 403, 404, 429 y 5xx), estado HTTP desconocido, desafío, denegación, URL inesperada, identidad incorrecta o falta de evidencia/estructura detiene la ejecución. stop_for_validation() registra el diagnóstico completo en el checkpoint; no hay reintentos. Esta política es un contrato para un adaptador futuro, no una prueba de acceso real.

## Almacén y recuperación

MatchDetailStore ofrece:

- inventories/<inventory_id>/inventory.json y manifest.json inmutables. El mismo contenido es idempotente; cualquier diferencia en una generación existente produce error y no sobrescribe.
- captures/<inventory_id>/<capture_id>/ con raw/source.html, match_detail.json, validation.json, metadata.json y manifest.json. Las capturas de generaciones distintas quedan aisladas. Se escribe en staging, se fsync y se promueve mediante rename atómico. El manifiesto fija hashes y tamaños de HTML, detalle, validación y metadata; el checkpoint conserva el hash del manifiesto.
- states/<inventory_id>.json como checkpoint mutable versionado y escritura atómica, con diagnóstico, estado y referencias de snapshots.
- acquisition.lock mediante flock, para una sola adquisición por almacén. El mismo MatchDetailStore permite llamadas anidadas durante una sesión secuencial.
- reconcile() recorre una vez los snapshots, vuelve a comprobar su identidad, evidencia y hashes, y devuelve un índice en memoria por internal_id. Distingue integrity_blocked (captura/checkpoint corrupto o incompatible) de active_stop (checkpoint stopped o diagnóstico con stop_acquisition). Ambos impiden promover; la parada también impide devolver una captura reutilizada. No confía solo en el checkpoint ni reutiliza un archivo por existir.
- Una captura válida se reutiliza sin escribir otra copia solo si no hay corrupción ni parada activa. Los diagnósticos son append-only y una parada no se resuelve borrándolos ni cambiando únicamente el estado. Este hito no implementa mecanismos de desbloqueo. finalize_inventory() solo marca completa si todos los registros tienen snapshot válido, no hay corrupción y no existe diagnóstico de parada.

No se borra una captura inválida automáticamente; requiere inspección explícita. Los snapshots promovidos no se editan ni sustituyen.

## CLI exclusivamente offline

Dry-run, sin escribir inventario, captura ni checkpoint:

    PYTHONPATH=src python scripts/plan_bdfutbol_match_details.py --dry-run

La salida JSON contiene estado READY/BLOCKED, conteos, IDs pendientes, capturas ya verificadas, errores previos, integridad del almacenamiento y espacio libre. Por defecto apunta a la generación y al almacén bajo ~/FootballDataHub-data. Se puede fijar --min-free-bytes para comparar la reserva requerida con el espacio disponible.

El archivo inmutable del inventario conserva estados iniciales pending/not_acquired. En el resultado del plan, match_states combina ese inventario con la reconciliación actual y muestra por partido pending/not_acquired o verified/valid, además del capture_id y el hash del HTML verificado.

Para persistir la generación inmutable del plan, después de revisar el dry-run:

    PYTHONPATH=src python scripts/plan_bdfutbol_match_details.py --persist-plan

Esto sigue siendo offline y no inicia adquisición. Sin --persist-plan o --write-inventory, la CLI no escribe datos.

## Pruebas y estado

Las pruebas unitarias usan inventarios y HTML sintéticos, explícitamente no presentados como contenido real de BDFutbol. Cubren IDs/URLs, rutas y symlinks, idempotencia, promoción, corrupción/truncamiento, denegaciones, reanudación, bloqueos, escritura atómica, discrepancias, minutos y que el plan no use APIs de red.

La integración local del snapshot del 14/10 es opt-in y vuelve a validar el origen:

    FDH_MATCH_01A_INTEGRATION=1 FDH_MATCH_01A_DATA_ROOT="$HOME/FootballDataHub-data" PYTHONPATH=src python -m pytest -p no:rerunfailures -p no:cacheprovider tests/integration/test_match_detail_inventory_latest.py

El plugin pytest-rerunfailures se desactiva porque su inicialización abre un socket local, restringido por algunos sandboxes. La suite histórica global de TestClient no es requisito para esta infraestructura offline.

## Límites y siguiente hito

No hay evidencia adquirida en este hito sobre selectores, HTML, eventos, alineaciones o los filtros reales de las fichas. Los marcadores del calendario son solo valores de referencia. Los contratos de estructura deben ajustarse tras inspeccionar una página autorizada; los marcadores mínimos actuales describen los tipos de evidencia que el futuro parser debe aportar, no selectores BDFutbol verificados.

MATCH-01B debería empezar con una sola ficha real de la generación, bajo sesión autorizada y secuencial cuando el navegador esté disponible: adquirir HTML una vez, registrar status/URL/tiempo, explorar DOM y datos embebidos, verificar identidad y estructura con evidencia por campo, guardar snapshot solo después de validar, comparar fecha/resultado con MATCH-00 como observaciones separadas y actualizar el checkpoint. Cualquier denegación o desafío se registra y detiene el lote.
