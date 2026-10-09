# Hito 1E-B1-I — Encuentros internos de páginas de jugador

**Fecha:** 9 de octubre de 2026 · **Rama:** `rebuild/football-data-hub-v2`
**Alcance:** diagnóstico de `window.P` y `#tpartits` con Manu Pedreño (`j23751`), contraste offline con Morillas (`j209629`) y extracción reutilizable. No se adquirieron otros jugadores.

## Resultado

`window.P` no es un agregado: es una secuencia de registros por encuentro que el JavaScript de BDFutbol convierte en filas de `#tpartits`. Las capturas base guardan esa secuencia aunque la tabla solo muestre su cabecera. El motivo es de presentación: la URL canónica muestra los agregados; una navegación filtrada activa el panel de encuentros.

El parser existente ahora conserva esos registros con su ID, fecha, equipos, marcador, temporada, competición, ronda, campos raw de participación y procedencia. Las posiciones cuyo significado no está demostrado siguen raw. No se declara completa la trayectoria ni el historial de partidos.

## Acceso y evidencia live

Se utilizó la infraestructura existente: `BrowserRuntimeConfig`, `BrowserSessionManager`, Brave con Xvfb, Playwright conectado por CDP, el perfil persistente autorizado `~/.football-data-hub-v2-probe` y `BDFutbolAccess`. No se usaron clientes HTTP alternativos, no se leyeron cookies y no se guardaron nuevas capturas raw.

Las tres navegaciones del documento deportivo fueron HTTP 200 y `VALID`, con identidad `Manu Pedreño` y URL final exacta:

| Recurso | Resultado observado |
|---|---|
| `https://www.bdfutbol.com/es/p/j23751.html` | `#tpartits` tenía solo cabecera; `#pest1` oculto y vista de agregados `#pest2` disponible. `window.P.length == 259`. |
| `https://www.bdfutbol.com/es/p/j23751.html?jug=si` | `VALID`; el control quedó seleccionado, pero esa URL por sí sola no activó filas en `#tpartits`. No se infiere que ese filtro nunca funcione en otro contexto. |
| `https://www.bdfutbol.com/es/p/j23751.html?cat=1rf` | `VALID`; `#pest1` visible, `#pest2` oculto y `#tpartits` con 68 filas DOM: cabecera, 66 encuentros y total. |

El enlace `cat=1rf` existe dentro de la tabla de agregados `#pest2`. La variante no se guardó como snapshot. No apareció desafío Cloudflare/CAPTCHA. La lectura de `scripts_partits.js?v=17.2.6` se hizo desde la página ya validada, en el contexto del navegador; respondió HTTP 200. También cargó `scripts_comuns.js?v=17.2.6` con HTTP 200.

El script `scripts_partits.js` muestra el flujo: `get_data` asigna las 27 posiciones (líneas 415–443), la rama de parámetros alterna los paneles (187–198), el bucle recorre `P.length` (656–658) y añade filas a `#tpartits` (827). Para la página de jugador, calcula `nojuga` a partir de `pt`, `pc` y `ps`; sin un filtro de vista la página conserva el panel agregado. En el modo `cat=1rf`, el valor por defecto de “Partidos jugados” deja 66 filas visibles. No se observó una petición deportiva XHR/fetch que suministre esas filas: ya están en el HTML como `P`. La entrada fetch observada fue telemetría Umami.

No hay una pestaña independiente enlazada a `#pest1` en el DOM inspeccionado. `#pest1` y `#pest2` son paneles que el script muestra u oculta según los parámetros de la URL. Los selectores de competición, temporada, equipo, rival, resultado y participación están en `#pest1`; el detalle aparece siguiendo enlaces filtrados de la tabla resumen. No se probaron combinaciones de filtros.

## Contenido de `window.P`

Ambos raws reutilizados contienen una asignación JSON `P=[...]`, con tuplas de 27 posiciones y un ID de partido distinto por registro. Los nombres de propiedades indicados abajo proceden de `get_data(p, "j")` en el JavaScript live. Los valores originales de cada fila permanecen íntegros en `source_values_raw`.

| Posición | Propiedad JS | Evidencia e interpretación conservadora |
|---:|---|---|
| 0 | `t` | Año inicial de temporada; se contrasta con `nomtemp`. |
| 1 | `cat` | Código raw de competición. No se expanden abreviaturas. |
| 2 | `jor1` | Valor auxiliar raw; vacío en ambos raws. Significado pendiente. |
| 3 | `dat` | Fecha raw `DD/MM/YYYY`. |
| 4 | `loc` | Indica qué lado corresponde al equipo del jugador: `1` local, `0` visitante, según la lógica JS y la coincidencia con las temporadas de equipo observadas. |
| 5–7 | `e1`, `gc`, `gf` | Nombre local, goles locales y goles visitantes. |
| 8 | `id` | ID del partido. El script lo usa para construir `p.php?id=...`; coincide con IDs de los exports de partidos. |
| 9–11 | `pt`, `pc`, `ps` | Flags que las cabeceras describen como partidos de titular, completos y como suplente. El JS los usa para distinguir participación de no participación. |
| 12–13 | `min`, `pv` | Minutos y flag que la cabecera describe como convocado sin jugar. |
| 14 | `tg1` | Campo de tarjetas asociado por la tabla a “Tarjetas amarillas 1”. Se conserva raw. |
| 15 | `tg2` | Propiedad raw del script, sin columna visible equivalente comprobada. No se asigna significado adicional. |
| 16 | `tv` | Campo asociado por la tabla a “Tarjetas rojas”. |
| 17 | `tg` | Valor raw que el script procesa para presentar eventos de gol. No se decodifican códigos ni abreviaturas. |
| 18 | `e2` | Nombre visitante. |
| 19–20 | `ce1`, `ce2` | IDs raw de los equipos local y visitante; se contrastaron con los IDs de club de partidos 2026/27 en los exports de equipos. |
| 21 | `gp` | Código raw que el script usa para filtrar y colorear victoria/empate/derrota. No se normaliza a un resultado semántico. |
| 22 | `genc` | Campo asociado en la cabecera a goles encajados. |
| 23 | `px` | Campo asociado a partidos sustituido. |
| 24–25 | `jor2`, `jor` | Etiqueta de jornada y valor presentado como ronda. |
| 26 | `nomtemp` | Etiqueta raw de temporada, por ejemplo `2026-27`. |

La tabla `#tpartits` conserva 19 columnas configurables, con `data-colid`, `title` y clases responsive. Entre sus títulos live están Fecha, Temporada, Tipo/Competición, Jornada, Local, Marcador, Visitante, partidos de titular/completos/suplente/sustituido/incompletos, convocado sin jugar, minutos, tarjetas, goles y goles encajados. Las cabeceras confirman algunos campos; las restantes posiciones de `P` que no tienen etiqueta suficiente permanecen raw.

## Contraste con datos conservados

Los resultados siguientes se obtuvieron offline de los snapshots válidos; Morillas es evidencia de artefacto, no navegación live de este hito.

| Jugador | Snapshot de Partidos | Estado/hash del HTML | Registros P | IDs únicos |
|---|---|---|---:|---:|
| `j23751` | `data/raw/bdfutbol/20261009T092115.395034Z/j23751/matches` | `VALID`, HTTP 200; `8e1c9aaf2c299390a6f54fcff0a6c850719ab87fbf240e5305b96961b801f29e` | 259 | 259 |
| `j209629` | `data/raw/bdfutbol/luna_audit/20261008T121250.991672Z/player_matches_morillas` | `VALID`, HTTP 200; `82e0145b2dbd8a83a4b7d9e40aebe90b251e9666116faca557a5b70522753cc0` | 81 | 81 |

En los dos HTML base `#tpartits` sigue teniendo cero filas de datos. Los registros salen de `P`, no de la cabecera vacía. Para Manu, los 126 registros raw de `1rf` incluyen 66 con flags de participación y 60 sin ellos. La fila `1ª RFEF` de `#t2` también indica 66 partidos; la navegación live `cat=1rf` produjo exactamente 66 filas individuales más cabecera y total. Para Morillas, sus seis registros `1rf` tienen participación y coinciden con las seis entradas de `#t2`.

Los contadores de participación de `P` coinciden con los agregados de competición `#t2` en todas las categorías de ambos raws. Ejemplos: Manu `2aB` 33, `CNF` 5, `PRF` 1, `COP` 1 y `CHA` 1; Morillas `2aB` 23, `PRF` 4 y `COP` 1. El código raw se mantiene como código; estos contrastes no crean una tabla de traducción general.

También se contrastaron los 18 registros `2026-27` de los dos jugadores con los exports del Hito 1B. Los 12 de Manu y seis de Morillas encontraron su ID de partido y coincidieron exactamente en fecha, local, goles, visitante y marcador. Hay 17 IDs distintos porque ambos aparecen asociados al partido `272550` (Jaén 2–1 UD Ibiza). Los exports del Hito 1D contienen referencias de equipo a esos 17 IDs.

Esto verifica registros de partido de las capturas observadas. No certifica que `P` cubra todas las temporadas o todo el historial de cada jugador.

## Cambios reutilizables

Solo se modificó el parser de jugador y sus pruebas; no cambiaron colector, acceso, contratos de captura ni otras entidades.

- Parser: `0.2.3`; esquema `football_data_hub.bdfutbol.player_pages.v3`.
- Reconoce la asignación serializada `P` solo si es única y todas las tuplas conservan las 27 posiciones comprobadas. Ante ausencia, asignación ambigua o forma distinta, no inventa filas y usa la tabla real como antes.
- En URL base, emite `individual_match_rows` desde `window.P`. Las variantes con query continúan emitiendo filas solo desde `#tpartits`; no repiten todo `P` como si fuera el subconjunto filtrado.
- Cada registro conserva `player_id`, ID/URL de partido, fecha, temporada, competición y ronda raw, equipos, marcador, IDs de equipo, estado del marcador, métricas raw, índice de tupla, orden de campos JS y la tupla exacta.
- Añade estado/cobertura de origen (`WINDOW_P`, `window_p_parse_status`, `window_p_record_count`) y distingue si los flags indican participación o no participación. No se considera `NO_APPEARANCE` si los flags no se pueden interpretar.
- El export incorpora estos registros al dataset existente `individual_matches.json.gz` y `.csv.gz`, con `source` de página que incluye URL, fecha y SHA-256. No se copia HTML a parsed.

No se necesitó otra captura raw: `P` ya estaba en los snapshots base. El reprocesamiento creó este export inmutable nuevo, manteniendo disponible el anterior `parser-0.2.2`:

`data/parsed/bdfutbol/player_2026_27/compact/snapshot-bacd5ecb1e07df3d584e-parser-0.2.3`

Contiene 340 filas de encuentro: 259 de Manu y 81 de Morillas; 39 archivos, 2.300.574 bytes. La cobertura total del conjunto sigue indicando 4.128 vistas pendientes y `career_completeness_certified=false`.

Reprocesar los raws existentes sin abrir navegador:

```bash
PYTHONPATH=src .venv/bin/python scripts/parse_bdfutbol_players_offline.py
```

Una futura actualización live, solo para un ID autorizado y cuando se decida refrescar esa vista, puede usar el colector existente. El refresh crea raw inmutable y mantiene la validación de acceso:

```bash
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_players.py live \
  --player-id j23751 --view matches --refresh
```

## Pruebas y límites

- Prueba específica `tests/test_player_pages.py`: **18 passed**.
- Suite completa en sandbox: el test preexistente `test_loopback_port_valid` no pudo abrir un socket local por la restricción del sandbox. Repetida con permiso para loopback local: **241 passed**.
- Ruff en los dos archivos Python modificados: **All checks passed**.
- `git diff --check`: sin errores.
- Los fixtures sintéticos ejercitan la forma de tupla, la selección de filas de una variante filtrada, y el rechazo de anchos no reconocidos o asignaciones ambiguas; son pruebas del parser, no evidencia de la estructura live. La evidencia estructural procede del JavaScript live, la tabla live y los raws reales de Manu/Morillas.
- No se probaron todas las opciones ni combinaciones de filtros. La captura raw de Morillas no se reabrió live. El parser requiere verificar la forma de `P` en los próximos pilotos y conserva intactos los raws ante una futura forma desconocida.

## Decisión

**GO para continuar con el siguiente piloto pequeño de jugadores**, sujeto a que el acceso vuelva a pasar `BDFutbolAccess` y a validar la estructura `P` del primer nuevo perfil. No se inicia aquí el siguiente lote ni adquisición masiva. En los jugadores comprobados, los IDs de partido, el marcador y las apariciones concuerdan con los agregados y exports de competición; el parser preserva los casos no interpretados y no certifica historial completo.
