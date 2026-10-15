# Estado actual del sistema — 2026-10-15

## Actualización del host Kali desde GitHub (2026-10-15)

Se descargaron e integraron por fast-forward los commits `46dd8e5` y `add96b1`
de `origin/feat/lucie-recibir`, desde `c719cb2`, por pedido explícito del usuario.
La rama local continúa en **`feat/lucie-recibir`**, en **`add96b1`**, coincidente
con su upstream. Las demás ramas remotas son antecedentes integrados.
Se conservaron bases/configuraciones locales y material; no se modificó master.
Incluye rutas/cancelación HTTP y HTTPS, revisión y copia del export al terminar,
pendientes visibles y retirada limitada de carpetas vacías tras operaciones exitosas.

Validación **Kali/Linux, Python 3.13.12: 415 pruebas OK, cinco saltadas**, en
**57.177 s**. Las cinco requieren capacidades nativas Windows (socket exclusivo,
compartición/bloqueo y archivos abiertos). Se conservaron guardia y aserciones.
La primera ejecución dentro del sandbox no pudo crear sockets locales
(`PermissionError`, 81 errores); se repitió fuera de esa restricción, sin cambiar
las pruebas. Log final externo: `/tmp/tests_host_kali_20261015_nativo.log`.
Manifiesto antes/después: **no disponible / no disponible**, sin pendrive montado;
no son recuentos cero. Todas las pruebas usaron temporales y receptores loopback.

AST: **0 infracciones/27 módulos**. Sintaxis JS, UI de edición/publicación/CSRF y
auditoría de 234 archivos rastreados e historial correctas. No se inició la
bandeja real ni se enviaron archivos reales para probar. Windows nativo y teléfono
físico no se ejecutaron en esta sesión. Para cargar la versión, iniciar normalmente
la bandeja y recargar el panel con **Ctrl+F5**. Las sesiones anteriores terminadas
sin export pueden usar **Revisar video final**; no se importan históricos al instalar.

## Terminé de editar revisa y copia el video final (2026-10-14)

El botón antes finalizaba únicamente los clips crudos; una copia final pendiente
podía quedar sin revisión ni aviso. Ahora, después de organizar los clips,
revisa el export vigente de la sesión y lo copia en modo automático a
`videos completos/videos sin publicar/<personaje>/<carpeta de salida>/`.
La respuesta incluye `export_final` con estado, mensaje y destino efectivo.
El panel distingue clips organizados de video copiado, espera o error.

Las sesiones editadas sin copia permanecen visibles con **Revisar video final**
(`POST /api/edicion/revisar-export`, con CSRF). No se necesita crear otra sesión.
Un export preexistente al arranque puede recuperarse si corresponde a la ventana
de esa edición confirmada, después de los sondeos normales de estabilidad y
apertura exclusiva. El origen de CapCut se conserva. Varios exports o ventanas
de sesiones superpuestas se ofrecen para asignación explícita; no se elige uno
por ser el último ni se copia el grupo ambiguo automáticamente.

La solicitud se registra en la columna local `revision_export_solicitada` y se
retoma tras reiniciar. La migración añade esa columna con cero para sesiones
anteriores: no importa exports históricos al instalar la corrección. Para la
sesión ya terminada del usuario, reiniciar normalmente la bandeja, recargar con
Ctrl+F5 y usar **Revisar video final**. El modo manual sigue esperando el envío
explícito y Deshacer conserva su bloqueo contra reenvíos automáticos.

El dashboard no exporta el proyecto dentro de CapCut; el video final debe
generarse con Exportar allí y guardarse en la carpeta vigilada configurada.
No se cambiaron las categorías ni se migró material real del pendrive.

Validación final **Windows/Python 3.13.0: 415 pruebas OK, 11 omisiones**, en
**72.160 s**. Las omisiones existentes requieren Linux o privilegios de symlinks;
se conservaron guardia y aserciones. Manifiesto real exclusivamente contado:
**302 / 302**, estable. Log externo:
`%TEMP%/tests_terminar_export_20261014_validado.log`. La primera ejecución del
ajuste final detectó una conexión SQLite sin cerrar en la nueva prueba de
migración; se corrigió su cierre explícito y pasó la repetición completa.

Doce regresiones nuevas cubren copia al terminar, recuperación tras reiniciar,
exports históricos, sesiones superpuestas, estabilidad/bloqueos, modo manual,
Deshacer, error de copia, confinamiento y migración conservadora del indicador.
Dos pruebas API cubren el botón, destino, solicitud persistente, pendientes
visibles y CSRF. JS/UI de edición, CSRF y Wi-Fi correctos; AST 0/27, auditorías
del repo/historial y cuatro archivos nuevos sin infracciones, diff sin errores.
Pruebas exclusivamente en temporales. No se inició la bandeja real ni se usaron
archivos reales de CapCut/pendrive como fixtures. Linux y teléfono físico no
ejecutados para este lote. El usuario autorizó el commit y push de las correcciones
de cierre y carpetas vacías el **2026-10-15**, en `feat/lucie-recibir`.
La revisión previa a publicar no encontró novedades remotas ni commits anteriores
pendientes de subir en esa rama.

## Carpetas vacías de edición y envío al celular (2026-10-14)

Corrección local en `feat/lucie-recibir`, sobre `46dd8e5`. Fetch comprobado:
sin commits entrantes ni locales pendientes en esta rama. Tras finalizar
correctamente la edición o completar todos los archivos del envío Wi-Fi, se
retiran los padres vacíos de los archivos trasladados, después de sus registros.
La API informa `carpetas_vacias_retiradas`. Deshacer recrea las rutas originales.

`bandeja/carpetas_vacias.py` no recorre ramas hermanas ni limpia históricos:
conserva categorías, personajes, respaldos, enlaces/junctions y cualquier
contenido nuevo. Los errores de registro, conflictos y envíos parciales no
inician la limpieza. AST admite exclusivamente `os.rmdir(ruta)` dentro de
`retirar_carpetas_vacias_traslado`; no se amplía la autorización a archivos.

Windows/Python 3.13.0: **401 pruebas OK, 11 omisiones**, **71.292 s**.
Las omisiones existentes requieren Linux o privilegios reales de symlinks.
Manifiesto real solo contado: **297 / 297**, estable. Log externo:
`%TEMP%/tests_carpetas_vacias_20261014.log`. AST 0 infracciones/27 módulos,
sintaxis de ambos JS, UI Wi-Fi (13 llamadas) y auditoría repo/historial correctas.
Pruebas de nuevas carpetas, contenido concurrente, fallos, envíos parciales,
límites AST y reversión, exclusivamente en temporales con guardia hermética.
No se inició la bandeja real ni se reorganizó el pendrive como prueba; Linux y
el celular físico no se ejecutaron para este lote.

Esta validación corresponde a la limpieza de carpetas vacías. El usuario aclaró
después que el video final exportado debe aparecer automáticamente en
`videos completos/videos sin publicar` al confirmar «Terminé de editar».
Se conserva la separación vigente: clips en Ya editados y export final en la cola.
La corrección de ese botón y su evidencia se describen arriba. La autorización
de commit/push del 2026-10-15 incluye este lote de limpieza junto con el cierre.

## Actualización del host Windows y correcciones nativas (2026-10-14)

Se descargó `origin/feat/lucie-recibir` hasta **`c719cb2`** y se integraron sus
cinco commits posteriores a `8cce55e` sin conflictos. El host continúa en la
rama de trabajo local **`feat/lucie-recibir`**, con upstream del mismo nombre.
Se conservaron bases/configuraciones locales y no se modificó master.
La actualización incluye Android 0.2.0, descubrimiento independiente, publicados
por personaje, organización manual, renovación CSRF y apertura Chrome desde Python.

La primera suite nativa de Windows detectó dos fallos (390 pruebas, 11 omisiones):
la organización mezclaba separadores en las rutas al actualizar SQLite y cancelar
durante preparación esperó cinco segundos pese a interrumpir el socket. Se corrigió
el armado de rutas con segmentos nativos; reintentos y deshacer conservan las
rutas JSONL relativas. Las lecturas HTTP/HTTPS ahora consultan cancelación con
esperas de hasta 100 ms, mantienen el límite total, propietario del descriptor
y timeout original para conexiones reutilizables. No se relajaron aserciones.

Validación final en **Windows/Python 3.13.0: 392 pruebas, OK, 11 saltadas**, en
**72.590 segundos**. Las omisiones requieren Linux o privilegios reales de symlinks.
Manifiesto real únicamente contado antes/después: **297 / 297** líneas, estable
tanto en la ejecución inicial como en la final. Logs fuera del repo:
`%TEMP%/tests_host_actualizado_20261014.log` y
`%TEMP%/tests_host_actualizado_20261014_final.log`.

La regresión existente comprueba actualización/reversión de rutas y cancelación
en menos de dos segundos. Se añadieron envío HTTPS con huella/hash y cancelación
HTTPS a un receptor loopback, certificado/clave efímeros generados con OpenSSL
en temporales; ambas se ejecutaron, sin omisión. OpenSSL solo se necesita para
esas pruebas; la aplicación sigue usando stdlib. Si realmente falta, se documenta
la omisión de las pruebas TLS. AST **0 infracciones/26 módulos**, sintaxis de ambos
JS, UI de publicación y CSRF, y auditoría de repo/historial correctas.

No se inició la bandeja real como prueba ni se ejecutó Android, teléfono físico
o Linux en esta sesión. El usuario confirmó el commit/push de las correcciones
nativas y esta evidencia en `feat/lucie-recibir`. Para cargar el
programa actualizado, reiniciar la bandeja y recargar el panel con Ctrl+F5.

## Revisión Windows y descubrimiento independiente (2026-10-14)

Los cambios de organización/publicación por personaje, renovación CSRF y Chrome
automático ya están publicados en `feat/lucie-recibir` (`76bbfa7` y `d5a8ee3`).
La revisión adicional no encontró una corrección de código necesaria para Windows:
se conservan las rutas y renombrados Windows, detección de Chrome por ubicaciones
habituales/registro/PATH, puertos temporales y funcionamiento del `.bat` sin
apertura duplicada. El panel usa el mismo HTML/JS en ambos sistemas.

Pruebas específicas ejecutadas en **Kali/Python 3.13.12: 55 tests OK, tres saltos
Windows**, 4.713 s: compatibilidad, navegador, organización, descubrimiento y
regresión CSRF con creación de capítulo en temporales. Los saltos requieren
socket exclusivo y semántica de compartición/bloqueo de archivos de Windows.
Las ramas Windows revisadas mediante mocks no equivalen a ejecución nativa.
Manifiesto solo contado antes/después: **294 / 294**, estable. Log externo:
`/tmp/tests_revision_windows_dashboard.log`. AST 0/26, JS/UI y auditorías correctas.
La suite completa anterior permanece en 390 OK/cinco saltos, descrita abajo;
no se repitió sin cambios de código. **Windows nativo sigue pendiente.**

El Motorola se encontró mediante un **cliente nuevo sin IP indicada**, usando
solo descubrimiento Wi-Fi; la API real de búsqueda devolvió HTTP 200 y el receptor.
Antes el puerto del teléfono rechazaba conexiones; con el receptor activo,
HTTPS y descubrimiento respondieron. La IP ingresada se usó únicamente en una
comprobación diagnóstica separada, no como entrada de esa búsqueda independiente.
Lucie Recibir debe permanecer abierta y visible: `onStop` detiene la escucha.
No se enviaron archivos ni se modificó material durante esas comprobaciones.

## Chrome automático desde Python (2026-10-14)

`python3 bandeja_descargas.py` abre Google Chrome cuando el dashboard local
responde; respeta el puerto configurado o `--puerto`. Si ya había una bandeja,
abre su panel sin iniciar otros vigilantes. Un servicio ajeno en ese puerto no
se abre como dashboard. `--sin-navegador` permite iniciar sin apertura automática.
Chrome se busca en PATH y, en Windows, en sus ubicaciones habituales y App Paths.
Si falta o falla el lanzamiento, se informa y la bandeja continúa. El `.bat`
delega esta apertura en Python, evitando dos pestañas y la URL fija previa.

Ocho pruebas cubren Linux, resolución Windows mediante mocks, servidor temporal
iniciando/listo, puerto ocupado por otro servicio, ausencia/error de Chrome,
puerto efectivo, instancia existente y modo sin navegador. Ninguna abre un
navegador real como fixture. Suite final del lote CSRF + Chrome en Kali/Python
3.13.12: **390 tests OK, cinco saltos Windows**, 53.519 s; manifiesto contado
**290 / 290**, estable. Log externo: `/tmp/tests_csrf_chrome_dashboard_final.log`.
AST 0 infracciones/26 módulos; JS/UI y auditoría repo/historial correctas.
Windows nativo de este lote no ejecutado. El usuario autorizó expresamente el
commit y push de ambas mejoras en `feat/lucie-recibir`.

## Token del dashboard después de reiniciar la bandeja (2026-10-14)

Una pestaña abierta conservaba el token CSRF anterior al reinicio: los GET
funcionaban, pero «Empezar capítulo» y otras acciones recibían 403. El panel
obtiene ahora el token vigente de un metadato del HTML local sin caché antes de
cada POST, también en los ocho flujos directos de Edición/CapCut. No se ejecuta
el HTML obtenido ni se inserta en la página; las peticiones POST y de renovación
usan el mismo origen y rechazan redirecciones. Si falla renovar, no se envía
la acción. Nunca se reintenta automáticamente un POST fallido o incierto.
La validación CSRF/Host del servidor se conserva.

Kali/Python 3.13.12: **382 tests OK, cinco saltos Windows**, 51.684 s; manifiesto
solo contado antes/después: **285 / 285**, estable. Log fuera de Git:
`/tmp/tests_csrf_dashboard_final.log`. Regresión Node/HTTP en temporales:
token anterior rechazado, token vigente crea un único capítulo; fallos de
renovación, HTTP/red sin reenvíos y nombre del formulario conservado. AST 0/25,
sintaxis JS, UI Wi-Fi y auditoría de repo/historial correctas. No se creó un
capítulo real como fixture ni se ejecutó Windows nativo. Tras la suite se dejó
la bandeja disponible para uso normal. **Recargar con Ctrl+F5** para cargar el
panel corregido. El usuario autorizó commit/push junto con la apertura automática
de Chrome, descrita arriba, en `feat/lucie-recibir`.

## Publicados separados por personaje (2026-10-14)

El usuario confirmó un envío real al Motorola y pidió corregir la ubicación
posterior. La causa era el cálculo del destino: solo retiraba el nivel Sin
publicar y un nombre numérico sin sesión quedaba sin personaje. Ahora se archiva
en **videos completos/videosPublicados/lucie, roli o mailen**, conservando carpetas
de capítulo y nombre. Una tarjeta Sin asignar exige elegir personaje antes de
simular; el filtro no asigna. El plan y el registro incluyen el personaje.

La tarjeta **Organizar completos anteriores** permite seleccionar carpetas
pendientes o publicados confirmados, revisar destinos y confirmar el grupo.
No se ejecuta al iniciar/listar. Verifica estructura/hash, identidad, ausencia de
enlaces y destinos libres; usa traslado sin reemplazo. Actualiza las rutas
locales de sesiones/exports y el historial de publicación. Deshacer organización
conserva el contenido y rechaza colisiones o contenido nuevo/cambiado. La lectura
puede recuperar un traslado con registro final interrumpido, sin mover nada.
Los conteos de Edición reconocen Sin publicar y videosPublicados.

Reorganización real solicitada: se simuló y aplicó el grupo explícitamente
indicado por el usuario, con las carpetas/rutas históricas intactas. El publicado
numérico fue a videosPublicados/roli; las dos carpetas históricas de Lucie/Roli
fueron a Sin publicar. Resultado: ocho pendientes, un publicado y tres traslados
con registro y Deshacer. Cinco archivos verificados, sin borrado/fusión/overwrite.
La auditoría encontró un duplicado exacto; ambas copias se conservan. Plan y
resultado generados quedaron en el temporal del sistema, fuera de Git. No se
sincronizaron bases/configuraciones de otros equipos ni se reenviaron archivos.

Validación **Kali/Python 3.13.12: 381 tests OK, cinco saltos Windows**, 51.132 s.
Manifiesto solo leído para el control de suite: **279 / 279 líneas**, estable.
La organización real se realizó después de ese control y añadió sus registros
append-only autorizados; no se usó el pendrive como fixture. Log externo:
`/tmp/tests_publicados_personaje_381.log`. AST **0 infracciones en 25 módulos**;
sintaxis JS y test UI (13 llamadas simuladas) OK. Trece tests de organización
cubren personajes, fechas, confirmación/CSRF, colisiones, cambios, enlaces,
actualización de rutas, recuperación, deshacer e IDs de archivos tras remontar.
Windows nativo de este lote no se ejecutó.

Código y documentación en `feat/lucie-recibir`; el usuario autorizó expresamente
el commit y push de este lote el 2026-10-14. Ver [uso y organización](docs/publicacion-wifi.md).

## Corrección de puertos y pantalla Android (2026-10-13)

La versión 0.1.0 instalada en el Moto G54 5G / Android 15 mostraba fallo de
apertura mientras LocalSend ocupaba 53317. La versión **0.2.0** separa HTTPS
**TCP 53318** y descubrimiento **UDP 53319**. El dashboard usa 53318 por defecto,
socket UDP temporal y búsquedas multicast/broadcast propias. La app responde por
unicast al origen. LocalSend puede conservar TCP/UDP 53317. Los receptores de una
misma IP se guardan por IP/puerto, evitando ocultar Lucie con LocalSend.

La pantalla usa tarjetas de conexión, solicitud e historial, estado visible,
identidad HTTPS desplegable y controles secundarios. Se mantienen aceptación,
PIN, comprobaciones y resguardos; no se sustituyen por aceptación automática.

Validación Android: build/lint, cuatro JVM y **cuatro instrumentadas OK**. La nueva
prueba ocupa TCP/UDP 53317 y demuestra que Lucie escucha TCP 53318 y responde al
puerto temporal del solicitante desde UDP 53319. Artemis comprobó la pantalla y
el flujo HTTPS real del emulador con video/foto, cancelación, segundo envío,
homónimo, PIN/rechazo, hash, huella y archivado/Deshacer. Logs externos en
`/tmp/lucie_android_puertos_build.log`, `/tmp/lucie_android_puertos_native.log` y
`/tmp/lucie_puertos_artemis.log`. Las pruebas no usan material real.

Suite Kali/Python 3.13.12: **368 tests OK, cinco saltos Windows**, en 50.931 s.
Manifiesto real contado antes/después: **no disponible / no disponible**; no son
recuentos cero. Log externo: `/tmp/tests_puertos_suite_final.log`.
AST: 0 infracciones en 24 módulos; test JS/UI OK. **0.2.0 instalada por USB en
Moto G54 5G / Android 15**, conservando los datos de la app. Artemis comprobó la
pantalla real con «Listo para recibir por Wi-Fi». La PC se conectó por HTTPS a
53318 y el descubrimiento automático encontró el Motorola en la red real.
`POST /api/publicacion/buscar` devolvió HTTP 200 y Lucie Recibir mediante un servidor
API aislado con configuración temporal, sin iniciar la bandeja real ni sus
vigilantes. Se verificaron identidad y metadatos; no se enviaron archivos al
MediaStore del teléfono como fixture. El proceso de LocalSend puede ejecutarse
mientras Lucie responde en su puerto propio; la ocupación simultánea de TCP/UDP
53317 está además cubierta por la prueba nativa en emulador.

Quedan pendientes archivos/galería y casos de desconexión/espacio lleno en el
Motorola físico, y Windows nativo. Para usarlo, reiniciar la bandeja normalmente
y recargar el dashboard con Ctrl+F5. Publicado en `feat/lucie-recibir`, implementación
`990f32e`; código, configuración reproducible y documentación, sin APKs/datos locales.

## Validación de la entrega en Kali (2026-10-12)

Se descargó e integró `8cce55e` de `origin/actualizacion-completa-host`
mediante fast-forward, conservando las mejoras anteriores y sin modificar
`master`. Python 3.13.12 en Kali/Linux: **361 pruebas, OK, 5 saltadas**,
en 48.369 segundos. Log externo: `/tmp/tests_host_publicacion_8cce55e.log`.
Las pruebas usan temporales y la guardia hermética; no se inició la bandeja
real para validarlas ni se enviaron archivos a un teléfono físico.

`node --check` de `panel.js` y `wifi.js` y `node test_publicacion_ui.js`
pasaron: grupos, imágenes/video, rutas, filtros, selección visible,
invalidación, envío e historial, con nueve llamadas simuladas. AST:
**0 infracciones en 24 archivos**. Auditoría de repositorio e historial:
**0 infracciones**. Manifiesto real antes/después: **no disponible / no
disponible**, no son recuentos cero. La configuración y SQLite de cada
equipo permanecen locales. Para cargar el nuevo servidor y la interfaz,
reiniciar la bandeja para uso real y recargar con Ctrl+F5.

Esta guía describe el comportamiento implementado y complementa las siete
Reglas de Oro de `openspec/config.yaml`. Para edición y CapCut, prevalece sobre
las rutas y decisiones anteriores de los documentos históricos de OpenSpec.

## Emisor corregido y Lucie Recibir Android (2026-10-12)

El usuario autorizó implementar el plan, utilizar Artemis y hacer commit/push
de este lote en **`feat/lucie-recibir`**, desde `8cce55e`, sin modificar master.
Fetch no encontró novedades entrantes. Para actualizar otros equipos, usar esta
rama y comprobar su referencia remota.
Guía de instalación, módulos y pruebas: [Android](android/README.md).

El emisor interrumpe conexiones al cancelar incluso esperando aceptación,
comprueba la cancelación de su sessionId y expone etapa/HTTP/duración sin secretos.
Un 409 previo al ID no cancela sesiones ajenas; una preparación 204 no confirma
recepción. El dashboard informa fases y muestra la huella HTTPS para comparar.
El descubrimiento escucha respuestas multicast UDP además de registros HTTP.
No hay reenvío automático cuando el resultado de la recepción es incierto.

APK Kotlin 0.1.0 para Android 10+, visible durante el envío: HTTPS con identidad
estable AndroidKeyStore, aprobación/PIN, tokens y cancelación por propietario,
video/foto/MP3, espacio, SHA-256, homónimos y MediaStore pendiente→visible.
Cada recepción conserva además un resguardo privado sin limpieza automática:
MediaStore puede expirar entradas pendientes, por lo que el resguardo independiente
preserva los bytes. Se reserva espacio para ambas copias. La cola actual de
publicación del dashboard sigue ofreciendo videos y fotos.

Validación final **Kali/Linux, Python 3.13.12: 367 pruebas OK, cinco saltadas**,
en **50.607 s**. Las cinco requieren capacidades Windows: exclusividad socket,
bloqueo exclusivo, compartición de escritor, export en escritura y finalización
con clip abierto. Se conservaron decoradores/motivos y aserciones. Manifiesto real
antes/después: **no disponible / no disponible**; no son recuentos cero.
La bandeja real del repositorio se detuvo ordenadamente antes de la suite;
las pruebas usan la guardia hermética y temporales, sin material real.
Log externo: `/tmp/tests_lucie_recibir_final.log`.

Android: build, lint, firma APK y **cuatro JVM + tres instrumentadas OK**, emulador
Android 17. Artemis oficial (revisión `351ca8422f7b5b54e80a9c1ce03a222e02415b6b`)
observó la UI y aceptó/canceló solicitudes. Se transfirieron bytes reales por
HTTPS y verificaron MediaStore visible, cancelación en preparación/upload,
segundo envío, homónimos, PIN/rechazo, huella falsa, hash corrupto y resguardo
privado. El gestor aislado envió video/foto, archivó tras ACK y deshizo conservando
bytes. Script reproducible: `android/tests/verificar_receptor.py`, limitado a
emuladores. Logs en `/tmp/lucie_android_resguardo_final.log` y
`/tmp/lucie_artemis_apk_final.log`, fuera de Git.

AST **0 infracciones / 24 módulos Python**; sintaxis JS y test UI (nueve llamadas)
OK; auditoría rastreados/historial y archivos nuevos sin infracciones. El análisis
AST no audita Kotlin: el código Android y las pruebas nativas se revisaron por
separado. APK, builds, SDK local, logs y claves de firma no se versionan.

**Pendiente:** Motorola físico (modelo/versión/conexión), Wi-Fi/multicast y galería
reales, archivo grande, desconexión, espacio lleno, comparación con LocalSend
oficial y suite Windows nativa de este lote. ADB al emulador no prueba Wi-Fi real.
No se atribuye el 409 histórico a una causa específica sin evidencia del teléfono.
Continuidad en [seguimiento del plan](docs/plan-receptor-android.md).

El cierre anterior quedó detenido: la suite dio **361 pruebas OK, 10 saltadas**, en
**56.844 segundos**, pero el
manifiesto real cambió **271 → 273** líneas y se detuvo la validación/publicación.
Log: `%TEMP%/tests_entrega_windows_kali_final.log`. No se atribuyó ese cambio
a las pruebas ni a la bandeja sin evidencia. Ese control se repitió y pasó;
ver la revalidación siguiente. Esa entrega Windows no validaba Linux; la
validación Kali está al inicio de esta guía. El teléfono físico sigue pendiente.

## Entrega revalidada para GitHub y Kali (2026-10-12)

La rama de esta entrega es **`actualizacion-completa-host`**, con los cambios
de nombres, cola Sin publicar, galería por personaje, emisor Wi-Fi y documentación
de continuidad. No se integró ni modificó master. El commit y push fueron
autorizados expresamente por el usuario; no hace falta volver a pedirlos para
este mismo lote anterior. En esa entrega el APK Android era un plan; la
continuación implementada se describe al inicio y cuenta con autorización
propia del usuario para commit/push.

Revalidación Windows/Python 3.13: **361 pruebas, OK, 10 saltadas**, en
**61.461 segundos**. Manifiesto real solo contado antes/después: **276 / 276**
líneas; el control que detenía el cierre quedó satisfecho. Log externo al repo:
`%TEMP%/tests_publicacion_github_final.log`. Las omisiones conservan los motivos
documentados: cinco requieren Linux y cinco privilegios para symlinks.
AST: **0 infracciones en 24 archivos operativos**; sintaxis de ambos scripts JS,
`node test_publicacion_ui.js` y auditorías de repo/historial correctas.

Los tests de `test_traslado_atomico.py` comprueban traslado y colisión nativos
en Windows y el contrato `renameat2(RENAME_NOREPLACE)` mediante mocks. No equivalen
a ejecutar Kali. Para continuar allí, leer README_KALI.md y ejecutar la suite
nativa con temporales y recuento del manifiesto. Bases, configuraciones locales,
material, logs, APKs y claves de firma no forman parte del commit.

## Actualización completa del dashboard (2026-10-11)

Se integró la actualización de GitHub `931febd` conservando las mejoras de
edición, CapCut y reproducción de esta rama. «Eliminar capítulos» permite
seleccionar archivos o carpetas del pendrive, revisar la simulación y escribir
`ELIMINAR` para confirmar un borrado permanente sin deshacer. Esta excepción
manual fue autorizada expresamente por el usuario; el borrado automático sigue
prohibido. Se conservan confinamiento, protección de metadatos, verificación
de identidad y contenido y bitácora append-only separada del manifiesto.

La actualización incluye vistas previas y audio MP3 en lotes y transferencias.
Ver [Eliminación manual y audio MP3](docs/dashboard-eliminacion-y-mp3.md).

Validación de esta integración en Windows/Python 3.13: **304 pruebas, OK,
10 saltadas** (cinco requieren Linux y cinco privilegios para symlinks), en
41.723 segundos. AST: 0 infracciones en 22 archivos; JavaScript y auditoría
de repositorio/historial correctos. Manifiesto real antes/después: **84 / 84**
líneas, solo lectura. Log: `%TEMP%/tests_host_actualizado.log`. No se inició
la bandeja real para probar ni se validó Linux en este equipo.

## Estructura del material

La nueva cola es `videos completos/videos sin publicar/`: se guardan allí los
exports nuevos y los pendientes sin sesión inequívoca. Los vinculados conservan
personaje/edición; los no vinculados se guardan por nombre con sufijo de versión
si es necesario. La recepción confirmada mediante LocalSend desde el dashboard
es la señal autorizada para retirar ese nivel y conservar el video en
`videos completos/`, con registro, actualización de rutas y Deshacer.
No se afirma publicación en Instagram ni se reorganizan completos históricos.
Ver [Publicación y Wi-Fi](docs/publicacion-wifi.md).

Cambio de nombres autorizado para **nuevas carpetas de videos ya editados**:
`videos ya editados/<personaje>/videoyaeditado_<nombre>_semana_<del mes>_<mes>_<año>/`.
Por ejemplo: `videoyaeditado_lucieinvitacafe_semana_2_octubre_2026`.
El nombre base no conserva el sufijo generado `videocompleto`; sus espacios se
separan con guiones bajos. Las carpetas de videos completos y capítulos mantienen
su formato vigente. Rutas existentes no se renombran: el manifiesto las conserva
para reintentos y deshacer, aunque cambie el mes o la regla de nombres.

```text
LucieSinReglas/
  videos sin editar/<personaje>/<capitulo>/<clip.mp4>
  videos ya editados/<personaje>/videoyaeditado_<nombre>_semana_2_octubre_2026/<clip.mp4>
  videos completos/videos sin publicar/<personaje>/<nombre - lunes - semana 2 - octubre - 2026>/<video.mp4>
  videos completos/<personaje>/<nombre - lunes - semana 2 - octubre - 2026>/<video.mp4>
  .lucie/manifiesto.jsonl
  _revertidos/
```

El personaje sigue siendo el nivel contenedor para exports asociados. Se usa
el reloj local y la semana del mes por bloques de días. Todos los clips de una
edición quedan directamente dentro de su carpeta, sin niveles adicionales de
semana ni subcarpetas de capítulo. Los completos sin sesión se resguardan
directamente en la cola. Al publicar se retira solo el nivel `videos sin publicar`.

Los archivos anteriores no se migran ni se reorganizan automáticamente. Los
destinos ocupados se rechazan. Las rutas efectivas del manifiesto permiten
reintentos, contadores y deshacer aunque cambie el mes. La ruta del video completo
registrada en SQLite evita volver a copiar una misma sesión en otro mes.

## Flujo de edición y CapCut

Cuando CapCut reutiliza un nombre de export, el vigilante detecta cambios en
tamaño, fechas e identidad del archivo y reinicia su estabilidad. La misma ruta
puede tener distintas versiones registradas por tamaño y mtime, sin sustituir
estados, asociaciones o hashes anteriores. La migración conserva íntegra la
tabla anterior como `exports_pendientes_historial_ruta`, además de copiar los
IDs a la tabla de versiones. Si una ruta ya registrada cambió mientras la
bandeja estaba cerrada, su nueva versión se detecta después del reinicio;
otros archivos históricos desconocidos siguen excluidos por la fotografía inicial.
El panel marca originales reemplazados y no permite enviarlos ni reproducir
otra versión mediante su ID histórico. Los reintentos también verifican la versión.
La asociación automática prioriza una única sesión `en_edicion` pendiente
sobre sesiones `editado` antiguas. Si hay varias `en_edicion`, exige elección
manual. Sin sesiones en edición, permite asociación automática solo si queda
una única sesión editada pendiente. El sondeo en modo automático puede retomar
un export `sin_asignar` si es el único vigente generado desde el inicio de la
única sesión en edición; no asocia históricos ni elige entre varios exports.

1. En **Edición**, seleccionar crudos y crear una sesión con su nombre.
   En Windows, confirmar la creación abre el Explorador en la carpeta del
   capítulo seleccionado (videos, o audios si la sesión solo tiene MP3).
   La petición de creación incluye `abrir_carpeta=true`; el servidor calcula
   la carpeta desde la sesión y el pendrive vinculado, verifica confinamiento
   y rechaza rutas a través de enlaces/junctions. No admite una ruta libre
   del navegador. Un error de apertura no deshace la sesión creada y se informa
   en `error_abrir_carpeta`. Otros sistemas no lanzan el Explorador.
   La lista **Para editar** agrupa por personaje y capítulo con un tilde para
   seleccionar o desmarcar el capítulo completo, incluidos archivos ocultos
   por la búsqueda. Crear una sesión exige seleccionar un solo personaje y
   capítulo para evitar mezclar capítulos con «Todos». Los MP3 aparecen tanto
   dentro de crudos como en `audios/<personaje>/<capítulo>/`, con tipo audio y
   vista previa. Pueden sumarse a una sesión existente; al finalizar se agrupan
   con los videos en la carpeta de la edición, y deshacer restaura su ruta de
   audio original. Sus IDs usan `audios/` como prefijo para evitar colisiones
   con los IDs históricos de video.
2. «Terminé de editar» agrupa los crudos en `videos ya editados`. La sesión
   puede recibir el export tanto en estado `en_edicion` como `editado`.
   Si Windows impide renombrar un clip abierto (WinError 32/33), se crea una
   copia exclusiva `.part`, se sincroniza y se verifican los hashes de copia y
   original antes de publicar el destino. El original queda conservado y se
   registra `original_preservado` en manifiesto y bitácora. No reaparece como
   crudo pendiente después de cerrar la sesión. Deshacer preserva esa copia en
   `_revertidos` si el original aún existe y coincide; si cambió, rechaza la
   reversión sin sobrescribir. Las copias fallidas quedan en `_a_revisar` con
   registro. Un bloqueo que también impida leer no puede evitarse: se informa
   el conflicto y no se cierra la sesión. No se elimina el original al cerrar CapCut.
   Un export enviado antes del cierre no oculta la sesión: permanece visible
   como **Export enviado · Crudos pendientes** hasta finalizar el tratamiento
   de los crudos. Al cerrar se conserva su estado completado y destino final.
   Para incorporar un clip faltante a una sesión en curso, seleccionarlo en
   **Para editar** y pulsar **Sumar video** en la sesión deseada. Se revisa la
   lista antes de confirmar. Se conservan nombre, clips anteriores y ubicación
   de archivos; los nuevos clips se incluyen al terminar la edición. Solo se
   admiten videos existentes del mismo personaje, sin enlaces ni rutas fuera
   de crudos, y que no pertenezcan a otra sesión activa. Repetir no duplica clips.
   Junto a la lista de crudos, **Sumar seleccionados a** permite elegir la sesión
   existente y pulsar **Sumar video**. La confirmación muestra su nombre.
   **Crear nueva sesión** abre una edición separada. Si un clip se incorporó por
   error a una sesión nueva, cancelar esa sesión lo devuelve a Para editar sin
   mover ni borrar archivos; luego puede sumarse a la sesión original.
   En Lotes detectados, el selector de escena incluye **En edición** con el
   personaje y capítulo de las sesiones activas, aunque su carpeta ya no esté en
   la sala de espera. Seleccionarlo ajusta el personaje del lote. El envío sigue
   pasando por simulación y aprobación; después se suma el clip desde Edición.
   La detección de duplicados recalcula el hash cuando cambia la identidad,
   tamaño o fechas del archivo; no reutiliza ciegamente el hash histórico de su
   ruta. Una copia con bytes idénticos sigue marcada como duplicada.
   «Terminé de editar» comprueba todos los orígenes y destinos antes de iniciar
   traslados. Si falta un clip o hay un destino conflictivo, no traslada nuevos
   archivos y conserva la sesión abierta. El panel identifica los clips que
   requieren recuperar su origen. Los traslados de intentos anteriores se
   reconocen por el manifiesto; no se omiten referencias faltantes sin decisión
   del usuario. Cambios del disco posteriores a la comprobación pueden aún
   interrumpir una operación iniciada: no se garantiza atomicidad del lote.
3. El vigilante de CapCut, iniciado junto con la bandeja, busca nuevos `.mp4`
   y `.mov`, también en subcarpetas hasta profundidad 3. Acepta nombres numéricos
   como `0818(15).mp4`. Ignora archivos preexistentes en su fotografía inicial,
   temporales y enlaces simbólicos; exige estabilidad y disponibilidad del archivo.
4. Si una sola sesión en edición espera un export, la prioriza frente a sesiones
   editadas antiguas. Con varias en edición exige elección. Si no hay ninguna
   en edición, asocia solo si hay una única editada pendiente; no adivina entre varias.
5. En modo automático copia al pendrive vinculado con el nombre de la sesión,
   sin alterar el export original de CapCut. Comprueba exclusividad, colisiones
   e integridad SHA-256 y registra la operación. Un pendrive desconectado deja
   el envío pendiente; los sondeos retoman pendientes al reconectar.
6. **Videos completados** muestra reproductor del export original, nombre de
   sesión, estado, errores y destino. Permite elegir sesión, enviar, descartar
   de la lista y deshacer. Descartar de la lista no elimina el archivo.

`envio_exports_capcut` acepta `automatico` (predeterminado) o `manual` en la
configuración local. En modo manual la asociación puede ser automática pero
la copia espera «Enviar al pendrive». Es independiente de `al_exportar`, que
controla el tratamiento de los crudos. El envío automático corresponde a la
autorización expresa del usuario para este flujo; no autoriza otras operaciones.

Deshacer un envío conserva el video en `_revertidos`, limpia la ruta completa
de la sesión y deja el export disponible para un nuevo envío explícito. No lo
vuelve a copiar automáticamente. Deshacer crudos restaura sus rutas originales
si están libres; no elimina carpetas vacías.

## Mapa del código y API

| Archivo | Responsabilidad |
| --- | --- |
| `bandeja_descargas.py` | Arranque/parada de vigilantes y callbacks de asociación y reintentos |
| `bandeja/capcut.py` | Fotografía inicial, sondeo recursivo, estabilidad y exclusividad |
| `bandeja/edicion.py` | Sesiones, nombres de carpetas, copia, traslado, manifiesto y deshacer |
| `bandeja/db.py` | Persistencia local; registro idempotente de exports sin reemplazar su historia |
| `bandeja/config.py` | Configuración de carpeta de CapCut y modo de envío |
| `bandeja/plataforma.py` | APIs Windows y rama POSIX de exclusividad |
| `bandeja/vigilante.py` | Mapa de descargas y registro persistente de identificadores del visor |
| `bandeja/servidor.py` | API, CSRF, confinamiento y streaming con rangos |
| `bandeja/web/panel.js` | Edición, Videos completados, reproductores y errores de carga |
| `bandeja/publicacion.py` | Cola sin publicar, planes de envío, historial y reversión |
| `bandeja/localsend.py` | Descubrimiento y emisor LocalSend v2 con integridad y aceptación |
| `bandeja/web/wifi.js` | Selección de videos y celular, revisión, progreso e historial |

`GET /api/edicion/secciones` incluye `videos_completados` y
`sesiones_para_export`, incluso sin pendrive conectado.
`POST /api/edicion/sumar-videos` recibe `sesion_id` entero y `clips` (lista de
rutas relativas a `videos sin editar`); requiere CSRF, pendrive conectado y
sesión `en_edicion` sin video completo. Actualiza solo la base local en una
transacción, sin copiar, mover ni borrar archivos.
`GET /api/capcut/exports` devuelve exports con información de sesión y destino.
`POST /api/capcut/enviar-export` acepta `export_id` y, si falta asociación,
`sesion_id`; comparte el flujo de `/api/capcut/asignar-export`.
Se conservan `/api/capcut/descartar-export`, `/api/capcut/deshacer-completo`
y `/api/capcut/escanear`.
`GET /api/media?id=capcut:<export_id>` sirve únicamente exports registrados,
no descartados y confinados a la carpeta configurada de CapCut.

La base SQLite y la configuración local pertenecen a cada equipo. Nunca se
suben ni se sincronizan entre Linux y Windows.

## Validación de publicación y Wi-Fi (2026-10-12)

Windows/Python 3.13: **353 pruebas, OK, 10 saltadas**, en **55.477 segundos**.
Las diez omisiones conservan los motivos existentes: cinco requieren Linux y
cinco privilegios para enlaces simbólicos. Manifiesto real solo contado antes
y después: **263 / 263** líneas. Log: `%TEMP%/tests_publicacion_wifi_final.log`.

Los nuevos tests ejercitan transferencia HTTP LocalSend a un receptor falso
en loopback, SHA-256, rechazo, aceptación parcial, desconexión, cancelación,
integridad, identidad del pendrive, colisiones, confirmación y token de un uso,
historial recuperable, rutas SQLite y Deshacer. Se comprobaron también el
resguardo automático sin sesión, el modo manual, el bloqueo ante otro envío
y los contadores de capítulos de la nueva cola sin compartir bases entre equipos.
La API conserva CSRF. Las aserciones y la guardia hermética se mantuvieron.

JavaScript: sintaxis de ambos scripts correcta y ejecución con DOM/API
simulados para selección, receptor, revisión, confirmación, progreso, historial
y reversión. AST: **0 infracciones** en **24 archivos operativos**. Auditoría de
archivos rastreados/historial y auditoría explícita de los cinco archivos nuevos:
sin infracciones. No se inició la bandeja real, no se transfirió material real
ni se validaron el teléfono físico, multicast real o Linux desde este equipo.

## Galería de publicación por personaje (2026-10-12)

La sección ofrece tarjetas con fotograma inicial/reproductor para videos e
imagen para fotos, nombre, tamaño y carpeta visible. Un selector separa Lucie,
Roli, Mailen y Sin asignar; la búsqueda filtra por archivo o carpeta. Se reconoce
el personaje por carpeta, sesión que registre la ruta exacta o prefijo explícito
del nombre, indicando esa última pista. Los nombres numéricos sin identificación
se mantienen en Sin asignar. No se mueve ni renombra material al filtrar.

La lista y sus vistas previas excluyen CapCut, crudos, ya editados y completos
fuera de la cola. `publicacion:<id>` en `/api/media` resuelve exclusivamente el
inventario vigente, admite rangos HTTP y deja de resolver después de publicar.
También pueden enviarse y revertirse imágenes de la cola. Cambiar de filtro
limpia selección/plan, «Seleccionar los visibles» afecta únicamente ese filtro
y actualizar elimina selecciones que hayan salido de la vista.

Validación final Windows/Python 3.13: **357 pruebas, OK, 10 saltadas**, en
**57.654 segundos**; mismos motivos de omisión documentados arriba. Manifiesto
real solo contado: **270 / 270** líneas. Log:
`%TEMP%/tests_galeria_publicacion_final.log`. `node test_publicacion_ui.js`
comprueba grupos, imágenes/videos, filtros, selección visible, invalidación,
envío e historial con DOM/API simulados. Sintaxis JS y auditoría AST correctas.

Se inspeccionó el diseño con Chrome headless y datos temporales. Una segunda
prueba con reloj real y video WebM sintetizado en un canvas confirmó decodificación
nativa (`readyState=4`) y fotograma visible en la tarjeta. La primera captura con
reloj virtual no generó fotogramas del fixture; se repitió sin acelerar el reloj.
No se inició la bandeja real ni se usaron videos del usuario; tampoco se validaron
Linux, la transferencia al teléfono físico ni los códecs del material real.

## Causas corregidas

| Causa | Corrección y evidencia |
| --- | --- |
| Un escritor Windows no necesita tomar un bloqueo de bytes `msvcrt` | Apertura de lectura `CreateFileW` sin compartir, cerrada siempre; test temporal comprueba ocupado durante escritura y libre al cerrar. Rama Linux `fcntl.flock` intacta. |
| Pruebas de symlinks suponían que Windows nunca los permite | Se intenta crear el enlace; solo se salta si falta privilegio (`WinError 1314`), con motivo explícito. |
| Fixture de capítulo dependía de resolución temporal del sistema de archivos | Inicio del capítulo un minuto anterior en el fixture; aserciones conservadas y producción intacta. |
| Carpetas de salida con niveles y semana no deseados | Una carpeta por edición con mes/año y videos directamente dentro; compatibilidad con rutas históricas. |
| Exports pendientes y revisión no integrados al arranque y panel | Vigilante activo, asociación no ambigua, reintentos e interfaz Videos completados; registro idempotente. |
| El sondeo de descargas borraba los identificadores del visor de edición | Registro separado `_media_registrada`; regresión HTTP comprueba rangos 206 después de dos sondeos y 403 al desconectar el pendrive. |

El mensaje de formato del navegador podía ocultar un HTTP 404 causado por ese
último defecto. El panel distingue archivo no disponible, pendrive desconectado,
fallo de red y formato no decodificable. No se añadió transcodificación: un códec
que el navegador no admita puede seguir sin reproducirse.

## Validación registrada y límites

Nombre específico de carpetas ya editadas: Windows/Python 3.13, **334 pruebas,
OK, 10 saltadas**, en 47.073 segundos; manifiesto **250 / 250** líneas.
Log `%TEMP%/tests_nombre_ya_editado.log`. Se verificaron semanas del mes,
separadores, eliminación del sufijo de video completo, destinos ocupados,
reintentos y reversión con rutas históricas. AST y auditoría correctos.
No se renombran carpetas reales automáticamente. En esa validación los exports
sin sesión permanecían pendientes; la posterior cola de publicación autoriza
resguardarlos sin asociación ficticia dentro de Videos sin publicar.

Repaso de CapCut, cierre, copia y reversión: Windows/Python 3.13, **333 pruebas,
OK, 10 saltadas**, en 50.333 segundos; manifiesto **248 / 248** líneas.
Log `%TEMP%/tests_capcut_bloqueos_revision.log`. Una prueba Windows nativa
mantiene un lector abierto mientras finaliza por copia, reintenta y deshace;
comprueba hashes y conservación de original/copia. Otras regresiones verifican
preservación de copias corruptas, visibilidad de crudos tras enviar el export,
estado completado al cerrar y reintento del callback del vigilante si falla.
Se ejecutó toda la suite y las auditorías AST, JS y repositorio/historial.
No se inició la aplicación real ni se manipuló material real para probar.
Linux no se ejecutó; sus traslados habituales siguen usando el flujo anterior.

Prioridad de la única sesión en edición para exports: Windows/Python 3.13,
**329 pruebas, OK, 10 saltadas**, en 50.191 segundos; manifiesto **248 / 248**
líneas. Log `%TEMP%/tests_capcut_prioridad.log`. Regresiones verifican prioridad
sobre editadas antiguas, rechazo de varias activas y recuperación de un único
export vigente reciente sin modificar asociaciones históricas. Sintaxis JS,
AST y auditoría correctos. No se inició la bandeja real ni se envió el export
real durante las pruebas; la regla se aplica al reiniciar la aplicación.

Versiones de exports reutilizados de CapCut: Windows/Python 3.13, **327 pruebas,
OK, 10 saltadas**, en 48.377 segundos; manifiesto **248 / 248** líneas.
Log `%TEMP%/tests_capcut_versiones_final.log`. Las regresiones temporales
comprueban reemplazos de históricos y exports detectados, estabilidad de la
nueva versión, recuperación de una ruta registrada tras reinicio y migración
con IDs/historial intactos. Se conservan las aserciones HTTP de rangos y
confinamiento; sus fixtures usan el mtime real del archivo temporal.
Sintaxis JS, AST y auditoría correctos. No se migró la base real ni se copió
material real durante la validación; se aplica la migración al reiniciar la
aplicación. La inspección diagnóstica real solo leyó metadatos y registros.

Apertura de carpeta al crear sesión en Windows/Python 3.13: **323 pruebas,
OK, 10 saltadas**, en 48.153 segundos; manifiesto **246 / 246** líneas.
Log `%TEMP%/tests_abrir_carpeta_edicion_final.log`. Las pruebas usan carpetas
temporales y sustituyen la apertura del Explorador por un mock; validan HTTP,
carpeta correcta, rechazo de escapes y aislamiento de otros sistemas. Sintaxis
JS, AST y auditoría del repositorio correctos. La primera suite tuvo un error
intermitente de conexión WinError 10053 en una prueba de capítulos existente;
esa prueba puntual y la repetición completa pasaron sin cambiar sus aserciones.
No se abrió el Explorador real ni se inició la bandeja real para validar.

Selección por capítulo y MP3 en edición: Windows/Python 3.13, **311 pruebas,
OK, 10 saltadas**, en 47.769 segundos. Manifiesto real: **159 / 159** líneas;
log `%TEMP%/tests_edicion_capitulos_mp3.log`. Prueba temporal de MP3 comprueba
listado, asociación, cierre con video en la misma carpeta y reversión al origen
con sus bytes intactos. Node comprueba selección/desmarcado del capítulo,
inclusión de MP3 ocultos por búsqueda y separación de personajes. Sintaxis JS,
AST y auditoría de repositorio/historial correctos; no se probó la interacción
en un navegador ni Linux. Se integró, con autorización, `f17ae98` de GitHub
(estética del dashboard y manual interno).

Validación de comprobación previa al finalizar: Windows/Python 3.13,
**310 pruebas, OK, 10 saltadas**, en 42.680 segundos. Manifiesto durante la
suite: **101 / 101** líneas; log `%TEMP%/tests_finalizar_faltante.log`.
Regresión temporal confirma que un faltante no permite trasladar otros clips,
no escribe bitácora y conserva la sesión abierta. Sintaxis JS, AST y auditoría
de repositorio/historial correctos. La inspección real en solo lectura fue
autorizada expresamente para diagnosticar el incidente; no forma parte de las
pruebas. No se movió, borró ni restauró material real durante el diagnóstico.

Corrección de descargas para capítulos en edición: **309 pruebas, OK,
10 saltadas**, en Windows/Python 3.13 (45.474 segundos); manifiesto real
**84 / 84** líneas. Log: `%TEMP%/tests_descarga_edicion.log`. Regresiones
temporales verifican que cambiar un archivo en la misma ruta no herede su hash
anterior y que una sesión activa ofrezca su capítulo sin carpeta de espera.
Node verificó la opción En edición con el personaje correcto; sintaxis JS,
AST y auditoría de repositorio/historial correctos. No se inspeccionó el video
real reportado ni se probó la interacción en navegador o Linux.

Validación de «Sumar video» en Windows/Python 3.13: **307 pruebas, OK,
10 saltadas**, en 43.418 segundos; saltos por interfaces Linux y privilegios
de symlinks ausentes. Manifiesto real: **84 / 84** líneas antes/después.
Log temporal: `%TEMP%/tests_sumar_video.log`. Se verificaron adición persistente,
ausencia de duplicados, finalización con todos los clips y rechazo de lotes
ocupados, rutas inválidas, otro personaje y sesiones cerradas. Node comprobó
selección vacía, cancelación, errores y confirmación del botón; sintaxis JS,
AST y auditoría del repositorio/historial correctos. No se inició la bandeja
real ni se probó esta interacción en un navegador o en Linux.

Suite anterior del visor: Python 3.13 en Windows, **286 pruebas,
OK, 9 saltadas**, en 45.693 segundos. Cinco saltadas corresponden a interfaces
Linux y cuatro a falta de privilegios reales para symlinks. Los tests exclusivos
de Windows se saltan en Linux con motivo explícito. Linux no se ejecutó en esta
máquina; no se declara una validación Linux nueva.

AST: **0 infracciones** en 21 archivos operativos. JavaScript: `node --check`
correcto. Manifiesto real antes/después de la última suite: **54 / 54** líneas,
contadas solo leyendo. Log fuera del repositorio:
`%TEMP%/tests_visor_edicion_final.log`.

Hubo ejecuciones previas con fallos intermitentes de tiempos y conexiones
Windows (`WinError 10053`); las pruebas puntuales y la repetición completa
pasaron. No se afirma haber eliminado todos los fallos intermitentes.
La regresión del visor se probó con archivos temporales y HTTP; no se inspeccionó
ni modificó el material real ni se verificaron sus códecs.

Para una nueva validación Windows:

```powershell
py -3 -m unittest discover -s . -p 'test_*.py'
py -3 seguridad_anti_borrado.py .
node --check bandeja/web/panel.js
py -3 auditar_repo.py --historial
```

Antes y después de la suite, contar en solo lectura el manifiesto del pendrive
vinculado, si existe; detenerse si cambia. Guardar logs en el directorio temporal
del sistema. Usar solo `tempfile` para fixtures; no iniciar la aplicación real
para verificar cambios. Tras actualizar la aplicación, el usuario debe
reiniciarla y recargar el navegador con `Ctrl+F5`.


## Nombres documentados de carpetas nuevas (2026-10-12)

La instrucción vigente para carpetas nuevas es:
`<nombre del video o capítulo> - <día de la semana> - semana <del mes> - <mes> - <año>`.
Por ejemplo: `oloraculo - lunes - semana 2 - octubre - 2026`.
La semana del mes se calcula por bloques de días: 1–7, 8–14, 15–21, 22–28 y 29–31.
Se usa el reloj local, nombres españoles y una sola carpeta, sin niveles de semana.
El dashboard aplica el formato al iniciar capítulos y simular nuevas escenas;
Las salidas de completos usan también ese formato; las nuevas carpetas de
`videos ya editados` usan la excepción `videoyaeditado_...` indicada arriba.
Esta regla sustituye el anterior sufijo de solo mes y año. Las carpetas y rutas
históricas no se renombran ni migran automáticamente. Reintentos y deshacer usan
las rutas registradas. La nueva excepción de limpieza solo retira directorios
vacíos de capítulos enviados; los originales siguen conservados en `_enviados`.
