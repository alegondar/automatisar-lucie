# Proposal

## Why

El inventario de archivos y la auditoría del pendrive revelaron miles de archivos duplicados, carpetas con alta similitud de contenido (por ejemplo, `laroli` vs `videos1/laroli`), archivos sueltos sin organizar en la raíz y carpetas vacías, consumiendo gigabytes de espacio y dificultando la navegación. 

Sin embargo, aplicar modificaciones directamente sobre un almacenamiento extraíble o carpetas locales conlleva alto riesgo de pérdida de datos o desorganización accidental. Se necesita una herramienta segura de **simulación y planificación** (dry-run) que consuma el inventario y la caché existentes, aplique reglas de negocio configurables y genere un plan de limpieza auditable (`plan_limpieza.json` y `plan_limpieza.md`) bajo el marco inviolable de las **Reglas de Oro del Proyecto** (cero borrados, simulación previa obligatoria, no sobrescritura de destinos y test estático anti-borrado exhaustivo).

## What Changes

- **Nuevo módulo/generador de plan de limpieza estrictamente en simulación**: Script de solo lectura que lee el inventario/caché del pendrive y produce `plan_limpieza.json` y `plan_limpieza.md`. No implementa ninguna función de movimiento, copia, renombre o borrado en el pendrive ni en `~/Descargas`.
- **Estructura estándar de acción auditable**: Cada acción en el plan incluye `id`, `tipo`, `origen`, `destino` y `motivo`.
- **Validación de no preexistencia en destinos**: El generador del plan comprueba que las rutas de destino propuestas no existan previamente en el almacenamiento ni en el inventario para no sugerir sobrescrituras.
- **Reglas de Oro del Proyecto integradas**:
  - Prohibición absoluta de borrado y pisado ciego (`os.remove`, `os.unlink`, `os.rmdir`, `os.removedirs`, `Path.unlink`, `Path.rmdir`, `shutil.rmtree`, `shutil.move`, `os.replace`, `send2trash`, `subprocess`/`os.system` con `rm`).
  - Simulación previa obligatoria con origen y destino exactos.
  - Test estático automático (AST) que falla si detecta cualquiera de las 11 primitivas prohibidas en el código del proyecto, verificado mediante tests sintéticos.
  - Deslinde con change futuro: la ejecución real de traslados (creación exclusiva `'xb'`), recálculo post-copia, aislamiento en `_a_revisar/copias_fallidas/` sin borrar, bitácora `.jsonl`, rollback y aprobación granular se delegan a `ejecutor-plan`.
- **Gestión diferenciada de duplicados exactos (mismo hash)**:
  - **Duplicados inter-carpeta** (distintas carpetas de primer nivel): regla configurable para seleccionar la copia a conservar (prioridad `"videos completos"` > resto; desempate por fecha más reciente) y proponer mover las demás a `_a_revisar/duplicados/` preservando su ruta relativa.
  - **Duplicados intra-carpeta** (dentro de la misma carpeta de primer nivel): NO proponer movimiento; catalogarlos en "duplicados a decidir a mano" con rutas, tamaños y fechas.
- **Análisis de diferencias en carpetas sospechosas (>= 75% similitud)**:
  - Para cada par (incluyendo `laroli` vs `videos1/laroli`), listar únicamente los archivos disjuntos (presentes en una y ausentes en la otra) con ruta, tamaño y fecha.
  - No proponer fusionar ni mover carpetas completas.
- **Clasificación de archivos sueltos**:
  - Clasificación de sueltos en raíz y primer nivel mediante archivo de configuración `alias-personajes.json` (ej. `roli*`, `laroli*`, `magui*` -> `roli`; `lucie*`, `luci*` -> `lucie`; `mailen*` -> `mailen, a confirmar`).
  - Los archivos sin coincidencia se marcan como "sin clasificar" y permanecen sin acción propuesta.
- **Detección de carpetas vacías**:
  - Listado de carpetas vacías sin acción de eliminación automática.
- **Configuración editable y exclusiones**:
  - Ignorar por defecto `_a_revisar` (cuarentena) y `code` para evitar que ejecuciones sucesivas reintroduzcan duplicados, con prioridades de conservación y parámetros configurables.
- **Huella de integridad con recálculo en vivo y tolerancia FAT/exFAT**:
  - La caché SQLite se utiliza únicamente para acelerar la generación del plan. La validación pre-ejecución recalcula el hash SHA-256 leyendo el archivo físico real en streaming desde el almacenamiento en ese momento y verifica el tamaño exacto, tratando `mtime` como dato informativo con tolerancia de 2 segundos.
- **Suite de pruebas unitarias**:
  - Pruebas con `unittest` sobre pendrive simulado en `/tmp`, test estático AST verificando detección de las 11 primitivas prohibidas y test de integridad `os.utime`.

## Capabilities

### New Capabilities
- `plan-limpieza`: Generación de plan de limpieza simulado (dry-run) sobre el inventario y caché del pendrive, generando `plan_limpieza.json` y `plan_limpieza.md` con huella de integridad tolerante a FAT/exFAT, recálculo real de SHA-256 pre-ejecución, exclusión de cuarentena, diferenciación de duplicados inter vs intra-carpeta, análisis de diferencias en carpetas sospechosas, clasificación de sueltos por alias, registro de carpetas vacías y analizador estático AST anti-borrado.

### Modified Capabilities
*(Ninguna - primer ciclo de especificación del proyecto)*

## Impact

- **Código nuevo**: Módulo de generación de plan (`plan_limpieza.py`), archivo de configuración `alias-personajes.json`, archivo de configuración editable `config_limpieza.json` y analizador estático AST.
- **Archivos de salida generados**: `plan_limpieza.json` y `plan_limpieza.md` en el repositorio local.
- **Pruebas**: Nuevos tests en `test_plan_limpieza.py` usando directorios temporales en `/tmp`, test estático AST anti-borrado de 11 primitivas y test de integridad `os.utime`.
- **Dependencias**: Solo bibliotecas estándar de Python 3 (`hashlib`, `json`, `os`, `pathlib`, `fnmatch`, `unittest`, `dataclasses`, `uuid`, `ast`). Sin dependencias externas adicionales.
- **Seguridad**: Se mantiene la estricta garantía de solo lectura sobre el pendrive y las Reglas de Oro del proyecto.
