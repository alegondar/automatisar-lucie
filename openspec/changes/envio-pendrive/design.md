# Design

## Context

El sistema actual gestiona la clasificación y renombrado de descargas multimedia en la sala de espera local `~/Descargas/_lucie/<personaje>/<capítulo>/(fotos|videos)`. Una vez que el material de un capítulo está consolidado o en proceso, debe transferirse físicamente a un almacenamiento externo (pendrive). Sin embargo, el pendrive del usuario puede contener ya colecciones existentes, archivos personales o respaldos que deben permanecer estrictamente intactos.

Para asegurar la integridad total, este diseño establece una arquitectura de transferencia confinada en una carpeta raíz exclusiva (`LucieSinReglas`), identifica el pendrive mediante un marcador criptográfico (`.lucie_pendrive.json`), aplica simulación previa estricta con detección de sistemas de archivos FAT32, copia atómica en archivos parciales (`.part`), preservación de originales en `_enviados`, registro append-only en un manifiesto (`.lucie/manifiesto.jsonl`), reversión limpia hacia `_revertidos` y vigilancia automática sin transferencias desatendidas. Todo ello respetando rigurosamente las 7 Reglas de Oro del proyecto y las restricciones de análisis estático AST anti-borrado.

## Goals / Non-Goals

**Goals:**
- Confinamiento estricto de toda operación de escritura dentro de `<pendrive>/LucieSinReglas/` y del marcador raíz `.lucie_pendrive.json`. Todo el resto del pendrive es de solo lectura.
- Función de detección multiplataforma `detectar_pendrive()` para Linux y Windows, con soporte de rutas candidatas por configuración (`rutas_candidatas_pendrive`) para entornos de prueba.
- Acción de vinculación previa con simulación que crea el marcador y la estructura base de directorios sin pisar marcadores existentes.
- Simulación previa obligatoria por lote (por capítulo o para todos los pendientes) con validación de espacio libre con margen, inspección de FAT32/vfat para bloquear archivos >4 GiB, resolución case-insensitive y detección de conflictos.
- Copia atómica en streaming con archivo parcial `<destino>.part`, `os.fsync`, renombrado seguro con `os.rename` y verificación posterior de SHA-256.
- Preservación sin borrado de los originales en `~/Descargas/_lucie/_enviados/`.
- Manifiesto append-only en el pendrive y bitácora local reversible.
- Capacidad de deshacer envíos sin eliminar archivos, reubicando la copia a `LucieSinReglas/_revertidos/<id_envio>/` y restituyendo el original si la sala de espera no está ocupada.
- Detección reactiva en el vigilante con banner interactivo en el panel web.
- Pestaña "Pendrive" y botones de envío integrados en las vistas de capítulos.
- Registrar las convenciones arquitectónicas para los tramos siguientes de post-producción.

**Non-Goals:**
- No realizar transferencias automáticas sin aprobación del usuario (la detección solo alerta mediante un banner, no envía sola).
- No modificar ni limpiar carpetas preexistentes del pendrive fuera de `LucieSinReglas/` (la limpieza general de pendrives permanece desacoplada en `plan_limpieza.py`).
- No utilizar primitivas destructivas de borrado (`os.remove`, `os.unlink`, `os.rmdir`, `os.removedirs`, `Path.unlink`, `Path.rmdir`, `shutil.rmtree`, `shutil.move`, `os.replace`, `send2trash` o comandos shell).
- No implementar en esta etapa la lógica de edición de CapCut ni la sincronización del tramo 3 (solo se registran sus convenciones de diseño).

## Decisions

### 1. Marcador de Identidad y Detección Multiplataforma (`detectar_pendrive`)
- **Decisión**: La identidad del pendrive se determina por la presencia del archivo `.lucie_pendrive.json` en su raíz con el esquema:
  ```json
  {
    "id": "<uuid4>",
    "creado": "<timestamp_iso>",
    "version": 1
  }
  ```
  La detección se aísla en la función `detectar_pendrive()`:
  - En Linux (`os.name == 'posix'`): inspecciona los puntos de montaje bajo `/media/<usuario>/*` y `/run/media/<usuario>/*` (reutilizando la lógica de inspección de puntos de montaje y tomando el nombre de etiqueta `MIUNIDAD` solo como pista secundaria).
  - En Windows (`os.name == 'nt'`): itera sobre las letras de unidad disponibles (`A:` a `Z:`) buscando el marcador `.lucie_pendrive.json`.
  - Configuración `"rutas_candidatas_pendrive"` en `config_bandeja.json`: permite inyectar rutas explícitas para pruebas unitarias automatizadas o configuraciones especiales.
  - Si ningún pendrive conectado posee el marcador, el sistema no autoriza ninguna operación de envío.
- **Razón**: Evita transferencias erróneas a unidades externas no deseadas (discos de respaldo, pendrives de terceros) y desacopla la detección para facilitar la portabilidad futura a Windows.

### 2. Vinculación Controlada de Pendrive
- **Decisión**: La vinculación se ejecuta en dos pasos:
  1. `POST /api/pendrive/vincular-simular`: Identifica la unidad candidata montada sin marcador, inspecciona su punto de montaje, sistema de archivos y espacio libre, y devuelve los datos al frontend.
  2. `POST /api/pendrive/vincular`: Tras confirmación del usuario, genera un UUIDv4 nuevo, escribe `.lucie_pendrive.json` con modo exclusivo (`'xb'`) para garantizar que nunca se sobrescriba un marcador existente, y crea la estructura base mediante `os.makedirs(..., exist_ok=True)`:
     - `<pendrive>/LucieSinReglas/.lucie/`
     - `<pendrive>/LucieSinReglas/videos sin editar/`
     - `<pendrive>/LucieSinReglas/videos ya editados/`
     - `<pendrive>/LucieSinReglas/videos completos/`
     - `<pendrive>/LucieSinReglas/imagenes/`
- **Razón**: Garantiza que el usuario autorice conscientemente qué unidad se convierte en pendrive de trabajo antes de realizar cualquier cambio físico.

### 3. Confinamiento de Rutas en `LucieSinReglas`
- **Decisión**: Toda escritura en el pendrive se valida canónicamente con `os.path.realpath`. Ningún archivo ni carpeta fuera de `<pendrive>/LucieSinReglas/` (a excepción del marcador `.lucie_pendrive.json`) puede ser creado, modificado o renombrado. Las carpetas existentes del usuario en el pendrive permanecen en estricto modo de solo lectura.
- **Razón**: Protección absoluta de la información preexistente del usuario en el medio físico.

### 4. Plan de Envío con Simulación Exhaustiva por Lote
- **Decisión**: Antes de cualquier transferencia, se genera un plan de envío (un único plan para el lote completo, ya sea un capítulo específico o todos los pendientes):
  - Listado de cada archivo con su origen, destino relativo proyectado, tamaño en bytes y hash SHA-256.
  - Validación de espacio libre: se exige que el espacio disponible en el pendrive supere la suma de tamaños de los archivos más el margen de seguridad (`margen_libre_bytes`).
  - Inspección de sistema de archivos FAT32/vfat (leyendo `/proc/mounts` en Linux): si la unidad es FAT32 y cualquier archivo supera los 4 GiB (4.294.967.296 bytes), se bloquea preventivamente la aprobación del lote con mensaje explícito.
  - Detección de colisiones case-insensitive: dado que FAT32/exFAT no distinguen mayúsculas/minúsculas, se evalúan colisiones normalizando a minúsculas.
  - Deduplicación contra el manifiesto: si un archivo ya figura en el manifiesto con el mismo hash SHA-256, se clasifica como "ya enviado" y se omite.
  - Detección de conflictos: si en el destino ya existe un archivo con diferente hash SHA-256, se marca en estado "conflicto" y se detiene la copia (nunca se sobrescribe ni se genera un sufijo en silencio).
  - Archivos sueltos no multimedia en la raíz del capítulo: se excluyen de la transferencia y se detallan con advertencia.
  - Si el capítulo sigue abierto en la sala de espera, la simulación advierte que podrían arribar más archivos.
  - La ejecución requiere un único clic "Confirmar y enviar" para el lote.
- **Razón**: Cumple la Regla de Oro #2 (simulación previa) y #3 (aprobación granular por lote explícito) y previene errores irreversibles o fallos en tiempo de ejecución.

### 5. Copia Segura Atómica con `.part` y Doble Verificación de Hash
- **Decisión**:
  1. El archivo se transfiere en bloques binarios hacia `<destino>.part` calculando el hash SHA-256 de origen y de la copia en la misma pasada.
  2. Al finalizar los bloques, se invoca `os.fsync(f.fileno())` para forzar la descarga de los buffers a la memoria física del pendrive.
  3. Se verifica que el destino final no exista y se ejecuta `os.rename("<destino>.part", "<destino>")`.
  4. Se vuelve a leer el archivo en su ubicación final para confirmar que el hash en disco coincide exactamente con el origen.
  5. En caso de fallo de E/S, desconexión o discrepancia, el archivo `.part` queda en el pendrive sin borrarse, se interrumpe el lote y se alerta en el panel web.
- **Razón**: Elimina el riesgo de archivos corruptos o truncados por desconexión del USB y garantiza que nunca se invoquen primitivas de borrado sobre datos defectuosos.

### 6. Preservación de Originales en `_enviados`
- **Decisión**: Únicamente tras la verificación exitosa del hash en el pendrive, el archivo original en la sala de espera se mueve con `os.rename` a `~/Descargas/_lucie/_enviados/<personaje>/<capítulo>/(fotos|videos)/<archivo>`. Si en el destino ya existe un archivo con dicho nombre, se le asigna un sufijo numérico correlativo sin pisar. La carpeta `_enviados` queda excluida del listado de capítulos y escenas.
- **Razón**: Al realizarse dentro del mismo sistema de archivos (`~/Descargas`), `os.rename` es instantáneo y atómico, liberando la sala de espera sin eliminar jamás el material original.

### 7. Manifiesto Append-Only en el Pendrive
- **Decisión**: En `<pendrive>/LucieSinReglas/.lucie/manifiesto.jsonl` se anexa una línea JSON por archivo enviado:
  ```json
  {
    "id_envio": "<uuid4>",
    "fecha": "<iso_timestamp>",
    "equipo": "<hostname>",
    "pendrive_id": "<uuid_pendrive>",
    "personaje": "<personaje>",
    "capitulo": "<capítulo>",
    "tipo": "crudo" | "imagen",
    "nombre": "<nombre_archivo>",
    "ruta_relativa": "<ruta_relativa_en_luciesinreglas>",
    "sha256": "<hash>",
    "bytes": 1234567,
    "estado": "enviado"
  }
  ```
  El archivo se abre exclusivamente con modo `'a'` (append-only) y nunca se reescribe. Simultáneamente, se registra el evento en `bitacora_bandeja.jsonl`.
- **Razón**: Garantiza trazabilidad histórica auditable e inmutable en el propio dispositivo externo.

### 8. Deshacer Envíos sin Borrado
- **Decisión**: Para revertir un envío:
  1. La copia que reside en el pendrive se traslada con `os.rename` hacia `<pendrive>/LucieSinReglas/_revertidos/<id_envio>/<ruta_relativa>`.
  2. El archivo original en `~/Descargas/_lucie/_enviados/` se traslada con `os.rename` de vuelta a su posición en la sala de espera.
  3. Si la ruta original en la sala de espera se encuentra ocupada por un archivo nuevo, la reversión se deniega de forma estricta sin alterar nada.
  4. Se añade una entrada `"envio_revertido"` al manifiesto append-only y a la bitácora local.
- **Razón**: Permite corregir transferencias erróneas sin violar la prohibición de borrado y protegiendo el contenido actual de la sala de espera.

### 9. Vigilante con Detección Automática y Banner
- **Decisión**: `VigilanteBandeja` ejecuta una comprobación periódica (cada 5 segundos) buscando la presencia del pendrive con marcador válido. Cuando detecta el pendrive conectado y existen archivos pendientes en la sala de espera, emite un aviso en el estado para mostrar un banner en el panel web:
  `"Pendrive detectado: N archivos de M capítulos listos para enviar [Ver plan]"`.
  El vigilante no ejecuta transferencias automáticamente; el usuario debe revisar el plan y confirmar en un solo clic.
- **Razón**: Notifica proactivamente la disponibilidad del medio físico manteniendo el control y la aprobación humana en todo momento.

### 10. Convenciones de Diseño para Tramos Futuros (SIN IMPLEMENTAR EN ESTE CHANGE)
- **Decisión**: Se establecen y documentan las siguientes convenciones que serán implementadas en tramos subsiguientes:
  1. **Export de CapCut**: Las versiones editadas exportadas por CapCut mantendrán el nombre idéntico exacto del archivo crudo original (ejemplo: `lucieoloraculo3.mp4`), permitiendo la correlación biunívoca entre crudo y editado.
  2. **Video Completo de Capítulo**: El video renderizado final del capítulo completo llevará el nombre de la escena con el sufijo `"videocompleto"` (ejemplo: `lucieoloraculovideocompleto.mp4`).
  3. **Botón "Voy a editar este"**: En una etapa futura se incorporará una acción en el panel que asentará en el manifiesto el estado `"en_edicion"` para un archivo crudo seleccionado, previniendo duplicidades de edición.
  4. **Tramo 3 de Copia de Editados**: El tramo 3 incorporará la sincronización de videos terminados hacia `<pendrive>/LucieSinReglas/videos ya editados/<personaje>/<capítulo>/` y videos finales a `<pendrive>/LucieSinReglas/videos completos/<personaje>/<capítulo>/`, dejando los archivos crudos en `videos sin editar` completamente intactos.

### 11. Monitoreo No Bloqueante con Límite de Tiempo (Robustez del Panel)
- **Decisión**: Cualquier detección o lectura del pendrive (marcador `.lucie_pendrive.json`, inspección de `/proc/mounts`, cálculo de espacio libre con `statvfs`, búsqueda de archivos `.part`) se ejecuta fuera del hilo principal que atiende las peticiones HTTP del servidor mediante un `ThreadPoolExecutor` con un timeout estricto de 3.0 segundos. Si la llamada excede dicho tiempo, la petición retorna inmediatamente indicando el estado "Pendrive sin respuesta" (`sin_respuesta: True`), sin bloquear en ningún momento la interfaz del usuario ni el hilo del servidor.
- **Razón**: Los dispositivos USB o sistemas de archivos con sectores dañados pueden congelar llamadas al sistema a nivel de kernel; aislar las lecturas con timeout previene que el panel web se congele o deje de responder ante problemas de hardware.

## Risks / Trade-offs

- **[Riesgo: Unidad USB que se congela o bloquea las llamadas al sistema]** → **Mitigación**: Ejecución delegada a un hilo secundario con límite de 3 segundos; si expira, se cancela la espera y el panel exhibe "Pendrive sin respuesta", permaneciendo plenamente funcional.
- **[Riesgo: Desconexión física del pendrive durante la copia]** → **Mitigación**: El uso de archivos parciales con extensión `.part` y llamadas forzadas a `os.fsync` garantiza que los archivos incompletos no se confundan con archivos definitivos. Los `.part` permanecen en el pendrive sin ser eliminados, el lote se detiene inmediatamente y la interfaz muestra una lista de archivos incompletos para auditoría.
- **[Riesgo: Límite de tamaño de 4 GiB en particiones FAT32/vfat]** → **Mitigación**: Detección anticipada del sistema de archivos en `/proc/mounts`. Cualquier archivo mayor a 4 GiB en una partición FAT32 es detectado y bloqueado en la simulación previa antes de intentar la transferencia física.
- **[Riesgo: Colisiones de nombres insensibles a mayúsculas en FAT32/exFAT]** → **Mitigación**: La simulación normaliza nombres a minúsculas para cotejar colisiones antes de escribir, evitando que nombres como `Video.mp4` y `video.mp4` sobrescriban datos.
- **[Riesgo: Conflicto al revertir un envío si la sala de espera ya contiene un archivo con el mismo nombre]** → **Mitigación**: Comprobación obligatoria de existencia previa en la sala de espera antes de renombrar; si el destino está ocupado, la reversión aborta con error 409 sin realizar cambios parciales.
- **[Riesgo: Infracción accidental de primitivas prohibidas de borrado]** → **Mitigación**: El código del módulo utiliza exclusivamente `open('...xb')` y `os.rename`, sin invocar `os.remove`, `shutil.move` ni ninguna de las 11 primitivas prohibidas. La suite de pruebas ejecuta el analizador estático AST garantizando 0 infracciones.

## Migration Plan

1. Actualizar `config_bandeja.json` para registrar `"carpeta_raiz_pendrive": "LucieSinReglas"` y `"rutas_candidatas_pendrive": []`.
2. Las carpetas existentes de los usuarios en pendrives conectados no requieren migración ni se alteran; al vincularse, se crea la estructura `LucieSinReglas/` de forma no destructiva.
3. La sala de espera local conserva su estructura, añadiendo la subcarpeta `_enviados/` para el resguardo de originales.

