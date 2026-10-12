# Adquisición por lotes de fichas de equipo

## Alcance y estado

El comando `scripts/acquire_bdfutbol_team_batch.py` prepara la adquisición
secuencial de las fichas de los 40 equipos de Primera Federación 2026/27. No se
ha iniciado el lote completo ni se han hecho nuevas visitas a BDFutbol en
TEAM-01B. El inventario, la selección de capturas y los planes se pueden
inspeccionar offline con `--dry-run`.

La política predeterminada pide seis vistas (`alignment`, `squad`,
`statistics`, `follow`, `transfers`, `matches`) y los cuatro estados de
Seguimiento (`p`, `t`, `go`, `tot`). Una captura solo se marca completa después
de volver a validar sus archivos originales y normalizados. La inspección no
confía únicamente en `valid=true` ni en la fecha de la carpeta.

## Estados de captura y reanudación

La inspección clasifica cada captura como:

- `complete`: identidad de equipo, grupo, temporada y catálogo compatibles;
  seis vistas con acceso válido y hashes correctos; cuatro estados de
  Seguimiento válidos; JSON normalizados completos que coinciden con una nueva
  normalización offline; validación semántica vigente.
- `reusable_seed`: identidad, catálogo, Alineación, vistas disponibles y
  relaciones semánticas suficientes para continuar. Puede faltar cobertura de
  la política actual o un JSON derivado requerido.
- `incomplete`: su equipo y procedencia son reconocibles, pero no es una
  semilla segura o no satisface el alcance inspeccionado.
- `invalid`: equipo, grupo, temporada, captura, catálogo o evidencia de origen
  no corresponden o no se pueden verificar.

También se informa por separado si la captura fue válida para las vistas que
declaró originalmente. Esto permite conservar capturas históricas sin
considerarlas completas bajo la política actual. Ningún snapshot existente se
edita o elimina.

Al continuar una semilla, se cargan sus vistas y cada estado de Seguimiento con
hashes y procedencia. Los estados válidos se mantienen y no se vuelven a
navegar. Una captura con los seis HTML pero solo el estado `p` necesita una
visita a Seguimiento; durante esa sesión se adquieren solo `t`, `go` y `tot`.
Los datos de minutos, goles y tarjetas se vuelven a exportar desde la semilla y
la evidencia nueva, sin completar eventos ausentes a partir de totales.

La selección prioriza la captura con mejor cobertura validada y solo usa la
fecha para desempatar capturas con igual cobertura.

## CLI de preparación y control

Opciones disponibles:

- `--dry-run`: inspecciona catálogos y capturas, escribe el plan en stdout y no
  inicia el navegador ni escribe capturas/manifiestos.
- `--team-id ID`: limita a un equipo; puede repetirse. Cada ID debe existir en
  los catálogos de los grupos incluidos en `--groups`.
- `--limit N`: limita globalmente el número seleccionado, manteniendo el orden
  de grupo y catálogo.
- `--pause-seconds SEGUNDOS`: pausa entre páginas y equipos. El valor
  predeterminado es 2 segundos.
- `--groups I`, `--groups II` o `--groups both`: selecciona grupos.
- `--view VISTA`: repetible para pedir un alcance menor en un piloto.
- `--output-root RUTA`: raíz configurable. Para el servidor UJA se recomienda
  una ruta persistente externa al checkout.

El plan informa capturas elegidas, cobertura existente, estados faltantes,
visitas previstas y transiciones de Seguimiento. La ejecución crea una sesión
de navegador por equipo, procesa un equipo cada vez y no abre sesiones en
paralelo. No reintenta una denegación ni cambia de navegador, perfil o IP. Una
denegación/desafío o un fallo de navegador detiene el lote; un error local
aislado de parsing se registra y permite continuar.

## Manifiestos y almacenamiento

Cada resultado de lote se publica como un directorio versionado y create-only:

```text
<output-root>/<season>/batch-manifests/<run_id>/manifest.json
```

Incluye grupo, `team_id`, `capture_id`, semilla utilizada, vistas y estados
adquiridos o reutilizados, cobertura, referencia de catálogo, fecha de
adquisición, errores y estados `complete`, `incomplete`, `failed` o `pending`.
Los campos `batch_scope.full_catalog_scope` y `batch_complete` diferencian una
ejecución sobre todos los equipos de los grupos seleccionados de un piloto.
`batch_complete` solo es verdadero cuando se recorrieron Grupo I y Grupo II y
los 40 equipos quedaron completos. Un manifiesto parcial describe únicamente
su ejecución y nunca cambia el dataset activo de FastAPI.

Los HTML nuevos se conservan como gzip determinista. SHA-256 corresponde a los
bytes HTML sin comprimir. También se registran compresión y tamaños. La metadata
de la captura guarda el SHA-256 de cada JSON normalizado en `normalized_snapshots`. Las
capturas se crean primero en una carpeta temporal y se publican mediante rename
atómico; una carpeta existente no se sobreescribe. Los catálogos originales y
capturas previas permanecen intactos. No se agregan snapshots masivos al
repositorio Git.

## Preflight de los pilotos

Inspección offline realizada en TEAM-01B:

- **Racing de Ferrol, Grupo I, `team_id=48`, captura
  `20261011T123240.190812Z-8f307d1c`:** completa bajo la política actual; seis
  vistas, cuatro estados, JSON normalizados coherentes y validación semántica
  versión 1. El preflight no programa nuevas visitas para este equipo.
- **Jaén, Grupo II, `team_id=49`, captura
  `team01a-group2-49-source-evidence`:** válida para su alcance original y
  reutilizable como semilla; en origen contiene las seis vistas y el estado
  `p`, pero no `t`, `go`, `tot` ni `normalized/player_match_metrics.json`. Ese
  preflight histórico precede a TEAM-02C1: las tres vistas se derivaron luego
  offline de las matrices embebidas, en la captura
  `20261012T120720.895650Z-8c75b830`. No se hizo una visita adicional a
  BDFutbol y la captura fuente continúa inmutable.

Una clasificación `complete` no exige que haya goles, tarjetas u otros eventos
positivos. Se valida que los archivos y sus relaciones sean íntegros, no que
cada categoría contenga registros.

## Comandos de preflight y adquisición futura

Primero hacer un piloto seco de un equipo:

```bash
PYTHONPATH=src .venv/bin/python scripts/acquire_bdfutbol_team_batch.py \
  --season 2026-27 --groups I --team-id 48 --limit 1 --dry-run \
  --output-root /srv/football-data-hub/team-captures
```

Para una adquisición autorizada, quitar `--dry-run`. Los comandos para el lote
completo, una vez aprobado y con Brave/Pure CDP, Xvfb, almacenamiento y perfil
configurados en el host, son:

```bash
# Grupo I
PYTHONPATH=src xvfb-run -a -s '-screen 0 1920x1080x24' \
  .venv/bin/python scripts/acquire_bdfutbol_team_batch.py \
  --season 2026-27 --groups I \
  --output-root /srv/football-data-hub/team-captures \
  --profile "$HOME/.football-data-hub-team-profile"

# Grupo II
PYTHONPATH=src xvfb-run -a -s '-screen 0 1920x1080x24' \
  .venv/bin/python scripts/acquire_bdfutbol_team_batch.py \
  --season 2026-27 --groups II \
  --output-root /srv/football-data-hub/team-captures \
  --profile "$HOME/.football-data-hub-team-profile"

# Ambos grupos
PYTHONPATH=src xvfb-run -a -s '-screen 0 1920x1080x24' \
  .venv/bin/python scripts/acquire_bdfutbol_team_batch.py \
  --season 2026-27 --groups both \
  --output-root /srv/football-data-hub/team-captures \
  --profile "$HOME/.football-data-hub-team-profile"
```

Los comandos son una preparación reproducible, no evidencia de que el lote se
haya ejecutado. Antes de usar el servidor, sus catálogos y perfil deben estar
disponibles y un piloto real debe confirmar el entorno de adquisición.
