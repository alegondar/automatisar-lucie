# Bandeja de Descargas - Guía para Windows 10 / 11

Guía rápida de instalación y operación de la bandeja de descargas del proyecto Lucie en entornos Windows.

---

## 1. Requisitos e Instalación de Python 3.13

1. Descargue el instalador oficial de **Python 3.13** desde [python.org](https://www.python.org/downloads/).
2. Al iniciar la instalación, **es indispensable** marcar la opción:
   ```text
   [X] Add python.exe to PATH (o "Agregar python.exe al PATH")
   ```
3. Haga clic en **Install Now** y espere a que finalice.
4. No se requieren librerías de terceros (el sistema funciona exclusivamente con la biblioteca estándar de Python y `ctypes`).

---

## 2. Cómo Iniciar la Aplicación

Para iniciar la bandeja:
1. Abra la carpeta del proyecto en el Explorador de Windows.
2. Haga doble clic en el archivo **`iniciar_bandeja.bat`**.
3. El lanzador detectará el intérprete de Python. El propio `bandeja_descargas.py`
   abrirá automáticamente **Google Chrome**, aunque Edge sea el navegador
   predeterminado, cuando el dashboard responda. La dirección por defecto es:
   ```text
   http://127.0.0.1:8766
   ```
4. Mantenga abierta la ventana de la consola (símbolo del sistema), donde podrá visualizar el registro de actividad (logs) en tiempo real. Para detener la bandeja, cierre la consola o presione `Ctrl + C`.

La apertura automática también funciona al ejecutar Python directamente; respeta
`--puerto` y no abre dos pestañas desde el `.bat`. Si la bandeja ya está activa,
abre su panel sin iniciar otros vigilantes. `--sin-navegador` permite iniciar
sin Chrome. Si no se encuentra Chrome, se informa la URL y la bandeja continúa.

### Inicio automático e icono junto al reloj

Para habilitar Lucie al **iniciar sesión con tu usuario de Windows**, desde
PowerShell en esta carpeta:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\instalar_inicio_windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\instalar_inicio_windows.ps1 -Instalar
```

El primer comando muestra la simulación y el segundo crea `Lucie.lnk` en la
carpeta Inicio del usuario. No requiere administrador ni instala dependencias.
Conserva un acceso directo diferente si ya existe; repetir la instalación con
los mismos datos no lo modifica. Cada equipo registra sus propias rutas.

Lucie se inicia en segundo plano, sin consola ni apertura automática de Chrome,
usando la misma configuración y vigilantes del `.bat`. **Un clic izquierdo en
el icono abre el panel** en Chrome; el menú derecho ofrece abrirlo o salir de
Lucie, deteniendo sus vigilantes. Windows puede ubicar el icono dentro de **^**:
se puede arrastrar desde allí junto al reloj. No se modifican las preferencias
de la barra de tareas. Para deshabilitar el arranque, usar las aplicaciones de
inicio de Windows o abrir `shell:startup` y gestionar el acceso `Lucie`.

`iniciar_bandeja.bat` también habilita el icono. Si ya existe, abre el panel sin
crear otro servicio ni otro icono. Si la bandeja fue iniciada previamente con
Python sin icono, se conecta a ella sin reiniciarla: el menú muestra **Cerrar
icono**, y esa acción conserva el servicio que ya estaba funcionando.

El acceso de Inicio ejecuta `iniciar_bandeja_windows.py` con `pythonw.exe` y
`--sin-navegador`. Para iniciarlo manualmente sin consola se puede usar ese
mismo lanzador; `bandeja_descargas.py --icono` permite mantener una consola.
Los diagnósticos de inicio se agregan a
`%LOCALAPPDATA%\Lucie\logs\bandeja_windows.log`, fuera del repositorio. Los
fallos de arranque muestran un aviso con la ruta del diagnóstico.

La entrega vigente está en **`feat/lucie-recibir`**, incluyendo publicados por
personaje, organización manual, renovación del token tras reiniciar y Chrome
automático. La actualización del host el 2026-10-14 incluyó dos correcciones
nativas de rutas/cancelación: **392 pruebas OK, 11 omisiones** en Windows/Python
3.13.0, con manifiesto estable. El usuario confirmó la publicación de estas
correcciones en la misma rama, sobre la base descargada `c719cb2`.
Ver resultados y límites en [ESTADO_ACTUAL.md](ESTADO_ACTUAL.md). Cada equipo
conserva sus configuraciones y SQLite locales; no copiarlos entre sistemas.

---

## 3. Primer Uso y Configuración Local

- En el primer inicio en Windows, la bandeja detecta automáticamente su carpeta de descargas real del usuario mediante la API de Windows (`SHGetKnownFolderPath`).
- Si necesita personalizar rutas o puertos sin afectar otros equipos, cree o edite el archivo **`config_bandeja.local.json`**. Este archivo tiene prioridad sobre `config_bandeja.json` y nunca se sube al repositorio Git.
- Si no existe dicho archivo, en el primer arranque se generará automáticamente de manera segura sin sobreescribir configuraciones previas.

---

## 4. Cómo Vincular el Pendrive

El pendrive compartido está formateado en **exFAT** (admite archivos mayores a 4 GiB y no distingue entre mayúsculas y minúsculas):
1. Conecte el pendrive al puerto USB de su equipo Windows.
2. En el panel web (`http://127.0.0.1:8766`), la bandeja escaneará periódicamente las unidades lógicas (`D:\`, `E:\`, etc.) sin bloquear el sistema.
3. Si el pendrive ya contiene el marcador `.lucie_pendrive.json`, se conectará de inmediato y mostrará el espacio libre disponible.
4. Si es la primera vez que usa ese pendrive o necesita vincularlo, utilice el asistente de vinculación disponible en la interfaz web.

---

## 5. Advertencias Críticas de Seguridad

> [!WARNING]
> **NO COPIAR LA BASE SQLITE ENTRE LINUX Y WINDOWS**
> Cada equipo (la máquina Linux y la máquina Windows) mantiene su propia base de datos SQLite local e independiente. No intente sincronizar, copiar ni compartir el archivo `.sqlite` a través del pendrive o de la red. La base de datos y el archivo `config_bandeja.local.json` están excluidos del control de versiones en el `.gitignore`.

> [!IMPORTANT]
> **Expulsión del Pendrive en Windows**
> En Windows, la expulsión segura de la unidad se realiza mediante la bandeja del sistema de Windows ("Quitar hardware de forma segura y expulsar el medio"). Las opciones basadas en comandos de Linux (`udisksctl`) están deshabilitadas en Windows.

---

## 6. Verificación de Compatibilidad

Puede comprobar la compatibilidad de su entorno Windows ejecutando en una consola:
```powershell
python verificar_windows.py
```
Este script evaluará el sistema, rutas, nombres reservados, codificación y exclusividad de puertos, guardando un diagnóstico en `verificacion_windows.txt` sin borrar ningún dato.

## 7. Edición, CapCut y reproducción

**Terminé de editar** organiza los clips y revisa el export final para copiarlo
automáticamente a `videos completos/videos sin publicar` cuando sea inequívoco
y esté libre de escritura. Si aún falta, la sesión terminada queda visible con
**Revisar video final**. Después de actualizar, reiniciar la bandeja y recargar
con Ctrl+F5; ese botón permite revisar una sesión que ya se había terminado.
El proyecto debe exportarse desde CapCut; terminar la sesión del panel no genera
el video. Si hay varios candidatos, elegir en Videos completados. El modo manual
sigue esperando el envío explícito.

Para enviarlos por Wi-Fi, abrir **Sin publicar · Enviar al celular**, seleccionar
videos y el receptor LocalSend, revisar y confirmar. Abrir LocalSend en el celular
conectado a la misma red y aceptar la recepción. Si la búsqueda falla, se puede
conectar por la IP y el puerto de LocalSend. Los recibidos pasan de
`videos completos/videos sin publicar/` al nivel anterior con opción de Deshacer.
Ver [Publicación y envío Wi-Fi](docs/publicacion-wifi.md).

**Terminé de editar** permite mantener CapCut abierto cuando sus clips pueden
leerse. Si Windows impide moverlos por estar en uso, crea copias verificadas en
`videos ya editados` y conserva los originales. Deshacer conserva las copias en
`_revertidos`, sin pisar esos originales. Si un bloqueo impide incluso leer el
archivo, se informa el conflicto y la sesión sigue abierta.

Al confirmar **Crear nueva sesión** en Edición, se abre automáticamente el
Explorador de Windows en la carpeta del capítulo seleccionado del pendrive
vinculado. Si solo se seleccionaron audios, se abre su carpeta de audios.
La apertura no mueve archivos. Si falla o se desconectó el pendrive, la sesión
se conserva y el panel informa el problema.

El funcionamiento actual, las rutas finales y los controles de seguridad están
documentados en [ESTADO_ACTUAL.md](ESTADO_ACTUAL.md). Las carpetas de salida usan
el formato vigente documentado allí, con los videos directamente dentro. Las
nuevas carpetas de ya editados usan `videoyaeditado_<nombre>_semana_<del mes>_<mes>_<año>`;
los nuevos completos pasan por `videos completos/videos sin publicar`.

CapCut conserva su export original. La bandeja copia el nuevo export con el
nombre de la sesión al pendrive vinculado y muestra el estado en **Videos
completados**. Para exigir el botón de envío antes de copiar, usar
`"envio_exports_capcut": "manual"` en `config_bandeja.local.json`.

La exclusividad Windows se comprueba con `CreateFileW` sin compartir el archivo;
un simple bloqueo de bytes `msvcrt` no detectaba todos los escritores abiertos.
El visor de Edición conserva ahora sus identificadores entre sondeos y distingue
errores HTTP de formatos no admitidos por el navegador. Después de actualizar,
reiniciar la bandeja y recargar con `Ctrl+F5`.

Los resultados más recientes están en ESTADO_ACTUAL.md; AST con 0 infracciones.
Consultar los motivos de los saltos y los límites de la validación en la guía
de estado. Nunca ejecutar pruebas contra carpetas reales del usuario.
