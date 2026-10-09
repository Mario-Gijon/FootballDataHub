# Hito 1E-B1-H — Cobertura de interacciones de jugador

Fecha de investigación: 2026-10-09. Alcance live limitado a Manu Pedreño (`j23751`), reutilizando las cuatro vistas canónicas y capturando una variante representativa de Estadísticas.

## Acceso y evidencia

Se reutilizó `BrowserSessionManager` con Brave gestionado en Xvfb, Playwright conectado por CDP y el perfil autorizado existente. `BDFutbolAccess` validó las páginas deportivas como `VALID`, HTTP 200, con URL final y título esperados. No apareció desafío Cloudflare/CAPTCHA. No se copiaron credenciales o cookies. No se usaron clientes HTTP alternativos.

Las capturas canónicas de `j23751` se reutilizaron; no se sobrescribieron:

| Vista | URL | Snapshot base existente | SHA-256 |
|---|---|---|---|
| Perfil/Trayectoria | `https://www.bdfutbol.com/es/j/j23751.html` | `20261009T092022.507033Z/j23751/profile` | `b06394be5ffc6809b8f74f19871064d7e6ee7a347fdbf2b7e63da43cb4267752` |
| Estadísticas | `https://www.bdfutbol.com/es/j/j23751.html?p=stats` | `20261009T092115.395034Z/j23751/statistics` | `5a4b0aa36cba0898fcb7316e11051e1f24914dcf96cec76fd3ffa38959bec2b0` |
| Partidos | `https://www.bdfutbol.com/es/p/j23751.html` | `20261009T092115.395034Z/j23751/matches` | `8e1c9aaf2c299390a6f54fcff0a6c850719ab87fbf240e5305b96961b801f29e` |
| Rivales | `https://www.bdfutbol.com/es/p/jr23751.html` | `20261009T092115.395034Z/j23751/rivals` | `1a006b47e8bf9fdc20616327909307899323c6c44278fb1aac6f147433ea4813` |

También se reutilizaron las capturas válidas de las cuatro vistas de Morillas. Son evidencia de snapshots previos; las conclusiones de interacción que siguen proceden de lectura live de `j23751`.

## Interacciones verificadas

Las opciones representativas se seleccionaron una a una. En las interacciones descritas no cambió la URL y no se observó petición deportiva `fetch`/XHR. Durante la ventana de observación del Perfil también aparecieron tres recursos auxiliares de Google reCAPTCHA con HTTP 200; no hay evidencia para atribuirlos a una selección concreta. La inspección no envió formularios, comentarios ni modificaciones.

| Vista/control | Selección observada | Efecto en vivo | ¿Añade datos respecto al snapshot base? |
|---|---|---|---|
| Perfil: `sel-equip` | UD Ibiza (`414`) | Mantiene las filas de `.traject`; valores estadísticos de filas no coincidentes pasan a guion. URL sin cambios; no se observó XHR deportivo. | No. El snapshot base conserva la tabla completa y sus celdas originales. |
| Perfil: `sel-pais` | Eslovenia | Mantiene las filas; cambia a guion parte de los valores estadísticos ajenos al filtro. URL sin cambios; no se observó XHR deportivo. | No se observaron filas nuevas; el filtro reduce lo mostrado. |
| Estadísticas: `cats_milestones` | `1rf` | Cambia el panel activo de `#mil_2aB` a `#mil_1rf`; no cambia URL ni genera petición adicional. | No. Las tablas del panel `1rf` ya estaban en el DOM inicial, aunque colapsadas. |
| Estadísticas: botón «Equipos» | vista de equipos | Alterna la visibilidad entre las tablas por competición y por equipo, que ya estaban en el DOM. Sin cambio de URL o red. | No. Es control de presentación. |
| Partidos: `jug` | `si` / `no` | Cambia el valor seleccionado del filtro. Sin URL ni red. | No aparecieron filas individuales. |
| Partidos: `pgep` | `pg`, `pe`, `pp` (probadas individualmente) | Cambia el valor seleccionado. Sin URL ni red. | No aparecieron filas individuales. |
| Partidos: `comp`, `temp`, `equip`, `rival` | muestras `1rf`, `2026-27`, un equipo y un rival | Actualiza el estado de cada control; no cambia URL ni genera petición. | No aparecieron filas individuales. No se probaron combinaciones. |
| Rivales: `filtre-cat` | `1rf` | Reduce las filas DOM de `t5/t6/t7` a 722/49/36, contando cabeceras. URL sin cambios, sin petición. | Subconjunto de tablas ya presente en el snapshot base. |
| Rivales: `filtre-temp` | `2026-27` | Reduce `t5/t6/t7` a 34/3/3 filas DOM, incluidas cabeceras. Sin URL/red. | Subconjunto de tablas ya presente. |
| Rivales: `filtre-dem` | `DEF` | Reduce `t5/t6/t7` a 408/89/73 filas DOM, incluidas cabeceras. Sin URL/red. | Subconjunto de tablas ya presente. |

Los filtros de Partidos observados en la vista de `j23751` ofrecen 2 opciones en `jug`, 3 en `pgep`, 7 en `comp`, 8 en `temp`, 8 en `equip` y 95 en `rival`. En Perfil, `sel-equip` presenta 8 opciones y `sel-pais` 3; `cats_milestones` ofrece 5 opciones. En Rivales, los controles observados presentan 7 opciones de competición, 8 de temporada y 5 de demarcación. No se recorrieron todas las opciones.

### Partidos y datos individuales

El panel `#pest1` está inicialmente oculto. Al inspeccionarlo, `#tpartits` conservó una sola fila de cabeceras y cero filas de partidos; el parser identifica 19 columnas. Entre sus etiquetas raw figuran fecha, temporada, competición, tipo, local, resultado, visitante y abreviaturas de estadísticas (`PT`, `PC`, `PS`, `PX`, `PI`, `C`, `Min`, `TA`, `TR`, `G`, `GE`). No se asigna significado no demostrado a esas abreviaturas. Las columnas configurables/responsive permanecen conservadas como celdas y cabeceras raw.

El HTML base contiene además `window.P` con 259 tuplas. Su estructura semántica no se ha validado; queda como contenido raw-only y no se convirtió en encuentros. Los filtros de Partidos probados no materializaron filas en `#tpartits`, así que no se fabricaron partidos a partir de agregados.

## Variante de Estadísticas capturada

Se hizo una navegación live adicional mediante el colector existente con `cats_milestones=1rf`. Resultado: `VALID`, HTTP 200, URL final exacta. El inventario registró el selector seleccionado y ninguna petición asociada.

- Snapshot: `data/raw/bdfutbol/20261009T100250.411360Z/j23751/statistics/variants/acf2d8bef2c0`
- `snapshot_kind`: `FILTERED_VARIANT`; `is_base_view_snapshot`: `false`
- Parámetros: `{"cats_milestones":"1rf"}`
- HTML: 974.356 bytes; SHA-256 `e4739e3eaeacb0d6692cb872632a6de443cd26ccc5d49ccaaeb1910f080dfc91`
- Resultado de adquisición: `CAPTURED_VALID_VARIANT`, `BASELINE_VARIANT`; carpeta raw completa: aproximadamente 1,9 MB.
- Parser: `PARSED`; 9 tablas: estadísticas por competición, por equipo y 7 tablas de hitos.
- El parser conserva 94 filas estadísticas en esta variante. La comparación celda a celda de las tablas con la captura base da contenido idéntico; solo cambia el panel colapsado que tiene `show`. Las tres filas visibles bajo `1rf` (dos participaciones y un gol) ya estaban en el HTML base dentro del panel oculto.

La variante se conserva de forma inmutable y separada de la vista canónica. Por tanto, es evidencia de interacción y de captura reproducible, pero **no añade filas deportivas** frente al snapshot base.

## Fotografías, galerías y columnas

La ficha contiene tres referencias de fotografía del jugador en `#carousel` (`23751.jpg`, `23751b.jpg`, `23751c.jpg`) con referencias de tamaño/versión. El carrusel ofrece controles anterior/siguiente. Se catalogaron las referencias sin descargar imágenes. `Rectangle6.webp` corresponde al arte de cabecera de la interfaz, no a una fotografía deportiva. El bloque comunitario indica cero fotos y muestra un formulario para subir; no se interactuó con él.

El panel configurable de Perfil contiene 26 opciones de columnas. Partidos incluye 12 identificadores de columnas configurables; en el HTML conservado no todos tienen etiqueta legible. No se cambiaron preferencias ni se recorrieron esas columnas. Las columnas raw ya presentes siguen en los snapshots.

## Cambios reutilizables

Se extendió el flujo existente, sin crear otro colector:

- `scripts/scrape_bdfutbol_players.py` acepta `--filter CONTROL=VALOR`, junto con una única `--view statistics`. La captura queda bajo `player/view/variants/<hash-de-parámetros>`, nunca en el directorio canónico.
- El colector solo permite opciones de `cats_milestones` comprobadas (`2aB`, `1rf`, `CHA`, `CNF`, `COP`). Verifica que el control exista, que la selección quede activa, que la URL no cambie y que no aparezcan desafío ni respuesta denegada. En caso de desafío detiene el lote y no guarda la respuesta como snapshot deportivo.
- Metadata identifica `FILTERED_VARIANT`, filtros, modo de interacción, solicitudes observadas y hash. Las próximas capturas y reusos también enlazan directorio y hash del snapshot canónico correspondiente. La captura live de este hito se creó antes de añadir ese enlace explícito; sigue diferenciada por `is_base_view_snapshot=false`, su subdirectorio `variants/` y sus parámetros, y no se alteró retroactivamente.
- `parse_player_snapshot_variants_inventory()` procesa cada conjunto de parámetros por separado. La capa de exports mantiene las filas canónicas sin variantes y añade `filtered_variants.json.gz`/`.csv.gz` y `variants/<jugador>/<vista>/<hash>.json.gz` con fuente y cobertura. No se copia HTML al export.
- `parse_bdfutbol_players_offline.py` vuelve a procesar las variantes localmente. Parser actualizado a `0.2.2`; exports versionados e inmutables.

Comandos para repetir la adquisición o crear una captura nueva de la misma variante:

```bash
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py live \
  --player-id j23751 --view statistics --filter cats_milestones=1rf
```

Añadir `--refresh` al final para crear otro snapshot inmutable en lugar de reutilizar el existente. Para reprocesar offline y generar el export versionado:

```bash
PYTHONPATH=src .venv/bin/python scripts/parse_bdfutbol_players_offline.py
```

El export generado está en `data/parsed/bdfutbol/player_2026_27/compact/snapshot-1ee162d21e97dbd2c41f-parser-0.2.2` (aproximadamente 2,2 MB). Incluye una variante parseada aparte y deja declaradas las 4.128 vistas pendientes; no certifica completitud histórica.

## Pendiente y evaluación

- `VERIFIED`: acceso live y controles representativos de las cuatro vistas; no hubo desafío. Se verificó la ausencia de partidos individuales en `#tpartits` para `j23751` y Morillas.
- `VERIFIED`: los filtros de Rivales y Estadísticas inspeccionados son filtros/controles client-side sobre tablas ya incluidas en el HTML base. No se observaron llamadas de red deportivas en las interacciones probadas.
- `ARTIFACT_ONLY`: snapshots canónicos anteriores de Morillas y de las cuatro vistas de `j23751`; el raw conserva lo que el parser no interpreta.
- `NOT_TESTED`: combinaciones de filtros, paginación no presente en las muestras, otras temporadas/equipos/rivales, exportación de preferencias de columnas y apertura de fotos del carrusel. No se descargaron medios ni se adquirieron perfiles adicionales.
- `RAW_ONLY`: `window.P` y abreviaturas sin contrato semántico demostrado.

No se detectó una nueva estructura que requiera reinterpretar datos deportivos ni se añadieron encuentros. La infraestructura queda lista para adquirir variantes filtradas futuras sin mezclarlas con las vistas base; por lo observado en este piloto, los filtros actuales seleccionan u ocultan contenido ya capturado y no aumentan la cobertura deportiva.

## Validaciones

- Pruebas completas: **237 passed**.
- Ruff en todos los archivos Python modificados: **All checks passed**.
- `git diff --check`: **sin errores**.
- Export offline repetible y versionado; snapshots anteriores intactos. Sin commit ni push.
