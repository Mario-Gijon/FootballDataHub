# PLAYER-01C1 — política segura y preflight de adquisición masiva

## Alcance y decisión

Esta fase prepara la adquisición, pero no ejecuta navegaciones a BDFutbol. El
lote de 1.705 jugadores pendientes y 6.820 vistas no se ha iniciado.

La política anterior que bloqueaba por falta de una página 404 observada se
eliminó. El sistema no intenta decidir si un jugador “no existe”: cualquier
resultado distinto de contenido e identidad válidos con HTTP 200 detiene el
lote. Un 404 queda registrado como error no verificado y nunca se salta.
El preflight local actual da **READY_FOR_EXPLICIT_EXECUTION**, sujeto a que el
usuario inicie el lote de forma explícita.

## Inventario y capturas

Entradas offline:

- Inventario PLAYER-01A: `$HOME/FootballDataHub-data/players/inventory-2026-27/players.json`
- Capturas inmutables: `$HOME/FootballDataHub-data/players/player-captures/`
- Perfil Chromium autorizado: `$HOME/.football-data-hub-chromium-pure-cdp`

El inventario contiene 1.709 IDs: 1.065 con pertenencia de plantilla y 644
referenciados únicamente desde Traspasos. Hay cuatro jugadores con las cuatro
vistas base verificadas (16 snapshots); quedan 1.705 jugadores y 6.820 vistas.
El orden es determinista: IDs de plantilla ascendentes y luego IDs de Traspasos
ascendentes. Las vistas son `profile`, `statistics`, `matches` y `rivals`.

El progreso de diagnóstico generado en esta ejecución está en
`/tmp/fdh-player-01c1-progress-final.json`; SHA-256:
`79e65d42ff001347ef9dc2e6be10567cf1fb220e0c9afbf8cb289ca823fad3b3`. Reconcilia
los snapshots originales en modo offline; los manifiestos y HTML no se alteran.

## Política de acceso y reanudación

La política `STOP_ON_UNVERIFIED_HTTP_ERROR` está en el camino de adquisición y
se prueba offline. Solo `VALID` + HTTP 200 + documento abierto puede avanzar.
HTTP 404, 403, 429, 5xx, estado HTTP ausente, desafío, identidad contradictoria,
URL incorrecta y error estructural dejan un diagnóstico con `player_id`, vista,
URL, HTTP, fecha y causa, y detienen el proceso antes de visitar al siguiente
jugador. Un 404 no se considera un perfil inexistente, no genera captura válida
y no permite continuar automáticamente. Las capturas previas permanecen
inmutables.

Una pausa por almacenamiento bajo se registra como `DISK_SPACE_LOW`, conserva el
estado del lote y permite volver a ejecutar el preflight y reanudar el mismo
`capture_id` después de liberar espacio. Este diagnóstico de almacenamiento no
se confunde con un error HTTP pendiente. La reserva mínima se consulta antes de
cada navegación, antes de escribir cada snapshot y después de guardarlo. La
comprobación de escritura usa el tamaño HTML sin comprimir como límite superior
y deja 64 KiB para metadata/compresión.

Al terminar las navegaciones, se reconstruye el índice completo. El estado del
lote solo será `complete` si verifica 1.709 IDs únicos, 1.709 jugadores con las
cuatro vistas base (6.836 pares), cero vistas pendientes, cero errores de acceso
sin resolver y cero manifiestos corruptos. `capture_id=complete` por sí solo no
certifica la cobertura global.

## Captura y reanudación

`scripts/acquire_bdfutbol_players.py` es de solo planificación si no se indica
`--execute`. En ejecución usa SeleniumBase Pure CDP, el perfil único, Xvfb
administrado por el runtime, una sola sesión secuencial y pausa mínima de cinco
segundos. No explora variantes de filtros. Cada snapshot se guarda y se valida
con el parser antes de contar como progreso. Si el parser falla, se registra el
diagnóstico y se detiene el lote.

Cada snapshot es un checkpoint recuperable en el manifiesto del `capture_id`.
`Ctrl-C` se registra como `interrupted`; los archivos ya guardados permanecen.
Al reanudar, el progreso se reconstruye desde los manifiestos y se reutilizan
las vistas válidas sin navegarlas otra vez. Un `flock` exclusivo impide dos
lotes sobre la misma raíz; el lock Chromium impide compartir el perfil.

El estado operativo persiste en:

- `$HOME/FootballDataHub-data/players/player-captures/acquisition-state-2026-27.json`
- `$HOME/FootballDataHub-data/players/player-captures/acquisition-progress-2026-27.json`
- Logs recomendados: `$HOME/FootballDataHub-data/players/logs/`

Comando definitivo de inicio. **No se ha ejecutado en este hito**:

```bash
cd "$HOME/Documents/Trabalo/Proyectos/RealJaen/FootballDataHub"
mkdir -p "$HOME/FootballDataHub-data/players/logs"
tmux new-session -d -s fdh-player-mass \
  "cd '$HOME/Documents/Trabalo/Proyectos/RealJaen/FootballDataHub' && PYTHONPATH=src .venv/bin/python scripts/acquire_bdfutbol_players.py --execute --pause-seconds 5 --reserve-gib 1.5 --inventory '$HOME/FootballDataHub-data/players/inventory-2026-27/players.json' --capture-root '$HOME/FootballDataHub-data/players/player-captures' --compact-root '$HOME/FootballDataHub-data/players/compact-2026-27' --profile '$HOME/.football-data-hub-chromium-pure-cdp' >> '$HOME/FootballDataHub-data/players/logs/acquisition-2026-27.log' 2>&1"
```

Monitorización y parada controlada:

```bash
tmux attach -t fdh-player-mass
# Para volver al shell sin detener: Ctrl-b, después d
cat "$HOME/FootballDataHub-data/players/player-captures/acquisition-state-2026-27.json"
tmux send-keys -t fdh-player-mass C-c
```

Tras reiniciar el ordenador, leer `capture_id` del estado y reanudarlo:

```bash
tmux new-session -d -s fdh-player-mass \
  "cd '$HOME/Documents/Trabalo/Proyectos/RealJaen/FootballDataHub' && PYTHONPATH=src .venv/bin/python scripts/acquire_bdfutbol_players.py --execute --resume '<capture_id>' --pause-seconds 5 --reserve-gib 1.5 --inventory '$HOME/FootballDataHub-data/players/inventory-2026-27/players.json' --capture-root '$HOME/FootballDataHub-data/players/player-captures' --compact-root '$HOME/FootballDataHub-data/players/compact-2026-27' --profile '$HOME/.football-data-hub-chromium-pure-cdp' >> '$HOME/FootballDataHub-data/players/logs/acquisition-2026-27.log' 2>&1"
```

La sesión `tmux` no sobrevive a un reinicio; los manifests, snapshots y estado
sí. El comando de reanudación crea otra sesión y continúa desde los datos
persistidos. No iniciar una segunda sesión si el primer proceso aún está vivo.

## Export compacto y procedencia

La evidencia original sigue siendo el HTML gzip con su SHA-256, metadata,
captured-at, URL final, identidad, controles y advertencias. No se modifica ni
se elimina.

`scripts/build_bdfutbol_player_compact_exports.py` produce una generación
versionada y atómica con un JSON gzip por jugador en `players/{id}.json.gz`, un
manifest con hashes y `current.json`. Agrupa cabeceras de tablas una sola vez y
elimina estilos/layout repetidos; los valores descartados pueden recuperarse
desde los HTML originales. Incluye identidad, trayectoria, estadísticas,
partidos, convocatorias sin participación, rivales, relaciones con clubes,
procedencia, cobertura y advertencias. Una generación solo declara
`COMPLETE_BASE_VIEWS` si las cuatro vistas pasan la validación; eso no certifica
exhaustividad histórica. El export verbose anterior sigue disponible mediante
`scripts/parse_bdfutbol_player_capture.py` para depuración solicitada.

La medición offline de los cuatro jugadores piloto produjo 3.066.047 bytes de
JSON sin comprimir y 191.771 bytes gzip (media 47.943; máximo 85.071). La
generación persistente está en
`$HOME/FootballDataHub-data/players/compact-2026-27/generations/20261014T170309.300465Z-c005a946/`;
SHA-256 del manifiesto: `f27c0abe89b95a05ccfbb61f55c01cfc9cddd4c1218d70480231a9a302838489`.
La medición temporal adicional está en `/tmp/fdh-player-01c0-gzip/`. Ambas se
pueden regenerar desde las capturas sin tráfico de red.

## Presupuesto de almacenamiento medido

El preflight calculó los máximos por vista observados en los 16 snapshots:

- Capturas y metadata pendientes: 1.849.166.275 bytes; con 25% de margen:
  2.311.457.844 bytes.
- JSON gzip compacto: extrapolación conservadora por máximo observado,
  181.732.924 bytes con 25% de margen.
- Logs, manifests e índices: 268.435.456 bytes.
- Espacio libre observado en la raíz de capturas tras publicar los cuatro
  compactos y ejecutar la suite: 5.191.127.040 bytes (4,835 GiB).
- Libre proyectado tras la adquisición: 2.429.500.816 bytes (2,263 GiB), por
  encima de la reserva obligatoria de 1,5 GiB.

El preflight PLAYER-01C1 final observó 4,802 GiB libres. La proyección para el trabajo
pendiente es 2,311,457,844 bytes de HTML/metadata con margen, 181,732,924 bytes
de exports compactos y 268,435,456 bytes para manifests/logs; quedarían
2,394,361,232 bytes (2,230 GiB), sobre la reserva de 1,5 GiB. La estimación se
basa en cuatro jugadores y se recalcula mientras avanza el lote.

## Browser isolation

El escritorio informó `DISPLAY=:0`, Wayland activo. Una prueba local de
`about:blank` con perfil temporal informó que Chromium nació en el `DISPLAY=:90`
de su Xvfb privado, sin `WAYLAND_DISPLAY`, con pantalla 1920×1080. El navegador
y Xvfb se cerraron y el lock del perfil se pudo adquirir de nuevo. No se visitó
BDFutbol. La ejecución en el sandbox no pudo iniciar Xvfb por restricciones del
entorno; la comprobación se realizó fuera del sandbox y permaneció solo en
`about:blank`.

## Pure CDP DOM readiness and safe resume

SeleniumBase Pure CDP's `get_text("body")` performs an internal element wait
and raises after seven seconds when the selector is not available. That
prevents the access layer from recording the navigation's HTTP status and
URL. The provider-neutral document adapter now reads the current DOM without
that implicit wait. `BDFutbolAccess` performs only its configured bounded DOM
readiness checks on the same navigation (four seconds for player base views).
Content that appears during that window can still be assessed; an unavailable
or incomplete document at the deadline remains `INVALID_CONTENT` and stops the
batch. Other DOM inspection exceptions are recorded as `DOCUMENT_ERROR` with
player, view, URL, HTTP status and final URL, then stop. Neither case reloads a
page or restarts a browser session. HTTP denials, challenges, identity
mismatches and structural failures continue to stop.

Before each navigation, the runtime status checkpoints the pending player,
view and requested URL. On resume, snapshots that already pass integrity and
parsing checks are reused without another visit.

## Pruebas y limitación pendiente

Los tests de PLAYER-01C1 cubren política HTTP offline, stop ante 404 sin visitar
el siguiente jugador, retención de capturas anteriores, diagnóstico y estado
reanudable, stop ante desafíos/identidad incorrecta, bajada dinámica de disco,
reanudación después de `DISK_SPACE_LOW`, exclusión de lote concurrente y
verificación de 1.709 × 4 antes de declarar éxito. La adquisición masiva sigue
sin iniciarse. El resultado READY permite iniciar una ejecución explícita; un
404 real u otra denegación detendrá ese lote y requerirá revisión antes de una
nueva ejecución.

Verificación de PLAYER-01C1: **332 passed, 1 skipped** en 577,99 s; omitida la
integración optativa de 40 perfiles. Los 30 tests focalizados de política,
reanudación, disco y progreso pasaron. Ruff y `git diff --check` también pasan.

## PLAYER-01C2 — reconciliación eficiente y reanudación del timeout

El run `20261014T180513.060987Z-85c60940` se detuvo en `27659/rivals` con
`NAVIGATION_ERROR`, `TimeoutError` y sin estado HTTP confirmado. La captura no
demuestra una denegación ni un desafío, así que se mantiene pendiente y nunca se
marca como válida.

El perfil acotado de la reconciliación anterior encontró el trabajo redundante:
en 60 segundos con `cProfile` solo avanzó por 21 snapshots; `parse_snapshot`
ocupó 47,2 s en 9 revalidaciones y BeautifulSoup construyó DOM 27 veces,
ocupando 34,6 s. El recorrido completo actual contiene 4.995 registros de
snapshot en dos manifiestos. El cuello de botella era volver a construir y
recorrer un árbol DOM grande para snapshots cuya validación ya estaba guardada,
además de volver a buscar linealmente en el manifiesto del run al preparar cada
jugador/vista.

La reconciliación ahora sigue calculando SHA-256 del HTML descomprimido y
verificando metadata, URL, identidad de captura, ID, vista, HTTP 200, tamaño y
procedencia en cada ejecución. Omite el parser pesado únicamente cuando la
validación previa está en la versión actual y el manifiesto acredita el mismo
SHA-256 del inventario; el HTML sigue teniendo que coincidir con los hashes del
manifiesto y metadata. Si cambia el inventario, la versión del parser o falta
esa vinculación, vuelve a parsear y validar identidad/estructura. No se añade
caché persistente que pueda ocultar cambios de snapshots.

`PlayerCaptureStore` crea índices en memoria para localizar snapshots por
jugador, vista, tipo y URL, y por `snapshot_id`. La adquisición normal aprovecha
el índice de progreso ya verificado para excluir las vistas existentes, sin
volver a barrer y descomprimir el manifiesto por cada vista del inventario. El
preflight envía progreso a stderr con manifiestos, snapshots verificados y
tiempo transcurrido.

Medición offline tras los cambios, contra los archivos locales existentes y sin
escrituras en el almacén de capturas:

- Tiempo total: **50,11 s** para 4.995 registros de snapshot y 4.976 vistas
  verificadas (la diferencia es un snapshot válido duplicado para el mismo
  jugador/vista).
- Resultado: 1.243 jugadores completos, 4.975 pares válidos únicos, 466
  jugadores pendientes y 1.861 vistas pendientes.
- Manifiestos corruptos: 0. Timeout transitorio pendiente: exactamente
  `27659/rivals` en el run indicado.
- El preflight CLI con reintento explícito obtuvo
  `READY_FOR_EXPLICIT_EXECUTION`; `execution_started` fue `false`.

Solo se autoriza un nuevo intento si el operador proporciona
`--retry-transient-navigation 27659/rivals` junto a `--resume` del mismo run.
El permiso cubre un único timeout sin HTTP confirmado, sin URL final, sin
marcadores de desafío/denegación y sin errores estructurales. No se cambia la
política de adquisición: esa navegación se ejecuta una vez, sin bucle de
reintentos, y cualquier nuevo timeout, HTTP 403/404/429/5xx, desafío, identidad
incorrecta o fallo estructural detiene el lote.

Comando preparado para una ejecución que el operador inicie explícitamente; no
se ha ejecutado en este hito:

```bash
PYTHONPATH=src .venv/bin/python scripts/acquire_bdfutbol_players.py \
  --execute --resume 20261014T180513.060987Z-85c60940 \
  --retry-transient-navigation 27659/rivals \
  --pause-seconds 5 --reserve-gib 1.5 \
  --inventory "$HOME/FootballDataHub-data/players/inventory-2026-27/players.json" \
  --capture-root "$HOME/FootballDataHub-data/players/player-captures" \
  --compact-root "$HOME/FootballDataHub-data/players/compact-2026-27" \
  --profile "$HOME/.football-data-hub-chromium-pure-cdp" \
  --browser-executable /usr/bin/chromium
```

La prueba completa de preflight usó rutas de salida bajo `/tmp`; no abrió
Chromium, no visitó BDFutbol ni cambió manifiestos, snapshots o archivos
capturados.
