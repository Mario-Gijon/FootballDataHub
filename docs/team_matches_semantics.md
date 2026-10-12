# Semántica de Partidos en la ficha de equipo

## Fuente y alcance

La página de equipo utiliza el bootstrap de clasificación del grupo al que pertenece el `team_id`. No crea un snapshot por equipo ni solicita un endpoint nuevo. El bootstrap contiene el catálogo, los 380 partidos del grupo y las series de progreso ya adquiridas. `buildTeamMatchCalendar()` selecciona el calendario por ID del equipo local o visitante y valida IDs de partido duplicados y referencias a equipos fuera del catálogo.

Las capturas disponibles contienen 20 equipos, 380 partidos y 38 encuentros programados por equipo en Grupo I y Grupo II. Los resultados, fechas, estadio, árbitro, enlace fuente y estado se muestran únicamente cuando están presentes en el contrato `Match`.

## Fechas y estados

- `source_match_date`: fecha del encuentro publicada por la fuente. Se muestra como fecha del partido cuando existe.
- `matchday_date`: fecha de referencia publicada para la jornada. Solo se muestra si no hay fecha específica, con la etiqueta «Fecha de jornada».
- Si ambas fechas son `null`, la tabla muestra `—`; nunca se fabrica una hora.
- `played`: requiere ambos goles y se presenta con marcador local–visitante. Victoria, empate o derrota se colorea desde la perspectiva del equipo de la ficha, incluyendo victorias como visitante.
- `unplayed`: conserva goles `null` y muestra `— : —` con el estado «Pendiente».
- `incomplete`: se muestra como «Datos incompletos» y no se calcula un resultado.
- Un `unplayed_state` como `result_unavailable_at_capture` permanece en el registro original; no se cambia a marcador ni se inventa un 0–0.

Los nombres, escudos y enlaces internos se resuelven con IDs del catálogo del mismo grupo. El marcador enlaza a `source_match_url` cuando está disponible. Los estadios conservan su enlace de BDFutbol si el contrato lo publica. No hay ruta interna de detalle de partido.

## Filtros

Los controles de estado (Todos, Disputados, Pendientes, Incompletos) y condición (Local, Visitante) filtran en memoria el calendario derivado del bootstrap. Cambiarlos no realiza solicitudes HTTP. La competición se limita a la Liga de Primera Federación 2026/27 del grupo propio.

## Progreso en Liga

El gráfico toma únicamente los registros `bootstrap.progress` del equipo seleccionado y grafica `position` por `matchday`. Conserva jornadas con posición `null` sin conectarlas como si existiera un dato. La escala se invierte para que la posición 1 aparezca arriba. La cobertura actual llega a J6; no se extrapolan jornadas futuras ni se reconstruye el gráfico a partir de resultados.

## Récords calculados

Los récords son derivados de los partidos `played` completos de la captura actual; no se presentan como datos oficiales independientes. Se calculan cuatro mayores diferencias de goles por condición local/visitante (victoria o derrota) y seis rachas: victorias, derrotas, invicto, sin ganar, empates y partidos sin empatar.

Para no atribuir una racha a un tramo sin evidencia, un partido pendiente o incompleto interrumpe la secuencia. También se interrumpe cuando falta una jornada entre dos partidos disputados. Se conservan todos los partidos o tramos empatados en el récord máximo. El valor `null` significa que la captura no contiene un caso evaluable para ese tipo de récord; no se sustituye por cero.

### Contraste de Jaén con el HTML guardado

La captura original de ficha está en `data/exports/bdfutbol/teams/2026-27/49/20261012T131457.209360Z-602005d8/raw/matches.html.gz`. En su tabla de récords, BDFutbol publica: victoria en casa `2 - 1` ante UD Ibiza; victoria fuera `0 - 3` ante Europa; derrota fuera `2 - 0` ante Antequera; y rachas máximas de 2 victorias, 1 derrota, 4 partidos invicto, 2 sin ganar, 1 empate y 3 sin empatar.

El cálculo desde los seis resultados disputados disponibles en el bootstrap Grupo II reproduce esos ocho valores y rivales. El contraste valida el cálculo para este equipo y esta captura, no garantiza equivalencia para todas las temporadas, estados de aplazamiento o convenciones futuras de la fuente.

## Procedencia dinámica

La interfaz muestra `captured_at` y `capture_id` del bootstrap que alimenta la página. Al publicarse una captura posterior, la vista utiliza el nuevo bootstrap y su cobertura. No hay valores de jornada, récord o fecha fijados en el componente.
