# Plan de Tareas: Script de Auditoría e Inventario de Pendrive

> Este plan corresponde al inventario inicial de 2026-10-03. Para el estado
> actual de Windows, edición y CapCut, consultar [ESTADO_ACTUAL.md](ESTADO_ACTUAL.md)
> y [progress.md](progress.md). No usar el estado histórico de este plan como
> indicador del avance de esas funcionalidades.

## Objetivo
Desarrollar un script en Python robusto, multiplataforma (Linux/Kali y Windows) y estrictamente de **SOLO LECTURA** para auditar e inventariar todo el contenido de un pendrive con análisis de archivos, detección de duplicados globales y carpetas sospechosas, cálculo de almacenamiento y generación de informes detallados.

**Status:** in_progress
**Current Phase:** Phase 1 - Análisis y Especificación

---

## Fases del Proyecto

### Phase 1: Análisis y Especificación
- [x] Inspección de entorno de ejecución (Linux Kali, Python 3.13, ffprobe disponible, `/run/media/<usuario>/<pendrive>` montado).
- [x] Verificación de estructura real del pendrive y casos de prueba.
- [x] Documentación de requerimientos y casos límite en `findings.md`.
- **Status:** complete

### Phase 2: Arquitectura y Módulos Base
- [x] Seguridad de rutas: resolución con `os.path.realpath`, rechazo estricto de symlinks o rutas que escapen de `--raiz`.
- [x] Filtrado de carpetas del sistema (`System Volume Information`, `$RECYCLE.BIN`, `.Trash-*`, `lost+found`) y archivos ocultos (`--incluir-ocultos`).
- [x] Clasificador por tipo de archivo: `video`, `foto`, `audio`, `documento`, `subtítulo`, `otro`.
- [x] Extractor de duración multimedia con `ffprobe` (exclusivo para videos, tolerante a fallos y timeouts).
- **Status:** complete

### Phase 3: Motores de Análisis Avanzado
- [x] Motor de cálculo de capacidad y espacio usado vs reportado por sistema de archivos (`shutil.disk_usage`).
- [x] Motor de duplicados en TODO el pendrive (agrupación previa por tamaño, hash SHA-256 por bloques con streaming). Detección cross-carpeta.
- [x] Detección de carpetas vacías y carpetas aparentemente duplicadas (comparación por contenido, por nombres similares y subconjuntos).
- [x] Detección de archivos sueltos en raíz del pendrive y en la raíz de cada carpeta de primer nivel.
- **Status:** complete

### Phase 4: Motor de Caché Persistente Local (Repo-Only)
- [x] Garantía de SOLO LECTURA en el pendrive (verificación estricta de no escritura en `--raiz`).
- [x] Motor de caché en el repositorio (almacenamiento local SQLite con mtime, tamaño, hash y duración).
- [x] Opciones CLI para invalidar o ignorar caché (`--sin-cache`, `--limpiar-cache`).
- **Status:** complete

### Phase 5: Formateador de Informes y CLI
- [x] CLI con `argparse`: `--raiz` (obligatorio en Windows, por defecto `/run/media/<usuario>/<pendrive>` en Kali/Linux si existe), `--incluir-ocultos`, `--salida`, `--sin-cache`, `--formato` (texto/markdown/json).
- [x] Resumen por carpeta de primer nivel: cantidad de archivos, peso total, desglose por tipo y duración acumulada.
- [x] Salida visual limpia y legible en consola con estadísticas destacadas e informe guardable en archivo Markdown.
- **Status:** complete

### Phase 6: Pruebas y Validación Exhaustiva
- [x] Ejecución de prueba real sobre el pendrive `/run/media/<usuario>/<pendrive>`.
- [x] Verificación de seguridad (test con symlink apuntando fuera de la raíz).
- [x] Verificación de no modificación del pendrive (garantía de solo lectura).
- [x] Pruebas unitarias automatizadas con `unittest` (9 tests pasando).
- **Status:** complete

### Phase 7: Documentación y Entrega
- [x] Manual de uso completo (`README.md`), guía para Windows y Linux/Kali.
- **Status:** complete

---

## Next Step
Presentar la solución completa y el resumen de la auditoría al usuario.
