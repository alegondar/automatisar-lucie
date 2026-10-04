# Design

## Context

El panel de la bandeja de descargas (`bandeja_descargas.py`) agrupa archivos de video e imágenes descargados para clasificarlos ordenadamente en `<destino>/<personaje>/<escena>/`. Anteriormente se introdujo un concepto preliminar de capítulo activo, pero requería un ciclo de vida formal: permitir iniciar una sesión de rodaje/descargas, canalizar todos los archivos entrantes del proyecto a dicho capítulo independientemente del alias del nombre, advertir si un capítulo quedó olvidado por más de 12 horas, mostrar un balance claro (pendientes vs. movidos) al momento de terminarlo con opciones de mover o cerrar sin mover, y posibilitar la reapertura de capítulos cerrados sin reasignar retroactivamente archivos ya detectados.

## Goals / Non-Goals

**Goals:**
- Proporcionar un ciclo de vida completo de capítulos: Empezar, Monitorear con Banner Fijo, Terminar con Balance, Reabrir y Alerta de Olvido.
- Asignación unificada: todo archivo candidato detectado mientras haya un capítulo activo se asigna a `<personaje_capitulo>/<nombre_capitulo>`, sin importar los alias contenidos en el nombre.
- Balance informativo de cierre: mostrar la cantidad de archivos pendientes y ya movidos al terminar.
- Opciones de finalización claras: "Mover pendientes y terminar" (mediante simulación previa obligatoria) o "Terminar sin mover" (cierra el capítulo y deja los archivos en Descargas).
- Alerta por inactividad prolongada (>12 horas configurable en `config_bandeja.json`) con acciones para continuar o cerrar.
- Historial y reapertura: consultar capítulos cerrados y reactivarlos a demanda.
- Persistencia robusta en SQLite (`bandeja_capitulos`) sin reasignaciones retroactivas.

**Non-Goals:**
- Modificar el comportamiento de la sala de espera unificada (videos y fotos conviven en la misma carpeta de escena).
- Reasignar retroactivamente archivos detectados previamente cuando se inicia, cierra o reabre un capítulo.
- Eliminar o limpiar archivos de capítulos antiguos (prohibición absoluta según Regla de Oro 1).

## Decisions

### 1. Modelo de Datos SQLite: Tabla `bandeja_capitulos`
- **Decisión**: Reemplazar la tabla básica previa por una tabla estructurada `bandeja_capitulos` con:
  ```sql
  CREATE TABLE IF NOT EXISTS bandeja_capitulos (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      personaje TEXT NOT NULL,
      nombre TEXT NOT NULL,
      estado TEXT NOT NULL CHECK(estado IN ('activo', 'cerrado')),
      fecha_inicio TEXT NOT NULL,
      fecha_fin TEXT,
      fecha_ultimo_aviso TEXT,
      archivos_movidos INTEGER DEFAULT 0
  );
  CREATE UNIQUE INDEX IF NOT EXISTS idx_capitulo_unico_activo 
  ON bandeja_capitulos(estado) WHERE estado = 'activo';
  ```
- **Razón**: El índice único parcial garantiza a nivel motor de base de datos que jamás coexistirán dos capítulos activos simultáneos.
- **Alternativa descartada**: Manejar el estado activo únicamente en memoria o en un archivo JSON volátil, lo que causaría inconsistencias si el proceso se reinicia.

### 2. Detección y Asociación Universal de Archivos
- **Decisión**: En `GestorBaseDatosBandeja.registrar_archivo()`, al detectar un nuevo archivo candidato, si existe un capítulo activo, se asigna `personaje = capitulo.personaje` y `escena = capitulo.nombre`.
- **Razón**: Permite al usuario descargar material diverso (Lucie, Roli, tomas compartidas) sabiendo que pertenecerán a la historia activa sin tener que editar cada lote a mano.
- **Alternativa descartada**: Intentar adivinar subpersonajes o dividir en múltiples lotes dentro de una misma sesión de capítulo.

### 3. Diálogo de Terminación y Acciones de Cierre
- **Decisión**: Al presionar "Terminar capítulo", el backend calcula:
  - `pendientes`: archivos detectados asignados al capítulo que siguen en `~/Descargas`.
  - `movidos`: cantidad de archivos ya trasladados a la carpeta del capítulo.
  La interfaz muestra el diálogo con ambas cifras y botones:
  - "Mover pendientes y terminar": lanza la simulación previa habitual (`dry-run`). Tras la confirmación del usuario, traslada los archivos y ejecuta el cierre del capítulo.
  - "Terminar sin mover": llama a `/api/capitulos/terminar` con acción `sin_mover`. El capítulo se marca como 'cerrado' y los pendientes quedan en la bandeja sin capítulo activo.
- **Razón**: Respeta de forma estricta las Reglas de Oro 2 (Simulación previa obligatoria) y 3 (Aprobación granular), sin obligar al usuario a mover archivos si prefiere revisarlos luego.

### 4. Alerta de Capítulo Olvidado (>12h)
- **Decisión**: Al consultar el estado del capítulo activo (`/api/capitulos/estado`), el backend computa la diferencia horaria entre la hora actual y `max(fecha_inicio, fecha_ultimo_aviso)`. Si excede `horas_alerta_capitulo_olvidado` (por defecto 12), retorna `alerta_olvidado: true`. La interfaz despliega un banner de advertencia con:
  - "Seguir": llama a `/api/capitulos/posponer_alerta` actualizando `fecha_ultimo_aviso` a la hora actual.
  - "Terminar": abre el modal de balance y terminación.
- **Razón**: Evita que una sesión abandonada siga capturando archivos descargados días después por accidente.

### 5. Catálogo de Capítulos Cerrados y Reapertura
- **Decisión**: Nueva sección o vista en la SPA que consulta `/api/capitulos/cerrados`. Cada capítulo cerrado muestra su fecha, personaje, nombre, archivos movidos y botón "Reabrir". Al reabrir, si no hay otro activo, pasa a `estado = 'activo'`, `fecha_fin = NULL` y `fecha_ultimo_aviso = NULL`. Si ya había uno activo, el backend rechaza la solicitud indicando que debe cerrarse el actual primero.
- **Razón**: Ofrece flexibilidad total para sesiones de rodaje que se extienden en múltiples jornadas.

## Risks / Trade-offs

- **[Riesgo]** Intentar reabrir un capítulo cuando ya hay otro activo.  
  → **Mitigación**: El endpoint verifica la existencia de un capítulo activo y devuelve error HTTP 409 / mensaje claro en JSON solicitando cerrar el activo antes de reabrir otro.
- **[Riesgo]** Fallo de red durante "Mover pendientes y terminar".  
  → **Mitigación**: La operación de mover conserva su naturaleza atómica por lote y bitácora `.jsonl`. El cierre solo se registra tras completarse el traslado exitoso.
- **[Riesgo]** Violación accidental de Reglas de Oro anti-borrado.  
  → **Mitigación**: No se implementa ninguna llamada de borrado; los tests estáticos AST del proyecto validan 0 violaciones en todo momento.
