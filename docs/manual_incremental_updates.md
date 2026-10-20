# Actualización local de Primera Federación

## Flujo disponible

La cabecera de Primera Federación ofrece una única acción: **Actualizar Primera Federación**. Esa operación siempre consulta Grupo I y Grupo II en secuencia. No hay controles de actualización por equipo ni un paso de revisión/aprobación humana para este flujo.

El backend es el único propietario de las adquisiciones y comparaciones. React inicia un trabajo y consulta su estado sin bloquear la interfaz ni mostrar rutas o huellas internas. Los trabajos, capturas nuevas e informes se guardan bajo `$FDH_LOCAL_DATA_ROOT/operations/manual-updates/`. Un lock compartido del navegador y un lock de competición impiden ejecuciones duplicadas. Un trabajo interrumpido no reanuda ni repite navegaciones automáticamente.

Cada grupo usa los scripts existentes `scrape_bdfutbol_classification.py` y `extract_bdfutbol_matches.py`. Se exige la validación guardada y los invariantes semánticos. La comparación relaciona equipos y partidos por sus IDs, compara clasificación/progreso y los campos de calendario y marcador. Después consulta, en secuencia, los adaptadores existentes de Destacados y Estadísticas para ambos grupos y el de Árbitros. No hay reintentos; una denegación o fallo de una fuente deja intacta su captura activa y detiene las adquisiciones opcionales siguientes. Una fuente opcional defectuosa no revierte resultados válidos del núcleo ni impide que las demás se sirvan.

Si no hay cambios normalizados en ninguna fuente, el resultado es **Sin cambios** y no se construye otra generación. Si solo cambia una sección opcional, se activa únicamente su captura validada mediante el puntero de secciones; no se reconstruye la generación MATCH. Si cambian Resultados, Clasificación o Calendario, se conserva el flujo MATCH existente y se incorporan al mismo puntero solo las secciones opcionales que también hayan cambiado. Las capturas son inmutables y los punteros anteriores se archivan.

Cuando hay diferencias, el backend construye una generación MATCH inmutable y usa el comparador y activador existentes. La aplica automáticamente solo si no hay conflictos de identidad/calendario ni partidos que pasen de disputados a pendientes. Antes de mover los punteros vuelve a verificar hashes de las capturas, JSON normalizados, generación y diff; el activador también vuelve a comprobar cada detalle aprobado frente a la generación nueva. Una contradicción detiene la activación.

La activación registra eventos locales inmutables con el actor de servicio `football-data-hub-local-update-service`; no es una aprobación humana. El campo histórico de atribución que usa el formato de eventos MATCH sigue siendo compatible con generaciones anteriores. Se escribe un journal antes de mover punteros. Si la activación se interrumpe, el backend detiene nuevas operaciones hasta resolver ese journal.

## Una fuente para competición y equipos

La generación MATCH activa y los dos catálogos de grupo se construyen desde las mismas capturas y normalizaciones. Después de activar, FastAPI carga Clasificación/Resultados y la generación de partidos y compara, por ID, los 760 registros y sus equipos, jornada, fechas, estado, marcador y referencias disponibles. Si detecta una diferencia, no cambia los bundles en memoria y comunica el error.

Las páginas de Resultados, las fichas de partido y las vistas recientes/de calendario de los equipos consumen esos mismos datos activos. Resultados, calendario, clasificación y relaciones partido-equipo comparten IDs de partido/equipo desde MATCH-00. Estadísticas recalcula agregados, récords y rachas desde el catálogo activo; sus penaltis y serie gráfica conservan los valores de la captura específica más reciente y la API muestra su fecha. Destacados usa su catálogo verificado del grupo correspondiente. Árbitros valida sus capturas y vuelve a cruzar por IDs exactos las designaciones contra los catálogos activos de ambos grupos; las estadísticas agregadas del árbitro siguen teniendo la fecha de la captura de Árbitros.

La recarga de FastAPI valida cada sección opcional de forma independiente. Si una falla, mantiene el bundle previo de esa sección y registra el error; los catálogos del núcleo y las otras secciones pueden seguir funcionando. Una captura opcional solo sustituye a la anterior si su identidad, validación, referencias y hashes pasan los loaders reales de la API y su contenido normalizado difiere.

Una actualización de calendario/resultados no vuelve a adquirir ni publica detalles de partido. Un nuevo encuentro disputado aparece en Resultados y sus vistas de equipo con su ficha detallada pendiente. No se inventan alineaciones, goles, tarjetas ni estadísticas individuales. Las 139 publicaciones actuales permanecen bajo el índice y paquetes existentes; el partido 272582 continúa excluido/bloqueado. Si una publicación aprobada discrepa del nuevo resultado, la activación completa se detiene en la validación del paquete.

## Dependencias y alcance

| Cambio detectado | Vistas afectadas | Comportamiento |
| --- | --- | --- |
| Resultado nuevo o corregido | Resultados, ficha de partido, forma/local-visita y clasificación publicada por BDFutbol | Activar únicamente después de validaciones; los detalles no adquiridos quedan pendientes |
| Fecha, jornada, estadio o árbitro | Calendario, página del partido y partidos de ambos equipos | Una fila por `match_id`, compartida entre local y visitante |
| Equipo o identidad de encuentro cambiados | Catálogo, calendario y publicaciones asociadas | Conflicto bloqueante; no se aplica automáticamente |
| Partido disputado que vuelve a pendiente | Resultados y detalles ya publicados | Conflicto bloqueante |
| Detalle deportivo nuevo | Alineación, entrenador, eventos y estadísticas individuales | Permanece pendiente del flujo MATCH de adquisición, validación y publicación |
| Destacados y estadísticas de competición | Capturas independientes por grupo | Se consultan con sus CLIs existentes; solo se activa el contenido normalizado que cambió y superó validación. Las estadísticas agregadas, récords y rachas se recalculan sobre Resultados activos. |
| Árbitros | Captura compartida de las tres vistas | Se consulta con el CLI existente; sus referencias a partidos se vuelven a unir por ID a ambos catálogos activos. Si no hay nueva captura válida, se conserva la anterior. |
| Jugadores individuales | Inventario y compactos de perfiles independientes | El botón no recorre las páginas de los 1.709 perfiles ni vuelve a adquirir sus cuatro vistas. Destacados/Estadísticas actualizan solo las tablas de competición que esas fuentes exponen; carreras, partidos y rivales de la ficha individual siguen dependiendo de su generación publicada. |
| Plantillas, traspasos y seguimiento de equipos | Capturas de perfil de equipo independientes | El calendario y los últimos partidos se sincronizan desde MATCH-00; el botón no vuelve a adquirir las vistas de plantilla, traspasos ni los estados de seguimiento del club. |

No existe un mecanismo condicional de BDFutbol (ETag/Last-Modified o feed de cambios) verificado para estas adquisiciones. Detectar cambios exige consultar las páginas de origen: dos páginas de competición, las vistas de Destacados y Estadísticas por grupo y las tres vistas de Árbitros, secuencialmente y con pausa entre navegaciones. El coste de adquisición de fuente no puede evitarse con la evidencia actual; sí se evita reconstruir generaciones y reaplicar datasets cuando sus hashes semánticos no cambian. El procesamiento MATCH completo solo se genera si cambian los catálogos de resultados. Los detalles publicados se conservan, y el flujo de informes solo considera partidos disputados sin informe publicado; nunca recaptura los 160 informes ya completos. El partido 272582 sigue sujeto a su recibo de recuperación validado y no se vuelve a adquirir.

El botón no actualiza perfiles individuales, Plantillas, Traspasos ni Seguimiento de jugadores/equipos: aunque algunos campos puedan aparecer también en estadísticas o en la ficha de un partido, no existe en este flujo un adaptador incremental validado para esas fuentes. No se declara actualizada una sección que no haya sido consultada por su fuente.

## Seguridad local y API

No hay tokens, contraseñas ni nombres de revisor para este flujo. Las rutas de actualización están limitadas a solicitudes loopback: peer, `Host`, `Origin` y `Sec-Fetch-Site` deben ser locales y se rechazan cabeceras reenviadas. FastAPI y Vite deben enlazarse a `127.0.0.1`. No desplegar estas rutas directamente en UJA; antes, protegerlas o dejarlas inaccesibles mediante controles del despliegue.

Rutas locales expuestas:

- `GET /api/v1/updates/status`
- `POST /api/v1/updates/competition`
- `GET /api/v1/updates/latest`
- `GET /api/v1/updates/jobs/{job_id}`

No se exponen rutas de actualización de equipos ni de aprobación humana. Las respuestas de estado omiten el candidato privado, las rutas del almacén, los hashes y el log completo; presentan progreso, resumen y errores. Los controles criptográficos y la procedencia permanecen en los recibos privados del backend.

Configurar antes de iniciar FastAPI:

```sh
export FDH_LOCAL_DATA_ROOT="$HOME/FootballDataHub-data"
export FDH_BDFUTBOL_PROFILE="$HOME/.football-data-hub-chromium-pure-cdp"
```

Competición requiere los catálogos, la generación MATCH, el almacén de detalles y los datasets de ambos grupos fuera del checkout. Si faltan, el backend no inicia la adquisición. La operación comprueba Xvfb antes de navegar y usa Pure CDP con el perfil local configurado. No cambia IP, navegador o perfil para superar una denegación, y no reintenta bloqueos ni fallos.

## Límites y siguientes fuentes

Este botón actualiza únicamente Resultados, calendario, clasificación y sus vistas basadas en los catálogos de partidos. No afirma haber actualizado los módulos con fuentes independientes. Una ampliación necesitará adaptar adquisición, validación, comparación y dependencias para cada fuente antes de sumarla al resumen.

En un servidor posterior se necesitará instalar y probar el navegador/Xvfb autorizado, mantener `FDH_LOCAL_DATA_ROOT` y locks en almacenamiento persistente, operar una única instancia (o locks distribuidos fiables) y restringir las rutas mediante autenticación/red privada a nivel de despliegue.
