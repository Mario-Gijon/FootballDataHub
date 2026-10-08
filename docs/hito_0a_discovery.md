Hito 0A — Discovery DOM de BDFutbol
Objetivo
Inventariar sin hacer clic los elementos de páginas piloto de BDFutbol,
sobre una sesión Brave + Xvfb + CDP ya autorizada (Hito 1A).
El inventario NO es una declaración de exhaustividad. Una captura VALID indica
acceso y documento correcto, mientras que scope=DOM_SNAPSHOT_ONLY,
complete=false e interaction_coverage=NOT_TESTED reflejan la cobertura real.
Rutas y archivos
- Módulo: src/football_data_hub/providers/bdfutbol/discovery.py
- CLI: scripts/discover_bdfutbol_page.py
- Tests: tests/test_bdfutbol_discovery.py
- Raw inmutable: data/raw/bdfutbol/discovery_0a/<UTC>/<target>/
  - rendered.html: HTML DOM renderizado
  - inventory.json: enlaces, tablas, controles, imágenes, gráficos y galerías candidatos
  - metadata.json: origen, fecha, SHA-256, diagnóstico de acceso
  - summary.json: conteos y límites alcanzados
  - screenshot.png: opcional
  - INCOMPLETE: solo si falló la captura a mitad de proceso
- Análisis: data/analysis/bdfutbol/discovery_0a/<UTC>/summary.json
Inventario del DOM
- Enlaces, URL y familia de rutas; incluye los enlaces a pestañas que generan nuevas URLs.
- Tablas con encabezados, cantidad de filas y muestras pequeñas para clasificar tablas de datos frente a maquetación.
- select con sus opciones, botones, tabuladores, paneles, details, controles personalizados (combobox, menús, dropdowns y collapse) y formularios sin guardar valores de inputs.
- Imágenes, srcset, referencias lazy, <picture><source>, galerías y disparadores del tipo Fotos (N).
- Posibles gráficos canvas, svg, contenedores chart / graph y librerías indicadas por script.
- URLs de recursos XHR/fetch presentes en la API Performance cuando estén disponibles. Esta lista no es un HAR y puede omitir peticiones.
Los recuentos se limitan con parámetros CLI para evitar archivos inmanejables y
el JSON avisa cuando se alcanza un límite. El HTML completo permite análisis posteriores.
Ejecución
Desde la raíz del repositorio, con la sesión autorizada y sin otro proceso usando el perfil:
PYTHONPATH=src .venv/bin/python -m pytest -q

PYTHONPATH=src .venv/bin/python scripts/discover_bdfutbol_page.py \
  --profile "$HOME/.football-data-hub-v2-probe" \
  --target morillas
Para comparar ficha y estadísticas:
PYTHONPATH=src .venv/bin/python scripts/discover_bdfutbol_page.py \
  --profile "$HOME/.football-data-hub-v2-probe" \
  --target morillas --target morillas_stats --screenshots
--screenshots es opcional. No ejecutamos un batch ni navegamos a enlaces externos.
Criterio de aceptación 0A
1. La página pasa la validación semántica del Hito 1A.
2. Se generan un HTML renderizado y un inventario JSON reproducible.
3. Se señalan límites de captura y posibles controles ocultos.
4. No se clican pestañas, selectores, galerías o formularios.
5. El raw queda separado de analysis/ y no se sobreescriben snapshots anteriores.
6. Ante desafío Cloudflare, se detiene la captura sin guardar un raw engañosamente válido.
Límites y siguiente hito
No almacena los datos de las vistas que aparecen tras una interacción ni
recorre todas las fotografías. SVG también puede representar simples iconos.
La sección xhr solo refleja peticiones presentes en Resource Timing;
no guarda respuestas ni cuerpos de peticiones.
En Hito 0B se diseñará una exploración controlada de pestañas, filtros,
desplegables y carruseles, con lista permitida de acciones y presupuesto de
navegación por entidad. La exhaustividad se evaluará después, en 0C/0D.
