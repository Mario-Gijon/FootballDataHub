# TEAM-03B3 — Catálogos de partidos y checkpoint de Cacereño

Fecha de adquisición local: 13/10/2026. Los catálogos descritos aquí son
candidatos externos al checkout. No sustituyen los datasets activos de la API.

## Diagnóstico de `427720` y `427726`

La captura guardada de Cacereño (`team_id=149`, Grupo I) identifica ambos IDs
en `#taula-resultats-plantilla` como partidos de **Copa Federación**:

| Match ID | Fecha | Competición / ronda | Local | Marcador | Visitante |
|---|---|---|---|---|---|
| `427720` | 09/09/2026 | Copa Federación, Dieciseisavos de final | Cacereño | 2–0 | San Pedro |
| `427726` | 16/09/2026 | Copa Federación, Octavos de final | Recreativo de Huelva | 2–1 | Cacereño |

La evidencia DOM de las dos filas muestra el texto de competición en la segunda
celda y la clase `COM_FED`. Las filas de Primera Federación muestran `Liga` y
`COM_LIG`. No son IDs nuevos del grupo, ni IDs de Liga sustituidos, ni una
inconsistencia del sitio. El parser anterior recopilaba enlaces a `p.php?id=`
de toda la tabla sin distinguir competición, y el validador los comparaba como
si todos fueran IDs de Primera Federación.

La captura también muestra el encuentro de Liga `269470` (Cacereño 1–1
Unionistas, jornada 7). El catálogo de Grupo I del 10/10 conservaba ese
encuentro como pendiente. Esta diferencia independiente justificó refrescar
ambos catálogos antes de validar el checkpoint y seguir adquiriendo equipos.

El parser ahora conserva la lista completa de IDs de la vista y la particiona
por competición usando la etiqueta visible de cada fila. Solo los IDs de Liga
se enlazan con el `matches.json` del grupo. Los de otras competiciones se
mantienen como referencias externas al catálogo de Liga. Rechaza filas con la
competición vacía y contradicciones entre `COM_LIG`/`COM_FED` y el texto de la
competición. No se resuelven IDs por parecido de nombres.

## Capturas candidatas

Las dos visitas se hicieron en secuencia con Chromium 152, SeleniumBase Pure
CDP, el perfil local persistente y Xvfb proporcionado por la infraestructura
existente. Ambas devolvieron HTTP 200, URL de temporada/grupo correcta, 20
equipos y pasaron las ocho validaciones de clasificación. Cada snapshot produjo
140 puntos de progreso y cubre 38 jornadas, con siete jornadas disputadas.
Después se normalizó `matches.json` offline desde el mismo snapshot; no hubo
una segunda visita de Resultados.

| Grupo | Capture ID | Captura UTC | Capture ID anterior | Captura anterior UTC | Ruta candidata de `matches.json` | SHA-256 |
|---|---|---|---|---|---|---|
| I | `20261013T103923.024344Z-b785fc3b` | `2026-10-13T10:39:23.024524+00:00` | `20261010T202500.293648Z-b770724f` | `2026-10-10T20:25:00.293798+00:00` | `$HOME/FootballDataHub-data/competition-candidates/group1_classification/20261013T103923.024344Z-b785fc3b/normalized/matches.json` | `39c143da25b40bdc0274c43ec7b9f06dc16eb0877b4794ac21fb4ae81675a474` |
| II | `20261013T103943.038093Z-1ed28513` | `2026-10-13T10:39:43.038311+00:00` | `20261010T102656.252222Z-72f200ad` | `2026-10-10T10:26:56.252397+00:00` | `$HOME/FootballDataHub-data/competition-candidates/group2_classification/20261013T103943.038093Z-1ed28513/normalized/matches.json` | `b85f573fe449cbfb3db34f0fd82f1c16fdb97c07f2edd0c698be744bc0e91e96` |

## Diferencias por grupo

| Dato | Grupo I | Grupo II |
|---|---:|---:|
| Equipos anteriores / nuevos | 20 / 20 | 20 / 20 |
| Partidos anteriores / nuevos | 380 / 380 | 380 / 380 |
| Jornadas disputadas anteriores / nuevas | 6 / 7 | 6 / 7 |
| Partidos disputados anteriores / nuevos | 60 / 68 | 59 / 68 |
| Pendientes anteriores / nuevos | 320 / 312 | 321 / 312 |
| IDs conservados | 380 de 380 | 380 de 380 |
| IDs añadidos / desaparecidos | 0 / 0 | 0 / 0 |
| Cambios de identidad de encuentro | 0 | 0 |
| Cambios pendiente → disputado | 8 | 9 |
| Marcadores añadidos | 8 | 9 |

En los 380 IDs comunes, `matchday`, `home_team_id` y `away_team_id` se
conservaron. No hubo cambios de marcador distintos de resultados recién
publicados. Los IDs `427720` y `427726` no aparecen en ninguno de los dos
catálogos candidatos porque pertenecen a Copa Federación.

IDs de resultados incorporados al estado disputado:

- **Grupo I:** `269468` (0–0), `269469` (2–4), `269470` (1–1), `269472`
  (0–1), `269474` (1–1), `269475` (1–0), `269476` (1–2) y `269477` (0–2).
- **Grupo II:** `272576` (2–2), `272577` (4–4), `272578` (1–1), `272579`
  (2–1), `272581` (1–1), `272582` (3–3), `272583` (2–2), `272584` (0–1)
  y `272585` (1–0).

El diff completo con old/new scores, estado, jornada, equipos, IDs añadidos,
IDs desaparecidos y conflictos está guardado fuera del checkout en
`$HOME/FootballDataHub-data/competition-candidates/catalog-comparisons/20261013T104300Z/catalog_diff.json`.

## Compatibilidad de capturas históricas

El inspector de capturas mantiene intactos la referencia original y su
SHA-256. Carga la ruta histórica guardada en los metadatos, verifica el hash y
la procedencia y vuelve a validar los snapshots y JSON normalizados contra esa
versión. Por separado compara la versión histórica con el catálogo candidato:

- exige la misma temporada, grupo y los mismos 20 `team_id`;
- exige que cada ID histórico siga existiendo y conserve jornada, local y
  visitante;
- informa IDs añadidos sin intentar emparejarlos con registros antiguos;
- registra por separado cambios de fecha, estado y marcador;
- bloquea la reutilización si hay IDs desaparecidos, duplicados o asociados a
  otros participantes/jornadas.

Así no se sustituye el hash histórico ni se interpreta el cambio de estado de
un partido ya existente como una nueva identidad. Con los candidatos del
13/10, las seis capturas completas de Racing de Ferrol, UD Logroñés, Lugo,
Real Jaén, Bilbao Athletic y Zaragoza siguen completas y son compatibles. No
se volvieron a navegar ni a modificar.

## Recuperación offline de Cacereño

El checkpoint seleccionado por los metadatos, no por un ID codificado en la
CLI, conserva seis vistas HTTP 200, los cuatro estados de Seguimiento y sus
hashes. El parseo offline contra el candidato del Grupo I pasa la validación:

- 25 jugadores y 1 entrenador;
- 175 filas de minutos y 19 métricas de eventos;
- 17 altas y 21 bajas;
- 9 referencias observadas en la ficha: 7 encuentros de Liga y 2 de Copa;
- los datos de Seguimiento se refieren a siete partidos de Liga, incluido el
  ID `269470`.

No se repitió ninguna vista de Cacereño. La captura derivada y validada es
`$HOME/FootballDataHub-data/team-captures/2026-27/149/20261013T094427.054639Z-94bb716e/`.
Conserva `captured_at_utc=2026-10-13T09:45:21.714905+00:00`, las seis vistas
reutilizadas y `acquired_views=[]`; `created_at_utc=2026-10-13T10:58:23.275611+00:00`
registra la exportación offline por separado. La validación offline queda en
`validation/results.json`: válida, sin incidencias, con advertencia explícita
que separa `427720` y `427726` de los partidos de Liga. El checkpoint duplicado
se retiró únicamente después de que `inspect_team_capture` confirmara que esta
captura está completa y es compatible con el catálogo candidato.

La primera exportación alcanzó a escribir la captura, pero su manifiesto de lote
registró un fallo local al ejecutar la inspección posterior a la publicación
(faltaba importar `inspect_team_capture`). Se corrigió la importación y la
inspección posterior se repitió offline contra la captura ya publicada; no se
volvió a exportar encima de ella ni se navegó a BDFutbol. El manifiesto de ese
intento queda en
`$HOME/FootballDataHub-data/team-captures/2026-27/batch-manifests/20261013T105823.449302Z-23ba8a5a/manifest.json`.
La CLI ahora mantiene el checkpoint si una futura captura no supera esa
inspección y añade metadatos de derivación en recuperaciones offline. En esta
captura ya exportada, `created_at_utc` y `capture_timestamp_basis` conservan la
fecha y el carácter offline de la derivación; el campo opcional `derivation`
permanece `null` porque el primer intento usó la versión anterior de la CLI.

El preflight global actual devuelve 7 `skip_complete` (incluido Cacereño),
33 `acquire_or_rebuild` y 198 navegaciones previstas. No inicia el navegador.
Los seis perfiles anteriores siguen completos, con los hashes originales
intactos y compatibles con los catálogos candidatos. El almacenamiento externo
se informó como no escribible desde el sandbox en este preflight; la operación
local de recuperación pudo escribirse usando el permiso de filesystem aprobado.

## Reproducción

Usar los `matches.json` candidatos indicados arriba, en vez de reemplazar los
archivos del 10/10. Para inspeccionar de nuevo el estado global:

```bash
PYTHONPATH=src .venv/bin/python scripts/acquire_bdfutbol_team_batch.py \
  --dry-run --groups both \
  --output-root "$HOME/FootballDataHub-data/team-captures" \
  --group1-catalog "$HOME/FootballDataHub-data/competition-candidates/group1_classification/20261013T103923.024344Z-b785fc3b/normalized/matches.json" \
  --group2-catalog "$HOME/FootballDataHub-data/competition-candidates/group2_classification/20261013T103943.038093Z-1ed28513/normalized/matches.json"
```

Villarreal B (`94`) y Alcorcón (`107`) siguen dentro de los 33 pendientes. No
se adquirieron en este hito. Su preflight explícito los confirma como Grupo II,
`acquire_or_rebuild`, seis vistas cada uno (12 navegaciones en total), con
`browser_started=false`. Esperar una decisión posterior antes de ejecutar el
bloque.

No se modificaron `config/team_profiles_2026-27.json`, capturas del 10/10,
bootstraps de FastAPI, ni datasets de Destacados, Estadísticas o Árbitros.
