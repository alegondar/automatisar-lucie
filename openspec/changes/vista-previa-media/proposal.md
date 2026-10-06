# Proposal: vista-previa-media

## Why

Actualmente, las tarjetas de archivos de video en el panel web de la bandeja de descargas muestran únicamente un recuadro de sustitución estático con la palabra "Media", impidiendo que el operador examine los videos o fotografías antes de tomar decisiones de clasificación, asignación de escena o movimiento. Para garantizar una clasificación precisa y ágil, es necesario previsualizar el primer fotograma en las tarjetas y disponer de un visor interactivo (lightbox) que reproduzca videos y amplíe fotos de manera fluida, segura y eficiente en memoria y ancho de banda.

## What Changes

- **Servicio seguro de medios y streaming HTTP Range**:
  - Nuevo endpoint `GET /api/media?id=<id>` y `HEAD /api/media?id=<id>`. El identificador `id` es un identificador opaco generado por el servidor a partir de los archivos conocidos en lotes, anteriores y sin identificar.
  - El servidor rechaza cualquier intento de pasar rutas directas o nombres de archivo arbitrarios desde el cliente.
  - Validación obligatoria de la cabecera `Host` y confinamiento estricto mediante `os.path.realpath` dentro de las raíces permitidas (`~/Descargas` y la sala de espera `~/Descargas/_lucie`), rechazando symlinks que apunten fuera.
  - Soporte completo para peticiones `Range` con código `206 Partial Content`, cabeceras `Content-Range`, `Accept-Ranges: bytes`, `Content-Length`, `ETag`, `Cache-Control: private`, `X-Content-Type-Options: nosniff` y `Content-Disposition: inline`.
  - Transmisión en bloques de 64 KiB sin cargar archivos completos en memoria, e ignorando silenciosamente desconexiones de cliente (`BrokenPipeError`, `ConnectionResetError`).
  - Verificación de servidor multihilo (`ThreadingHTTPServer` con `daemon_threads = True`).

- **Tarjetas interactivas con carga perezosa de fotogramas**:
  - Los videos en las tarjetas muestran su primer fotograma mediante `<video muted playsinline preload="metadata">` con `src` terminado en `#t=0.1`.
  - Carga diferida mediante `IntersectionObserver` con margen y límite de cargas concurrentes (máximo 3 concurrentes) para no saturar el navegador ni la red local. En caso de fallo, se preserva el recuadro de sustitución.
  - Las fotos cargan su miniatura correspondiente con cursor de mano.
  - El clic en la miniatura (diferenciado del clic en el checkbox) abre la vista previa en el visor.

- **Visor modal (Lightbox)**:
  - Modal a pantalla casi completa con foto ajustada (`object-fit: contain`) o video con controles estándar (`controls`), sin reproducción automática (`autoplay`).
  - Muestra nombre, tamaño formateado, fecha de llegada y lote al que pertenece el archivo.
  - Navegación bidireccional mediante botones visuales y flechas del teclado (izquierda/derecha) restringida a los archivos del mismo lote (o lista de sin identificar), y tecla `Escape` para cerrar.
  - Checkbox "Seleccionado" dentro del visor sincronizado bidireccionalmente con el de la tarjeta correspondiente.
  - Al cerrar: pausa del video y liberación inmediata de su `src` (`removeAttribute('src')` y `load()`) para liberar memoria.
  - Detección de error de códec/reproducción: muestra aviso explicativo "El navegador no puede reproducir este formato" y botón para "Copiar ruta".
  - Integración en Lotes Detectados, Anteriores y Sin Identificar.
  - Pausa automática del refresco periódico mientras el visor esté abierto registrándolo en `hayModalAbierto()`.

## Capabilities

### New Capabilities
- `vista-previa-media`: Servicio de streaming por rangos HTTP de fotos y videos mediante IDs opacos confinados a raíces permitidas, previsualización de fotogramas en tarjetas y visor modal con navegación por lote y selección sincronizada.

### Modified Capabilities
<!-- No modified capabilities -->

## Impact

- **Servidor y Vigilante**: `bandeja/servidor.py` implementa `_servir_media` con soporte de `Range`, `HEAD`, multihilo con hilos daemon y control de desconexión. `bandeja/vigilante.py` genera y resuelve IDs opacos `id_media` para todos los archivos detectados en lotes y sin clasificar.
- **Frontend Web**: `bandeja/web/panel.html`, `bandeja/web/panel.js` y `bandeja/web/panel.css` añaden la estructura del modal visor, estilos adaptativos, lazy loader con concurrencia controlada para videos y sincronización de checkboxes.
- **Suite de Pruebas**: `test_bandeja_descargas.py` valida peticiones `Range` (206/200/416), método `HEAD`, IDs inválidos/inexistentes (404), escape de raíces/symlinks (403), validación de Host, manejo silencioso de cortes de conexión y comportamiento del visor en frontend (Node.js).
- **Seguridad**: Reglas de Oro intactas (solo lectura en el endpoint, 0 infracciones en auditoría AST).
