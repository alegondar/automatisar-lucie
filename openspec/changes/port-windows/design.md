# Design: Arquitectura y Compatibilidad Multiplataforma (port-windows)

## Context

El sistema Lucie y su bandeja de descargas fueron desarrollados bajo supuestos del ecosistema Linux (rutas UNIX sensibles a mayúsculas, `/proc/mounts`, `sysfs`, `notify-send`, semantics de sockets POSIX y comandos `udisksctl`). Para ejecutar la aplicación en Windows 10/11 con Python 3.13 sin empaquetadores externos (.exe), el código debe adaptarse para correr con la biblioteca estándar de Python y `ctypes`, compartiendo un pendrive formateado en exFAT (sin el límite de 4 GiB de FAT32, pero sin distinción de mayúsculas y minúsculas).
Se debe garantizar paridad funcional completa, preservación de las 7 Reglas de Oro del proyecto (especialmente la Regla #1 de prohibición absoluta de borrado y pisado destructivo y la Regla #7 de 0 infracciones AST en `seguridad_anti_borrado.py`), y aislamiento de toda lógica dependiente del sistema operativo en `bandeja/plataforma.py`.

## Goals / Non-Goals

**Goals:**
- Centralizar todas las llamadas a APIs del sistema operativo, detección de pendrives y rutas del sistema en `bandeja/plataforma.py`.
- Proveer un punto de arranque nativo `iniciar_bandeja.bat` y un manual claro en `README_WINDOWS.md`.
- Soportar sobreescritura local de configuración mediante `config_bandeja.local.json` con creación exclusiva (`xb`) y detección automática de descargas (`ruta_descargas: "auto"`).
- Garantizar instancia única de servidor mediante `SO_EXCLUSIVEADDRUSE` en Windows y manejo amigable de puerto ocupado en todas las plataformas.
- Forzar codificación UTF-8 explícita en consola (`reconfigure`) y en toda apertura de archivos de texto con `newline="\n"`.
- Implementar validación de confinamiento canónica multiplataforma (`realpath`, `normcase`, `commonpath`), tolerando insensibilidad a mayúsculas y detectando diferencias de unidad o rutas UNC.
- Manejar robustamente archivos bloqueados (`PermissionError` / `WinError 32`) en el vigilante y movimientos sin abortar lotes ni procesos.
- Implementar detección de pendrives en Windows con `ctypes` (`GetLogicalDrives`, `GetDriveTypeW`, `GetVolumeInformationW`) bajo `SetErrorMode(SEM_FAILCRITICALERRORS)`.
- Diseñar y proveer la herramienta de diagnóstico `verificar_windows.py` para validar el entorno en Windows sin borrar ningún dato.
- Mantener la suite completa de tests pasando en Linux y simular Windows mediante `unittest.mock` y `ntpath`.

**Non-Goals:**
- Generar archivos ejecutables binarios (.exe, instaladores MSI o empaquetados PyInstaller).
- Permitir la sincronización o copia de bases de datos SQLite entre Linux y Windows (cada equipo mantiene su base local independiente).
- Integrar bibliotecas de terceros de PyPI (solo biblioteca estándar de Python y `ctypes`).
- Implementar desmontaje de bajo nivel o expulsión de hardware por software en Windows (se delega en el explorador y la bandeja del sistema operativo).

## Decisions

### Decisión 1: Aislamiento centralizado en `bandeja/plataforma.py`
- **Enfoque**: Todas las bifurcaciones de sistema operativo (`os.name == "nt"` vs `os.name == "posix"`) y llamadas a `ctypes` residen en `bandeja/plataforma.py`. Los demás módulos consumen funciones abstractas como `obtener_ruta_descargas_defecto()`, `detectar_unidades_windows()`, `esta_confinado_en_raiz(ruta, raiz)`, `sincronizar_disco()`, etc.
- **Alternativas consideradas**: Esparcir condicionales de plataforma en `servidor.py`, `vigilante.py` y `pendrive.py`. Descartado porque aumentaría el acoplamiento y dificultaría las pruebas unitarias y el análisis de seguridad.

### Decisión 2: Confinamiento de rutas mediante `os.path.normcase` y `os.path.commonpath`
- **Enfoque**: En lugar de verificar pertenencia con `cadena.startswith(base)`, se crea una función de validación canónica:
  ```python
  def esta_confinado_en_raiz(ruta: str, raiz: str) -> bool:
      ruta_real = os.path.normcase(os.path.realpath(ruta))
      raiz_real = os.path.normcase(os.path.realpath(raiz))
      try:
          return os.path.commonpath([ruta_real, raiz_real]) == raiz_real
      except (ValueError, OSError):
          return False
  ```
  Esto maneja de forma natural la insensibilidad a mayúsculas de Windows (`c:\` vs `C:\`), rechaza rutas en unidades distintas (que generan `ValueError` en `commonpath`), descarta rutas UNC fuera del árbol y funciona de forma idéntica en Linux.
- **Alternativas consideradas**: Usar `startswith` sobre rutas convertidas a minúsculas (`.lower()`). Descartado porque no protege adecuadamente contra colisiones de prefijo (ej: `C:\Descargas-otro` contra `C:\Descargas`) ni gestiona las reglas específicas de caracteres en distintos sistemas de archivos.

### Decisión 3: Exclusividad de socket en Windows (`SO_EXCLUSIVEADDRUSE`)
- **Enfoque**: En Windows, `SO_REUSEADDR` permite que múltiples sockets se vinculen al mismo puerto, lo que provocaría que dos instancias de la bandeja corran simultáneamente interceptando peticiones aleatorias. En Windows se desactiva `allow_reuse_address` o se configura `socket.SO_EXCLUSIVEADDRUSE` antes del `bind()`. Al capturar `socket.error` (o `OSError` con código de error de puerto en uso), se imprime `"Ya hay una bandeja corriendo en el puerto N"` y se sale limpiamente.
- **Alternativas consideradas**: Archivo de bloqueo (.lock). Descartado porque ante un apagado abrupto o caída del proceso el archivo puede quedar huérfano e impedir el arranque posterior.

### Decisión 4: Resolución de descargas vía `SHGetKnownFolderPath` y `config_bandeja.local.json`
- **Enfoque**: En Windows, la carpeta de descargas no siempre es `%USERPROFILE%\Downloads` (el usuario puede haberla movido a otra unidad). Usamos `ctypes.windll.shell32.SHGetKnownFolderPath` con el GUID conocido de Downloads (`{374DE290-123F-4565-9164-39C4925E467B}`), con respaldo a `%USERPROFILE%\Downloads`. `ConfiguracionBandeja` admite `config_bandeja.local.json` que pisa los valores del JSON base. Si no existe en Windows, se crea en modo `'xb'` durante el primer arranque con los valores detectados.
- **Alternativas consideradas**: Leer únicamente variables de entorno. Descartado porque no refleja cambios en carpetas personales personalizadas en Windows 10/11.

### Decisión 5: Tratamiento de bloqueos de archivo (`PermissionError` / `WinError 32`)
- **Enfoque**: En Windows, abrir un archivo en descarga activa o mover un archivo abierto por otra aplicación arroja `PermissionError` (código de error 32). El vigilante captura este error y lo considera "descarga activa / no estable", reintentando en la siguiente pasada. En `GestorMovimientosBandeja`, si un archivo individual genera este error al mover, se reporta "archivo en uso" sin abortar el procesamiento de los demás archivos del lote ni interrumpir el proceso.
- **Alternativas consideradas**: Abortar el lote completo. Descartado porque la descarga de un archivo secundario paralizaría el flujo de trabajo del usuario.

### Decisión 6: Determinación de fecha de llegada y conservación en movimientos
- **Enfoque**: En Windows, `st_ctime` representa la fecha de creación y en Python 3.12+ emite `DeprecationWarning`. En su lugar, se evalúa `getattr(st, "st_birthtime", None)` o se accede de forma segura según la plataforma.
- **Nota arquitectónica**: Al mover un archivo con `os.rename` dentro del mismo volumen de almacenamiento, el sistema de archivos conserva intacta la fecha de creación original del archivo (`st_birthtime`). Al transferir al pendrive entre distintos volúmenes, la operación se realiza mediante copia (`xb`) preservando metadatos y recalculando hashes de verificación.

### Decisión 7: Interacción con unidades de almacenamiento en Windows
- **Enfoque**: Para detectar el pendrive en Windows sin bloqueos de interfaz ni carteles del sistema (ej: "No hay disco en la unidad"), se utiliza `ctypes.windll.kernel32.SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX)`. Se enumeran las unidades con `GetLogicalDrives()` y `GetDriveTypeW()` identificando tipos removibles (`DRIVE_REMOVABLE = 2`) y fijos (`DRIVE_FIXED = 3`). Para cada letra candidata se inspecciona la raíz en búsqueda de `.lucie_pendrive.json`.
- **Desmontaje y expulsión**: Las funciones que llaman a `udisksctl` en Linux se deshabilitan en Windows; el panel web omite o desactiva estos controles en Windows, dejando la expulsión a la acción estándar de la bandeja de Windows. Si este cambio de UI no estuviera aplicado, la API retorna un estado indicando que la función no está disponible en la plataforma actual.

### Decisión 8: Fallback de tipos MIME
- **Enfoque**: En Windows, `mimetypes.guess_type` depende de las claves en el Registro de Windows (`HKEY_CLASSES_ROOT`), las cuales pueden estar corruptas o ausentes. Se agrega un diccionario estático de reserva para formatos multimedia soportados (`.mp4`, `.mov`, `.webm`, `.jpg`, `.jpeg`, `.png`, `.webp`) para garantizar que `/api/media` y las vistas previas siempre envíen el `Content-Type` correcto.

## Risks / Trade-offs

- **[Riesgo: Cruce de unidades de disco con `os.rename`]** → *Mitigación*: En Windows no es posible usar `os.rename` entre diferentes letras de unidad (ej: de `C:\` a `D:\`). Se valida de forma explícita mediante `os.path.splitdrive` que origen y destino compartan unidad antes del movimiento; el envío al pendrive utiliza el flujo seguro establecido de copia exclusiva (`xb`) seguida de verificación de hash y renombrado dentro del pendrive.
- **[Riesgo: Nombres reservados DOS en sistemas exFAT/Windows]** → *Mitigación*: `ValidadorEscenas` y los generadores de nombres en pendrive rechazan de manera estricta `CON`, `PRN`, `AUX`, `NUL`, `COM1`-`COM9`, `LPT1`-`LPT9`, `<>:"/\|?*` y terminaciones en punto o espacio en todos los sistemas operativos.
- **[Riesgo: Bloqueos de red al reabrir el puerto]** → *Mitigación*: Uso de `SO_EXCLUSIVEADDRUSE` en Windows para evitar secuestro de socket, y cierre explícito en el manejador de señales y bloques `finally`.
- **[Riesgo: Límites de longitud de ruta de 260 caracteres (MAX_PATH)]** → *Mitigación*: Se audita la longitud total antes de operaciones de archivo, retornando un error comprensible si se excede el límite en lugar de propagar un fallo de sistema operativo incomprensible.

## Migration Plan

1. El despliegue en Windows requiere únicamente descargar o clonar el repositorio y ejecutar `iniciar_bandeja.bat` con Python 3.13 instalado.
2. No se modifican contratos de API REST ni formatos de base de datos SQLite.
3. El archivo `config_bandeja.json` permanece inalterado como plantilla base, permitiendo a los entornos Windows coexistir sin modificar el control de versiones mediante `config_bandeja.local.json`.
