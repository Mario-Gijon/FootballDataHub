# Árbitros de BDFutbol — Primera Federación 2026/27

## Estado de la exploración

La pestaña se abrió con SeleniumBase Pure CDP, Chromium y Xvfb externo. Las tres
visitas necesarias para resolver los ámbitos `Todos`, `Grupo 1` y `Grupo 2`
devolvieron HTTP 200, mantuvieron su URL final y mostraron contenido de la
temporada 2026-27. No apareció una página de desafío.

| Hecho | Resultado observado |
|---|---|
| Tabla | `table#tab_arb`, incluida en el HTML inicial |
| Filas, excluida la cabecera | Todos 60; Grupo 1 43; Grupo 2 42 |
| Árbitros distintos | 60 en la unión; 25 aparecen en ambos grupos |
| IDs | Enlaces reales `/es/r/r<ID>.html`; 60 IDs únicos en «Todos» |
| Fotografía | 60/60 filas tienen `img.mini-foto-jugador`; se guardan URLs, no archivos |
| Bandera | La tercera celda está vacía en las filas observadas; nacionalidad y bandera quedan nulas |
| Alcance de P/TA/TR | Las tres métricas son por ámbito; por cada ID, «Todos» = Grupo 1 + Grupo 2 |
| Respuesta inicial | La tabla, los selectores y los enlaces están en el documento recibido; no se necesita ejecutar JavaScript para parsearlos |

En esta captura, P/TA/TR suman **Todos 119/563/35**, **Grupo 1 60/273/20** y
**Grupo 2 59/290/15**. El catálogo tiene edad y fecha de nacimiento en 59 de 60
filas; lugar de nacimiento en 60 y provincia en 59. Las estadísticas P/TA/TR
están presentes como números en las 145 filas de ámbitos.

La página base es la ruta del Grupo II, pero el filtro `Todos` agrupa árbitros
de los dos grupos. No se interpreta la ruta `/rf2` por sí sola como el ámbito
estadístico. `group_scope` conserva explícitamente `all`, `group1` o `group2`.

## Tabla y campos semánticos

El extractor lee únicamente `#tab_arb`. Hay otras tablas de partidos en el
documento; sus enlaces a árbitros no son filas de este catálogo. La cabecera
tiene once celdas: tres sin nombre (orden, fotografía y bandera) y ocho columnas
con nombre. `title` en la cabecera confirma «Fecha de nacimiento», «Partidos»,
«Tarjetas amarillas» y «Tarjetas rojas».

| Campo normalizado | Tipo | Evidencia y significado |
|---|---|---|
| `referee_id` | texto | Sufijo real `r<ID>` del enlace de nombre, por ejemplo `r601449`; clave estable. |
| `display_name` | texto | Texto del enlace de perfil en la columna «Nombre». No se publica aquí un nombre completo separado. |
| `profile_url` | URL | `href` del enlace `/es/r/r<ID>.html`, resuelto a HTTPS absoluto. |
| `photo_url` | URL o `null` | `src` de `img.mini-foto-jugador` en la segunda celda. No se descarga la imagen. |
| `flag_url` | URL o `null` | Tercera celda sin imagen ni texto en las tres capturas; se conserva nulo. No se infiere nacionalidad. |
| `nationality`, `nationality_code`, `full_name` | texto o `null` | La tabla no da evidencia verificable para estos campos; quedan nulos. |
| `age_years` | entero o `null`, años | Columna «Edad», valor publicado. No se recalcula. Dos edades no coinciden con la edad calculada a 10/10/2026; la fecha de referencia de BDFutbol no está publicada. |
| `birth_date` | fecha o `null` | Columna «Fecha», cuyo `title` es «Fecha de nacimiento». El valor fuente `DD/MM/YYYY` se normaliza a `YYYY-MM-DD`. |
| `birthplace` | texto o `null` | Columna «Lugar de nacimiento». |
| `province` | texto o `null` | Columna «Provincia»; puede estar vacía aunque haya lugar de nacimiento. |
| `published_order` | entero | Primera celda numérica de la fila. Es el orden mostrado, no se presenta como clasificación deportiva. |
| `matches_officiated` | entero o `null` | `P`, con `title="Partidos"`; cuenta de partidos arbitrados dentro del ámbito seleccionado. |
| `yellow_cards` | entero o `null` | `TA`, con `title="Tarjetas amarillas"`; tarjetas de los partidos del ámbito, no tarjetas personales del árbitro. |
| `red_cards` | entero o `null` | `TR`, con `title="Tarjetas rojas"`; tarjetas de los partidos del ámbito. |
| `statistics_url` | URL o `null` | Enlace presente en la celda P, normalmente `/es/p/r<ID>.html?cat=rf1&temp=2026-27`. No se visita. |

Los valores vacíos se representan como `null`; el cero publicado (por ejemplo,
TR=0) permanece como cero. No se fusionan entidades por nombre.

## Selectores y navegación

El documento tiene un selector de temporada y un selector de ámbito para la
tabla. Ambos usan `onchange` para asignar `window.location`; cambiar su valor
requiere navegación, no es un filtro local de DOM. El selector de temporada
ofrece temporadas históricas hasta 2026-27. Solo se adquiere 2026-27.

El selector de ámbito contiene:

| Etiqueta | Valor de destino observado desde la página base | Interpretación |
|---|---|---|
| Todos | `../t/t2026-271rf2.html?tab=referees` | Agregado de ambos grupos; validado porque P, TA y TR son la suma exacta por árbitro. |
| Grupo 1 | `t2026-271rf1.html?tab=referees&grups=1` | Estadísticas del Grupo 1. |
| Grupo 2 | `t2026-271rf2.html?tab=referees&grups=1` | Estadísticas del Grupo 2. |

Los destinos de grupo cambian el documento y conservan el ámbito en la URL.
Las tres páginas se capturaron una vez cada una; no se cargaron temporadas
históricas ni fichas individuales. Existe además un selector superior de
competición entre Grupo 1 y Grupo 2; no es el filtro de agregación de la tabla.

## Relación con Resultados (RES-01)

La referencia usada es
`data/exports/bdfutbol/group2_classification/derived-res01-20261010T102656Z/normalized/matches.json`.
El cruce utiliza `referee_id` exacto (`r<ID>`), y comprueba nombre y URL; nunca
utiliza coincidencia aproximada de nombres.

En la captura observada, 59 partidos disputados del Grupo II llevan árbitro y
se relacionan con 42 IDs únicos. Los 42 IDs aparecen en la tabla filtrada del
Grupo II; no hay árbitros de esa tabla sin partidos ni referencias de partidos
sin ficha en la tabla. Los 321 partidos no disputados de RES-01 no tienen ID de
árbitro asignado. No hay conflictos de nombre o URL. Por árbitro, P, TA y TR
coinciden con el recuento y las tarjetas agregadas de esos partidos; los totales
son 59 partidos, 290 amarillas y 15 rojas. Esta comparación describe
estas dos capturas, que no tienen exactamente el mismo instante de adquisición;
una discrepancia futura se informa, no se corrige ni se oculta.

## Validación, exports y limitaciones

El validador comprueba la tabla esperada, IDs únicos, tipos y valores no
negativos, unicidad de `(referee_id, season, group_scope)`, coherencia del
agregado Todos y relación exacta con Resultados. El número de árbitros no es una
constante del modelo ni una regla de validación.

Cada ejecución usa un directorio nuevo en
`data/exports/bdfutbol/group2_referees/<capture_id>/` con los tres HTML por
ámbito, diagnósticos HTTP, metadatos, `normalized/referees.json`,
`normalized/statistics.json`, `normalized/filter_options.json` y resultados de
validación y cruce. El HTML se puede volver a normalizar sin navegador y cada
hash SHA-256 se verifica antes de procesarlo.

Pendiente: la edad publicada no define su fecha de referencia; la tabla no
expone nacionalidad ni una bandera en estas filas; no se visitaron fichas
individuales para completar esos datos. FastAPI podrá consumir catálogo,
estadísticas por ámbito y metadatos de captura en REF-02; esta entrega no
modifica API ni React.
