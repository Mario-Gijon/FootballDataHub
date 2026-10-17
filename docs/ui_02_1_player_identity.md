# UI-02.1 — Identidad de jugador y relaciones observadas con clubes

## Proyección de identidad

La ficha expone una proyección de identidad separada del registro original del inventario. Los datos no se escriben de vuelta en el inventario ni en los compactos.

- Para nombre, nombre completo, fecha, edad, lugar de nacimiento, provincia, nacionalidad y demarcación, un valor no vacío del inventario tiene precedencia.
- Si el inventario no contiene un valor, se usa el campo interpretado de `views.profile.profile` en el compacto verificado.
- Si las dos fuentes contienen valores diferentes, se conserva el valor del inventario y la respuesta devuelve ambos valores y la fuente seleccionada en `identity.conflicts`.
- `country_of_birth_raw` y `nationality_raw` son campos distintos. No se usa el país de nacimiento como sustituto de nacionalidad.
- El lugar de nacimiento bruto del perfil se conserva en `birth_place_raw`. Cuando tiene la estructura observada `localidad (provincia)`, se proyecta además como localidad y provincia; no se traduce ni se corrige su texto original.
- Altura y peso se normalizan solo si el parser ya proporcionó una cifra positiva finita en centímetros/kilogramos o si el texto coincide exactamente con una cifra seguida por `cm`/`kg`. Valores como `1.90 m`, `81`, `180 lb` o texto con calificadores se conservan como texto original y no se convierten.
- `field_sources` identifica para cada valor si proviene del inventario, de la ficha individual o si no está disponible. La respuesta mantiene los SHA-256 del inventario y del HTML de perfil y la URL/fecha de captura.

La cabecera muestra nombre, nombre completo y los destacados de demarcación, altura y peso. El panel personal muestra nacimiento, país de nacimiento y nacionalidad. La vista Trayectoria no repite estos mismos campos.

## Club de referencia y movimiento

Las pertenencias de plantilla, asociaciones por referencias de traspasos y movimientos son conceptos distintos:

- **Club de referencia observado** se calcula únicamente a partir de pertenencias válidas de 2026/27 con evidencia de captura ordenable. Se requiere una pertenencia única en la captura más reciente y no debe existir una salida del mismo equipo en esa captura o en una posterior. La interfaz aclara que esa evidencia no certifica una afiliación vigente hoy.
- **Club actual no confirmado** se devuelve cuando no hay una pertenencia, faltan fechas para ordenar fuentes distintas, hay varias pertenencias en el último instante o una referencia de salida coincide con la última evidencia del equipo.
- **Último movimiento observado** requiere referencias de alta/baja compatibles por `team_id`. Los IDs determinan origen y destino; no se intenta reconciliar por nombres aproximados. Con varias parejas solo se selecciona una si existe un orden temporal fiable y único. Los empates o contradicciones quedan como ambiguos.
- Las fechas de traspaso ausentes permanecen `null`. La hora de captura se presenta como hora de observación del registro, no como fecha del movimiento.
- El historial conserva todos los clubes y grupos observados, dorsales, rótulos de plantilla, capturas y referencias de origen. No se elige una relación por el orden del array o por el último partido.

## Comprobación de Manu Pedreño (`player_id=23751`)

La comprobación local se basa en el inventario 2026/27 y en la generación compacta apuntada por `players/compact-2026-27/current.json`:

- Generación compacta: `20261017T122719.203466Z-42c0b82a`; SHA-256 del manifiesto declarado por el puntero: `7da7a6384d45937410f18e8bac93194228194ddcc2b3eea2747bd6a63b725086`.
- Entrada compacta de `23751`: SHA-256 `9aeac57b43a61fcb27f6139416a087c79424ddd818bf8da2dcd17839427e8f87`.
- Vista individual de perfil: URL `https://www.bdfutbol.com/es/j/j23751.html`, captura `20261014T133920.712440Z-bf7bc8e4`, observada `2026-10-14T13:39:25.641724Z`, SHA-256 del HTML `a0c34d3186881bb61c443fd378516e5d216955a1a17f43eaf48853c35203b870`.
- El compacto publica `Central`, `190 cm`, `81 kg`, fecha `2000-10-09`, lugar bruto `Los Garres ( Murcia )`, país de nacimiento `España` y nacionalidad ausente. El inventario aporta localidad `Los Garres`, provincia `Murcia` y la misma fecha. La nacionalidad queda sin observar.
- La pertenencia a UD Logroñés, Grupo I, está en la captura `20261012T160156.898705Z-8b30ebbd`, observada `2026-10-12T16:03:01.180645Z`. UD Ibiza, Grupo II, está en `20261013T164727.182448Z-61cb9f64`, observada `2026-10-13T16:48:36.725160Z`.
- El alta de UD Logroñés referencia por ID a UD Ibiza (`other_team_id=414`); la baja de UD Ibiza referencia por ID a UD Logroñés (`other_team_id=178`). Ambas fechas de traspaso son nulas. La baja y la pertenencia a Ibiza se observaron en la misma captura.
- Por ello se muestra el último movimiento observado **UD Ibiza (II) → UD Logroñés (I)**, pero el club actual queda **no confirmado**. No se escoge UD Logroñés como afiliación actual.

## Columnas y cobertura

Solo se usan como encabezados los textos originales verificados en la captura. Un encabezado ausente se muestra como «Dato de origen N» y ofrece un detalle desplegable de procedencia con el índice y los atributos originales que existan. Se preservan los valores de fila y columnas; no se asignan nombres deportivos por intuición. Los roles conocidos tienen nombres de interfaz en español; roles/IDs de origen quedan en detalles de procedencia, no como título visible de la tabla.

Los estados conocidos de cobertura se traducen a frases comprensibles. El valor original permanece disponible en el compacto y en la respuesta de datos individuales. «No certificado como completo» no significa que la tabla esté vacía ni que se haya comprobado exhaustividad.

## Alcance de validación

Las pruebas unitarias cubren precedencia, discrepancias, nulos, unidades ambiguas, pertenencias empatadas, perfiles solo con traspasos, salida coincidente y orden de arrays. La integración opcional `tests/integration/test_ui01_local_data.py` carga la generación y las capturas externas mediante sus hashes y comprueba los campos reales de Manu. No adquiere datos ni modifica los snapshots.
