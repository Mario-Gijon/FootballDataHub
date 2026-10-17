# UI-02.2 — fichas de jugador y tablas semánticas

## Inspección y alcance

El 17/10/2026 se inspeccionaron en navegador las fichas BDFutbol de [Manu Pedreño](https://www.bdfutbol.com/es/j/j23751.html), [Nacho Castillo](https://www.bdfutbol.com/es/j/j28577.html) y [Salvi](https://www.bdfutbol.com/es/j/j19269.html), en sus apartados Trayectoria, Estadísticas, Partidos y Rivales. No apareció un desafío. La inspección se limitó a esas páginas y no inició adquisición.

La aplicación lee los snapshots ya guardados, capturados el 14/10/2026, y un derivado temporal preparado en `/tmp/ui022-player-compact`. No se cambiaron capturas, índices activos, inventarios, checkpoints ni generaciones publicadas. Las identidades verificadas de Manu coinciden entre ficha individual y snapshot: Manu Pedreño, Antonio Manuel Moñino Pedreño, 09/10/2000, Los Garres (Murcia), España como país de nacimiento, central, 190 cm y 81 kg. La ficha no publica nacionalidad para él, así que no se presenta una. En los tres jugadores la vista web actual y los snapshots pertenecen a momentos distintos; este trabajo valida significado y conservación de las tablas, pero no afirma que todos los valores históricos actuales de la web coincidan fila por fila con la captura del día 14.

## Interpretación preservada

### Cabecera e identidad

La API selecciona cada campo no vacío de la ficha individual y usa el inventario solo como respaldo. Las discrepancias permanecen en el modelo interno. Nacionalidad y país de nacimiento son campos separados. La interfaz omite un valor ausente y solo ofrece un equipo de referencia cuando la evidencia del backend lo considera observado. Un movimiento identificado se presenta dentro de Trayectoria como un movimiento de la temporada, sin afirmar que su destino sea el club actual.

Para los perfiles revisados, la proyección produjo cuatro vistas y estos partidos observados: Manu 108, Nacho 88 y Salvi 90. Son los registros presentes en sus snapshots, no una certificación de exhaustividad histórica.

### Trayectoria y totales

La tabla de trayectoria mantiene todas las 26 columnas del HTML. Las cabeceras originales y sus títulos/tooltip se conservan en los datos de origen; la vista usa etiquetas en español legibles:

`Temporada`, `Equipo`, `País`, `Ascenso o descenso`, `División`, `Edad`, `Partidos Jugados`, `Partidos titular`, `Partidos completos`, `Partidos suplente`, `Partidos sustituido`, `Partidos incompletos`, `Partidos convocado`, `Total convocado`, `Ganados`, `Empatados`, `Perdidos`, `Minutos`, `Tarjetas amarillas`, `Tarjetas rojas`, `Goles`, `Goles penalty`, `Goles propia puerta`, `Goles encajados`, `Dorsal` y `Otras competiciones`.

Las dos columnas vacías en el HTML tienen clases distintas: `.colTrofeu` contiene indicadores de ascenso/descenso y `.colComps` los títulos de competiciones adicionales. El parser conserva esos valores y los compactos los asocian a su fila. La tabla de totales usa las mismas métricas disponibles, sin repetir país, logro ni edad cuando la fuente no los incluye.

### Estadísticas

Las matrices `#table-estadistiques-competicions` y `#table-estadistiques-equips` tienen una primera columna de métricas y columnas posteriores por competición o equipo. Se proyectan como “Estadística” y los encabezados observados en la fuente; se conserva cada fila métrica original (por ejemplo, temporadas, PJ, victorias, minutos, goles, tarjetas, ascensos/descensos y rachas). Los hitos estadísticos se muestran en tablas aparte con temporada, fecha y partido cuando esos campos están presentes. El selector Competiciones/Equipos cambia el conjunto mostrado localmente.

### Partidos

Se conservan los resúmenes por competición, temporada, equipo y rival. El parser relaciona los registros numéricos de `P` con las columnas `data-colid` y títulos reales de `#tpartits`, por `match_id`; no interpreta posiciones arbitrarias de la tupla. Las métricas verificadas son titularidad, partido completo, suplencia, sustitución, convocatoria sin jugar, minutos, amarillas, rojas, goles y goles encajados. Los valores sin dato siguen vacíos/nulos y no se transforman en cero.

Los resúmenes y partidos muestran encabezados de fecha, temporada, competición, jornada, local, marcador, visitante y participación. Los filtros de temporada y competición operan sobre los registros ya cargados en React y no generan nuevas solicitudes. Los enlaces de partido siguen apuntando a BDFutbol, claramente identificados como externos.

### Rivales

Se preservan las tablas de jugadores (`#t5`), entrenadores (`#t6`) y equipos (`#t7`). La tabla de jugadores contiene grupos de métricas del jugador y del rival; la proyección antepone el grupo para distinguir las cabeceras repetidas, por ejemplo `Jugador · Goles` y `Rival · Goles`. Demarcación procede del título de cabecera. El porcentaje aparece como `P%` en BDFutbol sin tooltip semántico en estas tablas; se conserva exactamente esa etiqueta y no se expande ni se calcula otra definición.

## Garantías de columnas

La API usa títulos reales antes que cabeceras visibles y mantiene índices de origen para alinear cada celda. En los snapshots de Manu, Nacho y Salvi se compararon tablas, columnas, filas y celdas compactadas con la proyección: no faltó ninguna columna ni fila. Los encabezados `Temp`, `Tipo` y `#` se presentan como `Temporada`, `Estadística` y `N.º` por el papel verificado de sus tablas. Si una tabla futura trae una columna vacía sin clase ni significado conocido, la proyección falla explícitamente; no publica esa tabla mutilada ni inventa un nombre.

## Presentación

La ficha queda organizada en cuatro pestañas: Trayectoria, Estadísticas, Partidos y Rivales. La cabecera presenta identidad y características disponibles, sin chips ni avisos de adquisición. Los movimientos identificados aparecen en Trayectoria. La tabla de partidos incorpora filtros locales por temporada y competición. Las tablas anchas tienen desplazamiento horizontal en móvil.

No se muestran en la interfaz pública hashes, IDs de capturas, fechas de adquisición, inventarios, códigos de estado, conflictos de fuentes ni mensajes de exhaustividad. La API y los compactos conservan la trazabilidad necesaria para validación interna.

## Validación local reproducible

El test de integración opcional comprueba contra una generación compacta local seleccionada las cuatro vistas, la igualdad de recuentos de tablas/columnas/filas/celdas y las etiquetas de métricas de partidos. Se puede ejecutar con:

```bash
FDH_UI022_RUN_REAL_PROFILE_INTEGRATION=1 \
FDH_UI022_REAL_COMPACT_ROOT=/tmp/ui022-player-compact \
PYTHONPATH=src:apps/api .venv/bin/pytest -q tests/integration/test_ui022_real_player_profiles.py
```

La inspección real de las páginas actuales no sustituye una captura nueva ni habilita una sincronización de datos. La diferencia temporal entre páginas abiertas hoy y snapshots guardados sigue siendo una limitación deliberada.
