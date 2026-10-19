# Guía para próximas sesiones

Leer primero [ESTADO_ACTUAL.md](ESTADO_ACTUAL.md), [README.md](README.md)
y, en Windows, [README_WINDOWS.md](README_WINDOWS.md).
En Kali/Linux, leer también [README_KALI.md](README_KALI.md): rama de entrega,
configuración por equipo, pruebas nativas pendientes y continuidad.
La constitución del sistema son las siete Reglas de Oro de
[openspec/config.yaml](openspec/config.yaml); siguen obligatorias.
Para retomar el envío Wi-Fi y Lucie Recibir para Android, leer
[docs/plan-receptor-android.md](docs/plan-receptor-android.md) y
[android/README.md](android/README.md). El usuario autorizó la implementación,
el uso de Artemis y el commit/push de este lote. La continuación está en
`feat/lucie-recibir`, desde `actualizacion-completa-host`; no volver a pedir
conformidad para lo ya autorizado. Ver evidencia y límites de validación en
ESTADO_ACTUAL.md. Los nuevos lotes siguen sujetos a la regla de publicación.

- No borrar automáticamente ni sobrescribir material. La eliminación manual
  desde «Eliminar capítulos» del dashboard está autorizada exclusivamente con
  selección del usuario, simulación previa y confirmación explícita; es permanente
  y no permite deshacer. Fuera de ese flujo, el borrado sigue prohibido.
  Toda copia debe respetar colisiones,
  comprobar integridad y permitir deshacer sin eliminar archivos.
- Pruebas exclusivamente en directorios temporales. No tocar Descargas reales,
  la carpeta real de CapCut ni el pendrive. Para la suite, la única lectura
  real autorizada del pendrive es contar las líneas de su manifiesto antes y
  después; si cambian, detenerse y avisar.
- No iniciar la bandeja real para probar: sus vigilantes pueden copiar material.
- Conservar la guardia hermética y todas las aserciones. Saltar pruebas solo
  por una capacidad realmente ausente y documentar el motivo.
- Preservar Linux al corregir Windows; no afirmar validación de un SO no ejecutado.
- No modificar `master` en esta línea de trabajo. Usar una rama de trabajo y
  subirla cuando el usuario lo autorice; no versionar bases, configuraciones
  locales, exports, logs ni informes generados.

La estructura de nuevas salidas de video, imágenes y audio (2026-10-19) es
`<categoria>/<personaje>/<mes - año>/<nombre - día - semana del mes - mes - año>/`.
Completos conserva primero `videos sin publicar` o `videosPublicados`, luego
personaje/mes/capítulo. «Videos en edición» se refiere a videos sin editar.
Excepción vigente para nuevas salidas en `videos ya editados` (2026-10-12):
`<personaje>/<mes - año>/videoyaeditado_<nombre del video>_semana_<del mes>_<mes>_<año>/`.
Se elimina del nombre base el sufijo `videocompleto` o `video completo` si existe;
se usan guiones bajos como separadores. Las salidas de `videos completos` y los
capítulos conservan su formato vigente; no renombrar rutas históricas automáticamente.
Los videos quedan directamente dentro de su carpeta de salida, sin niveles
adicionales de semana ni subcarpetas de capítulo.
Corrección de títulos (2026-10-15): conservar espacios, acentos y mayúsculas en
las sugerencias de edición y en nuevos completos. Quitar del título base los
sufijos generados `videocompleto` y día/semana/mes/año heredados, también si
quedaron pegados; la carpeta agrega la fecha vigente una sola vez y el archivo
usa `<título>.mp4` (o `.mov` cuando corresponde). Ya editados conserva su formato
`videoyaeditado_...`. Recuperar espacios de títulos antiguos solo a partir de un
capítulo o clip con el mismo título legible, sin adivinar palabras. No renombrar
material existente; reintentos y Deshacer respetan las rutas registradas.
CapCut conserva sus originales. Ver el mapa de módulos, API, estados, modo manual,
reintentos, reversión y validaciones en `ESTADO_ACTUAL.md`.

Retiro de crudos retenidos (2026-10-19): Terminé de editar registra el retiro
pendiente cuando Windows obliga a copiar un clip en uso. Tras liberarse, verificar
origen/copia por SHA-256, resguardar el original redundante en `_enviados/edicion`
sin sobrescribir y retirar solo sus padres vacíos, después de registrar. Mantener
Deshacer y las rutas históricas. El sondeo solo procesa solicitudes explícitas
registradas; los históricos sin indicador requieren Completar traslado y confirmar
su plan. Listar no mueve archivos. No cerrar CapCut ni forzar sus bloqueos.

Inicio Windows (2026-10-17): el usuario solicitó habilitar el inicio de Lucie al
entrar a su sesión, en segundo plano con icono junto al reloj. El acceso de Inicio
es local al equipo; `instalar_inicio_windows.ps1` simula antes de instalarlo sin
pisar accesos ajenos. Ver README_WINDOWS.md. No iniciar la bandeja real como
fixture: las pruebas del icono usan callbacks falsos y el instalador solo carpetas
temporales. Una bandeja existente puede recibir el icono sin nuevos vigilantes.

## Cola de publicación y Wi-Fi (2026-10-12)

Interfaz y receptor (2026-10-17): Preparar envío, Enviados y Organizar anteriores
son vistas separadas. El envío exige elegir archivos, app/celular, revisar y
confirmar. Lucie Recibir es la opción inicial; no sustituirla silenciosamente
por LocalSend. Cambiar app o destino invalida revisiones, incluso las pendientes
de respuesta. La búsqueda usa interfaces actuales y un respaldo local acotado
solo a TCP 53318 para Lucie; no cambia firewall/router ni envía archivos al buscar.

Al confirmar «Terminé de editar» (corrección 2026-10-14), además de organizar
los clips, revisar el único export vigente de esa sesión y copiarlo a la cola
en modo automático. Si falta o sigue escribiéndose, mantener visible la sesión
terminada pendiente del video final, con «Revisar video final». Una revisión
puede recuperar un export preexistente al arranque solo dentro de la ventana
de esa sesión confirmada; exigir estabilidad y exclusividad. Varios exports
o ventanas de sesiones superpuestas requieren elección explícita. Conservar
el modo manual, versiones históricas ajenas y el bloqueo de reenvío tras Deshacer.
La recuperación tras reiniciar solo se habilita con `revision_export_solicitada`,
registrada al terminar o revisar explícitamente la sesión. Las sesiones anteriores
a esta corrección conservan ese indicador desactivado; usar «Revisar video final».

Los nuevos completos se guardan en `videos completos/videos sin publicar/`.
Los asociados conservan personaje/edición; los exports sin sesión inequívoca
se resguardan por nombre/versionado, sin adivinar una sesión. No reorganizar
videos anteriores automáticamente. El modo manual y Deshacer siguen vigentes.
El usuario autoriza usar una recepción Wi-Fi confirmada como señal de publicación:
se traslada a `videos completos/videosPublicados/<personaje>/`, después de aceptación e integridad,
con simulación, confirmación, registro y reversión. Esto no comprueba publicaciones
en Instagram. No borrar ni sobrescribir archivos, ni marcar publicados envíos
rechazados, incompletos o con checksum fallido. Ver [Publicación y Wi-Fi](docs/publicacion-wifi.md).
La galería lee exclusivamente esa cola, admite videos/fotos y separa Lucie,
Roli, Mailen y Sin asignar. Usar carpeta conocida, sesión con ruta exacta o
prefijo explícito del nombre (indicarlo como pista); no adivinar el personaje
de nombres numéricos. El filtro no mueve ni renombra material. Cambiar de
personaje/búsqueda limpia selección y revisión; seleccionar todos afecta solo
los archivos visibles. Las vistas previas resuelven IDs del inventario vigente.

## Revisión de GitHub al iniciar cada sesión

- Tras leer las guías iniciales, revisar `git status`, la rama actual y los
  remotos. Ejecutar `git fetch origin` para comprobar novedades de GitHub sin
  modificar los archivos de trabajo. Esta comprobación está autorizada por el
  usuario; no implica autorización para integrar cambios.
- Comparar la rama actual con su upstream y revisar novedades en las demás
  ramas remotas. Distinguir cambios entrantes, commits locales pendientes y
  divergencias; no presentar como actualización una rama histórica ya integrada.
- Si hay cambios disponibles para incorporar, resumir de qué rama vienen y
  preguntar: «Hay cambios disponibles en GitHub en `<rama_remota>`.
  ¿Querés que los descarguemos e integremos en el host?». Esperar confirmación
  explícita antes de hacer pull, merge, rebase o cambiar la versión instalada.
- Con la confirmación, integrar en una rama de trabajo, conservar los cambios
  locales y las mejoras existentes, resolver conflictos y ejecutar las
  validaciones pertinentes. No modificar `master`, descartar cambios locales,
  sobrescribir material ni sincronizar bases de datos o configuraciones locales.
- Si no hay novedades, indicarlo brevemente y continuar con la tarea. Si falla
  la conexión o autenticación, informar que no se pudo comprobar; no afirmar
  que el repositorio está actualizado. Si el usuario rechaza o posterga, continuar
  con la versión local sin insistir durante esa sesión por las mismas novedades.

## Cierre de cambios y publicación en GitHub

Esta instrucción se aplica en cada sesión y a cada tarea que termine con cambios
en el proyecto, incluidos cambios de documentación o de estas instrucciones.

- Antes de cerrar la tarea, terminar el trabajo y las validaciones pertinentes,
  revisar el diff y resumir qué cambió y qué se comprobó.
- Preguntar por iniciativa propia: «¿Querés que haga el commit y suba estos
  cambios a GitHub en la rama `<rama_actual>`?». No esperar a que el usuario
  solicite la publicación. Si hay commits locales anteriores pendientes de subir,
  indicar que también se incluirán en el push.
- Esperar una confirmación explícita. Esta regla autoriza preguntar, pero no
  autoriza por sí sola hacer commit o push. Si el usuario ya autorizó expresamente
  ambas acciones para estos mismos cambios, ejecutarlas sin preguntar de nuevo.
- Con la confirmación, revisar `git status` y el diff, seleccionar explícitamente
  solo los archivos de la tarea, ejecutar las auditorías correspondientes y crear
  un commit descriptivo. No incluir cambios ajenos, secretos, bases de datos,
  configuraciones locales, material multimedia, exports, logs o informes generados.
- Subir la rama de trabajo a `origin`; si no tiene upstream, usar
  `git push -u origin <rama_actual>`. No modificar ni publicar `master`, no usar
  force push ni saltar hooks o auditorías. Verificar el resultado y comunicar
  la rama y el commit publicados; no afirmar éxito si el push falló.
- Si el usuario rechaza o posterga, conservar los cambios locales y no insistir
  sobre el mismo lote. Volver a preguntar al terminar un nuevo lote de cambios.
- Si no hubo cambios ni commits pendientes, no ofrecer un commit vacío.

## Archivos ya existentes al enviar (2026-10-18)

El plan compara destino relativo y SHA-256, sin omitir contenido reutilizado en
otro nombre/proyecto. Si ya existe, informar y permitir elegir por archivo
«Renombrar y agregar» (proponer sufijo libre y volver a simular) o «No agregar».
No cambiar archivos del host ni del pendrive al elegir. Enviar solo tras la
confirmación del plan con destinos efectivos; nunca sobrescribir. Deshacer
restaura el origen registrado y conserva las versiones anteriores del pendrive.

## Huérfanas de envíos anteriores en el host (2026-10-18)

Tras cada envío completo al pendrive, con integridad y registros confirmados,
revisar también las carpetas de proyectos de envíos anteriores que consten en
la bitácora local de esa misma sala de espera. Retirar únicamente directorios
vacíos mediante `os.rmdir` en `_limpiar_carpetas_vacias_enviadas`; no borrar
archivos ni sobrescribir. Conservar raíces, personajes, carpetas ajenas sin
registro, áreas `_enviados`/`_revertidos`/`_a_revisar`, directorios ocultos,
enlaces/junctions y cualquier contenido nuevo. No ejecutar al arrancar, listar,
ni después de fallos o envíos parciales. No limpiar automáticamente el pendrive.
El resultado API incluye las carpetas retiradas; Deshacer recrea los padres
necesarios usando las rutas originales registradas. Esta ampliación sustituye
la limitación anterior que solo revisaba los capítulos del envío actual.

## Carpetas vacías después del envío (2026-10-12)

Excepción expresamente autorizada: después de verificar todas las copias y escribir
los registros del envío, se retiran mediante `os.rmdir` las subcarpetas vacías y
la carpeta de los capítulos enviados en la sala de espera. No se eliminan
archivos, raíz de espera, personajes, respaldos `_enviados`, capítulos ajenos
ni enlaces/junctions. Si hay contenido nuevo o un error, la carpeta se conserva.
Un envío fallido no inicia esta limpieza. El resultado API informa las carpetas
retiradas. Deshacer recrea los directorios necesarios para restaurar los archivos.
Las huérfanas anteriores del host se revisan solo si tienen registro de envío,
según la ampliación del 2026-10-18; no se limpia material del pendrive.


## Carpetas vacías de edición y Wi-Fi (2026-10-14)

Excepción adicional solicitada el 2026-10-14: al finalizar correctamente una
edición o completar un envío Wi-Fi, después de verificar los traslados y escribir
sus registros, retirar solo los padres vacíos de los archivos de esa operación.
`bandeja/carpetas_vacias.py` limita `os.rmdir` a esos directorios; conserva raíces,
personajes, respaldos, capítulos ajenos y enlaces/junctions. Los fallos o envíos
parciales no inician esta limpieza. Deshacer recrea los padres originales.
No es una limpieza retroactiva del pendrive ni elimina archivos.

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

## Publicados por personaje y organización manual (2026-10-14)

La recepción confirmada se archiva en videos completos/videosPublicados/lucie,
roli o mailen, conservando capítulo/nombre. Los numéricos sin personaje exigen
una elección explícita en la tarjeta; un filtro no asigna ni adivina personajes.
Los nuevos destinos incluyen personaje en plan y registro. Deshacer respeta las
rutas originales registradas, también para publicaciones anteriores.

La organización histórica se ejecuta únicamente para elementos seleccionados y
simulados: carpetas pendientes a videos sin publicar/personaje y archivos sueltos
confirmados a videosPublicados/personaje. No se ejecuta al arrancar, listar ni
buscar. No fusiona destinos existentes ni atraviesa enlaces/junctions. Verifica
estructura/hash, actualiza rutas locales y registra preparación/finalización.
Deshacer organización rechaza destinos ocupados o contenido añadido/cambiado;
conserva archivos y directorios. No borrar ni renombrar automáticamente históricos.

## Organización mensual (2026-10-19)

El usuario pidió agrupar también los capítulos existentes por mes y año,
incluidas `imagenes` y `audios`, conservando íntegros sus nombres.
Los nuevos envíos usan también `imagenes/<personaje>/<mes - año>/<capítulo>/`
y `audios/<personaje>/<mes - año>/<capítulo>/`. Una carpeta histórica existente
se continúa en su ruta registrada hasta organizarla explícitamente.
`bandeja.organizacion_mensual` simula carpetas
seleccionadas, exige confirmación, verifica estructura/SHA-256/identidad, rechaza
archivos en uso, enlaces, colisiones y contenido cambiado, registra y permite
simular Deshacer. Nunca se ejecuta al arrancar/listar. Usar mes explícito del
nombre o un registro inequívoco; si falta fecha, exigir elección, sin usar mtime
como adivinación. La migración registra prefijos de rutas para que sesiones,
reintentos, retiro de originales y Deshacer sigan resolviendo referencias viejas.
No reescribir registros históricos ni mover material sin revisar su plan.
