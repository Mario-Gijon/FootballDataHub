# Publicación automática estricta de informes en Actualizar Primera Federación

La actualización global de Primera Federación puede adquirir y publicar informes de partido desde el mismo trabajo. La autorización de navegación procede únicamente de la acción local del botón; no equivale a una revisión humana del contenido.

## Selección y adquisición

Después de activar una generación de resultados verificada, el trabajo vuelve a leer el inventario MATCH y selecciona solo partidos con estado `played`, URL explícita y sin publicación, captura, bloqueo o diagnóstico de parada anterior. El ID de origen `272582` está excluido explícitamente.

Para esa selección se crea una campaña v2 vinculada al ID del trabajo, la generación y el hash del conjunto ordenado de candidatos. Cada candidato recibe un evento `AUTO_POLICY_AUTHORIZED` antes de navegar. Se utiliza el adaptador real ya existente de SeleniumBase Pure CDP, con un perfil dedicado, una navegación máxima por partido y cero reintentos automáticos. Un bloqueo, error o desafío detiene la secuencia; las capturas válidas ya obtenidas se conservan para procesarlas offline.

## Decisión de publicación

El HTML guardado pasa por el parser semántico actual. Solo se publica automáticamente si:

- la página, ID, equipos, grupo, competición, fecha, jornada y marcador coinciden con el catálogo verificado;
- la semántica es válida, no hay errores y están presentes y superadas todas las comprobaciones obligatorias de `automatic_publication_policy.py`;
- no hay advertencias de incertidumbre deportiva. Las únicas advertencias actualmente no bloqueantes son `ephemerides_not_observed` y el estado informativo de descubrimiento no promovido;
- el borrador, el HTML, la evidencia de validación y sus hashes siguen coincidiendo al reconstruir y publicar.

Una duda de alineación, evento, identidad, marcador o procedencia deja el informe en `PENDING_POLICY_REVIEW`; no se publica. Si BDFutbol no presenta todavía un informe utilizable, queda pendiente sin inventar datos.

## Trazabilidad y diferencia frente a una aprobación humana

La ruta automática añade un recibo inmutable con `approval_mode=automatic_policy`, ID y versión de política, ID del trabajo, hash del conjunto de candidatos, hash de la validación y hashes del documento. El ledger registra `AUTO_POLICY_AUTHORIZED`, `AUTO_POLICY_APPROVED` y `PUBLISHED` como eventos separados. No crea `DOCUMENT_APPROVED`, identidad de revisor ni confirmación humana, y no promueve la captura a la tienda de adquisición de referencia.

La publicación reutiliza la operación de paquetes v2 y su índice append-only con historial, carga íntegra posterior y verificación del manifiesto contra el índice y el ledger. La sustitución del conjunto publicado en FastAPI ocurre únicamente después de validar toda la nueva carga; `272582` debe seguir ausente. Las publicaciones históricas conservan su contrato de aprobación humana y no se vuelven a adquirir.

## Límites operativos

Este flujo puede hacer una navegación por cada candidato nuevo de los dos grupos durante una actualización global. La primera ejecución con varios partidos pendientes puede tardar; el panel informa el progreso de los informes. Una respuesta bloqueada corta las siguientes navegaciones. Los datos publicados y capturas previas no se borran; una diferencia de integridad deja el candidato pendiente y el paquete anterior activo.

Las pruebas automatizadas ejercen la política, ledger, adquisición simulada, creación del recibo, publicación y verificación en almacenes temporales. No demuestran disponibilidad actual de páginas BDFutbol ni sustituyen las condiciones de acceso de la fuente.
