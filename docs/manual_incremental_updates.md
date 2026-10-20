# Actualizaciones manuales incrementales

## Diseño general

El backend es el único propietario de las adquisiciones y comparaciones. React inicia un trabajo administrativo y consulta su estado; no accede a BDFutbol. Los trabajos se ejecutan en una cola única, conservan sus recibos JSON y capturas en `$FDH_LOCAL_DATA_ROOT/operations/manual-updates/`, y adquieren un lock de navegador compartido y otro por ámbito. Los locks se liberan al terminar. Un trabajo que la API encuentre `queued` o `running` al arrancar se marca como `interrupted`; nunca se reanuda ni se repiten navegaciones automáticamente.

El pipeline utiliza los scripts y validadores que ya existen. Cada captura se guarda en una ruta nueva. Los índices activos y los paquetes publicados son de solo lectura durante una comprobación. Un cambio produce un candidato `review_required`, con procedencia, diff y huellas SHA-256 de los archivos capturados. La página muestra el resumen y ofrece una acción administrativa explícita **Aprobar y activar**; la aprobación vuelve a comprobar la huella y se registra como evento inmutable. Los detalles de partido nunca se aprueban ni se publican desde este sistema.

## MVP disponible

### Primera Federación

El botón de competición comprueba ambos grupos secuencialmente. Para cada uno usa `scrape_bdfutbol_classification.py`, interpreta los partidos con `extract_bdfutbol_matches.py` y exige que la validación de clasificación y los invariantes del catálogo sean válidos. Compara filas de clasificación y campos deportivos de equipos/partidos por sus IDs frente a los JSON actualmente configurados. Si no encuentra cambios deportivos, registra `completed` y no construye otra generación. Si detecta cambios, construye una generación MATCH inmutable, ejecuta el comparador MATCH existente y deja el informe con su SHA para revisión. No cambia el puntero activo.

El diff MATCH protege los IDs y los detalles ya publicados, incluido el partido bloqueado 272582. Una nueva fecha/resultado aparece como cambio pendiente de revisión. La activación explícita utiliza el comando `activate` existente y después mueve el puntero de fuentes de grupo; el backend recarga ambos grupos, la generación de resultados y los detalles ya publicados en memoria. Se escribe un journal antes de cambiar punteros. Si el proceso cae durante ese paso, el arranque deja temporalmente indisponibles Clasificación/Resultados en vez de servir grupos mezclados. El administrador puede volver a confirmar el mismo candidato/huella para que el comando existente reconcilie los punteros; no se repite ninguna navegación. Esta versión no vuelve a adquirir fichas de partido publicadas.

### Ficha de equipo

El botón del equipo usa `acquire_bdfutbol_team_batch.py` con el ID y grupo resueltos desde los catálogos cargados por la API. Adquiere secuencialmente las seis vistas del perfil y los cuatro estados de Seguimiento con una pausa mínima de cinco segundos. `--force-refresh` impide reutilizar capturas completas, parciales o checkpoints. El batch valida la nueva captura; el coordinador compara los JSON normalizados con la captura seleccionada y sus hashes publicados. La revisión muestra los archivos que cambiaron. **Aprobar y publicar perfil** verifica de nuevo captura e índice y usa `publish_bdfutbol_team_profiles.py` con un manifiesto que conserva los otros 39 perfiles; luego recarga Plantilla, Seguimiento y Traspasos en memoria.

Si el catálogo conocido de partidos ya no es compatible con lo que publica el perfil de equipo, el validador existente detiene ese trabajo. El operador debe actualizar primero la competición, revisar/activar su generación y después iniciar explícitamente el trabajo del equipo. La vista de partidos incluida en una captura de equipo no activa por sí sola el catálogo de competición: los resultados/calendario se revisan con el ámbito de competición. No se infieren IDs ni se reintenta una captura fallida.

## Dependencias entre datos

| Cambio detectado | Entidades que puede afectar | Tratamiento de este MVP |
| --- | --- | --- |
| Marcador, fecha o equipo del partido | Resultados, calendario, clasificación, seguimiento/estadísticas derivadas de partido | Comparar y preparar nueva generación; revisión y activación explícitas |
| Puntos o posición publicados | Clasificación y progreso | Conservar el snapshot nuevo y mostrar diferencias; no activar sin revisión |
| Captura de un equipo | Identidad/temporada, plantilla, estadísticas, Seguimiento, Traspasos y partidos del equipo | Validar, mostrar diff y publicar el perfil solo con aprobación; los resultados globales se revisan con el ámbito competición |
| Nuevo detalle de partido | Alineaciones, entrenadores, goles, tarjetas, sustituciones | Usar el flujo de MATCH existente; no adquirir ni publicar detalles desde esta actualización |
| Destacados, estadísticas globales, árbitros | Capturas de sus pestañas dedicadas | No se presumen actualizados por refrescar clasificación; requieren sus adaptadores de adquisición/validación existentes |
| Jugador | Trayectoria, estadísticas, partidos y rivales | Fuera del MVP; futuras acciones deben usar IDs y las cuatro vistas ya existentes |

## Detección incremental y límites de la fuente

No tenemos un mecanismo condicional de BDFutbol (ETag/Last-Modified o feed de cambios) verificado para estos accesos. Por tanto, comprobar si hubo cambios requiere navegar una vez por cada página del ámbito elegido. El sistema compara datos normalizados por IDs y excluye del diff deportivo los metadatos de captura. No puede prometer cero navegación cuando no hubo cambios. Solo procesa la reconstrucción MATCH si el contenido normalizado cambió; las fichas de partido ya aprobadas no se vuelven a visitar.

La comprobación de equipo necesita recapturar sus vistas porque la fuente no ofrece un índice fiable de modificaciones. Se comparan los campos normalizados, no el timestamp de la nueva captura. Se conservan tanto el snapshot anterior como el nuevo.

## Seguridad y operación

Todas las rutas administrativas, incluidas capacidades, estado, trabajos y aprobaciones, requieren `X-FDH-Admin-Token`, comparado en tiempo constante con `FDH_UPDATE_ADMIN_TOKEN`. Sin credencial válida responden 401; la configuración solo se consulta después de autenticar. La interfaz pide acceso al administrador y no consulta el estado al cargar para visitantes. El token queda solo en memoria del componente, no se guarda en almacenamiento del navegador, ni se incorpora al bundle. En producción, el API y la interfaz administrativa deben servirse mediante HTTPS y el secreto debe inyectarse desde el gestor de secretos del servicio.

Configurar antes de iniciar FastAPI:

```sh
export FDH_LOCAL_DATA_ROOT="$HOME/FootballDataHub-data"
export FDH_UPDATE_ADMIN_TOKEN='un-secreto-largo-aleatorio'
export FDH_BDFUTBOL_PROFILE="$HOME/.football-data-hub-chromium-pure-cdp"
export FDH_TEAM_PROFILES_INDEX="$HOME/FootballDataHub-data/published/team_profiles_2026-27.json"
export FDH_PLAYER_TEAM_CAPTURES_ROOT="$HOME/FootballDataHub-data/team-captures"
```

Las capacidades se habilitan por separado. Competición requiere los catálogos, la generación MATCH y el almacén de detalles existentes fuera del checkout. Equipo requiere el índice publicado externo y el almacén de capturas externo. Si falta alguna dependencia, el control de ese ámbito no aparece y su endpoint no inicia trabajo.

La operación valida que existe Xvfb antes de navegar. Los scripts actuales usan la sesión Pure CDP aislada, el perfil persistente configurado y no reintentan ante errores, desafíos, denegaciones ni fallos estructurales. No se cambian IP, perfil ni navegador para superar una restricción.

Rutas administrativas (todas requieren el token):

- `GET /api/v1/admin/updates/capabilities`
- `GET /api/v1/admin/updates/status?scope=competition`
- `GET /api/v1/admin/updates/status?scope=team&team_id={team_id}`
- `POST /api/v1/admin/updates/competition`
- `POST /api/v1/admin/updates/teams/{team_id}`
- `GET /api/v1/admin/updates/jobs/{job_id}`
- `GET /api/v1/admin/updates/latest?scope=competition`
- `GET /api/v1/admin/updates/latest?scope=team&team_id={team_id}`

La UI muestra estado, hora, cambios resumidos y errores, y consulta cada trabajo sin bloquear el resto de la aplicación. En `review_required` muestra el diff inmediatamente y permite confirmar con un nombre de revisor; la huella se conserva internamente en la solicitud para que el backend la compare con el artefacto vigente y registre la aprobación. El operador no necesita copiarla. Para equipos, la captura versionada también queda bajo `team-captures/2026-27/{team_id}/{capture_id}`; las generaciones y diffs MATCH conservan sus hashes y manifiestos. La repetición de una activación ya completada es idempotente.

## Extensiones previstas

1. Añadir adaptadores por fuente que especifiquen consulta económica, comparación semántica, dependencias y tipo de revisión. No implementar un botón global hasta tener cobertura real de cada adaptador.
2. Ampliar las vistas administrativas para advertencias y conflictos sin exponer diagnósticos a visitantes.
3. Incorporar adaptadores dedicados para Destacados, Estadísticas, Árbitros, Jugadores y detalles de partidos. La actualización global solo estará disponible cuando cada fuente tenga adquisición/diff reales y el coste/revisión estén claros.
4. En el servidor UJA, guardar `FDH_LOCAL_DATA_ROOT` y el índice de equipos fuera del checkout, proteger el secreto, instalar navegador/Pure CDP/Xvfb y ejecutar una sola instancia del coordinador. Para varias réplicas, mover locks y estado a almacenamiento compartido con exclusión distribuida fiable.

No se incluye programación periódica ni una acción “buscar todo”: las fuentes no comparten una API de cambios y una búsqueda universal sin definir su costo sería fácil de disparar por error.
