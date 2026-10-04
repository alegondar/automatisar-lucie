# capitulo-solo-material-nuevo Specification

## Requirements

### Requirement: Adopción Temporal por Inicio de Capítulo
El sistema DEBE condicionar la adopción automática de archivos multimedia por parte de un capítulo activo a la fecha y hora de inicio (`fecha_inicio`) de dicho capítulo.

#### Scenario: Archivo posterior al inicio es adoptado
- **GIVEN** un capítulo activo con `fecha_inicio` $T_0$.
- **WHEN** se escanea un archivo multimedia con `st_mtime >= T_0`.
- **THEN** el archivo es asignado al capítulo activo, clasificado con el personaje y nombre de dicho capítulo, y agrupado en los lotes principales preseleccionados.

#### Scenario: Archivo anterior al inicio queda como material de respaldo
- **GIVEN** un capítulo activo con `fecha_inicio` $T_0$ y margen de 0 minutos.
- **WHEN** se escanea un archivo multimedia con `st_mtime < T_0`.
- **THEN** el archivo NO se asigna al capítulo activo, se mantiene en estado `detectado` y se agrupa en `lotes_anteriores` sin escena sugerida ni casillas marcadas.

### Requirement: Margen Configurable de Adopción
El sistema DEBE permitir configurar un margen de gracia en minutos previo al inicio del capítulo mediante la clave `minutos_antes_inicio_capitulo` en `config_bandeja.json`.

#### Scenario: Margen de gracia incluye archivos recientes inmediatos
- **GIVEN** `minutos_antes_inicio_capitulo` configurado en 10.
- **GIVEN** un capítulo iniciado a las 14:00.
- **WHEN** se escanea un archivo descargado a las 13:55 (5 minutos antes de las 14:00).
- **THEN** el archivo es adoptado por el capítulo activo al estar dentro del margen de 10 minutos.

#### Scenario: Archivo fuera del margen se clasifica como anterior
- **GIVEN** `minutos_antes_inicio_capitulo` configurado en 10.
- **GIVEN** un capítulo iniciado a las 14:00.
- **WHEN** se escanea un archivo descargado a las 13:45 (15 minutos antes).
- **THEN** el archivo se clasifica como anterior al capítulo y no se preselecciona.

### Requirement: Segregación en Panel UI ("Anteriores al capítulo")
La interfaz web DEBE presentar los lotes de material anterior en una sección colapsada independiente, garantizando que el usuario tenga control granular manual sin preselecciones invasivas.

#### Scenario: Despliegue de lotes anteriores
- **GIVEN** existen archivos anteriores al capítulo activo.
- **WHEN** se carga o actualiza el panel web.
- **THEN** los lotes correspondientes aparecen dentro de un contenedor colapsable rotulado "Anteriores al capítulo", con todas las casillas de archivos destildadas y sin nombre de escena precargado en los campos de texto.

### Requirement: Exclusión de Lotes Anteriores en Movimientos Masivos
La acción "Mover lotes listos" DEBE operar únicamente sobre los lotes del capítulo activo (material nuevo).

#### Scenario: Traslado masivo seguro
- **GIVEN** lotes activos listos y lotes en la sección "Anteriores al capítulo".
- **WHEN** el usuario pulsa "Mover lotes listos".
- **THEN** únicamente los lotes del capítulo activo marcados son simulados y preparados para el traslado; ningún archivo ni lote anterior es incluido automáticamente.

### Requirement: Base de Nombre Compacta
Al calcular la base para el renombrado automático de archivos, el sistema DEBE suprimir los espacios internos y caracteres de separación visual, manteniendo el nombre de carpeta tal como lo especificó el usuario.

#### Scenario: Escena con espacios internos
- **GIVEN** un lote asignado al personaje `lucie` con escena `lucie trapitos`.
- **WHEN** se calcula la base del archivo y se simula el traslado.
- **THEN** la base del archivo resultante es `lucietrapitos` (ej. `lucietrapitos1.jpg`).
- **AND** la carpeta en el destino conserva la denominación `lucie trapitos`.
- **AND** `obtener_personaje_de_alias_inicial("lucietrapitos1.jpg")` devuelve `lucie`.
