# Spec Delta: vista-previa-media

## Purpose

Define los requerimientos para el servicio seguro de archivos multimedia mediante HTTP Range, el streaming no bloqueante con identificadores opacos, la visualización diferida de primer fotograma en tarjetas y el visor modal de pantalla completa con controles de lote y selección sincronizada.

## ADDED Requirements

### Requirement: Endpoint seguro de servicio multimedia GET y HEAD
El servidor DEBE (SHALL) proveer un endpoint `GET /api/media?id=<id>` y `HEAD /api/media?id=<id>` donde `id` es un identificador opaco resuelto por el servidor contra archivos conocidos en lotes, anteriores o sin identificar. NUNCA DEBE aceptar rutas directas ni nombres de archivo desde el cliente.

#### Scenario: Petición con ID válido
- **WHEN** un cliente solicita `GET /api/media?id=<id>` para un archivo conocido
- **THEN** el servidor responde con el contenido multimedia, código 200 o 206, cabecera `Content-Type` adecuada, `ETag`, `Cache-Control: private`, `X-Content-Type-Options: nosniff` y `Content-Disposition: inline`

#### Scenario: Petición con ID inexistente
- **WHEN** un cliente solicita `GET /api/media?id=desconocido`
- **THEN** el servidor responde 404 Not Found

#### Scenario: Intento de inyección de ruta arbitraria
- **WHEN** un cliente envía parámetros con rutas o nombres como `/etc/passwd` o `../../archivo`
- **THEN** el servidor rechaza la solicitud con 404 Not Found al no coincidir con ningún identificador opaco conocido

### Requirement: Validación de cabecera Host y confinamiento a raíces permitidas
El servidor DEBE (SHALL) validar la cabecera `Host` y verificar que la ruta resuelta mediante `os.path.realpath` se encuentre confinada dentro de las raíces permitidas (`~/Descargas` y `~/Descargas/_lucie`), rechazando enlaces simbólicos que apunten fuera de ellas.

#### Scenario: Cabecera Host no autorizada
- **WHEN** una petición a `/api/media` incluye un `Host` no local
- **THEN** el servidor responde 403 Forbidden

#### Scenario: Enlace simbólico que escapa de las raíces
- **WHEN** un archivo resuelto es un enlace simbólico hacia fuera de `~/Descargas` o `~/Descargas/_lucie`
- **THEN** el servidor responde 403 Forbidden

### Requirement: Soporte para peticiones Range HTTP (RFC 7233)
El endpoint DEBE (SHALL) soportar peticiones parciales mediante la cabecera `Range: bytes=start-end`, respondiendo con código 206 Partial Content, cabeceras `Content-Range`, `Accept-Ranges: bytes` y `Content-Length`. Si no se especifica `Range`, DEBE responder 200 OK completo. Si el rango es insatisfactorio, DEBE responder 416 Range Not Satisfiable.

#### Scenario: Petición de rango válido de bytes
- **WHEN** se solicita `GET /api/media?id=<id>` con `Range: bytes=0-99`
- **THEN** el servidor devuelve 206 Partial Content con exactamente 100 bytes y `Content-Range: bytes 0-99/<total>`

#### Scenario: Petición sin cabecera Range
- **WHEN** se solicita `GET /api/media?id=<id>` sin cabecera `Range`
- **THEN** el servidor devuelve 200 OK con el archivo completo y `Accept-Ranges: bytes`

#### Scenario: Petición de método HEAD
- **WHEN** se realiza una petición `HEAD /api/media?id=<id>`
- **THEN** el servidor devuelve las cabeceras completas de respuesta sin cuerpo

### Requirement: Transmisión en bloques y tolerancia a desconexión
El servidor DEBE (SHALL) transmitir el contenido en bloques (64 KiB) sin leer el archivo completo en memoria, e ignorar silenciosamente excepciones de desconexión del cliente (`BrokenPipeError`, `ConnectionResetError`) sin emitir trazas de error.

#### Scenario: Cliente corta la conexión anticipadamente
- **WHEN** el cliente cierra el socket antes de completar la transferencia
- **THEN** el servidor finaliza la rutina sin generar excepciones en logs ni stderr

### Requirement: Servidor multihilo no bloqueante
El servidor DEBE (SHALL) configurarse mediante `ThreadingHTTPServer` con `daemon_threads = True`, evitando que la reproducción o descarga de video bloquee el sondeo del panel.

#### Scenario: Streaming prolongado de video
- **WHEN** se transmite un video a un cliente
- **THEN** otras peticiones concurrentes como `/api/estado-version` se atienden de inmediato sin retraso

### Requirement: Primer fotograma y carga perezosa en tarjetas
Las tarjetas de video DEBEN (SHALL) mostrar el primer fotograma mediante `<video muted playsinline preload="metadata">` con `#t=0.1`, cargado de manera diferida con `IntersectionObserver` y límite de concurrencia de hasta 3 cargas simultáneas, preservando el placeholder en caso de fallo. Las fotos DEBEN mostrar su miniatura.

#### Scenario: Carga perezosa de video en tarjeta
- **WHEN** una tarjeta de video entra en el margen de visibilidad del viewport
- **THEN** se encola y carga su fotograma inicial de forma concurrente controlada

#### Scenario: Fallo de carga de fotograma
- **WHEN** un video falla al cargar su fotograma
- **THEN** se muestra el recuadro de sustitución actual con el texto "Media"

### Requirement: Visor modal interactivo (Lightbox)
La interfaz DEBE (SHALL) proveer un visor modal a pantalla casi completa al pulsar sobre la miniatura de cualquier archivo (en lotes principales, anteriores y sin identificar), mostrando nombre, tamaño, fecha de llegada, lote al que pertenece, controles de navegación por lote (flechas y teclado), tecla Esc para cerrar, y un checkbox "Seleccionado" sincronizado con la tarjeta.

#### Scenario: Apertura de visor desde miniatura
- **WHEN** el usuario hace clic sobre la miniatura de un archivo
- **THEN** se abre el visor con los metadatos, controles y el checkbox reflejando el estado de la tarjeta

#### Scenario: Navegación de archivos en el lote
- **WHEN** el usuario pulsa flecha derecha o izquierda en el visor
- **THEN** el visor transiciona exclusivamente entre los archivos del lote en curso

#### Scenario: Sincronización de checkbox dentro del visor
- **WHEN** el usuario marca o desmarca el checkbox dentro del visor
- **THEN** la tarjeta correspondiente en la cuadrícula actualiza su checkbox y el contador de seleccionados del lote

#### Scenario: Cierre del visor y liberación de recursos
- **WHEN** el usuario cierra el visor mediante botón o tecla Escape
- **THEN** el visor se oculta, el video se pausa y se libera su atributo `src` ejecutando `load()`

#### Scenario: Formato no reproducible en el navegador
- **WHEN** el reproductor no soporta el códec o formato del video
- **THEN** se muestra "El navegador no puede reproducir este formato" y un botón "Copiar ruta" para copiarla al portapapeles

#### Scenario: Pausa del refresco automático con visor abierto
- **WHEN** el visor modal está abierto
- **THEN** la función `hayModalAbierto()` retorna verdadero y el sondeo de refresco automático se suspende
