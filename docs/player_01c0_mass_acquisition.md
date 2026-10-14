# PLAYER-01C0 — preparación de adquisición masiva

## Alcance y decisión

Esta fase prepara la adquisición de vistas individuales de jugadores. No ejecuta
navegaciones a BDFutbol. El lote de 1.705 jugadores pendientes y 6.820 vistas no
se ha iniciado.

El preflight técnico de inventario, Chromium, Xvfb, perfil y almacenamiento es
correcto. La decisión global sigue siendo **BLOCKED**: no hay evidencia real de
BDFutbol que permita distinguir un perfil legítimamente inexistente de un HTTP
404 transitorio. El orquestador bloquea `--execute` hasta validar esa política.
No se debe saltar un error por su código HTTP sin evidencia de la página.

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
`/tmp/fdh-player-01c0-progress-final.json`; SHA-256:
`100919e5cdd5c688008bfae56d0ea5fd479242ae4b3e662a535d807a5c59a3a4`. Se puede
reconstruir offline y no es un dataset publicado.

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

Ejemplo de inicio una vez resuelta la condición BLOCKED:

```bash
cd "$HOME/Documents/Trabalo/Proyectos/RealJaen/FootballDataHub"
mkdir -p "$HOME/FootballDataHub-data/players/logs"
tmux new-session -d -s fdh-player-mass \
  "cd '$HOME/Documents/Trabalo/Proyectos/RealJaen/FootballDataHub' && PYTHONPATH=src .venv/bin/python scripts/acquire_bdfutbol_players.py --execute >> '$HOME/FootballDataHub-data/players/logs/acquisition-2026-27.log' 2>&1"
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
  "cd '$HOME/Documents/Trabalo/Proyectos/RealJaen/FootballDataHub' && PYTHONPATH=src .venv/bin/python scripts/acquire_bdfutbol_players.py --execute --resume '<capture_id>' >> '$HOME/FootballDataHub-data/players/logs/acquisition-2026-27.log' 2>&1"
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

El presupuesto da margen suficiente con la muestra disponible, pero es una
extrapolación de cuatro jugadores. El orquestador volverá a comprobar el espacio
libre antes de empezar.

## Browser isolation

El primer smoke en `about:blank` observó que el escritorio heredaba `DISPLAY=:0`
y que el Xvfb administrado también había asignado `:0`. No se pudo atribuir de
forma concluyente el mismo número a la visibilidad de ventanas, así que ese
resultado no se aceptó como prueba de aislamiento. El runtime ahora prueba
displays virtuales explícitos en `:90` a `:199`, omite el número heredado y falla
cerrado si ambos coinciden. Chromium se inicia con `DISPLAY` del Xvfb, sin
variables Wayland y forzando X11.

El smoke repetido abrió solo `about:blank` con el perfil autorizado: Chromium y
Xvfb usaron `:90`, mostraron 1920×1080, ambos procesos se cerraron y se pudo
reacquirir el lock del perfil. No se visitó BDFutbol en esta fase.

## Pruebas y limitación pendiente

La suite finalizó con **313 passed, 1 skipped** en 695,84 s. El único omitido es
la integración optativa de los 40 perfiles publicada, que requiere activar
`FDH_RUN_40_TEAM_PROFILE_INTEGRATION=1`. Ruff y `git diff --check` pasaron. Los
tests offline comprueban round-trip gzip, hashes, lectura compacta,
completitud de cuatro vistas, orden de cohortes, lock, presupuesto de disco e
interrupción/reanudación del estado del orquestador.
La validación de acceso todavía detiene cualquier error HTTP o de estructura.
Antes de ejecutar el lote completo hace falta evidencia de una página real de
perfil inexistente y una regla específica que la clasifique sin confundirla con
una denegación o un fallo transitorio. Hasta entonces, la recomendación es no
arrancar el lote.
