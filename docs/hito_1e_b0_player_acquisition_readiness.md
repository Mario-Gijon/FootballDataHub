# Hito 1E-B0 — Preparación offline del piloto de jugadores

## Alcance y resultado

Este hito se ejecutó offline. No se abrió Brave, no se conectó a CDP, no se consultó BDFutbol ni se descargaron recursos. Se reutilizaron los exports y snapshots locales existentes para preparar un plan reanudable y un colector de vistas de jugador.

El parser de jugadores pasa a la versión `0.2.1`. Se corrigió la selección determinista de representantes: `first_by_position` ahora consulta la posición raw como clave, por lo que conserva el primer jugador ordenado de cada código en vez de reemplazarlo en cada fila. El export corregido se escribió en `data/parsed/bdfutbol/player_2026_27/compact/snapshot-d27b77fd5d7c449ec461-parser-0.2.1`; el export previo `parser-0.2.0` permanece intacto.

## Piloto seleccionado

Los candidatos salen de las 1.039 pertenencias de plantillas locales de los 40 participantes de 2026/27. Los códigos de posición se conservan como códigos raw; no se les asigna un significado semántico nuevo.

| Player ID | Código(s) raw | Equipo-temporada y grupo | Motivo adicional |
|---|---:|---|---|
| `j23751` | 4 | UD Logroñés (I); UD Ibiza (II) | Dos pertenencias, cubre ambos grupos |
| `j26481` | 10 | Sant Andreu (II); Huesca (II) | Dos pertenencias; Huesca con cero apariciones |
| `j100160` | 2 | Real Unión (I) | Representante código raw 2 |
| `j100350` | 10 | Ponferradina (I) | Representante código raw 10 |
| `j100397` | 3 | FC Cartagena (II) | Representante código raw 3 |
| `j101816` | 9 | Hércules (II) | Representante código raw 9 |
| `j102284` | 1 | Racing de Ferrol (I) | Representante código raw 1 |
| `j103389` | 1 | Antequera (II) | Pertenencia con cero apariciones |
| `j108959` | 5 | Barakaldo (I) | Representante código raw 5 |
| `j209629` | 1 | Jaén (II) | Morillas, baseline con snapshots existentes |
| `j304209` | 2 | Lugo (I); Avilés Industrial (I) | Dos pertenencias |
| `j304291` | 10 | Deportivo Fabril (I); Pontevedra (I) | Dos pertenencias |
| `j402372` | 4 | Pontevedra (I); Lugo (I) | Dos pertenencias, ambas con cero apariciones |
| `j1000865` | 6 | Águilas FC (II) | Representante código raw 6 |
| `j1014877` | 4 | Águilas FC (II) | Representante código raw 4 |

La lista cubre los ocho códigos raw presentes en la fuente (`1`, `2`, `3`, `4`, `5`, `6`, `9`, `10`), casos de cero apariciones, pertenencias múltiples y equipos de ambos grupos. No se atribuye una longitud prevista a las trayectorias aún no capturadas.

## Manifiesto y dry-run

`scripts/scrape_bdfutbol_players.py dry-run` construye un plan reproducible a partir de `rosters.json.gz` y `data/raw/bdfutbol/`. Valida HTML mediante los hashes del snapshot y nunca instancia el gestor de navegador. El JSON del plan incluye por jugador y vista: ID, equipos-temporada, URL, procedencia de la URL, estado de captura, snapshots y hashes disponibles, variantes filtradas, vistas pendientes, orden, lote y estado de parseo/cobertura.

Las rutas canónicas de las vistas son:

| Vista | Ruta | Procedencia del plan |
|---|---|---|
| Perfil/Trayectoria | `/es/j/j<ID>.html` | La URL de perfil procede de roster; queda verificada al existir snapshot válido |
| Estadísticas | `/es/j/j<ID>.html?p=stats` | Inferida del patrón de rutas observado hasta validación por snapshot |
| Partidos | `/es/p/j<ID>.html` | Inferida del patrón de rutas observado hasta validación por snapshot |
| Rivales | `/es/p/jr<ID>.html` | Inferida del patrón de rutas observado hasta validación por snapshot |

La comprobación realizada con los datos del repositorio produjo 15 jugadores, 60 vistas, 5 lotes de 3 jugadores y 56 vistas pendientes. Hay cuatro snapshots base válidos de Morillas, uno por vista; 4.132 vistas siguen pendientes en el inventario completo de 1.034 jugadores. En el almacenamiento hay cinco snapshots base válidos de jugador porque existe una captura anterior duplicada de su perfil; el parser selecciona la captura más reciente y no duplica su HTML en los exports.

Lotes planificados, ordenados por ID numérico y con las cuatro vistas en orden perfil, estadísticas, partidos, rivales:

1. `j23751`, `j26481`, `j100160`
2. `j100350`, `j100397`, `j101816`
3. `j102284`, `j103389`, `j108959`
4. `j209629`, `j304209`, `j304291`
5. `j402372`, `j1000865`, `j1014877`

En los snapshots locales de Morillas el parser observó 3 filas de trayectoria, 97 filas estadísticas, 51 filas agregadas de partidos y 533 relaciones/fichas de rivales. La vista de partidos contiene una tabla individual solo con encabezado: no se encontraron filas de encuentros individuales en esa captura. Los filtros de las vistas se identifican, pero su interacción no se probó en este hito.

## Colector preparado

`src/football_data_hub/collectors/bdfutbol_player.py` reutiliza `BrowserSessionManager`, `BDFutbolAccess` y `capture_dom_snapshot`; no añade otro gestor de navegador. `scripts/scrape_bdfutbol_players.py` ofrece dos modos:

- `dry-run`: carga roster y snapshots locales, comprueba integridad, prepara lotes y reporta cobertura; no inicia navegador ni hace conexiones.
- `live --player-id jNNN`: futuro modo explícito, limitado a tres IDs por ejecución. Reutiliza snapshots base válidos; `--refresh` escribe un run nuevo y no sobrescribe lo previo.

Cada respuesta live debe ser `VALID` por BDFutbolAccess y coincidir con el jugador/vista pedidos. Un desafío, error de acceso o raw inconsistente detiene el run; `acquisition_state.json` registra la interrupción y los snapshots válidos anteriores quedan conservados. Al reanudar con los mismos IDs, el colector vuelve a validar y reutiliza snapshots íntegros. Los errores no se tratan como datos deportivos. No se cambia IP, perfil o mecanismo de acceso ni se intenta resolver Cloudflare/CAPTCHA.

## Cobertura y preservación

El plan y su sección de cobertura separan `PENDING_CAPTURE`, variantes filtradas sin vista base, snapshot base raw-only, snapshot parseado y tablas requeridas ausentes. Para snapshots parseados se informa el número de filas interpretadas por colección, filas raw de tabla, controles de filtro y roles de tabla ausentes. Una vista capturada no certifica trayectoria completa: el plan mantiene `career_completeness: NOT_ASSESSED`.

Las capturas nuevas usan un directorio timestamp único bajo `data/raw/bdfutbol/`; el HTML renderizado, inventario y metadata conservan procedencia y SHA-256. No se escriben tablas raw duplicadas en el export. Los exports JSON/CSV gzip son deterministas y versionados; al corregir la selección se generó `parser-0.2.1` y no se modificó `parser-0.2.0`. El dry-run consulta el export de rosters/relaciones ya preparado y los snapshots de jugador; no vuelve a parsear páginas de clubes.

## Pruebas offline

Las pruebas nuevas cubren la clave de posición, orden y lotes deterministas, procedencia de URLs inferidas, una variante filtrada, dry-run sin iniciar el navegador, reutilización, refresh inmutable, invalidación de hash, parada inmediata ante challenge, conservación de capturas parciales y reanudación. Las pruebas existentes del parser usan los cuatro raw reales de Morillas y fixtures sintéticos marcados como tales para filas cero, totales, duplicados, filtros, valores ausentes, relaciones y columnas raw. Los casos sintéticos ejercitan la lógica del parser; no se presentan como estructuras reales observadas.

Comandos de preparación local:

```bash
PYTHONPATH=src:scripts .venv/bin/python scripts/parse_bdfutbol_players_offline.py \
  --raw-root data/raw/bdfutbol \
  --club-sports data/parsed/bdfutbol/club_team_2026_27/compact/snapshot-f36c91119a98390766ff-parser-1.3.0/sports \
  --output-root data/parsed/bdfutbol/player_2026_27

PYTHONPATH=src:scripts .venv/bin/python scripts/scrape_bdfutbol_players.py dry-run
```

## GO / NO-GO

- **GO para completar la preparación offline:** el plan se genera desde los exports locales, las cuatro vistas de Morillas se validan y parsean, y el colector reanudable está cubierto con dobles sin tráfico real.
- **NO-GO para ejecutar el piloto live en este hito:** no se comprobó el estado actual de acceso, y esta tarea prohíbe las peticiones. Antes de capturar se requiere acceso autorizado y una decisión expresa para el hito live. Empezar con el primer lote de tres, revisar estado, hashes y cobertura antes de continuar al siguiente; detenerse ante cualquier challenge.
- **NO habilitado:** no existe un modo para recorrer automáticamente los 1.034 perfiles. El modo live exige IDs y rechaza lotes de más de tres.

Tras validar manualmente un lote, se puede planificar el siguiente. La expansión solo debe ocurrir después de comprobar snapshots, parseo, cobertura y duplicados; las vistas filtradas y cualquier dato de carrera que falte se investigan como variantes explícitas, sin declarar cobertura completa por tener cuatro vistas base.
