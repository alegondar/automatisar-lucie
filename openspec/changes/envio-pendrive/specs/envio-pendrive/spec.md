# Spec Delta

## Purpose

Permite transferir material clasificado de capítulos desde la sala de espera local hacia una estructura aislada dentro del pendrive, validando identidad mediante marcadores, verificando integridad criptográfica con copias parciales y preservando originales sin borrado.

## ADDED Requirements

### Requirement: Identidad y detección del pendrive por marcador
El sistema SHALL identificar un pendrive válido exclusivamente mediante la presencia de un archivo marcador `.lucie_pendrive.json` en su raíz, el cual contiene un identificador único UUIDv4, fecha de creación y versión de esquema. La detección SHALL implementarse a través de una función `detectar_pendrive()` con soporte multiplataforma para Linux y Windows, así como rutas candidatas configurables. Si el marcador no existe, el sistema SHALL bloquear toda operación de envío.

#### Scenario: Detección exitosa de pendrive vinculado
- **WHEN** un pendrive con el archivo marcador `.lucie_pendrive.json` válido está montado en el sistema
- **THEN** el sistema detecta la unidad, reporta su identificador único, punto de montaje y espacio disponible, habilitando las operaciones de envío

#### Scenario: Bloqueo de envío cuando no existe marcador
- **WHEN** se solicita una operación de envío pero ninguna unidad montada contiene el archivo marcador `.lucie_pendrive.json`
- **THEN** el sistema rechaza la operación e informa que no hay ningún pendrive vinculado conectado

### Requirement: Vinculación de pendrive con simulación previa obligatoria
El sistema SHALL requerir una simulación previa antes de vincular una unidad candidata como pendrive oficial de Lucie. Dicha simulación SHALL mostrar el punto de montaje, sistema de archivos y espacio libre disponible. La creación del marcador `.lucie_pendrive.json` y de la estructura base `LucieSinReglas/` SHALL ejecutarse únicamente tras la confirmación explícita del usuario y SHALL NUNCA sobrescribir un marcador preexistente.

#### Scenario: Simulación previa de vinculación
- **WHEN** el usuario solicita vincular una unidad montada candidata
- **THEN** el sistema presenta los datos de la unidad (punto de montaje, tipo de sistema de archivos, espacio total y libre) sin realizar modificaciones físicas

#### Scenario: Confirmación de vinculación y creación de estructura
- **WHEN** el usuario confirma la vinculación tras revisar la simulación
- **THEN** el sistema genera el marcador con un UUIDv4 nuevo y crea las carpetas base dentro de `LucieSinReglas/` sin alterar el contenido previo de la unidad

#### Scenario: Rechazo de vinculación sobre marcador existente
- **WHEN** se solicita vincular una unidad que ya posee un archivo marcador `.lucie_pendrive.json`
- **THEN** el sistema rechaza la operación y mantiene intacto el marcador existente

### Requirement: Estructura de directorios confinada en el pendrive
El sistema SHALL confinar todas las transferencias de envío dentro del directorio raíz configurado (`LucieSinReglas/`) en el pendrive. Los videos clasificados SHALL transferirse hacia `LucieSinReglas/videos sin editar/<personaje>/<capítulo>/<archivo>` y las fotos hacia `LucieSinReglas/imagenes/<personaje>/<capítulo>/<archivo>`, creando además las carpetas base para `videos ya editados` y `videos completos`. Todo archivo o carpeta fuera de `LucieSinReglas/` SHALL ser de estricta solo lectura.

#### Scenario: Ruteo de videos y fotos a sus carpetas correspondientes
- **WHEN** se envían archivos de un capítulo que contiene tanto videos como fotos
- **THEN** los videos se ubican dentro de `videos sin editar/<personaje>/<capítulo>/` y las fotos dentro de `imagenes/<personaje>/<capítulo>/`

#### Scenario: Preservación de contenido fuera de la estructura confinada
- **WHEN** el pendrive contiene archivos y carpetas preexistentes en su raíz o en otros directorios
- **THEN** ninguna operación de envío escribe, mueve, renombra ni modifica ninguno de esos elementos externos

### Requirement: Plan de envío con simulación previa obligatoria por lote
El sistema SHALL exigir una simulación previa obligatoria antes de transferir archivos al pendrive, ya sea para un capítulo individual o para la totalidad de capítulos pendientes. La simulación SHALL listar de forma exhaustiva cada archivo indicando ruta de origen, destino relativo en pendrive, tamaño en bytes y hash SHA-256, verificando que exista espacio libre suficiente con margen de seguridad. Un único clic de confirmación SHALL aprobar el lote completo.

#### Scenario: Generación de simulación previa detallada
- **WHEN** el usuario solicita simular el envío de un capítulo o de todos los capítulos pendientes
- **THEN** el sistema retorna la lista completa de archivos con sus rutas relativas de destino, tamaños, hashes y balance proyectado de espacio libre sin escribir datos

#### Scenario: Advertencia al simular capítulo abierto
- **WHEN** se solicita la simulación de envío para un capítulo que aún se encuentra abierto en la sala de espera
- **THEN** la simulación incluye una advertencia explícita indicando que el capítulo sigue abierto y podrían ingresar archivos adicionales

#### Scenario: Bloqueo de envío por espacio insuficiente en pendrive
- **WHEN** el espacio libre disponible en el pendrive es inferior al tamaño del lote sumado al margen de seguridad configurado
- **THEN** la simulación bloquea la opción de confirmación y notifica el déficit exacto de almacenamiento

### Requirement: Detección y bloqueo por límite de sistema de archivos FAT32
El sistema SHALL inspeccionar el tipo de sistema de archivos de la unidad montada consultando los registros del sistema operativo (`/proc/mounts` en entornos Linux). Si el sistema de archivos es FAT32 o `vfat`, el sistema SHALL detectar cualquier archivo individual cuyo tamaño exceda los 4 GiB (4.294.967.296 bytes) y SHALL bloquear la ejecución del envío alertando sobre el límite arquitectónico del sistema de archivos.

#### Scenario: Bloqueo preventivo de archivo mayor a 4 GiB en FAT32
- **WHEN** el pendrive tiene formato FAT32/vfat y al menos un archivo del lote a transferir supera los 4 GiB de tamaño
- **THEN** el plan de envío marca el archivo como no transferible, advierte la limitación de FAT32 y bloquea la confirmación del lote

#### Scenario: Aprobación de archivos en FAT32 que no superan 4 GiB
- **WHEN** el pendrive es FAT32/vfat y todos los archivos del lote poseen un tamaño inferior o igual a 4 GiB
- **THEN** la simulación no emite bloqueos de formato y permite proceder con la transferencia

### Requirement: Detección de colisiones case-insensitive y conflictos de hash
La simulación de envío SHALL validar si en el destino proyectado existen colisiones de nombres sin distinguir entre mayúsculas y minúsculas (insensibilidad a mayúsculas propia de FAT/exFAT). Si un archivo ya fue enviado previamente y su hash SHA-256 coincide con el registrado en el manifiesto, SHALL omitirse informando su estado "ya enviado". Si existe un archivo en destino con diferente hash, SHALL marcarse como conflicto y no se copiará ni sufijará a ciegas.

#### Scenario: Omisión de archivo ya enviado previamente con hash idéntico
- **WHEN** un archivo a enviar coincide en ruta relativa y hash SHA-256 con una entrada previa del manifiesto
- **THEN** la simulación reporta el archivo como "ya enviado" y lo excluye de la transferencia física

#### Scenario: Detección y reporte de conflicto ante hash diferente
- **WHEN** en la ruta de destino existe un archivo con idéntico nombre pero diferente hash SHA-256
- **THEN** el sistema marca el archivo en estado de conflicto, bloquea su transferencia y no sobrescribe el archivo existente

### Requirement: Manejo de archivos no multimedia en la raíz del capítulo
El sistema SHALL examinar los archivos presentes en el capítulo. Si se detectan archivos sueltos en la raíz del capítulo cuya extensión no corresponde a formatos multimedia permitidos, el sistema SHALL excluirlos del plan de envío y SHALL emitir una advertencia visible en la simulación previa detallando los archivos no procesados.

#### Scenario: Detección de archivo no multimedia en la raíz del capítulo
- **WHEN** un capítulo contiene un archivo con extensión no multimedia (por ejemplo, un archivo de texto o ejecutable) en su raíz
- **THEN** la simulación excluye el archivo de la lista de copias e incluye una notificación de aviso al usuario

### Requirement: Protocolo de copia atómica segura con archivo parcial y fsync
El sistema SHALL transferir cada archivo nuevo copiándolo en bloques hacia un archivo temporal con extensión `.part` (`<destino>.part`), calculando el hash SHA-256 durante la pasada de copia. Tras completar la escritura, el sistema SHALL forzar la sincronización física a disco mediante `os.fsync` y posteriormente renombrarlo con `os.rename` a su nombre final tras validar que el destino no existe. Finalmente, SHALL releer el archivo destino para verificar que su hash coincide con el origen.

#### Scenario: Copia exitosa y verificación de hash
- **WHEN** se copia un archivo al pendrive, se ejecuta `os.fsync`, se renombra con `os.rename` y su hash verificado coincide con el origen
- **THEN** el archivo queda confirmado en su ubicación definitiva y se procede con la siguiente acción

#### Scenario: Interrupción o fallo durante la copia a archivo parcial
- **WHEN** ocurre una interrupción de E/S, desconexión o discrepancia de hash durante la transferencia
- **THEN** el archivo temporal `.part` permanece visible en el pendrive sin borrarse, el sistema detiene el lote y reporta el incidente en la interfaz

### Requirement: Preservación de originales locales en directorio de enviados
Únicamente después de verificar con éxito la copia del archivo en el pendrive, el sistema SHALL mover el archivo original desde la sala de espera hacia `~/Descargas/_lucie/_enviados/<personaje>/<capítulo>/(fotos|videos)/<archivo>` mediante `os.rename`. Si en el destino ya existe un archivo con dicho nombre, SHALL asignarse un sufijo numérico correlativo sin pisar. La carpeta `_enviados` SHALL NUNCA ser leída como capítulo ni ofrecida como escena.

#### Scenario: Reubicación de original verificado a carpeta de enviados
- **WHEN** un archivo culmina exitosamente su copia y verificación en el pendrive
- **THEN** el archivo original en la sala de espera se reubica con `os.rename` a `_enviados/` manteniendo la jerarquía de subcarpetas

#### Scenario: Aislamiento de la carpeta de enviados en la sala de espera
- **WHEN** el sistema lista los capítulos y escenas disponibles para clasificación o envío
- **THEN** la carpeta `_enviados` es ignorada y ningún archivo contenido en ella se interpreta como escena activa

### Requirement: Manifiesto append-only en pendrive y bitácora local
El sistema SHALL registrar cada transferencia confirmada agregando una línea JSON en `<pendrive>/LucieSinReglas/.lucie/manifiesto.jsonl`. El archivo de manifiesto SHALL abrirse exclusivamente en modo de anexado (`'a'`) y contendrá los campos: `id_envio`, `fecha`, `equipo`, `pendrive_id`, `personaje`, `capitulo`, `tipo`, `nombre`, `ruta_relativa`, `sha256`, `bytes` y `estado` ("enviado"). Asimismo, SHALL registrar el evento `"envio_pendrive"` en la bitácora local `bitacora_bandeja.jsonl`.

#### Scenario: Registro append-only al completar un envío
- **WHEN** se confirma y finaliza el envío de un archivo hacia el pendrive
- **THEN** se añade una nueva línea al archivo `manifiesto.jsonl` del pendrive y se asienta el evento `"envio_pendrive"` en `bitacora_bandeja.jsonl` sin reescribir contenido previo

### Requirement: Reversión de envío sin borrado hacia directorio de revertidos
El sistema SHALL proporcionar la capacidad de deshacer una operación de envío individual o por lote. Al revertir, el sistema SHALL mover la copia alojada en el pendrive hacia `<pendrive>/LucieSinReglas/_revertidos/<id_envio>/<ruta_relativa>` con `os.rename` y restituir el archivo original desde `_enviados/` a su ubicación en la sala de espera con `os.rename`. Si la ruta original en la sala de espera está ocupada, la reversión SHALL ser rechazada sin alterar ningún archivo.

#### Scenario: Reversión exitosa de un envío
- **WHEN** el usuario ejecuta la acción de deshacer un envío y la ruta en la sala de espera se encuentra libre
- **THEN** la copia en el pendrive se traslada a `_revertidos/`, el archivo original regresa a la sala de espera y se registran los eventos `"envio_revertido"` en el manifiesto y la bitácora

#### Scenario: Rechazo de reversión por colisión en sala de espera
- **WHEN** se intenta revertir un envío pero en la ruta de la sala de espera existe un archivo nuevo con el mismo nombre
- **THEN** el sistema rechaza la reversión, mantiene los archivos en sus ubicaciones y emite un mensaje de error explicativo

### Requirement: Detección automática en segundo plano y notificación en panel
El componente vigilante en segundo plano (`VigilanteBandeja`) SHALL comprobar periódicamente si el pendrive vinculado se encuentra conectado al sistema. Al detectarlo, el sistema SHALL exponer en el estado de la aplicación una notificación de alerta indicando la cantidad de archivos y capítulos listos para transferir con un acceso directo al plan de envío, sin iniciar ninguna transferencia automática.

#### Scenario: Detección de pendrive y activación de banner
- **WHEN** el vigilante detecta la conexión del pendrive vinculado con material pendiente en la sala de espera
- **THEN** la interfaz muestra un banner informativo con el total de archivos y capítulos listos para enviar junto a un botón para ver el plan

#### Scenario: Detección de desconexión del pendrive
- **WHEN** un pendrive previamente conectado es retirado o deja de estar montado
- **THEN** el sistema actualiza de inmediato el estado del pendrive a desconectado y deshabilita los controles de envío

### Requirement: Pestaña y controles de pendrive en la interfaz de usuario
La aplicación web SHALL ofrecer una pestaña "Pendrive" que exhiba el estado de conexión del dispositivo, identificador de pendrive, sistema de archivos, espacio libre, botón para vincular unidades, lista de capítulos con archivos pendientes, botones "Enviar al pendrive" por capítulo y "Enviar todos", historial de envíos con opción de deshacer y panel de archivos `.part` incompletos. Asimismo, SHALL incluir botones de envío en cada fila de capítulo y en el banner del capítulo en foco.

#### Scenario: Visualización del panel de pendrive
- **WHEN** el usuario ingresa a la pestaña "Pendrive" con el dispositivo conectado
- **THEN** el panel muestra la información de la unidad, el listado de capítulos disponibles con conteo de archivos y las opciones de simulación y envío

#### Scenario: Visualización y control de archivos temporales huérfanos
- **WHEN** existen archivos con extensión `.part` resultantes de fallos o desconexiones previas
- **THEN** la interfaz lista los archivos temporales detectados para conocimiento del usuario sin eliminarlos automáticamente

### Requirement: Endpoints de API seguros con validación de CSRF y Host
El servidor HTTP local SHALL exponer los endpoints `GET /api/pendrive/estado`, `POST /api/pendrive/vincular-simular`, `POST /api/pendrive/vincular`, `POST /api/pendrive/envio-simular`, `POST /api/pendrive/envio` y la extensión de `POST /api/deshacer`. Todos los métodos POST SHALL validar estrictamente la presencia y exactitud del token `X-CSRF-Token`, la cabecera `Host` autorizada y el tipo de contenido `application/json`.

#### Scenario: Rechazo de petición sin token CSRF
- **WHEN** se envía una petición POST a cualquiera de los endpoints de pendrive sin la cabecera `X-CSRF-Token` válida
- **THEN** el servidor responde con código HTTP 403 Forbidden y un mensaje de rechazo de seguridad

#### Scenario: Rechazo de petición con cabecera Host externa
- **WHEN** se envía una petición con un encabezado `Host` distinto a `127.0.0.1` o `localhost` en el puerto autorizado
- **THEN** el servidor rechaza la solicitud protegiendo la API contra accesos indebidos

### Requirement: Confinamiento canónico y exclusión de directorios reservados
El sistema SHALL verificar mediante resolución canónica (`os.path.realpath`) que cualquier ruta de lectura permanezca dentro de los límites de la sala de espera y que cualquier ruta de escritura en el pendrive resuelva estrictamente dentro de `LucieSinReglas/` (a excepción del marcador `.lucie_pendrive.json`). Si una ruta contiene secuencias de escape de directorio (`..`) o enlaces simbólicos dirigidos al exterior, la operación SHALL ser abortada. Asimismo, los directorios `_enviados` y `_revertidos` SHALL NUNCA ser interpretados como escenas.

#### Scenario: Rechazo de ruta con path traversal
- **WHEN** se solicita procesar un capítulo cuyo nombre o ruta incluye secuencias de navegación como `../` o caracteres fuera de la raíz permitida
- **THEN** el sistema lanza un error de confinamiento de seguridad y deniega la operación

#### Scenario: Ignorado estricto de carpetas reservadas
- **WHEN** el motor de escaneo de capítulos analiza el directorio base
- **THEN** las carpetas `_enviados`, `_revertidos`, `_descartados` y `_a_revisar` son completamente omitidas de los listados operativos

### Requirement: Monitoreo no bloqueante del pendrive con tiempo límite y resiliencia ante bloqueos
La detección y cualquier lectura del pendrive (búsqueda de marcador, `/proc/mounts`, cálculo de espacio libre o inspección de archivos) SHALL ejecutarse fuera del hilo que atiende las solicitudes HTTP del panel, con un tiempo límite estricto de 3 segundos. Si el pendrive o el medio físico se cuelga o no responde dentro de dicho lapso, el servidor SHALL continuar respondiendo normalmente y el estado del pendrive SHALL reportar "Pendrive sin respuesta" sin bloquear la interfaz.

#### Scenario: Lectura del pendrive que excede el tiempo límite
- **WHEN** la unidad del pendrive se bloquea o demora más de 3 segundos en responder a lecturas de disco o espacio
- **THEN** el hilo de consulta aborta la espera por timeout, el panel web sigue activo y muestra el estado "Pendrive sin respuesta"

#### Scenario: Lectura del pendrive en tiempo normal
- **WHEN** la unidad del pendrive responde dentro del límite de 3 segundos
- **THEN** el sistema actualiza normalmente los datos de montaje, identidad y espacio libre en el panel

