# MATCH-01C-D2 — Validación offline de la segunda ficha real

## Procedencia y estado de adquisición

Se inspeccionó exclusivamente el artefacto guardado en:

`$FDH_LOCAL_DATA_ROOT/matches/details/campaigns/match-detail-sample-campaign-67fdc4b4fac66b82/candidates/pf-2026-27-group-ii-bdfutbol-272525/artifacts/discovery-20261018T112656Z-4543b211/`

El SHA-256 de `source.html` es `9649b77712f8f259dd4cc413ebc90c26305069a7cb96ab8829fed3aff4b01113` (924.494 bytes). El lector verifica el manifiesto, los hashes y tamaños de todos los archivos, la referencia del ledger, su cadena de eventos, el intento único, la autorización consumida, el inventario reconstruido desde MATCH-00 y la identidad del candidato. Los eventos son `AUTHORIZED → STARTED → DISCOVERY_REVIEW_REQUIRED`; hubo una navegación y no se promovió captura alguna.

La adquisición original registra HTTP 200 y acceso preliminar `VALID`, pero no hizo validación semántica. El parser de este hito confirma `semantic_valid=true` en una lectura posterior; no altera el resultado histórico de adquisición ni la decisión `DISCOVERY_REVIEW_REQUIRED`. La observación y la interfaz siguen siendo `preview_only`; no se añadió información al índice de publicación.

La prueba de integración compara hashes antes y después para el artefacto, la campaña y ledger, el inventario, la generación MATCH-00, las capturas de origen y el artefacto anterior. La validación no escribe en ellos. Los casos de hash incorrecto e identidad discordante operan sobre copias temporales.

## Interpretación de 272525

| Campo | Resultado observado |
| --- | --- |
| Competición y grupo | Primera Federación, Grupo II (el grupo se contrasta con MATCH-00) |
| Jornada | 1 |
| Fecha del encuentro | 31/08/2026; distinta de la fecha de jornada del catálogo |
| Equipos | Teruel (`team_id=204`) – Real Madrid Castilla (`team_id=61`) |
| Marcador | 0–0 |
| Titulares | 11 por equipo |
| Suplentes | 7 Teruel, 10 Real Madrid Castilla |
| Entrenadores | Presentes en ambos equipos |
| Sustituciones | 9 entradas y 9 salidas, con minutos; no se emparejan jugadores |
| Tarjetas | 4 amarillas y 1 roja, con minutos |
| Goles | Ninguno; no se infiere ningún gol del penalti fallado |
| Penalti fallado | Rachad, minuto 43; icono fuente `PF`, título `Penalty Fallado` |
| Expulsión | Belevonis, minuto 90; icono fuente `TV`, título `Expulsión` |
| Otros iconos de evento | Ninguno desconocido en el bloque semántico aceptado |

Los 39 IDs de futbolistas presentes en titulares y suplentes existen en el directorio de jugadores local, que declara 1.709 IDs de inventario y 1.708 perfiles individuales compactos completos. Por tanto, la vista previa puede habilitar los 39 enlaces internos por ID verificado. El directorio marca asociación deportiva; el enlace no implica que el jugador siga actualmente en el equipo.

La ausencia de goles es coherente entre el marcador 0–0 de MATCH-00 y las estructuras de gol del documento. El penalti fallado es un evento distinto y no modifica el marcador. La expulsión se interpreta por el par exacto clase/título observado; un icono no reconocido sigue provocando fallo semántico, sin degradarlo a otra categoría.

## Comparación del núcleo semántico

| Dato | 272582 — Jaén 3–3 Villarreal B | 272525 — Teruel 0–0 Castilla |
| --- | ---: | ---: |
| Titulares | 11 + 11 | 11 + 11 |
| Suplentes | 12 + 9 | 7 + 10 |
| Goles | 6 (4 gol, 2 penalti) | 0 |
| Amarillas | 7 | 4 |
| Rojas | 0 observadas | 1 |
| Sustituciones | 10 entradas + 10 salidas | 9 entradas + 9 salidas |
| Penalti fallado | No observado | 1 |

Ambos documentos se interpretan con el mismo parser, pero con lectores de procedencia diferenciados: el formato histórico MATCH-01B y el formato de artefacto de campaña. No se convierte metadata de campaña al formato antiguo. Los minutos añadidos se conservan literalmente y se validan contra el HTML original.

La segunda página expuso dos valores reales que no estaban en el vocabulario del parser: `PF` / `Penalty Fallado`, ahora `missed_penalty`, y `TV` / `Expulsión`, ahora `red_card`. También se corrigió la comparación del día/mes del título para exigir ceros iniciales; el parser esperaba `31/8/2026` mientras el HTML publica `31/08/2026`.

## Vista previa local

La lectura de campaña se integra en `load_local_discovery_preview()`. Primero verifica generación, manifiestos, inventario, ledger, autorización, resolución, IDs y hashes; después invoca el núcleo semántico común. Un error de integridad o semántica produce un fallo explícito, no una ficha deportiva vacía ni una respuesta pública. La ruta auxiliar de vista previa continúa limitada a loopback y fuera del OpenAPI público; la ruta pública del partido no incorpora esta captura.

Para iniciar FastAPI configurado con la segunda captura:

```bash
export FDH_LOCAL_DATA_ROOT="$HOME/FootballDataHub-data"
export FDH_MATCH_LOCAL_PREVIEW_ARTIFACT="$FDH_LOCAL_DATA_ROOT/matches/details/campaigns/match-detail-sample-campaign-67fdc4b4fac66b82/candidates/pf-2026-27-group-ii-bdfutbol-272525/artifacts/discovery-20261018T112656Z-4543b211"
PYTHONPATH=src:apps/api .venv/bin/uvicorn football_data_hub_api.main:app --host 127.0.0.1 --port 8001
```

En otra terminal, configura el dashboard y abre la ficha:

```bash
cd apps/dashboard
VITE_API_BASE_URL=http://127.0.0.1:8001 npm run dev -- --host 127.0.0.1 --port 5175
```

`http://127.0.0.1:5175/matches/pf-2026-27-group-ii-bdfutbol-272525?preview=local`

El componente existente presenta alineaciones, suplentes, entrenadores y cronología, incluida la etiqueta «Penalti fallado». Para volver a la ficha de 272582, se debe reiniciar FastAPI con `FDH_MATCH_LOCAL_PREVIEW_ARTIFACT` apuntando al artefacto histórico. Al finalizar la revisión, reiniciar FastAPI sin esa variable. No se inicia ningún proceso ni se abre esta ruta como parte de la validación de este hito.

## Verificaciones y límites

Pruebas optativas sobre el almacén local:

```bash
FDH_MATCH_01C_D2_INTEGRATION=1 PYTHONPATH=src:apps/api .venv/bin/pytest -q tests/integration/test_match_campaign_preview_d2.py
FDH_MATCH_01C_INTEGRATION=1 PYTHONPATH=src:apps/api .venv/bin/pytest -q tests/integration/test_match_detail_semantic_latest.py
```

Estas pruebas no hacen HTTP ni inician navegador. La segunda ficha solo se ha validado semánticamente y mostrado como vista previa local; para publicarla hacen falta una revisión independiente y el flujo de aprobación de MATCH-02. No hay evidencia para emparejar entradas y salidas individuales ni para inferir información que no aparece en la ficha. Los datos de un evento se conservan con los nombres, IDs y minutos que ofrece la fuente.
