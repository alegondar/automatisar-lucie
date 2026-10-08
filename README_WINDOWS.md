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
3. El lanzador detectará el intérprete de Python, abrirá automáticamente su navegador web en:
   ```text
   http://127.0.0.1:8766
   ```
4. Mantenga abierta la ventana de la consola (símbolo del sistema), donde podrá visualizar el registro de actividad (logs) en tiempo real. Para detener la bandeja, cierre la consola o presione `Ctrl + C`.

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
