# Proposal: Compatibilidad con Windows 10/11 (port-windows)

## Why

El sistema Lucie y su bandeja de descargas fueron desarrollados y probados inicialmente en entornos Linux/POSIX, dependiendo de características específicas como `/proc/mounts`, `sysfs`, `notify-send`, rutas case-sensitive y el comportamiento de sockets de red bajo POSIX. Para que el usuario pueda operar la bandeja de descargas de forma nativa en estaciones con Windows 10 u 11 ejecutando Python 3.13 desde el código fuente (sin generar ejecutables binarios opacos) y utilizando el mismo pendrive formateado en exFAT, es imprescindible portar el sistema garantizando estricta paridad funcional, aislamiento de SO en `bandeja/plataforma.py`, tolerancia a bloqueos transitorios de archivos en Windows y cumplimiento total de las 7 Reglas de Oro con 0 infracciones en el análisis estático AST anti-borrado.

## What Changes

- **Lanzador para Windows**: Incorporación de `iniciar_bandeja.bat` que busca el intérprete con `py -3` o `python`, se posiciona en el directorio del proyecto, inicia la bandeja, abre el navegador en `http://127.0.0.1:<puerto>` y preserva la ventana de consola con el log activo, guiando la instalación de Python 3.13 con "Add python.exe to PATH" si no se encuentra el intérprete.
- **Manual de usuario para Windows**: Creación de `README_WINDOWS.md` (en español y conciso) documentando instalación de Python 3.13, arranque, primer uso, vinculación del pendrive exFAT y directrices de aislamiento (cada equipo mantiene su base de datos SQLite local independiente).
- **Configuración por equipo y detección automática de descargas**: Soporte de `config_bandeja.local.json` opcional que sobreescribe la configuración base sin versionarse en Git. Soporte para `"ruta_descargas": "auto"` que resuelve la carpeta de descargas del usuario vía `SHGetKnownFolderPath` (ctypes) en Windows (con respaldo en `%USERPROFILE%\Downloads`) y `~/Descargas` o `~/Downloads` en Linux. Creación exclusiva (modo `'xb'`) de la configuración local en el primer arranque de Windows si no existe.
- **Instancia única y exclusividad de puertos**: Configuración de sockets con `SO_EXCLUSIVEADDRUSE` en Windows para impedir que dos instancias escuchen en el mismo puerto (`SO_REUSEADDR` permite colisiones silenciosas en Windows). Detección amigable del puerto ocupado mostrando `"Ya hay una bandeja corriendo en el puerto N"` y finalización limpia del proceso en Linux y Windows.
- **Codificación y consola UTF-8**: Reconfiguración de `sys.stdout` y `sys.stderr` en el arranque con `encoding="utf-8", errors="replace"` para evitar excepciones con emojis en consolas de Windows (`cmd.exe`/PowerShell). Apertura explícita de todo archivo de texto (bitácora, manifiesto, configuración, logs) con `encoding="utf-8"` y `newline="\n"`.
- **Normalización Unicode**: Normalización a NFC (`unicodedata.normalize("NFC", ...)`) en nombres de escenas y capítulos al compararlos para neutralizar inconsistencias de codificación entre sistemas de archivos.
- **Confinamiento robusto y rutas multiplataforma**: Sustitución de comprobaciones basadas en `startswith` por `os.path.realpath` combinado con `os.path.normcase` y `os.path.commonpath`. Rechazo de accesos entre distintas unidades o rutas UNC no autorizadas. Manejo explícito y amigable de rutas que excedan el límite MAX_PATH (260 caracteres).
- **Normalización de separadores y nombres prohibidos**: Almacenamiento uniforme de `ruta_relativa` en el manifiesto del pendrive y en la bitácora siempre con separador `"/"`. Validación en `ValidadorEscenas` y destinos contra caracteres prohibidos `< > : " / \ | ? *`, nombres reservados de dispositivos Windows (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`) y nombres terminados en punto o espacio en todos los sistemas operativos.
- **Manejo de archivos bloqueados y operaciones de filesystem en Windows**: Detección de archivos en uso (`PermissionError`, `WinError 32`) en el vigilante tratándolos como descargas no estables transitorias. Gestión resiliente en movimientos de lotes informando "archivo en uso" sin abortar el lote ni interrumpir el proceso. Detección y rechazo claro de movimientos de archivo que intenten cruzar distintas unidades con `os.rename`.
- **Determinación de fecha de llegada compatible con Python 3.12+**: Adaptación de `obtener_fecha_llegada` para priorizar `st_birthtime` en Windows cuando esté disponible, previniendo advertencias de deprecación de `st_ctime`.
- **Tipos MIME de reserva**: Tabla de respaldo en el servidor para extensiones multimedia (`.mp4`, `.mov`, `.webm`, `.jpg`, `.jpeg`, `.png`, `.webp`) previniendo omisiones del registro de Windows.
- **Aislamiento de pendrive en plataforma.py**: Detección de pendrives en Windows mediante ctypes (`GetLogicalDrives`, `GetDriveTypeW`, `GetVolumeInformationW`) con protección `SetErrorMode(SEM_FAILCRITICALERRORS)` para evitar diálogos modales molestos del sistema. Consulta de espacio libre con `shutil.disk_usage`. Ocultación o desactivación de acciones dependientes de `udisksctl` (montar, desmontar, expulsar) en Windows. Tolerancia total a la ausencia de `notify-send`.
- **Herramienta de verificación para Windows**: Creación de `verificar_windows.py` (estándar, sin dependencias externas) que ejecuta diagnósticos de entorno, rutas, filesystem, sockets y APIs emitiendo `verificacion_windows.txt` sin borrar ningún dato.
- **Suite de pruebas multiplataforma**: Simulación de rutas y comportamiento de Windows (`ntpath`, mocks de ctypes y `sys.platform`), validación de confinamiento case-insensitive, tests de instancia única y adaptación con `skipUnless` para tests exclusivos de POSIX o Windows.

## Capabilities

### New Capabilities
- `port-windows`: Soporte nativo para Windows 10 y 11 con Python 3.13, garantizando compatibilidad multiplataforma con Linux, aislamiento de SO en `bandeja/plataforma.py`, socket exclusivo contra colisiones, confinamiento insensible a mayúsculas/minúsculas, manejo de archivos bloqueados, interoperabilidad en exFAT y suite de diagnóstico.

### Modified Capabilities
*(Ninguna; se preservan todas las especificaciones y contratos existentes sin alteraciones regresivas).*

## Impact

- **Código modificado**:
  - `bandeja/plataforma.py`: Detección de descargas por ctypes (`SHGetKnownFolderPath`), detección de pendrives y filesystems en Windows (`GetLogicalDrives`, `GetDriveTypeW`, `GetVolumeInformationW`), helper canónico de confinamiento (`esta_confinado_en_raiz`).
  - `bandeja/config.py`: Soporte de `config_bandeja.local.json`, soporte de `"ruta_descargas": "auto"`, creación exclusiva `xb` en primer arranque.
  - `bandeja/servidor.py`: Conexión de socket con `SO_EXCLUSIVEADDRUSE` en Windows, control de puerto en uso, confinamiento canónico en `/api/media` y archivos estáticos, tabla de respaldo de tipos MIME.
  - `bandeja/movimientos.py`: Confinamiento robusto con `normcase` y `commonpath`, manejo resiliente de `PermissionError` (archivo en uso), persistencia de `ruta_relativa` con `"/"`.
  - `bandeja/pendrive.py`: Confinamiento con `normcase`, protección condicional para `os.sync()`, omisión de botones udisksctl en Windows, persistencia de `ruta_relativa` con `"/"`.
  - `bandeja/clasificacion.py`: Confinamiento canónico en `ValidadorEscenas` y `asegurar_carpeta_capitulo`, normalización NFC en nombres, validación contra caracteres y nombres reservados Windows en todos los entornos.
  - `bandeja/lotes.py`: Adaptación de `obtener_fecha_llegada` para soportar `st_birthtime` en Windows / Python 3.13 sin `DeprecationWarning`.
  - `bandeja/vigilante.py`: Tolerancia a `PermissionError`/`WinError 32` al calcular hashes o inspeccionar archivos en descarga.
  - `bandeja_descargas.py`: Reconfiguración UTF-8 de `sys.stdout`/`sys.stderr`, captura amigable de puerto ocupado.
  - `.gitignore`: Inclusión de `config_bandeja.local.json`, `*.sqlite`, `verificacion_windows.txt`.
- **Nuevos componentes**:
  - `iniciar_bandeja.bat`
  - `README_WINDOWS.md`
  - `verificar_windows.py`
  - `test_compatibilidad_windows.py`
- **Dependencias**:
  - 0 dependencias externas (solo biblioteca estándar de Python y `ctypes`).
- **Seguridad y Reglas de Oro**:
  - 0 infracciones en el análisis estático AST (`seguridad_anti_borrado.py`).
  - Preservación íntegra de las 7 Reglas de Oro en ambos sistemas operativos.
