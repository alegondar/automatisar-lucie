# Design: Renombrado Atómico y Secuencial al Mover

## Context
Ver `proposal.md` y `specs/renombrado-al-mover/spec.md`. El sistema actual de la bandeja de descargas (`bandeja_descargas.py`) mueve los archivos a la sala de espera conservando su nombre crudo. El usuario requiere que los archivos se renombren atómicamente en el mismo movimiento (`os.rename`) siguiendo el patrón `<base><número>.<ext>`, con contadores separados para imágenes y videos, continuidad de numeración y compatibilidad con sistemas FAT32/exFAT.

## Goals / Non-Goals

**Goals:**
- Renombrar en un único paso atómico `os.rename(origen, destino_renombrado)`.
- Contadores independientes para fotos y videos (`<base>1.jpg`, `<base>1.mp4`).
- Continuidad numérica sobre archivos preexistentes en la carpeta destino.
- Verificación case-insensitive de colisiones para compatibilidad con pendrives FAT32/exFAT.
- Mostrar claramente `nombre_original -> nombre_nuevo` en la simulación previa.
- Registro completo en bitácora `.jsonl` y reversión exacta al nombre original de descarga.
- Limpiar código y configuración legada (`carpeta_imagenes`).

**Non-Goals:**
- No alterar la clasificación de candidatos ni el vigilante de descargas.
- No alterar otros scripts (`inventario_pendrive.py`, `plan_limpieza.py`).
- No introducir dependencias externas ni modificar esquemas de SQLite (se reutilizan las columnas existentes).

## Decisions

### 1. Algoritmo de cálculo de la base del nombre
- **Decisión:** Para una escena dada y un personaje, se normaliza la escena en minúsculas y sin espacios intermedios o extremos (`nombre_escena.strip().lower()`). Se consulta la lista de alias conocidos (`FiltroListaBlanca.alias_personajes`). Si el nombre de la escena ya comienza con el personaje o alguno de sus alias, la base es directamente la escena. De lo contrario, se antepone el personaje: `f"{personaje}{escena_normalizada}"`.
- **Alternativa descartada:** Separar personaje y escena con guión bajo (`<personaje>_<escena>`). Se descarta porque el usuario especificó explícitamente el formato pegado `<personaje><escena>` (ej: `lucietrapitos`).

### 2. Clasificación de tipo de medio y contadores separados
- **Decisión:** Agrupar las extensiones permitidas en dos familias disjuntas:
  - `FOTO`: `.jpg`, `.jpeg`, `.png`, `.webp`
  - `VIDEO`: `.mp4`, `.mov`, `.webm`
  Cada familia mantiene su propio contador entero. El formato del archivo generado es `f"{base}{contador}{ext}"` donde `ext` se normaliza a minúsculas.
- **Alternativa descartada:** Un contador unificado para todos los archivos del lote. Se descarta porque el usuario requiere explícitamente contadores separados para fotos y videos.

### 3. Inspección del destino y continuidad numérica
- **Decisión:** Antes de numerar un lote en `simular_movimiento_lote`, se lee el contenido del directorio de destino propuesto si ya existe en disco (`os.listdir(carpeta_destino)`). Mediante una expresión regular insensible a mayúsculas:
  `re.compile(rf"^{re.escape(base)}(\d+)\.([a-z0-9]+)$", re.IGNORECASE)`
  se extraen los números existentes para cada familia de tipo de medio. El contador inicial para cada tipo comienza en `max(numeros_existentes, default=0) + 1`.
- **Multi-lote y coherencia intra-simulación:** Si se simula un movimiento de múltiples lotes o archivos destinados a la misma carpeta, los contadores persisten en memoria a lo largo de toda la simulación para que ningún archivo comparta nombre ni colisione.

### 4. Detección de colisiones case-insensitive y red de seguridad
- **Decisión:** En sistemas Linux ext4, `base1.mp4` y `Base1.MP4` son archivos distintos, pero en el pendrive (FAT32/exFAT) colisionan. La comprobación en `carpeta_destino` compara nombres en minúsculas (`[f.lower() for f in os.listdir(carpeta_destino)]`).
- **Red de seguridad:** Inmediatamente antes de invocar `os.rename` en `ejecutar_movimiento_lote`, se mantiene la función `resolver_destino_sin_colision` que añade el sufijo correlativo ` (1)` únicamente si el destino fue ocupado por una condición de carrera imprevista.

### 5. Formato de la bitácora y reversibilidad estricta
- **Decisión:** En cada objeto de movimiento de `bitacora_bandeja.jsonl` se registran:
  ```json
  {
    "origen_anterior": "/home/<usuario>/Descargas/grok-image-xxx.jpg",
    "destino_nuevo": "/home/<usuario>/Descargas/_lucie/lucie/trapitos/lucietrapitos1.jpg",
    "nombre_original": "grok-image-xxx.jpg",
    "nombre_nuevo": "lucietrapitos1.jpg",
    "hash": "...",
    "tamanio": 12345
  }
  ```
  Al invocar `deshacer_operacion`, se utiliza `origen_anterior`, devolviendo el archivo a su nombre original. Si `origen_anterior` está ocupado, la operación aborta con `ErrorDeshacer` sin tocar el destino ni renombrar.

### 6. Actualización en SQLite (`bandeja_archivos`)
- **Decisión:** Al mover, se actualiza `ruta_actual = destino_nuevo` (con el nombre nuevo). Al deshacer, se actualiza `ruta_actual = origen_anterior` (con el nombre original). El hash SHA-256 permanece inalterable en ambas direcciones.

### 7. Limpieza de UI y configuración legada
- **Decisión:**
  - En `generar_html_simulacion`: eliminar la lógica que insertaba `<span class="tag-tipo tag-imagen">` o `videos sin editar`. La tabla mostrará la columna de archivo con `<strong>{nombre_original}</strong> &rarr; <span class="badge-nuevo">{nombre_nuevo}</span>`.
  - En `config_bandeja.json`: remover la clave `"carpeta_imagenes": "imagenes"`.
  - En `bandeja_descargas.py`: eliminar los parámetros y referencias residuales a `carpeta_imagenes`.

## Risks / Trade-offs

- **[Riesgo] Caracteres especiales o acentos en el nombre de la escena:**
  - *Mitigación:* `ValidadorEscenas` ya restringe caracteres prohibidos. La base del nombre se somete a `strip().lower()`, removiendo espacios superfluos.
- **[Riesgo] Deshacer con líneas de bitácora antiguas que no poseen `nombre_original`:**
  - *Mitigación:* Se implementa fallback en `deshacer_operacion` y `obtener_historial` extrayendo el nombre base mediante `os.path.basename(mov["origen_anterior"])`.
- **[Riesgo] Concurrencia entre simulación y ejecución:**
  - *Mitigación:* El lock de `GestorMovimientosBandeja` serializa las ejecuciones de movimiento, y el chequeo previo a `os.rename` garantiza que ningún archivo sea sobrescrito.
