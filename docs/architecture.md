# Principios previstos para V2

Estos son requisitos para hitos posteriores; no describen funciones implementadas.

- Ejecutar en servidores Linux sin entorno gráfico, con Playwright headless o clientes HTTP según la página. No depender del ratón, escritorio local ni interacción gráfica ordinaria.
- Admitir trabajos programables y reanudables mediante checkpoints.
- Versionar capturas raw, conservar medios originales y registrar la procedencia.
- Distinguir una adquisición correcta de una cobertura completa de la fuente.
- Permitir descubrir y auditar secciones, tablas, pestañas, gráficos y galerías.
- Detectar Cloudflare y CAPTCHA sin intentar eludirlos. Detener la adquisición afectada y ofrecer una vía autorizada para resolverlos.
- Permitir proveedores alternativos, incluida una API oficial cuando esté disponible y su uso autorizado.
- Mantener separadas las capas raw, parsed y normalized.

La implementación se diseñará por hitos después del discovery. Este documento no define contratos de entidades ni comportamiento de extracción.
