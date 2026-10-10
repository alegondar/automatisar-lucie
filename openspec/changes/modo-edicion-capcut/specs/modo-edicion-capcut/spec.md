# Spec Delta

## Purpose

Permite gestionar el ciclo de posproducción con CapCut: agrupar clips en sesiones de edición, monitorear exportaciones sin alterar el directorio de CapCut, copiar videos finales a 'videos completos' con verificación de integridad y trasladar crudos a 'videos ya editados' de forma reversible.

## ADDED Requirements

### Requirement: Creación y gestión de sesiones de edición
El sistema SHALL permitir agrupar uno o más clips crudos en una sesión de edición con identificador único, nombre editable y cálculo automático del nombre del video final (`<capítulo>videocompleto` o `<clip>videocompleto`).

#### Scenario: Creación de sesión con múltiples clips de un capítulo
- **WHEN** el usuario selecciona varios clips de un mismo capítulo y pulsa "Voy a editar estos"
- **THEN** el sistema crea una sesión en estado "en_edicion" con nombre por defecto `<capítulo>videocompleto` sin mover ningún archivo físico en el pendrive

#### Scenario: Creación de sesión con un solo clip
- **WHEN** el usuario selecciona un único clip y pulsa "Voy a editar estos"
- **THEN** el sistema crea una sesión con nombre por defecto `<nombre_del_clip>videocompleto`

#### Scenario: Cancelación de sesión abierta
- **WHEN** el usuario cancela una sesión abierta
- **THEN** la sesión se cierra y los clips vuelven al listado "Para editar" sin haber alterado el disco

### Requirement: Vista de tres secciones en la pestaña Edición
El sistema SHALL calcular en tiempo real desde el sistema de archivos del pendrive y su manifiesto tres secciones: "Para editar", "En edición" y "Editados y completos", incluyendo contadores por capítulo y reproducción vía streaming seguro.

#### Scenario: Carga dinámica del estado desde el pendrive
- **WHEN** el usuario accede a la pestaña "Edición" con el pendrive vinculado
- **THEN** el sistema inspecciona las carpetas del pendrive en un hilo con timeout de 3 segundos y presenta los clips clasificados en las tres secciones con sus respectivos contadores

#### Scenario: Vista previa de clip del pendrive
- **WHEN** el usuario solicita previsualizar un clip listado en la pestaña Edición
- **THEN** el endpoint `/api/media` sirve el contenido mediante streaming con HTTP Range requests, validando que la ruta resida estrictamente dentro de la raíz permitida del pendrive vinculado

### Requirement: Transición segura de crudos a videos ya editados
El sistema SHALL trasladar los archivos crudos de una sesión desde `videos sin editar` a `videos ya editados` usando `os.rename` dentro del mismo pendrive, verificando que el destino no exista y registrando los eventos en el manifiesto y bitácora.

#### Scenario: Finalización de edición exitosa
- **WHEN** el usuario pulsa "Terminé de editar" en una sesión
- **THEN** el sistema mueve cada clip a `videos ya editados/<personaje>/<capítulo>/<nombre>`, verifica que el destino esté libre, agrega el evento `editado` al manifiesto y permite deshacer la acción

#### Scenario: Conflicto por destino ocupado con distinto hash
- **WHEN** se intenta mover un crudo cuyo destino en `videos ya editados` ya existe con un hash diferente
- **THEN** el sistema detiene el movimiento de dicho archivo, marca un conflicto explícito y no sobrescribe el archivo existente

#### Scenario: Deshacer movimiento a ya editados
- **WHEN** el usuario solicita deshacer el traslado de clips editados
- **THEN** el sistema devuelve los archivos a `videos sin editar` siempre que el origen se encuentre libre y registra la reversión en la bitácora

### Requirement: Monitoreo no destructivo de exportaciones de CapCut
El sistema SHALL vigilar pasivamente el directorio de exportación de CapCut hasta profundidad 3, ignorando archivos preexistentes mediante una fotografía inicial en arranque, esperando estabilidad y apertura exclusiva, sin modificar ni borrar archivos en dicha carpeta.

#### Scenario: Fotografía inicial al arrancar el servicio
- **WHEN** el servicio de vigilancia de CapCut inicia su ejecución
- **THEN** registra todas las rutas, tamaños y marcas de tiempo existentes en la carpeta de CapCut y las marca como ignoradas permanentemente

#### Scenario: Detección de nuevo video estabilizado
- **WHEN** CapCut finaliza la exportación de un nuevo video `.mp4` o `.mov` y el archivo mantiene su tamaño durante los sondeos requeridos y permite apertura exclusiva
- **THEN** el vigilante emite un evento de nuevo export disponible sin renombrar, mover ni borrar el archivo original en CapCut

#### Scenario: Archivo en crecimiento o bloqueado
- **WHEN** un archivo nuevo en la carpeta de CapCut continúa creciendo o produce error de bloqueo por escritura en curso
- **THEN** el sistema pospone su procesamiento hasta que se estabilice completamente

### Requirement: Vinculación determinista de exportaciones con sesiones
El sistema SHALL asociar automáticamente una nueva exportación a una sesión de edición si y solo si existe exactamente una sesión abierta; en caso de cero o múltiples sesiones, SHALL colocar el export en una bandeja de no asignados para selección manual.

#### Scenario: Vinculación automática con sesión única
- **WHEN** se detecta una exportación estabilizada y hay exactamente una sesión en estado "en_edicion"
- **THEN** el sistema asigna el video a dicha sesión y procede a la copia automática a videos completos

#### Scenario: Retención en bandeja sin asignar
- **WHEN** se detecta una exportación y existen dos o más sesiones en edición abiertas, o ninguna
- **THEN** el video se registra en "Exports sin asignar" en la interfaz con un selector para asociarlo a una sesión o descartarlo

### Requirement: Copia segura de exports a videos completos
El sistema SHALL copiar el export asociado a `<pendrive>/LucieSinReglas/videos completos/<personaje>/<capítulo>/<nombre>.mp4` escribiendo en `.part`, calculando SHA-256 en la misma pasada, aplicando fsync, renombre atómico y verificación por relectura, sin confirmación previa solo bajo condiciones estrictas.

#### Scenario: Copia automática y verificación de integridad
- **WHEN** una exportación está vinculada a una sesión única, el pendrive vinculado tiene espacio suficiente y el destino está libre
- **THEN** el archivo se copia a `videos completos/` con verificación de hash idéntico, registrando el evento `completo` en el manifiesto

#### Scenario: Deshacer copia a videos completos
- **WHEN** el usuario pulsa "Deshacer" sobre un video recién copiado a `videos completos`
- **THEN** el sistema traslada el archivo en el pendrive a `LucieSinReglas/_revertidos/<nombre>` usando `os.rename`, sin destruirlo

### Requirement: Cola de exportaciones pendientes por desconexión
El sistema SHALL retener las exportaciones listas cuando el pendrive no esté conectado o vinculado, y procesar su copia automáticamente en cuanto se detecte la conexión del pendrive autorizado.

#### Scenario: Procesamiento diferido al conectar pendrive
- **WHEN** se genera una exportación con el pendrive desconectado y posteriormente se vincula el pendrive
- **THEN** el sistema retoma los exports pendientes y ejecuta su copia segura a `videos completos` según las reglas de sesión

### Requirement: Notificación interactiva y transición post-exportación
El sistema SHALL notificar al usuario tras una copia exitosa a `videos completos` ofreciendo mover los crudos asociados a `videos ya editados`, respetando el modo configurado en `al_exportar`.

#### Scenario: Notificación para confirmar traslado de crudos
- **WHEN** se completa la copia a `videos completos` y la configuración `al_exportar` es `preguntar`
- **THEN** el panel muestra un aviso interactivo "¿Terminaste de editar estos N clips? [Mover a ya editados]" para disparar la transición con un clic
