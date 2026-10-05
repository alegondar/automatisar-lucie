# Proposal: preseleccion-reciente-y-seleccion-global

## Why

En modo de respaldo (sin capítulo en foco), todos los lotes de `~/Descargas` se presentan actualmente con todos sus archivos preseleccionados y con escenas precargadas automáticamente por alias, incluso si fueron descargados semanas atrás. Esto incrementa el riesgo de mover accidentalmente material antiguo o no revisado. Adicionalmente, faltan botones de selección global para gestionar múltiples lotes ágilmente, el mensaje de error de escena vacía aparece prematuramente al cargar la vista, y los archivos duplicados (ya movidos o ya enviados) no están identificados visualmente.

## What Changes

- **Ventana de material reciente por defecto**: Se actualiza el valor por defecto de `horas_material_reciente` a 168 horas (7 días). Un valor de 0 continúa significando "criterio desactivado" (retrocompatibilidad).
- **Corte de material reciente en modo respaldo**: Cuando no hay capítulo en foco, los archivos cuya fecha de llegada (`obtener_fecha_llegada`) sea anterior a `ahora - horas_material_reciente * 3600` se segregan a la sección colapsada "Anteriores" (`<details>` cerrado), con checkboxes destildados, sin escena precargada y excluidos de "Mover lotes listos". Cuando hay capítulo en foco, se mantiene inalterado el corte estricto por `fecha_inicio` del capítulo.
- **Partición estricta de lotes mixtos**: Si un lote contiene archivos recientes y antiguos, se divide en dos lotes independientes para evitar contaminación.
- **Exclusión en "Mover lotes listos"**: Dicho botón solo procesa lotes recientes con escena válida, preservando la simulación previa obligatoria y confirmación modal.
- **Encabezado contextual de "Anteriores"**: Muestra el total de lotes anteriores y el texto `Material de más de N horas: revisá antes de mover`.
- **Botones globales de selección**: En la cabecera de la sección de lotes principales, junto a "Mover lotes listos", se incorporan los botones `Seleccionar todo`, `Ninguno` y un contador reactivo `X archivos seleccionados de Y` que actualiza los checkboxes de cada archivo, el checkbox maestro y el contador de cada lote sin afectar "Anteriores" ni alterar la persistencia de estado ante refrescos automáticos.
- **Validación visual diferida de escena**: El mensaje de error `"El nombre de la escena no puede estar vacío"` se oculta en la carga inicial y solo se muestra cuando el usuario abandona el campo vacío (`blur`) o intenta mover el lote.
- **Detección e insignia de archivos duplicados**: Los archivos cuyo SHA-256 coincide con otro archivo listado, un archivo ya movido en la base de datos o un archivo registrado en el manifiesto del pendrive se marcan con una insignia `"Duplicado"`, quedan destildados por defecto y detallan con cuál archivo coinciden. El cómputo de hash se realiza en segundo plano sin bloquear el servidor web.

## Capabilities

### New Capabilities
- `preseleccion-reciente-y-seleccion-global`: Reglas de preselección de material reciente, segregación en "Anteriores", botones globales de selección, validación diferida de escenas y detección no bloqueante de duplicados con insignia explicativa.

### Modified Capabilities
<!-- No modified capabilities -->

## Impact

- **Configuración**: `bandeja/config.py` y `config_bandeja.json` actualizan el valor por defecto de `horas_material_reciente` a 168.
- **Vigilante y agrupación**: `bandeja/vigilante.py` aplica el corte de 168 horas en ausencia de capítulo activo, detecta duplicados vía base de datos SQLite y manifiesto del pendrive, y asegura la división de lotes en `bandeja/lotes.py`.
- **Frontend SPA**: `bandeja/web/panel.html`, `bandeja/web/panel.js` y `bandeja/web/panel.css` añaden la barra de selección global, insignia de duplicados, validación de escena en `blur`/intento de mover, y encabezado dinámico de anteriores.
- **Pruebas unitarias**: `test_bandeja_descargas.py` incorpora casos de prueba para corte reciente vs anterior, partición mixta, botones globales, duplicados y preservación del comportamiento con capítulo en foco.
