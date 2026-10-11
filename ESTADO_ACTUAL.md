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
2. «Terminé de editar» agrupa los crudos en `videos ya editados`. La sesión
   puede recibir el export tanto en estado `en_edicion` como `editado`.
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

Última suite completa de esta sesión: Python 3.13 en Windows, **286 pruebas,
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
