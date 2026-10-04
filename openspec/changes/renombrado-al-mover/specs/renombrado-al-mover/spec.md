# Spec Delta: Renombrado Automático al Mover

## Purpose

Define el comportamiento del sistema para el renombrado automático de archivos en la bandeja de descargas durante el traslado, asignando nombres normalizados con contadores separados por tipo de medio, garantizando continuidad secuencial, prevención de colisiones insensible a mayúsculas y reversibilidad completa con el nombre original de descarga.

## ADDED Requirements

### Requirement: Cálculo de base de nombre por escena y personaje
El sistema SHALL calcular la base del nombre en minúsculas y sin espacios. Si el nombre de la escena ya comienza con el personaje o alguno de sus alias conocidos, la base SHALL ser exactamente el nombre de la escena. En caso contrario, la base SHALL componerse concatenando el identificador del personaje y el nombre de la escena (`<personaje><escena>`).

#### Scenario: Escena que ya incluye el alias del personaje
- **WHEN** se mueve un archivo con personaje `lucie` y escena `lucietrapitos`
- **THEN** la base calculada es `lucietrapitos` sin duplicar el prefijo `lucie`

#### Scenario: Escena sin alias del personaje
- **WHEN** se mueve un archivo con personaje `lucie` y escena `trapitos`
- **THEN** la base calculada es `lucietrapitos` anteponiendo el personaje

---

### Requirement: Contadores secuenciales separados por tipo de medio
El sistema SHALL mantener contadores numéricos independientes para imágenes (`.jpg`, `.jpeg`, `.png`, `.webp`) y para videos (`.mp4`, `.mov`, `.webm`). Cada archivo se renombrará pegando el número correlativo a la base (`<base><número>.<ext>`) sin guiones ni ceros a la izquierda, preservando la extensión en minúsculas.

#### Scenario: Lote mixto con imágenes y videos
- **WHEN** se procesa un lote para la base `rolibici` que contiene 1 video `.mp4` y 1 foto `.jpg`
- **THEN** el video se nombra `rolibici1.mp4` y la foto se nombra `rolibici1.jpg`

#### Scenario: Múltiples archivos del mismo tipo en un lote
- **WHEN** se procesa un lote con 3 fotos para la base `mailenauto`
- **THEN** se nombran secuencialmente `mailenauto1.jpg`, `mailenauto2.png` y `mailenauto3.jpg`

---

### Requirement: Ordenamiento por fecha de modificación y desempate
Dentro de cada lote o simulación, el sistema SHALL ordenar los archivos de forma ascendente por su fecha de modificación (`mtime`) antes de asignar los números correlativos. En caso de empate en `mtime`, el desempate SHALL realizarse por orden alfabético del nombre original de descarga.

#### Scenario: Asignación cronológica de números
- **WHEN** un lote contiene dos videos donde el video B tiene un `mtime` anterior al video A
- **THEN** el video B recibe el índice `1` (`<base>1.mp4`) y el video A recibe el índice `2` (`<base>2.mp4`)

#### Scenario: Desempate por nombre original
- **WHEN** dos archivos poseen idéntico `mtime`
- **THEN** el archivo cuyo nombre original precede alfabéticamente recibe el índice menor

---

### Requirement: Continuidad secuencial sobre carpetas preexistentes
Al simular y ejecutar un movimiento, el sistema SHALL inspeccionar la carpeta de destino. Si ya existen archivos con la misma base y tipo de medio, el contador inicial SHALL comenzar en el valor máximo existente más uno (`max_existente + 1`), garantizando que no se repitan índices numéricos ni se sobrescriban archivos previos.

#### Scenario: Envío de segundo lote a escena existente
- **WHEN** la carpeta destino ya contiene `lucietrapitos1.mp4` y se mueve un nuevo video
- **THEN** el nuevo video recibe el nombre `lucietrapitos2.mp4`

#### Scenario: Reapertura de capítulo con numeración avanzada
- **WHEN** un capítulo reabierto contiene archivos hasta `rolibici5.jpg` y se agrega una foto
- **THEN** la nueva foto se nombra `rolibici6.jpg`

---

### Requirement: Prevención estricta de colisiones case-insensitive
La comprobación de existencia previa en destino SHALL realizarse de manera insensible a mayúsculas y minúsculas para compatibilidad con sistemas FAT32/exFAT. El sistema SHALL asegurar que dos archivos dentro de la misma simulación nunca reciban el mismo destino y re-verificar la inexistencia inmediatamente antes de ejecutar `os.rename`.

#### Scenario: Detección de colisión insensible a mayúsculas
- **WHEN** existe en disco el archivo `Base1.MP4` y el nuevo candidato se llamaría `base1.mp4`
- **THEN** el sistema detecta la existencia previa e incrementa el contador al siguiente disponible

#### Scenario: Red de seguridad en ejecución atómica
- **WHEN** al momento exacto de ejecutar `os.rename` el destino resultara ocupado por una condición de carrera
- **THEN** el sistema aplica la resolución de colisión con sufijo numérico ` (1)` sin pisar el archivo existente

---

### Requirement: Proyección en simulación previa y limpieza visual
El modal de simulación previa SHALL proyectar y mostrar para cada archivo la relación explícita `nombre_original -> nombre_nuevo` junto con la ruta de destino completa en el tooltip. El sistema SHALL omitir etiquetas obsoletas de subcarpeta de tipo (`imagenes`, `videos sin editar`).

#### Scenario: Visualización clara del renombrado en el modal
- **WHEN** el usuario abre la simulación previa de un lote para mover
- **THEN** la tabla muestra la columna de archivo con `grok-image-xxx.jpg -> lucietrapitos1.jpg` y el destino exacto

#### Scenario: Modal sin etiquetas de tipo legadas
- **WHEN** se genera el marcado HTML de simulación
- **THEN** no se incluyen etiquetas `tag-tipo` de `imagenes` o `videos sin editar`

---

### Requirement: Registro auditable en bitácora y reversión con nombre original
El sistema SHALL registrar en cada movimiento de `bitacora_bandeja.jsonl` los campos `nombre_original` y `nombre_nuevo`. Al invocar `deshacer_operacion`, el archivo SHALL restaurarse a su ruta y nombre original de descarga con `os.rename`. Si la ruta original estuviera ocupada, el proceso SHALL abortar sin pisar ni renombrar.

#### Scenario: Reversión exitosa restaura el nombre original
- **WHEN** el usuario deshace un movimiento de `lucietrapitos1.mp4`
- **THEN** el archivo regresa a su ubicación previa en `~/Descargas/` con su nombre original `grok-video-xxx.mp4`

#### Scenario: Bloqueo de reversión por origen ocupado
- **WHEN** se intenta deshacer una operación pero la ruta original ya contiene un archivo
- **THEN** la reversión se niega terminantemente con error de conflicto sin alterar ningún archivo

#### Scenario: Retrocompatibilidad con bitácora previa
- **WHEN** se lee el historial de movimientos de líneas antiguas que no contienen `nombre_original`
- **THEN** el sistema opera normalmente deduciendo los nombres a partir de las rutas registradas
