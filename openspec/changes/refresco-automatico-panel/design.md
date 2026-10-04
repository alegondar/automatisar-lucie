# Design: Refresco Automático del Panel y Detección sin Demora

## Context

Actualmente, el panel web (`127.0.0.1:8766`) implementado en `bandeja_descargas.py` es una Single-Page Application (SPA) en HTML/JavaScript nativo servida por `HandlerServidorBandeja`. `VigilanteBandeja` corre en un hilo de fondo escaneando periódicamente `~/Descargas` y registrando cambios en SQLite (`bandeja_archivos`), pero el navegador solo actualizaba los datos en la carga inicial o mediante un clic manual en el botón "Refrescar".

Para mantener la interfaz sincronizada de forma transparente sin sobrecargar el servidor ni interrumpir la interacción del usuario, se diseña un esquema de sondeo liviano por versión (`GET /api/estado-version`), un controlador de ciclo de vida en el cliente con pausas inteligentes, un motor de preservación de estado de UI y un registro estructurado de eventos en el vigilante.

## Goals / Non-Goals

**Goals:**
- Implementar un endpoint `GET /api/estado-version` ultra liviano que calcule un token determinista del estado en memoria y SQLite sin I/O innecesario.
- Polling cada 4 segundos (configurable en `config_bandeja.json`, desactivable con 0) que solo solicita datos completos cuando el token cambia.
- Suspender consultas cuando la pestaña está oculta (`document.hidden`) o cuando hay modales abiertos, reanudando inmediatamente al regresar.
- Preservar al 100% el trabajo del usuario: selecciones de checkboxes, campos de texto de escenas nuevas, dropdowns de personaje/escena, `<details>` abierto/cerrado, pestaña activa y scroll vertical.
- Permitir actualización incremental para no pisar campos con foco o texto sin enviar.
- Mostrar aviso en título `(N)` en segundo plano, toast discreto de llegada de archivos e indicador de desconexión con backoff exponencial.
- Incorporar trazabilidad con timestamps (`[DETECTADO]`, `[ESTABLE]`, `[REGISTRADO]`) y garantizar detección < 10 segundos de archivos finalizados.

**Non-Goals:**
- No se implementarán WebSockets ni SSE (Server-Sent Events) para evitar dependencias externas complejas, problemas de reconexión y puertos adicionales; el sondeo con token es suficiente y altamente robusto.
- No se altera la obligatoriedad de la simulación previa (Reglas de Oro intactas).

## Decisions

### 1. Cálculo del token de versión en `GET /api/estado-version`
- **Decisión:** El vigilante y la base de datos proporcionan una función `obtener_token_version()` que concatena:
  - IDs y hashes de lotes actuales y lotes anteriores.
  - Conteo de archivos sin identificar.
  - Lista de capítulos abiertos, cerrados y descartados con sus estados y balances.
  - ID del capítulo en foco y timestamp de su último aviso.
  - Estado de alerta de capítulo olvidado.
  A partir de esta cadena concatenada se calcula un hash MD5/SHA256 de 16 caracteres.
- **Razón:** El cálculo toma microsegundos en memoria y no requiere recorrer el sistema de archivos si el vigilante ya mantiene el estado actualizado.
- **Alternativas consideradas:** Pollear `/api/lotes` y `/api/capitulos/estado` completos cada 4 segundos. Rechazado por consumo innecesario de CPU y serialización JSON redundante.

### 2. Controlador de sondeo con `setTimeout` encadenado y gestión de visibilidad
- **Decisión:** En lugar de un `setInterval` rígido que puede encolar peticiones ante lentitud de red, se utiliza un bucle encadenado con `setTimeout` y bandera `consultando = false`:
  - Si `document.hidden` es verdadero, no se programa la siguiente consulta hasta el evento `visibilitychange`.
  - Si hay un modal abierto (`#modal-simulacion`, `#modal-descartar-capitulo`, `#modal-terminar-capitulo`), se omite la consulta.
  - Al recibir `visibilitychange` (pestaña vuelve al frente), se cancela la espera y se ejecuta de inmediato.
- **Alternativas consideradas:** `setInterval` fijo. Rechazado porque genera peticiones acumuladas si la red o el servidor tardan en responder.

### 3. Preservación y restauración del estado del DOM
- **Decisión:** Antes de redibujar la vista con `cargarDatos()`:
  - Se captura un snapshot del estado:
    ```javascript
    const snapshot = {
      scroll: window.scrollY,
      pestana: pestanaActual,
      detailsAnteriores: document.getElementById('details-anteriores')?.open,
      checkboxes: {}, // data-id -> checked
      inputsNuevaEscena: {}, // loteId -> value
      selectsPersonaje: {}, // loteId -> value
      selectsEscena: {}, // loteId -> value
      focoActivo: document.activeElement ? { id: document.activeElement.id, start: document.activeElement.selectionStart } : null
    };
    ```
  - Tras redibujar el HTML, se recorre el snapshot y se reasignan los valores correspondientes.
  - Si un lote posee un campo con foco o texto modificado que no ha sido enviado, se actualizan únicamente los lotes adyacentes o se añade el nuevo lote sin reconstruir el contenedor del lote activo (actualización incremental).
- **Razón:** Evita frustración del usuario si estaba configurando un lote y un refresco involuntario borraba su selección.

### 4. Resiliencia de red y backoff exponencial
- **Decisión:** Si el fetch a `/api/estado-version` falla (servidor caído o timeout):
  - Se muestra una barra superior o aviso `"Sin conexión con la bandeja"`.
  - El intervalo de sondeo se incrementa progresivamente: `4s -> 8s -> 16s -> 30s` (máximo).
  - Al tener éxito la siguiente conexión, se remueve el aviso, se restablece el intervalo a 4s y se ejecuta `cargarDatos()`.

### 5. Trazabilidad del ciclo de vida y optimización de estabilidad
- **Decisión:** En `VigilanteBandeja`:
  - Se agrega un logger estructurado con prefijos `[DETECTADO]`, `[ESTABLE]` y `[REGISTRADO]`, imprimiendo nombre, tamaño y marcas temporales.
  - Cierre explícito de conexiones SQLite en `GestorBaseDatosBandeja` con `try...finally: con.close()` para evitar acumulación de file descriptors.
  - La ventana de estabilidad de 5 segundos combinada con el intervalo de sondeo de 5 segundos asegura que en a lo sumo 10 segundos el archivo nuevo esté clasificado y listo para mostrar.

## Risks / Trade-offs

- **[Riesgo: Parpadeo de interfaz durante el redibujado]** &rarr; *Mitigación:* Se preserva el scroll antes del render y se restaura inmediatamente en el mismo ciclo sincrónico (`requestAnimationFrame` / post-DOM update).
- **[Riesgo: Desconexión prolongada que agote recursos en el navegador]** &rarr; *Mitigación:* Backoff exponencial con tope de 30 segundos y una sola petición concurrente a la vez.
