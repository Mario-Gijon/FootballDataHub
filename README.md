# FootballDataHub

Base mínima para usar Brave con su perfil persistente mediante Playwright/CDP y comprobar el acceso normal a BDFutbol.

## Preparar el entorno

Se requiere Python 3.12 o posterior, Brave y `xvfb-run`/Xvfb. Instala el proyecto, el extra de navegador y las herramientas de desarrollo:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[scraping,dev]'
```

Playwright se conecta al navegador instalado por CDP; no descarga ni administra otro navegador.

## Ejecutar el smoke test

```bash
.venv/bin/python scripts/smoke_bdfutbol_session.py
```

El smoke conserva estos parámetros: `--profile`, `--browser`, `--output-root` y `--no-stats`. Por defecto usa Brave, el perfil `~/.football-data-hub-v2-probe` y guarda un informe local bajo `data/analysis/bdfutbol/session_smoke/`.

## Brave, CDP y sesión

`BrowserRuntime` inicia Brave con el perfil elegido y un puerto CDP ligado a loopback. `BrowserSessionManager` conecta Playwright a ese endpoint, crea páginas propias y cierra páginas, conexión CDP, Playwright y proceso al salir del bloque `with`. El runtime reserva un lock de FootballDataHub junto al perfil para evitar dos instancias administradas simultáneas.

El perfil persistente no se copia ni se limpia. Cierra cualquier Brave que lo esté usando antes de iniciar el smoke. No borres sus archivos `Singleton*` ni modifiques los locks manualmente.

## Comprobar BDFutbol

`BDFutbolAccess` navega únicamente a URLs HTTPS de `bdfutbol.com`, inspecciona el título, el contenido y los marcadores que indique la llamada, y clasifica el resultado como válido, error, contenido inválido o desafío. Un HTTP 200 por sí solo no valida una página.

Ejecuta el smoke solo cuando el acceso normal esté disponible. Si aparece un desafío o una denegación, el programa lo informa y no intenta resolverlo. No automatices CAPTCHA, no eludas controles de acceso y respeta los términos y límites del sitio.

Las páginas y sesiones se cierran automáticamente con sus gestores de contexto; también puede llamarse a `close()` explícitamente.

## API REST de Grupo II

La API se instala por separado y no carga Playwright ni el proveedor de scraping:

```bash
.venv/bin/python -m pip install -e '.[api]'
```

Configura los datasets con `.env.example` y sigue [`docs/group2_api.md`](docs/group2_api.md) para arrancar Uvicorn. Las herramientas de navegador están en el extra `scraping`, así que un servidor de API puede instalar únicamente `.[api]`.

## Clasificación del Grupo II

El diccionario observado de columnas, filtros y progreso está en [`docs/bdfutbol_group2_classification_semantics.md`](docs/bdfutbol_group2_classification_semantics.md). El extractor realiza una navegación por ejecución, valida el título `2026-27`, el Grupo II y los 20 IDs de `table#classific`, y no intenta resolver desafíos.

Para capturar la clasificación general de la jornada seleccionada actualmente en la página:

```bash
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_group2_classification.py \
  --browser brave \
  --profile "$HOME/.football-data-hub-v2-probe" \
  --classification-type general
```

La última jornada se lee del selector durante la navegación; también se puede fijar con `--matchday 6`. Otros estados explícitos:

```bash
# Clasificación local, jornada 6, excluyendo aplazados
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_group2_classification.py \
  --classification-type local --matchday 6 --exclude-postponed

# Rango de fechas inclusivo
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_group2_classification.py \
  --matchday 6 --range-type dates --date-start 2026-08-29 --date-end 2026-09-27

# Rango de jornadas inclusivo, sin superar la jornada seleccionada
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_group2_classification.py \
  --matchday 6 --range-type rounds --round-start 2 --round-end 4
```

Cada ejecución crea un directorio nuevo bajo `data/exports/bdfutbol/group2_classification/` (configurable con `--output-root` o `FDH_BDFUTBOL_CLASSIFICATION_OUTPUT`). Contiene `raw/source.html`, los JSON normalizados de clasificación y progreso, `metadata/capture.json`, `validation/results.json` y el log del navegador. El perfil se puede configurar con `--profile` o `FDH_BDFUTBOL_PROFILE`.

Pruebas offline: `PYTHONPATH=src .venv/bin/pytest -q`. La ejecución real de integración es el comando del scraper anterior y queda fuera de los tests automáticos; no recorre jornadas o combinaciones en lote.

En otro servidor hay que comprobar por separado que el navegador externo, Xvfb/CDP, el perfil autorizado y el acceso normal al sitio estén disponibles. El CLI registra errores de inicialización/acceso y no presupone que Brave/CDP ni el perfil local existan en la UJA.
