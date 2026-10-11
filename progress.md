# Registro de Progreso (progress.md)

## Sesión: 2026-10-11 — Windows, edición y CapCut

Implementados y commiteados: detección de escritores Windows, pruebas de symlinks
según privilegios reales, fixtures temporales de capítulos, carpetas únicas por
edición con mes/año, envío y revisión de exports CapCut, y persistencia de los
identificadores del visor entre sondeos. El detalle vigente y la evidencia están
en [ESTADO_ACTUAL.md](ESTADO_ACTUAL.md); sustituye el diseño intermedio con semana.

Última suite: 286 pruebas OK, 9 saltadas; AST 0 infracciones y JavaScript válido.
Manifiesto antes/después: 54/54. Linux no ejecutado en esta máquina.
Documentación actualizada para continuidad; rama `organizar-videos-por-fecha`,
con `master` intacto. Las propuestas anteriores se conservan como historial.

## Sesión: 2026-10-03

### [09:28] Inicialización del proyecto
- Creados `task_plan.md` y `findings.md`.
- Verificado el entorno: Python 3.13, ffprobe 8.1.2, pendrive montado en `/run/media/<usuario>/<pendrive>` con 115 GB y ~9.5 GB de datos.

### [09:31] Implementación, Pruebas y Validación Real
- Implementado [`inventario_pendrive.py`](file:///home/<usuario>/Documentos/code-proyect/automatisar-lucie/inventario_pendrive.py) con todos los requerimientos:
  * Confinamiento estricto de rutas con `realpath` y descarte de symlinks externos.
  * Ignorado de carpetas de sistema (`System Volume Information`, `$RECYCLE.BIN`, `.Trash-*`, `lost+found`) y archivos ocultos (`--incluir-ocultos`).
  * Clasificación por extensión (`video`, `foto`, `audio`, `documento`, `subtítulo`, `otro`).
  * Duración con `ffprobe` exclusiva para videos.
  * Detección de duplicados globales y cross-carpeta por SHA-256 en streaming.
  * Detección de carpetas vacías y carpetas similares/duplicadas.
  * Detección de archivos sueltos en raíz y raíces de primer nivel.
  * Motor de caché local SQLite en repositorio (`.cache/`).
  * Formatos de salida en consola, Markdown y JSON.
- Creada suite de pruebas [`test_inventario.py`](file:///home/<usuario>/Documentos/code-proyect/automatisar-lucie/test_inventario.py) (9/9 pruebas pasando).
- Ejecutado análisis real sobre `/run/media/<usuario>/<pendrive>`:
  * 1,915 archivos analizados (9.32 GB).
  * 637 videos con duración extraída.
  * 110 grupos de duplicados detectados (776.37 MB recuperables).
  * 2 carpetas vacías detectadas.
  * 7 carpetas con duplicación o alta similitud de contenido.
  * Tiempo inicial: ~46 segundos; tiempo con caché: 0.33 segundos.
- Documentado uso completo en [`README.md`](file:///home/<usuario>/Documentos/code-proyect/automatisar-lucie/README.md).

