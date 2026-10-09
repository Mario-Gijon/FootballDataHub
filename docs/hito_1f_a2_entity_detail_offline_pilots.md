# Hito 1F-A2 — Pilotos offline de fichas individuales de entidades

## Alcance y método

Auditoría y parsing exclusivamente offline de las cuatro capturas individuales ya presentes. No se abrió navegador, no se usó CDP, no se hicieron peticiones y no se adquirieron páginas. Los snapshots raw no se modificaron. El acceso live sigue en NO-GO; este hito no lo revalidó.

Se inspeccionaron `metadata.json`, `rendered.html`, `inventory.json` y `summary.json` de cada snapshot. Antes de parsear, el nuevo validador comprueba HTTPS y host BDFutbol, coincidencia de tipo e ID entre URL solicitada y final, HTTP 200, `access_status=VALID`, tamaño y SHA-256 exactos, ausencia de marcadores de desafío/error y estructura deportiva propia de la familia de página. Una captura rechazada no se incluye en los exports.

## Capturas comprobadas

| Tipo e ID | URL final | Título de página / identidad visible | Captura UTC | HTML raw | SHA-256 | Inventario DOM |
|---|---|---|---|---:|---|---|
| Partido `269462` | `https://www.bdfutbol.com/es/p/p.php?id=269462` | `Avilés Industrial - Lugo (1 - 2) 02/10/2026 \| BDFutbol` | `2026-10-08T12:13:55.280292+00:00` | 916.421 bytes | `890fac0cda4c7bfcb5cc9d2f2c7ca086c9072066007aabe8261e8f60c361e544` | `ready_state=loading` |
| Entrenador `l1835` | `https://www.bdfutbol.com/es/l/l1835.html` | `Manolo Herrero, Manuel Herrero Galaso - Entrenador \| BDFutbol`; H1 `Manolo Herrero` | `2026-10-08T12:14:28.259650+00:00` | 982.012 bytes | `abda5aba088dca2415260a75e1fbb5aceb9034cc2c0421ab9021a52d7d3d4233` | `interactive` |
| Árbitro `602267` | `https://www.bdfutbol.com/es/r/r602267.html` | `Pacheco Cotero, Mario Pacheco Cotero - Árbitro \| BDFutbol`; H1 `Pacheco Cotero` | `2026-10-08T12:14:30.402621+00:00` | 923.529 bytes | `acde88800929f191aea71bcc56baf86d3cace69a09707c401e9f438edaaa1511` | `complete` |
| Estadio `81` | `https://www.bdfutbol.com/es/s/81.html` | `Suárez Puerta \| BDFutbol`; H1 `Suárez Puerta` | `2026-10-08T12:14:32.678734+00:00` | 924.469 bytes | `d4808821d4279a03530812b673aaca7159065508c1eb47bbd28f798bf104bacc` | `complete` |

Las cuatro metadata indican HTTP 200 y `VALID`; se recalcularon los cuatro hashes sobre los bytes de `rendered.html` y todos coinciden con metadata. Las rutas locales son:

- `data/raw/bdfutbol/luna_audit/20261008T121346.469132Z/match_269462/`
- `data/raw/bdfutbol/luna_audit/20261008T121419.346588Z/coach_manolo_herrero/`
- `data/raw/bdfutbol/luna_audit/20261008T121419.346588Z/referee_pacheco_cotero/`
- `data/raw/bdfutbol/luna_audit/20261008T121419.346588Z/stadium_suarez_puerta/`

El estado `loading` que registra el inventario del partido es una limitación de la captura. Aun así, el HTML conservado sí contiene el título, H1, bloque `.hero-partit`, enlaces a ambos clubes, el marcador, las secciones de goleadores y las tablas de jugadores y entrenadores; por ello pasa la validación de esta familia. La discrepancia queda documentada para endurecer la espera del navegador en futuras capturas. No se infiere que todas las peticiones auxiliares o recursos visuales se hayan completado.

## Datos observados por entidad

### Partido 269462

- Título parseado con el patrón comprobado en el HTML: local `Avilés Industrial`, visitante `Lugo`, marcador `1–2`, fecha raw `02/10/2026` y fecha estructurada `2026-10-02`.
- El bloque `.hero-partit` conserva valores fuente etiquetados como `Competición` (`1ª RFEF`), `Jornada` (`Jornada 6`), `Estadio` (`Suárez Puerta (Avilés)`) y `Fecha` (`Viernes 02/10/2026 (19:00)`). La URL enlazada de competición queda como enlace raw porque su contrato no se normaliza aquí. Se observan enlaces explícitos a los clubes `e81`, `e76`, estadio `81` y árbitro `r602267`.
- Se conservaron 6 tablas `.taula_estil`, 52 filas de origen y 278 celdas, incluidos valores vacíos, orden, clases responsive y enlaces a personas. Se conservaron también las filas de entrenadores Yago Iglesias (`l104929`) y Borja (`l330`). Las filas/celdas no se convierten en alineaciones semánticas ni participaciones certificadas: el HTML fuente sigue siendo la evidencia para esa interpretación.
- El texto de eventos visible en el encabezado preserva `1-0 Santamaría 5'`, `1-1 Costa 68'` y `1-2 Godoy 90+11'`, con los enlaces de jugador disponibles. Se conserva como texto fuente; no se añadieron eventos normalizados ni tarjetas inferidas.
- **Contraste histórico completado:** el índice `matches_from_embedded_data.json.gz` del export válido de clubes parser 1.7.0 (`snapshot-7ffcbd5f11c8e83fdae4-parser-1.7.0`) contiene el mismo `match_id=269462`. Coinciden URL, fecha, IDs de local/visitante (`e81`/`e76`), nombres, marcador 1–2, competición raw `1rf`, jornada `Jornada 6` y árbitro raw `602267`. La fila consolidada contiene dos observaciones de clubes. No hubo discrepancia que corregir.

### Entrenador l1835

- La ficha se identifica visualmente como Manolo Herrero; su H1 es `Manolo Herrero`, mientras que el título incluye el nombre extendido `Manuel Herrero Galaso`.
- La tabla `.traject` tiene cabecera, 14 filas de trayectoria y una fila final `Total` (16 filas de origen, 13 celdas por fila). Se guardan literalmente las cabeceras `Temp`, `Equipo`, `País`, `Div`, `Edad`, `P`, `PG`, `PE`, `PP`, `TA`, `TR` y las columnas sin etiqueta; no se expanden abreviaturas.
- El JavaScript contiene los arrays fuente `trajectoria` (14 elementos), `competicions` (4 grupos) e `internacional` (vacío). Se guardan nombres de clave y valores sin convertirlos en una carrera completa ni atribuir semántica adicional a códigos. Hay una segunda tabla de títulos; se conserva su contenido raw.
- Se conservan las rutas de trayectoria y los IDs de equipo-temporada efectivamente enlazados. La ficha no demuestra por sí sola cobertura de todos los clubes, temporadas o partidos de su carrera.

### Árbitro r602267

- La ficha se identifica como Pacheco Cotero; el título incluye `Mario Pacheco Cotero` y la categoría `Árbitro`.
- La tabla `.traject` contiene cabecera, cuatro filas de temporada y una fila `Total` (6 filas; cabeceras raw `Temp`, `País`, `Div`, `Edad`, `PA`, `VL`, `E`, `VV`, `TA`, `TA PP`, `TR`, `TR PP`, además de celdas vacías). No se expanden estas abreviaturas.
- Los scripts conservan `trajectoria` (4 elementos), `competicions` (1 grupo) e `internacional` (vacío). Esta captura de perfil no aporta una lista de designaciones individuales: se conserva como pendiente, sin derivar partidos desde los agregados.

### Estadio 81

- H1 `Suárez Puerta`. La ficha incluye las secciones fuente `Equipo Local`, `Competiciones`, `Top Visitantes`, `Equipos Visitantes`, `Temporadas`, `Primer partido oficial`, `Nombres` y `Ubicación`.
- La sección de nombres conserva la tabla con `La Exposición (<1955)` y `Suárez Puerta (>1956)`. `Primer partido oficial` muestra raw `19/10/1947 Copa del Rey Avilés 3 1 Gijonés`.
- El gráfico `Top Visitantes` tiene el array fuente `dataVisit` con 15 elementos (`equip`, `partits`), guardados como valores raw. Los listados por equipo, competición y temporada se conservan en el texto de sus secciones.
- El JavaScript de Leaflet contiene literalmente centro y marcador `[43.557,-5.930]`, zoom `15` y popup `Suárez Puerta`; el export los marca `SOURCE_LITERALS_ONLY`. No se verificó la geolocalización externamente ni se atribuyeron capacidades o partidos al estadio por proximidad.

## Contratos, cobertura y exports

Se añadieron [individual_entity_pages.py](../src/football_data_hub/parsers/individual_entity_pages.py) y [parse_bdfutbol_entity_pages_offline.py](../scripts/parse_bdfutbol_entity_pages_offline.py). El parser común admite las cuatro familias observadas, valida cada snapshot antes de usarlo y crea un registro tipado separado para partido, entrenador, árbitro y estadio. Conserva provenance con URL solicitada/final, timestamp, estado, HTTP, ruta raw relativa, tamaño y SHA-256.

Las tablas conservan todas las celdas en orden, incluidos `-`, vacíos y clases que marcan columnas opcionales u ocultas (`resp_off`, `d-none`, `d-md-none`), además de enlaces e IDs fuente. El parser recoge títulos y secciones, relaciones de enlace con semántica `LINK_OBSERVED_ONLY`, referencias de imagen sin clasificarlas como foto deportiva/interfaz, variables JSON embebidas y literales de mapas detectados. El HTML original sigue siendo la fuente completa para reprocesamiento. Cada registro queda como `PARTIAL_STRUCTURED_WITH_RAW_PRESERVATION`; nunca se marca una entidad semánticamente completa.

El comando escanea offline las capturas individuales bajo `data/raw/bdfutbol`, rechaza entradas inválidas con motivo, procesa solo snapshots válidos y escribe exports gzip deterministas separados por tipo. El directorio se identifica por versión del parser y huella del conjunto de inputs; si ya existe, compara cada byte y lo reutiliza solo cuando el contenido coincide. Si los mismos inputs intentan producir otro contenido, falla en lugar de sobrescribir.

Export generado:

`data/parsed/bdfutbol/entity_detail_pilots/parser-0.1.1-source-4b97a04a5c1b8a6f/`

Contiene `match_details.json.gz`, `coach_details.json.gz`, `referee_details.json.gz`, `stadium_details.json.gz`, `coverage.json.gz`, `errors.json.gz` y `summary.json`. Los siete archivos ocupan 27.312 bytes en total. Hubo 4 snapshots candidatos, 4 válidos (uno por tipo) y 0 rechazos. No se copiaron HTML al parsed ni se modificaron exports históricos. Las salidas están bajo `data/parsed`, ignorado por Git.

Comando reproducible desde la raíz:

```bash
PYTHONPATH=src .venv/bin/python scripts/parse_bdfutbol_entity_pages_offline.py --repo-root .
```

Puede procesar futuras capturas de las mismas familias; el `source_fingerprint` crea otro directorio versionado cuando cambian sus inputs. No adquiere datos.

## Pruebas, límites y recomendación

Las pruebas añadidas en `tests/test_individual_entity_pages.py` usan los cuatro snapshots reales para integridad, identidad, tablas, claves embebidas y determinismo. Los casos de estructura incompleta, URL de otro ID, HTTP 403/desafío y hash incorrecto son fixtures **sintéticos**, no afirmaciones de páginas reales nuevas. También se verifica que los exports idénticos se reutilizan byte por byte y que un contenido distinto no puede sobrescribir la misma versión.

Resultados:

- Pruebas específicas: **13 passed**.
- Suite completa: **288 passed**. Se ejecutó con permiso loopback porque `test_loopback_port_valid` abre un socket local; no hubo tráfico externo.
- Ruff sobre los tres archivos Python modificados: **All checks passed**.
- `git diff --check`: limpio.

Limitaciones: solo hay una ficha individual por tipo; no se prueba su variación entre entidades. Trayectorias, designaciones, partidos, datos geográficos y disponibilidad global no se consideran completos por aparecer en estas cuatro páginas. No se descargaron ni verificaron fotografías; los centenares de referencias `<img>` por página incluyen interfaz y elementos sin clasificar. El partido indica `ready_state=loading` en el inventario, aunque la estructura deportiva principal sí está presente. No se tocaron Dev Explorer, scrapers, snapshots ni exports anteriores.

**Recomendación:** GO para diseñar los siguientes parsers offline y preparar cobertura por campos; **NO-GO para nuevas capturas live mientras persista el desafío de acceso**. Cuando se autorice el acceso, el siguiente piloto debe validar una sola ficha nueva por tipo y comparar sus variaciones estructurales antes de ampliar lotes.
