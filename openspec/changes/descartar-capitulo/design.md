# Design: Descartar Capítulo Moviéndolo a `_descartados` con Deshacer Reversible

## Architecture & Data Flow

### 1. Migración y Modelo de Datos (`GestorBaseDatosBandeja`)
- En `_inicializar_db()`:
  - Se verifica la presencia de las columnas `descartado` y `fecha_descartado` en la tabla `bandeja_capitulos` mediante `PRAGMA table_info(bandeja_capitulos);`.
  - Si no existen, se incorporan mediante:
    ```sql
    ALTER TABLE bandeja_capitulos ADD COLUMN descartado INTEGER DEFAULT 0;
    ALTER TABLE bandeja_capitulos ADD COLUMN fecha_descartado TEXT;
    ```
- Métodos añadidos y actualizados:
  - `listar_capitulos_cerrados()`: filtra `WHERE estado = 'cerrado' AND (descartado IS NULL OR descartado = 0)`.
  - `listar_capitulos_descartados()`: consulta `WHERE descartado = 1 ORDER BY id DESC`.
  - `marcar_capitulo_descartado(id_capitulo: int, descartado: bool = True)`:
    - Si `descartado = True`: actualiza `descartado = 1, estado = 'cerrado', fecha_fin = COALESCE(fecha_fin, now), fecha_descartado = now`.
    - Si `descartado = False`: actualiza `descartado = 0, estado = 'cerrado', fecha_descartado = NULL`.
  - Actualización de archivos asociados: actualiza `bandeja_archivos.ruta_actual` sustituyendo el prefijo de la carpeta de origen por la de destino, y asigna `estado = 'descartado'`.

### 2. Lógica de Cuarentena y Confinamiento (`GestorMovimientosBandeja`)
- **Método `_validar_confinamiento_destino_base(ruta: str)`**:
  - Resuelve `base_confinada = os.path.realpath(self.ruta_destino_base)`.
  - Resuelve `ruta_real = os.path.realpath(ruta)`.
  - Exige que `ruta_real.startswith(base_confinada + os.sep)`.
  - Rechaza symlinks explícitos (`os.path.islink(ruta)`).
- **Método `simular_descartar_capitulo(capitulo_id: int)`**:
  - Obtiene los datos del capítulo desde la base.
  - Valida el nombre de la escena con `ValidadorEscenas.validar_nombre_escena`.
  - Establece `origen_carpeta = os.path.join(self.ruta_destino_base, personaje, nombre)`.
  - Genera `fecha_tag = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")`.
  - Genera `destino_carpeta = os.path.join(self.ruta_destino_base, "_descartados", personaje, f"{nombre}_{fecha_tag}")`.
  - Resuelve colisiones agregando sufijo correlativo ` (1)`, ` (2)`...
  - Valida confinamiento de ambas rutas.
  - Recorre `origen_carpeta` en disco: cuenta archivos, calcula peso acumulado y verifica ausencia de symlinks salientes.
- **Método `ejecutar_descartar_capitulo(simulacion: Dict[str, Any], nombre_confirmacion: str)`**:
  - Verifica que `nombre_confirmacion.strip() == simulacion["escena"]`.
  - Re-valida confinamiento y que el destino no exista en disco.
  - Si la carpeta existe y contiene archivos:
    - Asegura la existencia de `os.path.dirname(destino_carpeta)` mediante `os.makedirs(..., exist_ok=True)`.
    - Ejecuta `os.rename(origen_carpeta, destino_carpeta)`.
    - Actualiza `bandeja_archivos` para los archivos reubicados.
  - Marca el capítulo como descartado en SQLite.
  - Si el capítulo era el activo, llama a `guardar_capitulo_activo("", "", False)`.
  - Registra el evento en `bitacora_bandeja.jsonl`.

### 3. Reversión Estricta (`deshacer_operacion`)
- Al procesar una operación con `evento == "descartar_capitulo"`:
  - Verifica que la operación no haya sido deshecha previamente.
  - Si hubo movimiento de carpeta:
    - Verifica que `destino_carpeta` exista.
    - Verifica que `origen_carpeta` esté LIBRE en disco. Si está ocupada, aborta con `ErrorDeshacer` sin sobrescribir ni añadir sufijos.
    - Ejecuta `os.rename(destino_carpeta, origen_carpeta)`.
    - Restaura `bandeja_archivos.ruta_actual` y `estado = 'movido'`.
  - En SQLite: `marcar_capitulo_descartado(capitulo_id, descartado=False)`.
  - Escribe el evento `deshacer` en la bitácora.
  - Retorna confirmación de reversión.

### 4. Endpoints y Seguridad Web (`HandlerServidorBandeja`)
- `POST /api/capitulos/descartar-simular`:
  - Recibe `{"id": <capitulo_id>}` o determina capítulo activo.
  - Retorna los datos de la simulación.
- `POST /api/capitulos/descartar`:
  - Recibe `{"id": <capitulo_id>, "nombre_confirmacion": "<nombre>"}`.
  - Valida coincidencia exacta y ejecuta el descarte.
  - Retorna `id_operacion` y mensaje.
- Ambos protegidos con `_validar_seguridad_post()` (Host, Content-Type application/json, token anti-CSRF).
- `GET /api/capitulos/descartados`:
  - Retorna la lista de capítulos con `descartado = 1`.

### 5. Interfaz de Usuario
- Botón "Descartar capítulo" en el banner del capítulo activo (junto a "Terminar capítulo").
- Botón "Descartar" en la tabla de "Capítulos Cerrados".
- Modal de simulación con aviso de reversibilidad y campo de confirmación por tipeo exacto.
- Nueva pestaña o vista "Descartados" en la barra de navegación para consultar capítulos archivados.
- Notificación superior con botón "Deshacer" y botón "Deshacer" en el historial para eventos de descarte.
