# Design

## Context

El flujo de producción de contenidos para el proyecto Lucie genera continuamente archivos multimedia que se descargan en `~/Descargas`. Estos archivos deben ser detectados, agrupados y clasificados hacia la estructura espejo del proyecto (`~/Descargas/_lucie/<personaje>/videos sin editar/<escena>/`), o hacia carpetas de escenas ya existentes en `~/Descargas`, garantizando que **no se toque el pendrive físico** y se respeten las 7 Reglas de Oro del proyecto (prohibición absoluta de borrado y pisado destructivo, simulación previa obligatoria, verificación de colisiones, registro auditable y reversibilidad).

El presente ajuste técnico complementa la arquitectura inicial con mejoras del panel web: selección granular de archivos por lote con estado reactivo, visualización y reversión del historial desde la bitácora `.jsonl`, y validación contextual anticipada al crear nuevas escenas.

## Goals / Non-Goals

**Goals:**
- Implementar un servicio local en Python estándar (`bandeja_descargas.py`) con sondeo periódico no invasivo y servidor web en `127.0.0.1` (puerto configurable, default `8766`).
- Aplicar una lista blanca estricta para procesar únicamente extensiones multimedia permitidas (`.mp4`, `.mov`, `.webm`, `.jpg`, `.jpeg`, `.png`, `.webp`) y patrones configurados en `config_bandeja.json`.
- Permitir la selección granular de archivos dentro de cada lote con casillas de verificación individuales, tooltips de metadatos, botones "Seleccionar todos" y "Ninguno", y botón de acción dinámico "Mover seleccionados (N)" deshabilitado cuando N = 0.
- Mantener los archivos no seleccionados en la bandeja como lote pendiente, preservando su agrupación temporal sin pérdida de contexto.
- Implementar el endpoint `GET /api/historial` para leer y presentar los últimos 50 movimientos registrados en la bitácora `.jsonl`.
- Habilitar botones de acción en el panel web para "Deshacer" movimientos individuales y "Deshacer último lote", enviando el token anti-CSRF al endpoint `/api/deshacer`.
- Mostrar el mensaje de negativa devuelto por el servidor si la ruta original ya se encuentra ocupada (cumplimiento estricto de las Reglas de Oro #1 y #4).
- Incorporar validación en tiempo real debajo del campo de "Crear nueva escena" informando el motivo exacto de invalidez antes de invocar la simulación.
- Mantener 0 violaciones en el analizador estático AST anti-borrado.

**Non-Goals:**
- No acceder, montar, copiar, mover ni alterar nada en el pendrive físico (`/run/media/...`).
- No utilizar primitivas de borrado (`os.remove`, `os.unlink`, `shutil.rmtree`, `send2trash`, etc.) ni de pisado ciego (`shutil.move`, `os.replace`).
- No procesar ni leer archivos o carpetas que no pertenezcan a la lista blanca.
- No depender de frameworks web externos (Flask, FastAPI) ni dependencias externas de Node.js/npm.

## Decisions

### 1. Módulo Unificado `bandeja_descargas.py` y Componentes
- **Decisión**: Estructurar la lógica en componentes desacoplados dentro de `bandeja_descargas.py`:
  - `ConfiguracionBandeja`: Carga y validación de `config_bandeja.json`.
  - `FiltroListaBlanca`: Validación estricta de nombres y extensiones. Lo no coincidente no se abre ni se procesa.
  - `ValidadorEscenas`: Validación exhaustiva de nombres de escena (longitud, caracteres especiales, nombres reservados) y resolución canónica con `os.path.realpath`.
  - `DetectorDescargasActivas`: Seguimiento de tamaño y tiempo para descartar `.crdownload`, `.part`, `.tmp` y archivos con mutaciones en los últimos 5 segundos.
  - `AgrupadorLotes`: Agrupa archivos estables por cercanía de `mtime` dentro de la ventana configurada.
  - `GestorBaseDatosBandeja`: Gestión de la tabla `bandeja_archivos` en SQLite para registrar archivos, recordar decisiones de archivos sin patrón y resolver IDs para miniaturas.
  - `GestorMovimientosBandeja`: Confinamiento de rutas con `os.path.realpath`, creación de directorios, resolución de colisiones numéricas en destino inicial, ejecución atómica con `os.rename`, registro en bitácora `.jsonl` y reversión estricta (rechazando si el origen está ocupado).
  - `HandlerServidorBandeja` y servidor `ThreadingHTTPServer`: Generación de token anti-CSRF al iniciar, validación de cabeceras en endpoints POST, endpoints REST y servicio de la SPA embebida.
- **Razón**: Mantiene el código autocontenido, fácil de probar con `unittest` en `/tmp` y auditable por el analizador AST.

### 2. Selección Granular de Archivos y Retención de Pendientes
- **Decisión**:
  - En la interfaz web, cada tarjeta de archivo en la cuadrícula del lote incluye un checkbox `<input type="checkbox" class="chk-archivo" data-id="${a.id_db}" checked>` posicionado de forma visible.
  - La tarjeta incorpora atributos de tooltip accesibles (`title="Archivo: ${a.nombre}&#10;Fecha: ${a.fecha_legible}&#10;Tamaño: ${formatearBytes(a.tamanio)}"`) que el navegador renderiza al pasar el cursor.
  - Se agregan botones "Seleccionar todos" y "Ninguno" en la cabecera de controles de cada lote.
  - Al cambiar cualquier casilla, la función `actualizarSeleccionLote(loteId)` recalcula la cantidad $N$ de archivos seleccionados. Si $N = 0$, el botón "Mover seleccionados (0)" se deshabilita (`disabled = true`) y adquiere opacidad reducida. Si $N > 0$, el botón se habilita y muestra "Mover seleccionados (N)".
  - Al pulsar el botón, `/api/simular-mover` recibe únicamente los objetos de los archivos con casilla marcada.
  - En el backend, tras ejecutarse el movimiento del subconjunto, la base SQLite actualiza los archivos movidos a estado `'movido'`. Al re-escanear, el `AgrupadorLotes` agrupa los archivos restantes que continúan en estado `'detectado'` en `~/Descargas`, presentándolos como lote pendiente sin perder su cohesión temporal.

### 3. Pestaña de Historial y Endpoints de Reversión
- **Decisión**:
  - Se añade el endpoint `GET /api/historial` en `HandlerServidorBandeja`.
  - Este endpoint lee el archivo `bitacora_bandeja.jsonl` en orden cronológico inverso (últimas 50 líneas válidas).
  - Analiza las entradas:
    - Entradas de tipo movimiento (`"evento": "mover_lote"`, `"movimientos": [...]`).
    - Entradas de tipo reversión (`"evento": "deshacer"`, `"id_operacion_revertida": "..."`).
  - Cada movimiento individual se entrega con: `fecha`, `id_operacion`, `archivo` (nombre base), `origen` (`origen_anterior`), `destino` (`destino_nuevo`), y `estado` (`"deshecho"` si su `id_operacion` fue revertido posteriormente, o `"movido"` en caso contrario).
  - En la SPA se agrega la pestaña "Historial" en la barra de navegación superior.
  - La vista renderiza una tabla con filtros y botones "Deshacer" para cada operación no revertida, más un botón superior "Deshacer último lote" que invoca la reversión de la última operación en estado `"movido"`.
  - Toda llamada a `/api/deshacer` se realiza mediante petición POST enviando `{ "id_operacion": id }` junto con el encabezado `X-CSRF-Token: CSRF_TOKEN`.
  - Si la reversión falla con HTTP 409 (Conflict) porque la ruta de origen original se encuentra ocupada, la función cliente captura el mensaje del servidor y lo presenta en un cartel de advertencia sin alterar el sistema de archivos.

### 4. Validación Anticipada en Creación de Escenas
- **Decisión**:
  - En el panel web, si el selector de escena está en `__nueva__`, se valida el valor del campo `txt-nueva-escena-${loteId}` en el evento `input` y de forma previa al clic en mover.
  - Si el campo está vacío, se muestra el mensaje de error: `"Ingresá un nombre para la nueva escena."`.
  - Si contiene caracteres inválidos (`/`, `\`, `..`, `< > : " | ? *`, terminación en punto/espacio o nombres reservados de Windows como `CON`, `PRN`, `AUX`, `NUL`), se muestra el motivo exacto: `"El nombre contiene caracteres prohibidos o reservados (/ \\ < > : \" | ? * o termina en punto/espacio)."`.
  - El mensaje se renderiza en un contenedor `<div class="error-escena-inline">` directamente debajo del input, con texto en color de peligro (`--danger`).
  - Si hay un error de validación, la función cancela la ejecución antes de llamar a `/api/simular-mover`, evitando abrir el modal de simulación con datos erróneos.

### 5. Banner de Aviso Fijo Superior con Deshacer Inmediato
- **Decisión**:
  - En la respuesta de `/api/mover-lote` y en la ejecución de movimientos, incluir explícitamente:
    `"personaje"`, `"escena"`, `"total_movidos"`, y `"id_operacion"`.
  - En la SPA, incorporar un componente fijado en la parte superior: `<div id="banner-aviso" class="banner-aviso" style="display:none;">`.
  - Al completar exitosamente `ejecutarMoverLote()`, poblar el banner con el texto:
    `"Se movieron ${res.total_movidos} archivos a ${res.personaje}/${res.escena}"`.
  - El banner incluye un botón interactivo `Deshacer` que llama a `deshacerMovimiento(res.id_operacion)` enviando el token anti-CSRF, y un botón `×` para cerrarlo.
  - El aviso queda visible de forma persistente hasta que:
    1. El usuario lo cierre manualmente pulsando `×`.
    2. Se mueva otro lote, en cuyo caso se actualiza con la nueva información.
    3. Se pulse "Deshacer", en cuyo caso tras la reversión exitosa el banner se oculta y se recargan los lotes y el historial.
  - La bitácora y la pestaña "Historial" siguen conteniendo el registro del movimiento de forma transparente.
  - Si al pulsar "Deshacer" desde el banner el servidor responde HTTP 409 (porque la ruta original está ocupada), la advertencia de error se presenta sin cerrar el banner ni sobrescribir archivos.

### 6. Modal de Simulación Previa: Ensanchamiento, Rutas Relativas y Resaltado de Segmentos
- **Decisión**:
  - Ampliar el modal a `width: 90vw; max-width: 1200px; max-height: 85vh;` para otorgar suficiente visibilidad a las rutas en pantallas modernas.
  - Aplicar `word-break: break-word` y `overflow-wrap: anywhere` en las celdas de rutas (`.ruta-celda`) para evitar que se corten las rutas o fuercen barras de desplazamiento horizontal.
  - Mostrar la ruta de destino relativa al directorio base (`<personaje>/<subcarpeta_tipo>/<escena>/<archivo>`), y preservar la ruta absoluta completa en el atributo `title` (tooltip nativo) y `data-destino` de cada archivo.
  - Resaltar visualmente el segmento de tipo ("imagenes" con badge `.tag-imagen` o "videos sin editar" con badge `.tag-video`) en el destino relativo para diferenciarlos a simple vista.
  - Implementar la función `generar_html_simulacion` en el servidor devuelta en `/api/simular-mover` y consumida directamente por la SPA con fallback reactivo en JavaScript.

## Risks / Trade-offs

- **[Riesgo: Selección parcial genera dispersión de archivos de una misma toma]** → **Mitigación**: Los archivos no seleccionados permanecen en el lote pendiente con su marca temporal original, permitiendo que el usuario los mueva más tarde a la misma escena o a otra diferente según su criterio sin perder la agrupación.
- **[Riesgo: Intento de deshacer una operación sobreescribe archivos creados posteriormente]** → **Mitigación**: `GestorMovimientosBandeja.deshacer_operacion` comprueba preventivamente si la ruta de origen original está ocupada. Si existe cualquier archivo en esa ruta, la operación aborta de inmediato con `ErrorDeshacer` y responde HTTP 409 con el mensaje descriptivo sin modificar ningún archivo.
- **[Riesgo: Vulnerabilidad CSRF en el endpoint de deshacer]** → **Mitigación**: `/api/deshacer` requiere validación estricta de token anti-CSRF, encabezado `Host` local y `Content-Type: application/json`, respondiendo `403 Forbidden` ante cualquier inconsistencia.
