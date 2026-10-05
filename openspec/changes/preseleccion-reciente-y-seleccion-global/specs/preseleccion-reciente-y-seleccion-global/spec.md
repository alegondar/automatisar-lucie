# Spec Delta: preseleccion-reciente-y-seleccion-global

## Purpose

Define las reglas de negocio para la preselección de archivos recientes, segregación de material anterior en modo respaldo, botones de selección global en el panel, validación diferida de nombres de escena y detección no bloqueante de duplicados con insignia explicativa.

## ADDED Requirements

### Requirement: Ventana de material reciente por defecto
El sistema DEBE (SHALL) configurar `horas_material_reciente` con un valor predeterminado de 168 horas (7 días). Un valor configurado en 0 DEBE (SHALL) interpretarse como criterio desactivado.

#### Scenario: Valor predeterminado activo
- **WHEN** se inicializa la configuración sin valor explícito de `horas_material_reciente`
- **THEN** el sistema establece 168 horas como ventana de material reciente

#### Scenario: Criterio desactivado con valor cero
- **WHEN** la configuración especifica `horas_material_reciente` igual a 0
- **THEN** el sistema desactiva el corte por antigüedad en modo respaldo y trata todos los archivos como recientes

### Requirement: Segregación y partición de material anterior en modo respaldo
Cuando no hay capítulo en foco, cualquier archivo cuya fecha de llegada (`obtener_fecha_llegada`) sea anterior a `ahora - horas_material_reciente * 3600` DEBE (SHALL) segregarse a la sección colapsada "Anteriores", con checkboxes destildados y sin escena precargada. Un lote que mezcle archivos recientes y anteriores DEBE (SHALL) dividirse en dos lotes independientes.

#### Scenario: Archivo anterior segregado y destildado
- **WHEN** se detecta un archivo con más de 168 horas de antigüedad sin capítulo en foco
- **THEN** el archivo se incluye en `lotes_anteriores`, destildado por defecto y sin escena precargada

#### Scenario: Partición de lote mixto
- **WHEN** un lote contiene archivos recientes y archivos con antigüedad mayor a 168 horas
- **THEN** el agrupador genera dos lotes separados: uno principal con los recientes y otro en anteriores con los viejos

### Requirement: Preservación del corte con capítulo en foco
Cuando existe un capítulo en foco, el criterio de corte temporal DEBE (SHALL) depender exclusivamente de la fecha de inicio del capítulo, sin ser afectado por `horas_material_reciente`.

#### Scenario: Capítulo en foco mantiene su corte propio
- **WHEN** un capítulo está activo en foco
- **THEN** los archivos con fecha de llegada posterior a su fecha de inicio se consideran nuevos y tildados, independientemente de `horas_material_reciente`

### Requirement: Exclusión de anteriores en Mover lotes listos
La acción "Mover lotes listos" DEBE (SHALL) evaluar únicamente los lotes recientes con escena válida de la sección principal, excluyendo absolutamente todos los lotes de la sección "Anteriores".

#### Scenario: Mover lotes listos ignora anteriores
- **WHEN** el usuario pulsa "Mover lotes listos" habiendo lotes con alias en "Anteriores"
- **THEN** la simulación generada solo incluye los lotes principales recientes con escena válida

### Requirement: Botones globales de selección de lotes
La interfaz DEBE (SHALL) proporcionar controles "Seleccionar todo", "Ninguno" y un contador "X archivos seleccionados de Y" sobre los lotes principales, actualizando checkboxes individuales, checkbox maestro y contadores de lote sin afectar la sección "Anteriores".

#### Scenario: Seleccionar todo en sección principal
- **WHEN** el usuario pulsa "Seleccionar todo"
- **THEN** se tildan todos los archivos de los lotes principales y se actualiza el contador global sin modificar "Anteriores"

#### Scenario: Ninguno en sección principal
- **WHEN** el usuario pulsa "Ninguno"
- **THEN** se destildan todos los archivos de los lotes principales y el contador refleja 0 seleccionados

### Requirement: Validación diferida del nombre de escena
El mensaje de advertencia "El nombre de la escena no puede estar vacío" NO DEBE (SHALL) mostrarse durante la carga inicial ni al escribir desde un campo vacío; DEBE (SHALL) mostrarse únicamente al abandonar el campo vacío (`blur`) o al intentar mover el lote.

#### Scenario: Carga inicial sin mensaje de error
- **WHEN** se renderiza un lote con campo de escena nueva vacío
- **THEN** el mensaje de error de escena vacía permanece oculto

#### Scenario: Intento de mover sin escena muestra error
- **WHEN** el usuario intenta mover un lote con escena nueva vacía o sale del campo sin escribir
- **THEN** se visualiza el mensaje de error "El nombre de la escena no puede estar vacío"

### Requirement: Detección e insignia de archivos duplicados
El sistema DEBE (SHALL) calcular el hash SHA-256 en segundo plano sin bloquear la respuesta del servidor web e identificar archivos cuyo contenido coincida con otro archivo listado, movido previamente o enviado al pendrive. Todo archivo duplicado DEBE (SHALL) presentarse destildado por defecto y con una insignia "Duplicado" indicando la coincidencia.

#### Scenario: Archivo duplicado marcado y destildado
- **WHEN** se detecta un archivo cuyo SHA-256 coincide con un archivo ya registrado en la base de datos o listado
- **THEN** el archivo muestra la insignia "Duplicado", se destilda por defecto y expone con cuál archivo coincide
