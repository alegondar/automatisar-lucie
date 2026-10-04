# Design: Capítulos Abiertos Múltiples y Gestión de Foco

## Context

Actualmente `bandeja_descargas.py` almacena los capítulos en la tabla SQLite `bandeja_capitulos` con `CHECK(estado IN ('activo', 'cerrado'))`. El índice único `idx_capitulo_unico_activo` impedía tener más de un capítulo en estado `'activo'`. El escaneo en `VigilanteBandeja` asumía que `obtener_capitulo_activo()` devolvía el único capítulo al cual preasignar material entrante. Para soportar múltiples historias simultáneas, el estado `'activo'` se reinterpreta como "abierto", complementándose con una columna `en_foco` para gobernar la ingesta automática.

Ver motivación y antecedentes en `proposal.md` y especificaciones en `specs/capitulos-abiertos-multiples/spec.md`.

## Goals / Non-Goals

**Goals:**
- Permitir la apertura simultánea de múltiples capítulos (`estado = 'activo'`).
- Garantizar a nivel de base de datos que como máximo un único capítulo abierto esté en foco (`en_foco = 1`) mediante un índice único parcial.
- Migración no destructiva en SQLite que conserve íntegros los datos existentes y marque el capítulo activo actual como en foco.
- Asignación automática por parte del vigilante restringida exclusivamente al capítulo en foco.
- Asignación manual granular a capítulos abiertos secundarios mediante el selector de escenas en cada lote, sin duplicados.
- Pestaña "Capítulos Abiertos (N)" en el frontend con tabla de control, indicador de foco y acciones rápidas por fila.
- Mantenimiento estricto de las 7 Reglas de Oro (sin primitivas de borrado, bitácora `.jsonl` reversible, 0 infracciones AST).

**Non-Goals:**
- Modificar el constraint `CHECK(estado IN ('activo', 'cerrado'))` o recrear la tabla `bandeja_capitulos`.
- Ingesta automática simultánea a múltiples capítulos (la asignación automática es estrictamente hacia el capítulo en foco).
- Traspaso automático de foco al cerrar o descartar el capítulo en foco (el foco queda deliberadamente vacío para que el usuario elija conscientemente el próximo objetivo).

## Decisions

### 1. Modelo de datos y migración segura en SQLite
- **Decisión**: Se mantiene `estado = 'activo'` para representar capítulos abiertos. Se agrega la columna `en_foco INTEGER DEFAULT 0` mediante `ALTER TABLE bandeja_capitulos ADD COLUMN en_foco INTEGER DEFAULT 0;`. Se elimina el índice `idx_capitulo_unico_activo` (`DROP INDEX IF EXISTS idx_capitulo_unico_activo;`) y se crea un índice único parcial:
  ```sql
  CREATE UNIQUE INDEX IF NOT EXISTS idx_capitulo_en_foco 
  ON bandeja_capitulos(en_foco) 
  WHERE en_foco = 1;
  ```
  Si existe un capítulo abierto con `en_foco = 0` y ningún otro con `en_foco = 1`, se actualiza el más reciente a `en_foco = 1`.
- **Alternativas consideradas**: Recrear la tabla con un nuevo enum `CHECK(estado IN ('abierto', 'cerrado'))`. Descartada porque recrear tablas en SQLite introduce riesgos de pérdida de datos y bloqueos innecesarios.

### 2. Transacción atómica para cambio de foco
- **Decisión**: El método `poner_capitulo_en_foco(id_capitulo)` ejecuta en una única transacción con lock:
  ```python
  with self._lock, self._conectar() as con:
      cur = con.cursor()
      cur.execute("UPDATE bandeja_capitulos SET en_foco = 0 WHERE en_foco = 1")
      cur.execute(
          "UPDATE bandeja_capitulos SET en_foco = 1 WHERE id = ? AND estado = 'activo' AND descartado = 0",
          (id_capitulo,)
      )
      if cur.rowcount == 0:
          raise ValueError(f"Capítulo con ID {id_capitulo} no encontrado o no está abierto.")
      con.commit()
  ```
- **Alternativas consideradas**: Dos llamadas separadas. Descartada por riesgo de violar temporalmente la unicidad o quedar inconsistente ante excepciones.

### 3. Ingesta automática y estabilidad de asignaciones
- **Decisión**: `VigilanteBandeja.escanear()` consulta `obtener_capitulo_en_foco()`. Si existe, su `fecha_inicio` actúa como corte temporal y el material nuevo se clasifica con su personaje y nombre. Si no hay capítulo en foco, el material nuevo se trata bajo el modo respaldo por alias al inicio. Los archivos ya detectados y registrados en `bandeja_archivos` conservan su asignación intacta aunque el foco cambie con posterioridad.
- **Razón**: Otorga estabilidad y predictibilidad; el usuario sabe que cambiar de foco no redistribuye archivos que ya estaban listados para mover.

### 4. Estructura del selector de escenas en los lotes
- **Decisión**: Al armar `<select id="sel-escena-...">`:
  1. Si hay capítulo en foco: `<option value="nombre_foco" data-tipo="capitulo_foco" selected>[Capítulo en foco] nombre_foco</option>`.
  2. Por cada capítulo abierto secundario: `<option value="nombre_abierto" data-tipo="capitulo_abierto" data-personaje="pers">[Capítulo abierto] pers/nombre_abierto</option>`.
  3. `<option value="__nueva__">+ Crear nueva escena...</option>`.
  4. Opciones de Descargas y Destino, filtrando aquellas cuyo nombre coincida con cualquier capítulo abierto para evitar duplicaciones confusas.

### 5. Frontend: Pestaña "Capítulos Abiertos" y sincronización de estado
- **Decisión**: Agregar en la barra superior un botón de pestaña:
  `<button class="tab-btn" onclick="mostrarTab('abiertos')">Capítulos Abiertos (<span id="conteo-tab-abiertos">0</span>)</button>`
  y su correspondiente sección contenedora con tabla renderizada dinámicamente.
  `/api/capitulos/estado` retornará:
  ```json
  {
    "capitulo_foco": { ... },
    "capitulos_abiertos": [ ... ],
    "cantidad_abiertos": 3
  }
  ```

## Risks / Trade-offs

- **[Riesgo] Intentar asignar foco a múltiples capítulos simultáneamente** → Mitigación: El índice parcial único en SQLite `idx_capitulo_en_foco WHERE en_foco = 1` garantiza a nivel de motor de persistencia que no puedan existir dos filas con `en_foco = 1`.
- **[Riesgo] Terminar el capítulo en foco deja el foco vacío** → Mitigación: Es el comportamiento deseado según las reglas de negocio; el banner superior mostrará claramente el aviso "Ningún capítulo en foco" y ofrecerá un botón para ir a la pestaña y seleccionar el nuevo foco.
- **[Riesgo] Peticiones POST de cambio de foco vulnerables a CSRF** → Mitigación: Se aplica la validación estricta de token anti-CSRF, cabeceras `Host` autorizadas y `Content-Type: application/json` en `/api/capitulos/en-foco`.
