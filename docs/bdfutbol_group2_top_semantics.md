# Destacados de BDFutbol — Grupo II 2026/27

## Estado del hito

| Funcionalidad | Estado | Evidencia |
|---|---|---|
| Acceso a `?tab=top` con Pure CDP | Verificado | HTTP 200, URL final igual a la solicitada, título de Grupo II 2026-27 y tablas/controles semánticos presentes. |
| Seis categorías del selector | Verificado | `#tipdest` contiene los valores 1, 2, 3, 4, 8 y 9. Las seis tablas están en el HTML inicial. |
| Ranking completo de goles | Verificado | Diez filas de `#jugs1` más 97 entradas de `DESTACATS_JS.LG`, añadidas localmente por `veure_mesdest()`. |
| Otras cinco categorías | Verificado con límite de fuente | Diez filas por tabla; no se observó un control «Ver todos» para ellas. Se exportan las filas disponibles, no se anuncian como rankings completos. |
| Series de progreso | Verificado | Arrays numéricos `DG`, `DM`, `DTG` y `DTV`; seis puntos, jornadas 1–6, en la captura actual. Cada serie termina en el total del ranking correspondiente. |
| Extranjeros y filtro por país | Verificado | 101 filas, 44 opciones del selector (Todos + 43 países); filtro local del DOM. |
| Límite de selección simultánea del gráfico | Pendiente | Tres jugadores aparecen seleccionados por defecto. No se confirmó un máximo simultáneo. |
| Fecha de referencia de la edad | Pendiente de la fuente | Se captura la edad mostrada; la tabla no ofrece la fecha de referencia. |
| Denominador de 19,65 % extranjeros | No publicado | Se conserva `denominator_count: null`; 514 es solo un denominador implícito inferido a partir del porcentaje redondeado. |

## Acceso y comportamiento observado

La navegación real a `https://www.bdfutbol.com/es/t/t2026-271rf2.html?tab=top` se hizo con la sesión existente `BrowserSessionManager` + `BDFutbolAccess`, backend `seleniumbase-pure-cdp`, Chromium y Xvfb externo. La respuesta fue HTTP 200; la página se validó como contenido deportivo del Grupo II de 2026-27, sin desafío observado. La URL no cambió al seleccionar tipos o filtrar países en la sesión exploratoria.

Los datos de categorías, extranjeros y evolución están en el documento inicial: tablas `#jugs1`, `#jugs2`, `#jugs3`, `#jugs4`, `#jugs8`, `#jugs9`, `#tab_estran` y el objeto `DESTACATS_JS`. El selector `#tipdest` llama a `canvi_dest()`, que delega en `veurejugs()`. No se identificó una respuesta de red independiente con rankings; por tanto el extractor descarga una página y parsea los datos embebidos. La conclusión se refiere a esta captura y no garantiza que BDFutbol mantenga igual su implementación.

«Ver todos» aparece en el área `#jugs1` y llama a `veure_mesdest()`. Esa función añade las 97 entradas de `LG` en el propio DOM; no hace una navegación de ficha. Así se obtienen 107 goleadores. No se encontró una expansión equivalente para minutos, tarjetas, jóvenes o veteranos: esas categorías aportan diez filas cada una.

La tabla de extranjeros se filtra mediante `#paisos_destacats` y `filtra_dest_pais()`, que compara la clase del país de cada fila y muestra/oculta registros localmente. No requiere consultar BDFutbol al cambiar el país. Los rankings usan checkboxes que invocan `grafs()`; los primeros tres aparecen marcados en cada categoría con gráfica. La página carga AmCharts 3.15.2. Para el dashboard conviene usar los números de `DESTACATS_JS`, nunca reconstruirlos desde píxeles.

## Diccionario de datos

### Catálogo mínimo de jugadores

`normalized/players.json` contiene una fila por `player_id` real de BDFutbol. Los IDs se leen de `../j/j<ID>.html` o, para las entradas añadidas de goles, de `LG`. Las URLs de ficha de esas entradas se forman con el mismo patrón de enlace usado por `veure_mesdest()`.

| Campo | Tipo / unidad | Origen y semántica |
|---|---|---|
| `player_id` | entero | ID numérico de BDFutbol, nunca nombre visible. |
| `display_name` | texto | Texto del enlace de jugador; `LG[2]` para goles añadidos. |
| `full_name` | texto o `null` | Span de nombre completo en `#tab_estran`; la mayoría de filas de ranking no lo publica. |
| `profile_url` | URL | Enlace `j<ID>.html`; en las entradas de `LG`, ruta construida según la función fuente. |
| `photo_url` | URL o `null` | `img.mini-foto-jugador`; para `LG`, regla documentada en `veure_mesdest()` a partir del ID y del indicador de imagen. |
| `nationality_code` | texto o `null` | Clase CSS del país, por ejemplo `espanya` o `argentina`. |
| `nationality` | texto o `null` | Texto del selector `#paisos_destacats`; España se etiqueta mediante la clase observada `espanya`. |
| `position_code` | texto o `null` | Clase CSS: `por`, `def`, `mig`, `dav`. |
| `position_name` | texto o `null` | Interpretación verificada: Portero, Defensa, Centrocampista, Delantero. |
| `age_years` | entero o `null`, años | Columna `Edad`; valor que muestra la página en la captura. No se conoce la fecha de referencia. |
| `team_id`, `team_name`, `team_url`, `crest_url` | ID/texto/URL | Enlace al catálogo existente de equipos mediante el nombre exacto del archivo del escudo. No se copia un segundo catálogo. |

Para formar el cruce se compara el basename del escudo de la página (`i/eg/<asset>`) con `crest_url` del catálogo de equipos RES-01. Los 217 jugadores deduplicados quedaron asociados a IDs de equipo del catálogo. La captura conserva `source_capture_id`, fecha y SHA-256 de ese catálogo.

### Rankings individuales

`normalized/rankings.json` conserva una fila por jugador y categoría. `rank` es el orden de filas del HTML; no es un número mostrado por BDFutbol. Para goles, el orden continúa con las entradas `LG` después de las diez filas HTML. `source_record` diferencia `html_table` de `destacats_js_lg`.

| Selector | Categoría | Métrica normalizada | Unidad | Complemento |
|---:|---|---|---|---|
| `1` | `goals` | `goals` | goles | Tabla inicial más `LG`; 107 registros en la captura. |
| `2` | `minutes` | `minutes_played` | minutos | 10 filas expuestas. |
| `3` | `yellow_cards` | `yellow_cards` | tarjetas | 10 filas expuestas. |
| `4` | `red_cards` | `red_cards` | tarjetas | 10 filas expuestas. |
| `8` | `youngest` | `age_years` | años | Orden por edad menor; `matches_played` viene de la columna `PJ`. |
| `9` | `oldest` | `age_years` | años | Orden por edad mayor; `matches_played` viene de `PJ`. |

En las categorías 1–4, `graph_selected_by_default` refleja el atributo HTML `checked` de cada checkbox. En jóvenes y veteranos ese campo es `null` porque las tablas no tienen esos controles. Los valores cero presentes en la fuente se conservan como cero; las estadísticas no publicadas se representan como `null`.

### Progreso

`normalized/progress.json` tiene una serie por jugador y categoría. Los IDs de arrays se alinean con el orden del ranking correspondiente: `DG` con goles (10 filas + 97 `LG`), `DM` con minutos, `DTG` con amarillas y `DTV` con rojas. Cada valor es acumulado y numérico. El array no incluye una columna de jornada explícita; el gráfico de la página usa `categoryField: jornada` y sus seis categorías actuales son 1–6. El parser asigna índices consecutivos desde J1 y conserva esa inferencia en este contrato. La validación confirma que el último punto de cada serie coincide con el total publicado del jugador.

Hay 137 series (107 de goles y diez para cada una de las otras tres métricas), con 822 puntos para las seis jornadas disputadas de esta captura. Jóvenes y veteranos no tienen series en el objeto fuente y no se exportan series para ellas.

### Extranjeros

`normalized/foreigners.json` combina el catálogo compartido del jugador con `matches_played`, `minutes_played`, `goals`, `yellow_cards` y `red_cards`. El orden de columnas se verifica contra los encabezados de `#tab_estran`; los ceros visibles son valores reales. La captura tiene 101 IDs únicos y todos tienen código de país distinto de `espanya`.

La fuente muestra 101 y 19,65 %. Su selector tiene 44 opciones: «Todos» con valor vacío y 43 códigos de país. El porcentaje parece corresponder a 101/514 (19,6498 %), pero BDFutbol no publica en esta sección el denominador ni define de forma explícita la población usada. El contrato guarda `denominator_count: null` e `implied_denominator_count: 514`, marcado como inferencia. “Extranjero” describe la clasificación de nacionalidad de la página, no una conclusión jurídica sobre ciudadanía.

## Completitud de la captura

| Datos que BDFutbol expone en la página | Capturados |
|---|---:|
| Categorías del selector | 6/6 (100 %) |
| Filas de rankings disponibles en este estado | 157/157 (100 %): 107 goles + 5 × 10 |
| Jugadores únicos tras cruzar categorías y extranjeros | 217 |
| Registros de extranjeros publicados | 101/101 (100 %) |
| Series numéricas publicadas | 137/137 (100 %) |
| Valores de progreso de seis jornadas | 822/822 (100 %) |

El 100 % se refiere a registros disponibles en la pestaña observada. No significa que se hayan obtenido todos los jugadores de la competición para minutos, tarjetas, jóvenes o veteranos: la fuente solo muestra diez por categoría. No se visitaron fichas individuales ni se completaron rankings ausentes.

## Archivos y ejecución

La captura versionada está en:

`data/exports/bdfutbol/group2_top/20261010T155145.195266Z-c5b031a6/`

La captura exploratoria anterior (`20261010T154807.184240Z-b71486ef`) se conserva en su propio directorio. La más reciente se obtuvo además ejecutando la nueva ruta CLI de adquisición; las capturas no se fusionaron ni sobrescribieron.

- `raw/source.html`: documento completo válido.
- `raw/access.json`: diagnóstico real de acceso y datos del navegador.
- `metadata/capture.json`: procedencia, integridad, contexto y enlace al catálogo de equipos.
- `normalized/players.json`, `rankings.json`, `progress.json`, `foreigners.json`.
- `validation/results.json`: recuentos, avisos y errores.

Normalización offline reproducible de la captura:

```bash
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_group2_top.py \
  --snapshot data/exports/bdfutbol/group2_top/20261010T155145.195266Z-c5b031a6/raw/source.html \
  --access-report data/exports/bdfutbol/group2_top/20261010T155145.195266Z-c5b031a6/metadata/capture.json
```

Nueva captura (si el acceso sigue permitido), con Xvfb externo y el perfil autorizado:

```bash
xvfb-run -a -s '-screen 0 1920x1080x24' env PYTHONPATH=src \
  .venv/bin/python scripts/scrape_bdfutbol_group2_top.py \
  --profile "$HOME/.football-data-hub-chromium-pure-cdp"
```

Una respuesta de desafío o denegación detiene la adquisición. La CLI solo crea el nuevo directorio después de que acceso, parsing y validación hayan terminado correctamente; nunca sobrescribe una captura anterior.

## Integración futura en FastAPI

FastAPI podrá cargar el JSON normalizado sin navegador y entregar:

- Catálogo mínimo `players` y rankings por `category` con su límite de cobertura.
- `progress` por categoría, jornada y jugador, incluyendo `graph_selected_by_default`.
- `foreigners` con las opciones de país para filtros locales.
- Metadatos de captura (`captured_at_utc`, `capture_id`, fuente, versión y catálogo relacionado) para mostrar la fecha de actualización.

El filtro de países, el cambio entre seis rankings y la selección de líneas del gráfico se pueden resolver con los datos ya servidos. Esta captura no incorpora cambios en API ni frontend.
