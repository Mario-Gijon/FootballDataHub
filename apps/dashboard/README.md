# Dashboard de clasificación del Grupo II

Aplicación independiente en React, TypeScript estricto, Vite y Recharts. No importa el scraper Python y no realiza solicitudes a BDFutbol. Carga una vez el endpoint `GET /api/v1/group2/bootstrap` y calcula las vistas de clasificación en cliente.

## Ejecutar en local

Arranca primero la API conforme a [`../../docs/group2_api.md`](../../docs/group2_api.md), con su dataset configurado. Después, desde este directorio:

```bash
npm ci
npm run dev
```

Abre `http://127.0.0.1:5173/`. Vite envía `/api/*` a `http://127.0.0.1:8000` de forma predeterminada. Para una API en otro origen, crea `.env` desde `.env.example` y establece `VITE_API_BASE_URL`. El bundle de producción se crea con `npm run build`.

## Datos y filtros

El contrato de respuesta se valida en ejecución con Zod antes de usarlo. Una respuesta incompatible o un API no disponible lleva a una vista de error con reintento. Al cargar se crean índices por `team_id` y `match_id`; los resultados se conservan en memoria mientras el usuario cambia filtros, que no vuelven a consultar la API.

El motor de `src/domain/classification/engine.ts` reproduce las reglas documentadas del motor BDFutbol: general/local/visitante, tope de jornada, inclusión de partidos aplazados según la regla de la fuente, rangos inclusivos por fechas de partido o jornadas y desempates. Ignora encuentros no disputados y no trata un marcador ausente como 0–0. Si faltan tarjetas en una igualdad, conserva el orden del catálogo y expone una advertencia en vez de inventar el criterio disciplinario.

La posición deportiva se calcula con los datos de resultados. El usuario puede ordenar visualmente por cualquier columna sin cambiar esa posición. El movimiento y las zonas se muestran únicamente cuando el contexto coincide con la clasificación original que publica BDFutbol (General, J6, todos los partidos). No se extrapolan los marcadores de ascenso/descenso a otras jornadas.

El gráfico usa las series históricas `progress` del bootstrap, no las recalcula a partir de resultados. Conserva los `null` publicados y no interpola ausencias. La captura disponible ofrece 120 valores (20 equipos hasta J6); la aplicación indica el contexto y el corte de esas series.

## Desarrollo y pruebas

```bash
npm test
npm run build
npm audit --omit=dev
```

Las pruebas incluyen nueve tablas de referencia calculadas por el JavaScript de BDFutbol y fixtures de API construidos desde los JSON reales versionados. Esos nueve contextos comprueban 20 equipos por 10 campos deportivos (1.800 valores), además de casos sintéticos acotados para rangos, local/visitante, estados sin resultado, aplazamientos y desempates. Para la integración manual, ejecuta la API y Vite y comprueba la carga, los filtros y el gráfico desde el navegador.

El dataset actual fue capturado el 10 de octubre de 2026: 20 equipos, 380 partidos programados, 59 disputados con resultado hasta J6, y 120 valores históricos de progreso. El dataset no declara equivalencia contra BDFutbol para los contextos que no estén en esas referencias. `includePostponed` conserva la regla observada por la fuente, pero la captura disponible no contiene un caso que permita contrastar un aplazamiento real.

El contrato actual tampoco incluye un campo de ajuste manual de puntos. Los nueve escenarios de referencia coinciden íntegramente, pero no prueban sanciones futuras ni desempates extraordinarios que no estén representados en el algoritmo fuente; esas diferencias deberán revisarse contra una tabla publicada cuando haya un caso real.
