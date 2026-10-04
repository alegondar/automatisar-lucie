# Diseño: Ajustes de Escena de Capítulo y Lotes Anteriores

## Arquitectura y Componentes Afectados

### 1. `asegurar_carpeta_capitulo` en `bandeja_descargas.py`
Se implementa una función de validación y creación segura:
- Parámetros: `personaje: str`, `nombre: str`, `ruta_destino_base: str`, `ruta_descargas: str = ""`
- Flujo:
  1. `ValidadorEscenas.validar_nombre_escena(nombre, ruta_destino_base, ruta_descargas, False, personaje)`.
  2. Verificación de `os.path.realpath(carpeta)` confinado en `os.path.realpath(ruta_destino_base) + os.sep`.
  3. Comprobación de existencia previa (`os.path.exists(carpeta)`).
  4. Si existe, conteo no destructivo de archivos (`os.walk`).
  5. Si no existe, creación con `os.makedirs(carpeta, exist_ok=True)`.
  6. Retorno de diccionario estructurado: `{"carpeta": ..., "ya_existia": bool, "total_archivos": int, "mensaje": str}`.

Esta lógica es expuesta por `GestorMovimientosBandeja.asegurar_carpeta_capitulo` y `GestorBaseDatosBandeja.asegurar_carpeta_capitulo`.
En los endpoints `/api/capitulos/empezar` y `/api/capitulos/reabrir`, se invoca la verificación y se incluye el resultado en el JSON de respuesta.

### 2. Soporte de Carpeta Vacía en `descartar-capitulo`
En `simular_descartar_capitulo` y `ejecutar_descartar_capitulo`:
- La condición de traslado físico cambia de `if carpeta_existe and not carpeta_vacia:` a `if carpeta_existe:`.
- Si la carpeta existe físicamente (incluso con 0 archivos), se traslada a `_descartados` mediante `os.rename(origen_carpeta, destino_carpeta)`.
- Si no existe físicamente, no se llama a `os.rename` y solo se actualiza el estado en la base de datos SQLite.
- `deshacer_operacion` funciona de forma simétrica usando `os.rename(destino_carpeta, origen_carpeta)`.

### 3. Agrupación y Partición de Lotes en `AgrupadorLotes`
En `AgrupadorLotes.agrupar`:
- Se inspeccionan los candidatos: si existen elementos con `es_anterior == True` mezclados con elementos normales (`es_anterior == False`), se dividen en dos subconjuntos independientes.
- Cada subconjunto se agrupa por separado.
- Los lotes generados a partir de candidatos anteriores reciben explícitamente `es_anterior = True`, `escena_sugerida = ""` y todos sus archivos se marcan con `es_anterior = True`.
- En `VigilanteBandeja.escanear`, se garantiza que ningún archivo con `mtime < ts_corte_capitulo` ingrese en `candidatos_estables`.

### 4. UI y Desplegable en el Frontend Web
- En `renderLotes`:
  - Si hay capítulo activo, se construye la opción `<option value="${capActivo.nombre}" data-tipo="capitulo_activo" selected>[Capítulo activo] ${capActivo.nombre}</option>` como la primera del desplegable.
  - Al iterar las escenas descubiertas en destino, se omite cualquier escena coincidente con el capítulo activo para evitar duplicados.
  - El campo de texto de nueva escena permanece oculto (`display: none`) ya que la opción del capítulo no es `__nueva__`.
- En `renderLotesAnteriores`:
  - Los checkboxes nunca poseen el atributo `checked`.
  - El selector inicia en `+ Crear nueva escena...` con el input de texto vacío.
  - El botón de mover inicia en `Mover seleccionados (0)` y `disabled`.
- En la simulación previa:
  - Si el personaje seleccionado difiere del personaje del capítulo activo, se expone explícitamente en el encabezado de la simulación.
