# Proposal: Ciclo de Vida y Gestión de Capítulos en Bandeja de Descargas

## Why

Actualmente la bandeja permite marcar un capítulo activo básico, pero carece de un flujo completo de ciclo de vida para empezar una sesión de descarga, terminarla con balance de archivos pendientes y movidos, evitar sesiones olvidadas durante horas, y reabrir capítulos finalizados para continuar agregando tomas. Esta mejora dota a la herramienta de un control intuitivo y ordenado para que el usuario gestione sus historias y rodajes sin perder archivos ni mezclar contextos.

## What Changes

- **Control de inicio de capítulo**: Controles superiores con selector de personaje (`lucie`, `roli`, `mailen`), campo "Nombre del capítulo" y botón "Empezar capítulo".
- **Canalización unificada al personaje seleccionado**: El personaje elegido establece la carpeta de destino (`<destino>/<personaje>/<capítulo>`). Todo archivo candidato del proyecto de cualquier personaje (`lucie`, `roli`, `mailen`, Grok, Gemini, Nano Banana) detectado en `~/Descargas` se asigna automáticamente al capítulo activo.
- **Capítulo único activo**: Solo puede existir un único capítulo activo en simultáneo. El banner superior permanente refleja `"Capítulo activo: <personaje>/<capítulo>"` junto al botón "Terminar capítulo".
- **Flujo de terminación con balance**: Al presionar "Terminar capítulo", se presenta un modal con el resumen ("N archivos pendientes, M ya movidos") y dos opciones de salida:
  1. *"Mover pendientes y terminar"*: abre la simulación previa habitual de los archivos pendientes y, tras la confirmación del usuario, traslada los archivos y cierra el capítulo.
  2. *"Terminar sin mover"*: cierra inmediatamente el capítulo dejando los archivos pendientes en `~/Descargas` como lotes huérfanos sin capítulo activo.
- **Cierre y retorno al modo de respaldo**: Al terminar un capítulo, este queda cerrado; las descargas subsiguientes no se le asignan y retoman el modo de respaldo habitual (por alias al inicio o sin identificar).
- **Catálogo y reapertura de capítulos**: Listado de capítulos cerrados disponibles para consulta con botón "Reabrir", permitiendo reanudar la recepción de archivos en una escena preexistente.
- **Detección y alerta de capítulo olvidado**: Advertencia visual destacada si el capítulo activo acumula más de 12 horas abierto (umbral configurable en `config_bandeja.json`), preguntando "¿Sigue activo este capítulo?" con botones para "Seguir" o "Terminar".
- **Persistencia íntegra en SQLite**: Catálogo de capítulos históricos y activos en SQLite (`bandeja_capitulos`), persistiendo ante reinicios del servidor. Modificar, terminar o reabrir capítulos nunca reasigna archivos detectados previamente.

## Capabilities

### New Capabilities
- `bandeja-capitulos`: Control del ciclo de vida de capítulos (empezar, asignar candidatos universales, balance de pendientes/movidos al terminar, terminar con o sin mover, reabrir capítulos cerrados, alerta por tiempo transcurrido y persistencia en base de datos).

### Modified Capabilities
<!-- No se modifican capabilities preexistentes en openspec/specs/. -->

## Impact

- **Código afectado**:
  - `bandeja_descargas.py`: Estructura de tabla `bandeja_capitulos` en `GestorBaseDatosBandeja`, nuevos métodos para ciclo de vida de capítulos, endpoints API (`/api/capitulos/empezar`, `/api/capitulos/terminar`, `/api/capitulos/reabrir`, `/api/capitulos/cerrados`, `/api/capitulo-activo`), enriquecimiento de la SPA con banner de capítulo activo, modal de terminación con métricas, panel de reapertura y alerta de capítulo olvidado.
  - `config_bandeja.json`: Campo `horas_alerta_capitulo_olvidado: 12`.
  - `test_bandeja_descargas.py`: Nuevas pruebas unitarias en `/tmp` que validen empezar capítulo, asignación universal, balance al terminar, opciones de cierre con/sin mover, reapertura, detección de capítulos olvidados (>12h) y auditoría AST sin primitivas de borrado.
- **Compatibilidad**: Conserva total compatibilidad con el modo de respaldo por alias al inicio, la sala de espera unificada sin subcarpetas de tipo y la bitácora `.jsonl` con reversión por lote.
