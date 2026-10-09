# Hito 1F-A4 — Normalización semántica de entrenadores, árbitros y estadios

## Alcance y procedencia

Trabajo 100% offline en la rama rebuild/football-data-hub-v2. Se reutilizaron las
cuatro capturas individuales locales y el parser/export 0.2.0. No se abrió
navegador, no se hicieron peticiones, no se crearon capturas y no se alteraron
los HTML raw.

| Ficha | URL observada | Captura UTC | HTML | SHA-256 |
|---|---|---|---:|---|
| Entrenador l1835 | https://www.bdfutbol.com/es/l/l1835.html | 2026-10-08T12:14:28.259650+00:00 | 982.012 B | abda5aba088dca2415260a75e1fbb5aceb9034cc2c0421ab9021a52d7d3d4233 |
| Árbitro 602267 | https://www.bdfutbol.com/es/r/r602267.html | 2026-10-08T12:14:30.402621+00:00 | 923.529 B | acde88800929f191aea71bcc56baf86d3cace69a09707c401e9f438edaaa1511 |
| Estadio 81 | https://www.bdfutbol.com/es/s/81.html | 2026-10-08T12:14:32.678734+00:00 | 924.469 B | d4808821d4279a03530812b673aaca7159065508c1eb47bbd28f798bf104bacc |

Las tres metadata locales declaran HTTP 200 y access_status=VALID; el cargador
recalculó los hashes y validó identidad y estructura antes de parsear. Los
directorios fuente están bajo
data/raw/bdfutbol/luna_audit/20261008T121419.346588Z/. Los tres directorios de
persona/estadio ocupan 7.814.468 bytes, incluyendo HTML, inventario, metadata,
resumen y captura de pantalla.

El partido 269462 usado solo para contrastar una relación conserva el HTML de
916.421 B y SHA-256
890fac0cda4c7bfcb5cc9d2f2c7ca086c9072066007aabe8261e8f60c361e544.
Su ficha enlaza directamente el estadio 81. Los hashes de los tres snapshots de
persona/estadio y de todos los archivos de los exports anteriores parser-0.1.1
y parser-0.2.0 se comprobaron antes y después; todos permanecieron idénticos.
El hash del HTML del partido se recalculó y coincide con metadata.

## Entrenador l1835 — Manolo Herrero

La tabla .traject contiene 14 filas de temporada, una fila Total y 13 columnas.
La cabecera publicada identifica Temp, Equipo, País, Div, Edad, P, PG, PE, PP,
TA y TR. Los atributos title amplían de forma explícita Div a “División”, P a
“Partidos”, PG a “Ganados”, PE a “Empatados”, PP a “Perdidos”, TA a “Tarjetas
amarillas” y TR a “Tarjetas rojas”.

- Se tiparon temporada y nombre de equipo como texto; edad, partidos, ganados,
  empatados y perdidos como enteros. Se preservan a la vez el valor raw, el
  encabezado/título, la clase de celda, el índice DOM y los enlaces.
- País tiene celda sin texto y una clase de bandera. Su valor España se
  incorpora desde trajectoria.flag solo después de alinear esa fila con la
  tabla.
- Las 14 filas de HTML coinciden en orden con las 14 entradas de JavaScript en
  temporada, nombre de equipo, código de equipo visible, división, edad y
  resultados. El estado general es
  ALL_ROWS_MATCHED_BY_ORDER_AND_VISIBLE_FIELDS.
- Cada temporada contiene enlace directo a un equipo-temporada, por ejemplo
  t2009-1049. Se conserva ese ID y URL como relación explícita. El código
  data-codi/codieq se conserva como código raw; no se transforma en ID de una
  ficha de club ni se inventa una relación entrenador-club separada.
- Las columnas sin encabezado, índices 3 y 12, siguen raw-only. También se
  conservan columnas responsive resp_off.
- En la primera fila, TA y TR muestran -, mientras los campos JavaScript tg y
  tv contienen 0. No se igualan: los guiones siguen siendo SOURCE_DASH, y tg/tv
  quedan entre las claves JavaScript no normalizadas.
- La fila Total tiene 10 celdas frente a 13 cabeceras; se conserva completa
  como totals_raw y no se asigna a estadísticas por posición.
- La sección explícita Títulos contiene una fila: “1 Liga 2a división B:
  2012-13”, con enlace directo a t2012-1349 y referencia de imagen lliga3.png.
  Se preserva el texto completo y el enlace, sin traducir el nombre de la
  imagen a un título adicional.
- El array competicions aporta 14 agregados por competición/temporada. Se
  estructuran pj, pg, pe y pp porque sus claves se contrastan con las columnas
  visibles de trayectoria. Las claves de competición (COP, PR2, etc.) y tokens
  como lbl_CopaRei se conservan raw; no se resuelven a fichas de competición.

No se afirma que las 14 filas representen toda la carrera del entrenador.

## Árbitro 602267 — Pacheco Cotero

.traject contiene cuatro filas de temporada y una fila Total. Sus 14 columnas
tienen dos cabeceras vacías (índices 2 y 13), que permanecen raw-only. Las
cuatro filas coinciden con trajectoria en temporada, división, edad, partidos
arbitrados, resultados locales/empates/visitantes y estadísticas de tarjetas.

Los title de la tabla demuestran las etiquetas completas: PA, “Partidos
Arbitrados”; VL, “Victorias locales”; E, “Empates”; VV, “Victorias visitantes”;
TA, “Tarjetas amarillas”; TA PP, “Tarjetas amarillas por partido”; TR,
“Tarjetas rojas”; y TR PP, “Expulsiones por partido”. Se conservan los códigos
y valores raw junto con sus números tipados. Los promedios siguen como
decimales (por ejemplo raw 0.00 → número 0.0).

El array competicions contiene un agregado de promoción con código raw PR3,
temporada 2025-26 y un partido. Su relación a competición permanece sin
resolver: no hay enlace directo a una ficha de competición en esa fila. La fila
Total tiene 12 celdas frente a las 14 cabeceras y también se conserva raw-only.
No se generan designaciones ni partidos individuales desde estadísticas
agregadas; no se crea ninguna designación individual.

## Estadio 81 — Suárez Puerta

El DOM presenta las secciones Equipo Local, Competiciones, Top Visitantes,
Equipos Visitantes, Temporadas, Primer partido oficial, Nombres y Ubicación.

- **Nombres:** se preservan La Exposición (<1955) y Suárez Puerta (>1956). Se
  separa nombre, operador y año publicado, pero no se convierten los
  comparadores en periodos inclusivos o fechas exactas.
- **Temporadas:** 29 filas con temporada, valor de badge y URL del filtro. La
  primera muestra 2026-27 y 3. Son valores publicados en la ficha; no
  certifican cobertura histórica.
- **Competiciones:** nueve rótulos con contadores y códigos de filtro raw
  (2aB, 1rf1, FED, etc.). Las URLs conducen a la vista filtrada de partidos,
  pero los códigos no se inventan como IDs de competición.
- **Equipos visitantes:** 94 filas fuente con ranking, enlace directo de club,
  contador y URL del filtro visitant. Las filas no se deduplican.
- **Top Visitantes:** dataVisit contiene 15 entradas. Nombre y contador
  coinciden en orden con las primeras 15 filas visibles; estado
  TOP_CHART_ROWS_MATCH_VISIBLE_LIST_BY_ORDER_NAME_AND_COUNT.
- **Equipo Local:** cuatro relaciones enlazadas a clubes, con badges de
  partidos y filtro local: Avilés Industrial, Avilés, Oviedo y Siero. La
  coincidencia de nombre no fusiona clubes ni permite atribuir todos sus
  partidos a este estadio.
- **Primer partido oficial:** la tarjeta estructurada publica 19/10/1947,
  Copa del Rey, Avilés 3–1 Gijonés, con enlace directo al partido 511636. Los
  clubes de esta tarjeta son texto, sin enlaces individuales, por lo que no se
  asignan IDs de club.
- **Ubicación:** el literal de Leaflet [43.557,-5.930] se convierte en latitud
  43.557, longitud -5.93 y zoom 15. El estado es
  SOURCE_DECLARED_NOT_EXTERNALLY_VERIFIED; no se hizo geocodificación ni
  verificación externa.

El recurso de relaciones contiene 99 referencias observadas: cuatro clubes de
la sección local, 94 clubes visitantes y un partido enlazado. Se preservan
repeticiones si aparecen en roles distintos. La ficha de partido 269462 enlaza
por separado al estadio 81; esto acredita esa relación puntual, no que todos
los partidos de un equipo se jueguen en el mismo estadio. No hay capacidad ni
otras características del estadio en la estructura normalizada.

## Contratos y exports

Se amplió el parser existente en
src/football_data_hub/parsers/individual_entity_pages.py a 0.3.0; no se creó un
parser paralelo. Los registros de entrenador, árbitro y estadio usan contrato
*_detail.v3. El contrato de partido sigue en
football_data_hub.match_detail.v2; una prueba compara sus campos deportivos
con el export 0.2.0 y confirma que conservan el mismo significado. El recurso
de cobertura usa schema v3 para incluir los nuevos recuentos semánticos.

El CLI existente scripts/parse_bdfutbol_entity_pages_offline.py genera exports
gzip separados para:

- coach_career.json.gz
- coach_honours.json.gz
- referee_career.json.gz
- stadium_history.json.gz
- stadium_visitors.json.gz
- stadium_competitions.json.gz
- stadium_relationships.json.gz
- stadium_location.json.gz

Cada recurso v1 retiene entity_id, URL, fuente, ruta snapshot, SHA-256, fecha,
estado de acceso y cobertura. Los registros semánticos incluyen valores raw,
valores tipados, claves/etiquetas fuente, índices DOM, IDs enlazados y estado
de interpretación. Las estructuras ambiguas permanecen raw-only.

Export generado:

data/parsed/bdfutbol/entity_detail_pilots/parser-0.3.0-source-4b97a04a5c1b8a6f/

Incluye 19 archivos, 89.279 bytes, cuatro snapshots válidos (uno por familia) y
cero rechazos. Una segunda ejecución obtuvo la misma huella
4b97a04a5c1b8a6f y reutilizó el directorio byte por byte. Los exports 0.1.1 y
0.2.0 permanecen intactos y disponibles; no se copió HTML al área parsed.

Comando reproducible:

    PYTHONPATH=src .venv/bin/python scripts/parse_bdfutbol_entity_pages_offline.py --repo-root .

## Pruebas y límites

- Parser focalizado: **29 passed**.
- Suite completa: **304 passed**. El sandbox restringido impidió inicialmente
  el socket localhost de test_loopback_port_valid; la repetición autorizada
  para ese socket local pasó. No se hicieron conexiones externas.
- Ruff en los tres archivos Python modificados: **All checks passed**.
- git diff --check: limpio.
- Las pruebas nuevas cubren las tres fichas reales, alineación HTML/JavaScript,
  columnas sin etiqueta, valores - y decimales, relaciones explícitas,
  agregados sin designaciones, filas duplicadas sintéticas, preservación del
  contrato A3 y export versionado/determinista. El fixture alternativo y la
  prueba de duplicados están identificados como sintéticos.

Solo existe una ficha real disponible por familia de personas/estadio. Por
tanto, la correspondencia observada queda demostrada para estas capturas, no
para todas las páginas BDFutbol. La cobertura de carrera, títulos, temporadas,
visitantes, competiciones, partidos y localización sigue siendo parcial o no
verificada; los inventarios de capturas tampoco sustituyen una revisión
interactiva de filtros. El estado de acceso live no se comprobó en este hito y
se mantiene el último estado conocido de bloqueo por CHALLENGE_REQUIRED.

**Siguiente paso:** GO para probar este parser offline con futuros snapshots
autorizados de estas familias y revisar variaciones antes de ampliar contratos.
NO-GO para reanudar adquisición live mientras siga vigente el bloqueo conocido;
este hito no intentó navegar ni renovar el acceso.
