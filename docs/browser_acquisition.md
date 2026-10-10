# Navegación de adquisición

## Interfaz común

Los proveedores reciben `BrowserDocument`, una interfaz pequeña para obtener
URL final, título, HTML, texto y opciones DOM, seleccionar controles, rellenar
campos, evaluar expresiones JavaScript concretas y cerrar la visita. No reciben
objetos SeleniumBase ni Playwright. `PageVisit` conserva la URL solicitada, el
estado HTTP principal cuando se puede observar y el documento adaptado.

`BDFutbolAccess` aplica validación de URL, título, marcadores, selectores,
documento y desafíos. Los parsers continúan consumiendo HTML serializado. El
dominio y el almacenamiento no importan bibliotecas de navegador.

## Backends

| Backend | Uso | Dependencias | Pantalla |
|---|---|---|---|
| `seleniumbase-pure-cdp` | Predeterminado para adquisición | `.[scraping]`, SeleniumBase 4.55.2 | Chromium no headless; Xvfb se proporciona externamente |
| `playwright-cdp` | Regresión temporal con la infraestructura anterior | `.[scraping-playwright]`, Brave/Chromium y Playwright | Runtime `BrowserRuntime` existente; puede iniciar `xvfb-run` |

Pure CDP inicia Chromium con un perfil persistente propio. No reutilices el
perfil Brave `~/.football-data-hub-v2-probe`; el perfil nuevo predeterminado es
`~/.football-data-hub-chromium-pure-cdp`. El gestor reserva un lock por perfil
para impedir dos sesiones FootballDataHub simultáneas. Al cerrar, llama a
`quit()`, espera el proceso Chromium iniciado por SeleniumBase y solo señaliza
su PID si sigue vivo y `/proc` confirma que usa exactamente ese perfil. No
borra el perfil persistente. Los datos de sesión quedan en ese perfil para
futuras ejecuciones autorizadas.

Pure CDP reutiliza una pestaña administrada por sesión y procesa las visitas en
serie. `PageVisit.close()` invalida el documento para el proveedor; al salir del
contexto se cierra el navegador completo. Los extractores actuales usan una
sola visita por sesión.

Pure CDP requiere `DISPLAY`. En un servidor Linux sin escritorio, envolver el
proceso Python con Xvfb externo:

```bash
xvfb-run -a -s '-screen 0 1920x1080x24' \
  .venv/bin/python scripts/scrape_bdfutbol_group2_classification.py \
  --backend seleniumbase-pure-cdp --browser chromium
```

La configuración es accesible tanto por `BrowserRuntimeConfig` como por el
CLI. Se pueden elegir perfil, backend, ejecutable y tiempos de arranque y
navegación. Si Pure CDP no está instalado, no cambia automáticamente a
Playwright; informa que falta el extra de scraping.

## Validación y procedencia

El estado HTTP puede ser desconocido. En Pure CDP se lee
`PerformanceNavigationTiming.responseStatus` cuando Chromium lo expone; en el
backend Playwright se observa la respuesta de navegación del documento
principal. `BDFutbolAccess` requiere contenido semánticamente válido además de
HTTP 200 y clasifica desafíos/denegaciones antes de guardar el HTML como una
captura válida. No se resuelven desafíos ni se hacen cambios automáticos de
backend.

Cada captura exporta backend, ejecutable, versión de Chromium, versión de
SeleniumBase o Playwright, URL, fecha, filtros y resultado de validación. El
export existente mantiene una carpeta nueva por `capture_id`.

## Pruebas

Prueba local sin contacto con BDFutbol, con respuestas 200 y 404, DOM,
JavaScript y reapertura del mismo perfil:

```bash
PYTHONPATH=src xvfb-run -a -s '-screen 0 1920x1080x24' \
  .venv/bin/python scripts/smoke_browser_local.py
```

Diagnóstico real de BDFutbol (una navegación y una captura explícita):

```bash
PYTHONPATH=src xvfb-run -a -s '-screen 0 1920x1080x24' \
  .venv/bin/python scripts/smoke_bdfutbol_session.py \
  --backend seleniumbase-pure-cdp --browser chromium --group2-classification
```

El smoke real no recorre jornadas ni resuelve controles de seguridad. Si la
respuesta es desafío o denegación, no se insiste.

## Resultado validado en CORE-01

Con SeleniumBase 4.55.2, Chromium 152.0.7977.82 y Xvfb externo, el smoke local
confirmó lectura de HTML y JavaScript, estado HTTP 200 y 404, `localStorage`
tras cerrar y reabrir el perfil, y conservación del directorio de perfil.
Una adquisición real única de la clasificación del Grupo II obtuvo HTTP 200,
20 equipos y 120 registros de progreso. Desde el mismo snapshot se normalizaron
offline 380 partidos, de los cuales 59 tenían resultado; la clasificación y el
dataset de partidos pasaron su validación. La captura y el export de partidos
de verificación se guardaron solo bajo `/tmp` y no sustituyeron los datasets
del proyecto. Los 59 encuentros disputados tuvieron estadio y árbitro con
nombre y URL; los 321 encuentros sin resultado conservaron esos campos ausentes.
El parser conservó las cuatro métricas nulas de progreso de Murcia y FC
Cartagena en J6 que faltaban en la fuente.

## Límites operativos

- La instalación y el acceso al servidor UJA todavía requieren una prueba en
  una imagen Linux equivalente al servidor, con Chromium y Xvfb.
- Pure CDP exige un proceso invocado bajo `xvfb-run` (u otro `DISPLAY`). No
  inicia ni administra Xvfb internamente.
- El timeout de navegación se aplica a `Tab.get`; el timeout de arranque se
  comprueba al completar la inicialización de SeleniumBase. SeleniumBase
  mantiene parte de su espera interna fija; una prueba de carga en el servidor
  debe confirmar tiempos reales.
- El smoke HTTP local no anticipa la política futura de BDFutbol. Una
  denegación detiene esa adquisición.
- Brave/Playwright sigue disponible para regresión técnica, no como cambio
  automático de navegador ante un desafío.
