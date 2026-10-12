# Guía para próximas sesiones

Leer primero [ESTADO_ACTUAL.md](ESTADO_ACTUAL.md), [README.md](README.md)
y, en Windows, [README_WINDOWS.md](README_WINDOWS.md).
La constitución del sistema son las siete Reglas de Oro de
[openspec/config.yaml](openspec/config.yaml); siguen obligatorias.

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

La estructura final de salidas es `<categoria>/<personaje>/<nombre - día - semana del mes - mes - año>/`
con videos directamente dentro, sin semana ni subcarpetas de capítulo.
CapCut conserva sus originales. Ver el mapa de módulos, API, estados, modo manual,
reintentos, reversión y validaciones en `ESTADO_ACTUAL.md`.

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

## Carpetas vacías después del envío (2026-10-12)

Excepción expresamente autorizada: después de verificar todas las copias y escribir
los registros del envío, se retiran mediante `os.rmdir` las subcarpetas vacías y
la carpeta de los capítulos enviados en la sala de espera. No se eliminan
archivos, raíz de espera, personajes, respaldos `_enviados`, capítulos ajenos
ni enlaces/junctions. Si hay contenido nuevo o un error, la carpeta se conserva.
Un envío fallido no inicia esta limpieza. El resultado API informa las carpetas
retiradas. Deshacer recrea los directorios necesarios para restaurar los archivos.
No se aplica una limpieza retroactiva al material real.


## Nombres documentados de carpetas nuevas (2026-10-12)

La instrucción vigente para carpetas nuevas es:
`<nombre del video o capítulo> - <día de la semana> - semana <del mes> - <mes> - <año>`.
Por ejemplo: `oloraculo - lunes - semana 2 - octubre - 2026`.
La semana del mes se calcula por bloques de días: 1–7, 8–14, 15–21, 22–28 y 29–31.
Se usa el reloj local, nombres españoles y una sola carpeta, sin niveles de semana.
El dashboard aplica el formato al iniciar capítulos y simular nuevas escenas;
las salidas de edición también usan el nombre de video, día, semana del mes, mes y año.
Esta regla sustituye el anterior sufijo de solo mes y año. Las carpetas y rutas
históricas no se renombran ni migran automáticamente. Reintentos y deshacer usan
las rutas registradas. La nueva excepción de limpieza solo retira directorios
vacíos de capítulos enviados; los originales siguen conservados en `_enviados`.
