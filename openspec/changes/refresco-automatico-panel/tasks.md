# Tasks

## 1. Configuración y Backend: Endpoint /api/estado-version y Trazabilidad

- [x] 1.1 Agregar `"refresco_panel_segundos": 4` a `config_bandeja.json` y a `ConfiguracionBandeja` en `bandeja_descargas.py` y verificar su carga correcta
- [x] 1.2 Implementar método para calcular token de versión liviano en `VigilanteBandeja` y `GestorBaseDatosBandeja` y verificar que refleja cambios de estado
- [x] 1.3 Agregar ruta `GET /api/estado-version` en `HandlerServidorBandeja` con validación estricta de `Host` y rechazo de `POST` (405) y verificar respuesta HTTP
- [x] 1.4 Agregar logging estructurado de ciclo de vida (`[DETECTADO]`, `[ESTABLE]`, `[REGISTRADO]`) y cierre seguro de conexiones SQLite en `bandeja_descargas.py`

## 2. Frontend: Polling, Pausas, Indicadores y Preservación de Estado de UI

- [x] 2.1 Implementar controlador de sondeo de `/api/estado-version` en el cliente JavaScript respetando `refresco_panel_segundos` y pausas por `document.hidden` y modales abiertos
- [x] 2.2 Implementar motor de captura y restauración de estado de UI (checkboxes, inputs de nueva escena, selects de personaje/escena, details y scroll)
- [x] 2.3 Implementar actualización incremental cuando hay un campo en edición o con foco activo para no pisar el trabajo del usuario
- [x] 2.4 Implementar indicador `(N)` en el título de la pestaña en segundo plano y toast discreto de llegada de nuevos archivos
- [x] 2.5 Implementar aviso "Sin conexión con la bandeja" y reintento con backoff exponencial sin encolar peticiones concurrentes

## 3. Pruebas y Validación de Calidad

- [x] 3.1 Implementar tests unitarios para `/api/estado-version`: cambio ante archivos nuevos, estabilidad ante consultas sin cambios, validación de Host y rechazo de POST
- [x] 3.2 Implementar tests para preservación de estado de UI: checkboxes, inputs de escena nueva, dropdowns, details y scroll
- [x] 3.3 Implementar tests para pausas de sondeo con pestaña oculta y modales, y reanudación inmediata en visibilitychange
- [x] 3.4 Implementar tests para indicador `(N)` en título y reintentos con backoff exponencial ante desconexión
- [x] 3.5 Implementar tests para archivos temporales (`.crdownload`, `.part`, `.tmp`) que no generan lotes
- [x] 3.6 Ejecutar suite completa de tests de la bandeja y auditoría AST de Reglas de Oro con 0 infracciones
