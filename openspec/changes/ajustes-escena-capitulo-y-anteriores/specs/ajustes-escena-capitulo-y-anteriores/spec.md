# Especificación: Ajustes de Escena de Capítulo y Lotes Anteriores

## Requisitos Funcionales

### 1. Creación y Validación de Carpeta al Iniciar o Reabrir Capítulo
- Al invocar `empezar_capitulo` o `/api/capitulos/empezar`, y `reabrir_capitulo` o `/api/capitulos/reabrir`, el sistema debe asegurar la existencia del directorio físico `~/Descargas/_lucie/<personaje>/<nombre>/`.
- Se debe validar previamente el nombre con `ValidadorEscenas.validar_nombre_escena` y verificar que la ruta quede estrictamente confinada dentro de `ruta_destino_base` (rechazando path traversal `..`, separadores absolutos o symlinks externos).
- La creación debe usar `os.makedirs(..., exist_ok=True)` de forma no destructiva e idempotente.
- Si la carpeta ya existía y contiene archivos (ej. de un capítulo previo con el mismo nombre), se debe reutilizar sin tocar ni modificar su contenido, informándolo en la respuesta de la API (`"La carpeta ya existía y tiene N archivos"`).
- Terminar un capítulo (`terminar_capitulo`) nunca borra la carpeta aunque quede vacía.

### 2. Desplegable de Escena con Opción de Capítulo Activo
- En el panel web, para los lotes correspondientes al capítulo activo, la primera opción del desplegable de escena debe ser `[Capítulo activo] <nombre>`, preseleccionada por defecto.
- No se debe duplicar esa misma carpeta bajo la etiqueta `[Destino] <nombre>`.
- Se deben mantener las opciones `+ Crear nueva escena...`, las escenas existentes en Descargas y las demás carpetas de destino.
- Si el usuario modifica el personaje del lote a uno diferente al del capítulo, la simulación previa debe reflejar claramente el nuevo personaje y la nueva ruta resultante.
- "Mover lotes listos" y el movimiento por lote deben utilizar esa escena por defecto sin requerir escribir en el campo de texto.

### 3. Traslado de Carpeta Vacía al Descartar Capítulo
- Al descartar un capítulo (`ejecutar_descartar_capitulo`), si la carpeta existe físicamente (incluso si está vacía, con 0 archivos), se debe mover completa a `_descartados/<personaje>/<escena>_<timestamp>` mediante un único `os.rename`.
- Si la carpeta no existe en disco, se mantiene el comportamiento de marcar el capítulo en base de datos sin ejecutar `os.rename`.
- La operación debe quedar registrada en la bitácora `.jsonl` y poder deshacerse de forma atómica.

### 4. Partición Estricta de Lotes Mixtos y Lotes Anteriores Destildados
- Los archivos con fecha de modificación anterior al inicio del capítulo (`mtime < ts_corte_capitulo`) nunca se consideran recientes.
- Si un conjunto de candidatos contiene archivos anteriores y nuevos (lote mixto), `AgrupadorLotes` debe dividirlos estrictamente en dos lotes independientes.
- Ningún archivo anterior puede compartir lote con material reciente.
- En la interfaz, todos los lotes de la sección "Anteriores al capítulo" y sus archivos deben renderizarse siempre desmarcados (sin atributo `checked`), con el conteo en "0 seleccionados", botón deshabilitado y sin escena preasignada ni preselección por alias o patrones de IA.
