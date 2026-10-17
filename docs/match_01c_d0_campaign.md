# MATCH-01C-D0 — ledger de campaña controlado

## Alcance

D0 añade contratos y persistencia para una futura revisión manual por partido. No
contiene una ruta de navegación real: el ejecutor solo acepta el adaptador
`SimulatedMatchAccessAdapter`, y el CLI disponible solo hace preflight de lectura.
No se inicia Chromium, no se hace HTTP y no se promocionan capturas.

La campaña se deriva del plan MATCH-01C-C, generación `match-00-4ad1d610507e425d`,
inventario `match-detail-inventory-8cf339654c80c0ef` y su selección canónica de
cinco IDs (`272525`, `272517`, `272577`, `272524`, `269411`). Los hashes de la
generación, inventario, manifiesto y capturas se validan contra el propio plan.
No se copian los resultados de calendario a una ficha ni se afirman datos HTML de
los cinco candidatos.

## Estado histórico 272582

El ledger de campaña es independiente del checkpoint detenido de MATCH-01B. Su
identidad registra el ID de inventario, hash del checkpoint, revisión, intento
original, hash y diagnóstico original. Se requiere además que una futura revisión
humana cite una referencia y hash de la evidencia semántica offline posterior.

D0 no crea esa revisión. Sin ella, cada candidato aparece `NOT_AUTHORIZED` y el
preflight devuelve `BLOCKED`. Una futura decisión `scope_to_original_pilot` solo
acota la parada al piloto histórico; `block_entire_campaign` mantiene bloqueada la
campaña. La revisión no autoriza una navegación por sí misma. El checkpoint,
diagnóstico y artefacto históricos no se abren para escritura desde este módulo.
Al registrar una revisión, D0 exige los bytes de la evidencia semántica y verifica
su SHA-256 junto con los hashes del checkpoint y el diagnóstico y el ID del intento.
La evidencia posterior no cambia el resultado histórico `INVALID_CONTENT`.

## Persistencia e integridad

La raíz prevista es `~/FootballDataHub-data/matches/details/campaigns/`. Cada
campaña tiene `campaign.json` y un manifiesto inmutables. Cada candidato tiene su
propio registro de eventos JSON append-only, numerado y enlazado por SHA-256. Los
artefactos exploratorios también viven bajo el candidato, con hashes de los bytes
originales, reporte de descubrimiento genérico, metadatos y manifiesto. Las
escrituras nuevas usan temporal, `fsync`, creación sin reemplazo y `fsync` del
directorio. Un lock entre procesos protege transiciones y ejecución simulada.

El preflight verifica el plan y el manifiesto, enlaces de eventos, contratos de
autorización, integridad de revisiones y artefactos, candidatos desconocidos y
archivos huérfanos. No repara ni limpia la evidencia. Una caída luego de escribir
`STARTED` deja el candidato como `INTERRUPTED_REQUIRES_REVIEW`; la autorización se
consume antes de llamar al adaptador y no se puede reutilizar. Un fallo HTTP,
desafío, redirección, respuesta sin estado, error de documento o de almacenamiento
produce parada; no hay reintentos ni promoción.

Aunque un documento HTTP 200 pueda guardarse como `DISCOVERY_REVIEW_REQUIRED`,
D0 no interpreta su HTML. Un futuro validador deberá contrastar URL canónica,
`codi` de la ficha, los dos equipos, marcador y contexto antes de decidir
identidad. El texto preliminar del cuerpo no basta y este ejecutor nunca llama a
`store_valid_capture()`.

## Estados

| Estado | Significado |
| --- | --- |
| `NOT_AUTHORIZED` | No hay evento de autorización para el candidato. |
| `AUTHORIZED` | Existe una autorización humana exacta, todavía sin reserva. |
| `STARTED` | Reserva durable creada antes del adaptador; en el preflight equivale a interrupción pendiente de revisión. |
| `DISCOVERY_REVIEW_REQUIRED` | Se guardó evidencia HTTP 200 no promocionable que necesita revisión semántica. |
| `STOPPED` | Un error o filtro de seguridad detuvo al candidato. |
| `INTERRUPTED_REQUIRES_REVIEW` | El último evento durable es `STARTED`; no se repite la navegación. |

Después de un `STOPPED`, `DISCOVERY_REVIEW_REQUIRED` o intento interrumpido, el
preflight de campaña queda bloqueado para nuevas autorizaciones. D0 no implementa
un evento que cierre revisiones de candidatos; esa transición requerirá un cambio
futuro revisado.

## Locks y aislamiento

D0 utiliza un lock exclusivo propio del ledger durante las escrituras y durante la
simulación. No adquiere el lock del almacén MATCH-01B ni el del perfil Chromium:
no toca el checkpoint existente, no comparte estado con PLAYER y no inicia un
navegador. Antes de habilitar un adaptador real, otro cambio deberá coordinar el
lock del almacén y el lock del perfil Chromium de `BrowserSessionManager` durante
toda la sesión, comprobar sus rutas y evitar que se conecte a perfiles existentes.
Ese adaptador no está presente ni se puede habilitar mediante este CLI.

## Comando disponible

Solo se ofrece un preflight offline y de solo lectura:

```bash
PYTHONPATH=src .venv/bin/python scripts/preflight_bdfutbol_match_campaign.py
```

Permite especificar `--data-root`, `--generation-root`, `--inventory-dir`,
`--store-root` y `--campaign-root`. No crea el ledger ni un archivo de lock cuando
la raíz aún no existe. Hoy el primer candidato `272525` se informa como
`NOT_AUTHORIZED`; no hay comando de adquisición, revisión o autorización.

## Validación

Las pruebas usan planes, almacenes, HTML y adaptadores sintéticos en `tmp_path`.
La prueba 272525 solo valida ID, URL y estados del plan: no inventa marcador,
alineaciones ni estructura de una página real. La integración sobre la captura
272582 y los tests anteriores se ejecutan en modo lectura; no escriben en el
checkpoint antiguo. La futura adquisición seguirá prohibida hasta MATCH-01C-D1 y
una autorización humana individual.
