# Tasks

## 1. Configuración, Detección de Pendrive y Marcador de Identidad

- [x] 1.1 Actualizar `config_bandeja.json` y la clase `ConfiguracionBandeja` en `bandeja_descargas.py` para incluir `"carpeta_raiz_pendrive": "LucieSinReglas"` y `"rutas_candidatas_pendrive": []`, verificando la carga correcta mediante tests unitarios en `test_envio_pendrive.py`.
- [x] 1.2 Implementar la función `detectar_pendrive()` en `bandeja_descargas.py` con estrategia según `os.name`: en Linux inspeccionar puntos de montaje en `/media/<usuario>/*` y `/run/media/<usuario>/*` (usando `MIUNIDAD` solo como pista) buscando `.lucie_pendrive.json`; en Windows buscar por letras de unidad `A:` a `Z:`; y soportar `rutas_candidatas_pendrive` para inyección de paths en tests. Verificar con pruebas unitarias que detecte pendrives con marcador y devuelva `None` si no existe marcador.
- [x] 1.3 Implementar validadores para el marcador `.lucie_pendrive.json` (`id` como UUIDv4, `creado` en formato ISO, `version: 1`), verificando que se rechacen archivos corruptos o de versiones incompatibles mediante tests unitarios.

## 2. Vinculación de Pendrive con Simulación Previa

- [x] 2.1 Implementar la función de simulación de vinculación que inspecciona una unidad montada candidata (punto de montaje, tipo de sistema de archivos, espacio total y libre), verificando mediante tests unitarios que reporte los metadatos sin escribir ningún archivo en el disco.
- [x] 2.2 Implementar la función de vinculación definitiva que crea el marcador `.lucie_pendrive.json` con modo exclusivo (`'xb'`) y la estructura base de directorios en el pendrive (`LucieSinReglas/videos sin editar`, `LucieSinReglas/videos ya editados`, `LucieSinReglas/videos completos`, `LucieSinReglas/imagenes`, `LucieSinReglas/.lucie`), verificando con tests unitarios que se niegue a sobrescribir un marcador existente.
- [x] 2.3 Exponer y proteger los endpoints `POST /api/pendrive/vincular-simular` y `POST /api/pendrive/vincular` en `bandeja_descargas.py`, validando token anti-CSRF, cabecera `Host` y `Content-Type: application/json`, comprobando su respuesta mediante tests de integración HTTP.

## 3. Motor de Simulación de Envío (Espacio, FAT32, Colisiones y Conflictos)

- [x] 3.1 Implementar la función `simular_envio_capitulos()` en `bandeja_descargas.py` para listar de forma exhaustiva cada archivo a transferir (por capítulo o para todos los pendientes), calculando ruta de origen, destino relativo en pendrive, tamaño y hash SHA-256, verificando con tests unitarios.
- [x] 3.2 Implementar la inspección del sistema de archivos mediante `/proc/mounts` (o simulación multiplataforma) para detectar particiones FAT32/vfat, alertando y bloqueando preventivamente cualquier archivo individual superior a 4 GiB, verificando con tests unitarios con archivos simulados >4 GiB.
- [x] 3.3 Implementar la validación de espacio libre con margen de seguridad (`margen_libre_bytes`), verificando que la simulación bloquee la confirmación cuando el espacio disponible sea insuficiente.
- [x] 3.4 Implementar la detección de colisiones case-insensitive y deduplicación: si un archivo ya figura en el manifiesto con idéntico SHA-256 se marca "ya enviado" y se omite; si en destino existe un archivo con diferente SHA-256 se marca "conflicto" y se bloquea la copia sin pisar ni sufijar a ciegas, verificando con tests unitarios.
- [x] 3.5 Implementar el filtrado de archivos no multimedia en la raíz del capítulo, omitiéndolos de la lista de transferencias y emitiendo una advertencia explícita en la simulación, verificando con tests unitarios.
- [x] 3.6 Exponer y proteger el endpoint `POST /api/pendrive/envio-simular` en `bandeja_descargas.py`, verificando con tests de integración HTTP que devuelva el plan de envío completo y advierta si el capítulo sigue abierto.

## 4. Protocolo de Copia Segura con `.part`, fsync y Preservación en `_enviados`

- [x] 4.1 Implementar la rutina de transferencia física segura: copia en bloques binarios hacia `<destino>.part` calculando SHA-256 en la misma pasada, llamada forzada a `os.fsync` y posterior renombrado con `os.rename` a su nombre final tras comprobar ausencia de colisión previa, verificando la integridad con tests unitarios.
- [x] 4.2 Implementar la verificación post-copia: relectura del archivo en su ubicación final en el pendrive para comparar su SHA-256 contra el origen; si ocurre una falla o discrepancia, el archivo `.part` no se elimina y el lote se interrumpe inmediatamente, verificando con tests unitarios.
- [x] 4.3 Implementar la preservación del archivo original local: únicamente tras la confirmación exitosa de la copia en el pendrive, el archivo en la sala de espera se mueve con `os.rename` a `~/Descargas/_lucie/_enviados/<personaje>/<capítulo>/(fotos|videos)/<archivo>`, asignando sufijo numérico correlativo si ya existiera en `_enviados`, verificando con tests unitarios.
- [x] 4.4 Exponer y proteger el endpoint `POST /api/pendrive/envio` en `bandeja_descargas.py` para procesar el lote completo aprobado en un solo clic, verificando mediante tests de integración HTTP que se ejecute la transferencia de forma atómica y auditable.

## 5. Manifiesto Append-Only y Mecanismo de Deshacer hacia `_revertidos`

- [x] 5.1 Implementar el registro de eventos en `<pendrive>/LucieSinReglas/.lucie/manifiesto.jsonl` abierto exclusivamente en modo append (`'a'`) con todos los campos requeridos (`id_envio`, `fecha`, `equipo`, `pendrive_id`, `personaje`, `capitulo`, `tipo`, `nombre`, `ruta_relativa`, `sha256`, `bytes`, `estado: enviado`), verificando con tests unitarios que nunca se reescriba el archivo.
- [x] 5.2 Registrar simultáneamente el evento `"envio_pendrive"` en la bitácora local reversible `bitacora_bandeja.jsonl`, verificando su asentamiento mediante tests unitarios.
- [x] 5.3 Implementar la función de deshacer envío: reubicar la copia del pendrive a `<pendrive>/LucieSinReglas/_revertidos/<id_envio>/<ruta_relativa>` con `os.rename`, devolver el original desde `_enviados` a su posición original en la sala de espera con `os.rename`, y registrar el evento `"envio_revertido"` en el manifiesto y en la bitácora, verificando la reversión completa con tests unitarios.
- [x] 5.4 Implementar la comprobación de ocupación en la sala de espera al revertir: si la ruta de destino original se encuentra ocupada por un archivo nuevo, la operación de deshacer se niega estrictamente sin modificar ningún archivo, verificando el rechazo con tests unitarios.
- [x] 5.5 Extender el endpoint `POST /api/deshacer` para soportar la reversión de operaciones de tipo `"envio_pendrive"`, verificando su funcionamiento con tests de integración HTTP.

## 6. Vigilante Automático, Banner Reactivo y Estado de API

- [x] 6.1 Extender `VigilanteBandeja` en `bandeja_descargas.py` para verificar periódicamente (cada 5 segundos) la presencia del pendrive vinculado y calcular la cantidad de archivos y capítulos listos para transferir sin ejecutar transferencias automáticas, verificando con tests unitarios.
- [x] 6.2 Exponer el endpoint `GET /api/pendrive/estado` que reporta el estado de conexión del pendrive (conectado/desconectado, identificador, punto de montaje, sistema de archivos, espacio libre) y la presencia de archivos `.part` incompletos, ejecutando toda lectura del pendrive fuera del hilo HTTP principal con límite de 3 segundos y reportando "Pendrive sin respuesta" si no responde, verificando con tests de integración HTTP.
- [x] 6.3 Implementar en el estado devuelto por el servidor la información para disparar el banner reactivo: `"Pendrive detectado: N archivos de M capítulos listos para enviar [Ver plan]"`, verificando con tests unitarios.

## 7. Interfaz de Usuario (Pestaña "Pendrive" y Botones en Capítulos)

- [x] 7.1 Implementar la pestaña "Pendrive" en la SPA de `bandeja_descargas.py` con tarjeta de estado físico (montaje, ID, filesystem, espacio libre), botón "Vincular pendrive" si falta el marcador, listado de capítulos con archivos pendientes de envío y botones "Enviar al pendrive" individual y "Enviar todos", historial de envíos recientes con botón "Deshacer", y tabla de archivos `.part` incompletos.
- [x] 7.2 Agregar el botón "Enviar al pendrive" en la fila de cada capítulo (tanto abiertos como cerrados) y en el banner del capítulo en foco, integrando el modal de simulación previa que advierte si el capítulo sigue abierto, verificando mediante inspección del HTML/JS embebido.
- [x] 7.3 Implementar el modal interactivo de plan de envío y el banner reactivo de pendrive detectado con enlace directo para revisar y confirmar el plan en un solo clic, verificando la renderización de los componentes visuales.

## 8. Confinamiento Canónico, Suite de Tests Integral y Auditoría AST Anti-Borrado

- [x] 8.1 Implementar el confinamiento estricto con `os.path.realpath` para asegurar que ninguna escritura escape de `LucieSinReglas/` y que ninguna lectura escape de `~/Descargas/_lucie/`, y actualizar `es_carpeta_escena_existente` y `validar_nombre_escena` para excluir estrictamente `_enviados` y `_revertidos` como escenas o capítulos, verificando con tests de path traversal y symlinks maliciosos.
- [x] 8.2 Crear `test_envio_pendrive.py` agrupando todos los casos de prueba con pendrives simulados en `/tmp` (sin marcador no envía, vincular no sobrescribe, creación de carpetas editadas y completas vacías al vincular, archivos preexistentes intactos, ruteo a videos sin editar/imagenes, FAT32 >4 GiB, colisión case-insensitive, omisión con aviso 'ya enviado', copia parcial `.part`, listado de `.part` huérfanos en panel, lectura colgada que activa 'Pendrive sin respuesta', preservación en `_enviados`, manifiesto append-only, deshacer a `_revertidos`, banner reactivo y seguridad CSRF/Host).
- [x] 8.3 Ejecutar la auditoría estática AST anti-borrado (`python3 seguridad_anti_borrado.py`) sobre todo el repositorio, comprobando que se mantengan exactamente 0 violaciones de las 11 primitivas prohibidas.
- [x] 8.4 Ejecutar la suite completa de pruebas unitarias del proyecto (`python3 -m unittest discover -s . -p "test_*.py"`), verificando que el 100% de los tests concluyan exitosamente.

