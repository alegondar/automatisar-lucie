# Lucie Recibir — Android 0.2.0

Cliente nativo Kotlin para recibir desde **Sin publicar · Enviar al celular**.
Android 10 o posterior (API 29), con la pantalla visible durante el envío.
No requiere instalar LocalSend. Es una primera versión de prueba; el Motorola
físico y su red Wi-Fi siguen pendientes de validación.

## Instalar y recibir

1. Obtener el APK compilado de esta entrega. Es una compilación debug firmada
   para pruebas, no una publicación de Play Store. No hay APKs ni claves en Git.
2. Abrir el APK en el Motorola y autorizar esa instalación cuando Android lo
   solicite. Alternativa por USB: activar depuración, elegir el serial exacto en
   `adb devices -l` y ejecutar `adb -s <serial> install -r <ruta-al-apk>`.
   Si existe una versión con otra firma, no desinstalarla automáticamente.
3. Conectar teléfono y PC a la misma Wi-Fi, abrir **Lucie Recibir** y mantener
   la pantalla abierta. Lucie usa sus propios puertos y puede coexistir con LocalSend.
4. En el dashboard, seleccionar archivos y buscar el celular. Si no aparece,
   usar la IP que muestra la app y el puerto **53318**. La app recibe por HTTPS.
5. Antes de confirmar, comparar los 64 caracteres de la **huella HTTPS** entre
   teléfono y revisión del dashboard. La aceptación del teléfono es obligatoria;
   el PIN opcional se ingresa en el dashboard y no sustituye esa aceptación.
6. Revisar nombres y tamaños en el teléfono, pulsar **Aceptar archivos** y esperar.
   Los videos quedan en `Movies/LucieSinReglas`, fotos en `Pictures/LucieSinReglas`
   y MP3 en `Music/LucieSinReglas`. La cola actual del dashboard ofrece video/foto;
   la API del receptor también admite MP3.
7. El dashboard archiva solamente después del ACK de recepción íntegra.
   **Volver a Sin publicar** revierte el archivado local, conserva la copia del
   teléfono y no elimina publicaciones de redes sociales.

Salir de la app detiene el receptor y cancela su sesión. La pantalla se mantiene
encendida mientras está visible. **Cancelar recepción actual** libera nuestra
sesión; otro envío exige una nueva selección y aceptación. No hay reenvío automático.

## Cómo se conectan las piezas

```text
Dashboard → GestorPublicacion → ClienteLocalSend → HTTPS → ReceiverServer
                                                       ↓ Aceptar/Rechazar
                                                 TransferState → MediaSink
                                                                 ↓
                                                MediaStore pendiente → visible
                         ACK 200 ← tamaño/hash/escritura persistente
                         ↓
                registro + archivado local sin reemplazar
```

- `MainActivity`: interfaz, IP, huella, PIN, aprobación, progreso e historial.
- `Identity`: certificado estable y clave no exportable en AndroidKeyStore.
  El emisor fija la huella del certificado; cambiarla rechaza la conexión.
- `TransferState`: una reserva, tokens por archivo, propietario por ID/IP y
  cancelación idempotente. Una cancelación anterior no afecta una sesión nueva.
- `ReceiverServer`: HTTPS local, endpoints de información, preparación, carga y
  cancelación de LocalSend v2; respuestas de descubrimiento multicast UDP.
- `MediaSink`: archivo nuevo mediante MediaStore con `IS_PENDING=1`, copia por
  bloques, SHA-256, tamaño, sincronización y publicación con `IS_PENDING=0`.
  También escribe un resguardo privado que no expira con MediaStore.
  No pide acceso general a la biblioteca del usuario.

Nombres inválidos, rutas, tipos no admitidos y espacio insuficiente se rechazan.
Un homónimo obtiene un sufijo; no reemplaza el anterior. Si se interrumpe la carga
o falla el hash, la entrada parcial se conserva pendiente/oculta y se registra en
el historial privado. Cada recepción también guarda los bytes en
`files/resguardos/` de la app, sin limpieza automática, incluso cuando se completa.
MediaStore puede expirar pendientes; ese resguardo independiente conserva la copia
sin publicarla. Se comprueba espacio para ambas copias. No desinstalar ni borrar
los datos de la app si se quieren conservar esos resguardos. Si el emisor no
proporciona SHA-256, se comprueba tamaño y se indica explícitamente la ausencia
de hash de origen; el dashboard sí envía SHA-256.

Contrato inicial: IPv4 local, HTTPS TLS 1.2/1.3, puerto TCP 53318 y descubrimiento UDP 53319, cuerpos con
`Content-Length`, hasta 100 metadatos por preparación (el dashboard limita 50),
aceptación durante 60 segundos y reserva inactiva durante 120 segundos. No soporta
cargas chunked, descarga inversa, servicios permanentes en segundo plano ni todos
los posibles clientes LocalSend. No abre puertos del router.

## Compilar y verificar

Se necesitan JDK 17 o posterior, Android SDK plataforma 35/build-tools y Gradle
Wrapper 8.13. AGP 8.13.2 y Kotlin 2.2.21 están fijados. Configurar `ANDROID_HOME`
o un `local.properties` **local e ignorado** con `sdk.dir`; no versionar esa ruta.

```bash
cd android
./gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
# Solo en un emulador de prueba conectado:
./gradlew :app:connectedDebugAndroidTest
```

Salida: `app/build/outputs/apk/debug/app-debug.apk`. En Windows, usar `gradlew.bat`.
La primera compilación necesita descargar las dependencias; `--offline` solo
funciona si ya están en caché. La firma debug queda en el entorno de desarrollo;
una distribución estable necesita una clave privada persistente fuera de Git.

Hay cuatro pruebas JVM de reserva, propiedad, cancelación y metadatos, y cuatro
pruebas instrumentadas de MediaStore: archivo íntegro/homónimo, hash incorrecto y
cancelación, más coexistencia con LocalSend ocupado y descubrimiento unicast.
Todas usan datos sintéticos; conservan sus copias y parciales en el
emulador, sin borrar archivos.

### Verificación de extremo a extremo con Artemis

Usa el proyecto oficial [google/artemis](https://github.com/google/artemis),
revisión comprobada `351ca8422f7b5b54e80a9c1ce03a222e02415b6b`. Instalarlo en un
directorio separado con `uv sync --no-dev`. No requiere ejecutar el asistente
autónomo ni configurar Gemini: esta prueba invoca observación UI y taps directos.

Instalar el APK **solo en el emulador** y ejecutar desde el directorio de Artemis,
con la ruta absoluta del script de este repo:

```bash
adb -s emulator-5554 install -r /ruta/repo/android/app/build/outputs/apk/debug/app-debug.apk
/ruta/artemis/.venv/bin/python /ruta/repo/android/tests/verificar_receptor.py --device emulator-5554
```

Requiere `adb`, `ffmpeg` y las dependencias de Artemis en ese entorno. El script
rechaza seriales de teléfonos físicos, crea una conexión ADB local 53318→53318,
manipula únicamente la app del emulador y archivos temporales. Puede instalar el
controlador UIAutomator2 en el emulador. No inicia la bandeja real ni accede al
pendrive. Capturas y logs deben quedar fuera de Git. No correr simultáneamente
las pruebas instrumentadas, que también controlan el emulador.

Comprueba bytes reales por HTTPS, MediaStore visible, cancelación esperando
aceptación, segundo envío, homónimos, huella falsa, PIN/rechazo, hash corrupto,
cancelación durante upload y el gestor del dashboard con video/foto, archivado
tras ACK y Deshacer en un pendrive simulado temporal.

## Alcance de esta entrega

Compilación/lint, 4 pruebas JVM, 4 instrumentadas y flujo Artemis ejecutados en
Kali con emulador Android 17. No equivale a ejecución en Android 10 ni en Motorola.
Falta comprobar Android/modelo reales, Wi-Fi/multicast, galería, archivo grande,
desconexión y espacio insuficiente en hardware físico; también la comparación
con el cliente oficial LocalSend y la suite nativa Windows de este lote.

Fuentes: [protocolo LocalSend](https://github.com/localsend/protocol),
[MediaStore](https://developer.android.com/training/data-storage/shared/media),
[AndroidKeyStore](https://developer.android.com/privacy-and-security/keystore),
[expiración de pendientes](https://developer.android.com/reference/android/provider/MediaStore.MediaColumns#DATE_EXPIRES) y
[red local Android](https://developer.android.com/privacy-and-security/local-network-permission).

## Puertos separados y descubrimiento (2026-10-13)

| Uso | Lucie Recibir | LocalSend oficial |
|---|---|---|
| Recepción HTTPS | TCP 53318 | TCP 53317, salvo configuración propia |
| Descubrimiento | UDP 53319 | UDP 53317 |
| Respuesta a búsqueda de Lucie | Unicast al puerto temporal del dashboard | Registro HTTP compatible |

El emisor busca Lucie por multicast y broadcast local; el teléfono responde a
la IP y al puerto de origen, anunciando el puerto HTTPS. Se verifica el receptor
por HTTPS antes de mostrarlo. El dashboard no abre escucha UDP 53317. Los dos
receptores de una misma IP se distinguen por puerto; no se ocultan mutuamente.
La conexión manual usa 53318 por defecto y permite elegir 53317 para LocalSend.
Si la Wi-Fi aísla equipos o bloquea ambos métodos, los puertos por sí solos no
resuelven la red: comprobar primero la conexión por IP en la misma Wi-Fi.

La nueva pantalla agrupa estado/IP en una tarjeta, identidad HTTPS desplegable,
solicitud de aprobación, controles secundarios e historial. No se quitan la
confirmación, el PIN, el hash ni los resguardos.
