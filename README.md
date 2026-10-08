# FootballDataHub V2

Herramienta interna para adquirir y auditar datos de fútbol. El alcance inicial es Primera Federación 2026/27, Grupos I y II, con BDFutbol como primera fuente.

El Hito 0 documentó la estructura del sitio. El [Hito 1B](docs/hito_1b_competition_scraper.md) implementa el primer extractor reutilizable para clasificaciones, participantes y calendario/resultados de competición. El [Dev Explorer](docs/dev_explorer.md) ofrece una vista local de solo lectura de esas salidas parsed; no realiza adquisición ni modifica datos.

## Dev Explorer local

Instala sus dependencias opcionales y arráncalo desde la raíz del repositorio:

```bash
.venv/bin/python -m pip install -e '.[dev-explorer]'
.venv/bin/streamlit run scripts/run_dev_explorer.py
```

Abre <http://127.0.0.1:8501>. La aplicación selecciona por defecto el export válido más reciente. Consulta [la guía del Dev Explorer](docs/dev_explorer.md) para sus pantallas y limitaciones.
