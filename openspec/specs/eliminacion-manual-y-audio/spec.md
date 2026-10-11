# Eliminación manual del pendrive y audio MP3

## Requirements

### Requirement: Eliminación manual con simulación y confirmación
El dashboard SHALL permitir seleccionar carpetas de capítulos, otras carpetas y archivos dentro de la raíz del pendrive vinculado. El servidor SHALL emitir un plan privado de un solo uso con vencimiento de cinco minutos; solo una confirmación explícita ELIMINAR, protegida por Host y CSRF, SHALL ejecutar el plan almacenado. La UI SHALL mostrar cada elemento y advertir que el borrado permanente no permite deshacer.

#### Scenario: Cancelación
- WHEN el usuario cancela la vista previa
- THEN no se elimina ningún elemento.

#### Scenario: Cambio de contenido o de unidad
- WHEN cambia la identidad de la unidad, la raíz o la huella de la selección
- THEN se rechaza la ejecución y se solicita una nueva simulación.

### Requirement: Confinamiento y registro
La eliminación SHALL rechazar la raíz, metadatos ocultos, rutas absolutas, traversal, enlaces y junctions. Se SHALL registrar antes de borrar y después de cada eliminación en .lucie/eliminaciones.jsonl, sin editar el manifiesto previo. Se SHALL detener ante el primer error y mostrar el resultado parcial. Envío, reversión y borrado SHALL compartir exclusión mutua.

### Requirement: Excepción AST acotada
El analizador SHALL admitir exclusivamente os.unlink(ruta) y os.rmdir(ruta) dentro de GestorEliminacionPendrive.ejecutar en bandeja/eliminacion.py. El resto de primitivas y ámbitos SHALL permanecer prohibidos.

### Requirement: MP3 en lotes y envío
El filtro SHALL reconocer .mp3 sin distinción de mayúsculas. Los alias conocidos y el capítulo en foco SHALL incorporarlos a lotes; los desconocidos SHALL permitir adopción manual desde Sin identificar. El traslado SHALL usar audios/ conservando nombres y evitando colisiones. El envío SHALL copiar audios al pendrive con las verificaciones de hash existentes.

### Requirement: Navegación de carpetas del proyecto
La sección SHALL mostrar la ruta de la raíz del proyecto vinculado, carpetas y archivos multimedia del nivel actual y navegación interna por subcarpetas. No SHALL mostrar un árbol completo del pendrive. SHALL permitir seleccionar individualmente videos, imágenes y MP3 dentro del proyecto. La selección por casillas SHALL conservarse al navegar; el botón Eliminar seleccionados SHALL permanecer visible y habilitarse cuando exista selección, abriendo la simulación antes de la confirmación.

### Requirement: Vista previa de archivos seleccionables
La UI SHALL mostrar imágenes con miniatura ampliable, videos con fotograma y controles y MP3 con icono y reproducción. Los recursos SHALL servirse mediante identificadores opacos a través del endpoint multimedia con validación de raíces. El video SHALL cargar al acercarse al viewport; el audio SHALL usar preload none. La reproducción SHALL detenerse al navegar a otra carpeta o pestaña. La previsualización no SHALL modificar la selección ni el archivo.

#### Scenario: Eliminación de archivos individuales
- WHEN el usuario confirma una selección de archivos multimedia
- THEN se eliminan solo esos archivos, conservando la carpeta, los archivos no seleccionados y los metadatos.
