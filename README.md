# 🔍 Auditoría e Inventario Integral de Pendrive (Solo Lectura)

Script en Python multiplataforma (**Kali Linux** y **Windows**) para auditar, inventariar y analizar todo el contenido de un pendrive o unidad de almacenamiento externo sin modificarlo jamás.

---

## 🚀 Características Principales

1. **Garantía Estricta de Solo Lectura:**
   - **No escribe ni modifica nada dentro del pendrive.**
   - La base de datos de caché SQLite (`.cache/inventario_pendrive_cache.sqlite`) y los informes generados se guardan **exclusivamente en el repositorio local**.
   - El script valida y rechaza cualquier intento de almacenar caché o informes dentro de la unidad analizada.

2. **Seguridad y Confinamiento de Rutas:**
   - Resuelve cada ruta mediante `os.path.realpath`.
   - Verifica el límite con `os.path.commonpath`.
   - Symlinks o rutas que apunten fuera de `--raiz` son descartados de inmediato con advertencia de seguridad.

3. **Exclusiones de Sistema y Archivos Ocultos:**
   - Ignora automáticamente carpetas de sistema: `System Volume Information`, `$RECYCLE.BIN`, `.Trash-*`, `lost+found`.
   - Ignora archivos y carpetas ocultos por defecto.
   - Opción `--incluir-ocultos` disponible para auditarlos si se desea.

4. **Clasificación por Tipo de Archivo:**
   - Categorías: `video`, `foto`, `audio`, `documento`, `subtítulo`, `otro`.
   - **ffprobe:** La extracción de duración multimedia aplica **únicamente a archivos de video** (tolerante a fallos y timeouts).

5. **Detección Avanzada de Duplicados (Cross-Folder):**
   - Detección en TODO el pendrive, incluso entre carpetas con distinto tipo de contenido (ej: la misma foto en dos carpetas diferentes o con nombres distintos).
   - Optimización en 2 fases: agrupación inicial por tamaño en bytes (descarta tamaños únicos al instante) y cálculo SHA-256 en bloques de 1MB por streaming.

6. **Carpetas Vacías y Carpetas Duplicadas:**
   - Identificación de carpetas vacías (sin archivos válidos tras los filtros).
   - Detección de carpetas sospechosas por:
     - 100% contenido idéntico (mismos hashes).
     - Alta similitud de contenido (>=75%).
     - Similitud de nombres (ej: copias redundantes).

7. **Auditoría de Archivos Sueltos:**
   - Archivos sueltos en la raíz del pendrive (`raiz/archivo.ext`).
   - Archivos sueltos en la raíz de cada carpeta de primer nivel (`raiz/carpeta1/archivo.ext`).

8. **Caché Persistente en Repositorio:**
   - Reduce el tiempo de análisis de **~47 segundos** a **~0.3 segundos** en escaneos posteriores.

---

## 💻 Requisitos y Compatibilidad

- **Python 3.8+** (Probado en Python 3.13).
- **Librerías estándar:** No requiere `pip install` de paquetes de terceros.
- **ffprobe (FFmpeg):** Opcional pero recomendado para calcular duración de videos (`apt install ffmpeg` en Debian/Kali/Ubuntu o FFmpeg en Windows).

---

## 🛠️ Modos de Uso

### En Kali / Debian / Ubuntu Linux:
```bash
# Especificando ruta de montaje:
python3 inventario_pendrive.py --raiz /run/media/<usuario>/<punto-de-montaje>

# Sin --raiz: busca un pendrive vinculado y pide confirmación explícita:
python3 inventario_pendrive.py

# Incluyendo archivos y carpetas ocultos:
python3 inventario_pendrive.py --incluir-ocultos

# Exportando informe a formato JSON:
python3 inventario_pendrive.py --formato json --salida informe.json

# Forzar recálculo completo sin usar la caché local:
python3 inventario_pendrive.py --sin-cache
```

### En Windows:
```cmd
python inventario_pendrive.py --raiz E:\
python inventario_pendrive.py --raiz F: --salida informe_windows.md
```

---

## 📋 Parámetros de la Línea de Comandos

| Parámetro | Requerido | Descripción |
| :--- | :---: | :--- |
| `--raiz` | No* | Punto de montaje o letra de unidad (ej: `/run/media/<usuario>/<punto-de-montaje>` o `E:\`). Si no se pasa, busca un pendrive vinculado y pide confirmación explícita. |
| `--incluir-ocultos` | No | Incluye archivos y carpetas ocultos (empiezan con `.` o atributos ocultos). |
| `--salida` | No | Ruta del informe de salida (por defecto `informe_pendrive.md` en el repo). |
| `--formato` | No | Formato del informe: `markdown` (defecto), `json` o `texto`. |
| `--sin-cache` | No | Desactiva la caché y fuerza recálculo de hashes y duraciones. |
| `--limpiar-cache` | No | Borra la base de datos de caché antes de comenzar. |
| `--verboso` | No | Muestra mensajes detallados paso a paso. |

---

## 🧪 Pruebas Automatizadas

El proyecto cuenta con una suite completa de pruebas unitarias que valida seguridad de rutas, symlinks, clasificación, duplicados cross-folder y exclusiones de sistema:

```bash
python3 test_inventario.py
```
Resultado:
```
Ran 9 tests in 0.010s
OK
```
