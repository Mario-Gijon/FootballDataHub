# Disposición táctica de Plantilla

## Evidencia inspeccionada offline

Se inspeccionaron los snapshots originales de Alineación ya publicados:

- Jaén, `team_id=49`: `data/exports/bdfutbol/teams/2026-27/49/team01a-group2-49-source-evidence/raw/alignment.html`.
- Racing de Ferrol, `team_id=48`: `data/exports/bdfutbol/teams/2026-27/48/20261011T123240.190812Z-8f307d1c/raw/alignment.html.gz`.

En ambos se encuentra `#alineacio #tactica #js`. Sus hijos incluyen nodos
`d_por`, `d_def...`, `d_mig...` y `d_dav...`. Cada nodo enlaza a una ficha
`/j/j<ID>.html` y contiene la fotografía publicada. Los 11 IDs de jugador de
cada snapshot coinciden con los 11 IDs de la categoría `Titulares` normalizada
de ese mismo equipo. No hay nombres ni fotos copiados a la estructura espacial.

La forma de los IDs es semántica en estas dos capturas: `d_por` identifica al
portero; en `d_def13`, el primer dígito es el ordinal `1` y el segundo declara
`3` posiciones para esa línea. El mismo patrón se observa en centrocampistas y
delanteros. Jaén publica líneas de 3 defensas, 4 centrocampistas y 3
delanteros; Racing publica 4, 2 y 4. La página fuente incluye el texto de que
la visualización se genera automáticamente a partir de las posiciones y es
aproximada.

El HTML no contiene coordenadas `left`/`top` ni una geometría numérica. Enlaza
la imagen `graphic_field.png`, `equip_temporada.css` y
`scripts_plantilla.js`, pero esos recursos externos no forman parte de los
snapshots guardados. Por eso no se reconstruye el dibujo original exacto ni se
declara que el campo conserve su orientación original.

## Coordenadas normalizadas de la aplicación

Para que el dashboard pueda dibujar una versión legible sin inventar una
formación, el loader deriva coordenadas normalizadas únicamente de la línea y
el hueco publicados:

- Eje horizontal de la aplicación: portero, defensa, centro del campo y ataque,
  respectivamente en `0.14`, `0.38`, `0.62` y `0.86`.
- Para una línea con ordinal `i` y tamaño `n`, el eje vertical es
  `0.10 + 0.80 × i / (n + 1)`.
- Los huecos ausentes quedan vacíos. El parser nunca rellena posiciones ni
  incorpora jugadores fuera de `Titulares`.

La orientación izquierda a derecha y la separación entre líneas pertenecen al
componente visual de FootballDataHub; no son coordenadas pixel a pixel
extraídas de BDFutbol. Cada punto conserva `player_id`, `source_dom_id`,
`source_view=alignment` y SHA-256 del snapshot de Alineación. El contrato
Pydantic/Zod marca la disposición como aproximada y el ETag avanza a la versión
2.

Si falta la raíz táctica, un enlace válido, una identidad de jugador o la
pertenencia a `Titulares`, la Plantilla sigue sirviéndose y la táctica se omite
con una advertencia. No se supone que futuras capturas tengan once posiciones
válidas.

## Indicadores

La interfaz solo muestra códigos presentes en `verified_indicators`:

- `played_in_first_division`: ha jugado en Primera División.
- `played_in_second_division`: ha jugado en Segunda División.
- `youth_international`: internacional en categorías inferiores.
- `new_signing`: nueva incorporación.

Los textos proceden de la leyenda validada del snapshot. Los colores de los
puntos son una clave visual de FootballDataHub, no una afirmación sobre la
paleta exacta de los CSS externos de BDFutbol.

## Estadísticas

Las dos tablas conservan el orden de `squad_groups` y unen edad/foto/nombre,
pertenencia y estadísticas por `player_id`. PJ, PT, PC, PS, C, minutos, TA,
TR y G proceden de `player_statistics.json`, que corresponde a la vista
Estadísticas. No se usan los números ambiguos de `#taulaplantilla`: en Jaén,
Morillas conserva `G=0` de Estadísticas, no el `G=-5` de la tabla compacta de
Alineación. El código numérico de demarcación no tiene una conversión
verificada, así que la columna Pos. no se presenta.
