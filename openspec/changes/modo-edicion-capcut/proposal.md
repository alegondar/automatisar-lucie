# Proposal: Modo Edición con CapCut (Tramo 3)

## Why

El flujo de trabajo actual cubre la ingesta de clips hacia la sala de espera y el envío estructurado al pendrive físico en `LucieSinReglas/videos sin editar/<personaje>/<capítulo>/`. Sin embargo, la etapa de posproducción y remasterización en CapCut (en Windows) carece de integración: los videos exportados quedan aislados en `%LOCALAPPDATA%\CapCut\Videos` con nombres genéricos (`0818(15)`), mientras que los crudos permanecen sin marcar en el pendrive y el material final debe moverse manualmente sin control de integridad ni bitácora.

Este cambio implementa el "Tramo 3" del pipeline: un sistema de sesiones de edición, monitoreo no destructivo de exportaciones de CapCut, detección estable y copia segura con verificación SHA-256 hacia `videos completos/`, y transición ordenada de crudos hacia `videos ya editados/`, respetando estrictamente las 7 Reglas de Oro del proyecto.

## What Changes

- **Pestaña "Edición" en el panel web**: Nueva vista interactiva con 3 secciones dinámicas calculadas desde el disco del pendrive y su manifiesto:
  - *Para editar*: clips en `videos sin editar` con selección múltiple (checkbox), vista previa vía streaming `/api/media` y filtrado/búsqueda.
  - *En edición*: sesiones activas con sus clips agrupados, acciones "Terminé de editar" y "Cancelar sesión", y nombre editable para el video final.
  - *Editados y completos*: historial agrupado por capítulo de clips crudos ya editados y videos completos remasterizados, con contadores visuales.
- **Modelo de Sesiones de Edición**: Agrupación lógica de clips para edición. Soporta múltiples sesiones concurrentes. Calcula nombres por defecto inteligentes (`<capítulo>videocompleto` o `<clip>videocompleto`). Cancelar una sesión no mueve archivos.
- **Transición segura "Terminé de editar"**: Traslado atómico vía `os.rename` dentro del mismo volumen pendrive desde `videos sin editar/` hacia `videos ya editados/`, con verificación previa de destino (sin pisado) y registro append-only de eventos (`en_edicion`, `editado`, `completo`) en el manifiesto y bitácora local. Incluye función "Deshacer" estricta y reversible.
- **Vigilante pasivo de exportaciones de CapCut (`VigilanteCapCut`)**:
  - Detección portable de la carpeta de exportación (`%LOCALAPPDATA%\CapCut\Videos` en Windows o configurable en Linux/local).
  - Fotografía inicial en arranque: ignora para siempre los exports históricos preexistentes (~45 archivos existentes).
  - Monitoreo pasivo hasta profundidad 3 (sueltos o en subcarpetas).
  - Ventana de estabilidad rigurosa: comprobación de tamaño inmutable y apertura exclusiva (sin lock del editor).
  - Ignorado de extensiones temporales parametrizadas (`.tmp`, `.part`, `.crdownload`, etc.).
  - Prohibición total de mutación: ningún archivo en la carpeta de CapCut se renombra, mueve ni elimina.
- **Asociación determinista y copia automática a "videos completos"**:
  - Si hay exactamente una sesión en edición abierta: vinculación automática.
  - Si hay cero o múltiples sesiones: retención en bandeja "Exports sin asignar" con asignación manual explícita.
  - Protocolo de copia segura entre volúmenes: escritura en `.part`, hash SHA-256 en la misma pasada, fsync, rename atómico y verificación post-copia.
  - Única excepción documentada a la aprobación previa: copia automática solo si hay sesión única y exacta, destino libre, pendrive vinculado con espacio y hash verificado.
  - Manejo de pendrive desconectado: cola de "Exports pendientes de copiar" que se procesan al detectar conexión.
  - Opción de revertir ("Deshacer") que traslada el archivo de `videos completos/` a `LucieSinReglas/_revertidos/` sin borrarlo.
- **Acciones post-exportación configurables**: Aviso "¿Terminaste de editar estos N clips? [Mover a ya editados]" con modos `preguntar` (por defecto), `automatico` o `manual`.
- **Ampliación de seguridad y hermeticidad**:
  - Confinamiento seguro de `/api/media` extendido a `LucieSinReglas` del pendrive vinculado.
  - Guardia hermética de tests extendida para prohibir accesos a la carpeta real de CapCut.
  - Herramienta `verificar_windows.py` ampliada con diagnóstico de solo lectura sobre el entorno de CapCut.

## Capabilities

### New Capabilities
- `modo-edicion-capcut`: Gestión integral de sesiones de edición, monitoreo no destructivo de CapCut, transiciones seguras en el pendrive físico entre `videos sin editar`, `videos ya editados` y `videos completos`, y panel web de control con bitácora reversible.

### Modified Capabilities
*(Ninguna capacidad preexistente modifica sus requisitos fundamentales).*

## Impact

- **Módulos nuevos y modificados**:
  - `bandeja/capcut.py` (nuevo): Vigilante de CapCut, fotografía inicial, estabilidad y cola de exports.
  - `bandeja/edicion.py` (nuevo): Gestor de sesiones de edición, transiciones en pendrive y sincronización de manifiesto.
  - `bandeja/plataforma.py`: Detección de ruta CapCut en Windows y chequeo de apertura exclusiva de archivos.
  - `bandeja/servidor.py`: Nuevos endpoints REST (`/api/edicion/*`, `/api/capcut/*`) y ampliación de `/api/media`.
  - `bandeja/web/`: Nueva pestaña "Edición" y controles asociados en el frontend nativo.
  - `guardia_hermetica.py`: Inclusión de la carpeta de CapCut en las rutas prohibidas durante tests.
  - `verificar_windows.py`: Verificación de existencia, permisos y conteo de exports en Windows.
- **Dependencias**: Ninguna (100% biblioteca estándar de Python 3).
- **Compatibilidad**: Linux y Windows nativos.
