# Spec Delta

## Purpose

Permite adoptar manualmente archivos sin patrón conocido desde la sección "Sin Identificar" a la sección principal de "Lotes Detectados" mediante "Del Proyecto" con precedencia sobre cortes temporales, soporte completo de reversión inmediata ("Deshacer"), feedback visible sin silenciamiento de errores, y operación de SQLite en modo WAL con `busy_timeout` para evitar bloqueos concurrentes.

## ADDED Requirements

### Requirement: Adopción explícita de archivos con prioridad sobre corte temporal
El sistema SHALL permitir adoptar archivos de la sección "Sin Identificar" marcándolos como "Del Proyecto", incorporándolos a la sección PRINCIPAL de Lotes Detectados independientemente de su fecha de llegada o de la fecha de inicio del capítulo en foco, con la insignia "Adoptado a mano", checkbox seleccionado por defecto, sin asumir personaje ni escena por alias, y ofreciendo en el selector de escenas todas las opciones disponibles (incluyendo la del capítulo en foco).

#### Scenario: Adopción de archivo anterior al capítulo en foco o al corte de material reciente
- **WHEN** un archivo sin alias conocido que llegó antes del inicio del capítulo en foco o antes del corte de horas de material reciente es adoptado haciendo clic en "Del Proyecto"
- **THEN** el sistema lo incorpora en la sección PRINCIPAL de Lotes Detectados y NO en "Anteriores", con insignia "Adoptado a mano", tildado para mover, y sin escena ni personaje preseleccionados

#### Scenario: Selector de escenas para archivo adoptado
- **WHEN** se visualiza el lote de un archivo adoptado a mano en la interfaz
- **THEN** el desplegable de escenas muestra todas las opciones disponibles del proyecto (incluida la escena del capítulo en foco si existe), pero permanece sin preselección hasta que el usuario elija una

### Requirement: Retroalimentación inmediata y reversión con Deshacer en panel web
El sistema SHALL remover inmediatamente la fila de "Sin Identificar" tras hacer clic en "Del Proyecto" o "Ignorar", exhibiendo un banner o toast con mensaje informativo y botón "Deshacer" funcional que devuelva el archivo a "Sin Identificar", actualizando el token de versión del vigilante e informando en pantalla cualquier error de servidor sin silenciarlo.

#### Scenario: Clic en Del Proyecto con retroalimentación y deshacer
- **WHEN** el usuario hace clic en "Del Proyecto" sobre un archivo en "Sin Identificar"
- **THEN** la fila sale inmediatamente de la tabla, aparece un aviso "Agregado a Lotes Detectados" con enlace a dicha sección y botón "Deshacer", y el listado de lotes se refresca de inmediato

#### Scenario: Reversión mediante botón Deshacer
- **WHEN** el usuario pulsa "Deshacer" en el aviso de confirmación de "Del Proyecto" o "Ignorar"
- **THEN** el sistema invoca la reversión en el servidor (`POST /api/deshacer-clasificar-sin-identificar`), elimina la decisión previa y devuelve el archivo a la lista de "Sin Identificar" intacto

#### Scenario: Fallo o error en la petición del servidor
- **WHEN** una petición al servidor al clasificar o deshacer falla o devuelve un error
- **THEN** la interfaz muestra el error exacto en pantalla de manera destacada sin silenciarlo

### Requirement: Persistencia de decisiones y soporte de endpoint de reversión
El sistema SHALL persistir las decisiones de clasificación e ignorado por hash y ruta en SQLite, y proveer un endpoint seguro (`POST /api/deshacer-clasificar-sin-identificar`) protegido por Host y CSRF para revertir la decisión y refrescar reactivamente el vigilante.

#### Scenario: Reversión de decisión en la base de datos
- **WHEN** se recibe una solicitud válida en `POST /api/deshacer-clasificar-sin-identificar` con el hash y ruta del archivo
- **THEN** la base de datos elimina o limpia la decisión asociada, el vigilante actualiza su estado interno y el token de versión se incrementa inmediatamente

### Requirement: Robustez y concurrencia SQLite en modo WAL
El sistema SHALL configurar `PRAGMA journal_mode=WAL;` y `PRAGMA busy_timeout=5000;` en todas las aperturas de base de datos SQLite (`bandeja.db` y cachés de inventario), permitiendo lecturas concurrentes sin generar excepciones de base de datos bloqueada (`database is locked`).

#### Scenario: Lecturas concurrentes durante operaciones de escritura
- **WHEN** procesos o hilos externos leen concurrentemente la base de datos mientras se ejecutan transacciones de escritura
- **THEN** las lecturas proceden sin bloquearse y no se lanzan excepciones de `database is locked`
