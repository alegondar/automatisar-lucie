# Seguimiento: emisor Wi-Fi y Lucie Recibir para Android

Estado: **implementación autorizada por el usuario y realizada en
`feat/lucie-recibir`**. APK inicial compilado y probado en emulador, pendiente
de archivos/galería en el Motorola físico. La instalación 0.2.0, HTTPS y
descubrimiento Wi-Fi en Moto G54 5G / Android 15 ya se comprobaron.
Ver [Android](../android/README.md).
Leer AGENTS.md, ESTADO_ACTUAL.md y README_KALI.md antes de continuar.

## Qué está comprobado y qué falta

El dashboard es el emisor; LocalSend o Lucie Recibir en el celular son receptores.
Los archivos viajan por la red local al dispositivo elegido, no a un servicio
de almacenamiento de LocalSend ni a Instagram. La captura muestra el error
«celular ocupado con otro envío», con cero recibidos y cero archivados.
El protocolo define HTTP 409 como una sesión que bloquea otra transferencia.
Eso no identifica por sí solo la causa: puede haber una sesión activa, un estado
retenido después de cancelar, dos solicitudes o un fallo de interoperabilidad.

El emisor actual prepara una sesión, obtiene tokens por archivo, transmite bytes
y espera una respuesta antes de mover el archivo del pendrive. Ante un error
intenta cancelar si ya recibió un sessionId; si prepare-upload devuelve 409 antes
de entregar ese identificador, no conoce la sesión ajena y no puede cancelarla.
No se debe cancelar una transferencia de otro dispositivo por adivinación.

Se han probado flujos HTTP con receptor falso y temporales; no se ha certificado
una transferencia de extremo a extremo con el teléfono real. La suite posterior
dio 361 pruebas OK, 10 omisiones, pero su comprobación del manifiesto real cambió
de 271 a 273 líneas y detuvo el cierre según AGENTS.md. Se repitió la comprobación:
361 pruebas OK, 10 omisiones y manifiesto estable en 276 / 276 líneas. El control
previo a la entrega quedó satisfecho; ver evidencia en ESTADO_ACTUAL.md.

## Decisión aprobada

Se autorizó corregir y demostrar el emisor y crear una aplicación Android
propia llamada **Lucie Recibir**, compatible con los mensajes LocalSend v2.
Así la interfaz y la gestión de estados serán nuestras, con un contrato conocido
para probar el dashboard contra LocalSend y contra el cliente propio.
El usuario podrá utilizar el APK propio sin instalar la app LocalSend existente.
La app propia no evita por sí sola fallos del emisor: ambas partes deben validarse.

## Trabajo por etapas

1. **Diagnóstico reproducible del emisor.** Registrar etapa, código HTTP,
   duración, identificador de operación y resultado de cancelación, sin PIN,
   tokens ni contenido personal. Reproducir ocupado, rechazo, PIN incorrecto,
   aceptación, cancelación durante preparación y envío. Verificar solicitudes
   duplicadas y sesiones retenidas; comparar con una transferencia usando el
   emisor oficial de LocalSend. No repetir automáticamente un envío cuyo estado
   de recepción no sea conocido. Usar archivos sintéticos y receptor aislado.
2. **Cerrar el flujo del dashboard.** Estados visibles: buscando, esperando
   aceptación, enviando, recibido, archivado, cancelado y error. Liberar únicamente
   nuestras sesiones y comprobar el resultado de cancelar. Añadir pruebas HTTPS,
   identidad del receptor, timeout, ocupación y segundo envío después de cancelar.
   Aceptación HTTP 204 sin transferencia no cuenta como archivo recibido.
3. **APK Android inicial.** Proyecto Kotlin separado en `android/`, herramientas
   y versiones fijadas al implementar. Pantalla «Recibir», nombre del dispositivo,
   IP/puerto, archivos solicitados, Aceptar/Rechazar, progreso, Cancelar e historial.
   Primera versión con la app visible; no depender de un vigilante permanente en
   segundo plano. Preparación, tokens por archivo, upload y cancelación compatibles
   con LocalSend v2. Descubrimiento Wi-Fi más conexión por IP de respaldo.
4. **Recepción segura.** HTTPS con identidad estable y huella verificable,
   emparejamiento/aceptación explícita y PIN cuando corresponda. Verificar nombre,
   tamaño, espacio y SHA-256. Guardar primero en estado pendiente y hacer visible
   en la galería mediante MediaStore solo tras completar/verificar la escritura.
   Carpeta propuesta: `Movies/LucieSinReglas` para videos y equivalente Pictures
   para fotos. No sobrescribir homónimos; conservar parciales para revisión.
   Responder éxito únicamente después de guardar el archivo íntegro. Ajustar los
   permisos de red local y almacenamiento a la versión real de Android.
5. **Integración y pruebas reales.** Windows y Kali con fixtures temporales;
   emulador Android para lógica y teléfono físico para Wi-Fi, permisos y galería.
   Matriz: video/foto, archivo grande, dos archivos, rechazo, cancelación,
   desconexión, destino lleno, nombre repetido y reinicio. Probar ida y repetición:
   terminar/cancelar un envío no debe bloquear el siguiente. No usar material real
   del pendrive como fixture ni iniciar la bandeja real para pruebas.
6. **Entrega y continuidad.** Documentar compilación/instalación del APK,
   emparejamiento, permisos, diagnóstico, contratos y resultados por plataforma.
   Firmas privadas y APKs generados fuera de Git; guardar solo código y configuración
   reproducible. Revisar diff/auditorías y publicar la rama con autorización vigente.

## Condiciones para darlo por terminado

- El teléfono recibe exactamente los bytes elegidos y confirma tamaño/hash.
- Cero recibidos implica cero archivos movidos fuera de Sin publicar.
- Solo los archivos confirmados y guardados íntegros pueden archivarse; los demás
  se conservan, sin duplicar envíos al reintentar ni cancelar sesiones ajenas.
- Cancelar libera el estado propio y permite otro envío; Deshacer devuelve la copia
  local a Sin publicar sin quitar el archivo del teléfono.
- Hay evidencia separada de Windows, Kali, emulador y teléfono; no confundir mocks
  o revisión de código con ejecución real.

La recepción seguirá siendo la señal de publicación elegida por el usuario;
no se verificará que el video se haya subido a una red social.

## Trabajo realizado y continuidad (2026-10-12)

- Emisor: diagnóstico por operación/etapa/HTTP/duración sin secretos, preparación
  con aceptación de hasta 90 s, cancelación que interrumpe sockets incluso antes
  de obtener el ID, resultado de cancelación comprobado y 204 de preparación
  rechazado como recepción. HTTP 409 previo al ID no cancela sesiones ajenas.
- Dashboard: fases de aceptación, envío, recepción, archivado y error; huella
  HTTPS comparable con el teléfono y diagnóstico de cancelación no confirmada.
- Android: Kotlin nativo, HTTPS con AndroidKeyStore, aprobación/PIN, estado único,
  cancelación por propietario, MediaStore pendiente, SHA-256 y nombres sin
  reemplazo. Resguardo privado persistente para conservar bytes aunque MediaStore
  expire pendientes; sin limpieza automática, con espacio para las dos copias.
  Multicast UDP más conexión por IP; visible durante la transferencia.
- Evidencia: 27 tests Python de publicación/emisor/descubrimiento; build, lint,
  cuatro tests JVM y tres instrumentados. Artemis observó la interfaz y aceptó
  solicitudes del APK en emulador Android 17. Se verificaron bytes por HTTPS,
  video/foto, cancelación antes de aceptar y durante upload, segundo envío,
  homónimos, PIN/rechazo, hash corrupto, identidad TLS y archivado/Deshacer.
  Suite Kali: 367 tests OK con cinco saltos. Resultados finales y manifiesto en
  ESTADO_ACTUAL.md. Los scripts reproducibles están en `android/tests/`.
- Pendiente: modelo y versión exactos del Motorola, instalación USB/APK, Wi-Fi
  real y descubrimiento, galería, transferencia grande, desconexión/espacio lleno,
  comparación con LocalSend oficial y Windows nativo. La reproducción aislada
  de 409 no demuestra cuál fue la causa de la captura del teléfono original.
- Publicación de este lote: el usuario autorizó expresamente commit/push en
  `feat/lucie-recibir`. No volver a pedir esa autorización para este mismo lote.

La siguiente sesión debe leer estas guías y revisar GitHub mediante fetch,
conservar cambios locales y no tocar master. Continuar por la validación física;
no volver a pedir conformidad para implementar lo ya autorizado. No usar material
real como fixture ni iniciar los vigilantes reales para comprobar el APK.

Fuentes primarias:
[Protocolo LocalSend v2.2](https://github.com/localsend/protocol),
[MediaStore](https://developer.android.com/training/data-storage/shared/media) y
[permisos de red local Android](https://developer.android.com/privacy-and-security/local-network-permission).

## Corrección 0.2.0 (2026-10-13)

- Puerto HTTPS propio 53318, descubrimiento propio UDP 53319; el emisor no
  escucha UDP 53317. Respuestas unicast al puerto temporal del dashboard,
  búsqueda multicast/broadcast y conexión manual con 53318 predeterminado.
- Dos apps en una IP se distinguen por puerto. LocalSend conserva 53317.
- Pantalla organizada en tarjetas, identidad desplegable, aceptación y controles.
- Prueba instrumentada con los dos puertos de LocalSend ocupados: Lucie abre y
  responde; ocho tests Android total OK. Flujo Artemis HTTPS/emulador OK.
- Moto G54 5G / Android 15 identificado, 0.1.0 instalada previamente con conflicto.
  0.2.0 instalada conservando datos; pantalla/HTTPS/descubrimiento Wi-Fi real y
  endpoint de búsqueda HTTP 200 comprobados. No se usó material real como fixture.
  Archivos y galería del teléfono físico siguen pendientes de una selección del usuario.
