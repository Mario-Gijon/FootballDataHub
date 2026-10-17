# MATCH-01C-D0/D1 — campaña de descubrimiento controlado

## Alcance y estado de D1

D0 creó un ledger independiente y una selección fija de cinco partidos. D1 añade
la verificación de la parada histórica, comandos humanos separados y el ejecutor
de una sola navegación para el candidato `272525`. El ejecutor real utiliza
`BDFutolAccess` y el `BrowserSessionManager` existente con SeleniumBase Pure CDP,
Chromium y Xvfb administrado.

D1 **no** ha escrito en el ledger real, no ha creado revisión humana ni
autorización, no ha reservado `STARTED`, no ha iniciado navegador y no ha hecho
HTTP. Los cinco candidatos permanecen `NOT_AUTHORIZED`; `272525` sigue siendo el
primero y único candidato que se podrá autorizar de forma individual.

La selección permanece ligada al plan MATCH-01C-C, generación
`match-00-4ad1d610507e425d`, inventario
`match-detail-inventory-8cf339654c80c0ef` y partidos `272525`, `272517`,
`272577`, `272524` y `269411`. El contrato impide usar la URL o autorización de
un candidato para otro.

## Evidencia histórica `272582`

La revisión ya no acepta bytes y un SHA-256 declarados por quien llama. El
verificador de solo lectura reconstruye el inventario desde la generación
validada, valida el `inventory.json` y su manifiesto, localiza el registro
histórico único, compara el hash actual del checkpoint y comprueba que siguen
presentes su parada, diagnóstico, intento y referencia al artefacto originales.
Después llama al parser semántico offline, que vuelve a validar el manifiesto y
los hashes del HTML.

La verificación efectuada en D1 confirmó:

- Partido e intento: `272582`, intento
  `90c760697c9141acb43e706396bf746e`.
- Checkpoint, revisión 4: SHA-256
  `d129476f2caebe1a9876fefe3a86cf6facf7254c96262a1ee4996855713e06f0`.
- Artefacto: `20261016T163942.933046Z-eb9b59e1`; manifiesto SHA-256
  `bf297e0fabe635b017ecd315aaa68e4ca4079f7b2d090fd48dcc622f14e7b802`.
- HTML: SHA-256
  `9242edad00b43a4e83c649ddad006edb0d1172e0d88640082312a0fe1cf16997`.
- Parser: `match-detail-semantic-0.2.0`, `semantic_valid=true` y
  `promotion_eligible=false`.

Esto no cambia el resultado histórico `INVALID_CONTENT`, no promueve esa captura
y no decide el alcance de la parada. La elección entre `scope_to_original_pilot`
y `block_entire_campaign` sigue requiriendo una decisión humana explícita. Cada
escritura vuelve a verificar los hashes actuales bajo los locks; la autorización
y la ejecución verifican otra vez que la evidencia no cambió desde la revisión.

## Ejecución real y barreras

El orden fijo de exclusión es:

1. lock exclusivo del ledger de campaña;
2. lock exclusivo del almacén MATCH;
3. lock exclusivo del perfil, adquirido por `BrowserSessionManager` antes de
   iniciar Chromium.

El ejecutor confirma que el checkpoint histórico sigue intacto y que el almacén
no contiene corrupción. El estado `stopped` conocido solo puede quedar acotado
mediante la decisión humana registrada en la revisión; no existe `--force` ni
desbloqueo automático. Se guarda un evento `STARTED` duradero antes de llamar a
la sesión/adaptador. El candidato queda consumido si la navegación, el arranque
del navegador o el proceso fallan. Un proceso nuevo no puede repetirlo.

El perfil indicado debe tener nombre `match-detail-272525`, estar dentro de
`data_root` y quedar fuera del almacén MATCH. Pure CDP lanza una instancia nueva
en Xvfb, con `about:blank` como URL inicial; el navegador existente rechaza
perfiles con Chromium activo y libera su lock al cerrarse. El navegador solo
abre la URL exacta autorizada, una vez, sin reintentos ni resolución de desafíos.

El resultado distingue errores de HTTP, desafío/denegación, redirección,
fallo/timeout del navegador, documento ilegible y contenido HTTP 200 cuya
identidad no se ha validado. Un HTTP 200 de la URL exacta, con HTML disponible y
sin señales de bloqueo puede guardarse como evidencia `DISCOVERY_REVIEW_REQUIRED`
incluso si falla el marcador preliminar. El artefacto incluye procedencia,
metadatos y hashes, sigue marcado como no promocionable y no llama a
`store_valid_capture()`.

## CLI y comandos futuros

El preflight predeterminado sigue siendo de solo lectura y no inicia navegador.
El nuevo gestor ofrece subcomandos separados; D1 no ejecutó los tres subcomandos
de escritura/ejecución.

```bash
PYTHONPATH=src .venv/bin/python scripts/manage_bdfutbol_match_campaign.py preflight
```

Una futura revisión histórica (decisión humana independiente):

```bash
PYTHONPATH=src .venv/bin/python scripts/manage_bdfutbol_match_campaign.py review-legacy \
  --reviewer "NOMBRE DEL REVISOR" \
  --decision scope_to_original_pilot \
  --confirm-historical-review I_REVIEWED_MATCH_272582_AND_CHOOSE_A_SCOPE
```

Una futura autorización individual de `272525`, usando el `review_id` devuelto
por el comando anterior:

```bash
PYTHONPATH=src .venv/bin/python scripts/manage_bdfutbol_match_campaign.py authorize \
  --internal-id pf-2026-27-group-ii-bdfutbol-272525 \
  --reviewer "NOMBRE DE QUIEN AUTORIZA" \
  --review-id "ID_DEVUELTO_POR_REVIEW_LEGACY" \
  --confirm-url https://www.bdfutbol.com/es/p/p.php?id=272525 \
  --confirm-authorization AUTHORIZE_ONE_DISCOVERY_NAVIGATION
```

La ejecución real futura requiere el ID de autorización devuelto, el perfil
dedicado y la confirmación de que PLAYER liberó el navegador:

```bash
PYTHONPATH=src .venv/bin/python scripts/manage_bdfutbol_match_campaign.py run \
  --internal-id pf-2026-27-group-ii-bdfutbol-272525 \
  --authorization-id "ID_DEVUELTO_POR_AUTHORIZE" \
  --confirm-url https://www.bdfutbol.com/es/p/p.php?id=272525 \
  --profile-dir "$HOME/FootballDataHub-data/browser-profiles/match-detail-272525" \
  --confirm-one-navigation EXECUTE_ONE_MATCH_DISCOVERY_NAVIGATION \
  --confirm-player-browser-idle PLAYER_BROWSER_IDLE_CONFIRMED
```

Los comandos de revisión y autorización cambian el ledger y requieren el token
exacto; `run` hace la única navegación y requiere sus propias confirmaciones.
No se deben ejecutar sin revisar antes el preflight y la evidencia. Cualquier
parada, desafío, respuesta inesperada o interrupción consume la autorización y
requiere revisión manual.

## Validación ejecutada

Las pruebas sintéticas cubren autorizaciones ligadas a candidato/URL, reserva
`STARTED`, respuestas HTTP/denegaciones/redirecciones, timeout, interrupción
abrupta, no repetición y ausencia de promoción. La prueba de integración optativa
releyó el artefacto local real y comprobó que sus hashes permanecían intactos;
no hizo HTTP ni abrió navegador. El preflight real siguió mostrando los cinco
candidatos `NOT_AUTHORIZED` y cero navegaciones.

El lock de perfil de BrowserSessionManager es cooperativo entre procesos
FootballDataHub. No protege frente a procesos externos que ignoren ese lock; el
chequeo de procesos asociados al perfil y el uso de un perfil dedicado reducen
ese riesgo. D1 no prueba la autorización contractual del sitio para futuras
capturas ni demuestra que el acceso a otros encuentros estará disponible.
