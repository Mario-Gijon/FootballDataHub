# Adquisición y actualización de datos BDFutbol — Grupo II

## Diagnóstico de ACCESS-01, CLAS-01 y RES-01

La captura de referencia `20261010T102656.252222Z-72f200ad` se adquirió el 10/10/2026 a las 10:26:56 UTC. Su `metadata/capture.json` registra URL de clasificación sin query, navegador `brave`, ejecutable `/usr/bin/brave`, perfil `/home/mario/.football-data-hub-v2-probe`, Xvfb activo, acceso `VALID` y HTTP 200. El documento pasó la validación de título, Grupo II y estructura; tiene una tabla válida de 20 equipos.

La única prueba de RES-01 solicitó `https://www.bdfutbol.com/es/t/t2026-271rf2.html?tab=results`. Se configuró con el mismo usuario Linux `mario` (UID 1000), `/usr/bin/brave`, perfil persistente, `BrowserRuntimeConfig`, `BrowserSessionManager`, CDP, Xvfb y `BDFutbolAccess`. La captura registra el mismo ejecutable y perfil. El intento fue aproximadamente dos horas después de la captura (el lock se modificó a las 14:26 CEST) y produjo una respuesta principal HTTP 403, URL final sin cambio, título `Just a moment...` y estado `CHALLENGE_REQUIRED`. No se siguió navegando.

El intento utilizó la misma **configuración del navegador y el mismo perfil persistente**, pero no la misma instancia/proceso del navegador ni la misma página/contexto: cada `BrowserSessionManager` inicia un Brave administrado nuevo, conecta Playwright por CDP y crea una página propia. El perfil persistente permite reutilizar el almacenamiento que Brave conserva; no demuestra que el contenido interno de sesión/cookies fuera idéntico ni se inspeccionó. La pestaña local de Codex que mostraba Vite (`127.0.0.1:5175`) no participó en la petición a BDFutbol.

La metadata de CLAS-01 no guarda la versión exacta de Brave. En el diagnóstico actual, `/usr/bin/brave` informa `Brave Browser 154.1.96.59` y su archivo tiene fecha de modificación 26/09/2026; por ello el path coincide y no hay señal de que el binario se cambiara, pero la versión exacta de la ejecución de las 10:26 no queda demostrada. ACCESS-01 y CLAS-01 registran el mismo perfil/configuración general; la evidencia disponible no demuestra que conservaran el mismo proceso vivo.

### El error del sandbox y el 403 son dos eventos distintos

Una ejecución inicial dentro del sandbox falló al crear el archivo de coordinación de perfil:

```text
OSError: [Errno 30] Read-only file system: '/home/mario/..football-data-hub-v2-probe.fdh.lock'
```

Ese error se produjo antes de iniciar Brave y antes de hacer una petición HTTP. El sandbox permite escribir en el repositorio, pero no en `/home/mario`; el perfil y el lock están fuera de las rutas escribibles. Al habilitar la ejecución local necesaria para la prueba, el mismo usuario pudo adquirir el lock, abrir Brave y recibir la respuesta HTTP 403. Por tanto, el error de permisos no es una respuesta de BDFutbol ni evidencia de Cloudflare.

El lock conserva el PID informativo del último proceso en el archivo, pero el fichero permanece en disco tras liberar `flock`; ese PID no prueba que el perfil siga bloqueado. En la inspección no había un proceso Brave visible. El directorio del perfil y el lock pertenecen a `mario` con permisos `0700` y `0600` respectivamente.

El 403 con `Just a moment...` sí es una denegación/desafío de la página observada. Es compatible con la protección de seguridad conocida del sitio, pero la evidencia no determina si el motivo fue la ruta `?tab=results`, una política temporal, la reputación de la sesión u otra regla. No se debe extrapolar el resultado de esa pestaña a la URL de clasificación, que sí había respondido 200 dos horas antes.

### Tiempos y comportamiento de navegación

`BrowserSessionManager` navega con `wait_until="domcontentloaded"` y timeout de 45 segundos. La adquisición CLAS usa además un asentamiento de 750 ms y `max_wait_seconds=0`. RES-01 utilizó la misma configuración temporal; por eso no esperó ni volvió a evaluar la página tras observar el desafío. El smoke de ficha no fija `max_wait_seconds` y usaba el valor predeterminado de 12 segundos; la página de Grupo II del smoke sí lo fijaba en 0.

Se detectó una posibilidad de continuación no deseada en `BDFutbolAccess`: si otra llamada recibía `CHALLENGE_REQUIRED` y solicitaba una espera positiva, el código volvía a observar el documento hasta que el desafío cambiara o expirara el límite. Aunque no pulsaba, recargaba ni resolvía el desafío, eso permitía continuar después de una respuesta marcada como desafío. Se cambió para detenerse inmediatamente ante `CHALLENGE_REQUIRED`; la espera limitada queda solo para contenido ordinario que todavía no cumple sus marcadores. RES-01 no estuvo afectado por esta diferencia porque usó `max_wait_seconds=0`.

## Procedimiento de actualización propuesto

La adquisición no debe modificar nunca el release activo. Las capturas, normalizaciones e informes se conservan en carpetas nuevas e inmutables por identificador. Un fallo de permisos, navegador, acceso, parsing o validación deja intacta la captura anterior.

### 1. Preparar y adquirir una captura nueva

En un host Linux autorizado, con el mismo usuario que posee el perfil, Brave y Xvfb instalados, se configura la ruta del perfil por entorno o argumento. No se debe lanzar dos procesos FootballDataHub simultáneos con el mismo perfil. El servidor futuro debe tener una configuración explícita de Brave/Xvfb/CDP; no se asume que existan en una instalación Linux cualquiera.

```bash
cd /ruta/al/FootballDataHub
export FDH_BDFUTBOL_PROFILE="$HOME/.football-data-hub-v2-probe"
export PYTHONPATH=src
.venv/bin/python scripts/scrape_bdfutbol_group2_classification.py \
  --browser brave \
  --profile "$FDH_BDFUTBOL_PROFILE" \
  --output-root data/exports/bdfutbol/group2_classification
```

El comando devuelve un `capture_id` nuevo. No reintentar si guarda `access_failure.json` con desafío/denegación; conservar el informe y terminar esa adquisición. `create_run_directory()` exige una carpeta inexistente y los exports abren archivos en modo exclusivo, así que una captura anterior no se sobrescribe.

### 2. Normalizar en un directorio derivado separado

Copiar el `capture_id` que imprimió el comando, asignarlo explícitamente y derivar los partidos desde el snapshot de esa misma captura:

```bash
CAPTURE_ROOT=data/exports/bdfutbol/group2_classification
CAPTURE_ID=PEGAR_CAPTURE_ID_DEVUELTO
RUN="$CAPTURE_ROOT/$CAPTURE_ID"
DERIVED="$CAPTURE_ROOT/derived-$CAPTURE_ID"

PYTHONPATH=src .venv/bin/python scripts/extract_bdfutbol_matches.py \
  --snapshot "$RUN/raw/source.html" \
  --capture "$RUN/metadata/capture.json" \
  --output "$DERIVED/normalized/matches.json"
```

La normalización conserva `source_capture_id`, timestamp, hash SHA-256 del HTML, versión del extractor y metadatos de jornadas. La clasificación y progreso están en `$RUN/normalized/`; la validación de partidos, en `$DERIVED/validation/matches.json`. Un código de salida distinto de cero deja el resultado en staging para diagnóstico, pero no debe publicarse.

### 3. Validar y comparar antes de publicar

Validar en conjunto, usando el mismo `capture_id`:

- `metadata/capture.json`: estado de acceso válido, URL, Grupo II, temporada y hora UTC.
- `validation/results.json`: 20 filas de clasificación y validación estructural.
- `validation/matches.json`: IDs y referencias únicos, 20 equipos, calendario esperado, estados coherentes y balance deportivo.
- `normalized/classification.json`, `progress.json` y `matches.json`: esquema y procedencia compatibles.
- Recalcular la clasificación local y compararla con la tabla fuente del mismo snapshot para el contexto capturado. Registrar diferencias por `team_id` y campo; no alterar puntos oficiales, sanciones ni valores `null` para forzar igualdad.
- Comparar el nuevo `matches.json` con el anterior por `match_id`. Informar cambios de estado, fecha, marcador, participantes o calendario. Los cambios legítimos de marcadores/resultados son esperables; IDs duplicados, referencias ausentes, equipos desconocidos, contenido incompleto o cambios estructurales sin explicar bloquean la promoción. No reconciliar IDs ambiguos únicamente por nombre.
- Guardar un informe de diferencias y la validación junto a la nueva captura. El informe debe identificar captura anterior/nueva, número de partidos añadidos/eliminados/modificados, campos afectados y advertencias.

La referencia JavaScript guardada en CLAS-01B corresponde al corte del 10/10/2026. No sirve por sí sola como referencia actual para datos de una captura futura. La comparación oficial debe usar una tabla del mismo snapshot nuevo; las nueve combinaciones históricas de CLAS-01B no son una validación automática de futuras fechas.

El motor local se puede ejecutar en staging sin navegador ni red:

```bash
PYTHONPATH=src .venv/bin/python scripts/calculate_group2_standings.py \
  --matches "$DERIVED/normalized/matches.json" \
  --matchday 6 \
  --output "$DERIVED/validation/calculated-general.json"
```

El número de jornada del ejemplo se debe sustituir por el contexto de `classification.json`. Hoy no existe una herramienta que genere automáticamente un diff entre dos `matches.json`, ni una que cree la referencia multi-filtro desde una captura nueva. `scripts/compare_group2_classification.py` consume referencias previamente guardadas y la comparación de la tabla publicada; su referencia de nueve escenarios es la del corte CLAS-01B. Antes de programar actualizaciones desatendidas habrá que añadir un generador de informe de cambios por ID y una comparación del corte actual, o ejecutar y archivar esos pasos de forma manual.

### 4. Promover solo un conjunto válido

La API actual carga cuatro archivos indicados explícitamente por variables `FDH_GROUP2_*`, comprueba que todos compartan captura y los conserva en memoria. No escoge el directorio más reciente automáticamente. Por ahora, la promoción debe ser una operación controlada: preparar las cuatro rutas de la nueva captura derivada, validar el conjunto con un proceso de API de staging y consultar `/ready` y `/api/v1/group2/bootstrap`; solo después cambiar la configuración activa y reiniciar/cambiar el proceso de servicio. Si falla staging o el proceso nuevo no está listo, se mantienen o restauran las rutas anteriores. No editar ni reutilizar las carpetas anteriores.

La configuración de staging debe señalar explícitamente las cuatro salidas de la misma ejecución, por ejemplo:

```dotenv
FDH_DATA_ROOT=data/exports/bdfutbol/group2_classification
FDH_GROUP2_MATCHES=derived-CAPTURE_ID/normalized/matches.json
FDH_GROUP2_CLASSIFICATION=CAPTURE_ID/normalized/classification.json
FDH_GROUP2_PROGRESS=CAPTURE_ID/normalized/progress.json
FDH_GROUP2_CAPTURE_METADATA=CAPTURE_ID/metadata/capture.json
```

La variable de coincidencias apunta al directorio derivado de esa captura; las otras tres apuntan a su carpeta de captura. La comprobación de compatibilidad de la API rechaza una mezcla de IDs. En el servidor Linux, un proceso de staging puede arrancarse con esa configuración y un puerto local distinto antes de cambiar el servicio activo.

Para el servidor UJA se recomienda añadir un manifiesto de release pequeño que contenga `capture_id`, `captured_at_utc`, rutas relativas de los cuatro JSON, versión de extractores, hash de snapshot, `previous_capture_id` e informe de validación. El publicador futuro escribiría primero un manifiesto temporal en el mismo filesystem y lo sustituiría atómicamente (`os.replace`) solo tras validar todo. La API deberá leer ese release como una única unidad. Esta promoción atómica todavía no está implementada; actualmente requiere seleccionar y actualizar juntas las cuatro rutas.

## Fecha mostrada en el dashboard

La API ya devuelve `metadata.captured_at`, `capture_id` y `dataset_version` desde la metadata de captura. El dashboard ya presenta `Actualizado <fecha>` a partir de `captured_at`; por tanto, al cambiar a un conjunto nuevo esa fecha mostrará su captura real, no la hora del último arranque del servidor. No se necesita inferir la fecha desde el sistema operativo.

## Qué puede continuar con el snapshot actual y qué necesita una captura nueva

| Trabajo | Con el snapshot del 10/10/2026 | Requiere página actualizada |
|---|---|---|
| Implementar y probar parsing semántico de `SP` y `#resultats` | Sí: contiene 380 partidos/fixtures, 20 equipos, 59 marcadores y 321 partidos sin resultado en ese corte. | No, salvo para confirmar cambios de estructura en la fuente. |
| Pruebas offline de estados, IDs, rangos y motor local | Sí; es apropiado como fixture reproducible. | No para tests unitarios. |
| Conocer resultados disputados después de las 10:26 UTC del 10/10/2026 | No. | Sí. |
| Confirmar si los partidos pendientes se jugaron, cambiaron de fecha o estado | No. El snapshot conserva solo lo observado entonces. | Sí. |
| Validar parser ante cambios actuales de HTML/JavaScript | No. | Sí. |
| Ver selector, orientación, colores, navegación y comportamiento de la matriz de Resultados | No; no está en el HTML guardado. | Sí, con acceso válido a la ruta de resultados. |
| Confirmar que el endpoint/pestaña de Resultados permite adquisición futura | No; la única apertura observada respondió 403. | Sí, en una ejecución autorizada que resulte válida. |
| Mostrar última captura en el dashboard | Sí, el campo existe y ya se muestra. | No para el componente; sí para que la fecha avance hace falta publicar una captura nueva. |

## Estado

- **Explorado:** comparación de metadata CLAS-01, código de sesión, permisos del perfil, ruta de la pestaña Resultados y diagnóstico RES-01.
- **Verificado:** CLAS-01 fue HTTP 200 con 20 equipos; el sandbox falló antes de HTTP al crear el lock; RES-01 alcanzó el sitio y recibió HTTP 403 / `Just a moment...`; el perfil es del usuario correcto; los exports son versionados y exclusivos; API y dashboard conservan/muestran `captured_at`.
- **Corregido:** `BDFutbolAccess` detiene inmediatamente el flujo ante `CHALLENGE_REQUIRED`, incluso cuando el llamador permite espera.
- **Pendiente:** una nueva captura válida en vivo, adquisición desatendida en servidor UJA, el comportamiento actual de la pestaña Resultados y la promoción atómica por manifiesto.

No se hizo una nueva petición tras el 403. No se afirma que las actualizaciones automáticas estén resueltas.
