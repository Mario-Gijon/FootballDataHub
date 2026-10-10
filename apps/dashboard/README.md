# Dashboard de Primera Federación — Grupos I y II

Aplicación única en React, TypeScript estricto, Vite y Recharts. No importa el scraper Python y no realiza solicitudes a BDFutbol. El selector de la cabecera carga bootstraps desde `/api/v1/groups/1/...` o `/api/v1/groups/2/...`; Grupo II es la selección inicial. Las rutas antiguas de Grupo II siguen soportadas por FastAPI para clientes anteriores.

## Ejecutar en local

Arranca primero la API conforme a [`../../docs/group2_api.md`](../../docs/group2_api.md), con su dataset configurado. Después, desde este directorio:

```bash
npm ci
npm run dev
```

Abre `http://127.0.0.1:5173/`. Vite envía `/api/*` a `http://127.0.0.1:8000` de forma predeterminada. Para una API en otro origen, crea `.env` desde `.env.example` y establece `VITE_API_BASE_URL`. El bundle de producción se crea con `npm run build`.

## Datos y filtros

Cada respuesta se valida en ejecución con Zod, incluido el grupo pedido, antes de usarla. Una respuesta incompatible o un API no disponible lleva a una vista de error con reintento. Los índices y caches se mantienen por grupo y sección; los filtros de interfaz no vuelven a consultar la API. La selección de pestaña se mantiene al cambiar de grupo y los filtros internos permanecen separados.

El motor de `src/domain/classification/engine.ts` reproduce las reglas documentadas del motor BDFutbol: general/local/visitante, tope de jornada, inclusión de partidos aplazados según la regla de la fuente, rangos inclusivos por fechas de partido o jornadas y desempates. Ignora encuentros no disputados y no trata un marcador ausente como 0–0. Si faltan tarjetas en una igualdad, conserva el orden del catálogo y expone una advertencia en vez de inventar el criterio disciplinario.

La posición deportiva se calcula con los datos de resultados. El usuario puede ordenar visualmente por cualquier columna sin cambiar esa posición. Las bandas de color siguen la posición deportiva: ascenso directo para el primero, promoción para el segundo al quinto y descenso para el decimosexto al vigésimo. Se etiquetan como referencias cuando el contexto no coincide exactamente con `published_standings`. Los movimientos y las zonas oficiales solo se muestran con coincidencia de tipo, jornada y política de aplazamientos. El progreso general no se usa para inferir movimientos porque su política de aplazamientos es desconocida.

El gráfico usa las series históricas `progress` del bootstrap, no las recalcula a partir de resultados. Conserva los `null` publicados y no interpola ausencias. Sus series mantienen su contexto original aunque cambien los filtros de la tabla.

## Desarrollo y pruebas

```bash
npm test
npm run build
npm audit --omit=dev
```

Las pruebas incluyen nueve tablas de referencia calculadas por el JavaScript de BDFutbol y fixtures de API construidos desde los JSON reales versionados. Esos nueve contextos comprueban 20 equipos por 10 campos deportivos (1.800 valores), además de casos sintéticos acotados para rangos, local/visitante, estados sin resultado, aplazamientos y desempates. Para la integración manual, ejecuta la API y Vite y comprueba la carga, los filtros y el gráfico desde el navegador.

El dataset actual fue capturado el 10 de octubre de 2026: 20 equipos, 380 partidos programados, 59 disputados con resultado hasta J6, y 120 valores históricos de progreso. El dataset no declara equivalencia contra BDFutbol para los contextos que no estén en esas referencias. `includePostponed` conserva la regla observada por la fuente, pero la captura disponible no contiene un caso que permita contrastar un aplazamiento real.

El contrato actual tampoco incluye un campo de ajuste manual de puntos. Los nueve escenarios de referencia coinciden íntegramente, pero no prueban sanciones futuras ni desempates extraordinarios que no estén representados en el algoritmo fuente; esas diferencias deberán revisarse contra una tabla publicada cuando haya un caso real.
