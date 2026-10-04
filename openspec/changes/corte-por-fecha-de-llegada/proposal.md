# Proposal: Corte de Reciente por Fecha de Llegada (ctime) y Aviso solo para Lotes Nuevos

## Why

El corte "reciente / anterior" (utilizado para la asignación de archivos al capítulo en foco, la sección "Anteriores" y el límite temporal `horas_material_reciente`) se basaba exclusivamente en el `st_mtime` del archivo. Navegadores como Google Chrome a menudo preservan la fecha original del servidor (`Last-Modified`) al descargar archivos multimedia (por ejemplo, desde Grok o generadores de IA), y copias con `cp -p` o descargas desde teléfonos móviles conservan fechas viejas. Como resultado, un archivo descargado recientemente tras el inicio del capítulo se clasificaba erróneamente en "Anteriores al capítulo" a pesar de haber arribado al disco después de iniciado el capítulo. Asimismo, la notificación de escritorio anunciaba lotes listos para ordenar aun cuando los lotes correspondientes quedaban relegados a "Anteriores" sin visibilidad en la lista principal.

Este cambio resuelve esta discrepancia estableciendo una función unificada de "fecha de llegada" basada en `max(st_mtime, st_ctime)`, asegurando que la ctime del sistema de archivos local capture con precisión cuándo el archivo ingresó al equipo, mostrando dicha fecha en la interfaz, restringiendo las notificaciones únicamente a lotes nuevos de la lista principal, y alineando visualmente el banner del capítulo en foco con la tabla de Capítulos Abiertos.

## What Changes

- **Función unificada de fecha de llegada**:
  - Se define `obtener_fecha_llegada(archivo_o_stat)` que calcula `max(st_mtime, st_ctime)`. Dado que `ctime` se actualiza forzosamente en el kernel al crear, escribir, descargar, copiar o renombrar el archivo en el sistema de archivos y no puede ser manipulada retroactivamente mediante `os.utime`, garantiza que archivos descargados con `Last-Modified` antiguo sean reconocidos como recién llegados.
  - Se utiliza `obtener_fecha_llegada` en todos los cortes temporales:
    1. Comparación con el inicio del capítulo en foco (`ts_corte_capitulo`).
    2. Clasificación a la sección "Anteriores" (destildados y sin escena precargada).
    3. Evaluación de `horas_material_reciente` (corte por antigüedad si está configurado).
    4. Notificaciones de nuevos lotes.
- **Visualización en la tarjeta / tooltip del archivo**:
  - Se expone la `fecha_llegada` en la metadata de cada archivo y se visualiza en el `title` (tooltip) y/o en la tarjeta del archivo en la interfaz de usuario.
- **Preservación del orden y numeración por mtime**:
  - Para agrupar dentro de los lotes y para la numeración correlativa secuencial al renombrar y mover en `simular_movimiento_lote`, se mantiene estrictamente el orden por `mtime` original. No se altera la numeración existente.
- **Aviso de lotes nuevos exclusivo para la lista principal**:
  - La notificación de escritorio (`_notificar_escritorio`) solo cuenta lotes que van a la lista principal de lotes listos para ordenar (`lotes_principales`). Los lotes que quedan en "Anteriores" nunca incrementan el contador ni disparan notificaciones.
- **Banner del capítulo en foco**:
  - El banner del capítulo en foco adopta el mismo estilo visual amarillo con estrella (`⭐ EN FOCO`, badge con `background: #f59e0b; color: #000; font-weight: 700;`) utilizado en la tabla de Capítulos Abiertos, manteniendo el aviso de `(+N abierto(s))` cuando hay múltiples capítulos abiertos.
- **Cumplimiento de Reglas de Oro**:
  - Cero primitivas prohibidas (test AST con 0 infracciones), simulación previa obligatoria y bitácora reversible.

## Capabilities

### New Capabilities
- `corte-por-fecha-de-llegada`: Gestión unificada de fecha de llegada efectiva mediante `max(st_mtime, st_ctime)` para todos los cortes de material reciente vs anterior, conteo selectivo de notificaciones para lotes principales y distintivo visual `⭐ EN FOCO` en el banner.

### Modified Capabilities
<!-- No requirement changes to existing specs -->

## Impact

- **Código**:
  - `bandeja_descargas.py`: Definición de `obtener_fecha_llegada`, integración en `VigilanteBandeja.escanear`, configuración de `horas_material_reciente` en `ConfiguracionBandeja`, renderizado de `fecha_llegada` en UI (tooltips de archivos), notificación filtrada solo para `lotes_principales`, y actualización del banner de capítulo en foco con badge `⭐ EN FOCO`.
  - `config_bandeja.json`: Campo `horas_material_reciente: 0` (soporte opcional para cortes por horas).
- **Seguridad**:
  - Sin uso de primitivas de borrado o sobreescritura (analizador AST 100% limpio).
- **Pruebas**:
  - `test_bandeja_descargas.py`: Suite de tests para fecha de llegada con mtime viejo y ctime nuevo, mtime y ctime anteriores, `horas_material_reciente`, aviso sin conteo de anteriores, max(mtime, ctime), y marca visual de foco en el banner.
