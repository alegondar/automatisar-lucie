# Spec Delta

## Purpose

Permite transferir escenas multimedia clasificadas desde el almacenamiento local hacia un pendrive externo mediante copias atómicas verificadas por hash, preservación no destructiva de originales y reversibilidad completa.

## ADDED Requirements

### Requirement: Pre-chequeos de seguridad y estado del pendrive
El sistema SHALL validar preventivamente que el destino externo sea un punto de montaje válido (`os.path.ismount`), que contenga el directorio base `videos1`, que no se encuentre montado en modo de solo lectura (`os.statvfs` con `ST_RDONLY`), y que cuente con espacio libre suficiente que exceda el tamaño total a copiar más un margen de seguridad de 1 GB. Si cualquiera de estos chequeos no se satisface, el sistema SHALL bloquear la operación de envío informando el motivo exacto.

#### Scenario: Bloqueo cuando el pendrive no está montado o falta videos1
- **WHEN** el usuario consulta el estado de envío y la ruta configurada no es un punto de montaje o no existe el subdirectorio `videos1`
- **THEN** el sistema bloquea las acciones de envío y muestra un mensaje de advertencia indicando que el pendrive no está montado o no tiene la estructura requerida

#### Scenario: Bloqueo cuando el pendrive está montado en solo lectura
- **WHEN** el sistema detecta que el punto de montaje posee el flag `ST_RDONLY` activo
- **THEN** se impide cualquier intento de transferencia y se notifica que el dispositivo externo se encuentra en modo de solo lectura

#### Scenario: Bloqueo por espacio libre insuficiente
- **WHEN** el espacio libre disponible en el pendrive es menor que la suma del tamaño de los archivos a transferir más 1 GB de margen
- **THEN** el sistema rechaza la simulación o ejecución del envío detallando los bytes requeridos y el espacio disponible actual

### Requirement: Simulación previa obligatoria por escena
El sistema SHALL requerir una simulación previa obligatoria antes de iniciar cualquier transferencia hacia el pendrive. Dicha simulación SHALL procesar exclusivamente una escena por vez (prohibiendo envíos masivos no supervisados) y detallar para cada archivo su ruta de origen canónica, destino proyectado en el pendrive, tamaño y estado (`nuevo`, `ya existe idéntico`, `ya existe distinto`).

#### Scenario: Ejecución de simulación previa detallada
- **WHEN** el usuario selecciona una escena clasificada y solicita su simulación previa
- **THEN** el sistema devuelve la lista exhaustiva de archivos a transferir con origen, destino en pendrive, tamaño y estado previsto sin alterar ningún archivo

### Requirement: Copia atómica verificada por hash sin borrado
El sistema SHALL transferir cada archivo nuevo escribiendo en bloques hacia un archivo temporal oculto `.<nombre>.parcial` dentro del directorio destino correspondiente en el pendrive, empleando creación exclusiva en modo binario (`'xb'`) y sincronización forzada a disco (`os.fsync`). Finalizada la escritura, el sistema SHALL recalcular el hash SHA-256 del archivo temporal y compararlo con el del archivo de origen; únicamente si ambos coinciden exactamente, el sistema SHALL renombrar el temporal a su nombre definitivo usando `os.rename`.

#### Scenario: Copia exitosa y verificación de integridad de hash
- **WHEN** se copia un archivo nuevo al pendrive y su hash SHA-256 coincide con el del archivo origen
- **THEN** el archivo temporal `.<nombre>.parcial` se renombra mediante `os.rename` a su nombre final en el pendrive

### Requirement: Manejo de copias fallidas sin destrucción de datos
Si la escritura en el pendrive falla o si el hash SHA-256 del archivo temporal no coincide con el del archivo origen, el sistema SHALL reubicar de inmediato el archivo temporal defectuoso hacia `<raiz_pendrive>/_a_revisar/copias_fallidas/<ruta relativa>` mediante `os.rename`. El sistema SHALL NUNCA invocar primitivas de borrado sobre ningún archivo.

#### Scenario: Detección de corrupción o discrepancia de hash
- **WHEN** el hash SHA-256 del archivo temporal difiere del hash del archivo de origen tras completarse la copia
- **THEN** el sistema mueve el archivo temporal a `_a_revisar/copias_fallidas/` con `os.rename`, registra la anomalía en la bitácora y no lo borra

### Requirement: Resolución de colisiones en pendrive sin pisado destructivo
Antes de transferir un archivo, el sistema SHALL verificar si ya existe un elemento con el mismo nombre en la ruta de destino. Si existe un archivo idéntico con el mismo hash SHA-256, el sistema SHALL omitir la copia y clasificar el archivo como "ya estaba". Si existe un archivo diferente con el mismo nombre, el sistema SHALL conservar el existente intacto y generar un nombre con sufijo numérico correlativo para la nueva copia, alertando al usuario en la bitácora y en la interfaz.

#### Scenario: Archivo idéntico preexistente en destino
- **WHEN** el archivo a copiar ya existe en el pendrive con el mismo tamaño y hash SHA-256
- **THEN** el sistema omite la transferencia y marca el estado como "ya estaba" sin sobrescribir

#### Scenario: Archivo colisionante con contenido diferente
- **WHEN** en el destino existe un archivo con igual nombre pero con diferente hash SHA-256
- **THEN** el nuevo archivo se guarda con sufijo numérico correlativo sin modificar ni sobrescribir el archivo preexistente

### Requirement: Preservación de originales en carpeta de enviados
Una vez que el archivo en el pendrive haya sido verificado y establecido con éxito, el sistema SHALL mover el archivo original desde `~/Descargas/_lucie` hacia `~/Descargas/_lucie/_enviados/<ruta relativa>` mediante `os.rename` dentro del mismo sistema de archivos. Queda terminantemente prohibido eliminar el archivo original del equipo local.

#### Scenario: Reubicación segura a carpeta de enviados
- **WHEN** la transferencia y verificación de un archivo en el pendrive culminan satisfactoriamente
- **THEN** el archivo de origen se reubica con `os.rename` en la subcarpeta `_enviados/` preservando su estructura relativa

### Requirement: Deshacer envío con reversión y preservación auditable
El sistema SHALL proveer una operación de reversión para deshacer envíos realizados. Al solicitar deshacer, el sistema SHALL reubicar la copia alojada en el pendrive hacia `<raiz_pendrive>/_a_revisar/envios_deshechos/<ruta relativa>` y retornar el archivo original desde `_enviados/` a su ubicación original previa con `os.rename`. Si la ruta original se encuentra ocupada o si falta alguno de los archivos, la operación SHALL ser rechazada con un mensaje de conflicto sin alterar el sistema de archivos.

#### Scenario: Reversión completa y exitosa de un envío
- **WHEN** el usuario confirma la acción de deshacer un envío previo
- **THEN** la copia en el pendrive se reubica en `_a_revisar/envios_deshechos/`, el original regresa a su carpeta de escena original mediante `os.rename` y se asienta el evento en la bitácora

#### Scenario: Negativa de reversión si la ruta original está ocupada
- **WHEN** se solicita deshacer un envío pero en la ruta de origen original se encuentra un archivo nuevo
- **THEN** el sistema rechaza la reversión informando que la ruta original está ocupada y mantiene los archivos intactos

### Requirement: Pestaña de envío al pendrive en el panel web local
El servidor web local (`127.0.0.1:8766`) SHALL ofrecer una nueva pestaña interactiva "Envío al pendrive", protegida con validación estricta de encabezado `Host` local y token `X-CSRF-Token`. La pestaña SHALL mostrar el diagnóstico del pendrive (montaje, modo lectura/escritura, espacio libre), un selector de escenas clasificadas pendientes de envío, la vista previa de simulación con confirmación explícita por escena, y la lista de envíos recientes con botón para deshacer.

#### Scenario: Navegación y consulta de escenas para envío
- **WHEN** el usuario accede a la pestaña "Envío al pendrive" con token CSRF válido
- **THEN** la interfaz carga las escenas disponibles en `~/Descargas/_lucie` y el estado en tiempo real del medio externo

### Requirement: Registro persistente y aislamiento en bitácora y SQLite
Cada operación de envío o reversión SHALL quedar registrada en `bitacora_envio.jsonl`. Asimismo, la base de datos SQLite SHALL almacenar el estado `"en_pendrive"` con hash, ruta de destino y marca de tiempo. La bandeja de descargas y el inventario del pendrive SHALL ignorar por completo las carpetas `_enviados` y los archivos temporales `*.parcial`.

#### Scenario: Asentamiento auditable en bitácora y base de datos
- **WHEN** se completa la transferencia de una escena
- **THEN** se registra una entrada con identificador de operación en `bitacora_envio.jsonl` y se actualiza la tabla SQLite con el estado `"en_pendrive"`
