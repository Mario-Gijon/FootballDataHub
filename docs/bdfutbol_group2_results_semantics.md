# Resultados BDFutbol — Primera Federación Grupo II 2026/27

## Estado de la exploración

La referencia local es la captura CLAS-01 `20261010T102656.252222Z-72f200ad`, tomada el 10/10/2026. Se inspeccionó primero `raw/source.html`, sin modificarlo. El snapshot contiene `SE`, `SP` y `div#resultats`: 20 equipos, 38 jornadas, diez filas por jornada y 380 partidos. Hay 59 marcadores y 321 filas sin resultado.

La captura principal abre la vista de clasificación. El enlace de navegación de Resultados apunta a `?tab=results`, pero la tabla `#resultats` ya está incluida en el HTML con `display:none`. El snapshot no contiene el selector visible ni una tabla de matriz. Se intentó una única apertura de la pestaña Resultados con Brave/CDP/Xvfb existentes para inspeccionar lo ausente; BDFutbol respondió HTTP 403 y `Just a moment...` (`CHALLENGE_REQUIRED`). La navegación se detuvo sin resolver el desafío ni reintentar.

| Área | Estado | Evidencia o límite |
|---|---|---|
| Calendario y lista completa en el snapshot | Explorados | 38 encabezados `jornadatit`; 380 filas `.jornadai`, identificadas por `data-jornada`. |
| Marcadores, jornadas y fechas | Verificados contra el extractor actual | `SP` y `#resultats` se reconcilian para los 380 partidos. Hay 59 marcadores; las 321 filas restantes no se interpretan como 0-0. |
| Estadio y árbitro | Explorados y verificados en el snapshot | Ambos aparecen en celdas 5 y 6 (índices 4 y 5) de las 59 filas con resultado. Se identificaron 19 IDs de estadio y 42 IDs de árbitro en sus enlaces. Las otras 321 filas están vacías. |
| Escudos | Ya disponibles en el catálogo | `Team.crest_url` se obtiene de la tabla de clasificación. El HTML de resultados también incluye imágenes `escut-mini` junto a los nombres, pero no hace falta duplicarlas en cada partido. |
| Selector de jornadas en la pestaña | Pendiente de verificar en la interfaz | El snapshot solo confirma que todas las jornadas están en el DOM; no incluye un selector de Resultados que permita conocer valores, navegación o eventos. |
| Opción «Todas» y cambios de jornada | Pendientes de verificar en la interfaz | La consulta local define `matchday=None` como los 380 partidos. No se presenta como semántica observada del control BDFutbol. |
| Matriz y colores | Pendientes de verificar con BDFutbol | No hay elementos ni código de matriz en el snapshot. No se afirma que la web use una orientación o paleta concreta. |

## Estructura disponible para el listado

El contenedor `div#resultats` contiene una tabla `.taula_estil.taula_estil-16`. Cada jornada empieza con una fila `tr.jornadatit` y una fila de encabezados `tr.jornadai.ijN` con `data-jornada="N"`. Después siguen diez filas de partido `tr.jornadai.ijN` con las mismas jornadas y valores de fecha, local, marcador, visitante, estadio y árbitro.

| Campo normalizado | Fuente observada | Significado y tipo | Cobertura de esta captura |
|---|---|---|---:|
| `match_id` | `SP[N]` campo `id`; para disputados también `p.php?id=...` en `#resultats` | ID BDFutbol, texto. Es único entre los 380 fixtures en esta captura. Para partidos sin resultado se conserva el ID de `SP`, aunque no haya enlace a ficha. | 380 |
| `matchday` | Índice de `SP[N]`; `data-jornada` de la fila | Jornada entera, 1–38. | 380 |
| `matchday_date` | Opción de `select#jornada` de la vista de clasificación | Fecha publicada para la jornada, no fecha efectiva de cada partido. | 380 |
| `source_match_date` | `SP.d` y primera celda de la fila | Fecha observada del encuentro si se disputó; fecha programada/de referencia si sigue sin resultado. La fuente no da otra fecha planificada por separado. | 380 |
| `home_team_id`, `away_team_id` | Índices `SP.a1/a2` resueltos mediante `SE`, cotejados con los nombres de las celdas y el catálogo `#classific[data-ideq]` | IDs BDFutbol del catálogo de equipos, no los índices internos de `SE`. | 380 |
| Escudos | `Team.crest_url` del catálogo de clasificación; imágenes `img.escut-mini` en las celdas de equipos de resultados | URL reutilizada desde el equipo relacionado por ID. | 20 equipos |
| `home_goals`, `away_goals` | `SP.g1/g2`; dos `div.resultat-gols` en la celda de resultado | Goles enteros cuando hay marcador. `SP` usa `-1/-1` y la tabla muestra una raya cuando no está disputado; ambos goles normalizados quedan `null`. | 59 con marcador; 321 `null` |
| `source_match_url` | Enlaces `p.php?id=...` de la fila | URL canónica construida desde el `id` de partido. Varios anchors de una fila pueden repetir el mismo ID; son enlaces al mismo partido, no entidades distintas. | 59 |
| `stadium_name`, `stadium_url`, `stadium_id` | Quinta celda (índice 4); anchor relativo `../s/{id}.html` cuando está enlazado | Nombre visible, URL absoluta y el segmento de ruta como ID de fuente, todos nullable. | 59 nombres/URLs/IDs; 19 IDs distintos |
| `referee_name`, `referee_url`, `referee_id` | Sexta celda (índice 5); anchor relativo `../r/{id}.html` cuando está enlazado | Nombre visible, URL absoluta y el segmento de ruta (por ejemplo `r601469`) como ID de fuente, todos nullable. | 59 nombres/URLs/IDs; 42 IDs distintos |
| Estado del partido | Marcador en `SP` y elementos `.resultat-gols` | `played` con dos goles; `unplayed` con ausencia de ambos; `incomplete` si solo existe uno. No se infiere estado de aplazamiento oficial por una celda vacía. | 59 `played`, 321 `unplayed`, 0 `incomplete` |

En los 59 marcadores, la clase `resultat-guanya` aparece en el lado ganador y no aparece en empates (59/59 casos comprobados). El extractor conserva el marcador numérico como dato principal; no utiliza esa clase para asignar goles ni para la matriz.

La lista J6 del snapshot conserva diez filas, ordenadas por las fechas visibles 02/10, 03/10 y 04/10/2026. El orden local propuesto es cronológico por `source_match_date`, seguido de jornada y `match_id` numérico (o lexicográfico si no fuera numérico), para mantener un resultado estable sin depender del orden de carga. Las consultas usan los partidos normalizados y el catálogo `Team`, por lo que pueden incluir nombre, escudo y enlaces sin navegador ni HTTP.

La fecha de una jornada se mantiene separada de la fecha de partido: por ejemplo, la fecha de J1 del selector es 30/08/2026, mientras que `SP.d` incluye partidos del 29/08 al 31/08. La opción local `matchday=None` devuelve todas las jornadas del conjunto guardado; un número de jornada restringe a las diez filas de esa jornada, incluyendo los encuentros sin resultado.

## Matriz de enfrentamientos

La captura no trae la matriz ni sus reglas de presentación: no se encontraron tabla, selector o código con referencias a una matriz. Por la respuesta 403 de la única navegación a `?tab=results`, siguen sin verificar con BDFutbol:

- qué equipo aparece en cada eje y cuál es la orientación exacta de sus celdas;
- si se colorea desde la perspectiva local o visitante y los colores asignados;
- cómo dibuja la fuente los empates, pendientes y la diagonal;
- si una celda enlaza a la ficha del partido;
- si la matriz es de toda la temporada o cambia al elegir jornada.

El modelo local implementa el contrato conceptual especificado para FootballDataHub: fila = local, columna = visitante, una celda vinculada por `match_id`; un resultado disputado recibe una categoría derivada desde la perspectiva del local (`home_win`, `draw`, `home_loss`). Un partido sin marcador conserva estado `unplayed`, celdas sin goles y sin categoría de resultado. La diagonal usa estado `diagonal`, separado de un partido. Este mapeo es un modelo de dominio para nuestra futura interfaz, no una afirmación sobre el HTML/CSS de BDFutbol. La ausencia de un par en un subconjunto se representa como `missing`, no como partido pendiente.

Para la captura completa, la validación de la matriz comprueba 20 filas y columnas, cero colisiones, una aparición por ID de partido, 380 celdas de fixture fuera de la diagonal, 59 con resultado y 321 sin marcador. Es una validación estructural de nuestro conjunto de partidos; no valida la representación visual de BDFutbol.

El motor está en `src/football_data_hub/domain/classification/results.py`: `list_group2_results(teams, matches, matchday=None)` prepara la lista uniendo los equipos por ID; `build_group2_results_matrix(teams, matches)` prepara las celdas por ID local/visitante. Ambos son cálculos puros y no escriben una matriz duplicada. Ejemplo offline:

```python
from pathlib import Path

from football_data_hub.domain.classification.results import (
    build_group2_results_matrix,
    list_group2_results,
)
from football_data_hub.providers.bdfutbol.classification.match_io import load_match_dataset

_, teams, matches = load_match_dataset(Path(".../normalized/matches.json"))
j6 = list_group2_results(teams, matches, matchday=6)
all_matches = list_group2_results(teams, matches)
matrix = build_group2_results_matrix(teams, matches)
```

`MatchListEntry` entrega el `MatchResult` existente junto a `home_team` y `away_team`, incluidos los escudos del catálogo. `ResultsMatrixCell` contiene IDs de fila/columna, estado, `match_id`, marcador nullable y resultado desde la perspectiva local; consumidores pueden unir el ID a la misma colección de partidos para URL, estadio, árbitro y procedencia.

## Compatibilidad y procedencia

Los partidos se amplían en el mismo contrato de dominio `MatchResult`; no se introduce otro modelo persistido de partidos. Los campos nuevos de estadio y árbitro son nullable y apuntan a los datos de la fila original mediante `source_references`. Los escudos y URLs de los equipos siguen en `Team`. Los exports CLAS-01 y CLAS-01B existentes permanecen intactos; la exportación enriquecida debe escribirse en una carpeta derivada versionada que identifique `source_capture_id`.

`matches.json` v1 sigue siendo legible y asigna `null` a los campos de enriquecimiento ausentes. Las exportaciones con el contrato aditivo usan v2. No se completan nombres ni IDs para los partidos futuros y no se visitan fichas de estadio, árbitro o partido.

La exportación nueva de esta tarea quedó en `data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/`. Su metadata referencia `source_capture_id=20261010T102656.252222Z-72f200ad`; no reemplaza ningún archivo CLAS-01/01B. El loader admite tanto versiones 1 como 2. El API actual no se modificó: para servir los nuevos campos, una tarea posterior debe incluirlos en su DTO público de partidos y exponer las consultas de resultados/matriz sin conectar el dominio con FastAPI.

## Validación realizada y pendiente

- Verificado offline: 20 equipos; 38 jornadas × diez partidos; IDs únicos; 59 marcadores; campos de estadio y árbitro presentes en las 59 filas con resultado y ausentes en las 321 filas sin resultado; 19 estadios y 42 árbitros distintos; consistencia de local/visitante, fecha y marcador entre `SP` y `#resultats`.
- Verificado offline: las diez filas normalizadas de J6 y la asociación de las 380 filas a un único par local/visitante.
- Implementado y probado en dominio: lista por jornada o completa con orden estable; matriz local orientada local/visitante, diagonal, fixture pendiente, ausencia de par y rechazo de colisiones.
- No validado con la fuente: selector visible, navegación entre jornadas, peticiones de red al cambiar selección, matriz visual/orientación/colores/enlaces y respuesta de matriz a jornada.
- Acceso en vivo: detenido en HTTP 403 / `CHALLENGE_REQUIRED`; no se intentó resolver ni repetir.

Para cerrar los puntos pendientes basta una captura autorizada de la pestaña Resultados que incluya controles y matriz, después de restablecerse el acceso normal. Esa observación no exige crear un scraper separado ni visitar los partidos individuales.
