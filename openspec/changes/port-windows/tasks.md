# Tasks: Implementación de Compatibilidad con Windows 10/11 (port-windows)

## 1. Arranque, Documentación y Exclusividad de Socket

- [x] 1.1 Crear el lanzador `iniciar_bandeja.bat` con detección de `py -3` o `python`, posicionamiento en carpeta del proyecto, apertura de navegador en `http://127.0.0.1:<puerto>` y mensaje de ayuda si Python no está en PATH
- [x] 1.2 Crear `README_WINDOWS.md` en español explicando instalación de Python 3.13, arranque, primer uso, vinculación de pendrive exFAT y directriz de no copiar la base SQLite entre equipos
- [x] 1.3 Actualizar `.gitignore` para ignorar `config_bandeja.local.json`, bases SQLite (`*.sqlite`, `*.db`) y reportes locales de verificación
- [x] 1.4 Configurar el servidor HTTP (`bandeja/servidor.py` y `bandeja_descargas.py`) con `SO_EXCLUSIVEADDRUSE` en Windows y captura de error de puerto ocupado mostrando `"Ya hay una bandeja corriendo en el puerto N"` con salida limpia

## 2. Configuración por Equipo y Autodetección de Descargas

- [x] 2.1 Implementar en `bandeja/plataforma.py` la resolución de la carpeta de descargas de Windows mediante `ctypes` (`SHGetKnownFolderPath` con `FOLDERID_Downloads`) con respaldo a `%USERPROFILE%\Downloads`
- [x] 2.2 Actualizar `ConfiguracionBandeja` en `bandeja/config.py` para cargar `config_bandeja.local.json` opcional sobre `config_bandeja.json` y resolver `"ruta_descargas": "auto"`
- [x] 2.3 Implementar la creación exclusiva en modo `'xb'` de `config_bandeja.local.json` en el primer arranque en Windows cuando el archivo no exista
- [x] 2.4 Agregar pruebas unitarias para la carga de configuración local y resolución automática en `test_compatibilidad_windows.py`

## 3. Codificación, Consola y Normalización Unicode

- [x] 3.1 Reconfigurar `sys.stdout` y `sys.stderr` en `bandeja_descargas.py` al arrancar con `encoding="utf-8", errors="replace"`
- [x] 3.2 Auditar y asegurar `encoding="utf-8"` explícito y `newline="\n"` en toda apertura de archivos de texto en `bandeja/`, `bandeja_descargas.py` e utilitarios
- [x] 3.3 Aplicar normalización Unicode NFC (`unicodedata.normalize("NFC", ...)`) en nombres de escenas y capítulos al compararlos en `bandeja/clasificacion.py`, `bandeja/movimientos.py` y `bandeja/capitulos.py`
- [x] 3.4 Agregar pruebas unitarias de persistencia UTF-8 con tildes/emojis y comparación normalizada NFC

## 4. Confinamiento de Rutas, Longitud y Validación de Nombres

- [x] 4.1 Implementar la función canónica de confinamiento `esta_confinado_en_raiz(ruta, raiz)` en `bandeja/plataforma.py` utilizando `os.path.realpath`, `os.path.normcase` y `os.path.commonpath`
- [x] 4.2 Migrar todas las comprobaciones de confinamiento en `bandeja/servidor.py`, `bandeja/movimientos.py`, `bandeja/pendrive.py` y `bandeja/capitulos.py` a la validación canónica, rechazando unidades distintas y rutas UNC no autorizadas
- [x] 4.3 Incorporar validación contra el límite MAX_PATH (260 caracteres) con mensaje de error comprensible en las validaciones de ruta
- [x] 4.4 Actualizar `ValidadorEscenas` y generadores de rutas de pendrive para rechazar en todos los sistemas operativos: caracteres `< > : " / \ | ? *`, nombres reservados (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`) y nombres terminados en punto o espacio
- [x] 4.5 Garantizar que `ruta_relativa` en el manifiesto del pendrive y en la bitácora se persista siempre normalizada con separador `"/"`
- [x] 4.6 Agregar pruebas unitarias en `test_compatibilidad_windows.py` para confinamiento case-insensitive, rechazo de otra unidad, nombres reservados y separadores "/"

## 5. Resiliencia de Archivos, Fechas y Tipos MIME en Windows

- [x] 5.1 Adaptar el detector de estabilidad en `bandeja/lotes.py` y el vigilante en `bandeja/vigilante.py` para capturar `PermissionError` y `WinError 32`, clasificando el archivo como descarga no estable transitoria
- [x] 5.2 Adaptar `GestorMovimientosBandeja` en `bandeja/movimientos.py` para reportar "archivo en uso" cuando ocurra un bloqueo de proceso sin abortar el resto del lote ni fallar el proceso
- [x] 5.3 Validar antes de `os.rename` que origen y destino compartan unidad lógica, impidiendo fallos silenciosos entre volúmenes distintos
- [x] 5.4 Adaptar `obtener_fecha_llegada` en `bandeja/lotes.py` para usar `st_birthtime` en Windows / Python 3.12+ evitando `DeprecationWarning` de `st_ctime`
- [x] 5.5 Incorporar tabla de respaldo para `mimetypes` en `bandeja/servidor.py` para formatos multimedia clave (`.mp4`, `.mov`, `.webm`, `.jpg`, `.jpeg`, `.png`, `.webp`)
- [x] 5.6 Proteger llamadas exclusivas de POSIX en el código (`os.sync()` condicional a `hasattr(os, "sync")`, `/proc`, `/sys`)

## 6. Detección y Operación de Pendrive en Windows (`bandeja/plataforma.py`)

- [x] 6.1 Implementar detección de pendrives en Windows mediante `GetLogicalDrives`, `GetDriveTypeW` y `SetErrorMode(SEM_FAILCRITICALERRORS)` con búsqueda de `.lucie_pendrive.json` en hilo con timeout de 3s
- [x] 6.2 Implementar consulta de sistema de archivos con `GetVolumeInformationW` (exFAT, FAT32, NTFS) y espacio libre con `shutil.disk_usage`
- [x] 6.3 Proteger o deshabilitar comandos de montaje/desmontaje `udisksctl` en Windows retornando estado no disponible sin fallar
- [x] 6.4 Asegurar tolerancia completa en `notificar_escritorio` si `notify-send` no existe en el sistema
- [x] 6.5 Agregar pruebas de detección de pendrive simulando el entorno de Windows y ctypes en `test_compatibilidad_windows.py`

## 7. Script de Verificación para Correr en Windows

- [x] 7.1 Crear el script `verificar_windows.py` (stdlib pura) que ejecute diagnósticos de entorno, consola, rutas, creación exclusiva, colisión de destinos, nombres reservados, unidades lógicas, fechas y socket exclusivo
- [x] 7.2 Implementar en `verificar_windows.py` la verificación de lectura del manifiesto y servicio multimedia `/api/media` con soporte de `Range`
- [x] 7.3 Asegurar que `verificar_windows.py` emita `verificacion_windows.txt` y conserve los archivos de prueba en `_verificacion_windows` sin realizar ningún borrado de datos (cumpliendo Regla de Oro #1)

## 8. Verificación Integral y Auditoría AST

- [x] 8.1 Ejecutar suite de pruebas completa en Linux (`pytest`) verificando 100% de tests exitosos y tests marcados con `skipUnless` para las ramas exclusivas de cada SO
- [x] 8.2 Ejecutar `python3 seguridad_anti_borrado.py` verificando 0 infracciones en el análisis estático AST sobre todos los archivos del proyecto
