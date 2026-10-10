# FootballDataHub

Base mínima para usar Brave con su perfil persistente mediante Playwright/CDP y comprobar el acceso normal a BDFutbol.

## Preparar el entorno

Se requiere Python 3.12 o posterior, Brave y `xvfb-run`/Xvfb. Instala el proyecto y las herramientas de desarrollo:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
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
