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
| Plantilla / Plantilla | opción del selector de vista, `t=plantilla` | `#c3p1` y `#taulaentrenadors`; incluye fecha y lugar de nacimiento | Adquirida para Jaén. En Racing se confirmó la opción en el HTML inicial, pero no se adquirió esta variante. |
| Plantilla / Estadísticas | opción del selector de vista, `t=lista` | `#c3p0`, `#taulaentrenadors` | Adquirida para Jaén y Racing de Ferrol; ambas respondieron HTTP 200. |
| Seguimiento | enlace `t=seg` | `#taula-seguiment`, IDs de partidos en las celdas y variable `JSEGID` | Adquirida para Jaén. |
| Traspasos | enlace `t=altas` | bloques titulados `Altas` y `Bajas`, tabla bajo `Altas` en el piloto | Adquirida para Jaén. El bloque `Bajas` no tenía registros visibles. |
| Partidos | enlace `tab=partits` | `#taula-resultats-plantilla` | Adquirida para Jaén. Los seis partidos disputados enlazan por ID con el dataset existente; los próximos encuentros no exponen ID de partido en esas filas. |
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
Goles y `tot` Todo. Se probaron sobre el mismo documento: la URL permaneció
estable y el DOM varió para Goles. Las entradas de recursos del navegador
aumentaron una vez al pasar por Goles y Todo; no se registró el destino de esas
entradas, así que no se afirma que todas las variantes sean estrictamente sin
red. La captura normalizada de este hito conserva el estado `Partidos` que
publica `#taula-seguiment`; las otras tres variantes quedan pendientes de
captura y validación semántica. `#comp` mostró solo Liga.

La tabla Seguimiento incluye las jornadas 1–6 disputadas en el momento de la
captura. Sus encabezados son jornadas y cada celda enlaza a un partido
`p.php?id=...`. En el estado Partidos los valores representan minutos jugados
en esa jornada: por ejemplo, Moyano tiene 90, 45 y 16 minutos, suma 151 y
coincide con Minutos en Estadísticas. Una celda en blanco se conserva como
`null`, no se sustituye por cero.

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

- Seguimiento aporta minutos por jugador y partido en el estado `Partidos`.
  El ID de cada partido se obtiene de la URL de la celda; la jornada del
  encabezado se puede reconciliar por ese ID con `matches.json`. Son datos
  nuevos de granularidad individual.
- Traspasos de Jaén presenta una tabla `Altas` con Apodo y Nombre, Edad, Pos y
  Equipo origen. Los enlaces permiten identificar el jugador y el club de
  origen; cada movimiento conserva también los nombres y URL de perfil del
  jugador asociados al mismo `player_id`, sin crear una segunda identidad.
  No se observaron importes ni fecha del movimiento. `Bajas` no tenía
  filas visibles en esta captura; eso no demuestra que el club no tuviera
  bajas fuera de lo publicado en esa vista.
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
ambos grupos. Sus IDs, título,
plantilla principal, entrenador y estructura de Estadísticas fueron válidos;
ambas vistas devuelven 25 jugadores. Sus datos del roster completo,
Seguimiento, Traspasos y Partidos no se adquirieron en este piloto. La
generalización de esas vistas queda pendiente de una captura de Grupo I en
TEAM-01B si ese lote las necesita.

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
| Plantilla completa con nacimiento | Verificada en Jaén | Incluida cuando la vista está disponible | Pendiente de comparación en Grupo I |
| Estadísticas individuales extendidas | Verificada en ambos grupos | Incluida | Encabezados semánticos de origen; checks con partidos |
| Seguimiento de minutos por partido | Verificado en Jaén | Incluido para estado Partidos | Suma individual contrastada con minutos agregados |
| Seguimiento Tarjetas/Goles/Todo | Opciones y cambio del DOM explorados | No se exportan todavía | Pendiente semántica/carga de recursos |
| Altas y Bajas | Tabla de Altas y bloque Bajas explorados para Jaén | Altas incluidas; vacíos conservados | No demuestra ausencia real de bajas |
| Partidos y clasificación de equipo | Vistas reales exploradas; IDs cruzados | Solo referencias/validación | No duplican datasets de competición |
| Traspasos, seguimiento y altas/bajas en Grupo I | Enlaces visibles en Grupo I | Pendiente | TEAM-01B |

## Extractor y capturas TEAM-01A

El paquete `football_data_hub.providers.bdfutbol.teams` contiene modelos
independientes, parser offline, lectura del catálogo, adquisición con
`BDFutbolAccess`/`BrowserSessionManager`, validación y exportación JSON
inmutable. La URL de cada vista se resuelve desde los enlaces y opciones reales
del HTML base. La adquisición se limita a un equipo y se detiene en la primera
denegación o contenido inválido; no reintenta ni resuelve desafíos.

Las capturas reales normalizadas en este hito están bajo:

- Jaén, Grupo II, `team_id=49`:
  `data/exports/bdfutbol/teams/2026-27/49/team01a-group2-49-source-evidence/`.
  Se guardaron Alineación, Plantilla, Estadísticas, Seguimiento, Traspasos y
  Partidos; 25 personas, un entrenador, 25 estadísticas, 150 celdas de minutos,
  34 altas y seis referencias a partidos disputados.
- Racing de Ferrol, Grupo I, `team_id=48`:
  `data/exports/bdfutbol/teams/2026-27/48/team01a-group1-48-source-evidence/`.
  Se guardaron Alineación y Estadísticas; 25 personas, un entrenador y 25
  estadísticas. No se atribuyen al piloto las demás vistas del Grupo I.
- El inventario versionado de los 40 clubes está en
  `data/exports/bdfutbol/teams/2026-27/catalog/20261011T115607.387269Z-f86d8190/`.
  Deriva de los dos catálogos existentes; no crea IDs ni modifica esos catálogos.

Cada directorio de captura conserva HTML por vista, URL y evaluación de acceso,
fecha de evidencia, SHA-256, catálogos de origen, modelos normalizados y
validación. El tiempo de las capturas exploratorias se tomó del archivo de
diagnóstico local porque los scripts de exploración no guardaron una hora de
navegación por vista; ese criterio queda explícito en `raw/access.json` y no se
presenta como una hora registrada por BDFutbol. Las ejecuciones futuras del
extractor guardarán su propia hora de adquisición.

Para normalizar snapshots autorizados sin abrir un navegador:

```bash
PYTHONPATH=src .venv/bin/python scripts/acquire_bdfutbol_team.py \
  --season 2026-27 --group 2 --team-id 49 --views all \
  --snapshot-dir /ruta/a/snapshots-jaen

PYTHONPATH=src .venv/bin/python scripts/acquire_bdfutbol_team.py \
  --season 2026-27 --group 1 --team-id 48 --views core \
  --snapshot-dir /ruta/a/snapshots-racing
```

Las carpetas deben contener `alignment.html`, las vistas solicitadas y
`access.json` con una evaluación `VALID`, HTTP 200, URLs finales iguales a las
resueltas del HTML base y hashes correctos. `core` captura Alineación y
Estadísticas; `all` añade Plantilla, Seguimiento, Traspasos y Partidos.

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

La suite offline usa los snapshots guardados, comprueba las dos identidades,
vistas, estadísticas, nulos, relaciones por ID, referencias a resultados,
hashes y lectura de JSON. No descarga imágenes, perfiles individuales ni
temporadas históricas, y no copia partidos a los exports de equipo. La
exploración de `Tarjetas`, `Goles` y `Todo` en Seguimiento sigue pendiente de
normalización semántica; solo se exporta el estado `Partidos` (minutos).
