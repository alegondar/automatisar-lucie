# Spec Delta: Compatibilidad con Windows 10/11 (port-windows)

## Purpose

Proveer soporte nativo para la ejecución de la bandeja de descargas en sistemas operativos Windows 10 y Windows 11 con Python 3.13, manteniendo paridad funcional estricta con Linux, aislamiento de código de sistema operativo en la capa de plataforma, utilización exclusiva de la biblioteca estándar (incluyendo ctypes), y pleno cumplimiento de las 7 Reglas de Oro con cero infracciones en el análisis estático AST anti-borrado.

## ADDED Requirements

### Requirement: Arranque nativo en Windows mediante lanzador por lotes
El sistema SHALL proveer un lanzador `iniciar_bandeja.bat` que detecte el entorno Python (intentando `py -3` y luego `python`), ubique la raíz del proyecto, inicie el servidor de la bandeja de descargas, abra el navegador web predeterminado en `http://127.0.0.1:<puerto>` y mantenga visible la consola de logs. En caso de no encontrar Python, SHALL mostrar instrucciones claras para su instalación con la opción "Add python.exe to PATH".

#### Scenario: Ejecución exitosa con intérprete Python disponible
- **WHEN** el usuario ejecuta `iniciar_bandeja.bat` en Windows con Python instalado
- **THEN** el script inicia el proceso de la bandeja, abre la URL del panel web en el navegador y mantiene la consola abierta mostrando el registro de actividad

#### Scenario: Ejecución en equipo sin Python instalado en el PATH
- **WHEN** el usuario ejecuta `iniciar_bandeja.bat` y ni `py` ni `python` se encuentran disponibles
- **THEN** el script detiene la ejecución, muestra un mensaje explicando cómo instalar Python 3.13 marcando la casilla "Add python.exe to PATH", y espera una pulsación de tecla antes de cerrar

---

### Requirement: Documentación operativa para Windows
El sistema SHALL incluir un archivo `README_WINDOWS.md` redactado en español con instrucciones paso a paso para instalar Python 3.13, iniciar la bandeja, realizar la vinculación del pendrive exFAT y advertir expresamente que la base de datos SQLite es local a cada equipo y nunca debe copiarse entre Linux y Windows.

#### Scenario: Consulta del manual de usuario para Windows
- **WHEN** el usuario consulta `README_WINDOWS.md`
- **THEN** encuentra los pasos concisos de primer uso, advertencias de aislamiento de base de datos SQLite y requisitos de configuración local

---

### Requirement: Configuración local por equipo y autodetección de descargas
El sistema SHALL permitir la existencia de un archivo opcional `config_bandeja.local.json` que sobrescriba los valores de `config_bandeja.json`. Cuando `ruta_descargas` contenga el valor `"auto"`, el sistema SHALL resolver en Windows la carpeta real de Descargas mediante `SHGetKnownFolderPath` (GUID FOLDERID_Downloads vía ctypes) con respaldo a `%USERPROFILE%\Downloads`, y en Linux `~/Descargas` o `~/Downloads`. En el primer arranque en Windows sin configuración local previa, SHALL crear `config_bandeja.local.json` mediante apertura exclusiva en modo `'xb'`.

#### Scenario: Resolución de ruta de descargas automática en Windows
- **WHEN** el sistema se inicia en Windows con `ruta_descargas` configurado en `"auto"`
- **THEN** resuelve la ruta canónica de la carpeta Downloads del usuario autenticado utilizando la API nativa de Windows con respaldo de entorno

#### Scenario: Creación exclusiva del archivo de configuración local en primer arranque
- **WHEN** la bandeja inicia en Windows y no existe `config_bandeja.local.json`
- **THEN** el sistema genera `config_bandeja.local.json` utilizando modo `'xb'` para garantizar que nunca sobrescriba un archivo preexistente

---

### Requirement: Instancia única de servidor y prevención de colisiones de socket
El servidor HTTP SHALL configurarse con la opción de socket `SO_EXCLUSIVEADDRUSE` en Windows para evitar que múltiples procesos compartan el mismo puerto de escucha. Tanto en Windows como en Linux, si el puerto ya se encuentra en uso por otra instancia, el sistema SHALL capturar el error de enlace, mostrar `"Ya hay una bandeja corriendo en el puerto N"` y finalizar sin lanzar una traza de excepción no controlada.

#### Scenario: Apertura de socket en Windows
- **WHEN** el servidor HTTP se enlaza a la dirección y puerto en Windows
- **THEN** aplica `SO_EXCLUSIVEADDRUSE` sobre el socket antes del bind impidiendo que otro proceso se apropie o comparta dicho puerto

#### Scenario: Detección de puerto en uso en arranque
- **WHEN** se intenta iniciar la bandeja y ya existe otro proceso escuchando en el puerto configurado
- **THEN** la aplicación imprime `"Ya hay una bandeja corriendo en el puerto N"` y finaliza limpiamente con código de error

---

### Requirement: Codificación UTF-8 universal y reconfiguración de consola
El sistema SHALL reconfigurar `sys.stdout` y `sys.stderr` al iniciar con `encoding="utf-8"` y `errors="replace"` para asegurar que emojis y caracteres acentuados no generen fallas de codificación en consolas de Windows. Todas las operaciones de apertura de archivos de texto (manifiestos, bitácoras, configuraciones y registros) SHALL especificar explícitamente `encoding="utf-8"` y `newline="\n"`.

#### Scenario: Emisión de registros con caracteres Unicode y emojis en consola
- **WHEN** el servidor o vigilante emite líneas de log que contienen caracteres no ASCII o emojis
- **THEN** la salida se renderiza correctamente sin generar `UnicodeEncodeError` en la consola de comandos de Windows

#### Scenario: Escritura y lectura de archivos de texto en Windows
- **WHEN** el sistema escribe o lee bitácoras, archivos de configuración o manifiestos en Windows
- **THEN** utiliza siempre codificación UTF-8 y saltos de línea LF (`\n`), evitando la traducción automática de CRLF o el uso del juego de caracteres cp1252

---

### Requirement: Normalización Unicode NFC en nombres de escenas y capítulos
El sistema SHALL normalizar a la forma canónica NFC (`unicodedata.normalize("NFC", ...)`) todas las cadenas de texto correspondientes a nombres de escenas, personajes y capítulos antes de realizar comparaciones de igualdad, pertenencia o búsquedas.

#### Scenario: Comparación de nombres con tildes o caracteres combinados
- **WHEN** se compara el nombre de una escena o capítulo que posee caracteres acentuados o diacríticos
- **THEN** ambas cadenas se normalizan a NFC garantizando coincidencia exacta independientemente de cómo hayan sido codificadas por el sistema de archivos de origen

---

### Requirement: Confinamiento estricto de rutas multiplataforma y prevención de path traversal
El sistema SHALL verificar el confinamiento de todas las rutas de lectura, escritura y servicio web (incluyendo `/api/media`, estáticos del panel web, descarte de capítulos y transferencias al pendrive) utilizando `os.path.realpath`, `os.path.normcase` y `os.path.commonpath`. El sistema SHALL rechazar rutas ubicadas en distintas unidades de disco, rutas UNC fuera de la raíz autorizada y rutas cuya longitud exceda 260 caracteres emitiendo un mensaje claro de error.

#### Scenario: Validación de ruta dentro de la raíz permitida en entorno insensible a mayúsculas
- **WHEN** se valida una ruta con diferencias de mayúsculas/minúsculas respecto a la carpeta autorizada
- **THEN** el sistema normaliza con `normcase` y `commonpath`, confirmando que pertenece a la raíz autorizada sin depender de comparaciones de cadenas directas

#### Scenario: Intento de acceso a ruta ubicada en otra unidad de disco o UNC
- **WHEN** una petición o proceso intenta referenciar una ruta situada en una letra de unidad distinta a la raíz permitida
- **THEN** el sistema detecta que no comparten raíz común y rechaza la operación por violación de seguridad

#### Scenario: Detección de ruta que excede 260 caracteres
- **WHEN** se evalúa una ruta cuya longitud absoluta supera el límite de 260 caracteres de Windows MAX_PATH
- **THEN** el sistema falla controladamente informando la longitud excesiva en lugar de provocar una excepción de I/O no controlada

---

### Requirement: Validación universal de nombres de archivo y caracteres prohibidos
El validador de escenas y todas las funciones que definen nombres destinados al almacenamiento en disco o pendrive SHALL rechazar en todos los sistemas operativos: caracteres reservados `< > : " / \ | ? *`, nombres de dispositivo DOS/Windows (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`) independientemente de la extensión, y nombres que finalicen con un punto o con un espacio. Asimismo, el campo `ruta_relativa` en el manifiesto y en la bitácora SHALL almacenarse siempre con barras inclinadas (`/`).

#### Scenario: Rechazo de nombres de archivo con caracteres inválidos
- **WHEN** se intenta crear una escena o archivo cuyo nombre contiene `<`, `>`, `:`, `"`, `|`, `?` o `*`
- **THEN** la validación rechaza el nombre indicando los caracteres no permitidos tanto en Linux como en Windows

#### Scenario: Rechazo de nombres reservados de dispositivo
- **WHEN** se intenta utilizar un nombre como `CON`, `aux.txt` o `NUL`
- **THEN** el sistema rechaza el nombre identificándolo como reservado para sistemas de archivos compatibles con Windows/exFAT

#### Scenario: Registro de ruta relativa con barra inclinada
- **WHEN** se añade una entrada de transferencia en el manifiesto del pendrive o en la bitácora
- **THEN** los separadores de directorio de la ruta relativa se registran normalizados con `/`

---

### Requirement: Resiliencia ante archivos bloqueados o en uso en Windows
El vigilante de descargas SHALL capturar excepciones de archivo en uso (`PermissionError` o código de error del sistema 32) al inspeccionar archivos o calcular hashes, clasificando el archivo como temporalmente no estable y programando su reintento en el siguiente ciclo. Durante las operaciones de movimiento de lotes, si un archivo no puede moverse debido a un bloqueo de proceso, el sistema SHALL registrar que el archivo está en uso y continuar con los demás elementos sin abortar el lote ni interrumpir la ejecución.

#### Scenario: Archivo bloqueado por un navegador o descargador activo
- **WHEN** el vigilante intenta calcular el hash SHA-256 de un archivo retenido por otro proceso con bloqueo exclusivo
- **THEN** captura la excepción de permisos y pospone el procesamiento sin generar alertas críticas ni abortar el escaneo

#### Scenario: Movimiento seguro de lote con un archivo retenido
- **WHEN** se ejecuta el movimiento de un conjunto de archivos y uno de ellos se encuentra bloqueado
- **THEN** el sistema informa "archivo en uso" para dicho archivo, mantiene el resto de movimientos seguros y no interrumpe el servicio

---

### Requirement: Determinación de fecha de llegada compatible con Python 3.12+
La función `obtener_fecha_llegada` SHALL verificar la disponibilidad del atributo `st_birthtime` en el resultado de `os.stat` antes de recurrir a `st_ctime` en plataformas Windows, asegurando que el cálculo de la fecha efectiva de llegada no dispare advertencias de deprecación (`DeprecationWarning`) y determine correctamente la fecha de creación del archivo.

#### Scenario: Consulta de fecha de llegada en Windows con Python 3.13
- **WHEN** se calcula la fecha de llegada de un archivo recién descargado o movido dentro del mismo volumen
- **THEN** la función utiliza `st_birthtime` junto a `st_mtime` para determinar la fecha efectiva sin emitir advertencias de deprecación

---

### Requirement: Detección y operación de pendrive en Windows mediante ctypes
La capa de plataforma en `bandeja/plataforma.py` SHALL implementar la detección de unidades candidatas en Windows consultando las letras de unidad disponibles mediante `GetLogicalDrives` y filtrando tipos mediante `GetDriveTypeW` con protección `SetErrorMode(SEM_FAILCRITICALERRORS)`. El sistema SHALL consultar el tipo de sistema de archivos (exFAT, FAT32, NTFS) mediante `GetVolumeInformationW` y el espacio libre mediante `shutil.disk_usage`, manteniendo el aislamiento de ejecución en hilo separado con límite de tiempo de 3 segundos.

#### Scenario: Escaneo de unidades removibles en Windows
- **WHEN** el sistema busca el pendrive en Windows
- **THEN** evalúa las letras de unidad activas evitando carteles del sistema operativo, localiza el marcador `.lucie_pendrive.json` e identifica el sistema de archivos y espacio libre

#### Scenario: Consulta en sistema sin soporte udisksctl
- **WHEN** la bandeja se ejecuta en Windows
- **THEN** las opciones de montaje, desmontaje y expulsión por `udisksctl` no son invocadas y el sistema opera tolerando que la expulsión sea gestionada por el entorno de escritorio

---

### Requirement: Script de verificación integral para Windows
El sistema SHALL incluir una herramienta de diagnóstico `verificar_windows.py` construida exclusivamente con la biblioteca estándar que evalúe y reporte el estado del entorno en Windows: versiones de Python y SO, codificación de consola, carpeta de descargas detectada, pruebas de creación y renombrado en una carpeta temporal `_verificacion_windows`, rechazo de colisiones en destino existente, manejo de rutas largas y nombres reservados, unidades lógicas con sistema de archivos y marcador, fecha de llegada (`st_ctime` vs `st_birthtime`), enlace exclusivo del puerto de red y servicio multimedia con cabecera `Range`. Los resultados SHALL ser registrados en `verificacion_windows.txt` sin realizar ningún borrado de datos.

#### Scenario: Ejecución de verificación en estación Windows
- **WHEN** el usuario ejecuta `python verificar_windows.py`
- **THEN** la herramienta evalúa cada prueba imprimiendo `OK` o `FALLA` con su justificación, genera `verificacion_windows.txt`, conserva los archivos de prueba para auditoría y recuerda al usuario eliminarlos manualmente
