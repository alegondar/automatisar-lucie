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
   Un analizador sintáctico automatizado ([`seguridad_anti_borrado.py`](seguridad_anti_borrado.py)) audita el árbol de sintaxis abstracta de cada archivo operativo, prohibiendo el borrado automático y el pisado. Solo admite las dos primitivas del método manual `GestorEliminacionPendrive.ejecutar`; las pruebas verifican su confinamiento y confirmación.

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

1. Abrir una terminal en el repositorio:
   ```bash
   python3 bandeja_descargas.py
   ```
2. Acceder al panel web desde el navegador:
   ```text
   http://127.0.0.1:8766
   ```

### En Windows 10 / 11

1. Hacer doble clic sobre el lanzador [`iniciar_bandeja.bat`](iniciar_bandeja.bat), o ejecutar en PowerShell:
   ```powershell
   python bandeja_descargas.py
   ```
2. Para más detalles sobre configuración local, nombres reservados y el montaje de unidades en Windows, consultar la guía específica:  
   👉 **[README_WINDOWS.md](README_WINDOWS.md)**

---

## 🧪 Pruebas Automatizadas y Auditorías

### Suite Completa de Tests Herméticos

Toda la suite está diseñada para ser completamente hermética (independiente del entorno, de montajes físicos y de puertos fijos):

```bash
env HOME=/tmp/homefalso python3 -m unittest discover -s . -p "test_*.py"
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

Para próximas sesiones y mantenimiento, consultar [Estado actual del sistema](ESTADO_ACTUAL.md)
y [Guía para agentes](AGENTS.md). La constitución permanece en [openspec/config.yaml](openspec/config.yaml).

Al pasar un clip a `videos ya editados` o copiar un export a `videos completos`,
se crea una única carpeta con el nombre de la edición dentro de su personaje.
Los videos quedan directamente dentro de ella, sin subcarpetas:

```text
videos ya editados/lucie/Mi video - octubre - 2026/Toma 1.mp4
videos ya editados/lucie/Mi video - octubre - 2026/Toma 2.mp4
videos completos/lucie/Mi video - octubre - 2026/Mi video.mp4
```

La fecha corresponde al momento del traslado o copia, según el reloj local del
equipo. La carpeta usa el nombre de la edición sin extensión, el mes en español
y el año; no incluye semana. Los clips de una misma edición se agrupan en ella.

### Exports de CapCut y videos completados

La bandeja inicia el vigilante de la carpeta de exportación de CapCut y espera
a que cada nuevo video se estabilice y quede libre de escritura. Cuando hay una
sola sesión esperando un export, incluso después de pulsar «Terminé de editar»,
la copia en `videos completos` recibe el nombre de esa sesión. El export numérico
original de CapCut se conserva. Los archivos presentes al iniciar el vigilante
no se importan automáticamente.

La pestaña **Videos completados** muestra el export original con reproductor,
el nombre de la edición, los pendientes, errores y la ruta enviada al pendrive.
Si varias sesiones esperan exports, permite elegir la edición antes de enviar.
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

### Audio MP3

El uso, las garantías del borrado manual y las limitaciones conocidas están
documentados en [Dashboard: eliminación y MP3](docs/dashboard-eliminacion-y-mp3.md).

Los `.mp3` se detectan como multimedia. Con alias conocido o capítulo en foco se incorporan a lotes; los demás aparecen en «Sin identificar» y pueden adoptarse con «Del proyecto». Se trasladan a `audios/` conservando su nombre, sin sobrescribir, y se envían al pendrive bajo `audios/<personaje>/<capítulo>/`.
