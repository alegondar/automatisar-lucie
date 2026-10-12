# Plan pendiente: verificar envío y crear Lucie Recibir para Android

Estado: **propuesto, pendiente de conformidad del usuario para implementar en
la próxima sesión**. No hay APK ni cliente Android implementado en esta entrega.
Leer AGENTS.md, ESTADO_ACTUAL.md y README_KALI.md antes de continuar.

## Qué está comprobado y qué falta

El dashboard es el emisor; la aplicación LocalSend del celular es el receptor.
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

## Decisión propuesta

Primero corregir y demostrar el emisor. Después crear una aplicación Android
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

## Para iniciar la próxima sesión

Leer este plan y confirmar la conformidad pendiente. Identificar modelo/versión
de Android, disponibilidad de Android SDK/emulador y acceso al teléfono para
pruebas. Revisar la entrega en `actualizacion-completa-host` y confirmar el
estado de GitHub mediante fetch. Trabajar en una rama, conservar los cambios locales
y no modificar master. Empezar por las etapas 1 y 2; después implementar el APK.

Fuentes primarias:
[Protocolo LocalSend v2.2](https://github.com/localsend/protocol),
[MediaStore](https://developer.android.com/training/data-storage/shared/media) y
[permisos de red local Android](https://developer.android.com/privacy-and-security/local-network-permission).
