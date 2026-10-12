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
3. Abrir [LocalSend en el celular](https://localsend.org/download), en la misma
   red Wi-Fi que la PC. No hace falta instalar LocalSend en la PC: el emisor está
   integrado al dashboard y usa la biblioteca estándar de Python.
4. Pulsar **Buscar celulares**, elegir el receptor y **Revisar envío**. Si no
   aparece, ingresar su IP local y el puerto de LocalSend (53317 por defecto).
5. Revisar archivos, tamaños, receptor y destinos, y confirmar el envío. Si el
   receptor solicita PIN, ingresarlo antes de confirmar. Aceptar la recepción
   en el celular y mantener LocalSend abierto hasta completar la transferencia.
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
- Una cancelación interrumpe los siguientes bloques/archivos. Si el celular ya
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

La búsqueda necesita que la red permita multicast y las respuestas locales. Si
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

Las pruebas usan archivos temporales y un receptor HTTP falso, compatible con
los mensajes LocalSend: se verifican bytes, hashes, aceptación y estados. La
interoperabilidad con el teléfono físico requiere una recepción real elegida por
el usuario. Linux no se declara validado desde esta máquina Windows.
La suite completa final de la galería ejecutada fue de 357 pruebas, OK con 10
omisiones por capacidades ausentes; el manifiesto real se mantuvo en 270 / 270 líneas.
`node test_publicacion_ui.js` verifica filtros, selección visible y flujo de envío
con DOM/API simulados. El fotograma nativo se comprobó en Chrome headless con un
video WebM sintético temporal; no se probaron códecs de los videos reales.
La evidencia y los motivos están en [ESTADO_ACTUAL.md](../ESTADO_ACTUAL.md).
