# Spec Delta

## Purpose

Permite trabajar múltiples historias en paralelo mediante la coexistencia de varios capítulos abiertos, manteniendo predecible la ingesta automática de descargas al asignar el nuevo material exclusivamente a un único capítulo designado en foco.

## ADDED Requirements

### Requirement: Coexistencia de múltiples capítulos abiertos
El sistema DEBE (SHALL) permitir que coexistan múltiples capítulos con estado abierto ('activo') en la base de datos sin cancelarse ni cerrarse entre sí al iniciar nuevos capítulos.

#### Scenario: Iniciar un nuevo capítulo manteniendo los previos abiertos
- **WHEN** el usuario inicia un nuevo capítulo mientras ya existen uno o más capítulos abiertos
- **THEN** el nuevo capítulo se registra con estado abierto, los capítulos previos continúan con estado abierto, y se crea la carpeta del nuevo capítulo en disco

#### Scenario: Restricción de unicidad para el foco
- **WHEN** se intenta registrar o actualizar más de un capítulo con `en_foco = 1`
- **THEN** la base de datos rechaza la operación mediante el índice único parcial `idx_capitulo_en_foco`

### Requirement: Asignación automática restringida al capítulo en foco
El escaneo automático de nuevas descargas DEBE (SHALL) asignar material entrante exclusivamente al capítulo que se encuentre marcado `en_foco = 1`, utilizando su fecha de inicio como límite temporal.

#### Scenario: Detección con capítulo en foco
- **WHEN** ingresa un archivo multimedia posterior a la fecha de inicio del capítulo en foco
- **THEN** el sistema lo asigna automáticamente al personaje y nombre del capítulo en foco, preseleccionándolo en un lote activo

#### Scenario: Detección sin capítulo en foco
- **WHEN** existen capítulos abiertos pero ninguno está en foco y entra nuevo material
- **THEN** el sistema no preasigna los archivos a ningún capítulo y aplica el modo de respaldo por alias de personaje al inicio

### Requirement: Gestión atómica del foco entre capítulos abiertos
El sistema DEBE (SHALL) proporcionar una acción explícita para trasladar el foco a cualquier capítulo abierto en una única transacción atómica, sin reasignar retroactivamente los archivos ya detectados.

#### Scenario: Cambio de foco exitoso
- **WHEN** el usuario solicita poner en foco un capítulo abierto que no tenía foco
- **THEN** el capítulo previamente en foco pasa a `en_foco = 0`, el capítulo indicado pasa a `en_foco = 1`, y los lotes previamente generados conservan sus asignaciones intactas

#### Scenario: Poner en foco capítulo cerrado o inexistente
- **WHEN** se solicita poner en foco un capítulo cerrado, descartado o inexistente
- **THEN** el sistema rechaza la solicitud con un error explícito y no altera el foco actual

### Requirement: Asignación manual a capítulos abiertos sin foco
Los capítulos abiertos que no se encuentran en foco DEBEN (SHALL) poder recibir archivos seleccionados manualmente por el usuario mediante el desplegable de escena en cualquier lote.

#### Scenario: Envío manual a capítulo abierto secundario
- **WHEN** el usuario selecciona en un lote la opción de un capítulo abierto sin foco y confirma el movimiento
- **THEN** los archivos se mueven con simulación previa obligatoria y se incrementa el contador de archivos movidos de ese capítulo específico

### Requirement: Desplegable de escenas con priorización de foco y abiertos
El desplegable de selección de escena en cada lote DEBE (SHALL) mostrar como primera opción preseleccionada el capítulo en foco, seguido de los capítulos abiertos sin foco, evitando duplicados.

#### Scenario: Renderizado del selector con capítulo en foco y abiertos
- **WHEN** el panel renderiza los lotes de candidatos con un capítulo en foco y otros capítulos abiertos
- **THEN** la primera opción seleccionada es `[Capítulo en foco] <nombre>`, las siguientes opciones muestran `[Capítulo abierto] <personaje>/<nombre>`, y no se duplican entradas en `[Destino]` para esas mismas carpetas

### Requirement: Pestaña de Capítulos Abiertos y visualización en panel
El panel web DEBE (SHALL) incluir una pestaña dedicada "Capítulos Abiertos (N)" en la barra superior y reflejar el estado del foco en el banner superior.

#### Scenario: Visualización de lista de capítulos abiertos
- **WHEN** el usuario accede a la pestaña "Capítulos Abiertos"
- **THEN** se muestra una tabla con personaje, nombre, fecha de inicio, archivos movidos, indicador visual del capítulo en foco, y botones por fila para poner en foco, terminar y descartar

#### Scenario: Banner superior con capítulo en foco y enlaces
- **WHEN** hay un capítulo en foco y además otros capítulos abiertos
- **THEN** el banner superior muestra el capítulo en foco con su balance y un enlace o botón `+N capítulos abiertos` que conduce a la pestaña correspondiente

### Requirement: Cierre, reapertura y descarte independiente por identificador
Las operaciones de terminar, reabrir y descartar capítulos DEBEN (SHALL) operar mediante su identificador numérico sin afectar a otros capítulos abiertos.

#### Scenario: Terminar el capítulo en foco
- **WHEN** se termina el capítulo que estaba en foco
- **THEN** el capítulo pasa a estado cerrado, el foco queda vacío sin transferirse automáticamente a otro capítulo, y el banner sugiere seleccionar un nuevo capítulo en foco

#### Scenario: Reabrir capítulo cerrado
- **WHEN** se reabre un capítulo cerrado mientras otro ya está en foco
- **THEN** el capítulo reabierto pasa a estado abierto con `en_foco = 0`, asegurando su carpeta física en disco sin despojar del foco al capítulo actual

#### Scenario: Descartar capítulo secundario
- **WHEN** se descarta un capítulo abierto que no estaba en foco
- **THEN** su carpeta se traslada a `_descartados`, se marca descartado en la base de datos y el capítulo en foco no sufre alteraciones

### Requirement: Evaluación de alertas y endpoints de API
La API DEBE (SHALL) exponer endpoints para consultar y modificar capítulos abiertos y el estado de foco, validando seguridad CSRF y restringiendo la alerta de inactividad al capítulo en foco.

#### Scenario: Consulta de estado y lista de abiertos
- **WHEN** se realiza una petición a `GET /api/capitulos/abiertos` o `GET /api/capitulos/estado`
- **THEN** la respuesta incluye la lista de capítulos abiertos, la cantidad total y el objeto del capítulo en foco

#### Scenario: Cambio de foco vía API con protección CSRF
- **WHEN** se envía una petición `POST /api/capitulos/en-foco` con token CSRF válido y el ID de un capítulo abierto
- **THEN** la API actualiza el foco atómicamente y responde con éxito en formato JSON

#### Scenario: Rechazo de petición sin token CSRF
- **WHEN** se envía un `POST /api/capitulos/en-foco` sin cabecera `X-CSRF-Token` válida
- **THEN** el servidor responde inmediatamente con código de error HTTP 403 Forbidden
