# Proposal

## Why

El flujo creativo del proyecto Lucie produce constantemente nuevos archivos multimedia generados con herramientas externas (videos de Grok, imágenes de Nano Banana, secuencias de Flow, etc.) que se descargan directamente en `~/Descargas`. En la actualidad, estos archivos quedan mezclados con descargas personales de diversa índole, requiriendo revisión manual para identificar qué pertenece al proyecto, agrupar archivos que corresponden a una misma toma y moverlos a la estructura organizada por personaje y escena.

Este cambio introduce y perfecciona la capacidad **`bandeja-descargas`**: un sistema local, liviano y seguro que vigila de forma no invasiva `~/Descargas`, detecta automáticamente el contenido del proyecto mediante una lista blanca estricta, lo agrupa en lotes por proximidad temporal y permite organizarlo con un clic en la carpeta correspondiente de personaje y escena, reflejando fielmente la estructura del pendrive sin tocar el pendrive físico. El presente ajuste incorpora mejoras ergonómicas esenciales en el panel web: selección granular de archivos dentro de cada lote, historial y reversión visibles con un clic, y validación contextual anticipada de nombres de escena.

## What Changes

- **Lista blanca estricta (Whitelist)**:
  - Lo que no califica en la lista blanca **no se lee, no se hashea, no se registra y no aparece en ningún log ni pantalla**.
  - **Candidatos de proyecto**: Archivos multimedia (`.mp4`, `.mov`, `.webm`, `.jpg`, `.jpeg`, `.png`, `.webp`) cuyo nombre coincida con patrones configurados en `config_bandeja.json`:
    - `"grok-video-*"`
    - Nano Banana: `<descripcion>_AAAAMMDDHHMMSS.<ext>` (patrón regex con marca temporal de 14 dígitos).
    - Flow: patrón editable en `config_bandeja.json` (vacío por defecto).
  - **Detección de escenas existentes**: Carpetas de primer nivel en `~/Descargas` cuyo nombre empiece con un alias de `alias-personajes.json` (`lucie`, `roli`, `laroli`, `magui`, `mailen`). Se registran como escenas utilizables y **NUNCA se mueven ni se tocan**.
  - **Pestaña "Sin identificar"**: Archivos multimedia sin patrón conocido (ej: `video.mp4`, `video (2).mp4`) para que el usuario decida si son "del proyecto" o "ignorar". La decisión se persiste por hash SHA-256 en la base SQLite.
  - **Exclusión total**: Cualquier otra extensión o carpeta fuera de la lista blanca es completamente ignorada.

- **Detección de descargas en curso**:
  - Filtro automático para omitir archivos temporales (`.crdownload`, `.part`, `.tmp`).
  - Verificación de estabilidad temporal: se ignoran archivos cuyo tamaño en bytes haya cambiado en los últimos 5 segundos.

- **Agrupación en lotes y vigilancia continua**:
  - Agrupación automática de candidatos en lotes basados en proximidad de fecha de modificación (`mtime`) con ventana configurable (10 minutos por defecto).
  - Vigilancia en segundo plano mediante sondeo (*polling*) ligero de intervalos periódicos en Python estándar, sin añadir librerías externas.
  - Notificaciones de escritorio vía `notify-send` (invocado solo si está disponible en el sistema) al detectar la llegada de un nuevo lote.

- **Selección granular de archivos dentro de un lote (Nuevo)**:
  - Cada archivo del lote dispone de una casilla de verificación individual, marcada por defecto.
  - Al pasar el cursor sobre la tarjeta del archivo, se despliega un tooltip con el nombre completo y la fecha/hora exacta.
  - Botones dedicados "Seleccionar todos" y "Ninguno" por lote para alternar la selección rápidamente.
  - El botón de acción se actualiza dinámicamente a "Mover seleccionados (N)" y se deshabilita si N = 0.
  - La simulación previa obligatoria muestra **exclusivamente** los archivos seleccionados, detallando origen y destino exactos.
  - Los archivos no seleccionados permanecen en la bandeja como lote pendiente, conservando su agrupamiento temporal para procesamientos posteriores.

- **Historial y reversión visibles (Nuevo)**:
  - Nueva pestaña "Historial" en el panel web que consulta y lista los últimos 50 movimientos registrados en la bitácora `.jsonl`.
  - Columnas detalladas: fecha, archivo, origen anterior, destino nuevo y estado del movimiento (movido / deshecho).
  - Botón individual "Deshacer" para cada operación registrada, enviando el token anti-CSRF al endpoint `/api/deshacer`.
  - Botón global "Deshacer último lote" para revertir en un solo paso la última operación realizada.
  - Negativa estricta sin sobrescritura: si la ruta de origen original ya se encuentra ocupada, se visualiza el mensaje de error explicativo devuelto por el servidor (Regla de Oro #1 y #4).
  - Endpoint `GET /api/historial` para servir la lectura estructurada de la bitácora.

- **Validación anticipada y mensajes claros en escenas (Nuevo)**:
  - Si el usuario selecciona "+ Crear nueva escena", la validación se dispara localmente en tiempo real.
  - Si el nombre está vacío o contiene caracteres inválidos / prohibidos, se visualiza un mensaje de advertencia específico directamente debajo del campo de texto, impidiendo la apertura del modal de simulación hasta que se subsane.

- **Estructura de destino e integridad de movimiento**:
  - Espejo de la jerarquía del pendrive: `<destino>/<personaje>/videos sin editar/<escena>/` para videos y `<destino>/<personaje>/<carpeta_imagenes>/<escena>/` para imágenes.
  - Destino configurable (por defecto `~/Descargas/_lucie`).
  - **Ámbito exclusivo**: Este módulo **únicamente mueve archivos dentro de `~/Descargas`**; no tiene acceso ni realiza operaciones sobre el pendrive.
  - Movimiento atómico mediante `os.rename` (mismo sistema de archivos), prohibiendo terminantemente `shutil.move` y `os.replace`.
  - Verificación previa de colisiones en destino: si el destino ya existe, se asigna un sufijo numérico incremental ` (1)`, ` (2)`.
  - Confinamiento estricto de rutas a `~/Descargas` mediante `os.path.realpath`.

- **Bitácora reversible y registro**:
  - Registro auditable en archivo `.jsonl` para cada lote movido, con función para **deshacer** (revertir movimientos mediante `os.rename`, jamás borrar nada).
  - Extensión de la base SQLite con la tabla `bandeja_archivos` (hash SHA-256, ruta actual, estado, personaje, escena, fecha).
  - Inclusión de archivos de bitácora `.jsonl` en `.gitignore`.

- **Seguridad y tests**:
  - Verificación estática AST anti-borrado (`seguridad_anti_borrado.py`) garantizando 0 infracciones de las 11 primitivas prohibidas.
  - Pruebas unitarias ampliadas (`test_bandeja_descargas.py`) sobre estructuras temporales en `/tmp`, cubriendo selección parcial, retención de pendientes, historial, protección CSRF y negativa de deshacer con colisión de ruta.

## Capabilities

### New Capabilities
- `bandeja-descargas`: Detección automática, agrupación en lotes, selección granular de archivos, panel web reactivo con historial/deshacer y organización segura por personaje y escena de nuevo contenido multimedia en `~/Descargas`.

### Modified Capabilities
*(Ninguna)*

## Impact

- **Módulos afectados**:
  - `bandeja_descargas.py`: Servidor HTTP, nuevo endpoint `GET /api/historial`, lógica de subconjunto de lotes en simulación y ejecución, interfaz SPA con casillas de verificación, tooltips, pestaña de historial y validación en línea de escenas.
  - `test_bandeja_descargas.py`: Incorporación de pruebas para mover subconjunto con retención de pendientes, lectura de historial desde bitácora, validación anti-CSRF en `/api/deshacer` y negativa al deshacer con ruta original ocupada.
- **Seguridad**: Se mantiene intacta la prohibición absoluta de borrado y pisado; el análisis AST sigue en 0 violaciones.
