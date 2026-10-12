# Semántica de fichas de equipo de BDFutbol

## Alcance y evidencia

Exploración de las fichas de Primera Federación 2026/27 mediante SeleniumBase
Pure CDP, Chromium y Xvfb, el 11/10/2026. Las URLs se resolvieron desde los
catálogos `teams` ya publicados en `normalized/matches.json`:

| Grupo | `team_id` | Catálogo | Nombre del catálogo | URL publicada | HTTP | Resultado |
|---|---:|---|---|---|---:|---|
| II | 49 | `data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json` | Jaén | <https://www.bdfutbol.com/es/t/t2026-2749.html> | 200 | Ficha válida; HTTP, título, URL y contenido semántico coherentes. |
| I | 48 | `data/exports/bdfutbol/group1_classification/20261010T202500.293648Z-b770724f/normalized/matches.json` | Racing de Ferrol | <https://www.bdfutbol.com/es/t/t2026-2748.html> | 200 | Ficha válida; estructura compatible con Grupo II. |

No apareció desafío ni denegación. La primera ejecución no llegó al sitio: el
sandbox bloqueó la creación del socket local de CDP. La prueba autorizada con
los permisos de navegador necesarios sí abrió las páginas. El perfil utilizado
fue temporal y separado del perfil persistente de Brave.

El inventario de identidades consta de 40 `team_id` únicos, 20 por grupo, sin
colisiones entre los dos catálogos. La fuente de verdad sigue siendo cada
`matches.json`; no se han inventado IDs ni copiado el catálogo a un dataset
de producción. Los IDs existentes son:

- Grupo I: `48, 58, 62, 72, 76, 81, 84, 87, 88, 95, 99, 104, 145, 149, 178, 359, 411, 473, 510, 515`.
- Grupo II: `17, 18, 39, 40, 49, 55, 61, 67, 79, 89, 94, 107, 119, 140, 176, 204, 227, 414, 482, 488`.

## Identidad, temporada y competición

La identidad estable es la del catálogo: `team_id`, nombre, `team_url` y
`crest_url`. El ID de la ficha se puede comprobar con el enlace de equipo, pero
no reemplaza ni corrige el catálogo. En los dos pilotos la temporada visible y
la URL corresponden a `2026-27`; las fichas tienen un selector de muchas
temporadas históricas. El extractor debe seleccionar exclusivamente la opción
2026/27 indicada por BDFutbol y no recorrer otras temporadas.

La competición visible para estos pilotos es `Liga` (selector `#comp`, valor
`lig`). Los metadatos de grupo y competición proceden del catálogo elegido. No
se combinarán estadísticas de otras competiciones.

## Vistas y controles observados

Las pestañas principales son enlaces de navegación a documentos distintos:

| Vista | Enlace observado | Estructura/fuente | Estado |
|---|---|---|---|
| Plantilla / Alineación | URL base del catálogo | `#plantilles`, `#taulaentrenadors`, `#taulaplantilla`, gráfico en `#alineacio` | Adquirida para Jaén y Racing de Ferrol. |
| Plantilla / Plantilla | opción del selector de vista, `t=plantilla` | `#c3p1`; incluye fecha y lugar de nacimiento | Adquirida para Jaén y Racing. |
| Plantilla / Estadísticas | opción del selector de vista, `t=lista` | `#c3p0`, `#taulaentrenadors` | Adquirida para Jaén y Racing de Ferrol; ambas respondieron HTTP 200. |
| Seguimiento | enlace `t=seg` | `#taula-seguiment`; las celdas y matrices JavaScript enlazan por `player_id`, jornada y `match_id` | Adquirida para ambos pilotos; los cuatro estados se probaron en Racing. |
| Traspasos | enlace `t=altas` | raíz `#pestaltesbaixes`; una tabla compartida con separador `Bajas` y cabeceras de equipo origen/destino | HTML real inspeccionado en ambos pilotos. Jaén: 14 Altas y 20 Bajas; Racing: 15 Altas y 15 Bajas. |
| Partidos | enlace `tab=partits` | `#taula-resultats-plantilla` | Adquirida para ambos. Los seis partidos disputados de cada piloto enlazan por ID con el dataset existente; los próximos encuentros no exponen ID estable en esas filas. |
| Clasificación | enlace al URL de la competición del grupo | `#classific` es una lista de escudos/equipos; la pestaña enlaza a la clasificación de grupo | No se normaliza como otra clasificación. Reutilizar clasificación existente. |

El selector de vista de Plantilla contiene `Alineación`, `Plantilla` y
`Estadísticas`; sus valores se extraen del HTML, no se forman a partir de
suposiciones. El selector de temporada contiene temporadas históricas, pero
solo la opción de temporada actual está dentro del alcance. En la vista de
alineación, `dem` ofrece `-`, `por` (Portero), `def` (Defensa), `mig`
(Centrocampista) y `dav` (Delantero); `pais` ofrece `-` y códigos de países. Se
observó que son filtros de la tabla, pero no se verificó aquí su interacción;
no se guardan como filtros aplicados.

En Seguimiento, `#vista_jornades` publica `p` Partidos, `t` Tarjetas, `go`
Goles y `tot` Todo. Las cuatro opciones se seleccionaron en la misma página de
Racing. La URL y el número de filas se mantuvieron (26, incluida cabecera); las
clases y los valores de las celdas cambiaron. No se inició otra navegación ni
se observó una petición de datos deportivos a BDFutbol. Durante el intervalo
de `go` apareció una llamada de telemetría de Google Analytics que incluía la
URL de la página; no contiene los registros del partido. El HTML inicial ya
incluye las matrices JavaScript `JSEG`, `JSEGC`, `JSEGG`, `JSEGID` y el resumen
`json_data`, de modo que el navegador no necesita descargar una fuente
deportiva al cambiar el control. `#comp` ofreció Liga (`lig`).

La tabla Seguimiento de ambos pilotos incluye seis jornadas disputadas en el
momento de la captura; cada encabezado aporta el número de jornada y cada celda
de partido enlaza a `p.php?id=...`. En `p`, el número visible y `JSEG` son
minutos jugados; una celda en blanco se conserva como `null`. En `t`, el número
sigue siendo el minuto, no el número de tarjetas: la marca de tarjeta procede
de `JSEGC` y de las clases de la celda. Se observaron 10 marcas `tg1` en
Racing, y su suma por jugador coincide con las 10 tarjetas amarillas de
Estadísticas. En este piloto no aparecieron `tg2` ni `tv`; su interpretación
como segunda amarilla/roja queda pendiente de una observación positiva.

En `go`, `JSEGG` y las celdas muestran el número de goles del jugador en ese
partido; se observaron 7 goles y la suma coincide con Estadísticas. Un valor
vacío no se convierte en cero ni crea un registro de evento. En `tot`, los
minutos permanecen y se combinan con marcadores de gol y tarjeta; las marcas
de goles y amarillas coinciden con `go` y `t`, respectivamente. No aporta una
métrica numérica exclusiva en estos datos, por lo que no se duplican registros
desde ese estado.

## Campos semánticos

### Equipo y participación de temporada

- `TeamIdentity.team_id`: entero BDFutbol tomado del catálogo.
- `name`, `team_url`, `crest_url`: valores del mismo registro del catálogo;
  la URL del escudo se guarda sin descargar la imagen.
- `TeamSeason`: contexto de `team_id`, temporada, competición y grupo.
- Entrenadores: enlace `/l/l<ID>.html` proporciona el ID; el enlace a imagen
  `/i/lm/...` proporciona la URL de foto. Se publican nombre visible y nombre
  completo. La alineación informa Edad, jornadas, partidos, TA y TR. La vista
  Plantilla del piloto informa fecha de nacimiento, lugar y provincia. Puede
  haber varios entrenadores en una temporada: no se presupone una sola fila.
- `Partidos: 6 (50% ganados)` es un rótulo de la ficha y no reemplaza las
  estadísticas colectivas ya derivadas de Resultados.

### Jugadores y relación equipo-temporada

El ID se extrae del enlace `/j/j<ID>.html`; el nombre visible y el completo se
leen de los spans del enlace cuando existen. La foto es la URL de `/i/m/...` y
no se descarga. Se deduplican personas por `player_id`; la pertenencia se
almacena aparte como `PlayerTeamMembership(player_id, team_id, season,
competition, group, jersey_number, squad_group)`.

La vista Alineación contiene encabezados publicados `Titulares` y `Suplentes`.
Se preserva ese texto de origen como agrupación de la plantilla; no significa
que sean titulares/suplentes de un partido concreto. La fuente advierte que el
campo táctico se genera automáticamente desde las posiciones y es aproximado,
no una táctica verificada. El extractor no convierte las coordenadas de esa
visualización en una alineación de partido.

La leyenda permite validar estos indicadores: `dot-superior1` = ha jugado en
Primera División; `dot-superior2` = ha jugado en Segunda División;
`dot-internacionals` = internacional en categorías inferiores; `dot-alta` =
nueva incorporación. Se guardan solo los indicadores cuya clase se pudo
relacionar con esta leyenda. El código numérico de `Pos` tiene título
`Demarcación`, pero no se encontró una tabla oficial de conversión del código
numérico; se conserva como `source_position_code` sin asignarle un nombre.
Los selectores de demarcación y país no bastan para confirmar la conversión
del código numérico ni el país de cada bandera.

La vista Plantilla ofrece fecha de nacimiento, lugar y provincia; la vista
Alineación publica edad. La edad se conserva tal como la publica la fuente, sin
recalcularla desde la fecha. Banderas sin etiqueta textual conservan, como
mucho, su URL de imagen; no se infiere una nacionalidad a partir del nombre del
archivo.

### Estadísticas de jugador y abreviaturas

Los `title` de encabezado y `data-colid` proporcionan los siguientes
significados. Los nombres de salida normalizados usan conceptos en inglés;
se preserva el código de origen en la evidencia.

| `data-colid` | Cabecera | Significado validado | Unidad/tipo |
|---|---|---|---|
| `dor` | `#` | Dorsal | entero nullable |
| `fot` | — | URL de fotografía | URL nullable |
| `pais` | — | Indicador gráfico de país; sin etiqueta legible confirmada | URL/raw nullable |
| `nom` | Apodo / Apodo y Nombre | Nombre publicado; link aporta `player_id` | texto/URL |
| `dem` / `pos` | Pos | Demarcación en código numérico de origen | texto nullable, sin mapa validado |
| `edat` | Edad | Edad publicada por la fuente | años, entero nullable |
| `pj` | PJ | Partidos jugados | partidos, entero nullable |
| `pt` | PT | Partidos como titular | partidos, entero nullable |
| `pc` | PC | Partidos completos | partidos, entero nullable |
| `ps` | PS | Partidos como suplente | partidos, entero nullable |
| `px` | PX | Partidos sustituido | partidos, entero nullable |
| `pconv` / `c` | C | Convocado sin jugar | partidos, entero nullable |
| `min` | Min | Minutos jugados | minutos, entero nullable |
| `tg` | TA | Tarjetas amarillas | tarjetas, entero nullable |
| `tv` | TR | Tarjetas rojas | tarjetas, entero nullable |
| `g` | G | Goles | goles, entero nullable |
| `gm` | Minutos/G | Minutos por gol | minutos por gol, entero nullable |
| `gy` | GP | Goles de penalti | goles, entero nullable |
| `gp` | GPP | Goles en propia puerta | goles, entero nullable |
| `ge` | GE | Goles encajados | goles, entero nullable |
| `pg` | PG | Partidos ganados | partidos, entero nullable |
| `pe` | PE | Partidos empatados | partidos, entero nullable |
| `pp` | PP | Partidos perdidos | partidos, entero nullable |

Los títulos completos son, por ejemplo, `Partidos titular`, `Partidos
completos`, `Partidos suplente`, `Partidos sustituido`, `Convocado (sin jugar)`,
`Goles penalty`, `Goles propia puerta` y `Goles encajados`; no se deducen de
las siglas. En la vista Estadísticas algunos encabezados carecen de
`data-colid`, pero el `title` y la posición de columna documentan los campos.
La vista Estadísticas fue compatible en ambos grupos. La tabla de Jaén contiene
25 filas de jugadores y una fila agregada final sin enlace de jugador. El
parser identifica solo personas por `player_id` y no convierte ese total en
una entidad deportiva.

La tabla compacta de Alineación repite abreviaturas, pero no se usa como fuente
normalizada de estadísticas: en el piloto, el portero Morillas mostraba `-5`
bajo `G`, mientras que `#c3p0` publicaba `G=0` y `GE=5`. El valor `-5` no se
interpreta ni se fuerza a coincidir con `Goles`; su significado en esa vista
queda pendiente. Estadísticas se toma exclusivamente de la vista completa con
encabezados y títulos verificables.

En celdas numéricas, un número explícito `0` es cero. Guion o celda vacía son
`null`. Esto se observa especialmente comparando Alineación (muestra guiones
para estadísticas sin valor) con Estadísticas (muestra ceros en algunos de
esos casos). No se convierte un ausente en cero.

## Seguimiento, traspasos y datos ya existentes

- Seguimiento aporta minutos por jugador y partido en `p`, marcas de
  amonestación en `t`, goles por jugador-partido en `go`, y una combinación en
  `tot`. El ID de la celda se enlaza por `match_id`, no por el nombre del
  rival. Las tarjetas amarillas observadas se normalizan como
  `yellow_cards=1` solo cuando `JSEGC`/DOM contiene `tg1`; el texto numérico de
  `t` es tiempo jugado. Los goles se toman de `JSEGG`/el número de `go` y se
  conservan solo cuando la fuente publica un valor numérico. Los marcadores
  `tg2` y `tv` quedan pendientes de validación positiva.
- La inspección de las capturas originales corrigió un error semántico del
  parser: cada ficha presenta **una tabla compartida**, no dos tablas hermana.
  `Altas` aparece antes de la tabla; dentro de ella una fila con el encabezado
  `Bajas` separa la segunda sección. La primera cabecera acaba en `Equipo
  origen`; después del separador, la nueva cabecera acaba en `Equipo destino`.
  Los datos de origen confirman Jaén (`team_id=49`): 14 altas y 20 bajas;
  Racing de Ferrol (`team_id=48`): 15 altas y 15 bajas. Una fila se asigna a
  una sección solo después de reconocer esa cabecera explícita. El parser
  rechaza cabeceras, filas o cantidad de tablas desconocidas en vez de
  asignarlas por defecto a Altas.
- Cada dirección se exporta con `source_heading`, dirección, cantidad y estado
  `verified_with_rows` o `verified_empty`. La falta del contenedor, de uno de
  los encabezados o de su cabecera de equipo es un error de parsing, no una
  sección vacía. El estado vacío solo se emite cuando el encabezado y la
  columna `Equipo origen`/`Equipo destino` están presentes y se han comprobado
  todas las filas del bloque.
- Los enlaces de jugadores preservan su `player_id`, nombre visible y completo,
  URL y foto de origen. El enlace del otro club conserva nombre, ID y URL tal
  como aparecen en la captura; los ejemplos incluyen fichas históricas 2025/26
  para Altas y URLs 2026/27 para Bajas. No se reinterpretan como fichas
  actuales del dashboard. Algunas filas de Bajas carecen de club de destino;
  se mantiene `null` en nombre, ID y URL. No se observaron importes ni fechas,
  por lo que `fee` y `transfer_date` siguen como `null`.
- Partidos presenta fecha, competición, jornada/tipo, local, marcador,
  visitante y estadio. Seis filas disputadas enlazaron por `match_id` con los
  datos ya capturados. La tabla incluyó 38 jornadas, pero las filas futuras no
  tenían ID estable de partido en el enlace observado. No se exportan otra vez
  los fixtures, marcadores, árbitros o estadios de Resultados.
- Clasificación enlaza a la competición del grupo. El widget `#classific` de
  esta ficha lista escudos/equipos, pero no es una segunda tabla de estadísticas
  de clasificación. No se duplica.
- Destacados es una lista parcial. La unión se efectúa por `player_id`; que un
  jugador no aparezca allí no invalida una pertenencia de plantilla.
- Las estadísticas agregadas de jugador se contrastan con los partidos
  capturados solo cuando equipo, competición y temporada coinciden. Las
  discrepancias se conservan en validación; no se corrigen en los valores de
  BDFutbol.

## Resultados de los pilotos y limitaciones

Ambas fichas Alineación publicaron la misma estructura principal, `#taulaentrenadors`
y `#taulaplantilla`; las dos tienen 25 registros en la tabla de plantilla y un
entrenador en la captura. Jaén también tiene 25 enlaces a jugadores en
Estadísticas, además de una fila agregada sin ID al final. La vista Plantilla
contiene los mismos 25 IDs. El parser une vistas por ID y no exige una cantidad
fija de jugadores; si una vista futura aporta IDs adicionales, los conservará
al unirla.

Racing de Ferrol se eligió desde el catálogo del Grupo I como segundo piloto
con identidad distinta a Jaén y para comprobar que un único parser sirve en
ambos grupos. Las seis vistas fueron válidas: 25 jugadores y 25 estadísticas,
un entrenador, 150 celdas de minutos, 17 métricas positivas del Seguimiento
(10 amarillas y 7 goles), 30 traspasos (15 altas y 15 bajas) y seis referencias a partidos. Las
cuatro vistas pendientes se adquirieron mediante la CLI en una sesión Pure
CDP; se reutilizaron Alineación y Estadísticas del snapshot anterior y el
manifiesto conserva su captura de origen y las horas por vista.

La página tiene elementos de comentarios, fotos de comunidad y consentimiento
de publicidad que no forman parte del dominio de equipo. No se almacenan ni se
raspan perfiles individuales. La fecha global de actualización que aparece en
el footer del sitio no se trata como fecha de actualización específica de la
ficha.

## Estado de exploración

| Capacidad | Exploración | Normalización en TEAM-01A | Validación |
|---|---|---|---|
| Identidad, grupo y temporada 2026/27 | Verificada en dos fichas reales | Catálogo existente, ID y URL sin reconstruir | 2 fichas HTTP 200; no desafíos |
| Alineación, entrenador, jugadores y estadísticas básicas | Verificada en dos fichas | Incluida | Mismo parser; IDs reales |
| Plantilla completa con nacimiento | Verificada en ambos grupos | Incluida cuando la vista está disponible | IDs cruzados en ambos |
| Estadísticas individuales extendidas | Verificada en ambos grupos | Incluida | Encabezados semánticos de origen; checks con partidos |
| Seguimiento de minutos por partido | Verificado en ambos pilotos | Incluido | `player_id`, `match_id`, minutos; ausencias permanecen `null` |
| Seguimiento Tarjetas/Goles/Todo | Probado en el mismo documento Racing | Amarillas `tg1` y goles normalizados; Todo es combinación | 10 TA y 7 goles coinciden con Estadísticas; `tg2`/`tv` pendientes |
| Altas y Bajas | Verificadas en los HTML originales de ambos equipos | Jaén: 14/20; Racing: 15/15 | Separador y columna origen/destino verificados; ausencias marcadas explícitamente |
| Partidos y clasificación de equipo | Vistas reales exploradas; IDs cruzados | Solo referencias/validación | No duplican datasets de competición |
| Parser compartido de las seis vistas en Grupo I y II | Verificado con ambos pilotos | Incluido | Relaciones por ID |

## Extractor y capturas TEAM-01A

El paquete `football_data_hub.providers.bdfutbol.teams` contiene modelos
independientes, parser offline, lectura del catálogo, adquisición con
`BDFutbolAccess`/`BrowserSessionManager`, validación y exportación JSON
inmutable. La URL de cada vista se resuelve desde los enlaces y opciones reales
del HTML base. La adquisición se limita a un equipo y se detiene en la primera
denegación o contenido inválido; no reintenta ni resuelve desafíos.

Las capturas reales normalizadas de los pilotos están bajo:

- Jaén, Grupo II, `team_id=49`:
  `data/exports/bdfutbol/teams/2026-27/49/team01a-group2-49-source-evidence/`.
  Se guardaron Alineación, Plantilla, Estadísticas, Seguimiento, Traspasos y
  Partidos; 25 personas, un entrenador, 25 estadísticas, 150 celdas de minutos,
  14 altas, 20 bajas y seis referencias a partidos disputados.
- Racing de Ferrol, Grupo I, `team_id=48`:
  - `data/exports/bdfutbol/teams/2026-27/48/team01a-group1-48-source-evidence/`
    conserva la captura previa de Alineación y Estadísticas.
  - `data/exports/bdfutbol/teams/2026-27/48/20261011T121730.599917Z-f3f61e3d/`
    es la salida de la CLI real: adquirió Plantilla, Seguimiento, Traspasos y
    Partidos, reutilizó Alineación y Estadísticas, y guardó las cuatro variantes
    de Seguimiento.
  - `data/exports/bdfutbol/teams/2026-27/48/20261011T123240.190812Z-8f307d1c/`
    vuelve a normalizar offline esa evidencia con el parser semántico ampliado
    y referencia el run de origen. Los snapshots de ambos runs usan gzip
    reproducible y conservan el SHA-256 del HTML descomprimido.
- El inventario versionado de los 40 clubes está en
  `data/exports/bdfutbol/teams/2026-27/catalog/20261011T115607.387269Z-f86d8190/`.
  Deriva de los dos catálogos existentes; no crea IDs ni modifica esos catálogos.

Cada captura conserva contenido de origen por vista, URL, evaluación de acceso,
fecha de adquisición, SHA-256 del HTML descomprimido, catálogos de origen,
datos normalizados y validación. Seguimiento conserva las cuatro variantes
DOM, los valores de control confirmados, hashes y deltas de recursos. Las horas
de Alineación y Estadísticas reutilizadas siguen siendo las de su captura
original y no se presentan como si pertenecieran a la sesión nueva.

### Actualización offline de Seguimiento de Jaén (TEAM-02C1)

La captura fuente `team01a-group2-49-source-evidence` contenía las matrices
JavaScript `JSEG`, `JSEGC`, `JSEGG` y `JSEGID`, además de la vista `p`. El
12-10-2026 se derivaron localmente desde ese snapshot las vistas `t`, `go` y
`tot`, sin abrir el navegador ni visitar BDFutbol. El resultado inmutable es
`data/exports/bdfutbol/teams/2026-27/49/20261012T120720.895650Z-8c75b830/`.

Las seis jornadas tienen un partido enlazado por ID. Las matrices reproducen
25 filas de jugadores y 150 celdas de minutos; los eventos suman 15 amarillas
(`tg1`/`tg2`), 2 rojas (`tv`) y 8 goles. Para cada jugador, amarillas, rojas y
goles concuerdan con sus estadísticas extendidas del mismo snapshot; los
match IDs y jornadas también coinciden con el catálogo del Grupo II. Los
estados derivados están marcados `DERIVED_OFFLINE`, conservan la hora original
de captura fuente y añaden su propia hora `derived_at_utc`. No se cambia ni se
reescribe la captura fuente. Esta derivación valida esos datos históricos y no
demuestra que una futura captura BDFutbol vaya a exponer exactamente las mismas
matrices.

Para normalizar snapshots autorizados sin abrir un navegador:

```bash
PYTHONPATH=src .venv/bin/python scripts/acquire_bdfutbol_team.py \
  --season 2026-27 --group 2 --team-id 49 --views all \
  --snapshot-dir /ruta/a/snapshots-jaen

PYTHONPATH=src .venv/bin/python scripts/acquire_bdfutbol_team.py \
  --season 2026-27 --group 1 --team-id 48 --views core \
  --snapshot-dir /ruta/a/snapshots-racing
```

Los snapshots planos antiguos siguen admitidos. Las capturas exportadas por la
CLI usan `metadata/capture.json` y rutas con gzip; la normalización verifica
hashes, URLs y HTTP antes de parsear. `core` captura Alineación y Estadísticas;
`all` añade Plantilla, Seguimiento, Traspasos y Partidos.

Para una adquisición normal de un solo equipo con Pure CDP, Xvfb y un perfil
aislado o persistente configurado:

```bash
PYTHONPATH=src .venv/bin/python scripts/acquire_bdfutbol_team.py \
  --season 2026-27 --group 2 --team-id 49 --views all \
  --profile "$HOME/.football-data-hub-team-profile" \
  --output-root data/exports/bdfutbol/teams
```

El catálogo se carga desde `normalized/matches.json`; se puede reemplazar con
`--team-catalog` o las variables `FDH_BDFUTBOL_GROUP1_MATCHES` y
`FDH_BDFUTBOL_GROUP2_MATCHES` (también se aceptan los alias `FDH_GROUP1_MATCHES`
y `FDH_GROUP2_MATCHES`).
No se construye la URL a partir del nombre ni del ID. Para producir el
inventario de 40 IDs desde los catálogos ya existentes:

```bash
PYTHONPATH=src .venv/bin/python scripts/acquire_bdfutbol_team.py \
  --season 2026-27 --inventory-only \
  --output-root data/exports/bdfutbol/teams
```

Para adquirir solo vistas pendientes, resolver sus URLs desde la Alineación ya
capturada y conservar la procedencia de las vistas reutilizadas:

```bash
PYTHONPATH=src xvfb-run -a -s '-screen 0 1920x1080x24' \
  .venv/bin/python scripts/acquire_bdfutbol_team.py \
  --season 2026-27 --group 1 --team-id 48 \
  --reuse-capture data/exports/bdfutbol/teams/2026-27/48/team01a-group1-48-source-evidence \
  --view squad --view follow --view transfers --view matches \
  --output-root data/exports/bdfutbol/teams
```

Para volver a normalizar una captura sin navegador y publicar un run derivado
inmutable con una referencia a la captura de origen:

```bash
PYTHONPATH=src .venv/bin/python scripts/acquire_bdfutbol_team.py \
  --season 2026-27 --group 1 --team-id 48 \
  --snapshot-dir /ruta/a/captura --derived-capture \
  --output-root /ruta/a/exports
```

La suite offline comprueba los dos pilotos, transiciones, métricas observadas,
nulos, relaciones por ID, referencias a resultados, hashes, compresión gzip y
lectura posterior de JSON. No descarga imágenes, perfiles individuales ni
temporadas históricas, y no copia partidos a los exports de equipo. La
adquisición por lotes, sus estados y política de reanudación están en
[`docs/team_batch_acquisition.md`](team_batch_acquisition.md).

## Corrección TEAM-02D y capturas derivadas

La revisión de los HTML originales confirmó que el parser anterior seguía el
`h2` Altas hasta la tabla compartida, por lo que absorbía también las filas
posteriores a la fila separadora `Bajas`. La corrección recorre la tabla como
una secuencia de secciones y exige, para cada bloque, la cabecera de relación
correspondiente. La cabecera `Equipo destino` respalda Bajas; una estructura
desconocida o una fila no interpretable detiene el parseo. `TeamTransferSection`
conserva el estado `verified_with_rows`/`verified_empty` y el recuento, de modo
que una sección no inspeccionada nunca se presenta como vacía.

Resultados contrastados directamente con las filas de los snapshots guardados:

| Equipo | Altas / origen | Bajas / destino | Ejemplos contrastados |
|---|---:|---:|---|
| Jaén (`49`, Grupo II) | 14 | 20 | Álex Pérez (`304042`) llega desde Atlético Baleares, URL original `t2025-26130.html`; Curro (`307847`) sale hacia Getafe; Rabanillo (`22537`) aparece en Bajas sin equipo publicado. |
| Racing de Ferrol (`48`, Grupo I) | 15 | 15 | Monjonell (`15141`) llega desde UD Ibiza, URL original `t2025-26414.html`; Parera (`23024`) sale hacia Cultural Leonesa. |

Los datos se regeneraron sin navegación y sin modificar las capturas originales.
Los nuevos exports versionados son:

- Jaén: `20261012T131457.209360Z-602005d8`; `normalized/transfers.json`
  SHA-256 `16eff7297249f383bef0b224832af8be50cad1613024e9f4c41b275c31b06547`.
- Racing: `20261012T131518.543469Z-43ff1122`; `normalized/transfers.json`
  SHA-256 `060cb05f34b203439a2621fc73f515effb8273b4b390c24670514faf0ea06625`.

En ambos manifests `captured_at_utc` conserva la captura fuente del 11/10/2026;
`derivation.derived_at_utc` registra la nueva normalización offline del
12/10/2026. El índice explícito de perfiles fija los dos nuevos `capture_id`,
las huellas de los snapshots original y normalizado, los grupos, y los estados
de Altas/Bajas. También se actualizaron las huellas de Plantilla y Seguimiento
al seleccionar las nuevas capturas. Jaén conserva sus cuatro estados de
Seguimiento y 22 métricas positivas; Racing conserva los cuatro estados y 17
métricas. `transfer_date` y `fee` permanecen `null`; los enlaces de clubes se
conservan como referencias BDFutbol originales, incluso cuando son históricos.

## Adquisición piloto TEAM-03A (12/10/2026)

Las capturas reales de dos equipos nuevos confirmaron las seis vistas y los
cuatro estados de Seguimiento bajo Pure CDP. El resumen normalizado es:

| Grupo / equipo | `team_id` | `capture_id` | Jugadores | Entrenadores | Minutos jugador/partido | Métricas de eventos | Altas / Bajas | Referencias de partidos |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| I / UD Logroñés | 178 | `20261012T160156.898705Z-8b30ebbd` | 28 | 1 | 168 | 28 | 17 / 17 | 6 |
| II / Zaragoza | 39 | `20261012T155605.771164Z-271d43f3` | 27 | 1 | 162 | 32 | 18 / 30 | 6 |

Las seis vistas devolvieron HTTP 200 y título `Plantilla del <equipo>
2026-27 1ª RFEF | BDFutbol`; la identidad del equipo y la temporada se
validaron contra el catálogo del mismo grupo. Los IDs de partidos se enlazan
por `match_id`; no se exportan copias de Resultados. Cada snapshot y JSON
normalizado conserva SHA-256 y metadatos de procedencia. Las capturas quedaron
completas y reutilizables tras una segunda inspección offline.

La vista Plantilla de UD Logroñés (`#c3p1`) publicó `2008` y `2007` en la
columna con `title="Fecha de nacimiento"`. Son años sin día ni mes: el parser
no los transforma en fechas. `birth_date` queda `null`, y la validación agrega
una advertencia con el valor fuente; el HTML original comprimido preserva la
evidencia. Una cadena no reconocible que no sea un año aislado sigue siendo un
error de parsing. Esta diferencia se cubre con una regresión offline en
`tests/test_bdfutbol_team_profiles.py`.
