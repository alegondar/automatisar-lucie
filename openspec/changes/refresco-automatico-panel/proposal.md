# Proposal: Refresco Automático del Panel y Detección sin Demora

## Why

El panel web (`127.0.0.1:8766`) no se actualiza de forma automática: cuando un archivo nuevo se descarga en `~/Descargas`, queda registrado en la base de datos (por ejemplo, en estado `clasificado` asociado al capítulo en foco), pero no se refleja en la sección de Lotes Detectados hasta que el usuario oprime manualmente el botón "Refrescar". Además, se observó una brecha de 3 minutos entre la creación/modificación del archivo y su registro en la base de datos debido a la falta de trazabilidad en el ciclo de vida del archivo (descarga temporal `.crdownload`, ventana de estabilidad e intervalos de escaneo).

Este cambio introduce un mecanismo de refresco automático reactivo y no destructivo mediante un endpoint liviano de versionado (`GET /api/estado-version`), consulta periódica en segundo plano respetando pausas por visibilidad o modales abiertos, actualización incremental que preserva intacto el trabajo del usuario (selecciones, texto ingresado, menús desplegables y scroll), indicadores de nuevos lotes en segundo plano y desconexión, y optimización con logging estructurado de tiempos de detección para que los archivos estables aparezcan en menos de ~10 segundos.

## What Changes

- **Endpoint de versión liviano `GET /api/estado-version`**:
  - Calcula y devuelve un token de versión representativo del estado que afecta a la vista:
    - Lotes principales y lotes anteriores.
    - Conteo de archivos sin identificar.
    - Capítulos abiertos, cerrados y descartados.
    - Capítulo en foco actual.
    - Balance de pendientes y movidos.
    - Alerta de capítulo olvidado.
  - No reescanea el disco innecesariamente si no hubo cambios de estado.
  - Valida estrictamente la cabecera `Host` (permitiendo solo `127.0.0.1` o `localhost`) y no acepta el método `POST` (responde `405 Method Not Allowed`).
- **Ciclo de consulta en el Frontend (`config_bandeja.json`)**:
  - Parámetro configurable `"refresco_panel_segundos": 4` (0 para desactivar).
  - Consulta periódica a `/api/estado-version`. Solo si el token cambia, se solicitan los datos completos y se redibuja la vista.
- **Pausas inteligentes de sondeo**:
  - Se detiene la consulta cuando la pestaña está oculta (`document.hidden`).
  - Al recuperar el foco (`visibilitychange`), se dispara una consulta inmediata.
  - Se suspende la consulta mientras haya un diálogo modal abierto (simulación de movimiento, descartar capítulo, terminar capítulo).
- **Preservación estricta del trabajo del usuario**:
  - Al redibujar la interfaz:
    - Conserva el estado tildado o destildado de los checkboxes de archivos existentes.
    - Conserva el texto ingresado en los campos de "Nombre de escena nueva".
    - Conserva la selección actual en los selectores desplegables de personaje y escena.
    - Conserva el estado desplegado o colapsado del `<details>` "Anteriores al capítulo".
    - Conserva la pestaña activa y la posición vertical del scroll (`window.scrollY`).
  - Los archivos nuevos se incorporan con su estado predeterminado (tildados si corresponden al capítulo en foco reciente).
- **Actualización incremental en edición activa**:
  - Si el usuario tiene el foco o texto sin enviar en algún campo de edición de un lote, se insertan los nuevos lotes sin destruir ni reinstanciar los componentes existentes.
- **Indicadores visuales de actividad y conectividad**:
  - Notificación en el título de la pestaña: antepone `(N)` al título (ej. `(1) Bandeja de Descargas`) si se detectan nuevos lotes mientras la pestaña está oculta, y lo restablece al regresar.
  - Aviso discreto en el panel ("Llegaron N archivo(s) nuevo(s)") que se disuelve automáticamente.
  - Indicador flotante "Sin conexión con la bandeja" ante fallos de red con reintentos mediante retroceso exponencial (backoff) sin acumulación de peticiones asíncronas.
  - Conservación del botón manual "Refrescar" como respaldo funcional.
- **Detección rápida y trazabilidad con logs estructurados**:
  - Registro de auditoría con marcas de tiempo explícitas: `[DETECTADO]`, `[ESTABLE]` y `[REGISTRADO]`.
  - Garantía de que los temporales de descarga (`.crdownload`, `.part`, `.tmp`) sean ignorados de inmediato sin generar lotes.
  - Explicación fundamentada de la demora observada y verificación de que carpetas como `lucieoloraculo` no sean creadas por el sistema ni colisionen con capítulos de escena.
- **Conformidad con Reglas de Oro**:
  - Simulación previa obligatoria mantenida para cualquier movimiento.
  - Cero infracciones en auditoría AST contra primitivas de borrado o sobreescritura.

## Capabilities

### New Capabilities
- `refresco-automatico-panel`: Sincronización automática periódica del panel web basada en versión de estado, preservación de interacciones del usuario en el cliente, temporización de detección con registro de eventos y trazabilidad del ciclo de vida de los archivos.

### Modified Capabilities
<!-- No requirement changes to existing specs -->

## Impact

- **Código**:
  - `bandeja_descargas.py`: Implementación de ruta `GET /api/estado-version`, validación de `Host`, manejo de métodos HTTP en handlers, lógica de sondeo `setInterval` / `visibilitychange` en el cliente JavaScript, funciones de captura y restauración de estado de UI (checkboxes, inputs, selects, details, scroll), banner toast de nuevos archivos, indicador de desconexión con backoff, y logging estructurado de detección.
  - `config_bandeja.json`: Inclusión de `"refresco_panel_segundos": 4`.
- **Seguridad**:
  - Endpoints de consulta GET confinados y validados por `Host`. No se permiten acciones de modificación de archivos sin simulación previa ni token CSRF.
- **Pruebas**:
  - `test_bandeja_descargas.py`: Cobertura exhaustiva de `/api/estado-version`, validación de Host, rechazo de POST, temporales ignorados, estabilidad de detección, y simulación de cliente para preservación de estado de UI y pausas de visibilidad.
