# Spec Delta

## Purpose

Detecta automáticamente nuevo contenido multimedia del proyecto Lucie en `~/Descargas`, agrupándolo en lotes temporales y organizándolo de forma segura por personaje y escena con un clic.

## ADDED Requirements

### Requirement: Lista blanca estricta de selección
El sistema SHALL filtrar archivos de `~/Descargas` mediante una lista blanca estricta, procesando únicamente archivos multimedia con extensiones autorizadas (.mp4, .mov, .webm, .jpg, .jpeg, .png, .webp) que coincidan con patrones del proyecto o carpetas con alias. Cualquier otro archivo o carpeta fuera de la lista blanca no se leerá, no se hasheará ni se registrará.

#### Scenario: Archivo coincidente con patrón Grok
- **WHEN** un archivo `grok-video-12345.mp4` aparece en `~/Descargas`
- **THEN** el sistema lo identifica como candidato de proyecto para procesamiento

#### Scenario: Archivo de imagen Nano Banana
- **WHEN** una imagen `lucie_primer_plano_20261003153000.png` aparece en `~/Descargas`
- **THEN** el sistema valida el patrón de descripción y marca temporal de 14 dígitos, catalogándolo como candidato

#### Scenario: Archivo fuera de la lista blanca
- **WHEN** un archivo `.pdf`, `.zip`, `.exe` u otro archivo no perteneciente a la lista blanca se encuentra en `~/Descargas`
- **THEN** el sistema lo ignora totalmente sin leer su contenido, sin calcular hash ni emitir registro en logs

### Requirement: Detección y omisión de descargas activas e incompletas
El sistema SHALL ignorar archivos temporales con sufijos de descarga (.crdownload, .part, .tmp) y omitir archivos cuyo tamaño en bytes haya variado en una ventana de observación de 5 segundos, procesándolos únicamente cuando la descarga haya finalizado y el tamaño se estabilice.

#### Scenario: Detección de archivo temporal de descarga
- **WHEN** se detecta un archivo con extensión `.crdownload` o `.part`
- **THEN** el sistema lo excluye del procesamiento de candidatos y lotes

#### Scenario: Archivo con tamaño en mutación activa
- **WHEN** un archivo de video está siendo escrito en disco y su tamaño difiere entre lecturas separadas por 5 segundos
- **THEN** el sistema pospone su inclusión en lotes hasta que permanezca estable

### Requirement: Reconocimiento y enrutamiento hacia escenas según tipo de archivo
El sistema SHALL enrutar el destino de los archivos según su tipo: videos (mp4, mov, webm) hacia `<destino>/<personaje>/videos sin editar/<escena>/`, e imágenes (jpg, jpeg, png, webp) hacia `<destino>/<personaje>/<carpeta_imagenes>/<escena>/` (con `carpeta_imagenes` configurable en `config_bandeja.json`, por defecto "imagenes"). Los lotes mixtos se repartirán automáticamente entre ambas carpetas. Si se selecciona una escena existente en `~/Descargas`, los archivos se moverán directamente dentro de ella sin reordenarla ni moverla.

#### Scenario: Detección de carpeta de escena existente
- **WHEN** existe una carpeta `roli parque` en `~/Descargas`
- **THEN** el sistema la reconoce como escena existente para el personaje `roli` y la mantiene intacta en su ubicación original

#### Scenario: Movimiento hacia carpeta de escena existente en Descargas
- **WHEN** el usuario selecciona una escena existente ubicada en `~/Descargas` como destino de un lote
- **THEN** los archivos del lote se mueven directamente al interior de dicha carpeta sin reordenar ni mover la carpeta contenedora

#### Scenario: Enrutamiento diferenciado en lote mixto hacia escena nueva
- **WHEN** un lote contiene videos (ej. `grok-video-1.mp4`) e imágenes (ej. `lucie_20261003120000.png`) para una escena nueva `toma1` del personaje `lucie`
- **THEN** el sistema asigna el video a `<destino>/lucie/videos sin editar/toma1/` y la imagen a `<destino>/lucie/<carpeta_imagenes>/toma1/`, mostrándolo en la simulación previa

### Requirement: Validación estricta de nombres de escena y verificación de destino
El sistema SHALL validar el nombre de cualquier escena y rechazarlo con mensaje claro si contiene "/", "\", "..", caracteres de control, caracteres inválidos en Windows/exFAT (<, >, :, ", |, ?, *), si termina en punto o espacio, si coincide con nombres reservados de Windows (CON, PRN, AUX, NUL, COM1-9, LPT1-9) o si supera 100 caracteres, verificando con realpath que el destino resida dentro de `<destino>` o de la escena existente.

#### Scenario: Rechazo de caracteres inválidos o nombres reservados en escena
- **WHEN** el usuario ingresa un nombre de escena como `escena/toma`, `CON`, `escena.` o con caracteres `< > : " | ? *`
- **THEN** el sistema rechaza la creación con un mensaje de error explicativo en el panel sin ejecutar ninguna acción en disco

#### Scenario: Verificación de confinamiento con realpath
- **WHEN** se genera la ruta de destino de una escena
- **THEN** el sistema confirma mediante `os.path.realpath` que la ruta resultante permanece dentro del directorio base de destino o de la carpeta de escena existente

### Requirement: Pestaña de archivos multimedia sin identificar y memoria de decisiones
El sistema SHALL listar en una pestaña separada aquellos archivos multimedia que no coincidan con patrones conocidos, permitiendo al usuario clasificarlos como pertenecientes al proyecto o ignorados, recordando la decisión en SQLite mediante su hash SHA-256.

#### Scenario: Clasificación manual de archivo sin patrón
- **WHEN** el usuario marca un archivo `video.mp4` como "del proyecto" o "ignorar"
- **THEN** el sistema almacena la decisión indexada por su hash SHA-256 en la base de datos para no volver a preguntar en futuras detecciones

### Requirement: Agrupación en lotes temporales y notificación de escritorio
El sistema SHALL agrupar los candidatos de proyecto en lotes coherentes considerando la proximidad temporal de su fecha de modificación dentro de una ventana configurable (10 minutos por defecto), emitiendo una notificación mediante `notify-send` al detectar un lote listo.

#### Scenario: Agrupación temporal de candidatos
- **WHEN** ingresan 5 archivos con diferencias de mtime menores a 10 minutos entre sí
- **THEN** el sistema los presenta consolidados en un único lote de trabajo

#### Scenario: Emisión de notificación de escritorio
- **WHEN** un nuevo lote de candidatos es detectado y el binario `notify-send` está presente en el sistema
- **THEN** el sistema invoca `notify-send` informando la disponibilidad del nuevo lote

### Requirement: Panel web local con preselección
El sistema SHALL proveer una interfaz web en `127.0.0.1` (puerto configurable, default 8766) con visualización de lotes, selectores de personaje y escena, y preselección automática del personaje del último lote procesado.

#### Scenario: Carga del panel y preselección de personaje
- **WHEN** el usuario abre el panel tras haber movido previamente un lote del personaje `lucie`
- **THEN** el selector de personaje del nuevo lote aparece preseleccionado con `lucie`

### Requirement: Generación segura de miniaturas por identificador de archivo
El endpoint `/api/miniatura` SHALL recibir exclusivamente el identificador de un archivo registrado en la base de datos y nunca una ruta directa del sistema de archivos, e invocar `ffmpeg` mediante `subprocess` con lista de argumentos, sin `shell=True` y anteponiendo `--` antes del nombre de archivo.

#### Scenario: Solicitud de miniatura con identificador registrado
- **WHEN** el cliente solicita `/api/miniatura?id=<archivo_id>` para un archivo registrado en la base SQLite
- **THEN** el servidor resuelve la ruta interna y ejecuta `ffmpeg` de manera segura con lista de argumentos y `--` para generar y responder con la miniatura

#### Scenario: Rechazo de solicitud con parámetro de ruta o id desconocido
- **WHEN** una petición intenta pasar una ruta directa del sistema de archivos o un ID no registrado en la base de datos
- **THEN** el servidor rechaza la petición con código de error HTTP sin invocar `ffmpeg`

### Requirement: Protección anti-CSRF y validación de cabeceras en endpoints mutables
El servidor SHALL generar un token aleatorio criptográficamente seguro al iniciar e inyectarlo en la página. Todos los endpoints POST (`/api/mover-lote`, `/api/deshacer`, `/api/clasificar-sin-identificar`) SHALL exigir dicho token en una cabecera, requerir `Content-Type: application/json` y validar que `Host` sea `127.0.0.1:<puerto>`, respondiendo 403 Forbidden si no se cumplen.

#### Scenario: Petición POST legítima con token y cabeceras válidas
- **WHEN** se envía una petición POST incluyendo el token anti-CSRF correcto, `Content-Type: application/json` y `Host: 127.0.0.1:<puerto>`
- **THEN** el servidor valida las credenciales y procesa la solicitud

#### Scenario: Petición POST rechazada por falta de token o cabecera Host incorrecta
- **WHEN** una petición POST carece del token anti-CSRF, contiene un token inválido o presenta un encabezado `Host` externo
- **THEN** el servidor rechaza inmediatamente la petición con código `403 Forbidden`

### Requirement: Simulación previa obligatoria y movimiento seguro sin pisado
El sistema SHALL presentar una simulación previa obligatoria con las rutas exactas de origen y destino antes de ejecutar cualquier movimiento, realizándolo exclusivamente con `os.rename` dentro de `~/Descargas`, verificando que el destino no exista y agregando sufijo numérico ante colisiones.

#### Scenario: Simulación previa antes de mover
- **WHEN** el usuario hace clic en "Mover seleccionados"
- **THEN** el panel muestra una previsualización de cada archivo seleccionado con su origen y destino final antes de solicitar la confirmación definitiva

#### Scenario: Manejo de colisión en destino
- **WHEN** el destino propuesto ya contiene un archivo con idéntico nombre
- **THEN** el sistema añade un sufijo numérico correlativo ` (1)`, ` (2)` al nombre de destino para evitar cualquier sobrescritura

### Requirement: Confinamiento estricto a ~/Descargas y prohibición de acceso al pendrive
El sistema SHALL validar mediante `os.path.realpath` que todas las rutas de origen y destino pertenezcan estrictamente al subárbol de `~/Descargas`, rechazando cualquier operación que apunte fuera de este límite o intente interactuar con el pendrive.

#### Scenario: Validación de contención de ruta
- **WHEN** se evalúa una ruta de origen o destino
- **THEN** el sistema confirma que su ruta canónica absoluta comienza con el directorio canónico de `~/Descargas`, abortando la acción si no coincide

### Requirement: Bitácora reversible y función de deshacer estricta sin sobrescritura
El sistema SHALL registrar cada operación de lote en un archivo de bitácora `.jsonl` y permitir revertirla con una función de deshacer que use `os.rename`. Si la ruta de origen original se encuentra ocupada por otro archivo, el sistema SHALL rechazar la reversión con un mensaje claro, sin pisar ni sufijar jamás.

#### Scenario: Reversión exitosa de lote con ruta libre
- **WHEN** el usuario solicita deshacer un lote y las rutas de origen originales están desocupadas
- **THEN** el sistema devuelve cada archivo a su ubicación original mediante `os.rename` y asienta la reversión en la bitácora

#### Scenario: Rechazo de deshacer por ruta original ocupada
- **WHEN** se solicita deshacer un movimiento pero el archivo original en la ruta de origen fue recreado o ya existe otro archivo en dicha ubicación
- **THEN** el sistema se niega a realizar la operación, emite un mensaje claro informando el conflicto y no modifica ningún archivo

### Requirement: Selección granular de archivos dentro de un lote en el panel web
El panel web SHALL proporcionar casillas de verificación individuales para cada archivo de un lote (marcadas por defecto), tooltip emergente con nombre completo y fecha/hora al pasar el cursor, botones "Seleccionar todos" y "Ninguno" por lote, y actualizar el botón a "Mover seleccionados (N)", deshabilitándolo si N=0. Los archivos no seleccionados SHALL permanecer en la bandeja como lote pendiente sin perder su agrupamiento.

#### Scenario: Marcado por defecto y tooltip con metadatos
- **WHEN** el usuario visualiza un lote detectado en el panel web
- **THEN** todos los archivos del lote aparecen con su casilla marcada y al pasar el mouse sobre cada tarjeta se muestra un tooltip con el nombre completo y la fecha exacta

#### Scenario: Alternancia de selección masiva en el lote
- **WHEN** el usuario presiona "Ninguno" o "Seleccionar todos" en la cabecera del lote
- **THEN** las casillas de todos los archivos del lote se desmarcan o marcan respectivamente, actualizando inmediatamente el contador en el botón de acción

#### Scenario: Deshabilitación del botón de acción ante selección vacía
- **WHEN** la cantidad N de archivos seleccionados en el lote es igual a cero
- **THEN** el botón muestra "Mover seleccionados (0)" y permanece deshabilitado para evitar peticiones vacías

#### Scenario: Simulación y movimiento exclusivo de archivos seleccionados
- **WHEN** el usuario selecciona un subconjunto de N archivos y pulsa "Mover seleccionados (N)"
- **THEN** la simulación previa y la posterior ejecución mueven únicamente los N archivos seleccionados a la escena elegida

#### Scenario: Retención de archivos no seleccionados en lote pendiente
- **WHEN** se mueve un subconjunto de archivos de un lote
- **THEN** los archivos no seleccionados continúan en `~/Descargas` y se mantienen agrupados como lote pendiente en la bandeja para revisiones futuras

### Requirement: Pestaña de historial y reversión visible en interfaz web
El panel web SHALL incluir una pestaña "Historial" que consuma el endpoint `GET /api/historial` para mostrar los últimos 50 movimientos de `bitacora_bandeja.jsonl` (fecha, archivo, origen anterior, destino nuevo y estado movido/deshecho), disponiendo de un botón "Deshacer" por movimiento y un botón "Deshacer último lote" protegidos por token anti-CSRF, mostrando el mensaje de negativa si la ruta de origen está ocupada.

#### Scenario: Visualización de los últimos 50 movimientos
- **WHEN** el usuario hace clic en la pestaña "Historial"
- **THEN** el panel carga y presenta en una tabla cronológica los últimos 50 movimientos registrados con sus rutas completas y estados

#### Scenario: Reversión individual desde la pestaña de historial
- **WHEN** el usuario presiona "Deshacer" en una fila del historial con estado movido
- **THEN** el cliente web envía una petición POST a `/api/deshacer` con el token anti-CSRF y el identificador de operación, actualizando el estado de la fila al confirmarse

#### Scenario: Reversión masiva del último lote procesado
- **WHEN** el usuario presiona el botón "Deshacer último lote"
- **THEN** el sistema localiza el último lote registrado con movimientos pendientes y ejecuta su reversión completa mediante `/api/deshacer` con token anti-CSRF

#### Scenario: Visualización de error ante ruta original ocupada al deshacer
- **WHEN** el servidor responde conflicto porque la ruta original de un archivo a deshacer se encuentra ocupada
- **THEN** el panel web muestra en pantalla el mensaje explicativo de negativa devuelto por el servidor, sin alterar archivos

### Requirement: Validación previa y mensajes de advertencia en línea para creación de escenas
El panel web SHALL validar de forma anticipada el nombre ingresado al elegir "+ Crear nueva escena", mostrando un mensaje explicativo directamente debajo del campo de texto si está vacío o si contiene caracteres inválidos (<, >, :, ", /, \, |, ?, *, terminación en punto/espacio o nombres reservados), antes de abrir el modal de simulación previa.

#### Scenario: Advertencia ante campo de nombre de escena vacío
- **WHEN** el usuario selecciona "+ Crear nueva escena", deja el campo vacío y presiona el botón de mover
- **THEN** el sistema muestra un mensaje de advertencia debajo del campo indicando que se requiere un nombre y no abre el modal de simulación

#### Scenario: Advertencia ante caracteres prohibidos en nombre de escena
- **WHEN** el usuario escribe un nombre con caracteres prohibidos como `escena/toma` o `toma?`
- **THEN** el sistema visualiza debajo del campo el motivo del rechazo detallando los caracteres no permitidos e impide la apertura del modal

### Requirement: Aviso fijo superior tras mover lote con acción de reversión inmediata
Tras confirmar la operación "Mover seleccionados", el panel web SHALL mostrar un aviso fijo en la parte superior con el texto "Se movieron N archivos a <personaje>/<escena>", un botón "Deshacer" para revertir el lote completo inmediatamente y un botón de cierre. El aviso SHALL permanecer visible hasta que el usuario lo cierre manualmente o mueva otro lote. El movimiento revertido o activo SHALL mantenerse disponible en la pestaña Historial. La reversión SHALL usar el endpoint `/api/deshacer` con token anti-CSRF y, si la ruta original está ocupada, se negará con el mensaje del servidor sin pisar ni sufijar.

#### Scenario: Generación del aviso fijo tras mover lote
- **WHEN** el usuario confirma y ejecuta el movimiento de N archivos hacia una escena
- **THEN** se despliega en la parte superior de la página el banner con el mensaje "Se movieron N archivos a <personaje>/<escena>", el botón "Deshacer" y el botón para cerrar

#### Scenario: Reversión completa desde el botón del aviso
- **WHEN** el usuario pulsa el botón "Deshacer" en el aviso fijo
- **THEN** el sistema envía una petición POST a `/api/deshacer` con el token anti-CSRF y el `id_operacion` correspondiente, restaurando todos los archivos del lote a sus ubicaciones originales y refrescando la vista

#### Scenario: Persistencia del aviso y reemplazo por nuevo lote
- **WHEN** el aviso está visible en pantalla
- **THEN** permanece en su posición hasta que el usuario hace clic en cerrar o hasta que se ejecuta el movimiento de un lote posterior, que reemplaza el aviso con los nuevos datos

#### Scenario: Negativa ante colisión al deshacer desde el aviso
- **WHEN** el usuario pulsa "Deshacer" desde el aviso pero la ruta original de algún archivo fue ocupada externamente
- **THEN** el servidor responde 409 Conflict y el panel muestra el mensaje explicativo de negativa sin sobrescribir ni mutar ningún archivo

