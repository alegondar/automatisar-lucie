# Estado actual del sistema — 2026-10-11

Esta guía describe el comportamiento implementado y complementa las siete
Reglas de Oro de `openspec/config.yaml`. Para edición y CapCut, prevalece sobre
las rutas y decisiones anteriores de los documentos históricos de OpenSpec.

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

```text
LucieSinReglas/
  videos sin editar/<personaje>/<capitulo>/<clip.mp4>
  videos ya editados/<personaje>/<Mi video - octubre - 2026>/<clip.mp4>
  videos completos/<personaje>/<Mi video - octubre - 2026>/<Mi video.mp4>
  .lucie/manifiesto.jsonl
  _revertidos/
```

El personaje sigue siendo el nivel contenedor. La carpeta de salida contiene
el nombre de la edición sin extensión, el mes en español y el año de la operación,
según el reloj local. No contiene semana ni otra carpeta de capítulo: todos los
clips de una edición quedan directamente dentro de su carpeta. La petición final
sustituye la primera implementación con semana y carpetas anidadas.

Los archivos anteriores no se migran ni se reorganizan automáticamente. Los
destinos ocupados se rechazan. Las rutas efectivas del manifiesto permiten
reintentos, contadores y deshacer aunque cambie el mes. La ruta del video completo
registrada en SQLite evita volver a copiar una misma sesión en otro mes.

## Flujo de edición y CapCut

1. En **Edición**, seleccionar crudos y crear una sesión con su nombre.
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
4. Si exactamente una sesión espera un export, lo asocia a ella. Si hay varias
   o ninguna, deja la elección al usuario; no adivina por fecha.
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
