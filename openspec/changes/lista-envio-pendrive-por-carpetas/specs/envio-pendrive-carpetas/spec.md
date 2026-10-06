# Spec Delta: envio-pendrive-carpetas

## Purpose

Permite explorar exhaustivamente todas las carpetas y archivos en la sala de espera de descargas mediante un endpoint independiente, inspeccionarlos interactivamente, auditarlos contra el pendrive y seleccionar en lote cuáles transferir con simulación previa obligatoria.

## ADDED Requirements

### Requirement: Endpoint desacoplado para catálogo exhaustivo de carpetas de sala de espera
El sistema SHALL proveer el endpoint `GET /api/pendrive/carpetas` para escanear y listar exclusivamente las carpetas y archivos en la sala de espera local (`~/Descargas/_lucie/<personaje>/<carpeta>`), sin acceder ni depender de la unidad pendrive física. El endpoint `GET /api/pendrive/estado` SHALL restringirse exclusivamente al estado físico y vinculación de la unidad pendrive. Si el pendrive está desconectado o no responde, `GET /api/pendrive/carpetas` SHALL devolver igualmente la lista completa de carpetas sin demoras ni bloqueos.

#### Scenario: Listado sin pendrive conectado ni respuesta de unidad
- **WHEN** el usuario consulta `GET /api/pendrive/carpetas` y el pendrive físico no está conectado o no responde
- **THEN** el sistema responde con código 200 y la lista completa de carpetas existentes en disco para cada personaje, incluyendo conteo de archivos, peso y fecha

#### Scenario: Omisión estricta de carpetas de control interno
- **WHEN** existen carpetas denominadas `_enviados`, `_revertidos` o `_descartados` dentro del árbol de la sala de espera
- **THEN** el sistema las omite de la lista de carpetas para transferir

### Requirement: Escaneo recursivo seguro con límite de profundidad y sin symlinks
El sistema SHALL escanear el árbol de cada carpeta de forma recursiva con `followlinks=False` (sin seguir enlaces simbólicos) y con un tope estricto de profundidad de hasta 6 niveles. El sistema NO SHALL descartar carpetas que no contengan archivos directos en su raíz si poseen archivos en sus subcarpetas, y SHALL acumular el conteo y peso total recursivo de todos los archivos encontrados.

#### Scenario: Carpeta con archivos únicamente en subcarpetas anidadas
- **WHEN** una carpeta de sala de espera (por ejemplo `imagenes`) no tiene archivos en su raíz pero contiene archivos dentro de subcarpetas (como `imagenes/prueba bandeja/archivo.jpg`)
- **THEN** el sistema incluye la carpeta en el catálogo con el conteo y peso total acumulado de sus archivos anidados

#### Scenario: Enlaces simbólicos que apuntan a otras rutas
- **WHEN** una carpeta contiene enlaces simbólicos (symlinks) a otros directorios
- **THEN** el sistema no los sigue (`followlinks=False`) previniendo ciclos y escapes de la raíz permitida

### Requirement: Tipificación cruzando con la base de datos de capítulos
El sistema SHALL clasificar cada carpeta descubierta cruzando su personaje y nombre de carpeta contra la tabla `bandeja_capitulos` de la base de datos:
1. Si coincide con un capítulo activo en foco: `Capítulo en foco`.
2. Si coincide con un capítulo abierto: `Capítulo abierto`.
3. Si coincide con un capítulo registrado como cerrado: `Capítulo cerrado`.
4. Si no está registrada en la base pero posee estructura de escena: `Escena suelta`.
5. Si es una carpeta de sala de espera sin estructura canónica de capítulo (por ejemplo `imagenes`): `Carpeta heredada`.
Las carpetas clasificadas como `Carpeta heredada` SHALL mostrar una insignia y aviso explicativo, y no SHALL transferirse automáticamente sin selección explícita del usuario.

#### Scenario: Clasificación de carpeta heredada
- **WHEN** el sistema escanea una carpeta preexistente sin estructura canónica de capítulo (por ejemplo `imagenes`)
- **THEN** la presenta en el panel identificada como "Carpeta heredada" con su contenido disponible para inspección manual

#### Scenario: Clasificación de capítulo en foco, abierto y cerrado
- **WHEN** se escanean carpetas correspondientes a capítulos registrados en `bandeja_capitulos`
- **THEN** el sistema las tipifica exactamente como "Capítulo en foco", "Capítulo abierto" o "Capítulo cerrado" según su estado en la base de datos

### Requirement: Desglose y enrutamiento de archivos multimedia y no multimedia
El sistema SHALL contabilizar todos los archivos dentro de cada carpeta, tanto los ubicados en subcarpetas `fotos/` y `videos/` como los archivos sueltos en la raíz. Los archivos multimedia sueltos en la raíz se contabilizarán y se enrutarán por tipo (`fotos` o `imagenes`, `videos` o `videos sin editar`) preservando sus nombres. Si se detectan archivos con extensiones no multimedia, el sistema SHALL contabilizarlos por separado y mostrar una advertencia visible sin interrumpir la operación.

#### Scenario: Carpeta con archivos sueltos en la raíz
- **WHEN** una carpeta contiene archivos `.jpg` y `.mp4` directamente en su raíz sin subcarpetas
- **THEN** el sistema los incluye en los conteos de fotos y videos y los considera listos para transferir

#### Scenario: Detección de archivos no multimedia
- **WHEN** una carpeta contiene documentos o archivos con extensiones no multimedia (como `.txt` o `.pdf`)
- **THEN** el sistema muestra un indicador de aviso y los lista por separado sin procesarlos destructivamente

### Requirement: Inspección de archivos y vista previa multimedia
Cada fila de la tabla de carpetas SHALL proveer un control desplegable "Ver archivos" que exponga el listado de archivos que contiene (nombre, tamaño, tipo y fecha). Para cada archivo multimedia en el desglose, el sistema SHALL permitir invocar el visor multimedia modal existente (lightbox) para reproducir videos o visualizar imágenes antes de decidir el envío.

#### Scenario: Inspección detallada de archivos de una carpeta
- **WHEN** el usuario hace clic en "Ver archivos" en la fila de una carpeta
- **THEN** se despliega la lista con el detalle individual de sus archivos y miniaturas interactivas para abrir el visor

### Requirement: Selección granular en lote y plan unificado con simulación obligatoria
El sistema SHALL permitir al usuario seleccionar una, varias o todas las carpetas mediante casillas de verificación individuales y botones globales ("Seleccionar todas", "Ninguna", "Enviar seleccionadas (N)"). El envío de las carpetas seleccionadas SHALL generar un único plan de envío unificado que requiera simulación previa obligatoria (dry-run) y confirmación explícita de un clic antes de cualquier copia física.

#### Scenario: Envío múltiple unificado
- **WHEN** el usuario selecciona 3 carpetas de la sala de espera y pulsa "Enviar seleccionadas (3)"
- **THEN** el sistema calcula y presenta un único modal de simulación consolidado que muestra todos los archivos a transferir, el espacio requerido y las verificaciones de seguridad

#### Scenario: Botón individual de envío por carpeta
- **WHEN** el usuario pulsa "Enviar esta carpeta" en una fila específica
- **THEN** el sistema abre la simulación de envío limitada exclusivamente a dicha carpeta

### Requirement: Diagnóstico de estado de la unidad física y pendrive
La sección "Unidad Pendrive" del panel SHALL diferenciar claramente cuatro estados: (1) Ninguna unidad conectada, (2) Unidad conectada pero sin vincular (mostrando etiqueta, punto de montaje, sistema de archivos, espacio libre y botón destacado "Vincular pendrive"), (3) Pendrive conectado y vinculado listo para operar, y (4) Sin respuesta (cuando el dispositivo se bloquea o demora más allá del tiempo límite). Si el pendrive no está conectado o no está vinculado, las acciones de envío SHALL permanecer deshabilitadas indicando el motivo.

#### Scenario: Unidad conectada sin vincular
- **WHEN** se conecta un pendrive formateado que aún no contiene el marcador `.lucie_pendrive.json`
- **THEN** el panel muestra sus datos técnicos (punto de montaje, filesystem, espacio libre) y destaca el botón para iniciar su vinculación

#### Scenario: Deshabilitación de botones de envío sin pendrive listo
- **WHEN** el pendrive no está conectado o no está vinculado
- **THEN** la lista de carpetas permanece navegable pero los botones de envío se deshabilitan con un mensaje explicativo

### Requirement: Auditoría de archivos ya enviados contra manifiesto
Cuando el pendrive vinculado se encuentre conectado, el sistema SHALL contrastar los hashes SHA-256 de los archivos de cada carpeta contra las entradas del manifiesto del pendrive para informar en cada fila cuántos archivos ya fueron transferidos previamente y cuántos restan por enviar. El cálculo de hashes en el servidor no SHALL bloquear la respuesta del panel.

#### Scenario: Detección de archivos ya transferidos
- **WHEN** una carpeta de 5 archivos tiene 3 archivos cuyos hashes ya figuran en el manifiesto del pendrive
- **THEN** la fila muestra "3 ya enviados, 2 pendientes" y la simulación omite volver a copiar los 3 idénticos

### Requirement: Persistencia de selección durante refresco periódico
Durante el redibujado automático del panel (polling periódico), el sistema en el cliente frontend SHALL preservar el estado de selección (casillas marcadas o desmarcadas) de cada carpeta para no alterar la interacción del usuario mientras toma decisiones.

#### Scenario: Conservación de selección durante refresco
- **WHEN** el usuario marca 2 carpetas y ocurre un ciclo de refresco automático
- **THEN** tras actualizar los datos de la interfaz, las mismas 2 carpetas continúan seleccionadas
