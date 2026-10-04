# Tasks

## 1. Configuración, Pre-chequeos del Pendrive y Entorno

- [ ] 1.1 Crear `config_envio.json` con los parámetros por defecto (`ruta_origen_base`: `~/Descargas/_lucie`, `raiz_pendrive`: `/run/media/<usuario>/<pendrive>`, `subcarpeta_videos`: `videos1`, `carpeta_imagenes`: `imagenes`, `margen_libre_bytes`: 1073741824, `tamanio_buffer`: 1048576) y verificar su carga con pruebas unitarias en `test_envio_pendrive.py`.
- [ ] 1.2 Actualizar `.gitignore` para ignorar `bitacora_envio.jsonl` y registros de transferencia temporales, verificando que `git status` no los rastree.
- [ ] 1.3 Implementar `VerificadorPendrive` en `envio_pendrive.py` con métodos para comprobar que la raíz sea un punto de montaje (`os.path.ismount`), que exista la subcarpeta base `videos1`, que no esté montado en solo lectura (`os.statvfs` con `ST_RDONLY`), y que el espacio disponible supere los bytes requeridos más 1 GB de margen, verificando con pruebas unitarias en `/tmp`.

## 2. Motor de Simulación, Copia Atómica Verificada y Preservación de Originales

- [ ] 2.1 Implementar `GestorEnvioPendrive.simular_envio_escena` en `envio_pendrive.py` para listar de forma estricta los archivos de una única escena clasificada, calculando su origen canónico, destino proyectado en el pendrive según tipo (`videos sin editar` o `imagenes`), tamaño y estado (`nuevo`, `ya_estaba`, `colision_distinto`), verificando con tests unitarios.
- [ ] 2.2 Implementar en `GestorEnvioPendrive` la rutina de copia atómica en bloques hacia un archivo temporal oculto `.<nombre>.parcial` en la carpeta destino con modo exclusivo (`'xb'`), sincronización forzada (`os.fsync`) y comparación de hash SHA-256 contra el origen antes de renombrar a nombre final con `os.rename`, verificando la integridad con tests unitarios.
- [ ] 2.3 Implementar el desvío preventivo de archivos corruptos o con discrepancia de hash hacia `<raiz_pendrive>/_a_revisar/copias_fallidas/<ruta relativa>` con `os.rename`, verificando que jamás se invoquen funciones de borrado.
- [ ] 2.4 Implementar la resolución de colisiones en destino: si el archivo existente tiene idéntico hash se marca "ya estaba" y se omite la copia; si tiene hash distinto, se asigna un sufijo numérico correlativo sin pisar el existente, verificando con tests unitarios.
- [ ] 2.5 Implementar la reubicación del archivo original local verificado hacia `~/Descargas/_lucie/_enviados/<ruta relativa>` mediante `os.rename` dentro del mismo sistema de archivos, verificando que el original se preserve íntegramente.

## 3. Reversibilidad (Deshacer Envío) y Registro Persistente

- [ ] 3.1 Implementar el registro estructurado de eventos de envío y reversión en `bitacora_envio.jsonl`, verificando que cada operación genere un registro auditable con identificador único, rutas y hashes.
- [ ] 3.2 Ampliar la capa SQLite en `GestorBaseDatosBandeja` para admitir y consultar el estado `"en_pendrive"` con hash, ruta de destino y marca de tiempo, verificando con pruebas unitarias.
- [ ] 3.3 Implementar `GestorEnvioPendrive.deshacer_envio` para reubicar la copia en el pendrive hacia `<raiz_pendrive>/_a_revisar/envios_deshechos/<ruta relativa>` y retornar el archivo original desde `_enviados` a su carpeta original mediante `os.rename`, verificando la reversión con tests unitarios.
- [ ] 3.4 Implementar la validación y rechazo estricto de la reversión si la ruta original en `~/Descargas/_lucie` ya se encuentra ocupada por otro archivo o si falta alguno de los elementos, verificando que responda con error descriptivo y sin modificar ningún archivo.

## 4. Endpoints HTTP y Confinamiento de Seguridad

- [ ] 4.1 Extender `HandlerServidorBandeja` en `bandeja_descargas.py` para exponer los endpoints `/api/envio/estado-pendrive`, `/api/envio/escenas-disponibles`, `/api/envio/simular`, `/api/envio/ejecutar`, `/api/envio/historial` y `/api/envio/deshacer`, aplicando validación de token anti-CSRF (`X-CSRF-Token`), cabecera `Host` local y `Content-Type: application/json`.
- [ ] 4.2 Actualizar `FiltroListaBlanca` en `bandeja_descargas.py` e `inventario_pendrive.py` para ignorar explícitamente cualquier directorio llamado `_enviados` y archivos con extensión `.parcial`, verificando con tests unitarios.
- [ ] 4.3 Aplicar confinamiento canónico con `os.path.realpath` en todas las rutas de origen y destino de envío para asegurar que no se acceda a directorios externos ni mediante secuencias `..`, verificando el rechazo de accesos no autorizados.

## 5. Panel Web Interactivo (Pestaña "Envío al pendrive")

- [ ] 5.1 Agregar la pestaña "Envío al pendrive" en la barra de navegación superior de la SPA embebida de `bandeja_descargas.py`.
- [ ] 5.2 Implementar en la SPA la tarjeta de diagnóstico del pendrive mostrando estado de montaje, advertencia si está en solo lectura, espacio libre disponible y margen de seguridad requerido.
- [ ] 5.3 Implementar el selector de personajes y escenas disponibles en `_lucie`, vista de archivos de la escena seleccionada, botón "Simular envío", modal de simulación previa detallada y botón de ejecución con confirmación explícita.
- [ ] 5.4 Implementar la sección de historial de envíos recientes en la pestaña con botón "Deshacer" para cada operación, capturando errores de conflicto (como ruta ocupada) y mostrándolos en avisos claros.

## 6. Pruebas Unitarias Integrales y Auditoría AST

- [ ] 6.1 Crear `test_envio_pendrive.py` con una suite de pruebas unitarias sobre un pendrive simulado en `/tmp`, cubriendo: copia verificada correcta, desvío de hash fallido a `copias_fallidas`, no sobreescritura ante archivos existentes, aborto preventivo ante espacio insuficiente (+1GB margen), aborto ante sistema de archivos en solo lectura, reubicación del original a `_enviados` y reversión completa con deshacer.
- [ ] 6.2 Integrar `envio_pendrive.py` en la auditoría estática AST anti-borrado de `seguridad_anti_borrado.py`, verificando que mantenga 0 violaciones de las 11 primitivas prohibidas.
- [ ] 6.3 Ejecutar la suite completa de pruebas unitarias (`python3 -m unittest discover -s . -p "test_*.py"`) asegurando el 100% de pruebas exitosas.
