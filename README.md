# FootballDataHub

Base modular para adquisición deportiva de BDFutbol, dominio, API y dashboard.
El navegador predeterminado de adquisición es SeleniumBase Pure CDP con Chromium;
Brave + Playwright/CDP permanece como backend explícito de regresión.

## Preparar el entorno de adquisición

Se requiere Python 3.12 o posterior, Chromium y Xvfb en Linux sin escritorio.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[scraping,dev]'
```

El extra `scraping` fija SeleniumBase 4.55.2. Para utilizar el backend histórico:

```bash
.venv/bin/python -m pip install -e '.[scraping-playwright]'
```

La API se instala por separado y no carga SeleniumBase ni Playwright:

```bash
.venv/bin/python -m pip install -e '.[api]'
```

## Smoke tests

Prueba offline de HTML, JavaScript, HTTP 200/404 y perfil persistente:

```bash
PYTHONPATH=src xvfb-run -a -s '-screen 0 1920x1080x24' \
  .venv/bin/python scripts/smoke_browser_local.py
```

Diagnóstico de acceso BDFutbol en una única navegación controlada:

```bash
PYTHONPATH=src xvfb-run -a -s '-screen 0 1920x1080x24' \
  .venv/bin/python scripts/smoke_bdfutbol_session.py \
  --backend seleniumbase-pure-cdp --browser chromium --group2-classification
```

Si aparece un desafío o una denegación, la prueba se detiene sin resolverlo. Un
HTTP 200 por sí solo no valida el contenido deportivo.

## Clasificación del Grupo II

El diccionario observado de columnas, filtros y progreso está en
[`docs/bdfutbol_group2_classification_semantics.md`](docs/bdfutbol_group2_classification_semantics.md).
El extractor valida el título `2026-27`, el Grupo II y los 20 IDs de
`table#classific`; ejecuta una navegación por captura.

```bash
PYTHONPATH=src xvfb-run -a -s '-screen 0 1920x1080x24' \
  .venv/bin/python scripts/scrape_bdfutbol_group2_classification.py \
  --backend seleniumbase-pure-cdp \
  --browser chromium \
  --profile "$HOME/.football-data-hub-chromium-pure-cdp" \
  --classification-type general
```

El perfil predeterminado de Chromium es distinto del antiguo perfil Brave
`~/.football-data-hub-v2-probe`; no reutilices la misma ruta entre backends.
Las capturas se escriben en directorios versionados y nunca sustituyen las
anteriores. Configuración adicional: `FDH_BDFUTBOL_PROFILE`,
`FDH_BDFUTBOL_BROWSER_BACKEND`, `FDH_BDFUTBOL_BROWSER`,
`FDH_BDFUTBOL_BROWSER_EXECUTABLE`,
`FDH_BDFUTBOL_BROWSER_STARTUP_TIMEOUT_SECONDS`,
`FDH_BDFUTBOL_NAVIGATION_TIMEOUT_MS` y
`FDH_BDFUTBOL_CLASSIFICATION_OUTPUT`.

Para la regresión técnica con Brave/Playwright:

```bash
PYTHONPATH=src .venv/bin/python scripts/scrape_bdfutbol_group2_classification.py \
  --backend playwright-cdp --browser brave \
  --profile "$HOME/.football-data-hub-v2-probe"
```

En este backend el runtime existente inicia Xvfb, administra CDP y reserva un
lock del perfil. En Pure CDP, Xvfb se administra fuera del proceso, por ejemplo
con `xvfb-run`; el perfil persistente no se borra al cerrar.

Los filtros deportivos y los formatos JSON se mantienen independientes del
backend. Los detalles de instalación, versiones, perfiles y límites están en
[`docs/browser_acquisition.md`](docs/browser_acquisition.md).

## API REST y dashboard

La API y el dashboard siguen siendo consumidores independientes de los datos
preparados. Consulta [`docs/group2_api.md`](docs/group2_api.md) para arrancar
FastAPI y [`apps/dashboard/README.md`](apps/dashboard/README.md) para Vite.
