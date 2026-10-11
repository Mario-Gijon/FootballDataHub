# Plantillas de equipo en la API

La ficha de Plantilla se sirve desde capturas normalizadas y validadas de BDFutbol. La API no navega ni vuelve a interpretar HTML durante una petición.

## Publicación explícita de una captura

`config/team_profiles_2026-27.json` es el índice de publicación. Solo se aceptan capturas enumeradas en `profiles`, con `capture_id`, directorio y SHA-256 fijados para cada archivo necesario. No se elige automáticamente la captura más reciente.

Las rutas relativas de `directory` se resuelven desde el directorio del propio índice. En el servidor de la UJA, se puede montar el índice y las capturas fuera del repositorio y señalar el índice mediante `FDH_TEAM_PROFILES_INDEX`. La ruta puede ser absoluta o relativa a la raíz del proyecto. Cada proceso valida el índice y prepara los perfiles en memoria al arrancar; publicar una captura nueva requiere actualizar el índice y reiniciar el proceso de API.

Para añadir otro equipo:

1. Guardar la captura normalizada en almacenamiento persistente.
2. Validar identidad, grupo, temporada, archivos normalizados y evidencia de las vistas Alineación, Plantilla y Estadísticas.
3. Comprobar que `related_team_catalog` apunta al catálogo activo del grupo.
4. Añadir una entrada explícita con su `capture_id`, ruta y SHA-256 de cada archivo que consume Plantilla.
5. Reiniciar la API y verificar el endpoint del equipo.

Los archivos de una captura seleccionada son inmutables desde la perspectiva de la API. Si falta un hash o no coincide, el perfil se marca inválido. Ese fallo se aísla al equipo afectado; no impide cargar el otro grupo ni otro perfil válido. La captura histórica de Jaén puede publicarse para Plantilla aunque no incluya los estados enriquecidos de Seguimiento.

## Endpoint y estados

`GET /api/v1/teams/{team_id}/seasons/2026-27/roster`

- `200`: captura validada, con metadata, entrenadores, jugadores, pertenencias, estadísticas, categorías publicadas, posiciones tácticas derivadas y procedencia.
- `304`: el cliente envió el ETag actual.
- `404 team_unknown`: ID ausente en los catálogos cargados.
- `404 profile_not_captured`: equipo conocido que aún no figura en el índice.
- `404 season_not_available`: temporada distinta de 2026/27.
- `503 profile_invalid`: captura seleccionada, pero inválida.
- `503 profile_index_unavailable`: índice ausente o no válido.

El contrato público de Plantilla está en la versión 2. El ETag incluye esa versión, el equipo, la temporada y una huella del contenido fijado, incluida la disposición táctica derivada. Un ETag de la versión 1 no debe producir `304`.

## Procedencia y uniones

El servidor valida SHA-256 de los archivos indexados, los metadatos de captura, el informe de validación, las respuestas de acceso, la identidad del catálogo relacionado y los snapshots de las tres vistas. Los jugadores se unen con estadísticas y pertenencias exclusivamente por `player_id`. Los IDs, campos opcionales y categorías no se completan por inferencia. Un perfil puede contener cualquier número positivo de jugadores; las tres listas no se suponen de longitud fija.

La respuesta solo expone los campos de Plantilla. Los datos de Seguimiento, Traspasos y partidos permanecen en sus futuras vistas y no se duplican aquí.

## Posiciones tácticas

El loader interpreta offline `#alineacio #tactica #js` del snapshot ya verificado. Conserva la relación por `player_id`; cada posición incluye su `source_dom_id`, la vista de origen y el hash del HTML. La forma de los IDs de la captura, como `d_def13` o `d_mig24`, conserva la línea y el ordinal/tamaño de esa línea. Con esos componentes se deriva una disposición normalizada de portero a defensa, centro del campo y ataque. Es una visualización aproximada propia: las capturas no contienen las reglas CSS externas ni coordenadas calculadas, por lo que no se afirma que coincida con la orientación o geometría exacta del campo de BDFutbol. Si la raíz, las referencias a jugadores o los IDs no se pueden validar contra Titulares, el endpoint sigue disponible y devuelve `tactical_visualization: null` con una advertencia.

## Comprobación local

Desde la raíz del proyecto:

```bash
.venv/bin/uvicorn football_data_hub_api.main:app --app-dir apps/api --reload
```

En el dashboard, abre `/teams/49/roster` o `/teams/48/roster`. La página continua muestra entrenadores, titulares, suplentes, indicadores y la disposición espacial si está validada. Las estadísticas se unen por `player_id` desde la vista completa de Estadísticas, no desde la tabla compacta de Alineación. Para un club sin perfil publicado, la ficha deportiva sigue disponible y la vista indica que la Plantilla todavía no se ha adquirido.
