# Design: vista-previa-media

## Context

El panel web de la bandeja de descargas sirve como interfaz para la revisión y organización rápida de material entrante. Hasta ahora, las tarjetas mostraban solo metadatos y un recuadro de sustitución estático ("Media").

Para la motivación detallada, véase [proposal.md](file:///home/<usuario>/Documentos/code-proyect/automatisar-lucie/openspec/changes/vista-previa-media/proposal.md).
Para los requerimientos funcionales, véase [specs/vista-previa-media/spec.md](file:///home/<usuario>/Documentos/code-proyect/automatisar-lucie/openspec/changes/vista-previa-media/specs/vista-previa-media/spec.md).

## Goals / Non-Goals

**Goals:**
- Servir contenido multimedia mediante `GET /api/media?id=<id>` y `HEAD /api/media?id=<id>` usando identificadores opacos resueltos internamente.
- Soportar peticiones `Range` parciales (`206 Partial Content`) para permitir adelantado y retroceso fluido en reproducción de video.
- Confinar el acceso a las raíces permitidas (`~/Descargas` y `~/Descargas/_lucie`), resolviendo enlaces simbólicos con `os.path.realpath` y rechazando cualquier escape (403/404).
- Validar la cabecera `Host` y emitir cabeceras de seguridad (`X-Content-Type-Options: nosniff`, `Content-Disposition: inline`, `ETag`, `Cache-Control: private`).
- Transmitir en bloques de 64 KiB e ignorar sin trazas las desconexiones prematuras (`BrokenPipeError`, `ConnectionResetError`).
- Configurar `ThreadingHTTPServer` con `daemon_threads = True` para evitar bloqueos del servidor durante el streaming o apagado.
- Cargar perezosamente el primer fotograma en las tarjetas de video (`#t=0.1`) con concurrencia controlada (máximo 3 concurrentes) y fallback a placeholder.
- Implementar un visor modal (lightbox) accesible al hacer clic en miniaturas, con controles de teclado (flechas y Esc), checkbox sincronizado, pausa y liberación de memoria al cerrar, y detección de formatos no soportados con botón "Copiar ruta".
- Pausar el sondeo periódico de refresco mientras el visor esté abierto registrándolo en `hayModalAbierto()`.

**Non-Goals:**
- No transcodificar videos ni re-comprimir fotos al vuelo en el servidor.
- No modificar el sistema de archivos ni alterar archivos en disco.
- No admitir rutas de archivo directas ni nombres de archivo arbitrarios suministrados por el cliente.

## Decisions

### 1. Resolución de Identificadores Opacos y Confinamiento de Raíces
En `bandeja/vigilante.py`, durante `escanear()`, cada archivo detectado recibe un identificador opaco determinista:
```python
id_media = hashlib.sha256(f"media:{ruta_completa}".encode("utf-8")).hexdigest()[:32]
item_info["id_media"] = id_media
```
El vigilante almacena el mapa `_mapa_media[id_media] = ruta_completa` para todos los elementos vigentes en lotes principales, anteriores y sin identificar.
En `bandeja/servidor.py`, al recibir `/api/media?id=<id>`:
1. Valida la cabecera `Host`.
2. Si `id` no existe en `_mapa_media`, responde `404 Not Found`. Nunca se aceptan parámetros de ruta como `/api/media?ruta=...`.
3. Resuelve `real_ruta = os.path.realpath(ruta)` y verifica que esté estrictamente contenida en `raices_permitidas = [os.path.realpath(config.ruta_descargas), os.path.realpath(config.ruta_destino_base)]`. Si un enlace simbólico apunta fuera o la ruta no existe, responde `403 Forbidden` o `404 Not Found`.

### 2. Streaming por Rangos HTTP (RFC 7233)
El endpoint `GET` y `HEAD` procesa la cabecera opcional `Range: bytes=start-end`, `bytes=start-` o `bytes=-suffix`:
- Sin `Range`: Código 200, `Content-Length: <total>`, `Accept-Ranges: bytes`.
- Con `Range` válido: Código 206, `Content-Range: bytes <start>-<end>/<total>`, `Content-Length: <longitud>`, `Accept-Ranges: bytes`.
- Con `Range` insatisfactorio: Código 416, `Content-Range: bytes */<total>`.
- Cabeceras comunes: `Content-Type` detectado por `mimetypes` con fallback seguro, `ETag: f'"{total}-{int(mtime)}"'`, `Cache-Control: private`, `X-Content-Type-Options: nosniff`, `Content-Disposition: inline`.
- Transmisión en bloques de 64 KiB con captura silenciosa de `(BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.error)`.
- En peticiones `HEAD`: solo se envían las cabeceras correspondientes y `end_headers()`, sin emitir cuerpo.

### 3. Concurrencia de Servidor Multihilo
En `crear_servidor`:
```python
servidor = ThreadingHTTPServer((config.host_servidor, config.puerto_servidor), CustomHandler)
servidor.daemon_threads = True
```
Garantiza que peticiones prolongadas de video o streaming no bloqueen peticiones concurrentes a `/api/estado-version` o la navegación en el panel.

### 4. Carga Perezosa de Fotogramas de Video en Tarjetas
Para los videos en las tarjetas, se genera el elemento:
```html
<video class="video-thumb-lazy" data-src="/api/media?id=${a.id_media}#t=0.1" muted playsinline preload="none"></video>
```
Un `IntersectionObserver` con margen de 200px encola los videos visibles y los procesa con un despachador que limita a un máximo de 3 cargas concurrentes. Al completar o fallar cada carga (`loadeddata`, `seeked`, `error`), se libera el cupo para el siguiente video en la cola. Si falla la carga del fotograma, se muestra el recuadro SVG de sustitución actual.

### 5. Visor Modal y Sincronización
El visor lightbox se monta sobre `#modal-visor-media`:
- Registrado en `hayModalAbierto()` para pausar automáticamente el temporizador de refresco periódico.
- Al abrirse, detecta el tipo de medio: si es imagen muestra `<img>`, si es video muestra `<video controls playsinline>` sin autoplay.
- Si el reproductor del navegador dispara error de formato/códec, oculta el elemento multimedia y muestra el contenedor `#visor-error-formato` con el mensaje "El navegador no puede reproducir este formato" y el botón "Copiar ruta" que escribe la ruta absoluta en el portapapapeles.
- El checkbox del visor sincroniza inmediatamente con el checkbox del archivo en la tarjeta llamando a `actualizarSeleccionLote(loteId)`.
- Al cerrarse (botón o tecla `Escape`), ejecuta `video.pause()`, `video.removeAttribute('src')` y `video.load()` para evitar fugas de memoria.
