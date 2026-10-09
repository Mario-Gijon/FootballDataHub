# Hito 1F-A3 — Extracción deportiva de detalle de partido

## Alcance y método

Trabajo exclusivamente offline sobre la captura ya conservada de match_269462. No se abrió Brave/CDP, no se hicieron peticiones, no se crearon snapshots y no se tocaron los exports históricos. Se extendió el parser de fichas individuales existente y su CLI; no se creó un colector paralelo.

La evidencia principal es data/raw/bdfutbol/luna_audit/20261008T121346.469132Z/match_269462/rendered.html, solicitada como https://www.bdfutbol.com/es/p/p.php?id=269462. Metadata: HTTP 200, access_status=VALID, URL final idéntica, título “Avilés Industrial - Lugo (1 - 2) 02/10/2026 | BDFutbol”, captura 2026-10-08T12:13:55.280292+00:00, 916.421 bytes y SHA-256 890fac0cda4c7bfcb5cc9d2f2c7ca086c9072066007aabe8261e8f60c361e544. El hash recalculado coincide.

El inventario asociado informa document.ready_state=loading, complete=false, interaction_coverage=NOT_TESTED, 63 tablas, 26 scripts, cero entradas XHR registradas y listas truncadas. Por ello el parser describe lo que está presente en este snapshot, pero deja la completitud de la ficha y de los eventos como desconocida.

## Estructura observada

El parser 0.1.1 conservaba seis tablas .taula_estil text-left: índices DOM 57–62, 52 filas y 278 celdas. Las seis tienen un primer tr vacío con style="display: none"; se conserva como fila raw, pero no se promueve como participante.

Las otras 57 tablas del documento usan clases de presentación como d-none y fons-blau-2 y están dentro del submenú de navegación de temporadas. No son tablas deportivas de la ficha. Ninguna de las seis tablas .taula_estil deportivas observadas lleva esas clases, así que la regla previa no omitía tablas deportivas en esta captura. Se añadió una prueba sintética que comprueba que una tabla deportiva marcada como oculta queda identificada como raw-only y no se interpreta como contenido visible.

Las seis tablas visibles se agrupan así:

| Índices | Estructura comprobada | Resultado |
|---|---|---|
| 57–58 | Dos tablas de 11 filas de jugador, antes del encabezado Suplentes | Grupo de alineación titular, respaldado por ambas tablas de 11 y su posición respecto al encabezado |
| 59–60 | Dos tablas bajo el encabezado explícito Suplentes | Suplentes listados |
| 61–62 | Dos tablas bajo Entrenadores; las filas tienen clase entren | Entrenadores listados |

Los lados local/visitante se relacionan por el orden de las dos columnas de las tablas con el orden de los enlaces de clubes en el H1 del partido. Cada relación registra la evidencia usada. La clave normalizada de club se conserva como 81/76 siguiendo identify_entity_url; también se conserva el ID fuente e81/e76, el href y la URL exacta para cruzarlo con exports que usan el prefijo.

El H1 contiene versiones de presentación desktop y móvil, por lo que repite enlaces de clubes. El parser deduplica esos enlaces por ID al crear match_clubs, sin quitar las referencias del HTML raw. El bloque de goles tiene tres nodos de evento, no copias desktop/móvil duplicadas.

Se inspeccionaron los 26 elementos script: 13 externos y 13 inline. El parser no detectó datasets JSON deportivos embebidos (embedded_json=[]). El inventario no registra XHR en esta captura. Esto no demuestra que nunca exista contenido cargado tarde: el estado loading, los recursos truncados y la falta de interacción impiden certificar ausencia global.

## Datos extraídos y límites de interpretación

### Partido y relaciones

- Del patrón del título se normalizan fecha 2026-10-02, local Avilés Industrial, visitante Lugo y resultado 1–2.
- El bloque .hero-partit conserva competición 1ª RFEF, jornada Jornada 6, fecha/hora publicada y estadio Suárez Puerta (Avilés), con sus enlaces fuente.
- Hay enlaces directos a clubes e81 y e76, árbitro r602267 y estadio 81.
- Los exports de clubes conservan match_id=269462 dos veces, una observación desde cada club. Coinciden fecha, clubes, marcador, competition_code_raw=1rf, jornada 6, URL y árbitro 602267; differing_fields_between_club_sources=[]. La ficha expresa 1ª RFEF y enlaza una página de competición, pero el parser no convierte ese texto a 1rf.
- El estadio está enlazado directamente en la ficha. El registro histórico consultado no tiene campo stadium_id, así que no se declara una comparación histórica de estadio.

### Jugadores

Se producen 44 observaciones de jugador: 22 en el grupo titular estructural y 22 bajo Suplentes. Las 44 tienen enlace de jugador e ID verificable en esta página.

- Diez filas de titular incluyen el marcador Sale con minuto; diez filas de suplente incluyen Entra con minuto. Se normalizan como acciones individuales de salida/entrada.
- Los doce suplentes restantes no muestran marcador de entrada. Se conservan como SUBSTITUTE_LISTED_PARTICIPATION_NOT_EVIDENCED; no se etiquetan como jugadores que no participaron.
- Los goles de Santamaría (j27562, minuto raw 5), Costa (j206674, 68) y Godoy (j26448, 90+11) tienen referencias de corroboración a celdas de jugador con marcador Gol. Esas celdas no generan goles duplicados.
- 90+11 se conserva como cadena. No se suma ni transforma en minuto 101.
- La primera celda de las filas contiene valores como 1, 18 y 9, pero no hay una cabecera fuente que permita demostrar que sean dorsales. Se conservan como leading_cell_raw, sin asignarles ese significado.
- No se asignan posiciones, minutos jugados ni estadísticas individuales. Las tablas no ofrecen encabezados que permitan interpretar esos valores con seguridad.

Las entradas y salidas del mismo minuto no se emparejan en sustituciones. Hay varias acciones de ambos lados en un mismo minuto y el HTML no establece de forma inequívoca cada pareja. El export conserva cada acción, equipo, jugador, minuto raw y referencia DOM con pairing_status=NOT_INFERRED.

### Entrenadores, goles y tarjetas

El encabezado Entrenadores y los enlaces identifican a Yago Iglesias (l104929) para Avilés Industrial y Borja (l330) para Lugo. La fila de Yago contiene Tarjeta Amarilla a 63, que se extrae como evento de tarjeta del entrenador; la fila de Borja no muestra marcador de evento.

El bloque del héroe contiene tres cambios de marcador:

| Marcador | Actor enlazado | Equipo por columna | Minuto raw |
|---|---|---|---|
| 1–0 | Santamaría, j27562 | Avilés Industrial, e81 | 5 |
| 1–1 | Costa, j206674 | Lugo, e76 | 68 |
| 1–2 | Godoy, j26448 | Lugo, e76 | 90+11 |

La secuencia termina en el marcador publicado y su número de goles suma tres, coherente con 1–2. El control de calidad lo registra como coherencia con el resultado, no como prueba de que el listado de eventos esté completo. La lista exportada se agrupa por clase de extracción —goles, acciones de tablas y tarjetas— y no debe leerse como una cronología global.

## Cambios del parser y exports

Se extendió individual_entity_pages.py a parser 0.2.0 y a contratos *_detail.v2. Las celdas conservan valores, cabeceras, clases, atributos de visibilidad, enlaces y elementos descendientes con clases/títulos relevantes; las filas conservan estilo y estado oculto. El HTML original no se copia al export: cada recurso mantiene ruta, URL, timestamp, tamaño y SHA-256 hacia el snapshot raw inmutable.

El registro de partido ahora incorpora match_clubs, match_participants, match_coaches, match_events, ocurrencias raw, marcadores no interpretados, tablas deportivas ocultas detectadas y match_quality. Además, la CLI emite recursos comprimidos separados:

- match_details.json.gz
- match_participants.json.gz
- match_coaches.json.gz
- match_events.json.gz
- match_quality.json.gz

Se regeneró el export inmutable:

data/parsed/bdfutbol/entity_detail_pilots/parser-0.2.0-source-4b97a04a5c1b8a6f/

Incluye cuatro snapshots válidos (partido, entrenador, árbitro y estadio), cero rechazos y huella de fuentes 4b97a04a5c1b8a6f. El export completo ocupa 42.141 bytes; el HTML del snapshot ocupa 916.421 bytes y la carpeta raw con metadata, inventarios y captura de pantalla ocupa 2.567.940 bytes.

El export 0.1.1 y el export histórico de clubes no se modificaron. El export 0.1.1 conserva su esquema anterior y sus hashes antes/después coinciden. Una segunda ejecución del CLI produjo la misma huella y reutilizó el directorio 0.2.0 al comparar los bytes, sin sobrescribirlo.

Comando de regeneración offline:

    PYTHONPATH=src .venv/bin/python scripts/parse_bdfutbol_entity_pages_offline.py --repo-root .

## Pruebas y reproducibilidad

Los tests usan el snapshot real de 269462 para verificar hashes, identidad, tablas, relaciones, contraste histórico, participantes, acciones, goles, tarjeta de entrenador, minuto añadido, estado loading y export por recursos. Los casos de evento sin minuto, evento duplicado, actor sin enlace, tabla oculta, equipo no verificable, acciones de sustitución simultáneas y marcador desconocido usan fixtures sintéticos; no se presentan como estructuras adicionales observadas en BDFutbol.

- Tests específicos: 22 passed.
- Suite completa: 297 passed. La primera ejecución restringida falló solo en test_loopback_port_valid, porque el sandbox impedía crear el socket local que prueba BrowserRuntime; repetida con permiso loopback local, la suite completa pasó. No hubo conexiones externas.
- Ruff sobre los tres módulos Python modificados: All checks passed.
- git diff --check: limpio.

Comandos:

    PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_individual_entity_pages.py
    PYTHONPATH=src .venv/bin/python -m pytest -q
    .venv/bin/ruff check src/football_data_hub/parsers/individual_entity_pages.py scripts/parse_bdfutbol_entity_pages_offline.py tests/test_individual_entity_pages.py
    git diff --check

## Pendiente antes de declarar cobertura general

- Probar el contrato con otra ficha ya adquirida cuando exista un snapshot offline, en especial variaciones de estructura, eventos sin goleador enlazado, expulsiones y ausencia de sustituciones.
- Revalidar esperas de captura con acceso autorizado en otra fase; este hito no intenta resolver ready_state=loading.
- Verificar si otras fichas rotulan explícitamente la primera sección de alineación y si las tablas responsive cambian.
- Confirmar en páginas distintas si el significado de los marcadores y la asignación por orden de columnas se mantiene.
- Obtener después una captura cuyo inventario completo y DOM estable permitan evaluar disponibilidad de eventos y datos posteriores al HTML conservado.

No se declara completitud semántica ni de eventos para el partido 269462 ni para una competición. No se modificaron snapshots, datos históricos, scrapers de clubes/jugadores ni Dev Explorer. No se hizo commit ni push.
