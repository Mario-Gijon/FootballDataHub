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
  predeterminado es 5 segundos.
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

## Preflight y piloto TEAM-03A (12/10/2026)

El preflight offline con ambos catálogos confirmó 20 equipos por grupo, 40 IDs
únicos y alcance completo. Antes del piloto había 38 equipos pendientes y dos
capturas completas reutilizables: Racing de Ferrol (`48`) y Jaén (`49`). El
plan calculó **228 navegaciones**: seis páginas por cada equipo pendiente. Los
cuatro valores de Seguimiento (`p`, `t`, `go`, `tot`) se seleccionan y
serializan en la misma visita a la página Seguimiento; no añaden cuatro
navegaciones HTTP.

Los dos equipos nuevos elegidos del catálogo fueron UD Logroñés, Grupo I,
`team_id=178`, y Zaragoza, Grupo II, `team_id=39`. La primera ejecución tuvo
HTTP válido en las seis páginas de ambos equipos. Zaragoza se publicó como
captura completa. En Logroñés falló la normalización por dos valores de año
(`2008`, `2007`) en la columna «Fecha de nacimiento» de `#c3p1`; esa ejecución
no publicó una captura parcial. Tras inspeccionar esa estructura real, el
parser conserva `birth_date=null` y registra una advertencia con el valor
original, que sigue disponible en el snapshot comprimido. Se volvió a adquirir
solo Logroñés y la captura completa pasó la revalidación offline.

| Equipo | `capture_id` completo | Vistas | Seguimiento | Resultado resumido |
|---|---|---:|---|---|
| UD Logroñés (I, `178`) | `20261012T160156.898705Z-8b30ebbd` | 6/6 | `p`, `t`, `go`, `tot` | 28 jugadores, 1 entrenador; 17 Altas, 17 Bajas; 6 referencias de partidos. |
| Zaragoza (II, `39`) | `20261012T155605.771164Z-271d43f3` | 6/6 | `p`, `t`, `go`, `tot` | 27 jugadores, 1 entrenador; 18 Altas, 30 Bajas; 6 referencias de partidos. |

Los manifiestos create-only de las dos ejecuciones son:

- `20261012T155712.762396Z-4cf93b8c`: el primer intento registró Logroñés
  fallido por parsing y Zaragoza completo; no hubo denegación ni desafío.
- `20261012T160301.578161Z-a72aca3b`: reanudación dirigida a Logroñés,
  completa después de corregir la fecha parcial.

El dry-run offline posterior validó las cuatro capturas completas (48, 49, 178
y 39), las seis vistas, los cuatro estados, las huellas y la normalización. La
CLI las marca `skip_complete`; quedan 36 equipos y el plan actualizado prevé
216 navegaciones. Esta verificación demuestra la reanudación desde capturas
completas; no se inició el lote restante ni se cambió el índice de publicación
`config/team_profiles_2026-27.json`.

La ejecución se hizo en el Linux local `archlinux` como usuario `mario` con
Chromium 152, SeleniumBase 4.55.2, Xvfb externo y el perfil persistente Pure CDP
del usuario. El servidor UJA no fue el destino de este piloto y su preparación
continúa pendiente de una prueba en ese host.

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

## Persistencia antes del parser y reanudación (TEAM-03B1)

El orquestador guarda cada vista después de validar el acceso (`VALID`, HTTP
200, URL y estructura), antes de ejecutar el parser. El checkpoint se escribe
bajo:

```text
<root>/<season>/<team_id>/diagnostics/<capture_id>/
```

`metadata/evidence.json` registra identidad, grupo, temporada, catálogo, URLs,
título, estado HTTP, hora, navegador y SHA-256. Cada HTML se comprime de forma
determinista y se publica mediante escritura temporal, `fsync` y `replace`.
Seguimiento se conserva por estado con la misma política. Desafíos, respuestas
403/429 y documentos inválidos no se guardan como snapshots. Si falla el parser
o la validación local, el checkpoint queda como `parse_failed` o `local_error`;
no se crea una captura `complete` ni puede seleccionarla FastAPI.

Al reanudar, la CLI verifica identidad, URLs y hashes; planifica únicamente las
vistas y estados sin evidencia íntegra. Si todas las páginas ya están, vuelve a
parsear offline. Cuando la captura normalizada se publica atómicamente, el
checkpoint temporal se elimina, porque sus bytes ya están conservados en la
captura completa. Las capturas publicadas anteriores son inmutables.

Las referencias de Partidos y Seguimiento se validan por `match_id` exacto
contra los 380 registros del catálogo del grupo. Un ID ausente produce una
condición `stale_match_catalog` que detiene el bloque; no hay reconciliación por
nombre o marcador y no se edita el catálogo desde esta CLI. Los catálogos
actuales fueron capturados el 10/10/2026. Antes de adquirir nuevas fichas tras
cambios de calendario habrá que actualizar y validar los datasets de
competición en una fase autorizada independiente.

## Almacenamiento externo y despliegue UJA

`--output-root` acepta rutas absolutas o relativas y se puede configurar con
`FDH_TEAM_CAPTURE_ROOT`; `FDH_BDFUTBOL_GROUP1_MATCHES` y
`FDH_BDFUTBOL_GROUP2_MATCHES` apuntan a los catálogos. `FDH_BDFUTBOL_PROFILE`
configura el perfil local del navegador. El servidor debe usar su propio perfil
persistente y almacenamiento, nunca una ruta del usuario de desarrollo.
Una adquisición real se niega si `--output-root` resuelve dentro del checkout;
la excepción explícita `--allow-repository-storage` se reserva para pruebas
locales controladas. `--dry-run` sí puede inspeccionar el root del repositorio.

Para migrar a un volumen del servidor:

1. Copiar catálogos y capturas completas preservando bytes y permisos; comparar
   los SHA-256 de manifiestos antes y después.
2. Configurar `FDH_TEAM_CAPTURE_ROOT` a un directorio persistente fuera del
   checkout, conceder acceso de lectura/escritura al usuario del servicio y
   confirmar el espacio libre.
3. Ejecutar el `--dry-run` contra esa raíz; verificar que el plan reutiliza las
   cuatro capturas completas sin visitas y que no propone más de cinco equipos.
4. Hacer un piloto de hasta cinco equipos, con `--pause-seconds 5` y sin
   paralelismo. Detener el lote ante desafío, denegación o catálogo desactualizado.
5. Validar offline manifiestos, hashes y normalización; publicar al índice de la
   aplicación en una operación posterior e independiente.

En Git hay actualmente snapshots piloto bajo seguimiento. Los siguientes lotes
deben dirigirse al volumen externo y añadirse a una política de exclusión de
artefactos antes de adquirir más equipos; no se deben borrar ni reescribir los
pilotos existentes. Los manifiestos y hashes deben quedar en el volumen
persistente y en copias de seguridad versionadas fuera del checkout.

El piloto TEAM-03A fue local y no acredita disponibilidad de la UJA. La ruta
`/srv/football-data-hub/team-captures` no está creada en la máquina de
desarrollo y el usuario `mario` no tiene permiso de escritura en `/srv`. La
ejecución de un bloque en este host no se considera sustituto del piloto UJA.

### Preflight TEAM-03B1 (13/10/2026)

La CLI actual, sin navegador, volvió a inspeccionar los 40 clubes y confirmó:

- Capturas completas y reutilizables: UD Logroñés (I, 178), Racing de Ferrol
  (I, 48), Zaragoza (II, 39) y Jaén (II, 49); las seis vistas y los estados
  `p`, `t`, `go`, `tot` están íntegros en las cuatro.
- Pendientes: 36; plan actual: 216 navegaciones, seis por club.
- Los catálogos contienen 380 partidos cada uno. Grupo I fue capturado
  `2026-10-10T20:25:00Z`; Grupo II, `2026-10-10T10:26:56Z`. Las cuatro fichas
  completas existentes se revalidan contra sus IDs y no contienen referencias
  desconocidas. Las páginas nuevas aún no se han contrastado; si introducen un
  ID ausente, el bloque se detendrá con `stale_match_catalog`.
- El root local está legible/escribible, con aproximadamente 9.3 GiB libres,
  pero está dentro del checkout. En el checkout hay 87 archivos raw de equipo
  bajo seguimiento Git, aproximadamente 24 MiB. No se añadieron ni migraron
  snapshots en este hito.

El candidato de primer bloque, obtenido del catálogo validado, sería:

| Grupo | `team_id` | Equipo | Vistas a visitar |
|---|---:|---|---:|
| I | 76 | Lugo | 6 |
| I | 72 | Bilbao Athletic | 6 |
| I | 149 | Cacereño | 6 |
| II | 94 | Villarreal B | 6 |
| II | 107 | Alcorcón | 6 |

Son 30 navegaciones previstas; cada selección de los cuatro estados de
Seguimiento ocurre en la vista ya abierta. Solo se ejecutó su dry-run. En esta
sesión no se ha confirmado que el host remoto `torre` sea un servidor UJA; la
resolución local de SSH tampoco fue posible por un error de permisos en
`/etc/ssh/ssh_config.d/20-omarchy-keepalive.conf`. Por eso no se trasladó ni se
ejecutó el bloque en la máquina de desarrollo.

El host local tiene Chromium 152, SeleniumBase 4.55.2, `xvfb-run` y el perfil
Pure CDP de `mario` con permisos `0700` (66 MiB). Esto acredita solamente el
entorno local; no acredita la configuración, acceso ni almacenamiento del
servidor UJA.

La verificación automática final del código TEAM-03B1 terminó con 253 tests
pasando en 462.85 s, Ruff, compilación Python y `git diff --check` correctos.
No se modificó el índice `config/team_profiles_2026-27.json`.
