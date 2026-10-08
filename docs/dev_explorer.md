# Preview deportiva local

La preview es una aplicación Streamlit local, deportiva y de solo lectura para los exports parsed de Primera Federación 2026/27. Funciona con los JSON ya creados por Hito 1B; no visita BDFutbol, no inicia scrapers y no modifica snapshots ni exports.

## Instalación y ejecución

Desde la raíz del repositorio, instala las dependencias opcionales y arranca la aplicación:

```bash
.venv/bin/python -m pip install -e '.[dev-explorer]'
.venv/bin/streamlit run scripts/run_dev_explorer.py
```

Abre <http://127.0.0.1:8502>. Streamlit queda ligado a `127.0.0.1` y sus métricas de uso están desactivadas. Detén el servidor con `Ctrl+C`.

## Navegación

- **Inicio:** cifras del grupo elegido, resultados recientes, próximos encuentros y cinco primeros puestos.
- **Clasificación:** tabla completa con estadísticas de posición, puntos, partidos, goles y tarjetas; incluye un resumen del equipo seleccionado.
- **Calendario:** filtro por grupo y jornada, estado en español, fecha, marcador y campos de estadio y árbitro cuando existen.
- **Equipos:** posición, estadísticas y los últimos resultados y próximos partidos del equipo seleccionado.
- **Partidos:** ficha deportiva con equipos, marcador, jornada, fecha, estado, estadio, árbitro y enlace de origen cuando está publicado.
- **Calidad y procedencia:** acceso secundario desde el final de la barra lateral. Conserva los checks del parser, los diagnósticos, los registros sin ID, la validez de acceso, las URLs de origen y el hash del snapshot.

El selector detecta automáticamente los exports, permite elegir una captura anterior y selecciona por defecto la captura válida más reciente según sus metadatos. Las capturas incompletas se identifican sin mostrar rutas internas en las vistas deportivas.

## Limitaciones

La V1 representa solo la información que exporta Hito 1B: competición, participantes, clasificaciones y calendario/resultados. No incluye fichas completas de clubes, plantillas, jugadores, alineaciones o estadísticas individuales. Los resultados y estadísticas se muestran únicamente cuando están presentes en el export. Para datos antiguos sin `fixture_status`, la capa de presentación deriva estados a partir de `result_status`, fecha y captura; no reescribe el dataset.
