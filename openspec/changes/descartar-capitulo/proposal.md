# Proposal: Descartar Capítulo Moviéndolo a `_descartados` con Deshacer Reversible

## Why
Actualmente en la bandeja de descargas (`bandeja_descargas.py`), un capítulo creado (ya sea el activo o uno cerrado en la sala de espera `~/Descargas/_lucie/<personaje>/<escena>/`) no cuenta con un mecanismo para ser descartado o apartado si el usuario decide cancelar la sesión o archivar material no deseado.
De acuerdo con las 7 Reglas de Oro del proyecto, está terminantemente prohibido borrar cualquier archivo o carpeta (`os.remove`, `shutil.rmtree`, etc.). Por lo tanto, descartar un capítulo debe realizarse mediante un traslado seguro y atómico con `os.rename` hacia una carpeta de cuarentena `~/Descargas/_lucie/_descartados/<personaje>/<escena>_<AAAAMMDD-HHMMSS>/`, con simulación previa obligatoria, confirmación por tipeo exacto, registro auditable en la bitácora `.jsonl` y capacidad estricta de deshacer (`deshacer_operacion`).

## What Changes
1. **Acción "Descartar capítulo":**
   - Disponible para el capítulo activo (botón secundario en su banner junto a "Terminar capítulo") y para cada capítulo en la lista de "Capítulos Cerrados".
   - Mueve atómicamente la carpeta `~/Descargas/_lucie/<personaje>/<escena>/` a `~/Descargas/_lucie/_descartados/<personaje>/<escena>_<AAAAMMDD-HHMMSS>/` usando un único `os.rename`.
2. **Simulación previa y confirmación estricta:**
   - Modal informativo con origen, destino proyectado, total de archivos, peso acumulado y la advertencia explícita: *"Esto NO borra: mueve a _descartados y se puede deshacer"*.
   - La confirmación exige escribir el nombre exacto del capítulo en un campo de texto; si no coincide, el botón se bloquea y la API rechaza la petición.
3. **Confinamiento estricto y resolución de colisiones:**
   - Ambas rutas (`origen` y `destino`) deben permanecer confinadas dentro de `~/Descargas/_lucie` (validado mediante `os.path.realpath`).
   - Se rechazan terminantemente symlinks salientes y secuencias de path traversal (`..`).
   - Si la carpeta de destino ya existe, se añade un sufijo correlativo ` (1)`, ` (2)` sin sobrescribir nunca.
4. **Manejo de carpetas inexistentes o vacías:**
   - Si la carpeta en disco no existe o está vacía, el capítulo se marca como descartado en la base de datos sin invocar `os.rename`, informándolo en la respuesta.
5. **Cierre automático del capítulo activo:**
   - Si el capítulo descartado era el activo, se desactiva inmediatamente (`guardar_capitulo_activo("", "", False)`), deteniendo la asignación automática de material nuevo.
6. **Migración segura de Base de Datos:**
   - Se añade la columna `descartado INTEGER DEFAULT 0` y `fecha_descartado TEXT` a `bandeja_capitulos` mediante migración segura (`ALTER TABLE` condicional), preservando el constraint `CHECK(estado IN ('activo', 'cerrado'))` y todos los datos históricos.
   - Los capítulos descartados se excluyen de "Capítulos Cerrados" y se muestran en una nueva sección "Descartados".
   - En `bandeja_archivos`, se actualiza la `ruta_actual` y el estado a `'descartado'` para los archivos afectados.
7. **Registro en Bitácora:**
   - Se añade un evento `descartar_capitulo` en `bitacora_bandeja.jsonl` con `id_operacion`, `capitulo_id`, `personaje`, `escena`, `origen_carpeta`, `destino_carpeta`, `total_archivos`, `peso_total` y `fecha`.
8. **Deshacer reversible estricto:**
   - `deshacer_operacion` restaura la carpeta descartada a su origen original con `os.rename`.
   - Si la ruta de origen original está ocupada, la reversión se NIEGA rotundamente sin pisar ni sufijar.
   - Restaura el estado en SQLite a `descartado = 0, estado = 'cerrado'` y actualiza `bandeja_archivos`.
   - Se expone la opción "Deshacer" en el banner superior y en la pestaña "Historial".
9. **Endpoints HTTP seguros:**
   - `POST /api/capitulos/descartar-simular`: Simulación previa.
   - `POST /api/capitulos/descartar`: Ejecución del descarte con confirmación.
   - Ambos protegidos con validación de cabecera Host, Content-Type JSON y token anti-CSRF.
10. **Aislamiento de `_descartados`:**
    - La carpeta `_descartados` nunca es leída como escena ni ofrecida como sugerencia de destino.

## Capabilities

### New Capabilities
- `descartar-capitulo`: Cuarentena atómica de capítulos a `_descartados` con simulación previa, confirmación por nombre, confinamiento de rutas, bitácora y reversibilidad estricta.

## Impact
- **Código operativo:** `bandeja_descargas.py`: Métodos en `GestorBaseDatosBandeja`, `GestorMovimientosBandeja`, `HandlerServidorBandeja` y frontend HTML/CSS/JS.
- **Persistencia:** Migración en tabla `bandeja_capitulos` (`descartado`, `fecha_descartado`) y nuevos eventos en `bitacora_bandeja.jsonl`.
- **Pruebas:** `test_bandeja_descargas.py`: Suite completa de pruebas para simulación, movimiento, rechazo por confirmación, no-colisión, deshacer seguro, migración, CSRF y confinamiento.
