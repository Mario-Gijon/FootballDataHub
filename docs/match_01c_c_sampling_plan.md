# MATCH-01C-C — selección offline y preparación de campaña

## Alcance y resultado

Este hito verifica MATCH-00 y MATCH-01A desde archivos locales, selecciona cinco muestras reproducibles y describe una futura campaña. No contiene ni llama a una ruta de navegación. El comando escribe JSON en stdout y solo guarda un informe separado si se pide expresamente con `--write-report`; esa opción no permite sustituir archivos existentes ni escribir dentro de los árboles de origen o del almacén.

La selección usa el inventario MATCH-01A validado, con 140 partidos disputados y URL individual explícita (70 por grupo), procedente de `match-00-4ad1d610507e425d`. Las fechas y resultados son los del catálogo de calendario. No demuestran que una futura ficha individual tenga una estructura concreta ni que todos sus datos coincidan con el calendario.

## Muestras seleccionadas

El orden es el orden del plan y el primer candidato sería el primero que se revisaría **solo tras una autorización futura independiente**.

| Orden | ID BDFutbol | ID interno | Grupo | Jornada | Fecha del partido / fecha de jornada | Local (ID) | Marcador | Visitante (ID) | URL exacta | Motivo |
| ---: | ---: | --- | :---: | ---: | --- | --- | :---: | --- | --- | --- |
| 1 | `272525` | `pf-2026-27-group-ii-bdfutbol-272525` | II | 1 | 2026-08-31 / 2026-08-30 | Teruel (`204`) | 0–0 | Real Madrid Castilla (`61`) | [Ficha 272525](https://www.bdfutbol.com/es/p/p.php?id=272525) | Grupo II, 0–0. |
| 2 | `272517` | `pf-2026-27-group-ii-bdfutbol-272517` | II | 1 | 2026-08-29 / 2026-08-30 | Huesca (`79`) | 1–0 | Sant Andreu (`119`) | [Ficha 272517](https://www.bdfutbol.com/es/p/p.php?id=272517) | Victoria por un gol. |
| 3 | `272577` | `pf-2026-27-group-ii-bdfutbol-272577` | II | 7 | 2026-10-11 / 2026-10-11 | Atlético Madrileño (`67`) | 4–4 | Zaragoza (`39`) | [Ficha 272577](https://www.bdfutbol.com/es/p/p.php?id=272577) | Partido de al menos cinco goles; es el total más alto disponible con menor diferencia. |
| 4 | `272524` | `pf-2026-27-group-ii-bdfutbol-272524` | II | 1 | 2026-08-30 / 2026-08-30 | Gimnàstic de Tarragona (`17`) | 2–0 | Zaragoza (`39`) | [Ficha 272524](https://www.bdfutbol.com/es/p/p.php?id=272524) | Diferencia de dos goles, sin atribuir eventos especiales. |
| 5 | `269411` | `pf-2026-27-group-i-bdfutbol-269411` | I | 1 | 2026-08-29 / 2026-08-29 | Arenas de Getxo (`87`) | 1–1 | Racing de Ferrol (`48`) | [Ficha 269411](https://www.bdfutbol.com/es/p/p.php?id=269411) | Segundo grupo; empate distinto del 0–0 para contraste. |

Las categorías están definidas para que la elección sea repetible: 0–0 exacto; diferencia de un gol; al menos cinco goles totales; diferencia de dos o más; y al menos una muestra del Grupo I. Cada categoría usa una URL distinta y se excluye `272582`. Para muchos goles se prefiere menor diferencia, después mayor total, jornada e ID. Por eso se elige el 4–4 del ID `272577`; el catálogo contiene otros marcadores que también superarían el umbral.

Para estas cinco fichas se desconocen la estructura individual, las alineaciones, los futbolistas, los minutos, los cambios, las tarjetas y el contenido de los eventos. El resultado del calendario no permite inferir autogoles, expulsiones, sustituciones ni ninguna otra característica de la página.

## Integridad del origen y estado MATCH

| Artefacto | Identidad | SHA-256 |
| --- | --- | --- |
| Generación MATCH-00, manifiesto | `match-00-4ad1d610507e425d` | `00166887b13413e3e6a5344fa1c64d52db8d38800f3ef9f282237584b3e65fbf` |
| Inventario MATCH-01A | `match-detail-inventory-8cf339654c80c0ef` | `9be747311ff237235b21e27c064d486d4ce990c3278d9020bae816968aabac08` |
| Manifiesto del inventario | mismo `inventory_id` | `e31b4ad341c87634b8f1cc032e02acae40d7de94f5a0de9e23a0a58ee3056b2b` |
| Checkpoint MATCH-01B | mismo `inventory_id`, revisión 4 | `d129476f2caebe1a9876fefe3a86cf6facf7254c96262a1ee4996855713e06f0` |

El checkpoint sigue en `stopped`. `reconcile()` encontró `integrity_blocked=false`, ningún snapshot válido y ningún intento de navegación pendiente. Sí hay una parada activa (`active_stop=true`), derivada del estado detenido, del artefacto de descubrimiento y del diagnóstico con `stop_acquisition`. El diagnóstico histórico es HTTP 200, `INVALID_CONTENT`, `IDENTITY_OR_CONTENT_UNVERIFIED`, para `272582`; no es una denegación HTTP. La reserva de su única navegación figura resuelta con ese diagnóstico. El artefacto diagnóstico mantiene su manifiesto e incluye HTML con SHA-256 `9242edad00b43a4e83c649ddad006edb0d1172e0d88640082312a0fe1cf16997`.

El planificador leyó el estado mediante el `acquisition.lock` existente y un lock compartido de solo lectura. No llamó a `prepare_inventory()`, `begin_navigation_attempt()`, `record_diagnostic()`, `store_discovery_artifact()` ni `store_valid_capture()`. La integración offline confirma que generación, inventario y almacén no cambiaron. El resultado es `BLOCKED` por la parada activa. El plan no borra ni resuelve esa parada y no habilita navegación.

## Por qué no reutilizar directamente MATCH-01B

`pilot_cli.py` restringe el piloto al inventario y generación aprobados. `acquisition.select_pilot_record()` exige exactamente el ID `272582`, su ID interno, URL, equipos y marcador. `run_match_discovery_pilot()` reconcilia el almacén antes de reservar y rechaza integridad bloqueada o parada activa. No acepta los candidatos nuevos ni puede resolver el checkpoint. Pasar otro ID o cambiar la selección del plan no crea una autorización ni vuelve ejecutable esa ruta.

La selección nueva vive únicamente en un plan canónico con `campaign_id` `match-detail-sample-campaign-67fdc4b4fac66b82`. El SHA-256 del plan es `3724965228fd94132ae1ee659678e8cbe8917dee529b74bfebd0c2fd28dcaa40`. Esos identificadores describen el plan actual; un cambio de inventario, generación o selección debe producir otra identidad.

## Diseño requerido para una adquisición controlada futura

No se implementa en este hito. Antes de permitirla, otro cambio deberá añadir y probar:

1. Una autorización append-only por partido, ligada al `campaign_id`, `inventory_id`, hash del inventario, ID interno, ID BDFutbol y URL exacta. Cada autorización concede como máximo una navegación, no concede reintentos ni promoción y queda consumida al crear la reserva.
2. Un registro explícito de revisión humana para la parada de `272582`. Debe conservar intactos su checkpoint y diagnóstico. La adquisición nueva seguirá bloqueada si falta ese registro; ninguna opción `--force` ni una nueva campaña puede saltarse la revisión.
3. Un ledger/namespace de campaña independiente para reservas y diagnósticos, con reserva `started` atómica y durable antes del navegador. Una caída deja el candidato bloqueado para revisión manual; no hay reanudación automática.
4. Un lock común entre procesos del almacén y del perfil de navegador, mantenido desde la comprobación y reserva hasta cerrar la sesión. Debe impedir dos campañas que compartan perfil o almacenamiento.
5. Una sola navegación por reserva; cualquier HTTP no válido, desafío, redirección, error persistente del navegador, identidad o estructura insuficiente detiene el candidato. Sin rotación de perfil/IP ni resolución de desafíos.
6. Diagnósticos y HTML de descubrimiento aislados, inmutables y con hashes, procedencia y manifiesto. No son capturas promocionables. La promoción futura requiere validación semántica con evidencia DOM ligada al HTML, no banderas declaradas ni el resultado del calendario.

La separación de campaña aísla evidencia y autorización; no sirve para ignorar la parada histórica. La decisión humana para permitir la primera muestra debe indicar expresamente si la parada anterior es global o queda acotada al piloto, referir su hash/diagnóstico y autorizar solo el partido seleccionado. El checkpoint original continuará detenido e inalterado.

## Ejecución offline

Desde el checkout principal:

```bash
PYTHONPATH=src .venv/bin/python scripts/plan_bdfutbol_match_samples.py
```

El comando predeterminado solo lee MATCH-00, MATCH-01A y el almacén. No inicia navegador ni solicita acceso de red. Se pueden fijar otras rutas locales con `--data-root`, `--generation-root`, `--inventory-dir` y `--store-root`. Para guardar una copia inmutable del informe fuera de los datos de origen y del almacén:

```bash
PYTHONPATH=src .venv/bin/python scripts/plan_bdfutbol_match_samples.py \
  --write-report /ruta/de-informes/match-sample-plan.json
```

La ruta debe ser nueva; nunca se sobrescribe. Un plan `BLOCKED` devuelve código 2 aunque muestra los candidatos para revisión.

## Pruebas

Las pruebas sintéticas cubren determinismo, selección desde el inventario, exclusión de `272582`, coherencia ID/URL/equipos/resultado, categorías ausentes, inventarios ausentes/corruptos/alterados, parada, no mutación, ausencia de red, navegación y promoción, y repetibilidad. La integración local optativa vuelve a verificar hashes, genera la selección desde las capturas originales y comprueba que no cambian:

```bash
FDH_MATCH_01C_C_INTEGRATION=1 \
PYTHONPATH=src .venv/bin/python -m pytest -p no:rerunfailures -q \
  tests/integration/test_match_detail_sample_plan_latest.py
```

No se hicieron solicitudes HTTP ni se ejecutó navegador durante MATCH-01C-C.
