# UI-02: perfiles individuales completos y plantillas publicadas

## Compactos de jugadores

La API consulta el puntero externo
`$HOME/FootballDataHub-data/players/compact-2026-27/current.json`. El inventario y las capturas individuales siguen siendo las fuentes; la generación compacta es una proyección derivada, versionada y reproducible que no modifica esas capturas.

La publicación se realiza en dos pasos: generar en una raíz temporal con `build_bdfutbol_player_compact_exports.py --complete-only --progress-index …`, validar manifest, hashes, IDs y las cuatro vistas, y luego copiar la generación inmutable y mover atómicamente el puntero. La generación anterior permanece disponible para rollback.

El arranque del API comprueba la identidad y el SHA-256 de cada archivo gzip del manifest, sin descomprimir todos los perfiles. Al solicitar una ficha, el API vuelve a comprobar el hash del archivo seleccionado, descomprime y valida su ID, temporada, estado y vistas. Una caché LRU conserva como máximo 12 documentos. Así, buscar o paginar el inventario no abre miles de JSON individuales.

La respuesta de cada vista conserva su cobertura, tablas y columnas de origen, todos los valores normalizados de las celdas, campos contextuales de las filas y, en Partidos, resúmenes, apariciones, convocatorias sin participación, otros registros y el estado de exhaustividad. Los valores cero y null se mantienen distintos.

## Plantillas de equipos

El índice explícitamente publicado de los 40 equipos reside fuera de Git en `$HOME/FootballDataHub-data/published/team_profiles_2026-27.json`. Para que el API use ese índice y sus capturas sin reemplazar el archivo histórico de dos pilotos del repositorio, se configura `FDH_TEAM_PROFILES_INDEX` al iniciar el API. El registro existente valida cada captura contra el catálogo activo del grupo antes de servirla.

Las capturas de Plantilla y Traspasos están disponibles para los 40 clubes. Algunas capturas de Seguimiento remiten a encuentros que los catálogos de competición seleccionados aún marcan como no disputados; esas respuestas permanecen aisladas como inválidas y no se fuerzan sobre el catálogo ni impiden servir Plantilla.

## Ejecución local

```bash
FDH_LOCAL_DATA_ROOT="$HOME/FootballDataHub-data" \
FDH_TEAM_PROFILES_INDEX="$HOME/FootballDataHub-data/published/team_profiles_2026-27.json" \
PYTHONPATH=src:apps/api .venv/bin/uvicorn football_data_hub_api.main:app --host 127.0.0.1 --port 8000
```

En otra terminal:

```bash
cd apps/dashboard
npm run dev -- --host 127.0.0.1 --port 5173
```

## Límites de cobertura

Una relación de pertenencia proviene de la captura de plantilla y no certifica afiliación actual. Las capturas individuales son las vistas base observadas; filtros de temporada, equipo, competición, rival y demarcación que no se recorrieron no se presentan como exhaustivos. Las series históricas se limitan a las filas y filtros realmente capturados por BDFutbol.
