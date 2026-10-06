# Proposal: control-montaje-pendrive

## Why

Cuando un pendrive extraíble (como `sda1`, `exfat`) está físicamente conectado a la máquina pero no se encuentra montado en el sistema de archivos (`MOUNTPOINTS` vacío en `lsblk`), la interfaz web de la bandeja de descargas informa "Ningún pendrive vinculado detectado", haciéndolo indistinguible de la ausencia física de cualquier unidad. Los usuarios no tienen visibilidad de particiones conectadas pendientes de montaje ni disponen de una vía integrada y segura para montar, desmontar o expulsar eléctricamente sus pendrives desde el panel, teniendo que recurrir a la terminal o corriendo riesgos de extracciones en caliente mientras hay operaciones en curso.

## What Changes

- **Detección nativa en Linux sin subprocess**: Inspección directa de `/sys/block/*/removable` (=1) y sus particiones hijas en `/sys/class/block`, resolución de etiquetas por enlaces simbólicos en `/dev/disk/by-label`, y detección de puntos de montaje a través de `/proc/self/mountinfo` (considerando montajes FUSE como `ntfs-3g` y `exfat-fuse` como montados). Tolerancia a atributos faltantes sin generar excepciones no controladas.
- **Cinco estados en la tarjeta "Unidad Pendrive"**:
  1. `sin_unidad`: no hay ninguna partición extraíble conectada.
  2. `detectada_sin_montar`: partición extraíble conectada pero no montada (expone dispositivo, etiqueta, tamaño y sistema de archivos).
  3. `conectada_sin_vincular`: partición montada que carece del marcador `.lucie_pendrive.json` (expone punto de montaje, sistema de archivos, espacio libre y botón "Vincular pendrive").
  4. `vinculado_listo`: partición montada con marcador válido, lista para operaciones de transferencia.
  5. `sin_respuesta`: timeout de 3 segundos en hilo independiente si la unidad física no responde.
- **Soporte de múltiples unidades extraíbles**: Listado de todas las particiones detectadas con selector obligatorio cuando existan dos o más. La etiqueta `MIUNIDAD` funciona únicamente como criterio de orden preferente, nunca como requisito excluyente.
- **Diagnóstico desplegable "¿Por qué no veo mi pendrive?"**: Sección colapsable que enumera todas las particiones evaluadas en el sistema indicando si son o no removibles, si están montadas, punto de montaje y sistema de archivos detectado.
- **Acciones seguras de montaje y desmontaje**:
  - Botón "Montar unidad" (en estado sin montar): ejecuta exclusivamente `udisksctl mount -b <dispositivo>`.
  - Botón "Desmontar" (en estados montada sin vincular y vinculada): ejecuta `udisksctl unmount -b <dispositivo>` (prohibido `-f` y `-l`).
  - Botón "Desmontar y expulsar": ejecuta `udisksctl unmount` y, únicamente tras tener éxito, ejecuta `udisksctl power-off -b <disco_padre>`, informando al usuario "Ya podés retirar el pendrive".
- **Garantías de seguridad para comandos de control**:
  - Invocación con `subprocess.run` con lista fija de argumentos (sin `shell=True`, sin privilegios `sudo`), con tiempo límite.
  - Validación estricta del dispositivo contra la lista de particiones removibles activamente detectadas (nunca aceptar rutas arbitrarias enviadas por el cliente).
  - Modal de confirmación interactivo previo que exhibe el comando exacto a ejecutar.
  - Degradación elegante si `udisksctl` no está instalado o si fallan los permisos de Polkit: mensaje claro de error y visualización del comando manual equivalente con botón "Copiar".
- **Precondiciones y protección de desmontaje**:
  - Bloqueo preventivo de desmontaje si existe un envío, deshacer o archivo `.part` activo en curso.
  - Espera a que finalice cualquier lectura concurrente sobre el pendrive y ejecución obligatoria de `os.sync()` antes de solicitar el desmontaje.
  - Detección de unidad ocupada (busy): si el desmontaje falla por recursos en uso, escanear `/proc/*/cwd` y `/proc/*/fd` de procesos del usuario para reportar qué procesos están reteniendo la unidad y recomendar su cierre.
- **Silenciamiento post-desmontaje/expulsión**: Suspensión del sondeo de lectura y silenciamiento del banner "Pendrive detectado" para la unidad retirada hasta que se desconecte físicamente y se vuelva a insertar, o hasta que se pulse manualmente "Montar".
- **Registro en bitácora**: Grabación de eventos `montar_unidad` y `desmontar_unidad` en la bitácora append-only local.
- **Soporte Windows**: En entornos Windows se omiten los controles de montaje/expulsión (delegados al explorador del sistema operativo) y se documenta la decisión en el diseño.
- **Seguridad HTTP y AST**: Endpoints POST protegidos contra CSRF, cabecera Host y validación de Content-Type JSON. Reglas de Oro intactas: ninguna operación destructiva sobre el contenido del pendrive. Reglas AST de seguridad actualizadas para permitir `udisksctl` con verbos acotados (`mount`, `unmount`, `power-off`).

## Capabilities

### New Capabilities
- `control-montaje-pendrive`: Manejo del ciclo de vida de montaje de unidades extraíbles, detección de particiones en Linux vía `/sys` y `/proc/self/mountinfo`, ejecución controlada y validada de `udisksctl mount/unmount/power-off`, precondiciones de sincronización (`os.sync()`), inspección no destructiva de procesos ocupantes vía `/proc`, silenciamiento reactivo y controles en el panel web.

### Modified Capabilities
<!-- Ninguna capacidad previa cambia sus requerimientos contractuales -->

## Impact

- **Código afectado**:
  - `bandeja/plataforma.py`: Módulos de inspección de `/sys/block`, `/sys/class/block`, `/dev/disk/by-label`, `/proc/self/mountinfo`, resolución de disco padre, inspección de `/proc/*/cwd` y `/proc/*/fd`.
  - `bandeja/pendrive.py`: Transiciones entre los 5 estados, lógica de ejecución y verificación de `montar_unidad`, `desmontar_unidad`, `expulsar_unidad`, precondiciones de `os.sync()`, bitácora local y silenciamiento temporal.
  - `bandeja/servidor.py`: Nuevos endpoints `POST /api/pendrive/montar`, `POST /api/pendrive/desmontar`, `POST /api/pendrive/expulsar`, y ampliación del payload de `GET /api/pendrive/estado`.
  - `bandeja/web/panel.html`, `bandeja/web/panel.css`, `bandeja/web/panel.js`: Renderizado de tarjetas según los 5 estados, diálogo modal de confirmación con comando visual, botón "Copiar", bloque colapsable "¿Por qué no veo mi pendrive?" y selector de unidad extraíble si hay múltiples.
  - `seguridad_anti_borrado.py`: Mantenimiento de la regla de oro #1 y #7 asegurando que el uso de subprocess esté estrictamente restringido a los verbos seguros de `udisksctl`.
- **APIs**: Tres nuevos endpoints REST protegidos por Host, CSRF y Content-Type JSON.
- **Dependencias**: Utiliza herramientas estándar de Linux (`sysfs`, `procfs`, `udisksctl`) sin dependencias externas de terceros adicionales.
