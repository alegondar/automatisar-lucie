# 🎬 Lucie & Personajes Digitales — Bandeja de Descargas y Bóveda Multimedia

Plataforma integral desarrollada en Python para la automatización, clasificación, resguardo y auditoría continua del flujo de producción multimedia de personajes digitales (**Lucie**, **Magui la Roli** y **Mailen**).

Para entender qué hace cada módulo y cómo se conectan, abrí el
[manual HTML del funcionamiento interno](docs/manual-interno.html) en el navegador.
Incluye un recorrido paso a paso, mapa de componentes, glosario y explicación
de los controles de seguridad. Funciona sin conexión y permite imprimirlo.

El sistema coordina la captura no invasiva de descargas de inteligencia artificial (Grok, Gemini, Nano Banana, Google Flow), su estructuración por escenas y capítulos, el traslado atómico a la sala de espera y la transferencia segura hacia unidades externas (pendrives compartidos formateados en exFAT) para su posterior montaje y edición en Windows con CapCut.

> [!IMPORTANT]
> **Repositorio Privado:** Este proyecto es de uso exclusivo y privado. No cuenta con licencia pública de distribución ni redistribución.

---

## 🛡️ Las 7 Reglas de Oro de Seguridad

Dado el valor irreemplazable de las creaciones y grabaciones, toda la plataforma opera bajo siete principios de seguridad:

1. **Prohibición de Borrado Automático y Pisado Ciego:**
   Fuera del flujo manual confirmado, queda estrictamente prohibida la invocación de primitivas destructivas del sistema operativo (`os.remove`, `os.unlink`, `os.rmdir`, `os.removedirs`, `shutil.rmtree`, `shutil.move`, `os.replace`, `send2trash` o comandos de shell con `rm`). Los descartes se trasladan a carpetas protegidas (`_descartados/`) preservando cada byte original. Excepción: en «Eliminar capítulos» el usuario puede seleccionar carpetas o archivos multimedia dentro del proyecto LucieSinReglas del pendrive, revisar la simulación y escribir ELIMINAR para borrarlos permanentemente. Se protegen la raíz, los metadatos y los enlaces; se revalida identidad y contenido antes de ejecutar.
2. **Simulación Previa Obligatoria (Dry-Run):**  
   Ningún archivo se traslada o copia sin generar antes una simulación detallada que exponga los orígenes, los destinos exactos calculados, los tamaños y el estado del almacenamiento.
3. **Aprobación Granular por el Usuario:**  
   El usuario conserva la decisión final sobre cada lote o archivo antes de cualquier alteración en el disco.
4. **Validación de Destino y Confinamiento de Rutas:**  
   Toda ruta de archivo se resuelve canónicamente con `realpath` y se verifica contra los límites autorizados mediante `commonpath`, impidiendo cualquier escape por enlaces simbólicos o secuencias de escape de directorio (`../`).
5. **Verificación de Integridad por SHA-256 y Atomicidad:**  
   La transferencia hacia pendrives se realiza escribiendo en archivos temporales `.part`, sincronizando buffers físicos con `fsync` y verificando la coincidencia exacta de hash SHA-256 antes del renombrado final.
6. **Bitácora Append-Only y Operaciones Reversibles:**  
   Cada eliminación manual se registra en `.lucie/eliminaciones.jsonl` y es irreversible, sin opción de deshacer. Cada movimiento queda documentado en bitácoras cronológicas `.jsonl`. El sistema cuenta con mecanismos de deshacer (`/api/deshacer`) capaces de retornar los archivos a su ubicación original sin colisiones.
7. **Verificación Estática Continua (AST):**  
   Un analizador sintáctico automatizado ([`seguridad_anti_borrado.py`](seguridad_anti_borrado.py)) audita el árbol de sintaxis abstracta de cada archivo operativo, prohibiendo el borrado automático y el pisado. Admite las dos primitivas del método manual `GestorEliminacionPendrive.ejecutar` y únicamente `os.rmdir(ruta)` en `_limpiar_carpetas_vacias_enviadas` y `retirar_carpetas_vacias_traslado`, después de operaciones exitosas y registradas; las pruebas verifican el confinamiento de estas excepciones.

---

## 🔄 El Flujo de Trabajo

```
[ Generación IA ]  -->  [ ~/Descargas ] (Archivos crudos)
                               |
                               v
                     [ Vigilante / Bandeja ] (Detección no invasiva + Sondeo de estabilidad)
                               |
                               v
                     [ Capítulo en Foco ] (Preasignación por personaje/escena)
                               |
                               v (Simulación previa + Aprobación)
                     [ Sala de Espera ] (Organizado en ~/Descargas/_lucie/<personaje>/<capítulo>/)
                               |
                               v (Transferencia segura con fsync y .part)
                     [ Bóveda Pendrive ] (Estructura LucieSinReglas/ para edición en Windows)
```

1. **Crear o Enfocar un Capítulo:** En el panel web se crea o selecciona el capítulo en curso (ej. `lucie/plaza`). Dicho capítulo toma el foco principal.
2. **Descarga y Detección Automática:** Las descargas provenientes de navegadores caen en la carpeta de descargas. El vigilante supervisa que el tamaño del archivo se mantenga estable (descarga completada) antes de registrarlo.
3. **Simular y Mover a Sala de Espera:** El lote se inspecciona en la interfaz web; al aprobarlo, los archivos se reubican atómicamente en la sala de espera estructurada (`~/Descargas/_lucie/`).
4. **Envío Seguro al Pendrive:** Al conectar la unidad externa vinculada, el usuario selecciona los lotes listos, revisa la simulación de espacio y transfiere el material a la bóveda del pendrive (`LucieSinReglas/`).

---

## 📦 Estructura del Proyecto

### Paquete `bandeja/`

* [`bandeja/__init__.py`](bandeja/__init__.py): Interfaz y exportaciones públicas del paquete.
* [`bandeja/capitulos.py`](bandeja/capitulos.py): Gestión de estados de historias y escenas (abiertos, en foco, cerrados y descartados con reversibilidad).
* [`bandeja/clasificacion.py`](bandeja/clasificacion.py): Filtros de lista blanca y clasificación por reglas heurísticas y alias de personajes (Grok, Gemini, Nano Banana).
* [`bandeja/config.py`](bandeja/config.py): Carga y normalización de parámetros generales (`config_bandeja.json`) y configuraciones locales independientes por máquina (`config_bandeja.local.json`).
* [`bandeja/db.py`](bandeja/db.py): Capa de persistencia en SQLite local configurada en modo `WAL` (`Write-Ahead Logging`) para concurrencia e integridad.
* [`bandeja/lotes.py`](bandeja/lotes.py): Agrupador temporal de descargas para consolidar ráfagas de archivos en lotes coherentes.
* [`bandeja/movimientos.py`](bandeja/movimientos.py): Ejecutor seguro de traslados a la sala de espera, cálculo de rutas de destino, simulación previa y reversión atómica.
* [`bandeja/pendrive.py`](bandeja/pendrive.py): Integración con unidades USB: verificación del marcador `.lucie_pendrive.json`, asistente de vinculación, simulación de capacidad, streaming con `.part` y control seguro de montaje.
* [`bandeja/plataforma.py`](bandeja/plataforma.py): Abstracción del sistema operativo (Linux / Windows) para detección de unidades, cálculo de espacio libre y normalización de rutas.
* [`bandeja/servidor.py`](bandeja/servidor.py): Servidor HTTP integrado (API REST, Server-Sent Events para reactividad en vivo, generación de miniaturas y streaming multimedia).
* [`bandeja/vigilante.py`](bandeja/vigilante.py): Hilo demonio de monitoreo continuo sobre la carpeta de descargas con filtrado de archivos temporales.
* `bandeja/web/`: Frontend visual sin dependencias externas (HTML, CSS y JS modular) servido directamente por el backend.

### Herramientas Operativas y de Seguridad

* [`bandeja_descargas.py`](bandeja_descargas.py): Punto de inicio principal para arrancar el servidor de la bandeja de descargas.
* [`inventario_pendrive.py`](inventario_pendrive.py): Herramienta CLI de auditoría en modo estrictamente de solo lectura para unidades USB (duplicados globales por SHA-256, desglose de carpetas y duraciones).
* [`plan_limpieza.py`](plan_limpieza.py): Generador y validador de planes de ordenamiento y limpieza simulada (dry-run).
* [`seguridad_anti_borrado.py`](seguridad_anti_borrado.py): Analizador AST que prohíbe las primitivas destructivas fuera del método de eliminación manual confirmado.
* [`auditar_repo.py`](auditar_repo.py): Auditor integral del repositorio que inspecciona archivos rastreados y el historial de Git en busca de credenciales, secretos, datos personales o archivos pesados.
* [`instalar_hooks.py`](instalar_hooks.py): Instalador seguro de creación exclusiva del hook Git `pre-push`.
* [`verificar_windows.py`](verificar_windows.py): Diagnóstico de compatibilidad de entorno y rutas reservadas para Windows.
* [`guardia_hermetica.py`](guardia_hermetica.py): Módulo de aislamiento de entorno para pruebas unitarias herméticas.

---

## 🚀 Puesta en Marcha

### En Linux (Kali / Debian / Ubuntu)

Para descargar esta entrega de `feat/lucie-recibir` y continuar en Kali,
seguir [README_KALI.md](README_KALI.md). Incluye configuración independiente,
pruebas temporales y alcance de la compatibilidad revisada.

1. Abrir una terminal en el repositorio:
   ```bash
   python3 bandeja_descargas.py
   ```
2. Acceder al panel web desde el navegador:
   ```text
   http://127.0.0.1:8766
   ```

Al ejecutar `bandeja_descargas.py`, Google Chrome se abre automáticamente cuando
el dashboard responde. Respeta `--puerto`; si la bandeja ya está activa, abre
su panel sin iniciar otra instancia. Si Chrome no está instalado, se informa
la dirección y el servidor sigue funcionando. Para iniciar sin navegador:
`python3 bandeja_descargas.py --sin-navegador`.

### En Windows 10 / 11

1. Hacer doble clic sobre el lanzador [`iniciar_bandeja.bat`](iniciar_bandeja.bat), o ejecutar en PowerShell:
   ```powershell
   python bandeja_descargas.py
   ```
2. Para más detalles sobre configuración local, nombres reservados y el montaje de unidades en Windows, consultar la guía específica:  
   👉 **[README_WINDOWS.md](README_WINDOWS.md)**

Windows también permite iniciar Lucie en segundo plano al entrar a la sesión,
con un icono junto al reloj para abrir el panel con un clic. El instalador
`instalar_inicio_windows.ps1` ofrece simulación y habilitación por usuario;
ver [inicio automático e icono](README_WINDOWS.md#inicio-automático-e-icono-junto-al-reloj).
El `.bat` conserva su consola y añade el mismo icono, sin duplicar instancias.

---

## 🧪 Pruebas Automatizadas y Auditorías

### Suite Completa de Tests Herméticos

Toda la suite está diseñada para ser completamente hermética (independiente del entorno, de montajes físicos y de puertos fijos):

```bash
python3 -m unittest discover -s . -p "test_*.py"
```

### Auditoría AST Anti-Borrado (Regla de Oro #1 y #7)

Valida la prohibición de borrado automático y sobrescritura ciega, con la excepción explícita del método manual confirmado:

```bash
python3 seguridad_anti_borrado.py .
```

### Auditoría de Seguridad e Historial

Verifica que el repositorio se encuentre libre de secretos, datos personales, bases de datos o archivos pesados:

```bash
python3 auditar_repo.py --historial
```

---

## 🔒 Protección Automática contra Fugas (Hook Pre-Push)

Para evitar que se suban accidentalmente archivos no autorizados, datos personales o reportes generados a GitHub, el proyecto incluye un instalador del hook `pre-push`:

```bash
python3 instalar_hooks.py
```

* El script instala `.git/hooks/pre-push` de forma segura.
* **Garantía de creación exclusiva:** Si ya existe un hook configurado, no lo sobrescribe.
* Al ejecutar cualquier comando `git push`, el hook ejecutará automáticamente `python3 auditar_repo.py --historial` y cancelará el envío si se detecta alguna anomalía.

## Organización de videos editados y completos

**Sin publicar · Enviar al celular** integra un emisor Wi-Fi compatible con LocalSend.
Los nuevos completos quedan en `videos completos/videos sin publicar/`; después
de recibirlos en el dispositivo elegido, pasan a
`videos completos/videosPublicados/<personaje>/` con registro y Deshacer. Los originales de CapCut se conservan. Ver [Uso, conexión y reglas de
publicación](docs/publicacion-wifi.md). El receptor propio
[Lucie Recibir para Android](android/README.md) permite aprobar y guardar los
archivos sin instalar LocalSend; APK inicial probado en emulador, pendiente
de verificar en el Motorola físico.

Las nuevas carpetas de **videos ya editados** usan
`videoyaeditado_<nombre>_semana_<del mes>_<mes>_<año>`, dentro del personaje.
Por ejemplo: `videoyaeditado_Lucie_invita_a_café_semana_2_octubre_2026`.
Se quita el sufijo generado `videocompleto` del nombre base. Esta excepción
solo cambia los nuevos destinos de crudos editados; las rutas registradas
anteriormente siguen disponibles para reintentos y deshacer.

Para próximas sesiones y mantenimiento, consultar [Estado actual del sistema](ESTADO_ACTUAL.md)
y [Guía para agentes](AGENTS.md). La constitución permanece en [openspec/config.yaml](openspec/config.yaml).

Al pasar un clip a `videos ya editados` o copiar un export asociado a una sesión,
se crea una carpeta de salida dentro de su personaje. Los archivos quedan
directamente dentro de ella, sin subcarpetas de semana o capítulo:

```text
videos ya editados/lucie/videoyaeditado_Mi_video_semana_2_octubre_2026/Toma 1.mp4
videos ya editados/lucie/videoyaeditado_Mi_video_semana_2_octubre_2026/Toma 2.mp4
videos completos/videos sin publicar/lucie/Mi video - lunes - semana 2 - octubre - 2026/Mi video.mp4
```

La fecha corresponde al momento del traslado o copia, según el reloj local del
equipo, con semana del mes por bloques de días. Los clips de una misma edición
se agrupan en ella. Los completos sin sesión inequívoca se resguardan directamente
en Sin publicar por nombre/versionado; no se inventa su asociación. Al confirmar
la recepción en el celular se trasladan a `videosPublicados/<personaje>/`,
conservando nombres y carpetas de capítulo. Los numéricos sin personaje requieren
elegirlo en su tarjeta. La organización de completos anteriores es manual, con
simulación, confirmación, registro y deshacer; no se fusionan ni sobrescriben destinos.

### Exports de CapCut y videos completados

**Terminé de editar** también revisa el video final de la sesión: en modo
automático lo copia a `videos completos/videos sin publicar` si hay un único
export vigente. El aviso distingue la organización de clips del resultado del
export e informa destino, espera o error. Si falta la copia, la sesión terminada
permanece visible con **Revisar video final**; no hace falta crear otra sesión.
El botón no exporta el proyecto dentro de CapCut: hay que usar Exportar allí.

Una revisión puede recuperar un video exportado durante esa sesión que existía
antes del arranque de la bandeja, respetando los sondeos de estabilidad y la
apertura exclusiva. La espera solicitada se retoma tras reiniciar. Las sesiones
terminadas antes de esta corrección requieren **Revisar video final**, para evitar
una importación retroactiva al instalar la actualización. Varios exports o sesiones
superpuestas se ofrecen en Videos completados para elegir, sin copiar ni adivinar
una asociación. El modo manual y Deshacer mantienen sus restricciones.

La bandeja inicia el vigilante de la carpeta de exportación de CapCut y espera
a que cada nuevo video se estabilice y quede libre de escritura. Cuando hay una
sola sesión esperando un export, incluso después de pulsar «Terminé de editar»,
la copia en `videos completos` recibe el nombre de esa sesión. El export numérico
original de CapCut se conserva. Los archivos presentes al iniciar el vigilante
no se importan automáticamente.

La pestaña **Videos completados** muestra el export original con reproductor,
el nombre de la edición, los pendientes, errores y la ruta enviada al pendrive.
Una única sesión **En edición** tiene prioridad para el envío automático aunque
haya sesiones antiguas editadas pendientes. Si hay varias sesiones en edición,
permite elegir antes de enviar. Si no hay ninguna en edición, solo asocia
automáticamente cuando queda una única sesión editada esperando export.
Los envíos autorizados pendientes se retoman al reconectar el pendrive, aunque
no aparezca un nuevo export. «Deshacer envío» conserva el video en `_revertidos`
y requiere un nuevo envío explícito para volver a copiarlo.

Por defecto el envío es automático. Para revisar cada export antes de enviarlo,
configurar `"envio_exports_capcut": "manual"` en la configuración de la bandeja.
En ese modo se asocia la sesión automáticamente, pero la copia espera el botón
**Enviar al pendrive**. Esta opción es independiente de `al_exportar`, que
corresponde al tratamiento de los clips crudos.

Las rutas efectivas quedan registradas para permitir reintentos y deshacer aunque
cambie la fecha. Los archivos existentes conservan su estructura anterior y no se
reorganizan automáticamente. Los destinos ocupados se respetan sin sobrescribir.

Desde el 2026-10-15, la sugerencia de edición conserva espacios, acentos y
mayúsculas. El título base de las nuevas salidas quita el sufijo generado
`videocompleto` y la fecha documentada del capítulo, incluso si una sugerencia
anterior los había pegado. La carpeta agrega una sola fecha del traslado y el
archivo conserva solo el título: por ejemplo,
`Caballero lo estamos llamando - jueves - semana 3 - octubre - 2026/Caballero lo estamos llamando.mp4`.
En ya editados se conserva el formato `videoyaeditado_...` con guiones bajos.
Si una sesión antigua tiene el título pegado, se recuperan sus espacios solo
cuando el capítulo o un clip conserva el mismo título legible; sin esa evidencia
no se inventa una separación de palabras. No se renombran salidas existentes,
no se altera el export original de CapCut ni se cambian las rutas de Deshacer.

### Audio MP3

El uso, las garantías del borrado manual y las limitaciones conocidas están
documentados en [Dashboard: eliminación y MP3](docs/dashboard-eliminacion-y-mp3.md).

Los `.mp3` se detectan como multimedia. Con alias conocido o capítulo en foco se incorporan a lotes; los demás aparecen en «Sin identificar» y pueden adoptarse con «Del proyecto». Se trasladan a `audios/` conservando su nombre, sin sobrescribir, y se envían al pendrive bajo `audios/<personaje>/<capítulo>/`.

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

Desde el 2026-10-14, finalizar una edición y completar un envío al celular también
retiran los directorios vacíos que dejaron sus archivos trasladados. Solo se
consideran los padres de esos archivos; se conservan categorías, personajes,
respaldos, carpetas ajenas y cualquier contenido nuevo. No se limpian traslados
fallidos ni envíos parciales. Deshacer recrea las rutas originales. La limpieza
no se aplica retroactivamente al material del pendrive.

Excepción expresamente autorizada: después de verificar todas las copias y escribir
los registros del envío, se retiran mediante `os.rmdir` las subcarpetas vacías y
la carpeta de los capítulos enviados en la sala de espera. No se eliminan
archivos, raíz de espera, personajes, respaldos `_enviados`, capítulos ajenos
ni enlaces/junctions. Si hay contenido nuevo o un error, la carpeta se conserva.
Un envío fallido no inicia esta limpieza. El resultado API informa las carpetas
retiradas. Deshacer recrea los directorios necesarios para restaurar los archivos.
Las huérfanas anteriores del host se revisan solo si tienen registro de envío,
según la ampliación del 2026-10-18; no se limpia material del pendrive.


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
