# MATCH-02 — detalles de partidos

## Estado de los datos

El único HTML deportivo detallado usado en esta tarea es el artefacto local de descubrimiento de `272582`:

`$FDH_LOCAL_DATA_ROOT/matches/details/diagnostics/match-detail-inventory-8cf339654c80c0ef/20261016T163942.933046Z-eb9b59e1/`

Su HTML tiene 1.504.876 bytes y SHA-256 `9242edad00b43a4e83c649ddad006edb0d1172e0d88640082312a0fe1cf16997`. La prueba de integración vuelve a comprobar manifiesto, hashes, identidad y semántica antes y después de la vista previa. El parser reconoce:

- 11 titulares por equipo y 21 suplentes en total.
- Los entrenadores Manolo Herrero y Albelda.
- 6 goles, 7 amarillas, 0 rojas observadas y 10 entradas más 10 salidas.
- Minutos en todos los eventos, incluidos `90+1` y `90+6`.

El parser devuelve `semantic_valid=true`, pero el almacén conserva el estado histórico `INVALID_CONTENT`, `promotion_eligible=false` y el checkpoint detenido. No hay capturas `VALID` ni índice de publicación de detalles. Por tanto, el endpoint público de `272582` continúa respondiendo con `detail_status=not_available`.

No hay una captura detallada local de Europa–Jaén (`272523`). El calendario de MATCH-00 y las apariciones en páginas de jugadores no se tratan como una ficha completa del partido.

## API y publicación incremental

`match_details_dataset.py` implementa un lector de solo lectura para `matches/details/published/index.json`. Un índice ausente significa que no hay detalles publicados; el lector no recorre `diagnostics/` ni descubre HTML por sí mismo. Cada entrada apunta a un paquete inmutable con:

- `manifest.json`: identidad del partido, generación, captura de origen e hashes.
- `approval.json`: aprobación independiente que liga `publication_id`, `internal_id`, inventario, captura, hashes del detalle y del HTML, hash del documento API, persona aprobadora y fecha con zona horaria.
- `details.json`: proyección deportiva lista para la API.

Antes de servir un paquete, el backend reconstruye el inventario desde la generación MATCH-00 verificada, valida la captura `VALID` con `MatchDetailStore.verify_capture_read_only()`, vuelve a comprobar todos los hashes, compara `details.json` con la proyección de la captura, y contrasta fecha, equipos, jornada, generación y marcador con MATCH-00. Un recibo ausente, no aprobado, alterado o discordante bloquea el paquete. El error de detalles queda aislado: Resultados sigue sirviendo su calendario y sus marcadores.

`build_match_detail_publication_draft()` prepara el documento y sus hashes sin escribir. `publish_match_detail_draft()` vuelve a verificar el origen y exige un recibo explícito que coincida campo por campo. Guarda paquetes inmutables y cambia `index.json` mediante escritura atómica bajo bloqueo exclusivo; conserva las referencias de índice anteriores en `indexes/`. Estas funciones no se invocaron durante MATCH-02.

Configuración:

- `FDH_MATCH_DETAILS_STORE_ROOT`: almacén de capturas verificadas; por defecto `$FDH_LOCAL_DATA_ROOT/matches/details`.
- `FDH_MATCH_DETAILS_PUBLISHED_ROOT`: índice de paquetes aprobados; por defecto `$FDH_LOCAL_DATA_ROOT/matches/details/published`.
- `FDH_MATCH_GENERATION_ROOT` y `FDH_LOCAL_DATA_ROOT`: deben identificar la generación y los archivos MATCH-00 ya validados.

Los modelos conservan los eventos de sustitución como `substitution_in` y `substitution_out` separados. La API no crea parejas salvo que el origen tipado proporcione explícitamente un jugador relacionado. Los perfiles internos se enlazan solo cuando el ID existe en el inventario de jugadores cargado por la API. El código de posición no se transforma en una demarcación sin equivalencia validada.

## Vista previa local de 272582

La ruta pública `/api/v1/matches/{internal_id}` no lee ni admite observaciones. Para una inspección local explícita, se puede configurar `FDH_MATCH_LOCAL_PREVIEW_ARTIFACT` con el directorio del artefacto y abrir:

`/matches/pf-2026-27-group-ii-bdfutbol-272582?preview=local`

La ruta auxiliar `__local-preview` solo responde a clientes loopback y solo existe funcionalmente si se configuró ese artefacto. Recomprueba MATCH-00, manifiesto, hashes e identidad en cada lectura, entrega `publication_status=preview_only` y no escribe capturas, checkpoints ni índices. La interfaz incluye el rótulo «Vista previa local · datos exploratorios, no publicados». La ruta no se incluye en OpenAPI pública.

Para la aplicación local, por ejemplo:

```bash
export FDH_LOCAL_DATA_ROOT="$HOME/FootballDataHub-data"
export FDH_MATCH_LOCAL_PREVIEW_ARTIFACT="$FDH_LOCAL_DATA_ROOT/matches/details/diagnostics/match-detail-inventory-8cf339654c80c0ef/20261016T163942.933046Z-eb9b59e1"
PYTHONPATH=src:apps/api .venv/bin/uvicorn football_data_hub_api.main:app --host 127.0.0.1 --port 8001
```

Para que el navegador llegue directamente a la API local y permita el endpoint de vista previa, configura la URL de la API y el origen CORS de Vite:

```bash
export FDH_CORS_ORIGINS=http://127.0.0.1:5173
export VITE_API_BASE_URL=http://127.0.0.1:8001
npm run dev -- --host 127.0.0.1 --port 5173
```

Al terminar la comprobación local, hay que reiniciar FastAPI sin `FDH_MATCH_LOCAL_PREVIEW_ARTIFACT`; el modo de vista previa no debe configurarse en despliegues.

## Visualización

La ficha reutiliza `MatchPage.tsx`: marcador, entrenadores, alineaciones en dos columnas, dorsal, fotografía con fallback, suplentes y cronología. La cronología ordena por minuto reglamentario y añadido, mantiene el orden original entre eventos con igual minuto, muestra marcador parcial solo cuando el origen lo contiene y separa entrada y salida. Un ID de jugador sin presencia verificada en el inventario queda como texto sin ruta interna.

## Límites y siguiente paso

- `272582` sigue siendo solo vista previa, nunca una publicación aprobada.
- No hay detalle local de `272523` ni de los demás partidos.
- Aún se necesita un flujo humano de revisión que entregue el recibo aprobado después de inspeccionar una captura `VALID`; no hay aprobación criptográfica ni captura publicada en esta tarea.
- La adquisición futura debe usar las políticas de acceso y el almacén existente, detenerse ante desafíos/denegaciones y requerir aprobación independiente antes de generar el índice.
- El lector actual soporta una publicación activa por partido y conserva los paquetes anteriores para auditoría.
