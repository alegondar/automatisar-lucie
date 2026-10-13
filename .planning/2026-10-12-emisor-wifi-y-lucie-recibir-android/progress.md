# Progreso — 2026-10-12

## Realizado

- Revisadas guías, CodeGraph, estado Git y remotos; fetch sin nuevas versiones.
- Rama de trabajo creada conservando documentación Kali local; master intacto.
- Emisor: errores por etapa/HTTP, interrupción de sockets en espera, cancelación
  propia comprobada, HTTP 204 sin recepción y descubrimiento UDP.
- Dashboard: fases y diagnóstico visibles; huella HTTPS para comparar.
- Android Kotlin: HTTPS/AndroidKeyStore, propietario de sesión, aceptación/PIN,
  recepción por bloques y MediaStore; respaldo privado sin limpieza automática.
- Gradle/JDK/SDK locales; herramientas y versiones fijadas. APK/builds ignorados.
- Artemis instalado en temporal y usado con UIAutomator2 sobre emulador; no se
  configuraron credenciales ni agentes globales. Modo autónomo no requerido.
- Bandeja real de este repo detenida ordenadamente antes de suite por README_KALI.

## Evidencia

- Kali: suite 367 tests OK, cinco saltos Windows; final: 50.607 s.
- Emisor: 27 tests de publicación, cancelación y respuesta UDP OK.
- Android: cuatro JVM y tres instrumentados; build/lint OK antes de añadir
  aserciones del resguardo persistente. Revalidación final: build/lint, cuatro JVM
  y tres instrumentados OK; resguardos comprobados con bytes exactos.
- APK final instalado en emulador, script Artemis reproducible OK; firma APK
  validada. Logs en temporales y artefactos Android ignorados por Git.
- Artemis: bytes HTTPS, MediaStore visible, cancelar esperando aprobación,
  repetición/homónimos, PIN/rechazo, huella falsa, checksum y cancelación upload.
- Gestor aislado: video/foto, ACK, archivado y deshacer con bytes conservados.
- AST 0/24; JS/UI y auditoría rastreados/historial/nuevos sin infracciones.
- Manifiesto real no disponible antes/después; no son recuentos cero.

## Hallazgos corregidos

- Taps Artemis usan límites normalizados 0–1000, no píxeles físicos.
- TLS con AndroidKeyStore EC requiere DIGEST_NONE para firmas prehasheadas.
- Script de prueba debe esperar servidor listo tras iniciar la Activity.
- Pendientes MediaStore expiran: copia privada persistente evita perder parciales.

## Pendiente

Motorola físico, Wi-Fi/multicast, galería, archivo grande/espacio lleno/desconexión,
Windows nativo y comparación con LocalSend oficial. El usuario confirmó
commit/push para este lote; publicación en curso. No afirmar validación de
plataformas no ejecutadas.

## Continuación 2026-10-13

El usuario exige separar puertos y mejorar pantalla. Se corrigieron TCP 53318,
UDP 53319 y respuesta unicast a socket efímero; búsqueda multicast/broadcast y
clave IP/puerto. Build/lint, cuatro JVM y cuatro nativas OK, incluida coexistencia
con puertos LocalSend ocupados. Artemis HTTPS/video/foto/cancelación/hash/homónimo/
PIN/archivado/deshacer OK. Suite Kali final: 368 OK, cinco saltos, 50.931 s;
manifiesto antes/después no disponible, AST 0. Motorola no conectado; requiere
reinstalar 0.2.0 y verificar Wi-Fi real. Commit/push anterior autorizado sigue
pendiente de ejecutar en este mismo lote, condicionado a auditorías finales.

### Cierre con hardware real

El Motorola se reconectó: instalada 0.2.0 con datos conservados. Artemis verificó
pantalla y receptor listo. HTTPS 53318 y búsqueda automática Wi-Fi encontrados;
API aislada /api/publicacion/buscar devolvió HTTP 200 con Lucie. No se mandaron
fixtures a la galería del teléfono ni se inició la bandeja real. Código publicado
990f32e en feat/lucie-recibir; registro de evidencia en documentación. Quedan
archivos/galería físicos y Windows nativo, sin confundirlos con emulador.
