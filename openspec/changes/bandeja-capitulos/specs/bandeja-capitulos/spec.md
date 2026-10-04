# Spec Delta

## Purpose

Permite gestionar el ciclo de vida completo de capítulos en la bandeja de descargas, coordinando el inicio, asignación universal de archivos del proyecto, balance de archivos al cerrar, reapertura y alertas por tiempo transcurrido.

## ADDED Requirements

### Requirement: Empezar capítulo activo con asignación universal
El sistema SHALL permitir iniciar un capítulo indicando el personaje destino y el nombre del capítulo. Solo SHALL permitirse un único capítulo activo en simultáneo. Todo archivo candidato del proyecto detectado en Descargas durante su vigencia SHALL asignarse automáticamente a la carpeta de dicho capítulo y personaje, independientemente de los alias presentes en su nombre.

#### Scenario: Inicio exitoso de capítulo activo
- **WHEN** el usuario selecciona el personaje "lucie", ingresa el nombre de capítulo "paseo al lago" y pulsa "Empezar capítulo"
- **THEN** el sistema registra el capítulo como activo y rechaza el inicio concurrente de otro capítulo sin cerrar el previo

#### Scenario: Asignación universal de archivos al capítulo activo
- **WHEN** arriba a la carpeta de descargas un archivo candidato con prefijo "roli_baile.mp4" mientras "lucie/paseo al lago" está activo
- **THEN** el archivo queda asignado al lote correspondiente al capítulo activo con destino "lucie/paseo al lago"

#### Scenario: Capítulo de personaje roli recibe archivo lucie
- **WHEN** el capítulo activo pertenece al personaje "roli" ("roli/gimnasio") y arriba a descargas un archivo candidato "lucie_pesas.mp4"
- **THEN** el archivo queda asignado al capítulo activo con destino "roli/gimnasio"

### Requirement: Banner de capítulo activo permanente
Mientras exista un capítulo activo, la interfaz SHALL mostrar en la parte superior un banner fijo visible que indique "Capítulo activo: <personaje>/<capítulo>" junto al botón de acción "Terminar capítulo".

#### Scenario: Visualización del banner superior
- **WHEN** se carga o actualiza la interfaz web y existe un capítulo activo
- **THEN** se muestra un banner superior fijo con el texto del personaje, nombre del capítulo y el botón "Terminar capítulo"

### Requirement: Terminar capítulo con balance y opciones de cierre
Al solicitar terminar el capítulo, el sistema SHALL mostrar un resumen indicando la cantidad de archivos pendientes y la cantidad de archivos ya movidos. SHALL ofrecer dos opciones de resolución: "Mover pendientes y terminar" (que ejecuta la simulación previa habitual antes de mover) y "Terminar sin mover" (que cierra el capítulo de inmediato dejando los archivos pendientes sin modificar). Al cerrarse, los archivos posteriores no se asignan a este capítulo.

#### Scenario: Terminar sin mover
- **WHEN** el usuario pulsa "Terminar capítulo", observa el balance y selecciona "Terminar sin mover"
- **THEN** el capítulo pasa a estado cerrado, los archivos pendientes permanecen en Descargas y los archivos posteriores no se asignan a este capítulo

#### Scenario: Mover pendientes y terminar con simulación
- **WHEN** el usuario pulsa "Terminar capítulo" y selecciona "Mover pendientes y terminar"
- **THEN** el sistema abre la ventana de simulación previa habitual de los pendientes y solo tras la confirmación traslada los archivos y marca el capítulo como cerrado

#### Scenario: Cierre de asignación para archivos posteriores
- **WHEN** un capítulo es cerrado y posteriormente se detecta un nuevo archivo candidato en Descargas
- **THEN** el nuevo archivo no se asigna al capítulo cerrado y se canaliza según las reglas sin capítulo activo

#### Scenario: Precisión del balance de pendientes y movidos
- **WHEN** existen 3 archivos pendientes en Descargas y 2 archivos ya trasladados al destino del capítulo
- **THEN** el balance de terminación reporta exactamente 3 pendientes y 2 movidos

### Requirement: Reabrir capítulos cerrados
El sistema SHALL mantener un catálogo de capítulos previamente cerrados y permitir al usuario reabrir cualquiera de ellos mediante un botón "Reabrir". Al reabrirse, el capítulo pasa a ser el único capítulo activo y recibe nuevamente las descargas posteriores.

#### Scenario: Reapertura de capítulo cerrado
- **WHEN** el usuario consulta el listado de capítulos cerrados y pulsa "Reabrir" en un capítulo específico
- **THEN** el capítulo seleccionado pasa a estado activo, se muestra nuevamente en el banner superior y las nuevas detecciones se le asignan

#### Scenario: Reapertura permite asignar de nuevo
- **WHEN** un capítulo cerrado es reabierto y posteriormente arriba a Descargas un nuevo archivo candidato
- **THEN** el nuevo archivo se asigna automáticamente al capítulo reabierto

### Requirement: Alerta de capítulo olvidado por tiempo prolongado
Si un capítulo activo supera el límite configurado de horas continuas (por defecto 12 horas), el sistema SHALL presentar un aviso destacado preguntando "¿Sigue activo este capítulo?" con opciones para "Seguir" o "Terminar".

#### Scenario: Detección y confirmación de capítulo que continúa
- **WHEN** un capítulo activo tiene una antigüedad mayor a las horas configuradas y el usuario pulsa "Seguir"
- **THEN** el sistema renueva la marca temporal del aviso y mantiene el capítulo como activo sin interrumpir la sesión

#### Scenario: Terminación desde la alerta de capítulo olvidado
- **WHEN** se visualiza la alerta de capítulo olvidado y el usuario pulsa "Terminar"
- **THEN** se abre el diálogo de balance y terminación del capítulo

#### Scenario: Aviso aparece a las 12 horas con reloj simulado
- **WHEN** un capítulo activo cumple o excede 12 horas desde su inicio o último aviso evaluado con reloj simulado
- **THEN** el sistema retorna la alerta activa de capítulo olvidado

### Requirement: Persistencia y estabilidad de asignaciones
El estado de los capítulos (activo, cerrados, fechas y contador de movimientos) SHALL almacenarse en SQLite y persistir ante reinicios del servicio. Cambiar, cerrar o reabrir capítulos SHALL NOT alterar ni reasignar los archivos que ya hubiesen sido detectados previamente.

#### Scenario: Persistencia ante reinicio del servidor
- **WHEN** se detiene y vuelve a iniciar el proceso de la bandeja de descargas
- **THEN** el capítulo activo y el historial de capítulos cerrados se recuperan íntegramente de la base de datos

#### Scenario: No reasignación retroactiva
- **WHEN** se cierra un capítulo o se activa uno nuevo
- **THEN** los archivos detectados y agrupados con anterioridad conservan sus destinos asignados sin alteración
