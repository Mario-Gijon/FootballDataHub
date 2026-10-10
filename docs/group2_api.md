# API REST — Primera Federación Grupo II

## Arquitectura

La aplicación HTTP vive en `apps/api/football_data_hub_api/`. Carga el dataset principal durante el startup y conserva su `BootstrapResponse` en memoria. Destacados, Árbitros y Estadísticas se validan y cargan como capturas independientes: un fallo en cualquiera de ellas solo desactiva su endpoint. Sus módulos no importan el proveedor BDFutbol, Playwright ni el navegador. El extra opcional `api` permite instalar FastAPI sin instalar el extra de scraping.

El API solo sirve datos preparados. No navega a BDFutbol, vuelve a leer los JSON por petición ni ejecuta el motor Python de clasificación. Los filtros interactivos y las tablas derivadas serán responsabilidad del frontend TypeScript. El motor Python de CLAS-01B continúa siendo una referencia para validación. `progress_context` identifica el contexto original de esas series y evita que el cliente las confunda con la tabla filtrada.

## Configuración de los datasets

Copia `.env.example` a `.env`. `FDH_DATA_ROOT` puede ser una ruta relativa a la raíz del proyecto o una ruta absoluta. Las cuatro variables `FDH_GROUP2_*` admiten rutas relativas a ese directorio o rutas absolutas. El ejemplo selecciona de forma explícita el dataset `derived-clas01b-20261010T102656Z` y la captura `20261010T102656.252222Z-72f200ad`; la aplicación no escoge automáticamente el directorio más reciente.

En el inicio se verifica que:

- Los cuatro archivos tengan el esquema esperado y el mismo `capture_id`/`source_capture_id`.
- Competición, temporada, grupo y URL sean coherentes.
- Haya 20 equipos y 380 partidos, con 10 fixtures para cada una de las 38 jornadas.
- IDs de equipo y partido sean únicos y todas las relaciones apunten al catálogo cargado.
- La clasificación publicada contenga los mismos equipos y el progreso tenga un único registro por equipo y jornada disponible.
- Los contadores de `matches.json` coincidan con los partidos.

Ante error de configuración, JSON inválido o datasets mezclados, FastAPI sigue respondiendo a `/health` como proceso vivo con `dataset_ready: false`; `/ready` y las rutas de datos contestan `503`. La causa detallada se registra en el log del proceso, pero las respuestas HTTP no revelan rutas locales.

Árbitros usa `FDH_GROUP2_REFEREES_ROOT` para seleccionar una captura REF-01 versionada y opcionalmente `FDH_GROUP2_REFEREES_MATCHES` para sustituir la ruta de Resultados declarada por la captura. El valor por defecto apunta al corte validado `20261010T171227.617128Z-4cfe71bc`. En el arranque verifica los tres HTML originales por SHA-256, la identidad de captura de los JSON, los recuentos declarados en `metadata/capture.json` y `validation/results.json`, estadísticas únicas por ID/temporada/ámbito, los agregados publicados y las referencias por `referee_id` al dataset de Resultados. El ETag lleva versión de contrato. Las capturas de Árbitros y Resultados conservan sus propios `capture_id`; una fecha distinta se informa como procedencia y no mezcla filas ni fuerza igualdad estadística.

Estadísticas usa `FDH_GROUP2_STATISTICS_ROOT` para la captura versionada de STAT-01. Comprueba hashes del HTML y del proveedor numérico del gráfico, los reportes de acceso y validación, la referencia y el SHA-256 del `matches.json` activo, y vuelve a ejecutar una sola vez el motor puro de estadísticas durante el arranque. El resultado debe coincidir con los agregados, récords y rachas preparados en STAT-01. Si la captura de partidos activa cambió, o los artefactos no pertenecen a una misma captura, Estadísticas responde 503 sin desactivar las demás rutas. Sus dos `capture_id` y fechas se exponen por separado. Los penaltis son datos exclusivos de la página; no se asignan a encuentros o personas.

## Instalar y arrancar

Para una instalación solo de servidor API:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[api]'
cp .env.example .env
set -a
source .env
set +a
.venv/bin/uvicorn --app-dir apps/api football_data_hub_api.main:app --host 127.0.0.1 --port 8000
```

Swagger se sirve en [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs); OpenAPI está en `/openapi.json`. En otro host se puede cambiar `--host` según las reglas del servidor. CORS se limita a las URLs enumeradas en `FDH_CORS_ORIGINS`; no usa comodín.

Para desarrollo/test en un entorno que también vaya a ejecutar el scraper, instala los extras necesarios:

```bash
.venv/bin/python -m pip install -e '.[api,scraping,dev]'
```

## Endpoints

| Ruta | Uso |
|---|---|
| `GET /health` | Liveness del proceso y `dataset_ready`. Devuelve 200 si el proceso vive. |
| `GET /ready` | Readiness; incluye `capture_id` y `dataset_version`, o 503 si falla la carga/validación. |
| `GET /api/v1/group2/metadata` | Competición, corte, cobertura, versión y advertencias. |
| `GET /api/v1/group2/bootstrap` | Catálogo de equipos, los 380 fixtures, 120 valores de progreso y la clasificación fuente de General J6. |
| `GET /api/v1/group2/referees/bootstrap` | Catálogo sin duplicados, estadísticas publicadas por `all`/`group1`/`group2`, metadatos de captura, opciones y recuentos por ámbito. |
| `GET /api/v1/group2/statistics/bootstrap` | Totales derivados, cobertura por jornada, récords, rachas con empates, penaltis publicados, reconciliación y procedencia de ambas capturas. |

Bootstrap excluye `source_fields`, referencias internas del scraper, HTML, JavaScript, perfiles de navegador y rutas del servidor. Las fechas son ISO 8601; los datos ausentes permanecen como `null`. `published_standings` identifica expresamente la tabla de BDFutbol para General J6 y no representa otros filtros. La respuesta lleva ETag de la versión preparada y admite `If-None-Match`.

Ejemplos:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/v1/group2/metadata
curl -H 'If-None-Match: "20261010T102656.252222Z-72f200ad-<digest>"' \
  http://127.0.0.1:8000/api/v1/group2/bootstrap
```

## Muestra del bootstrap real

La respuesta completa contiene 20 equipos, 380 partidos, 120 registros de progreso y 20 filas fuente. Ejemplo abreviado de la forma de datos del corte capturado el 10 de octubre de 2026:

```json
{
  "metadata": {
    "source": "BDFutbol",
    "competition": "Primera Federación",
    "season": "2026-27",
    "group": "II",
    "team_count": 20,
    "capture_id": "20261010T102656.252222Z-72f200ad",
    "availability": {
      "teams": 20,
      "matches": 380,
      "played_matches": 59,
      "unplayed_matches": 321,
      "incomplete_matches": 0,
      "progress_records": 120,
      "progress_through_matchday": 6,
      "published_standings_available": true
    }
  },
  "teams": [
    {
      "team_id": 39,
      "name": "Zaragoza",
      "team_url": "https://www.bdfutbol.com/es/t/t2026-2739.html",
      "crest_url": "https://www.bdfutbol.com/i/eg/39.png"
    }
  ],
  "matches": [
    {
      "match_id": "272516",
      "matchday": 1,
      "matchday_date": "2026-08-30",
      "source_match_date": "2026-08-29",
      "home_team_id": 55,
      "away_team_id": 176,
      "home_goals": 1,
      "away_goals": 3,
      "status": "played",
      "unplayed_state": null,
      "postponed_by_source_rule": false
    },
    {
      "match_id": "272559",
      "matchday": 5,
      "matchday_date": "2026-09-27",
      "source_match_date": "2026-09-27",
      "home_team_id": 176,
      "away_team_id": 40,
      "home_goals": null,
      "away_goals": null,
      "status": "unplayed",
      "unplayed_state": "result_unavailable_at_capture",
      "postponed_by_source_rule": false
    }
  ],
  "progress": [
    {
      "team_id": 39,
      "matchday": 1,
      "matchday_date": "2026-08-30",
      "position": 19,
      "points": 0,
      "goals_for": 0,
      "goals_against": 2
    }
  ],
  "published_standings": {
    "source": "BDFutbol",
    "source_capture_id": "20261010T102656.252222Z-72f200ad",
    "context": {
      "classification_type": "general",
      "matchday": 6,
      "matchday_date": "2026-10-04",
      "postponed_policy": "include",
      "range_type": "all"
    },
    "rows": [
      {
        "team_id": 39,
        "team_name": "Zaragoza",
        "position": 1,
        "points": 15,
        "matches_played": 6,
        "sports_zone": "direct_promotion"
      }
    ]
  }
}
```

El recorte omite campos y filas únicamente para que sea legible; los endpoints devuelven todos los registros. La clasificación fuente conserva `position_change` y `sports_zone` solo para este contexto.

El bootstrap de Árbitros devuelve un único catálogo de personas y filas estadísticas que apuntan a ellas mediante `referee_id`. `all` es el agregado propio publicado por BDFutbol y no la concatenación de los dos grupos. Por ahora solo expone la temporada adquirida `2026-27`; no anuncia temporadas históricas listadas por la fuente. Las tarjetas son las mostradas en partidos dirigidos, no sanciones personales. Los datos nulos, incluidos edad, fecha de nacimiento y nacionalidad, se conservan como `null`.

El bootstrap de Estadísticas reutiliza el dataset activo de Resultados y no incluye una segunda copia de los partidos. Los récords solo contienen sus IDs, marcador y jornada; el cliente resuelve nombres, escudos y enlaces mediante las listas compartidas de equipos y encuentros. Las series por jornada conservan `null` y cobertura parcial. La reconciliación reporta que el gráfico publicado suma 153 goles en J1–J6 frente a 155 en el resumen; en J5 publica 19 mientras que los nueve partidos disputados suman 21. Se preservan ambos datos sin atribuir una causa. Las tarjetas rojas se muestran como tarjetas rojas, porque su equivalencia conceptual con «Expulsiones» no está demostrada.

## Consumo futuro desde TypeScript

El dashboard carga de forma diferida los bootstrap de sección al primer acceso y conserva sus respuestas en memoria. Para Estadísticas, los IDs de récords y rachas se resuelven contra equipos y partidos del bootstrap principal; el gráfico usa las 38 filas por jornada incluidas en este endpoint. Los filtros de gráfico y los cambios de pestaña son locales y no vuelven a solicitar los datos. Las series de progreso de Clasificación se consumen tal cual; no se rellenan `null` con resultados calculados. La tabla fuente sirve como referencia para comprobar el futuro motor TypeScript en General J6.
