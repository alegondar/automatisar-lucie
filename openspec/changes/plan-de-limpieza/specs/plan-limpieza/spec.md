# Spec Delta

## Purpose

Permite generar planes de limpieza simulados sobre el almacenamiento extraíble a partir del inventario y caché existentes, garantizando solo lectura estricta, validación de no colisión en destinos propuestos, trazabilidad por huella de integridad tolerante a FAT/exFAT con recálculo de SHA-256 en vivo, exclusión de cuarentena y verificación estática exhaustiva anti-borrado (AST) según las Reglas de Oro del proyecto.

## ADDED Requirements

### Requirement: Simulación de solo lectura y validación de destinos
El sistema SHALL operar exclusivamente en modo de solo lectura sobre el almacenamiento analizado, sin realizar operaciones de escritura, traslado, copia ni renombre en el pendrive ni en `~/Descargas`. El sistema SHALL generar como salida los archivos `plan_limpieza.json` y `plan_limpieza.md` en el repositorio local. Toda acción con destino propuesto SHALL verificar que la ruta no exista previamente en el inventario ni en el almacenamiento para evitar proponer colisiones.

#### Scenario: Generación exitosa de plan en modo simulación
- **WHEN** se ejecuta el generador de plan sobre un inventario y caché existentes
- **THEN** se crean los archivos `plan_limpieza.json` y `plan_limpieza.md` en el repositorio mostrando origen y destino exactos sin modificar ni escribir ningún archivo en el almacenamiento origen

#### Scenario: Detección y rechazo de colisión en destino propuesto
- **WHEN** una regla del plan genera una ruta de destino que ya existe en el pendrive o en el inventario
- **THEN** el generador invalida la propuesta de destino marcando la colisión y absteniéndose de sugerir sobrescritura

#### Scenario: Fallo ante intento de escritura en la unidad analizada
- **WHEN** se intenta configurar una ruta de salida o archivo temporal dentro del pendrive
- **THEN** el sistema rechaza la operación inmediatamente con un error de seguridad de solo lectura

### Requirement: Prohibición absoluta de borrado y verificador estático AST
El código del proyecto SHALL NOT contener llamadas a primitivas de borrado ni pisado ciego (`os.remove`, `os.unlink`, `os.rmdir`, `os.removedirs`, `Path.unlink`, `Path.rmdir`, `shutil.rmtree`, `shutil.move`, `os.replace`, `send2trash`, ni `subprocess`/`os.system` con `rm`). El proyecto SHALL incorporar un analizador estático AST y pruebas unitarias que verifiquen que detecta cada una de dichas funciones en ejemplos sintéticos y confirmen que el código del proyecto está 100% libre de ellas.

#### Scenario: Analizador AST detecta cada primitiva prohibida en código de prueba
- **WHEN** se ejecuta el test del analizador AST sobre fragmentos de código de prueba conteniendo individualmente cada una de las 11 llamadas prohibidas
- **THEN** el analizador detecta y reporta exitosamente cada una de las infracciones

#### Scenario: Verificación estática exitosa sobre el código del proyecto
- **WHEN** el analizador AST examina la totalidad de los archivos de código operativo del repositorio
- **THEN** no encuentra ninguna llamada prohibida y el test resulta exitoso

### Requirement: Estructura unificada de acciones del plan
Cada entrada de acción en el plan de limpieza SHALL incluir obligatoriamente los campos `id` (identificador único secuencial o UUID), `tipo` (categoría de acción), `origen` (ruta relativa del archivo o carpeta), `destino` (ruta relativa propuesta o null) y `motivo` (explicación textual de la regla aplicada).

#### Scenario: Validación de campos de acción
- **WHEN** se emite cualquier propuesta de acción en `plan_limpieza.json`
- **THEN** la acción contiene `id`, `tipo`, `origen`, `destino` y `motivo` con valores válidos y no nulos en sus identificadores y motivos

### Requirement: Gestión de duplicados inter-carpeta y copias a conservar
Para duplicados exactos distribuidos en distintas carpetas de primer nivel que no contengan copias en carpetas protegidas, el sistema SHALL seleccionar una copia a conservar priorizando carpetas configuradas ("videos completos" > resto; desempate por mtime más reciente). Las copias secundarias de otras carpetas SHALL proponer traslado a `_a_revisar/duplicados/` preservando su ruta relativa. Si alguna copia del grupo pertenece a una carpeta protegida (`carpetas_protegidas`), el grupo SHALL NOT generar traslados automáticos. El sistema SHALL NEVER proponer borrar.

#### Scenario: Selección de copia en carpeta prioritaria entre distintas carpetas
- **WHEN** existen duplicados exactos donde una copia está en `videos completos/` y otra en `videos1/`, y ninguna pertenece a una carpeta protegida
- **THEN** la copia en `videos completos/` se marca para conservar y la de `videos1/` propone traslado a `_a_revisar/duplicados/videos1/...`

#### Scenario: Desempate por fecha más reciente en carpetas distintas
- **WHEN** existen duplicados exactos en distintas carpetas con la misma prioridad y sin copias protegidas
- **THEN** se conserva la copia con mtime más reciente y las demás proponen traslado a `_a_revisar/duplicados/`

#### Scenario: Prohibición estricta de borrado
- **WHEN** se procesan duplicados exactos
- **THEN** ninguna acción del plan contiene un tipo o instrucción de eliminación física

### Requirement: Registro de duplicados a decidir a mano (intra-carpeta o en carpetas protegidas)
Cuando dos o más copias idénticas residen dentro de la misma carpeta de primer nivel (incluso en distintas subcarpetas), O cuando ALGUNA copia de un grupo de duplicados se encuentra dentro de una carpeta protegida configurada en `carpetas_protegidas` (como `laroli` o `videos1/laroli`), el sistema SHALL NOT proponer ningún traslado automático (ni de la copia protegida ni de las otras). El sistema SHALL registrarlas en una sección "duplicados a decidir a mano" detallando todas las rutas, tamaños y fechas.

#### Scenario: Duplicados dentro de la misma carpeta de primer nivel
- **WHEN** existen copias idénticas dentro de la misma carpeta de primer nivel (ej. `videos completos/clip.mp4` y `videos completos/sin_publicar/clip.mp4`)
- **THEN** no se propone mover ninguno de ellos (`destino: null`), y se listan como "duplicados a decidir a mano" con sus rutas, tamaños y fechas

#### Scenario: Duplicados con alguna copia en carpeta protegida
- **WHEN** un grupo de duplicados exactos tiene al menos una copia dentro de una carpeta protegida configurada en `carpetas_protegidas` (ej. `laroli` o `videos1/laroli`)
- **THEN** el sistema no genera ningún traslado automático para ninguna de las copias (destino: null) y registra el grupo en "duplicados a decidir a mano" con todas sus rutas, tamaños y fechas

### Requirement: Detección y reporte diferencial de carpetas sospechosas
Para pares de carpetas con una similitud de contenido mayor o igual al 75% (incluyendo el par `laroli` frente a `videos1/laroli`), el sistema SHALL listar individualmente los archivos disjuntos (presentes en una carpeta y ausentes en la otra) detallando ruta, tamaño y fecha. El sistema SHALL NEVER proponer la fusión ni el traslado masivo de carpetas enteras.

#### Scenario: Identificación de diferencias en laroli frente a videos1/laroli
- **WHEN** se evalúa el par de carpetas `laroli` y `videos1/laroli` con similitud superior al 75%
- **THEN** el plan lista los archivos exclusivos de cada una con ruta, tamaño y fecha, sin proponer mover las carpetas completas

#### Scenario: Par de carpetas sin archivos compartidos suficientes
- **WHEN** dos carpetas tienen una similitud de contenido menor al umbral configurable (75%)
- **THEN** no se genera un bloque de diferencias de carpetas sospechosas para ese par

### Requirement: Clasificación de archivos sueltos mediante alias de personajes
El sistema SHALL evaluar los archivos sueltos ubicados en la raíz del almacenamiento y en la raíz de carpetas de primer nivel contra un mapa configurable de alias de personajes (`alias-personajes.json`). Los archivos que coincidan con patrones reconocidos SHALL proponer como destino la carpeta del personaje asignada (o indicar estado a confirmar si el alias lo define). Los archivos sin coincidencia SHALL registrarse con la etiqueta "sin clasificar" y sin acción de traslado (`destino: null`).

#### Scenario: Coincidencia con alias roli
- **WHEN** un archivo suelto tiene un nombre que coincide con el patrón `roli*`, `laroli*` o `magui*`
- **THEN** el plan propone como destino la carpeta correspondiente a `roli` con motivo indicando coincidencia de alias

#### Scenario: Coincidencia con alias lucie
- **WHEN** un archivo suelto coincide con `lucie*` o `luci*`
- **THEN** el plan propone como destino la carpeta `lucie`

#### Scenario: Coincidencia con alias mailen a confirmar
- **WHEN** un archivo suelto coincide con `mailen*`
- **THEN** el plan propone destino `mailen` señalando en el motivo que requiere confirmación previa

#### Scenario: Archivo suelto sin coincidencia de alias
- **WHEN** un archivo suelto no coincide con ningún patrón de alias definido
- **THEN** el archivo se clasifica como "sin clasificar" y su destino propuesto es null

### Requirement: Registro informativo de carpetas vacías
El sistema SHALL identificar y registrar en el plan todas las carpetas que no contengan archivos válidos luego de aplicar los filtros de sistema. El registro SHALL ser de naturaleza informativa y SHALL NOT proponer acciones de borrado automático.

#### Scenario: Listado de carpetas vacías sin acción
- **WHEN** se detecta una carpeta que no contiene archivos válidos
- **THEN** el plan la incluye en la sección de carpetas vacías con destino nulo y tipo informativo

### Requirement: Configuración editable de exclusiones y cuarentena
El sistema SHALL cargar su configuración desde archivos editables en el repositorio, incluyendo por defecto `_a_revisar` y `code` entre las carpetas ignoradas para evitar reprocesar cuarentenas, la lista `carpetas_protegidas` (con `laroli` y `videos1/laroli` por defecto) para prevenir movimientos de duplicados sensibles, junto con el orden de carpetas prioritarias y el mapa de alias de personajes.

#### Scenario: Exclusión de cuarentena y carpetas ignoradas por defecto
- **WHEN** se ejecuta el análisis sobre un inventario que contiene `_a_revisar/` o `code/`
- **THEN** los archivos dentro de `_a_revisar/` y `code/` se ignoran por completo y no se computan como duplicados ni candidatos a clasificar

#### Scenario: Protección de carpetas sensibles configuradas
- **WHEN** se define la lista `carpetas_protegidas` en `config_limpieza.json` con rutas relativas a la raíz
- **THEN** cualquier archivo o copia de duplicados ubicado dentro de dichas rutas activa la regla de no movimiento para todo su grupo

#### Scenario: Uso de valores por defecto si no existe archivo de configuración
- **WHEN** no se proporciona un archivo de configuración personalizado
- **THEN** el sistema utiliza la configuración estándar con prioridad `videos completos`, carpetas protegidas `['laroli', 'videos1/laroli']`, ignorando `_a_revisar` y carpetas de sistema

### Requirement: Huella de integridad y validación pre-ejecución tolerante a FAT
El plan SHALL incluir un `plan_id` y huella con tamaño y hash SHA-256 de los archivos a mover. La caché SQLite SHALL usarse solo para generar el plan. La validación pre-ejecución SHALL recalcular el SHA-256 leyendo el archivo físico real en ese momento y comparándolo con el hash guardado en el plan. El mtime SHALL ser informativo con tolerancia de 2 segundos. Si el tamaño difiere o el hash recalculado no coincide, el sistema SHALL abortar la ejecución inmediatamente.

#### Scenario: Validación exitosa con tolerancia de mtime en FAT/exFAT
- **WHEN** un validador coteja los archivos a mover, recalcula su SHA-256 del disco real coincidiendo con la huella, y constata mtime difiriendo en menos de 2 segundos
- **THEN** la validación de integridad resulta exitosa

#### Scenario: Aborto ante discrepancia de hash recalculado o tamaño
- **WHEN** un archivo programado para traslado ha cambiado de tamaño o su hash recalculado desde el disco real no coincide con la huella
- **THEN** la validación falla y la ejecución se aborta inmediatamente sin consultar la caché SQLite

#### Scenario: Detección de alteración de contenido con mismo tamaño y mtime
- **WHEN** se modifica el contenido de un archivo a mover preservando su tamaño original y restaurando su mtime exacto con os.utime
- **THEN** el validador recalcula el SHA-256 leyendo los bytes físicos reales, detecta la divergencia contra el hash de la huella y aborta la ejecución
