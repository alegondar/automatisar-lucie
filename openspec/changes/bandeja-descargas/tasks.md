# Tasks

## 1. Configuración, Lista Blanca y Base de Datos SQLite

- [ ] 1.1 Crear `config_bandeja.json` con los patrones de candidatos ("grok-video-*", Nano Banana regex, Flow editable), extensiones de media, rutas y ventanas temporales, verificando su carga con prueba unitaria.
- [ ] 1.2 Actualizar `.gitignore` para ignorar archivos `.jsonl` de bitácoras y registros de movimientos, verificando que `git status` no los rastree.
- [ ] 1.3 Implementar la capa SQLite en `bandeja_descargas.py` para crear la tabla `bandeja_archivos` (hash, ruta_actual, estado, personaje, escena, fecha) y registrar decisiones de archivos sin patrón, verificando su funcionamiento con tests unitarios.
- [ ] 1.4 Implementar `FiltroListaBlanca` en `bandeja_descargas.py` para admitir exclusivamente extensiones multimedia autorizadas y patrones coincidentes, verificando que archivos fuera de la lista blanca (.pdf, .zip, etc.) se descarten sin ser leídos ni hasheados.

## 2. Detección, Estabilidad de Descargas y Agrupación de Lotes

- [ ] 2.1 Implementar `DetectorDescargasActivas` para descartar archivos `.crdownload`, `.part`, `.tmp` y archivos con mutaciones de tamaño en los últimos 5 segundos, verificando la detección de archivos inestables con pruebas unitarias.
- [ ] 2.2 Implementar `AgrupadorLotes` para agrupar candidatos estables por cercanía de `mtime` dentro de la ventana configurable de 10 minutos, verificando la partición de lotes con tests unitarios.
- [ ] 2.3 Implementar la detección de escenas existentes a partir de carpetas de primer nivel con alias en `~/Descargas` y subcarpetas ya existentes en el destino, verificando que no se proponga su movimiento.
- [ ] 2.4 Implementar la rutina de vigilancia periódica (polling) e integración con `notify-send` si está disponible en el sistema, verificando el flujo de notificación con mocks en tests unitarios.

## 3. Movimiento Seguro, Bitácora y Reversibilidad

- [ ] 3.1 Implementar `GestorMovimientosBandeja` con confinamiento estricto de rutas a `~/Descargas` mediante `os.path.realpath`, verificando el rechazo de rutas externas con tests unitarios.
- [ ] 3.2 Implementar la simulación previa que calcula los destinos exactos `<destino_base>/<personaje>/videos sin editar/<escena>/` y resuelve colisiones mediante sufijos numéricos correlativos ` (1)`, ` (2)`.
- [ ] 3.3 Implementar la ejecución de movimientos exclusivamente con `os.rename` y el asentamiento en la bitácora `.jsonl`, verificando que el archivo se reubique sin duplicar ni borrar.
- [ ] 3.4 Implementar la función de deshacer (undo) que revierte los movimientos de un lote usando `os.rename` hacia su origen anterior, verificando la restauración completa sin pérdida ni borrado.

## 4. Servidor HTTP Local y Panel Web Interactivo

- [ ] 4.1 Implementar los endpoints REST en `bandeja_descargas.py` (`/api/lotes`, `/api/sin-identificar`, `/api/escenas`, `/api/personajes`, `/api/clasificar-sin-identificar`, `/api/simular-mover`, `/api/mover-lote`, `/api/deshacer`, `/api/miniatura`), verificando sus respuestas en JSON.
- [ ] 4.2 Implementar la generación de miniaturas con `ffmpeg` (segundo 1) y fallback para imágenes o entornos sin `ffmpeg`, verificando el servicio correcto del fotograma.
- [ ] 4.3 Desarrollar la interfaz web SPA en tema oscuro con lista de lotes, miniaturas, selectores de personaje y escena (existente o nueva), preselección del último personaje utilizado, modal de simulación previa y botón "Mover lote".
- [ ] 4.4 Desarrollar la pestaña "Sin identificar" en la SPA para clasificar archivos multimedia sin patrón ("del proyecto" o "ignorar") y persistir la memoria por hash SHA-256 en SQLite.

## 5. Pruebas Unitarias, Seguridad AST y Validación

- [ ] 5.1 Crear la suite `test_bandeja_descargas.py` cubriendo la lista blanca, estabilidad de descargas, agrupación de lotes, colisiones, movimientos con `os.rename` y función deshacer en `/tmp`.
- [ ] 5.2 Integrar `bandeja_descargas.py` en la auditoría estática AST anti-borrado de `seguridad_anti_borrado.py`, verificando que mantenga 0 violaciones de las 11 primitivas prohibidas.
- [ ] 5.3 Ejecutar la suite completa de pruebas del proyecto (`test_plan_limpieza.py`, `test_inventario.py`, `test_bandeja_descargas.py`) asegurando que pasen al 100%.
