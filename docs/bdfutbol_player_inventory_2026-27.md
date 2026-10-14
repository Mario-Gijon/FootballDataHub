# Inventario offline de jugadores 2026/27

## Alcance y procedencia

El inventario se construye exclusivamente desde el índice publicado
`$HOME/FootballDataHub-data/published/team_profiles_2026-27.json` y las capturas que
este referencia en `$HOME/FootballDataHub-data/team-captures`. El proceso no inicia
navegador, no realiza peticiones y no altera las capturas. Antes de interpretar una
captura comprueba la temporada, grupo, identidad del club, estado `complete`, estado
de validación y SHA-256 publicado para cada fichero consumido.

Los datos de pertenencia proceden de `normalized/memberships.json`. Cada fila queda
unida a `normalized/players.json` por `player_id`; no se deduplica por nombre. Las
estadísticas de temporada y por partido proceden de `player_statistics.json`,
`player_match_minutes.json` y `player_match_metrics.json`. Las filas de Traspasos se
conservan como evidencia relacionada, sin convertirlas en pertenencias de plantilla.

Se incorporan como enriquecimiento complementario los dos ficheros de jugadores de
Destacados que ya están configurados para los grupos I y II. Sus datos de nacionalidad
y posición nominal se unen exclusivamente por ID. Son capturas del 10/10/2026,
anteriores a las capturas de equipos; cada observación conserva captura, fecha, grupo,
fichero, índice de fila y SHA-256. El `team_id` de Destacados no se utiliza para crear
pertenencias ni para afirmar que el jugador sigue en ese club. Los IDs de Destacados
que no aparecen en las plantillas o en las secciones de Traspasos no se añaden al
inventario de personas.

## Contrato de exportación

El constructor está en
`src/football_data_hub/providers/bdfutbol/teams/player_inventory.py` y su CLI en
`scripts/build_bdfutbol_player_inventory.py`.

- `players.json`: un registro por ID único observado en una plantilla o en Traspasos.
  Distingue `roster_membership_observed` de `transfer_reference_only`. Incluye datos
  personales disponibles, equipos/grupos observados, estadísticas de temporada,
  filas de Seguimiento, movimientos de Traspasos y referencias de procedencia.
- `memberships.json`: relaciones verificadas de jugador, equipo, temporada y grupo,
  con dorsal, grupo de plantilla, equipo y referencia al fichero de origen.
- `inventory_report.json`: cobertura, recuentos por grupo/equipo, IDs repetidos,
  conflictos de identidad, cobertura de campos y advertencias semánticas.
- `manifest.json`: hash del índice publicado, capturas de origen, fechas, hashes de
  cada JSON consumido, capturas suplementarias y hashes de los otros tres exports.

La escritura se prepara en un directorio temporal y se publica mediante renombrado
atómico del directorio completo. El destino existente se rechaza; no se sobrescriben
inventarios anteriores accidentalmente.

`nationality_flag_url` es el campo disponible en los perfiles de equipo, no un nombre
de nacionalidad. La nacionalidad textual y su código solo se rellenan desde los
snapshots de Destacados verificados. `source_position_code` del perfil de equipo y
`transfer_position_codes` se mantienen en dominios separados. `position_name` y
`position_code` de Destacados conservan la procedencia histórica de esa vista. Los
campos ausentes siguen como `null`; ceros estadísticos se conservan como cero.

Una pertenencia significa que el futbolista está en la captura publicada del club y
temporada; no demuestra por sí sola su situación contractual o actual. Una fila de
Traspasos sin pertenencia se mantiene como `transfer_reference_only`. Un mismo ID
puede tener más de una pertenencia, incluso entre grupos, sin que el inventario
etiquete automáticamente la causa como un traspaso.

## Resultado de la captura local examinada

| Métrica | Valor |
|---|---:|
| Equipos del índice | 40 (20 por grupo) |
| Registros de plantilla | 1.070 |
| Pertenencias verificadas | 1.070 |
| IDs únicos en plantillas | 1.065 |
| Personas adicionales solo en Traspasos | 644 |
| IDs únicos del inventario (plantillas ∪ Traspasos) | 1.709 |
| IDs relacionados con al menos una observación de Traspasos | 1.317 |
| Filas de Traspasos | 1.548 |
| IDs únicos con estadísticas de temporada | 1.065 |
| Filas de estadísticas de temporada | 1.070 |
| IDs con minutos por partido | 1.065 |
| Filas de minutos por partido | 7.193 |
| IDs con métricas de partido | 526 |
| Filas de métricas de partido | 1.014 |
| URL de perfil | 1.709 / 1.709 |
| URL de fotografía | 1.663 / 1.709 |
| IDs con conflicto entre valores no vacíos de identidad | 0 |

| Grupo | Equipos | Registros/relaciones de plantilla | IDs únicos en plantilla | IDs solo de Traspasos |
|---|---:|---:|---:|---:|
| I | 20 | 532 | 529 | 294 |
| II | 20 | 538 | 537 | 350 |

Las cinco personas con más de una pertenencia de plantilla son:

| `player_id` | Nombre mostrado | Clubes observados |
|---:|---|---|
| 23751 | Manu Pedreño | UD Logroñés (I), UD Ibiza (II) |
| 26481 | Armero | Huesca (II), Sant Andreu (II) |
| 304209 | Yago Rodríguez | Lugo (I), Avilés Industrial (I) |
| 304291 | Luisao | Pontevedra (I), Deportivo Fabril (I) |
| 402372 | Juanra | Pontevedra (I), Lugo (I) |

`23751` es el único ID de plantilla observado en los dos grupos. La suma de los
recuentos únicos por grupo supera por uno el total de personas únicas de plantilla
por esa pertenencia transversal. No se deduce si las filas reflejan un movimiento,
un estado temporal o una particularidad de la fuente.

Cobertura de campos personales del inventario de 1.709 IDs: nombre mostrado 1.709,
nombre completo 1.708, fecha de nacimiento 1.040, edad publicada 1.677, lugar de
nacimiento 1.007, provincia 902, nacionalidad/código 397 (Destacados), código de
posición del perfil de equipo 1.065 y nombre/código de posición de Destacados 397.
El campo nacionalidad no está disponible en el esquema del perfil de equipo. Las
cuarenta capturas de equipo y los dos snapshots suplementarios pasaron sus
comprobaciones de integridad usadas por el constructor.

## Jugadores candidatos para el piloto individual

Los candidatos salen de IDs observados; los motivos describen evidencia existente,
no una afirmación de que la carrera histórica esté completa.

| ID | Jugador | Evidencia y uso recomendado |
|---:|---|---|
| 23751 | Manu Pedreño | Dos pertenencias de 2026/27 en los grupos I y II. Un informe de piloto histórico del 09/10/2026 describió diez filas de trayectoria y varios clubes/temporadas; usar para verificar las cuatro vistas en un caso multiclub y multitemporada. La carrera quedó marcada como no certificada completa. |
| 28577 | Nacho Castillo | Presente en Jaén (II), con URL de perfil, foto, fecha de nacimiento y estadística de temporada. Candidato directo solicitado para probar la ficha enlazada desde un club local. Las temporadas anteriores aún deben comprobarse en su propia vista. |
| 209629 | Morillas | Presente en Jaén (II). El informe del snapshot histórico describió tres filas 2024/25–2026/27 y campos personales que no estaban en aquella captura. Sirve para trayectoria observada corta e información parcial; no se afirma que la trayectoria total sea corta ni completa. |
| 729168 | Mendinueta | Presente en UD Logroñés (I); la captura de equipo no incluye fotografía ni fecha de nacimiento. Candidato para comprobar cómo las vistas individuales complementan datos incompletos sin rellenarlos por inferencia. |

Los dos informes de pilotos antiguos están en el historial local de Git, no se
reutilizaron sus parsers ni sus exports. El informe histórico describe snapshots y
pruebas de interacción de octubre; no sustituye la comprobación de las capturas que
se adquieran en el siguiente hito.

## Preparación de adquisición de perfil individual

El árbol activo no contiene un colector ni parser vigente de fichas individuales.
En el historial de Git existen componentes anteriores bajo `collectors`, `parsers`
y `storage`, junto con pruebas y documentación. Sirven para conocer la estructura
que se observó entonces, pero emplean otro contrato de datos y no se importan sin
revalidación. Para la futura adquisición se debe reutilizar el runtime actual de
Brave/Pure CDP, `BrowserSessionManager` y la validación de acceso BDFutbol; no se
debe compartir la sesión como sustituto de snapshots versionados.

Rutas observadas en snapshots históricos:

| Vista | Ruta observada |
|---|---|
| Trayectoria | `/es/j/j{player_id}.html` |
| Estadísticas | `/es/j/j{player_id}.html?p=stats` |
| Partidos | `/es/p/j{player_id}.html` |
| Rivales | `/es/p/jr{player_id}.html` |

El piloto histórico de `23751` observó controles de equipo/país en Trayectoria;
competición de hitos y un selector de presentación en Estadísticas; jugados,
resultado, competición, temporada, equipo y rival en Partidos; y competición,
temporada y demarcación en Rivales. Las interacciones representativas de filtros
quedaron en el documento histórico de cobertura. En las pruebas de entonces los
filtros observados cambiaron el contenido ya presente en el DOM sin solicitudes
deportivas adicionales, pero no se probaron todas las opciones ni combinaciones.
Los valores y opciones deben inventariarse de nuevo por jugador/vista antes de
automatizar una interacción.

Una tabla `#tpartits` sin filas en la captura base de `23751` y Morillas no prueba
que ningún filtro pueda aportar contenido diferente. El piloto de `23751` accionó
representantes de sus filtros sin materializar partidos individuales; tampoco
autoriza a convertir las tablas agregadas o `window.P` en encuentros. En el futuro,
cada variante debe conservar sus controles seleccionados, HTML y SHA propios, y
compararse por filas/IDs con el estado base. Una ausencia seguirá siendo
`not observed in this snapshot` hasta que exista evidencia suficiente.

Plan de siguiente adquisición:

1. Generar una lista desde `players.json` por `player_id`, reutilizar capturas
   individuales válidas si existen y verificar sus hashes antes de navegar.
2. Pilotar primero los cuatro IDs de la tabla, en lotes pequeños y secuenciales.
   Capturar cada una de las cuatro vistas base con URL, respuesta, título, identidad,
   controles, fecha y hash.
3. Inspeccionar y probar solo filtros representativos de temporada, competición,
   equipo, rival y estado de partido que existan realmente en cada vista. Registrar
   cambios de DOM y red. No recorrer el producto cartesiano de opciones.
4. Unir registros exclusivamente por `player_id`; conservar cada contexto de
   temporada/equipo/rival y las celdas raw que todavía no tengan semántica validada.
5. Mantener snapshots parciales e inmutables. Un HTML vacío, una tabla agregada o
   un filtro de cero filas no se transforma en partidos, temporadas ni hechos
   negativos.
6. Detener una adquisición si aparece un desafío o una denegación. El inventario
   puede construirse y regenerarse completamente offline desde estas capturas.

## Regeneración local

```bash
PYTHONPATH=src .venv/bin/python scripts/build_bdfutbol_player_inventory.py
```

El comando usa el índice y el directorio de salida solicitados para este hito,
incorpora los snapshots de Destacados configurados en el repositorio y falla sin
escribir si el destino ya existe, una captura está incompleta o algún hash no
coincide. No hay modo de navegación en esta herramienta.
