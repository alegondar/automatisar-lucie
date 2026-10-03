# Proposal

## Why

El inventario del pendrive (`informe_pendrive.json`), el plan de limpieza (`plan_limpieza.json`) y la base de metadatos SQLite contienen cientos de registros de archivos, duplicados inter/intra-carpeta, clasificaciones por personaje y acciones propuestas. Analizar estos datos en archivos de texto o JSON voluminosos resulta complejo y propenso a errores de interpretación al momento de evaluar las decisiones de limpieza.

Este cambio introduce un dashboard web local interactivo de **SOLO LECTURA** que permite auditar visualmente el estado del pendrive y revisar minuciosamente cada acción del plan de limpieza sin riesgo alguno de modificar, copiar, renombrar o borrar nada en el pendrive ni en `~/Descargas`.

## What Changes

- **Servidor HTTP local de solo lectura (`servidor_dashboard.py`)**:
  - Implementado con librería estándar de Python (`http.server.ThreadingHTTPServer` o `HTTPServer`).
  - Vinculado exclusivamente a la interfaz local `127.0.0.1` (no expuesto a la red).
  - Puerto configurable mediante argumentos de línea de comandos (`--puerto` / `-p`), con valor predeterminado `8765` (evitando explícitamente el puerto `8000` ocupado por Portainer).
  - Admite exclusivamente peticiones `GET`. Cualquier otro método HTTP (`POST`, `PUT`, `DELETE`, `PATCH`, etc.) es rechazado terminantemente con código `405 Method Not Allowed`.
  - Lectura de SQLite estrictamente en modo solo lectura (`file:...mode=ro` con URI habilitada).

- **Interfaz de usuario (SPA) 100% offline y tema oscuro**:
  - Aplicación de página única (SPA) con HTML5, CSS y JavaScript vanilla sin dependencias ni CDNs externos, apta para funcionar completamente desconectada de internet.
  - Tema oscuro (dark mode) diseñado para lectura prolongada y contraste de datos técnicos.
  - **Banner fijo superior**: Visible de forma inamovible con la leyenda `"SOLO LECTURA: este panel no modifica nada"`.
  - **Botón "Recargar datos"**: Invoca la relectura en memoria de los archivos JSON y la caché en disco, sin disparar reescrituras ni ejecuciones en el pendrive.

- **Siete vistas de auditoría y análisis**:
  1. **Resumen**: Tarjetas de métricas principales: capacidad total del pendrive, espacio usado, libre, cantidad total de archivos analizados, duplicados detectados y desglose de acciones del plan por tipo.
  2. **Por carpeta de primer nivel**: Distribución de peso (bytes legibles) y cantidad de archivos según categoría (`video`, `foto`, `audio`, `documento`, `otro`), visualizado con barras comparativas.
  3. **Por personaje y estado**: Segmentación por personaje (`lucie`, `roli`, `mailen`) y estado deducido de las carpetas (`videos sin editar`, `videos ya editados`, `videos completos`, `videos sin publicar`), indicando cantidad de videos y duración acumulada (obtenida de la caché SQLite). Elementos no atribuibles se agrupan en "sin clasificar".
  4. **Duplicados**: Vista detallada con filtros de búsqueda por tipo (inter-carpeta, intra-carpeta, protegidas), rango de tamaño, visualización de todas las copias con rutas completas, mtime y acción propuesta.
  5. **Plan de limpieza**: Listado exhaustivo de acciones propuestas con filtros por tipo de acción, personaje y tamaño; detalle de origen, destino sugerido y motivo. Incluye casilla "revisado" para control de auditoría personal persistida en el navegador mediante `localStorage` (sin escribir en el pendrive ni en disco).
  6. **Sección destacada "laroli vs videos1/laroli"**: Análisis comparativo de archivos que residen exclusivamente en una sola de las dos carpetas homónimas.
  7. **Archivos sueltos**: Clasificación comparativa entre archivos sueltos identificados por alias de personaje vs. archivos sueltos sin clasificar.

- **Pruebas y verificación estricta**:
  - Suite de pruebas unitarias (`unittest`) que verifica la respuesta de todos los endpoints GET sobre fixtures en `/tmp`.
  - Verificación de rechazo con código `405` para cualquier método que no sea `GET`.
  - Verificación estática AST anti-borrado que confirma 0 violaciones de las 11 primitivas prohibidas en el nuevo código.

## Capabilities

### New Capabilities
- `dashboard-revision`: Servidor web local y dashboard interactivo de solo lectura para inspección visual del inventario del pendrive y revisión detallada del plan de limpieza.

### Modified Capabilities
*(Ninguna)*

## Impact

- **Código nuevo**: Módulo de servidor y UI `servidor_dashboard.py` (y archivos estáticos asociados si se desacoplan, o integrados en el servidor para portabilidad monoarchivo).
- **Pruebas**: Módulo `test_servidor_dashboard.py` agregado a la suite de tests.
- **Auditoría AST**: Inclusión del nuevo archivo operativo en la verificación de `seguridad_anti_borrado.py`.
- **Compatibilidad y seguridad**: Cero impacto destructivo; cumple estrictamente las Reglas de Oro al no implementar primitivas de modificación o borrado.
