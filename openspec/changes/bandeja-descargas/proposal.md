# Proposal

## Why

El flujo creativo del proyecto Lucie produce constantemente nuevos archivos multimedia generados con herramientas externas (videos de Grok, imágenes de Nano Banana, secuencias de Flow, etc.) que se descargan directamente en `~/Descargas`. En la actualidad, estos archivos quedan mezclados con descargas personales de diversa índole, requiriendo revisión manual para identificar qué pertenece al proyecto, agrupar archivos que corresponden a una misma toma y moverlos a la estructura organizada por personaje y escena.

Este cambio introduce la capacidad **`bandeja-descargas`**: un sistema local, liviano y seguro que vigila de forma no invasiva `~/Descargas`, detecta automáticamente el contenido del proyecto mediante una lista blanca estricta, lo agrupa en lotes por proximidad temporal y permite organizarlo con un clic en la carpeta correspondiente de personaje y escena, reflejando fielmente la estructura del pendrive sin tocar el pendrive físico.

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

- **Panel web local interactivo**:
  - Servidor HTTP local en `127.0.0.1`, con puerto configurable por línea de comandos (por defecto `8766`, evitando el puerto `8000` de Portainer y el `8765` del dashboard de auditoría).
  - Vista de lotes con miniaturas (extracción de cuadro con `ffmpeg` si se encuentra instalado, o fallback genérico).
  - Selectores desplegables:
    - Selector de personaje (`lucie`, `roli`, `mailen`, etc.).
    - Selector de escena: lista escenas existentes (carpetas con alias en Descargas y subcarpetas ya creadas en destino) o permite crear una nueva con texto libre.
  - Preselección automática del personaje utilizado en el último lote procesado.
  - **Simulación previa obligatoria**: Visualización detallada de origen y destino exactos de cada archivo antes de autorizar el movimiento (cumplimiento estricto de la Regla de Oro #2).
  - Botón de acción explícita "Mover lote".

- **Estructura de destino e integridad de movimiento**:
  - Espejo de la jerarquía del pendrive: `<destino>/<personaje>/videos sin editar/<escena>/`.
  - Destino configurable (por defecto `~/Descargas/_lucie`).
  - **Ámbito exclusivo**: Este módulo **únicamente mueve archivos dentro de `~/Descargas`**; no tiene acceso ni realiza operaciones sobre el pendrive.
  - Movimiento atómico mediante `os.rename` (mismo sistema de archivos), prohibiendo terminantemente `shutil.move` y `os.replace`.
  - Verificación previa de colisiones en destino: si el destino ya existe, se asigna un sufijo numérico incremental ` (1)`, ` (2)`.
  - Confinamiento estricto de rutas a `~/Descargas` mediante `os.path.realpath`.

- **Bitácora reversible y registro**:
  - Registro auditable en archivo `.jsonl` para cada lote movido, con función para **deshacer** (revertir movimientos mediante `os.rename`, jamás borrar nada).
  - Extensión de la caché SQLite con una nueva tabla `bandeja_archivos` (hash SHA-256, ruta actual, estado, personaje, escena, fecha).
  - Inclusión de archivos de bitácora `.jsonl` en `.gitignore`.

- **Seguridad y tests**:
  - Verificación estática AST anti-borrado (`seguridad_anti_borrado.py`) con 0 infracciones de las 11 primitivas prohibidas.
  - Suite de pruebas unitarias (`test_bandeja_descargas.py`) sobre estructuras simuladas en `/tmp`.

## Capabilities

### New Capabilities
- `bandeja-descargas`: Detección automática, agrupación en lotes y organización por personaje y escena de nuevo contenido multimedia en `~/Descargas`.

### Modified Capabilities
*(Ninguna)*

## Impact

- **Nuevos módulos**:
  - `bandeja_descargas.py`: Núcleo de detección, agrupación de lotes, servidor HTTP local y operaciones seguras de movimiento.
  - `config_bandeja.json`: Archivo de configuración de patrones, rutas, tiempos y destino.
  - `test_bandeja_descargas.py`: Pruebas unitarias completas.
- **Base de datos**: Nueva tabla `bandeja_archivos` en `.cache/inventario_pendrive_cache.sqlite`.
- **Configuración de repositorio**: Actualización de `.gitignore` para omitir bitácoras `.jsonl`.
- **Compatibilidad**: No altera el funcionamiento del pendrive ni de los scripts de inventario y limpieza existentes. Cumple 100% las Reglas de Oro.
