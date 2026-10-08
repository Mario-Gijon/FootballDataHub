# Auditoría autónoma de BDFutbol — Primera Federación 2026/27

Fecha de auditoría: 8 de octubre de 2026. Alcance: páginas representativas de los Grupos I y II y páginas relacionadas. No se implementaron scrapers.

## Resultado y método

Se demostró acceso directo con el código del repositorio: BrowserSessionManager, BrowserRuntime, Brave externo en Xvfb, Playwright conectado por CDP y BDFutbolAccess. El smoke de una página visitó la ficha de Morillas y registró URL solicitada/final, HTTP 200, título y 58 tablas diagnósticas. BDFutbolAccess la marcó VALID por sus marcadores deportivos. La prueba quedó en `data/analysis/bdfutbol/session_smoke/20261008T120931.289334Z/summary.json`.

El primer intento del smoke se detuvo antes de abrir Brave: el sandbox no permitió crear el lock junto al perfil en `~/.football-data-hub-v2-probe`. No hubo navegación en ese intento. Repetí la misma prueba autorizada con acceso al perfil; no inspeccioné, copié ni exporté cookies, credenciales ni archivos del perfil. El acceso real requirió poder crear ese lock. El administrador inició y cerró su propio Brave/Xvfb/CDP; no se detuvo ningún navegador ajeno.

Conté **20 aperturas de páginas objetivo en BDFutbol**, incluyendo una repetición de la clasificación del Grupo I y la prueba inicial de Morillas. Se hicieron además interacciones locales de lectura que no cambiaron la URL ni causaron navegación principal. No se intentaron completar páginas no verificadas ni se consumieron las 30 navegaciones permitidas.

Al inicio no se observó Brave/Xvfb ni proceso de acquisition, discovery, smoke o sincronización en ejecución. No se mató ningún proceso. Todos los documentos que abrí terminaron en VALID/HTTP 200. Aun así, en una ventana de observación de red aparecieron solicitudes de fondo a Cloudflare JavaScript Detection, recursos de reCAPTCHA, telemetría Umami y un GET 403 a `manifest.json`. El documento deportivo siguió válido y no apareció interstitial; el 403 fue de ese recurso secundario. No inspeccioné cuerpos ni cabeceras. El log coincidió con una interacción de disclosure, pero no permite atribuir esas solicitudes al clic: pueden ser actividad retrasada de carga. No hice más navegaciones después de observarlas.

### Evidencias anteriores, separadas de esta navegación

Estos resultados son ARTIFACT_ONLY y no cuentan como visitas de esta auditoría:

- `data/analysis/bdfutbol/headless_probe/20261008T103331.853564Z/summary.json` y `20261008T103340.009489Z/summary.json`: el modo HTTP y el Chromium headless fueron clasificados como CHALLENGE_REQUIRED para las páginas incluidas, entre ellas Morillas, Real Jaén, una temporada de equipo y un partido.
- `data/analysis/bdfutbol/discovery_0a/20261008T113427.602554Z/summary.json`: Morillas dio HTTP 403, título “Just a moment...” y CHALLENGE_REQUIRED.
- `data/analysis/bdfutbol/discovery_0a/20261008T114243.890449Z/summary.json` y el raw asociado: Morillas dio HTTP 200/VALID; el snapshot registró 10.541 enlaces (truncados por el límite), 58 tablas, 7 selectores y cuatro pestañas de jugador.
- Los smoke previos `20261008T111943.094353Z` y `20261008T112019.452894Z` informan Morillas y Estadísticas válidos. Son ejecuciones anteriores, no acceso que yo haya comprobado ahora.

## Inventario de recursos comprobados

Todos los snapshots indicados abajo se generaron en directorios timestamp nuevos. El HTML y el inventario DOM se guardaron con metadata y SHA-256; varios incluyen screenshot. Las rutas raw están ignoradas por Git como datos generados, pero permanecen accesibles en el workspace.

| Entidad / vista | URL visitada | Resultado y evidencia directa | Dificultad estimada |
|---|---|---|---|
| Competición, Grupo I, clasificación | `https://www.bdfutbol.com/es/t/t2026-271rf1.html` | VERIFIED, HTTP 200, título “Clasificación 1ª RFEF Grupo I 2026-27”; `data/raw/bdfutbol/luna_audit/20261008T121024.595861Z/competition_group_i/` | Media: página grande y DOM con controles globales repetidos |
| Competición, Grupo II, clasificación | `https://www.bdfutbol.com/es/t/t2026-271rf2.html` | VERIFIED, HTTP 200, mismo patrón para Grupo II; `.../competition_group_ii/` | Media |
| Grupo I, Resultados | `...?tab=results` | VERIFIED; `.../20261008T121144.726760Z/results/` | Media |
| Grupo I, Destacados | `...?tab=top` | VERIFIED; rankings de jugadores; `.../top/` | Media |
| Grupo I, Árbitros | `...?tab=referees` | VERIFIED; tabla de árbitros y selector de temporada/grupo; `.../referees/` | Media |
| Grupo I, Estadísticas | `...?tab=stats` | VERIFIED; agregados de temporada; `.../stats/` | Baja-media |
| Jaén, temporada/plantilla 2026/27 | `https://www.bdfutbol.com/es/t/t2026-2749.html` | VERIFIED; plantilla, técnico, tabs y selector de 70 temporadas; `data/raw/bdfutbol/luna_audit/20261008T121250.991672Z/team_season_jaen/` | Media-alta por vista y configuración de columnas |
| Jaén, vista de estadísticas de plantilla | `https://www.bdfutbol.com/es/t/t2026-2749.html?t=lista` | VERIFIED; tabla agregada por jugador; `data/raw/bdfutbol/luna_audit/20261008T121519.382702Z/team_season_statistics/` | Media |
| Club Jaén | `https://www.bdfutbol.com/es/e/e49.html` | VERIFIED; datos generales, cronología y rutas de vistas; `data/raw/bdfutbol/luna_audit/20261008T121250.991672Z/club_profile_jaen/` | Media |
| Jugador Morillas, Trayectoria | `https://www.bdfutbol.com/es/j/j209629.html` | VERIFIED; ficha, carrera por temporada/equipo y gráfico; `data/raw/bdfutbol/luna_audit/20261008T121250.991672Z/player_profile_morillas/` | Media-alta por gráficos, opciones y tablas configurables |
| Morillas, Estadísticas | `...?p=stats` | VERIFIED; tabla comparativa de competiciones con 73 filas DOM; `.../player_stats_morillas/` | Media |
| Morillas, Partidos | `https://www.bdfutbol.com/es/p/j209629.html` | VERIFIED; vistas agregadas por competición, temporada, equipo y rival; `.../player_matches_morillas/` | Media-alta |
| Morillas, Rivales | `https://www.bdfutbol.com/es/p/jr209629.html` | VERIFIED; filtros por competición, temporada y demarcación; tablas de rivales; `.../player_rivals_morillas/` | Alta por volumen y tabla relacional |
| Partido Avilés Industrial–Lugo | `https://www.bdfutbol.com/es/p/p.php?id=269462` | VERIFIED; ficha de jornada 6, 1–2; `data/raw/bdfutbol/luna_audit/20261008T121346.469132Z/match_269462/` | Alta: página propia y eventos/relaciones |
| Entrenador Manolo Herrero | `https://www.bdfutbol.com/es/l/l1835.html` | VERIFIED; trayectoria multi-temporada y pestañas; `data/raw/bdfutbol/luna_audit/20261008T121419.346588Z/coach_manolo_herrero/` | Media-alta |
| Árbitro Pacheco Cotero | `https://www.bdfutbol.com/es/r/r602267.html` | VERIFIED; historial por temporada y estadísticas; `.../referee_pacheco_cotero/` | Media |
| Estadio Suárez Puerta | `https://www.bdfutbol.com/es/s/81.html` | VERIFIED; ficha y agregados de uso; `.../stadium_suarez_puerta/` | Media |

La lista ordenada con las 20 aperturas, la evidencia y el estado de cada recurso está en el catálogo JSON. La clasificación del Grupo I se visitó dos veces; la ficha de Morillas también se probó una vez en smoke y otra con captura.

## Campos deportivos observados

### Competiciones

Ambas páginas de clasificación identifican temporada 2026/27 y grupo. Cada una muestra 20 equipos y 38 jornadas. En cada raw hay una tabla de clasificación con 21 filas DOM, incluida la cabecera, y columnas Pts., PJ, PG, PE, PP, GF, GC, TA y TR. “Local”, “Visitante” y “General” cambian la clasificación.

En el HTML de ambos grupos también está la tabla de calendario/resultados que no es visible en la vista inicial. Tiene 456 filas DOM: 38 cabeceras de jornada, 38 cabeceras de columnas y 380 filas de partidos (10 por jornada). Sus columnas son Fecha, Local, resultado, Visitante, Estadio y Árbitro; los enlaces conducen a partido, equipos, estadio y árbitro. El contenido inicial incluye resultados de jornadas jugadas y calendario futuro. Este hallazgo no implica que cada enlace o cada dato final de temporada haya sido auditado.

Las pestañas Resultados, Destacados, Árbitros y Estadísticas conservan la URL base y se abren con `tab=results`, `tab=top`, `tab=referees` y `tab=stats`. La vista Resultados incluye además una tabla cruzada equipo contra equipo y un selector Todas/Jornada 1…38. Destacados ofrece Goles, Minutos, Tarjetas amarillas, Tarjetas rojas, Más joven y Más veterano; su tabla principal tiene columnas jugador, país, posición, edad, goles y club. Otra tabla observada contiene país, edad, PJ, minutos, goles y tarjetas. Estadísticas muestra agregados de temporada; en la página revisada figuraban 20 equipos, 60 partidos, victorias locales/visitantes, empates, goles, tarjetas, expulsiones, penaltis y rachas.

En Árbitros aparecen selects para temporada (96 opciones, de 1928-29 a 2026-27) y grupo (Todos, Grupo 1, Grupo 2). La tabla muestra nombre, edad, fecha/lugar de nacimiento, provincia, partidos y tarjetas. El contenido de todas las temporadas está en el control, pero no se recorrió.

### Club y temporada de equipo

La ficha del club Jaén confirma nombre completo, fundación, localidad/provincia, país, estadio y aforo. Presenta Trayectoria, Estadísticas, Jugadores, Entrenadores, Partidos y Rivales, además de vistas Tabla/Listado, competiciones y comparación con otros clubes. El selector de comparación reporta 947 opciones; el inventario DOM limita la lista de opciones guardada, así que el número es recuento observado, no una lista íntegra.

La temporada del equipo presenta competición, seis partidos al corte observado, técnico y plantilla. El encabezado de plantilla comprende dorsal, foto, país, apodo/nombre, demarcación, edad, PJ, titularidades, partidos completos, suplencias, convocatorias sin jugar, minutos, amarillas, rojas y goles. El técnico aparece como registro separado. El modo `?t=lista` ofrece además minutos por gol, goles y resultado W/D/L por jugador. El selector de temporada incluye 70 campañas históricas; no se recorrieron.

La pestaña interna de columnas es un disclosure local con 15 checkboxes: dorsal, foto, país, nombre, demarcación, edad, PJ, titular, completos, suplente, convocado sin jugar, minutos, tarjetas amarillas/rojas y goles. Abrí el panel, inspeccioné las etiquetas y no pulsé Recordar ni Restablecer. Las tabs Seguimiento, Traspasos y Partidos se encontraron como enlaces; sus páginas quedan NOT_TESTED.

### Jugadores

La ficha de Morillas presenta nombre completo, fecha y lugar de nacimiento, país, demarcación y altura; en Trayectoria muestra temporada, equipo, país, división, edad, PJ, PT, PC, PS, minutos, tarjetas, goles y totales. Para el jugador seleccionado aparecían Jaén y Atlético Baleares, y temporadas 2024/25–2026/27. Los selects visibles filtran equipo y país. La ficha contiene un carrusel DOM con una sola fotografía de perfil y muestra “Fotos (0)” en la sección comunitaria; no se comprobó una galería adicional.

Estadísticas ofrece una tabla de 73 filas comparando competiciones y métricas: temporadas, equipos, partidos jugados/completos/titular/suplente/convocado, resultados, minutos, goles, promedios, porterías a cero, goles encajados, tarjetas y edades. El selector visto permite 2ª B, 1ª RFEF y Copa del Rey. Una comparación que conviene validar en futuros parsers: en esta muestra el total de PJ por competición (23 + 6 + 1) no coincide con el total 29 mostrado en Trayectoria. Puede obedecer a criterios distintos o solapamiento; no se declara error ni se deben sumar métricas sin comprobar su definición.

Partidos contiene selectores de competición, temporada, equipo y rival, así como resúmenes/tablas por esas dimensiones; Rivales contiene selectores de competición, temporada y demarcación, y una tabla relacional con PJ, PG, PE, PP, porcentaje, goles y tarjetas. Las vistas muestran bastantes datos ya en DOM. No se comprobó paginación ni se confirmó que Partidos exponga un registro completo, fila a fila, de cada encuentro.

### Partido, entrenador, árbitro y estadio

El partido seleccionado muestra competición, jornada, estadio, fecha/hora, marcador y eventos de gol con minuto. La ficha contiene alineaciones, suplentes, minutos de sustitución y entrenadores; los enlaces de la página enlazan equipos, entrenador, árbitro y estadio. No se observó una sección de tarjetas en este partido; las tarjetas no deben darse por disponibles en toda ficha sin muestras adicionales.

La ficha de entrenador contiene nombre, fecha/lugar de nacimiento, país y posible enlace a perfil de jugador; ofrece Trayectoria, Estadísticas, Partidos y Rivales. La tabla histórica vista incluye temporada, club, división, edad, partidos dirigidos, ganados, empatados, perdidos y tarjetas. La ficha de árbitro muestra datos personales, trayectoria por temporada/país/división y partidos, local/empate/visitante, amarillas/rojas y promedios; enlaza Trayectoria, Estadísticas y Partidos. No abrí las vistas de partidos de árbitro ni de entrenador.

La ficha del estadio contiene nombre oficial, aforo, inauguración, arquitecto, dimensiones y localidad. También agrega partidos, equipos, temporadas y competiciones, y muestra equipos locales/visitantes y una clasificación de visitantes. La existencia de un enlace de estadio desde partido y club confirma parte de la relación; identidades y cambios de estadio por temporada aún requieren reconciliación.

## Navegación, controles, contenido oculto y red

| Capa | Hallazgo | Estado |
|---|---|---|
| Navegación global | Competiciones, Clubes, Rankings, Selección y Comunidad; el menú “Más” contiene Jugadores, Entrenadores, Árbitros, Estadios y otras rutas. No seguí todas esas secciones globales. | Etiquetas/DOM VERIFIED; destinos globales NOT_TESTED salvo los perfiles indicados |
| Navegación deportiva | Tabs con enlaces y query strings: competición, club, jugador, entrenador y árbitro. Son vistas separadas que requieren URL directa. | URLs de tabs enumeradas en snapshot; solo vistas marcadas arriba fueron abiertas |
| Controles de clasificación | Grupo, Local/Visitante/General, jornadas, aplazados incluidos/no incluidos, filtro por fechas/jornadas y métrica del gráfico. | VERIFIED en Grupo I; filtros y gráfico probados |
| Filtros | Cambiar clasificación a Local actualizó filas; seleccionar Filtrar fechas reveló campos date1/date2. No se leyeron sus valores. | VERIFIED |
| Gráfico | El gráfico visible usa SVG y amCharts 3.15.2. Cambiar métrica de Posición a Puntos lo redibujó en cliente. | VERIFIED |
| Tabla oculta | La tabla de 380 partidos está en el DOM inicial aunque no se muestre en clasificación; el tab Resultados también sirve calendario y tabla cruzada. | VERIFIED |
| Columnas | El panel del equipo revela 15 checkboxes; preferencias Recordar/Restablecer no se activaron. | VERIFIED |
| Imágenes | Los inventarios registran cientos de imágenes por página, muchas son navegación, escudos, banderas o contenido oculto. La ficha de Morillas tiene una imagen de perfil en carrusel. | Carrusel e imagen de perfil VERIFIED; clasificación semántica exhaustiva de imágenes NOT_TESTED |
| Peticiones dinámicas | Cambios de clasificación, filtro de fechas y selector de gráfico dejaron la URL intacta y no generaron solicitudes fetch/XHR observadas. La API de Resource Timing no es un HAR. | VERIFIED solo para esas interacciones y ventana |

El inventario DOM es deliberadamente acotado: los menús comunes disparan recuentos grandes (aprox. 10–17 mil enlaces, 58–66 tablas y cientos/más de mil imágenes candidatas), por lo que no todos son recursos deportivos de la página. El snapshot de partido tenía `ready_state=loading` aunque ya permitía leer la ficha; la extracción deberá esperar marcadores deportivos y estabilidad del contenido, no depender solo de `document.readyState`.

## Relaciones observadas

```text
Competición (grupo y temporada)
  ├── jornada / resultado / partido
  │     ├── equipos de temporada
  │     ├── estadio
  │     ├── árbitro
  │     └── entrenadores y jugadores
  ├── clasificaciones / destacados / estadísticas
  └── designaciones de árbitros

Club
  ├── temporadas de equipo ── plantilla y técnico
  ├── jugadores ── trayectoria / estadísticas / partidos / rivales
  └── entrenadores ── trayectoria / estadísticas / partidos / rivales
```

El grafo es una propuesta derivada de enlaces y campos observados; los IDs deben conservarse como claves de origen y validarse en el discovery de todos los grupos.

## Obstáculos, estados pendientes y cobertura

- El acceso fue real y estable durante esta muestra, pero los artefactos anteriores registran 403/CHALLENGE_REQUIRED. El éxito actual no garantiza acceso futuro ni disponibilidad para una ejecución desatendida.
- BrowserSessionManager escribe un lock junto al perfil. El entorno de auditoría aislado lo bloqueó inicialmente; en servidor debe configurarse un directorio de perfil/lock escribible con acceso autorizado. No se deben copiar cookies ni intentar automatizar la resolución de CAPTCHA/Cloudflare.
- Cloudflare JSD/reCAPTCHA aparecen en recursos de fondo aun cuando la página deportiva valida. Hay que registrar el status del documento principal separado del status de recursos secundarios, y detener la adquisición afectada ante interstitial o marcador de desafío.
- La liga estaba en curso: las vistas consultadas llegaban a jornada 6; cada grupo presenta 38 jornadas y 20 equipos. La estructura observada equivale a 380 filas de partido por grupo y 760 entre los dos. Es una expectativa de cobertura para comprobar, no una afirmación de que los partidos futuros ya tengan resultado.
- No se recorrieron clubes restantes, todas las plantillas, todos los jugadores/entrenadores, paginación, todas las competiciones de carrera, la galería de fotos ni todas las combinaciones de filtros.
- No se verificaron global Rankings, páginas de designaciones de todos los árbitros, descargas originales de medios, datos de respuesta XHR, pestañas de estadísticas/partidos de entrenador y árbitro, ni todas las opciones de club.
- Los inventarios de imágenes, scripts, SVG y XHR son candidatos; requieren clasificación semántica. Las tablas de navegación pueden contener años y ligas que no son el cuerpo deportivo.

## Propuesta para scrapers deterministas posteriores

1. Mantener BrowserSessionManager/BDFutbolAccess como puerta de acceso y validación semántica. Una lista permitida de rutas y acciones debe declarar entidad, temporada, grupo, vista, marcadores y presupuesto. No hacer обход de desafíos: CHALLENGE_REQUIRED detiene ese recurso y requiere resolución autorizada.
2. Separar navegadores y parsers: adquisición por familia de página con pasos de Playwright explícitos para tabs/filtros, y parsing offline de snapshots con selectores DOM/HTML estables. Evitar acoplar los parsers a IA, texto aproximado o a los elementos de navegación global.
3. Guardar cada captura en una ruta inmutable con timestamp UTC y variante, HTML renderizado, metadata JSON, SHA-256, assessment, URL solicitada/final, title/status, screenshot selectivo y un inventario de controles/solicitudes permitidas. No guardar cookies, cabeceras de autenticación, payloads sensibles ni perfil de navegador. Mantener el raw aunque cambie el parser.
4. Derivar JSON parsed por recurso y CSV de intercambio desde raw; producir normalized después con claves BDFutbol, procedencia, versión del parser y reglas de reconciliación. No usar CSV como única copia: las tablas de alineación/eventos pueden ser relacionales y contener celdas repetidas/encabezados de jornada.
5. Medir adquisición y cobertura por separado. La primera indica página válida; la segunda compara la lista esperada de grupos, 20 equipos, 38 jornadas, fixtures únicos, tablas requeridas, plantillas y enlaces de entidad. Auditar 380 fixtures esperados por grupo, duplicados y ausencias, enlaces rotos, y discrepancias entre vistas (como PJ 29 frente a 30 en la muestra) antes de declarar completa una colección.
6. Revalidar periódicamente páginas mutables mediante snapshots nuevos, diffs de esquema/campos y revisión manual de cambios. Las fechas futuras, partidos aplazados, modificaciones de plantillas y diferencias entre temporadas requieren historiales versionados, no sobrescritura.

La arquitectura es técnicamente viable: el navegador existente accedió a las páginas y el HTML renderizado contiene los datos necesarios para diseñar parsers reproducibles. La viabilidad de una captura completa y desatendida es **condicional** a estabilidad de acceso autorizado, tratamiento conservador de Cloudflare, descubrimiento restante y una estrategia de cobertura/versionado. La investigación actual no certifica que BDFutbol ofrezca todos los campos objetivo.

## Entregables y alcance de cambios

- Este informe: `docs/bdfutbol_primera_federacion_2026_27_luna_audit.md`.
- Catálogo estructurado: `data/analysis/bdfutbol/luna_audit/resource_catalog.json`.
- Snapshots directos y análisis auxiliares: `data/raw/bdfutbol/luna_audit/` y `data/analysis/bdfutbol/luna_audit/<timestamp>/`.
- No se modificó código productivo, no se añadieron dependencias, no se ejecutaron pruebas ni se realizó commit/push. Las modificaciones preexistentes en el worktree quedaron intactas. Se añadió una excepción de ignore solo para que el catálogo solicitado pueda aparecer como archivo versionable; las capturas y carpetas timestamp continúan ignoradas.
