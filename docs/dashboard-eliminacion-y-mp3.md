# Eliminación manual y audio MP3

## Uso del dashboard

En «Eliminar capítulos» se navega exclusivamente dentro de `LucieSinReglas`
del pendrive vinculado. Las casillas permiten elegir carpetas o archivos de
video, imagen y MP3; la selección se conserva al abrir subcarpetas.
«Eliminar seleccionados» abre una revisión con el inventario exacto. Escribir
`ELIMINAR` y confirmar ejecuta un borrado permanente, sin opción de deshacer.
Cancelar la revisión no modifica archivos.

Las imágenes tienen miniatura ampliable, los videos fotograma y controles,
y los MP3 reproducción de audio. La compatibilidad de reproducción depende
del navegador y del códec del archivo.

## Seguridad

No existe borrado automático. La excepción manual requiere confirmación,
CSRF, un plan privado de un solo uso con vencimiento de cinco minutos y
revalidación de identidad, contenido y ubicación. Se protegen la raíz,
los metadatos ocultos y las rutas que atraviesan enlaces o junctions.
Envío, reversión y eliminación comparten un bloqueo exclusivo.

La bitácora `.lucie/eliminaciones.jsonl` registra el plan antes de ejecutarlo
y cada eliminación realizada. Ante un error se detiene la operación y se
informa el resultado parcial. El manifiesto existente no se modifica.
El analizador AST permite únicamente las dos llamadas del método manual
`GestorEliminacionPendrive.ejecutar`; el resto sigue prohibido.

## MP3 en lotes

Los MP3 se detectan sin distinguir mayúsculas. Con alias conocido o capítulo
en foco se incorporan a lotes; los desconocidos se adoptan desde «Sin
identificar». Se organizan en `audios/` conservando nombres y evitando
colisiones. El envío usa `audios/<personaje>/<capítulo>/` y verifica SHA-256.

## Validación y limitaciones

Se añadieron pruebas de listado, eliminación individual y de carpetas,
confirmación, caducidad, cambios de contenido e identidad, confinamiento,
registro, exclusión mutua, CSRF y detección/transferencia de MP3.
Las pruebas usan directorios temporales. La comprobación en Chromium con
MP4, PNG y MP3 temporales confirmó las vistas previas y ambos tipos de borrado.
No se accedió al pendrive, Downloads ni CapCut reales durante estas pruebas.

La suite Linux anterior a la publicación pasó 294 pruebas con cuatro
saltados correspondientes a Windows nativo; la auditoría AST dio cero
infracciones. Windows nativo no se verificó en este host Linux. El manifiesto
`E:\LucieSinReglas\.lucie\manifiesto.jsonl` no está disponible aquí: los
recuentos anterior y posterior no están disponibles, no son cero.

**Incidencia pendiente:** el usuario informó que una carpeta real aparece
vacía en el dashboard. Se confirmó que el proceso sirve la interfaz actual
desde este repositorio y las pruebas temporales sí muestran archivos.
Falta un nombre completo de archivo y su ubicación para reproducir el caso;
su causa raíz no está confirmada y no se considera solucionada.
