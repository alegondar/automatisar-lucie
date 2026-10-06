# Tasks: vista-previa-media

## 1. Backend: Identificadores opacos y endpoint de streaming HTTP Range

- [x] 1.1 Implementar en `bandeja/vigilante.py` la generación de `id_media` opaco para cada archivo en `candidatos_estables`, `candidatos_anteriores` y `sin_identificar`, manteniendo el diccionario `_mapa_media` y el método `resolver_ruta_media(id_media)`; verificar con tests unitarios
- [x] 1.2 Configurar `ThreadingHTTPServer` con `daemon_threads = True` en `crear_servidor` en `bandeja/servidor.py` para evitar bloqueos del servidor durante el streaming
- [x] 1.3 Implementar el método `do_HEAD` y el manejador `_servir_media` en `bandeja/servidor.py` con validación de cabecera `Host`, resolución estricta con `os.path.realpath`, confinamiento a raíces permitidas (`~/Descargas` y `~/Descargas/_lucie`), rechazo de symlinks que escapen, y respuesta 404 para identificadores desconocidos
- [x] 1.4 Implementar soporte de peticiones `Range` en `_servir_media` (código 206, `Content-Range`, `Accept-Ranges`, `Content-Length`, código 200 sin Range, y 416 para rangos inválidos), cabeceras de seguridad (`ETag`, `Cache-Control: private`, `X-Content-Type-Options: nosniff`, `Content-Disposition: inline`) y streaming en bloques de 64 KiB con captura silenciosa de `BrokenPipeError` y `ConnectionResetError`; verificar con pruebas unitarias

## 2. Frontend: Tarjetas con primer fotograma y carga perezosa

- [x] 2.1 Actualizar `generarHtmlCardLote`, `generarHtmlCardLoteAnterior` y `renderSinIdentificar` en `bandeja/web/panel.js` para diferenciar videos de fotos: videos con `<video muted playsinline preload="metadata">` apuntando a `/api/media?id=${a.id_media}#t=0.1` vía carga perezosa y fallback a placeholder, y fotos con su miniatura con cursor de mano
- [x] 2.2 Implementar en `bandeja/web/panel.js` el gestor de carga diferida con `IntersectionObserver` y límite de concurrencia (máximo 3 cargas simultáneas) para los fotogramas de video en tarjetas
- [x] 2.3 Añadir estilos CSS en `bandeja/web/panel.css` para miniaturas interactivas, cursor pointer, contenedor de video y transiciones de carga

## 3. Frontend: Visor modal interactivo (Lightbox)

- [x] 3.1 Añadir en `bandeja/web/panel.html` la estructura HTML del visor modal `#modal-visor-media` con cabecera de información (nombre, tamaño, fecha de llegada, lote), controles de navegación (anterior/siguiente), checkbox "Seleccionado", contenedor multimedia para foto/video y contenedor de error de formato con botón "Copiar ruta"
- [x] 3.2 Añadir en `bandeja/web/panel.css` los estilos del visor a pantalla casi completa, centrado de foto/video (`object-fit: contain`), botones de navegación flotantes y caja de aviso de formato no soportado
- [x] 3.3 Implementar en `bandeja/web/panel.js` las funciones `abrirVisorMedia(loteId, idMedia)`, `cerrarVisorMedia()`, `navegarVisorMedia(delta)`, `copiarRutaVisor()` y los manejadores de teclado (flechas izquierda/derecha y Escape)
- [x] 3.4 Sincronizar bidireccionalmente el checkbox dentro del visor con el de la tarjeta correspondiente y registrar `#modal-visor-media` en `hayModalAbierto()` para suspender el refresco automático mientras el visor esté activo
- [x] 3.5 Implementar la liberación de memoria al cerrar el visor (pausar video, remover atributo `src` y ejecutar `load()`) y el manejo de formatos no soportados

## 4. Pruebas unitarias, auditoría AST y verificación integral

- [x] 4.1 Agregar pruebas unitarias en `test_bandeja_descargas.py` para el endpoint `/api/media`: Range con 206 y bytes exactos, petición completa con 200, Range inválido con 416, método HEAD sin cuerpo, ID inexistente con 404, intento de inyección de ruta con 404, symlink que escapa con 403, Host no permitido con 403, corte de conexión sin excepciones en logs, y pruebas de frontend en Node.js (apertura de visor, navegación por lote, sincronización de checkbox y pausa de refresco)
- [x] 4.2 Ejecutar `python3 seguridad_anti_borrado.py` verificando 0 infracciones en todos los módulos y correr la suite completa con 100% de tests en verde
