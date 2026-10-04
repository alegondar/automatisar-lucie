# descartar-capitulo Specification

## Requirements

### Requirement: Cuarentena Atómica Sin Borrado
El sistema DEBE permitir descartar un capítulo moviendo su carpeta completa desde `~/Descargas/_lucie/<personaje>/<escena>/` hacia `~/Descargas/_lucie/_descartados/<personaje>/<escena>_<AAAAMMDD-HHMMSS>/` mediante un único `os.rename`, sin utilizar primitivas de borrado ni sobrescritura.

#### Scenario: Descarte exitoso de capítulo existente con archivos
- **GIVEN** un capítulo `playa` de `lucie` con 5 archivos en `~/Descargas/_lucie/lucie/playa/`.
- **WHEN** se ejecuta el descarte con la confirmación correcta.
- **THEN** la carpeta completa es trasladada a `~/Descargas/_lucie/_descartados/lucie/playa_<timestamp>/`.
- **AND** los 5 archivos conservan intactos sus contenidos y hashes SHA-256.
- **AND** el capítulo se marca como `descartado = 1` en la base de datos.

#### Scenario: Descarte de capítulo con carpeta inexistente o vacía
- **GIVEN** un capítulo registrado en la base de datos cuya carpeta en disco no existe o no contiene archivos.
- **WHEN** se ejecuta el descarte.
- **THEN** el capítulo es marcado como `descartado = 1` en la base de datos sin ejecutar `os.rename`.
- **AND** la respuesta informa que no hubo archivos para trasladar.

### Requirement: Simulación Previa y Confirmación Obligatoria
Toda acción de descarte DEBE requerir una simulación previa que exponga las rutas, cantidad de archivos, peso total y advertencia de reversibilidad, exigiendo el tipeo exacto del nombre del capítulo para su ejecución.

#### Scenario: Simulación no altera el disco
- **GIVEN** un capítulo con archivos en su carpeta.
- **WHEN** se solicita la simulación de descarte vía `POST /api/capitulos/descartar-simular`.
- **THEN** la respuesta contiene `origen_carpeta`, `destino_carpeta`, `total_archivos`, `peso_total` y el aviso explicativo.
- **AND** la carpeta en el disco permanece intacta.

#### Scenario: Rechazo de confirmación errónea
- **GIVEN** una simulación para el capítulo `lucietrapitos`.
- **WHEN** se envía `POST /api/capitulos/descartar` con `nombre_confirmacion` distinto a `lucietrapitos`.
- **THEN** la petición es rechazada con código 400 y mensaje de error.
- **AND** no se realiza ningún movimiento de carpetas.

### Requirement: Confinamiento y Prevención de Sobrescritura
El sistema DEBE verificar que las rutas de origen y destino pertenezcan estrictamente a `~/Descargas/_lucie`, rechazando symlinks salientes y resolviendo colisiones con sufijo numérico.

#### Scenario: Destino ya existe en `_descartados`
- **GIVEN** ya existe una carpeta con el mismo nombre y timestamp en `_descartados`.
- **WHEN** se calcula el destino.
- **THEN** el sistema asigna automáticamente un sufijo correlativo ` (1)` sin pisar la carpeta preexistente.

#### Scenario: Rechazo de path traversal o symlinks
- **GIVEN** un intento de descarte con ruta o nombre que intente escapar de `~/Descargas/_lucie` o apunte a un symlink exterior.
- **WHEN** se valida el confinamiento.
- **THEN** la operación es abortada con `ErrorSeguridadBandeja`.

### Requirement: Desactivación Inmediata de Capítulo Activo
Al descartar el capítulo actualmente activo, el sistema DEBE cerrarlo y desactivarlo de forma inmediata.

#### Scenario: Capítulo activo descartado
- **GIVEN** un capítulo activo asignando archivos nuevos.
- **WHEN** el usuario descarta dicho capítulo.
- **THEN** el capítulo activo se deshabilita en `bandeja_estado`.
- **AND** los nuevos escaneos ya no asignan archivos a ese capítulo.

### Requirement: Registro en Bitácora y Deshacer Estricto
Toda operación de descarte DEBE asentarse en `bitacora_bandeja.jsonl` con el evento `descartar_capitulo` y admitir reversión estricta a su ubicación original.

#### Scenario: Deshacer exitoso restaura la carpeta
- **GIVEN** un capítulo descartado cuyo origen original permanece libre.
- **WHEN** se invoca `deshacer_operacion` con el `id_operacion` del descarte.
- **THEN** la carpeta en `_descartados` es movida de regreso a su ruta original con `os.rename`.
- **AND** el capítulo queda restablecido como `descartado = 0, estado = 'cerrado'` en la base de datos.
- **AND** se registra un evento `deshacer` en la bitácora.

#### Scenario: Deshacer denegado si el origen está ocupado
- **GIVEN** un capítulo descartado cuyo origen original fue ocupado por un nuevo archivo o carpeta.
- **WHEN** se intenta deshacer la operación.
- **THEN** el sistema se niega terminantemente a realizar la reversión sin pisar ni sufijar.
- **AND** la carpeta permanece segura en `_descartados`.

### Requirement: Aislamiento de la Carpeta `_descartados`
La carpeta `_descartados` NUNCA DEBE ser leída como escena en la sala de espera ni ser sugerida como destino para nuevos movimientos.

#### Scenario: Escaneo ignora `_descartados`
- **GIVEN** existen capítulos archivados dentro de `~/Descargas/_lucie/_descartados/`.
- **WHEN** el vigilante realiza el escaneo de escenas existentes o el usuario consulta las opciones de destino.
- **THEN** `_descartados` y sus subcarpetas no aparecen en el catálogo de escenas.
