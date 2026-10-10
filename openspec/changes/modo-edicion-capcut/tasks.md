# Tasks

## 1. Configuración, Plataforma y Guardia Hermética

- [x] 1.1 Extender `bandeja/config.py` con parámetros `carpeta_exportacion_capcut`, `al_exportar` y `extensiones_temporales_capcut`, y verificar su carga con tests unitarios.
- [x] 1.2 Implementar en `bandeja/plataforma.py` la resolución de la ruta de CapCut (`%LOCALAPPDATA%\CapCut\Videos`) y la función `verificar_archivo_exclusivo()`, verificando su comportamiento en Windows y Linux.
- [x] 1.3 Ampliar `guardia_hermetica.py` para incluir la carpeta real de CapCut en `_RUTAS_PROHIBIDAS` y verificar que la suite rechace accesos no simulados en tests.
- [x] 1.4 Extender `verificar_windows.py` con diagnósticos de solo lectura para la carpeta de CapCut (existencia, conteo de exports preexistentes y permisos de lectura).

## 2. Vigilante de CapCut y Fotografía Inicial

- [x] 2.1 Crear `bandeja/capcut.py` con la clase `VigilanteCapCut` e implementar la fotografía inicial en arranque que registra e ignora de por vida los archivos preexistentes.
- [x] 2.2 Implementar en `VigilanteCapCut` el escaneo recursivo hasta profundidad 3, filtrado de extensiones temporales, ventana de estabilidad de tamaño y apertura exclusiva.
- [x] 2.3 Implementar pruebas unitarias en `test_capcut.py` con carpetas temporales simuladas, validando el descarte de archivos preexistentes, detección de nuevos sueltos y en subcarpetas, y espera ante archivos bloqueados.

## 3. Gestor de Sesiones de Edición y Transiciones en Pendrive

- [x] 3.1 Añadir en `bandeja/db.py` las tablas `sesiones_edicion` y `exports_pendientes` en modo WAL, y crear `bandeja/edicion.py` con el gestor de sesiones.
- [x] 3.2 Implementar la creación de sesiones múltiples/individuales con cálculo de nombre por defecto (`<capítulo>videocompleto` o `<clip>videocompleto`), y el listado de las tres secciones ("Para editar", "En edición", "Editados y completos").
- [x] 3.3 Implementar la acción "Terminé de editar" con traslado atómico vía `os.rename` a `videos ya editados/` en el pendrive, comprobación de destino sin pisado y registro append-only en `.lucie_pendrive.json` y bitácora.
- [x] 3.4 Implementar la acción "Deshacer" para crudos editados (devolviéndolos a `videos sin editar` si está libre) y la cancelación de sesiones sin alterar archivos físicos.
- [x] 3.5 Crear pruebas unitarias en `test_edicion.py` para sesiones, cálculo de nombres, traslado seguro, conflictos de hash y deshacer en pendrive simulado.

## 4. Asociación de Exports, Copia a Videos Completos y Cola Pendiente

- [x] 4.1 Implementar la lógica de vinculación determinista: asociación automática si hay exactamente 1 sesión abierta, o derivación a "Exports sin asignar" si hay 0 o >1 sesiones.
- [x] 4.2 Implementar la copia segura entre volúmenes a `videos completos/` (escritura en bloques a `.part`, SHA-256 en la misma pasada, fsync, rename atómico y relectura para verificar hash).
- [x] 4.3 Implementar la cola de "Exports pendientes de copiar" para procesar transferencias retenidas cuando se conecte o vincule el pendrive.
- [x] 4.4 Implementar la acción "Deshacer" para copias en `videos completos/`, trasladando el archivo a `LucieSinReglas/_revertidos/<nombre>` con `os.rename` sin borrarlo.
- [x] 4.5 Crear pruebas unitarias que validen la copia segura, manejo de nombres con caracteres especiales (paréntesis, acentos, espacios), descarte de colisiones y desconexión/reconexión del pendrive.

## 5. Endpoints REST, Streaming Seguro y Frontend Web

- [x] 5.1 Implementar en `bandeja/servidor.py` los endpoints POST `/api/edicion/*` y `/api/capcut/*` con validación estricta de Host, CSRF y Content-Type JSON.
- [x] 5.2 Ampliar `/api/media` para permitir streaming con Range requests de los clips en `LucieSinReglas` del pendrive vinculado bajo confinamiento estricto por `esta_confinado_en_raiz`.
- [x] 5.3 Crear la pestaña "Edición" en `bandeja/web/` con las secciones "Para editar", "En edición", "Editados y completos", "Exports sin asignar" y avisos interactivos de confirmación/deshacer.
- [x] 5.4 Crear pruebas de integración en `test_bandeja_descargas.py` para los nuevos endpoints, streaming de medios y panel web.

## 6. Verificación Integral y Auditoría

- [x] 6.1 Ejecutar auditoría AST anti-borrado (`python3 seguridad_anti_borrado.py .`) y verificar 0 infracciones en todos los módulos nuevos y modificados.
- [x] 6.2 Ejecutar auditoría del repositorio (`python3 auditar_repo.py --historial`) y verificar 0 infracciones de rutas personales o archivos prohibidos.
- [x] 6.3 Ejecutar la suite completa de pruebas unitarias (`python3 -m unittest discover -s . -p "test_*.py"`) y la suite hermética (`env HOME=/tmp/homefalso python3 -m unittest discover -s . -p "test_*.py"`).
