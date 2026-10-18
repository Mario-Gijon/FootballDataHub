# MATCH-04B — Actualización incremental de partidos y horarios

## Estado y límites

MATCH-04B añade comparación y activación offline de generaciones, conserva los detalles aprobados contra su generación histórica y proyecta horarios únicamente cuando el HTML ya guardado los acredita. No ejecuta adquisición, HTTP, navegadores, publicaciones ni tareas programadas. Las generaciones y publicaciones reales externas se leyeron sin modificarlas.

La generación local de referencia inspeccionada es `match-00-4ad1d610507e425d` (G1), con 40 equipos y 760 partidos. Los horarios de partidos pendientes no aparecen en los snapshots de competición disponibles: `SP` no contiene campo horario y los HTML examinados tampoco exponen tokens `HH:MM` para dichos fixtures. Por ello, la hora permanece `null` en esos registros hasta que una captura futura aporte evidencia verificable.

## Arquitectura anterior y cambio

MATCH-00 construía una generación verificada, y FastAPI cargaba una ruta fija al inicio de su lifespan. Los detalles tenían hashes y aprobación correctos, pero su lector comparaba la generación fuente del paquete con el calendario activo. Esa igualdad de versiones ocultaba una publicación histórica válida al actualizar el calendario.

Ahora se distinguen:

1. La generación inmutable de calendario/resultados que FastAPI carga como activa.
2. La generación MATCH-00 inmutable que originó cada publicación de detalles.
3. La captura HTML, su hash y el documento deportivo derivado.
4. El paquete aprobado y su entrada en el índice de publicación.
5. El diff y el evento de activación que enlaza la generación activa anterior y nueva.

El lector revalida cada publicación contra su generación histórica y su paquete/captura originales. Después compara `internal_id`, ID fuente, grupo implícito en el ID, equipos, estado disputado, fecha y marcador con el fixture activo. No usa similitud de nombres. Un paquete no se reescribe para ajustarlo al calendario nuevo.

Si falta la generación histórica, falla un hash o hay una contradicción deportiva, la carga de detalles falla cerrada. Una fecha o marcador contradictorios también impiden activar la nueva generación mientras haya una publicación afectada. El diff marca dichos casos para revisión; el flujo actual no ofrece una excepción para forzar equivalencias. Los paquetes aprobados y sus hashes quedan intactos.

## Horarios: evidencia y semántica

El parser de ficha individual lee la etiqueta `Fecha` de `div.hero.hero-partit .f14`. En los tres HTML guardados, el texto contiene fecha y, entre paréntesis, una hora:

| Partido | Texto observado | Hora normalizada | HTML SHA-256 |
|---|---|---:|---|
| Teruel–Real Madrid Castilla (`272525`) | `Lunes 31/08/2026 (21:15)` | `21:15` | `9649b77712f8f259dd4cc413ebc90c26305069a7cb96ab8829fed3aff4b01113` |
| Huesca–Sant Andreu (`272517`) | `Sábado 29/08/2026 (19:15)` | `19:15` | `48eeada83ddbf8ff9c7493f6fdcbeed13e54a694da6a274052822f8966827cbb` |
| Jaén–Villarreal B (`272582`, referencia histórica) | `Sábado 10/10/2026 (18:45)` | `18:45` | `9242edad00b43a4e83c649ddad006edb0d1172e0d88640082312a0fe1cf16997` |

En esa estructura, fecha y hora se presentan juntas bajo el rótulo `Fecha` de la ficha del encuentro. Se conserva la hora como reloj local mostrado por la fuente; el HTML no declara una zona horaria y no se convierte a UTC ni se asigna `Europe/Madrid`. Esto acredita lo que publica la ficha, no una comprobación independiente del horario inicialmente programado. `272582` sigue siendo una referencia de lectura histórica; su estado de adquisición/publicación no se modifica.

El parser separa fecha y hora. Devuelve `HH:MM` solo para un único literal parentético válido, preserva el texto fuente y registra estado `observed`, `explicitly_absent` o `unresolved`. Formatos ambiguos, inválidos o fuera de rango no producen hora. La ausencia de hora no invalida por sí sola una fecha o un partido semánticamente válido. No hay timezone fuente. El campo adicional de MATCH-00 `kickoff_time_local` es opcional y nullable; no se inventa para los encuentros futuros que carecen de hora.

La API puede exponer la hora desde el registro MATCH-00 cuando una adquisición futura la valide, o como proyección de lectura de la evidencia HTML ya validada para una ficha publicada. La proyección incluye estado, texto fuente, referencia DOM, versión de parser y hash del HTML; no modifica `details.json`, la aprobación ni el manifiesto publicados. Los documentos antiguos sin estos campos siguen siendo válidos. Resultados y ficha usan un formateador común; sin hora solo muestran la fecha.

## Diff incremental

`compare_match_generations(before, after)` produce una lista determinista por `internal_id` con valores anteriores/nuevos y SHA de ambas generaciones. Distingue:

- `newly_played`: estado anterior no disputado y nuevo `played` (incluye `incomplete → played`).
- `played_to_unplayed_conflict`: requiere revisión y nunca se interpreta como una eliminación normal.
- `result_corrected`: marcador cambió; requiere revisión.
- `fixture_updated`: fecha, hora, estadio, árbitro o disponibilidad de URL cambió.
- `identity_conflict`, `fixture_added` y `fixture_missing`: conflicto duro que bloquea activación.
- `unchanged`.

Un valor nuevo `null` se registra como `not_observed_in_new_capture`, no como borrado confirmado. Los valores previamente desconocidos que pasan a tener contenido quedan registrados como cambios. Los partidos `played` se marcan con `approved` o `details_pending` según el índice publicado verificado. El hash del informe incluye la lista completa y el resumen. No se escoge una generación por timestamp: para comparar se indican explícitamente las dos rutas.

La operación `compare` imprime resumen y produce JSON. El informe es de solo lectura salvo que se pida `--output`, que escribe un archivo nuevo sin sobreescribir uno existente. La activación vuelve a calcular el diff bajo lock y exige exactamente su SHA-256.

## Activación, atomicidad y recuperación

Para la primera activación, el operador debe proporcionar el ID G1 esperado. Para siguientes activaciones se valida el puntero actual y se bloquea la comparación/activación con `.generation-activation.lock`. Antes de cambiar el puntero se:

1. Verifican manifiesto, capturas, hashes, catálogo y reproducción de la generación candidata.
2. Compara el fixture por ID y comprueba que no haya conflictos duros.
3. Revalida el índice y todas las publicaciones aprobadas contra sus fuentes históricas y los fixtures candidatos.
4. Comprueba el hash del diff confirmado y la identidad del revisor.
5. Escribe de forma inmutable el informe y un evento de activación con G1, G2, revisor y hash del informe.
6. Reemplaza atómicamente `active-generation.json`, que referencia el evento y el hash de manifiesto.

El lector del puntero valida evento, hash del evento, fecha, informe/diff y manifiesto antes de resolver la generación. Si falla cualquier verificación antes del reemplazo, G1 sigue activo. Si el proceso cae tras escribir el evento pero antes de cambiar el puntero, queda un evento huérfano auditable y G1 continúa activo. No se sobrescribe una generación, un informe, un evento o un paquete histórico.

### Comandos offline

```bash
export DATA_ROOT="$HOME/FootballDataHub-data"
export G1="$DATA_ROOT/matches/generations/match-00-4ad1d610507e425d"
export G2="$DATA_ROOT/matches/generations/ID_CANDIDATO_VERIFICADO"

PYTHONPATH=src:apps/api .venv/bin/python scripts/build_bdfutbol_match_generation.py \
  --group-i-root "$DATA_ROOT/competition-candidates/group1_classification/CAPTURA_VALIDADA" \
  --group-i-matches "$DATA_ROOT/competition-candidates/group1_classification/CAPTURA_VALIDADA/normalized/matches.json" \
  --group-ii-root "$DATA_ROOT/competition-candidates/group2_classification/CAPTURA_VALIDADA" \
  --group-ii-matches "$DATA_ROOT/competition-candidates/group2_classification/CAPTURA_VALIDADA/normalized/matches.json" \
  --data-root "$DATA_ROOT" --output-root "$DATA_ROOT/matches"

PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_generations.py compare \
  --data-root "$DATA_ROOT" --store-root "$DATA_ROOT/matches" \
  --before "$G1" --after "$G2"
```

Revisar el JSON completo y copiar su `report_sha256` exacto; no activar si hay conflicto duro o si la evidencia/publicaciones producen error. Después de validar hashes, identidad, cambios y partidos disputados sin detalle, el revisor puede activar explícitamente:

```bash
PYTHONPATH=src:apps/api .venv/bin/python scripts/manage_bdfutbol_match_generations.py activate \
  --data-root "$DATA_ROOT" --store-root "$DATA_ROOT/matches" \
  --candidate "$G2" --expected-current-generation "match-00-4ad1d610507e425d" \
  --reviewer "IDENTIDAD DEL OPERADOR" --confirm-report-sha256 "SHA256_DEL_DIFF_REVISADO"
```

Para FastAPI, configurar `FDH_LOCAL_DATA_ROOT="$DATA_ROOT"`. Si existe `matches/active-generation.json`, la configuración por defecto selecciona el almacén y valida el puntero; si todavía no existe, conserva el pin histórico G1. `FDH_MATCH_GENERATION_ROOT` explícito prevalece y puede fijar una generación concreta o apuntar al almacén. FastAPI carga calendario y detalles juntos durante el lifespan. Para adoptar una generación activada, reiniciar el proceso; el reinicio vuelve a cargar todo como un único bundle y evita mezclar generaciones en memoria. No se añade polling.

## Cobertura de detalles y operación futura

El informe identifica los partidos finalizados sin publicación aprobada para preparar una cola de detalles. Esa cola no navega ni autoriza candidatos. La futura adquisición debe permanecer separada de validación, comparación, activación y publicación, con autorización individual de acuerdo con las políticas de acceso actuales.

En el servidor UJA: instalar el mismo paquete, montar el almacén versionado fuera del repositorio, comprobar permisos/espacio y ejecutar validaciones offline; adquirir solo mediante una operación autorizada aparte; construir G2 en un directorio nuevo; revisar diff y detalles pendientes; activar atómicamente; reiniciar FastAPI y verificar endpoints locales. Solo después de haber estabilizado esa operación podrá diseñarse una tarea periódica. MATCH-04B no instala cron, no configura scraping masivo ni despliega al servidor.

## Limitaciones pendientes

- Los snapshots de clasificación disponibles no proporcionan horarios de los partidos pendientes. Se necesitará una fuente o captura autorizada que los exponga con evidencia vinculada al fixture.
- La ficha individual publica hora junto a `Fecha`, pero no indica timezone. No se ha comprobado independientemente si refleja el horario original o una hora reprogramada en todos los casos.
- La activación actualmente falla cerrada ante cambios de fecha/marcador que contradicen detalles aprobados; resolver esos casos requiere una revisión deportiva y, si el detalle cambia, una nueva versión aprobada, nunca editar la anterior.
- FastAPI adopta una generación al iniciar. El operador debe reiniciar después de activar; no hay recarga en caliente ni polling.
- El comparador reconoce fixtures añadidos/faltantes como conflictos duros porque MATCH-00 espera el inventario de 760 IDs estables. Un cambio de inventario requiere revisión del modelo/competición, no una fusión automática.
- El índice activo y el recibo de activación son evidencia auditable en el almacén de confianza local, no una firma digital externa.

## Verificación de artefactos

La prueba de integración local optativa `tests/integration/test_match_04b_local_kickoff.py` vuelve a parsear `272525` y `272517`, carga las publicaciones existentes desde sus paquetes y comprueba que se proyecten `21:15` y `19:15` sin escritura ni cambio de hash. La prueba puede omitirse si falta el almacén local:

```bash
FDH_MATCH_04B_INTEGRATION=1 PYTHONPATH=src:apps/api \
  .venv/bin/python -m pytest -p no:rerunfailures -q tests/integration/test_match_04b_local_kickoff.py
```
