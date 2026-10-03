# Tasks

## 1. Configuración, Lista Blanca y Base de Datos SQLite

- [x] 1.1 Crear `config_bandeja.json` con los patrones de candidatos ("grok-video-*", Nano Banana regex, Flow editable), extensiones de media, rutas y ventanas temporales, verificando su carga con prueba unitaria.
- [x] 1.2 Actualizar `.gitignore` para ignorar archivos `.jsonl` de bitácoras y registros de movimientos, verificando que `git status` no los rastree.
- [x] 1.3 Implementar la capa SQLite en `bandeja_descargas.py` para crear la tabla `bandeja_archivos` (id INTEGER PK, hash TEXT UNIQUE, ruta_actual TEXT, estado TEXT, personaje TEXT, escena TEXT, fecha TEXT) y registrar decisiones de archivos sin patrón, verificando su funcionamiento con tests unitarios.
- [x] 1.4 Implementar `FiltroListaBlanca` en `bandeja_descargas.py` para admitir exclusivamente extensiones multimedia autorizadas y patrones coincidentes, verificando que archivos fuera de la lista blanca (.pdf, .zip, etc.) se descarten sin ser leídos ni hasheados.

## 2. Detección, Estabilidad de Descargas, Agrupación y Validación de Escenas

- [x] 2.1 Implementar `DetectorDescargasActivas` para descartar archivos `.crdownload`, `.part`, `.tmp` y archivos con mutaciones de tamaño en los últimos 5 segundos, verificando la detección de archivos inestables con pruebas unitarias.
- [x] 2.2 Implementar `AgrupadorLotes` para agrupar candidatos estables por cercanía de `mtime` dentro de la ventana configurable de 10 minutos, verificando la partición de lotes con tests unitarios.
- [x] 2.3 Implementar la detección de escenas existentes a partir de carpetas de primer nivel con alias en `~/Descargas` y subcarpetas ya existentes en el destino, verificando que se listen como opciones sin moverlas.
- [x] 2.4 Implementar `ValidadorEscenas` para validar y rechazar nombres con "/", "\", "..", caracteres de control, caracteres inválidos en Windows/exFAT (< > : " | ? *), terminación en punto o espacio, nombres reservados (CON, PRN, AUX, NUL, COM1-9, LPT1-9) o de más de 100 caracteres, y verificar con realpath que el destino final resida dentro de `<destino>`, verificando con tests unitarios.
- [x] 2.5 Implementar la rutina de vigilancia periódica (polling) e integración con `notify-send` si está disponible en el sistema, verificando el flujo de notificación con mocks en tests unitarios.

## 3. Movimiento Seguro, Bitácora y Reversibilidad

- [x] 3.1 Implementar `GestorMovimientosBandeja` con confinamiento estricto de rutas a `~/Descargas` mediante `os.path.realpath`, verificando el rechazo de rutas externas con tests unitarios.
- [x] 3.2 Implementar la simulación previa y resolución de destino: hacia escenas existentes en `~/Descargas` (entran directo a la carpeta sin alterarla) o escenas nuevas (`<destino>/<personaje>/videos sin editar/<escena>/`), aplicando sufijos numéricos correlativos ` (1)`, ` (2)` ante colisiones en el destino inicial.
- [x] 3.3 Implementar la ejecución de movimientos exclusivamente con `os.rename` y el asentamiento en la bitácora `.jsonl`, verificando que el archivo se reubique sin duplicar ni borrar.
- [x] 3.4 Implementar la función de deshacer (undo) con `os.rename`, verificando que si la ruta original ya está ocupada se rechace la operación con mensaje explicativo, sin pisar ni sufijar jamás.

## 4. Servidor HTTP Local, Seguridad CSRF y Panel Web Interactivo

- [x] 4.1 Implementar la generación del token anti-CSRF aleatorio al iniciar el servidor e inyección en la SPA, y el middleware de seguridad que valida cabecera `X-CSRF-Token`, `Content-Type: application/json` y `Host: 127.0.0.1:<puerto>` en todos los endpoints POST, respondiendo 403 Forbidden ante cualquier fallo.
- [x] 4.2 Implementar el endpoint seguro `/api/miniatura` que recibe exclusivamente el `id` numérico de un archivo registrado en la base SQLite (nunca una ruta) e invoca `ffmpeg` con `subprocess.run`, sin `shell=True` y con `--` antes del nombre de archivo.
- [x] 4.3 Implementar los endpoints REST en `bandeja_descargas.py` (`/api/lotes`, `/api/sin-identificar`, `/api/escenas`, `/api/personajes`, `/api/clasificar-sin-identificar`, `/api/simular-mover`, `/api/mover-lote`, `/api/deshacer`), verificando sus respuestas en JSON y códigos de estado.
- [x] 4.4 Desarrollar la interfaz web SPA en tema oscuro con lista de lotes, miniaturas seguras, selectores de personaje y escena (existente o nueva con validación visual), preselección del último personaje utilizado, modal de simulación previa, botón "Mover lote" y pestaña "Sin identificar".

## 5. Pruebas Unitarias, Seguridad AST y Validación

- [x] 5.1 Crear en `test_bandeja_descargas.py` pruebas unitarias en `/tmp` para la validación exhaustiva de nombres de escena (caracteres prohibidos, nombres reservados Windows, trailing dot/space, longitud > 100 y realpath confinada).
- [x] 5.2 Crear en `test_bandeja_descargas.py` pruebas para la protección anti-CSRF, validación de cabeceras Host y Content-Type, verificando que solicitudes POST sin token o con Host foráneo respondan 403 Forbidden.
- [x] 5.3 Crear en `test_bandeja_descargas.py` pruebas para `/api/miniatura` asegurando que rechace rutas directas, solo acepte IDs registrados y construya el comando de `ffmpeg` seguro con `--` y sin shell.
- [x] 5.4 Crear en `test_bandeja_descargas.py` pruebas para el enrutamiento de escenas existentes en Descargas (los archivos entran tal cual a la carpeta sin reordenarla ni moverla) y escenas nuevas en `<destino>`.
- [x] 5.5 Crear en `test_bandeja_descargas.py` pruebas para la función de deshacer, confirmando que si la ruta original está ocupada se rechaza con error claro, sin pisar ni sufijar jamás.
- [x] 5.6 Crear en `test_bandeja_descargas.py` pruebas para la lista blanca, estabilidad de descargas (5s) y agrupación temporal de lotes.
- [x] 5.7 Integrar `bandeja_descargas.py` en la auditoría estática AST anti-borrado de `seguridad_anti_borrado.py`, verificando que mantenga 0 violaciones de las 11 primitivas prohibidas.
- [x] 5.8 Ejecutar la suite completa de pruebas del proyecto (`test_plan_limpieza.py`, `test_inventario.py`, `test_bandeja_descargas.py`) asegurando que pasen al 100%.
