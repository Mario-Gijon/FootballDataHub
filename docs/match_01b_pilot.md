# MATCH-01B — Piloto de descubrimiento de una ficha de partido

## Alcance y estado

Esta fase prepara un piloto de una sola URL, seleccionada desde el inventario persistido y verificado MATCH-01A. El único registro permitido es `272582`: Grupo II, temporada `2026-27`, jornada 7, IDs de equipo local/visitante 49 y 94 y marcador de referencia 3–3. Su URL se lee del inventario y se valida contra la generación MATCH-00; no se construye a partir del ID.

No se ejecutó Chromium, SeleniumBase, Playwright ni HTTP durante MATCH-01B. El preflight ejecutado fue offline. Las pruebas usan HTML sintético y adaptadores falsos; no acreditan el DOM de BDFutbol.

## Componentes

- `inventory.py` sigue verificando la generación MATCH-00, sus capturas, manifiestos, hashes y el inventario determinista.
- `pilot_cli.py` vuelve a construir el inventario desde la generación, compara el resultado con `inventory.json` y `manifest.json` persistidos, selecciona exclusivamente el ID piloto y revisa el almacén.
- `acquisition.py` conecta el inventario con `BDFutbolAccess` y `MatchDetailStore`. Tiene una sola llamada a `open`, sin reintentos, y nunca llama a `store_valid_capture`.
- `discovery.py` describe el DOM genéricamente: título, conteos de etiquetas, atributos observados, tablas/celdas, controles, scripts, claves y forma/tipos de JSON parseable, enlaces y términos que pueden orientar una revisión. No copia los valores JSON embebidos a ese resumen.
- `store.py` almacena posibles páginas de descubrimiento bajo `diagnostics/<inventory_id>/<discovery_id>/`, separadas de `captures/`, con manifiesto y SHA-256. Antes de llamar a `access.open()`, el checkpoint registra atómicamente un intento `started` con ID, inventario, partido, URL y timestamp. El ID queda persistido; la autoridad para completar ese intento es una capacidad en memoria del mismo objeto de almacén y no se recupera tras reiniciar.

## Reserva duradera de navegación

El bloqueo exclusivo del almacén cubre la comprobación del checkpoint, la escritura durable de la reserva y la llamada única a `access.open()`. La escritura usa el reemplazo atómico existente, con `fsync` del archivo y del directorio antes de que `begin_navigation_attempt()` devuelva el permiso al llamador. Por tanto, el adaptador no se invoca si esa escritura no termina.

Una excepción normal del adaptador se conserva como diagnóstico del intento y puede resolver la reserva tras guardar ese diagnóstico. Una terminación abrupta (por ejemplo, SIGKILL) no ejecuta resolución: el estado conserva `status: started` y el preflight informa `interrupted_navigation_attempt_requires_manual_review`. No se reintenta, no se borra la reserva y no existe desbloqueo automático. Hace falta revisar manualmente la evidencia antes de cualquier cambio operativo.

Los intentos, diagnósticos y capturas son registros separados: una reserva `started` solo prueba que la navegación iba a comenzar; un diagnóstico describe su resultado; un snapshot verificado requeriría el flujo de promoción de MATCH-01A y evidencia de identidad y estructura. La reserva permite a su propietario en el proceso actual añadir el artefacto de descubrimiento y el diagnóstico de cierre. Un proceso nuevo, aunque conozca el ID persistido, no puede reutilizar esa autoridad en memoria. Los checkpoints de MATCH-01A sin campos de intentos se leen como un historial vacío.

## Evidencia observada frente a hipótesis

El informe marca `semantic_mapping_confirmed: false`. Los nombres de atributos, encabezados de tabla, claves JSON, texto visible, enlaces y valores numéricos en query se conservan como observaciones literales. Las coincidencias de palabras se etiquetan `unverified_keyword_hypothesis`. No se fija ningún selector semántico de BDFutbol y no se concluye que un `id` en cualquier fragmento represente la identidad del partido.

El ID `272582` se pasa a `BDFutbolAccess` solo como marcador preliminar para clasificar la respuesta. Que el marcador aparezca no verifica identidad ni estructura. La primera página real deberá contrastarse con la URL final, los IDs del partido y de ambos equipos, y las estructuras realmente visibles antes de diseñar un parser. No se promocionará un snapshot en esta fase, aunque el acceso preliminar resulte `VALID`.

`BrowserDocument.html()` devuelve la serialización HTML del DOM disponible en la sesión, no los bytes originales de transporte HTTP. El adaptador lo registra como evidencia de DOM de navegador; la interfaz actual no expone el cuerpo HTTP original.

## Paradas y conservación

- HTTP distinto de 200, estado HTTP desconocido, redirección, desafío, error de navegación o error de documento: registrar diagnóstico y detenerse; no guardar HTML de desafíos o redirecciones.
- HTTP 200 de la URL esperada, sin desafío: guardar el HTML del DOM y el informe genérico únicamente como artefacto de descubrimiento, y dejar el estado en revisión/parada.
- La corrupción o desaparición de cualquier archivo de descubrimiento referenciado bloquea la reconciliación por separado de `invalid_snapshots`.
- Los diagnósticos son históricos y no se borran. No existe desbloqueo automático.
- Los datos van fuera de Git, en `$HOME/FootballDataHub-data/matches/details/diagnostics/`. Las capturas existentes y la generación MATCH-00 no se alteran.

## CLI

El modo predeterminado es offline y no inspecciona perfiles ni procesos. Ejecuta el preflight con:

```bash
cd ~/Documents/Trabalo/Proyectos/RealJaen/FootballDataHub-match-00-offline
PYTHONPATH=src "$HOME/Documents/Trabalo/Proyectos/RealJaen/FootballDataHub/.venv/bin/python" scripts/acquire_bdfutbol_match_detail_pilot.py --dry-run
```

El preflight compara la generación local, el inventario persistido y el checkpoint, informa dependencias de Pure CDP/Xvfb/Chromium y espacio escribible. No prueba ni abre el perfil. En el futuro, `BrowserSessionManager` adquirirá su lock del perfil antes de crear Chromium. El CLI no inspecciona procesos PLAYER-01C2; para el modo real exige una confirmación explícita de que el navegador de PLAYER está inactivo.

Un estado `PREFLIGHT_READY_PROFILE_UNCHECKED` solo indica que inventario, dependencias y almacén están preparados offline. No autoriza la navegación: faltan la ruta existente del perfil, el lock/proceso comprobado al iniciar la sesión y las dos confirmaciones explícitas. Si se encuentra una reserva `started` sin resolver, el informe incluye `pending_navigation_attempt` y bloquea el modo real para revisión manual.

El comando futuro, **no ejecutado en MATCH-01B**, será:

```bash
cd ~/Documents/Trabalo/Proyectos/RealJaen/FootballDataHub-match-00-offline
PYTHONPATH=src "$HOME/Documents/Trabalo/Proyectos/RealJaen/FootballDataHub/.venv/bin/python" scripts/acquire_bdfutbol_match_detail_pilot.py \
  --profile-dir "$FDH_BDFUTBOL_PROFILE" \
  --confirm-player-browser-idle \
  --confirm-real-acquisition
```

Después de obtener un artefacto de diagnóstico, su HTML y `discovery.json` se conservan juntos. Si se quiere volver a generar el informe offline desde el HTML guardado, usar un destino nuevo fuera de `captures/`:

```bash
mkdir -p "$HOME/FootballDataHub-data/matches/details/discovery-reports"
PYTHONPATH=src "$HOME/Documents/Trabalo/Proyectos/RealJaen/FootballDataHub/.venv/bin/python" \
  scripts/analyze_bdfutbol_match_detail_html.py \
  "$HOME/FootballDataHub-data/matches/details/diagnostics/<inventory_id>/<discovery_id>/raw/source.html" \
  --output "$HOME/FootballDataHub-data/matches/details/discovery-reports/<inventory_id>-<discovery_id>-rerun.json"
```

`FDH_BDFUTBOL_PROFILE` debe apuntar al perfil autorizado seleccionado por el usuario. No se debe ejecutar hasta que PLAYER-01C2 haya liberado el navegador. Si hay una parada activa, corrupción, falta de espacio o conflicto de perfil, el CLI debe detenerse antes de navegar. La navegación real podrá generar una parada `DISCOVERY_REVIEW_REQUIRED`; no se debe repetir ni desbloquear el lote para obtener otra captura.

## Verificaciones realizadas

El preflight offline real verificó:

- 140 registros y `inventory_id=match-detail-inventory-8cf339654c80c0ef`.
- SHA-256 de `inventory.json`: `9be747311ff237235b21e27c064d486d4ce990c3278d9020bae816968aabac08`.
- SHA-256 de su manifiesto: `e31b4ad341c87634b8f1cc032e02acae40d7de94f5a0de9e23a0a58ee3056b2b`.
- Generación `match-00-4ad1d610507e425d` y hash de manifiesto `00166887b13413e3e6a5344fa1c64d52db8d38800f3ef9f282237584b3e65fbf`.
- Selección exacta del partido 272582 desde el inventario.
- Cero capturas verificadas, cero snapshots inválidos y ninguna parada activa al preflight.
- SeleniumBase, Xvfb y Chromium disponibles en el entorno de ejecución consultado. No se inspeccionó el perfil.

Los tests sintéticos verifican el flujo de una navegación como máximo, la reserva durable antes del adaptador, interrupción abrupta y bloqueo tras reinicio, autoridad del propietario, resolución con diagnóstico/artefacto, respuestas HTTP, timeout sin estado, desafío, redirección, artefactos separados, hash/corrupción, checkpoint detenido, rechazo de identidad incorrecta y que el dry-run no modifica el almacén ni abre sockets o instancia un navegador.

## Pendiente para MATCH-01B real / MATCH-01C

- Que el navegador/perfil autorizado esté libre y su lock disponible.
- Una navegación real única a la URL ya persistida.
- Revisar manualmente el informe y el HTML de DOM real.
- Confirmar si identidad, equipos, marcador, alineaciones, banquillo, entrenadores, eventos, minutos, estadio, árbitro y enlaces aparecen, y documentar evidencia concreta.
- Implementar parser semántico únicamente a partir de esa evidencia, con referencias ligadas al hash.
- Tests del parser basados en una captura real autorizada antes de que cualquier dato pueda pasar a `store_valid_capture`.

La estructura actual de promoción de MATCH-01A exige cuatro registros `FieldEvidence` y coincidencias literales/hash. Es una barrera necesaria, pero el parser futuro aún deberá demostrar que sus referencias corresponden a nodos y campos semánticos reales; no se debe fabricar esa evidencia desde una lista de banderas.
