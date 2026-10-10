# Design: Modo Edición con CapCut (Tramo 3)

## Context

El sistema gestiona la ingesta y envío estructurado de clips hacia un pendrive en `LucieSinReglas/videos sin editar/<personaje>/<capítulo>/`. En Windows, el usuario edita estos clips con CapCut, el cual exporta a `%LOCALAPPDATA%\CapCut\Videos` con nombres no correlativos (ej. `0818(15)`). El proyecto exige el cumplimiento irrestricto de las 7 Reglas de Oro: prohibición absoluta de borrado o truncado destructivo, simulación/aprobación granular, verificación de destino sin pisado, validación de hash post-copia, registro reversible y hermeticidad de pruebas unitarias.

Ver motivación y alcance en `proposal.md` y especificaciones formales en `specs/modo-edicion-capcut/spec.md`.

## Goals / Non-Goals

**Goals:**
- Monitoreo pasivo y 100% no destructivo de la carpeta de CapCut (nunca alterar, mover, renombrar ni borrar nada en dicha carpeta).
- Desacoplar archivos históricos preexistentes (~45 exports) mediante una fotografía inicial en arranque para evitar falsos positivos.
- Gestión de sesiones de edición con múltiples clips o capítulos, con nombres calculados inteligentes.
- Traslado atómico vía `os.rename` de crudos a `videos ya editados/` en el pendrive con capacidad de Deshacer.
- Copia segura entre volúmenes a `videos completos/` con verificación de hash en vuelo y post-copia.
- Integración en la pestaña "Edición" del panel web con contadores y previsualización segura por streaming.
- Ampliación de `guardia_hermetica.py` para aislar estrictamente la carpeta de CapCut en entornos de prueba.

**Non-Goals:**
- No manipular proyectos internos, bases de datos SQLite ni archivos de configuración propios de CapCut.
- No alterar ni renombrar archivos dentro de la carpeta de exportación de CapCut.
- No realizar transcodificación ni procesamiento de video en el backend (se confía en el renderizado final de CapCut).

## Decisions

### 1. Copia automática sin confirmación a "videos completos" (Excepción Regla de Oro #3)
- **Decisión**: El archivo exportado por CapCut se copia automáticamente a `LucieSinReglas/videos completos/<personaje>/<capítulo>/<nombre>.mp4` SIN diálogo de confirmación previa si y solo si se satisfacen todas las siguientes condiciones:
  1. Existe exactamente una sesión en estado "en_edicion" abierta.
  2. El destino en el pendrive no existe previamente (sin colisión de nombres).
  3. El pendrive está vinculado, montado y cuenta con espacio suficiente.
  4. El hash SHA-256 de la copia coincide exactamente con el origen verificado en relectura.
  5. Se emite inmediatamente una notificación interactiva con botón "Deshacer".
- **Justificación**: El usuario acaba de exportar desde CapCut con la intención explícita de obtener su video final. Requerir una confirmación redundante interrumpe el flujo creativo. La seguridad queda resguardada porque la copia es aditiva, verificada por hash y reversible.
- **Alternativa descartada**: Exigir siempre confirmación manual en el panel web. Descartado por fricción innecesaria durante sesiones activas.

### 2. Vigilante pasivo (`VigilanteCapCut`) con Snapshot inicial y exclusividad
- **Decisión**: Implementar un hilo monitor en segundo plano configurable (`"carpeta_exportacion_capcut": "auto"` que resuelve a `%LOCALAPPDATA%\CapCut\Videos` en Windows o directorio simulado en Linux).
  - Al iniciar, realiza un recorrido hasta profundidad 3 y registra un snapshot en memoria `(ruta, tamaño, mtime)` de todo lo preexistente, ignorándolo indefinidamente.
  - Al detectar un nuevo archivo `.mp4` o `.mov`, espera una ventana de estabilidad (3 sondeos consecutivos con tamaño inmutable) y valida apertura en modo exclusivo (verificando que no esté bloqueado por CapCut durante la escritura).
  - Ignora extensiones temporales parametrizadas (`.tmp`, `.part`, `.crdownload`, `.downloading`).
- **Justificación**: CapCut no expone una API ni webhook de finalización. El sondeo con verificación de bloqueo garantiza capturar el archivo solo cuando la exportación haya concluido íntegramente.
- **Alternativa descartada**: `watchdog` o `ReadDirectoryChangesW`. Descartado por depender de librerías externas o ser propenso a ráfagas de eventos mientras el renderizador aún está escribiendo bloques.

### 3. Modelo de Sesiones de Edición y Nombrado Automático
- **Decisión**: Las sesiones se almacenan en la base de datos local SQLite y se reflejan en el archivo `.lucie_pendrive.json` mediante eventos append-only:
  - `en_edicion`: cuando se agrupan clips crudos.
  - `editado`: cuando los crudos se mueven a `videos ya editados/`.
  - `completo`: cuando el export final se copia a `videos completos/`.
  - Regla de nombres: si la sesión contiene clips de un único capítulo (ej. `capitulo_01`), el nombre por defecto es `<capítulo>videocompleto.mp4` (ej. `capitulo_01videocompleto.mp4` o `lucieoloraculovideocompleto.mp4`). Si es un solo clip suelto, `<clip>videocompleto.mp4`. El usuario puede editar este nombre en la interfaz antes o durante la edición.
- **Justificación**: Desacopla los nombres aleatorios generados por CapCut (`0818(15)`) asignando una nomenclatura canónica y clara en el archivo de entrega.

### 4. Protocolo de movimiento local vs copia entre volúmenes
- **Decisión**:
  - Movimiento de crudos (`sin editar` ➔ `ya editados`): ocurre dentro del mismo sistema de archivos del pendrive. Se ejecuta mediante `os.rename` atómico tras verificar `not os.path.exists(destino)`.
  - Copia de exports (`CapCut` ➔ `videos completos`): ocurre entre volúmenes distintos (disco C: a Pendrive). Se implementa el protocolo robusto de envío: copia por bloques de 64 KB a archivo temporal `.part`, cálculo de SHA-256 en la misma pasada, `os.fsync()`, `os.rename` atómico a `.mp4` y relectura para verificación.
  - Mecanismo "Deshacer": En crudos, revierte con `os.rename` si el origen está desocupado. En videos completos, traslada el archivo de `videos completos/` a `LucieSinReglas/_revertidos/<nombre>` con `os.rename`, preservando el principio de nunca borrar.

### 5. Confinamiento de streaming `/api/media` para el pendrive
- **Decisión**: Ampliar la lista blanca de rutas permitidas en `bandeja/servidor.py` para incluir la carpeta `LucieSinReglas` del pendrive actualmente vinculado.
  - Se valida confinamiento canónico mediante `esta_confinado_en_raiz(ruta, pendrive_raiz)` utilizando `os.path.realpath`, `os.path.normcase` y `os.path.commonpath`.
  - El frontend solo envía identificadores seguros o rutas relativas normalizadas; nunca rutas absolutas arbitrarias.

## Risks / Trade-offs

- **[Risk]** CapCut genera extensiones temporales no documentadas que podrían confundir al vigilante.  
  ➔ *Mitigación*: Parámetro configurable `"extensiones_temporales_capcut": [".tmp", ".part", ".crdownload", ".tmp.mp4"]` en `config_bandeja.json` y ventana obligatoria de estabilidad de tamaño y apertura exclusiva.
- **[Risk]** El pendrive se extrae abruptamente durante la copia o mientras una exportación está lista.  
  ➔ *Mitigación*: Cola de "Exports pendientes de copiar" en SQLite que persiste el estado. Al reconectar el pendrive, el sistema verifica espacio y retoma la transferencia.
- **[Risk]** Los tests unitarios podrían escanear o contaminar la carpeta real de CapCut en máquinas Windows donde esté instalado.  
  ➔ *Mitigación*: La guardia hermética (`guardia_hermetica.py`) detecta la ruta real de CapCut (o `%LOCALAPPDATA%\CapCut\Videos`) y la incorpora a `_RUTAS_PROHIBIDAS`, forzando que los tests utilicen únicamente directorios temporales `tempfile`.

## Migration / Rollback Plan

- Los cambios son completamente aditivos en el servidor y panel web.
- La base SQLite actualizará su esquema de manera transparente creando las tablas de sesiones y exports pendientes.
- En caso de rollback de código, no hay pérdida de información: los archivos en el pendrive permanecen en sus carpetas físicas y el manifiesto append-only conserva su trazabilidad.
