# Design: control-montaje-pendrive

## Context

Actualmente `bandeja/plataforma.py` busca candidatos a pendrive inspeccionando únicamente carpetas preexistentes en `/media`, `/run/media` y entradas activas en `/proc/mounts`. Si un pendrive está conectado físicamente pero el sistema no lo ha montado automáticamente, resulta totalmente invisible para la bandeja. Ver `proposal.md` para la motivación.

Este diseño define la detección en bajo nivel mediante `sysfs` y `procfs` en Linux sin lanzar subprocesos, la interfaz de control segura con `udisksctl`, las precondiciones de desmontaje (`os.sync()`, inspección de procesos bloqueantes), el silenciamiento reactivo y el desacoplamiento multiplataforma.

## Goals / Non-Goals

**Goals:**
- Detección nativa en Linux sin `subprocess`: inspeccionar `/sys/block/*/removable`, `/sys/class/block`, `/dev/disk/by-label` y `/proc/self/mountinfo`.
- Reconocimiento de montajes FUSE (`ntfs-3g`, `exfat-fuse`) como unidades montadas.
- Clasificación en 5 estados precisos: `sin_unidad`, `detectada_sin_montar`, `conectada_sin_vincular`, `vinculado_listo`, `sin_respuesta`.
- Operaciones de montaje (`mount`), desmontaje (`unmount`) y expulsión (`power-off`) invocando exclusivamente `udisksctl` con lista fija de argumentos.
- Validación obligatoria de nodo de dispositivo contra la lista blanca en memoria de particiones removibles activamente detectadas.
- Diálogo interactivo de confirmación que exhibe el comando exacto antes de ejecutarlo.
- Precondiciones estrictas: bloqueo si hay transferencia o reversión en curso, ejecución previa de `os.sync()`, y prohibición total de desmontajes forzados (`-f`, `-l`).
- Diagnóstico de unidad ocupada (busy): inspección no destructiva de `/proc/*/cwd` y `/proc/*/fd` para identificar procesos del usuario que impiden el desmontaje.
- Silenciamiento reactivo post-desmontaje/expulsión para evitar re-sondeos molestos de unidades retiradas.
- Conformidad estricta con las Reglas de Oro del proyecto y auditoría AST con 0 infracciones.

**Non-Goals:**
- Montaje automático desatendido sin interacción del usuario.
- Soporte para privilegios `sudo` o comandos arbitrarios en shell.
- Formateo o particionado de discos desde la interfaz.
- Implementación de montaje/desmontaje en Windows (en Windows el sistema operativo monta automáticamente y la expulsión segura se realiza desde el explorador / bandeja del sistema).

## Decisions

### 1. Detección nativa por `sysfs` y `procfs` sin `subprocess`
- **Decisión**:
  - Dispositivos removibles: iterar `/sys/block/*` donde el archivo `removable` contenga `1` y no comience por `loop` ni `ram`.
  - Particiones: listar subdirectorios en `/sys/block/<disco>/` que comiencen con el nombre del disco (o mediante `/sys/class/block`).
  - Etiqueta del sistema de archivos: leer enlaces simbólicos en `/dev/disk/by-label/*` y cotejar sus destinos en `/dev/` (ej: `../../sda1`).
  - Detección de montajes: parsear `/proc/self/mountinfo`, reconociendo dispositivos de bloque mayores/menores, rutas de montaje y tipos FUSE (`fuse`, `fuseblk`, `ntfs-3g`, `exfat-fuse`).
- **Alternativas consideradas**:
  - `subprocess.run(["lsblk", "--json"])`: Descartado para el ciclo de sondeo recurrente por sobrecoste de procesos concurrentes cada 3 segundos y potencial punto de bloqueo si el subsistema I/O se cuelga.
- **Razón**: Máxima eficiencia, cero llamadas a subprocesos durante el refresco normal y tolerancia ante atributos faltantes.

### 2. Ciclo de control con `udisksctl` y lista blanca de dispositivos
- **Decisión**:
  - Montar: `udisksctl mount -b <dispositivo>`
  - Desmontar: `udisksctl unmount -b <dispositivo>`
  - Desmontar y expulsar: `udisksctl unmount -b <dispositivo>` y, si retorna código 0, `udisksctl power-off -b <disco_padre>`.
  - El backend nunca acepta una ruta arbitraria: verifica que `<dispositivo>` pertenezca a la lista de particiones removibles detectadas en el escaneo más reciente.
- **Alternativas consideradas**:
  - Comandos clásicos `mount` / `umount`: Descartados porque requieren privilegios `root` (sudo) y no administran permisos de usuario de escritorio.
- **Razón**: `udisksctl` está diseñado específicamente para usuarios estándar de escritorio, utiliza D-Bus/Polkit de forma segura y monta de forma predeterminada en `/run/media/$USER/<etiqueta>`.

### 3. Precondiciones de desmontaje y diagnóstico de unidad ocupada
- **Decisión**:
  - Verificar cerrojos globales en `bandeja/pendrive.py`: rechazar desmontaje si hay una transferencia o deshacer en curso, o si existen archivos `.part` abiertos.
  - Ejecutar `os.sync()` inmediatamente antes de solicitar el desmontaje para asegurar que los buffers del kernel se vuelquen a la memoria física.
  - Si el desmontaje falla con indicación de que el dispositivo está ocupado (*target is busy*), escanear en `/proc` los enlaces simbólicos `cwd` y descriptores `fd/*` pertenecientes a los procesos del usuario, cotejando si apuntan al punto de montaje. Retornar la lista de procesos (PID, nombre, línea de comandos) al usuario recomendando su cierre.
- **Alternativas consideradas**:
  - Forzar desmontaje con `-l` (lazy) o `-f` (force): Estrictamente prohibido para evitar corrupción de datos en sistemas FAT32/exFAT.

### 4. Silenciamiento reactivo y bitácora
- **Decisión**:
  - Mantener un registro en memoria de unidades expulsadas/desmontadas manualmente (`unidades_silenciadas`).
  - Mientras el dispositivo permanezca en la lista de silenciados, no se mostrará el banner "Pendrive detectado" ni se intentarán lecturas de capítulos, hasta que el dispositivo desaparezca físicamente o el usuario presione "Montar".
  - Registrar los eventos `montar_unidad` y `desmontar_unidad` en la bitácora append-only (`.jsonl`).

### 5. Adaptación a Windows
- **Decisión**:
  - En Windows (`os.name == 'nt'`), la tarjeta de estado informa los puntos de montaje existentes (letras de unidad) pero no presenta los botones de "Montar", "Desmontar" ni "Expulsar", ya que Windows asigna letras automáticamente y la extracción segura es delegada a la bandeja de sistema de Windows.

### 6. Verificación AST de seguridad
- **Decisión**:
  - Asegurar que `seguridad_anti_borrado.py` valide que cualquier uso de `subprocess` en `bandeja/pendrive.py` o `bandeja/plataforma.py` esté restringido a llamadas a `udisksctl` con los argumentos fijos `mount`, `unmount` y `power-off`, manteniendo 0 infracciones anti-borrado.

## Risks / Trade-offs

- **[Riesgo]** `udisksctl` no disponible en instalaciones mínimas sin entorno de escritorio.
  - *Mitigación*: Capturar `FileNotFoundError` o código de error, no provocar excepciones HTTP 500, y devolver mensaje claro con el comando manual equivalente junto al botón "Copiar".
- **[Riesgo]** Permisos de Polkit deniegan el montaje en sesiones sin interfaz gráfica activa.
  - *Mitigación*: Capturar el mensaje de error de `udisksctl` y presentarlo legiblemente en el modal de la interfaz.
- **[Riesgo]** Conflicto de sondeo recurrente durante el proceso de desmontaje.
  - *Mitigación*: Adquirir un cerrojo de sincronización (`_cerrojo_operacion_pendrive`) para pausar el sondeo mientras se ejecuta `os.sync()` y `udisksctl`.
- **[Riesgo]** El navegador intenta enviar comandos POST repetidos al hacer doble clic.
  - *Mitigación*: Deshabilitar inmediatamente el botón de acción en la interfaz con estado "Procesando..." hasta recibir la respuesta.
