# Videos sin publicar y envío al celular

Los exports nuevos se resguardan en `LucieSinReglas/videos completos/videos sin publicar/`.
Los vinculados a una sesión conservan personaje y carpeta de edición. Los exports
sin una sesión inequívoca se copian con su nombre original directamente en la cola,
sin inventar una asociación. Si un nombre ya contiene otro video, se usa un sufijo
de versión derivado del hash. Los originales de CapCut no se modifican.

```text
videos completos/
  videos sin publicar/
    luciecafe.mp4
    roli/<nombre de edición>/<video.mp4>
  luciecafe.mp4                         # después de recibirlo por Wi-Fi
  roli/<nombre de edición>/<video.mp4>  # después de recibirlo por Wi-Fi
```

Las carpetas y videos anteriores no se reorganizan automáticamente. La opción
manual de envío de exports continúa respetándose. «Guardar en Sin publicar»
permite resguardar explícitamente un export sin sesión, también después de Deshacer.
Una copia deshecha no vuelve a enviarse automáticamente.

## Usar la sección del dashboard

1. Reiniciar la bandeja después de actualizar y recargar el navegador con `Ctrl+F5`.
2. Abrir **Sin publicar · Enviar al celular**. Elegir Lucie, Roli o Mailen,
   buscar por nombre/carpeta si es necesario y revisar la vista previa. Marcar
   archivos individualmente o pulsar **Seleccionar los visibles**.
3. Abrir [Lucie Recibir](../android/README.md) o
   [LocalSend en el celular](https://localsend.org/download), en la misma
   red Wi-Fi que la PC. No hace falta instalar LocalSend en la PC: el emisor está
   integrado al dashboard y usa la biblioteca estándar de Python.
4. Pulsar **Buscar celulares**, elegir el receptor y **Revisar envío**. Si no
   aparece, ingresar su IP local y el puerto del receptor (53318 para Lucie Recibir, 53317 para LocalSend).
5. Revisar archivos, tamaños, receptor y destinos, y confirmar el envío. Si el
   receptor solicita PIN, ingresarlo antes de confirmar. Aceptar la recepción
   en el celular y mantener el receptor abierto hasta completar la transferencia.
   Con Lucie Recibir, comparar antes la huella HTTPS completa con el dashboard.
6. Tras la respuesta satisfactoria del receptor y la verificación de integridad,
   los videos se trasladan al nivel anterior de `videos completos`, conservando
   su estructura relativa. El historial ofrece **Volver a Sin publicar**.

Por decisión del usuario, una recepción confirmada se utiliza como señal de
publicación. No se consulta Instagram ni se comprueba que un video se subió a
una red social. Deshacer devuelve el archivo local a la cola; no elimina la
copia del celular ni modifica ninguna publicación en redes.

## Galería y separación por personaje

La lista contiene únicamente videos y fotos que existen dentro de
`videos completos/videos sin publicar/` del pendrive vinculado. No se incluyen
directamente originales de CapCut, crudos ni archivos de ya editados. Un export
copiado a la cola puede conservar un nombre numérico de CapCut; la tarjeta
muestra su carpeta para distinguirlo y ofrece una vista previa de esa copia.

Los archivos se agrupan en Lucie, Roli, Mailen y **Sin asignar**. Se usa primero
la carpeta contenedora conocida, luego una sesión que registre esa ruta exacta
y por último un prefijo explícito del nombre (se indica en la tarjeta). Nombres
como `1010(6).mp4` sin carpeta o sesión identificadora no se asignan a un personaje
por adivinación. Filtrar no mueve, renombra ni clasifica físicamente material.

Las fotos se muestran como imágenes y los videos mediante reproductores con
fotograma inicial y controles. No requiere ffmpeg: la vista previa depende de
los formatos/códecs admitidos por el navegador. Si falla, aparece un mensaje y
un enlace para abrir el archivo. Las vistas previas se cargan al acercarse a la
zona visible para evitar descargar muchos videos simultáneamente.

Al cambiar de personaje o búsqueda se limpian selección y revisión anteriores.
«Seleccionar los visibles» incluye exclusivamente el filtro actual; al actualizar,
se retiran selecciones que ya no pertenecen a esa vista. El contador muestra
cuántos archivos están visibles y cuántos se enviarán. El endpoint de vista previa
usa IDs opacos del inventario vigente, con rangos HTTP; rechaza rutas libres y
deja de resolver el archivo cuando sale de la cola.

## Fallos, cancelación y seguridad

- La revisión no envía ni mueve archivos. El plan privado vence en cinco minutos,
  es de un solo uso y exige confirmación explícita desde el dashboard con CSRF.
- Se comprueban identidad del pendrive, rutas canónicas, ausencia de enlaces y
  junctions, identidad y contenido del archivo y destinos libres. El renombrado
  de publicación no puede sobrescribir un destino existente.
- Se envía tamaño y SHA-256 al receptor, se verifica el hash del flujo enviado
  y se espera su respuesta satisfactoria. Rechazo, desconexión o error de checksum
  conservan el video en la cola. Si solo se aceptan algunos archivos, se archivan
  los recibidos y se informa el resultado parcial; el resto se conserva.
- Una cancelación interrumpe la conexión incluso esperando aceptación y evita los
  siguientes bloques/archivos. Si el celular ya
  confirmó un archivo completo, su recepción queda registrada. No se borra nada.
- Envío y reversión usan el bloqueo exclusivo del pendrive. No se desconecta ni
  se elimina material mediante otra operación mientras se transfiere.
- Se registran inicio, recepción, traslado y reversión en el manifiesto append-only,
  con sincronización de escritura. Se actualizan las rutas de sesiones y exports.
  Si el último registro fallara después del traslado, el historial puede recuperar
  el archivo mediante la recepción registrada y la coincidencia del hash.
- El dashboard sigue ligado a su dirección local. El descubrimiento abre durante
  unos segundos un servidor de registro de dispositivos sin acceso a archivos.
  La transferencia es saliente hacia la IP local del receptor. No se abren puertos
  en el router ni se cambian reglas del firewall automáticamente.
- Se admiten receptores LocalSend v2 HTTP/HTTPS. En HTTPS se fija la huella del
  certificado elegido; en HTTP se vuelve a comprobar la identidad del receptor.
  No se persisten PIN ni tokens de transferencia en registros.

La búsqueda escucha anuncios/respuestas UDP y registros HTTP temporales;
Lucie Recibir usa descubrimiento UDP 53319, respuesta unicast al dashboard y
HTTPS TCP 53318 para los archivos. LocalSend conserva 53317. No comparten escucha. Necesita que la
red permita multicast y las respuestas locales. Si
la red de invitados aísla los dispositivos o el firewall impide el descubrimiento,
usar una red compartida y conexión por IP. No se garantiza descubrimiento en redes
que bloqueen la comunicación entre dispositivos.

## API y módulos

`bandeja/publicacion.py` gestiona cola, planes, tareas, publicación y reversión.
`bandeja/localsend.py` implementa el emisor del
[protocolo LocalSend v2.2](https://github.com/localsend/protocol).
`bandeja/web/wifi.js` proporciona selección, receptor, revisión, progreso e historial.

- `GET /api/publicacion/lista` y `GET /api/publicacion/estado?id=...`.
- `POST /api/publicacion/buscar`, `/conectar`, `/simular`, `/enviar`, `/cancelar`,
  `/deshacer`, `/resguardar`, dentro de ese mismo prefijo.

## Diagnóstico de receptor ocupado

El error muestra etapa, HTTP y resultado de cancelar. **Preparación / 409**
significa que el receptor ya reservó otro envío: aceptarlo, rechazarlo o cancelarlo
**en el teléfono**. Sin sessionId propio no se cancela esa sesión por adivinación.
Si falla después de obtener nuestro ID, el emisor intenta cancelar y distingue
confirmación de error. HTTP 204 durante preparación no marca archivos recibidos.
No se repite automáticamente un envío con recepción desconocida.

Abrir Lucie Recibir permite revisar la solicitud pendiente y cancelarla de forma
explícita. Mantenerlo visible; detenerlo o salir libera la reserva. No se atribuye
el 409 de la captura histórica a una causa específica sin el teléfono original.
Los logs del emisor incluyen operación, etapa, HTTP y duración, sin PIN ni tokens.

## Evidencia por plataforma

Kali/Python 3.13: suite de 367 pruebas, OK con cinco saltos por capacidades Windows.
Las pruebas HTTP falsas conservan aserciones de bytes, hashes y estados. El APK
propio además se probó por HTTPS en emulador Android 17 usando Artemis: video/foto,
MediaStore, aceptación, cancelación, segundo envío, homónimos, PIN, huella falsa,
hash corrupto y el gestor de archivado/Deshacer con temporales. Ver
[compilación y pruebas Android](../android/README.md).

`node test_publicacion_ui.js` verifica filtros, selección visible y flujo con
DOM/API simulados. El fotograma nativo se comprobó anteriormente con un WebM
sintético; no se certifican todos los códecs del material real. Este lote no se
ha ejecutado en Windows, ni en el Motorola físico ni contra la app oficial
LocalSend. Recibir en emulador mediante ADB no demuestra descubrimiento Wi-Fi.
Resultados, recuentos y evidencia histórica en [ESTADO_ACTUAL.md](../ESTADO_ACTUAL.md).
