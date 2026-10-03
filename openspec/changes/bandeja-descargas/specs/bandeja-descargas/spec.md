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

### Requirement: Reconocimiento de escenas existentes sin movimiento
El sistema SHALL escanear las carpetas de primer nivel en `~/Descargas` cuyos nombres comiencen con alias registrados de personajes y ofrecerlas como escenas existentes en la interfaz, sin moverlas, modificarlas ni renombrarlas.

#### Scenario: Detección de carpeta de escena existente
- **WHEN** existe una carpeta `roli parque` en `~/Descargas`
- **THEN** el sistema la reconoce como escena existente para el personaje `roli` y la mantiene intacta en su ubicación original

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

### Requirement: Panel web local con preselección y miniaturas
El sistema SHALL proveer una interfaz web en `127.0.0.1` (puerto configurable, default 8766) con visualización de lotes, miniaturas generadas con `ffmpeg`, selectores de personaje y escena (existente o nueva), preseleccionando el personaje del último lote procesado.

#### Scenario: Carga del panel y preselección de personaje
- **WHEN** el usuario abre el panel tras haber movido previamente un lote del personaje `lucie`
- **THEN** el selector de personaje del nuevo lote aparece preseleccionado con `lucie`

#### Scenario: Generación de miniatura con ffmpeg
- **WHEN** se visualiza un lote con archivos de video y `ffmpeg` está disponible
- **THEN** el sistema genera y sirve un fotograma estático de vista previa para el usuario

### Requirement: Simulación previa obligatoria y movimiento seguro sin pisado
El sistema SHALL presentar una simulación previa obligatoria con las rutas exactas de origen y destino antes de ejecutar cualquier movimiento, realizándolo exclusivamente con `os.rename` dentro de `~/Descargas`, verificando que el destino no exista y agregando sufijo numérico ante colisiones.

#### Scenario: Simulación previa antes de mover
- **WHEN** el usuario hace clic en "Mover lote"
- **THEN** el panel muestra una previsualización de cada archivo con su origen y destino final antes de solicitar la confirmación definitiva

#### Scenario: Manejo de colisión en destino
- **WHEN** el destino propuesto ya contiene un archivo con idéntico nombre
- **THEN** el sistema añade un sufijo numérico correlativo ` (1)`, ` (2)` al nombre de destino para evitar cualquier sobrescritura

### Requirement: Confinamiento estricto a ~/Descargas y prohibición de acceso al pendrive
El sistema SHALL validar mediante `os.path.realpath` que todas las rutas de origen y destino pertenezcan estrictamente al subárbol de `~/Descargas`, rechazando cualquier operación que apunte fuera de este límite o intente interactuar con el pendrive.

#### Scenario: Validación de contención de ruta
- **WHEN** se evalúa una ruta de origen o destino
- **THEN** el sistema confirma que su ruta canónica absoluta comienza con el directorio canónico de `~/Descargas`, abortando la acción si no coincide

### Requirement: Bitácora reversible y función de deshacer sin borrado
El sistema SHALL registrar cada operación de lote en un archivo de bitácora en formato `.jsonl` y permitir su reversión total mediante una acción de deshacer que reubique los archivos en su origen original con `os.rename`, sin utilizar jamás primitivas de borrado.

#### Scenario: Registro en bitácora tras mover
- **WHEN** se completa exitosamente el movimiento de un lote
- **THEN** se escribe una entrada estructurada en la bitácora `.jsonl` con el detalle de archivos, marcas temporales y rutas previas

#### Scenario: Ejecución de deshacer
- **WHEN** el usuario solicita deshacer un movimiento registrado en la bitácora
- **THEN** el sistema devuelve cada archivo a su ruta de origen mediante `os.rename` y actualiza la bitácora

### Requirement: Registro persistente en SQLite
El sistema SHALL registrar cada archivo procesado en la tabla `bandeja_archivos` de la base de datos SQLite, vinculando su hash SHA-256, ruta actual, estado del ciclo de vida, personaje, escena y fecha de actualización.

#### Scenario: Registro de archivo en base SQLite
- **WHEN** un archivo es detectado, clasificado o movido
- **THEN** el sistema inserta o actualiza el registro correspondiente en la tabla `bandeja_archivos`
