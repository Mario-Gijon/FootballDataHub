# Adquisición por lotes de fichas de equipo

## Estado

El orquestador secuencial y su manifiesto están implementados y probados con
fixtures offline. La CLI real se ejecutó únicamente para Racing de Ferrol
(`team_id=48`), no para los 40 equipos. No hay programación periódica ni una
ejecución en el servidor de la UJA.

## Alcance del lote

`scripts/acquire_bdfutbol_team_batch.py` acepta Grupo I, Grupo II o ambos, y
una o más vistas (`--view`). Si no se indican vistas, selecciona las seis:

```text
alignment, squad, statistics, follow, transfers, matches
```

El inventario se carga desde los dos catálogos de partidos ya validados, con 20
IDs por grupo. Se usa un proceso navegador cada vez, un club cada vez, una
sesión por club y ninguna navegación paralela. Si no hay una Alineación previa,
la añade como vista base para identificar el equipo y resolver los enlaces
reales a las otras páginas.

Ejemplo de ejecución futura para el Grupo I:

```bash
PYTHONPATH=src xvfb-run -a -s '-screen 0 1920x1080x24' \
  .venv/bin/python scripts/acquire_bdfutbol_team_batch.py \
  --season 2026-27 --groups I \
  --profile "$HOME/.football-data-hub-team-profile" \
  --output-root /srv/football-data-hub/team-captures
```

`--groups II` selecciona el otro grupo y `--groups both` recorre ambos. Se
pueden repetir `--view` para pedir una selección limitada. Los catálogos se
pueden pasar con `--group1-catalog` y `--group2-catalog`, o mediante
`FDH_BDFUTBOL_GROUP1_MATCHES` y `FDH_BDFUTBOL_GROUP2_MATCHES`.

## Reanudación y estados

Antes de navegar a un equipo, se busca una captura que:

1. incluya todas las vistas solicitadas;
2. tenga validación `valid=true`;
3. conserve para cada vista HTTP 200 y estado `VALID`;
4. tenga los snapshots en disco y hashes coincidentes con el contenido original
   descomprimido.

Una captura que satisface los cuatro requisitos se marca `complete` y se omite.
Si solo hay un snapshot parcial válido, se usa como semilla y el navegador
adquiere únicamente las vistas pendientes. La exportación crea un directorio
nuevo y deja explícitos `acquired_views`, `reused_views` y
`reused_source_capture_ids`.

El manifiesto final incluye cada equipo y su estado:

| Estado | Significado |
|---|---|
| `complete` | Todas las vistas pedidas pasaron validación, o una captura completa con hashes válidos ya existía. |
| `incomplete` | Existía una captura parcial, pero una vista solicitada falló o el acceso fue denegado. |
| `failed` | El equipo no tenía captura válida reutilizable y la adquisición o validación falló. |
| `pending` | No se inició porque una denegación anterior detuvo el lote. |

Los errores locales de parsing, estructura o validación quedan asociados al
club y el lote continúa con el siguiente. Una denegación/desafío, un error HTTP
de origen, un fallo de navegación o un problema de navegador/almacenamiento
detiene el lote para evitar repetir una condición que afecta a los siguientes
equipos. Una denegación o desafío se marca específicamente como tal; el resto
conserva su motivo técnico. No se reintenta ni cambia de navegador, identidad o
dirección IP. Una carpeta
versionada de manifiesto se publica con rename atómico bajo
`<output-root>/<season>/batch-manifests/<run_id>/manifest.json`.

No ejecutar el lote completo hasta preparar el host, almacenamiento y perfil
autorizado del servidor. Una primera prueba en la UJA debería limitarse a un
club con `--groups` y catálogo explícitos; el script permite seleccionar vistas
para esa prueba.

## Política de snapshots y almacenamiento

- Las capturas antiguas en HTML plano permanecen intactas y siguen siendo
  reproducibles.
- Los runs nuevos guardan el HTML como gzip determinista (`mtime=0`). El
  SHA-256 publicado corresponde a los bytes del HTML descomprimido; también se
  registra el tamaño almacenado.
- El HTML original sigue siendo recuperable exactamente con gzip, y el parser
  offline acepta tanto el formato antiguo plano como el comprimido.
- No se borran capturas incompletas o antiguas automáticamente. El manifiesto y
  la validación permiten decidir una política de archivo/retención posterior.
- En este piloto real, las seis vistas ocupan 724 KB comprimidas; las cuatro
  variantes de Seguimiento ocupan otros 489 KB. Es un único equipo y solo una
  referencia de tamaño, no una garantía para los 40 clubes.
- Los JSON normalizados, manifiestos, hashes y validaciones se conservan junto
  al snapshot para poder consumirlos offline. En el servidor UJA se recomienda
  configurar `--output-root` en almacenamiento persistente fuera del checkout;
  así se conserva la procedencia completa sin añadir cada actualización al
  historial Git. No se requiere instalar un servicio ni base de datos.

## Verificación realizada

Las pruebas automáticas offline simulan éxito, error local, reanudación sin
duplicación, parada ante desafío, estado pendiente y exportación create-only
del manifiesto. `find_valid_capture` verifica cobertura, estado, existencia y
hash del snapshot. El lote de 40 clubes no se ha iniciado.
