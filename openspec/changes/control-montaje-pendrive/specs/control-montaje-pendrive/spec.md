# Spec Delta

## Purpose

Proporciona detección de particiones extraíbles montadas y sin montar en Linux vía sysfs/procfs, y permite operaciones seguras y auditadas de montaje, desmontaje y expulsión eléctrica sin riesgos destructivos.

## ADDED Requirements

### Requirement: Detección nativa de particiones removibles montadas y sin montar
El sistema SHALL inspeccionar `/sys/block/*/removable` (=1), `/sys/class/block`, los enlaces de `/dev/disk/by-label` y `/proc/self/mountinfo` sin utilizar subprocess, para detectar particiones extraíbles tanto montadas como sin montar, reconociendo montajes FUSE como montados y tolerando atributos faltantes sin error.

#### Scenario: Partición extraíble detectada sin montar
- **WHEN** un pendrive extraíble con partición formateada está enchufado pero carece de punto de montaje en `/proc/self/mountinfo`
- **THEN** el sistema lo identifica como unidad removible no montada, extrayendo su nodo de dispositivo, etiqueta, tamaño y sistema de archivos sin lanzar subprocesos

#### Scenario: Múltiples particiones extraíbles detectadas
- **WHEN** se conectan dos o más particiones o pendrives removibles simultáneamente
- **THEN** el sistema lista todas las unidades detectadas ordenando prioritariamente aquellas con etiqueta `MIUNIDAD`, y requiere que el usuario elija explícitamente cuál operar

#### Scenario: Discos internos no removibles ignorados
- **WHEN** una partición pertenece a un dispositivo de bloque con `removable` igual a 0 o inexistente
- **THEN** el sistema no la clasifica como candidata a pendrive ni la incluye en las unidades seleccionables

### Requirement: Clasificación de estados y diagnóstico de particiones
El sistema SHALL clasificar la situación del pendrive en cinco estados mutuamente excluyentes (`sin_unidad`, `detectada_sin_montar`, `conectada_sin_vincular`, `vinculado_listo`, `sin_respuesta`) y proveer un diagnóstico completo de todas las particiones evaluadas en un bloque colapsable.

#### Scenario: Estado detectada sin montar
- **WHEN** no hay pendrives montados pero se detecta al menos una partición removible conectada
- **THEN** el estado reportado es `detectada_sin_montar` y expone los datos técnicos del dispositivo junto a la acción de montaje

#### Scenario: Consulta de diagnóstico de particiones
- **WHEN** el usuario despliega la sección "¿Por qué no veo mi pendrive?"
- **THEN** el sistema muestra la lista de todas las particiones evaluadas con su indicador de removible, estado de montaje, ruta de montaje y sistema de archivos

#### Scenario: Timeout en lectura física
- **WHEN** el sondeo de lectura de la unidad excede el tiempo límite de 3 segundos en el hilo de trabajo
- **THEN** el sistema devuelve inmediatamente el estado `sin_respuesta` sin congelar el servidor ni la interfaz

### Requirement: Montaje controlado mediante udisksctl
El sistema SHALL permitir montar particiones removibles detectadas ejecutando exclusivamente `udisksctl mount -b <dispositivo>` mediante `subprocess.run` con lista fija de argumentos, previa confirmación visual que detalle el comando exacto a ejecutar.

#### Scenario: Montaje exitoso de unidad extraíble
- **WHEN** el usuario confirma montar una partición previamente detectada en estado no montado
- **THEN** el sistema invoca `udisksctl mount -b <dispositivo>`, valida el éxito y transiciona la unidad al estado montado correspondiente

#### Scenario: Rechazo de dispositivo no detectado o arbitrario
- **WHEN** una petición de montaje especifica una ruta o dispositivo que no figura en la lista de particiones removibles detectadas
- **THEN** el sistema rechaza la solicitud con error 400 y no ejecuta ningún comando en el sistema operativo

#### Scenario: Fallo de udisksctl o permisos Polkit
- **WHEN** `udisksctl` no está instalado en el sistema o la invocación falla por denegación de permisos de Polkit
- **THEN** el sistema captura el error sin caerse, lo presenta en pantalla y ofrece el comando manual equivalente junto con un botón para copiarlo al portapapeles

### Requirement: Desmontaje seguro y expulsión con precondiciones
El sistema SHALL proveer acciones para desmontar (`udisksctl unmount -b <dispositivo>`) y expulsar (`udisksctl power-off -b <disco_padre>`), prohibiendo parámetros forzados o diferidos (`-f`, `-l`), ejecutando `os.sync()` previamente y verificando precondiciones de no interferencia.

#### Scenario: Bloqueo de desmontaje por operaciones activas
- **WHEN** existe una transferencia en curso, un proceso de deshacer activo o archivos temporales `.part` en escritura
- **THEN** el sistema inhabilita las acciones de desmontaje y explica al usuario el motivo del bloqueo

#### Scenario: Desmontaje y expulsión eléctrica exitosa
- **WHEN** no hay operaciones activas y el usuario confirma "Desmontar y expulsar"
- **THEN** el sistema ejecuta `os.sync()`, luego `udisksctl unmount`, y solo tras el éxito ejecuta `udisksctl power-off`, confirmando que el dispositivo ya puede retirarse

#### Scenario: Unidad ocupada con inspección de procesos
- **WHEN** el desmontaje falla porque la unidad reporta estar ocupada (*target is busy*)
- **THEN** el sistema inspecciona de forma no destructiva `/proc/*/cwd` y `/proc/*/fd` de los procesos del usuario, lista los procesos identificados que retienen la unidad y recomienda su cierre sin forzar el desmontaje

### Requirement: Silenciamiento reactivo post-desmontaje y auditoría
El sistema SHALL silenciar el banner reactivo y suspender las lecturas de sondeo hacia una unidad desmontada o expulsada manualmente hasta su reconexión física o montaje explícito, y registrar cada acción en la bitácora local.

#### Scenario: Silenciamiento tras desmontaje manual
- **WHEN** el usuario completa un desmontaje o expulsión manual desde el panel
- **THEN** el sistema no vuelve a emitir el banner "Pendrive detectado" ni intenta leer la unidad hasta que desaparezca y vuelva a conectarse, o se pulse "Montar"

#### Scenario: Registro de eventos en bitácora
- **WHEN** se ejecuta una acción de montaje o desmontaje
- **THEN** el sistema escribe una entrada append-only en la bitácora con el nombre del evento, nodo de dispositivo, punto de montaje y resultado de la operación

### Requirement: Adaptación de plataforma y protección de endpoints
El sistema SHALL omitir los controles de montaje y desmontaje en entornos Windows, proteger las rutas de mutación mediante validación de cabecera Host, Content-Type JSON y CSRF, y garantizar estricta conformidad con las Reglas de Oro anti-borrado.

#### Scenario: Visualización en entorno Windows
- **WHEN** la aplicación se ejecuta sobre el sistema operativo Windows
- **THEN** la interfaz omite los botones de montaje y desmontaje indicando que la expulsión se realiza desde el explorador del sistema

#### Scenario: Protección CSRF y cabeceras en endpoints de control
- **WHEN** se envía una petición POST a `/api/pendrive/montar`, `/api/pendrive/desmontar` o `/api/pendrive/expulsar` sin token CSRF válido o cabecera Host inválida
- **THEN** el servidor rechaza la solicitud inmediatamente sin procesar ninguna acción
