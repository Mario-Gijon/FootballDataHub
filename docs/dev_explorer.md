# Dev Explorer V1

El Dev Explorer es una interfaz Streamlit local, de solo lectura, para inspeccionar los exports parsed existentes de Primera Federación 2026/27. No inicia adquisiciones, no visita BDFutbol y no modifica archivos. Detecta los directorios de export automáticamente y selecciona por defecto el dataset válido con la captura de origen más reciente. Se pueden seleccionar datasets anteriores para comparar su contenido.

## Instalación y ejecución

Desde la raíz del repositorio, instala el extra opcional en el entorno virtual actual y ejecuta:

```bash
.venv/bin/python -m pip install -e '.[dev-explorer]'
.venv/bin/streamlit run scripts/run_dev_explorer.py
```

La configuración de Streamlit liga el servidor a `127.0.0.1` y desactiva las métricas de uso. Abre <http://127.0.0.1:8501>. Para detenerlo, usa `Ctrl+C` en esa terminal.

## Secciones

- **Resumen:** recuentos de estructura y resultados, estado de acceso, fecha, URLs y hash de snapshots de origen.
- **Clasificaciones:** tabla de posiciones y ficha breve del equipo elegido.
- **Calendario:** filtros de grupo, jornada, equipo, estado y búsqueda; el resultado ausente se muestra como `—`.
- **Visor de partidos:** campos parsed completos de un partido.
- **Equipos:** participante, clasificación relacionada y partidos del equipo.
- **Calidad y cobertura:** cobertura estructural, disponibilidad de resultados, diagnósticos y comprobaciones de parser por separado. No se reduce a una puntuación agregada.
- **Explorador de datos:** archivos JSON del export, filtro textual, valores null y registros completos.

El cargador tolera la diferencia conocida entre exports antiguos y recientes: cuando un registro antiguo carece de `fixture_status`, deriva `scheduled`, `unresolved` o `unconfirmed` a partir de `result_status`, la fecha del partido y la fecha de captura. Esta presentación no reescribe los JSON. Los directorios ausentes, incompletos o corruptos se informan en el selector y no sustituyen al último dataset válido.

## Limitaciones conocidas

La V1 refleja solo los campos que exporta Hito 1B: competición, participantes, clasificaciones y calendario/resultados con la procedencia y calidad disponibles. No contiene fichas completas de clubes, plantillas, jugadores ni alineaciones de partidos. Los estados calculados para exports antiguos son una ayuda de inspección, no una corrección del dataset ni una nueva evaluación del proveedor.
