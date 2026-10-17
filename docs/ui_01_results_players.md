# UI-01: Resultados y jugadores

## Fuentes verificadas

- Resultados se sirven desde la generación local MATCH-00 `match-00-4ad1d610507e425d`, comprobada con `load_verified_match_generation()`. Contiene 40 equipos y 760 partidos: 380 por grupo, 70 disputados por grupo (140 con marcador) y 620 pendientes con goles `null`. La API conserva el ID y URL BDFutbol, la jornada, fechas, estadio y árbitro disponibles. Esta generación no reemplaza las capturas empleadas por Clasificación, Progreso, Árbitros o Estadísticas.
- El inventario de jugadores se verifica usando su manifest, hashes, las 40 capturas de equipo declaradas y el índice de perfiles publicado. La captura local contiene 1.709 IDs únicos, 1.065 con pertenencia de plantilla observada, 644 referenciados solo en traspasos y 1.070 relaciones de pertenencia.
- La publicación compacta existente es `20261014T170309.300465Z-c005a946`: cuatro jugadores con sus cuatro vistas base completas. No se presenta el progreso de adquisición como si fuera una generación compacta publicada. Los otros IDs se pueden buscar y consultar en su ficha de inventario, pero esta versión no afirma que tengan vistas individuales listas para mostrar.

## API

- `GET /api/v1/matches/bootstrap`: los dos grupos, fixtures, marcadores y procedencia de MATCH-00. Los pendientes no se convierten en empates.
- `GET /api/v1/players?q=...&group=I|II&team_id=...&page=1&page_size=25`: directorio con filtros y paginación.
- `GET /api/v1/players/{player_id}`: inventario, relaciones, datos de temporada disponibles y, cuando existe un compacto válido, sus vistas individuales estructuradas.

La aplicación carga Resultados de forma independiente al entrar en esa sección. El dashboard mantiene los endpoints anteriores de Clasificación y no solicita datos a BDFutbol.

## Arranque local

En la raíz del proyecto, arrancar la API:

```bash
FDH_LOCAL_DATA_ROOT="$HOME/FootballDataHub-data" PYTHONPATH=src:apps/api .venv/bin/uvicorn football_data_hub_api.main:app --host 127.0.0.1 --port 8000
```

En otra terminal, arrancar el dashboard:

```bash
cd apps/dashboard
npm run dev -- --host 127.0.0.1 --port 5173
```

El proxy de desarrollo de Vite envía `/api` a `http://127.0.0.1:8000`.

- Aplicación: `http://127.0.0.1:5173/`
- Resultados: abrir Competiciones → Resultados y seleccionar Grupo I o II.
- Jugadores: `http://127.0.0.1:5173/players`
- Ficha de Nacho Castillo: `http://127.0.0.1:5173/players/28577`
- API de resultados: `http://127.0.0.1:8000/api/v1/matches/bootstrap`
- API de jugadores: `http://127.0.0.1:8000/api/v1/players`

## Verificación de datos externos al repositorio

Las pruebas locales de integración están separadas de la suite automática. Para ejecutarlas con los datos en `$HOME/FootballDataHub-data`:

```bash
FDH_UI01_RUN_LOCAL_INTEGRATION=1 PYTHONPATH=src:apps/api .venv/bin/pytest -p no:rerunfailures -q tests/integration/test_ui01_local_data.py -m integration
```

No modificar el índice `current.json` de la compactación original, las capturas, el inventario ni los estados de adquisición para esta interfaz.
