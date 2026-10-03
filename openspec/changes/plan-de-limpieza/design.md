# Design

## Context

El proyecto cuenta con `inventario_pendrive.py` para la auditoría de almacenamiento extraíble en solo lectura. Este diseño define la arquitectura técnica para `plan_limpieza.py` y sus archivos auxiliares de configuración, delimitando con precisión su alcance:

- **Alcance de este change (`plan-de-limpieza`)**: Es **estrictamente de simulación (dry-run) y validación estática**. Genera `plan_limpieza.json` y `plan_limpieza.md` en el repositorio local. No contiene ninguna función que mueva, copie, renombre o escriba dentro del pendrive ni de `~/Descargas`. Valida que las rutas de destino propuestas en el plan no existan previamente.
- **Deslinde con change futuro (`ejecutor-plan`)**: Las tareas de ejecución física (traslado con creación exclusiva `'xb'`, recálculo de hash post-copia, aislamiento a `_a_revisar/copias_fallidas/` en caso de discrepancia, registro en bitácora `.jsonl`, rollback y aprobación granular) quedan reservadas para el change `ejecutor-plan`. En este change rigen como principios rectores en `openspec/config.yaml`.
- **Reglas de Oro del Proyecto**: Prohibición absoluta de borrado y pisado ciego, simulación previa obligatoria, test estático AST anti-borrado exhaustivo.

Para la motivación general, ver `proposal.md`. Para los requerimientos normativos, ver `specs/plan-limpieza/spec.md`.

## Goals / Non-Goals

**Goals:**
- Implementar `plan_limpieza.py` en modo 100% simulación (dry-run) consumiendo el inventario y caché existentes.
- Estructurar acciones con esquema unificado: `{ "id": int|str, "tipo": str, "origen": str, "destino": str|null, "motivo": str, "detalles": dict }`.
- Validación de no preexistencia en destinos propuestos: el generador verifica contra el inventario y disco que la ruta `destino` sugerida no exista previamente.
- Manejo diferenciado de duplicados exactos:
  - **Duplicados con copia en carpetas protegidas** (`carpetas_protegidas` como `laroli`, `videos1/laroli`): catalogados en "duplicados a decidir a mano" sin propuesta de movimiento (`destino: null`), reportando todas las rutas, tamaños y fechas del grupo.
  - **Duplicados inter-carpeta sin copias protegidas**: regla de conservación (`videos completos` > resto; mtime más reciente) y propuesta de traslado hacia `_a_revisar/duplicados/` preservando rutas relativas.
  - **Duplicados intra-carpeta**: catalogados en "duplicados a decidir a mano" sin propuesta de movimiento (`destino: null`).
- Exclusión obligatoria por defecto de `_a_revisar` (cuarentena) y `code`.
- Configuración de carpetas protegidas (`carpetas_protegidas`) para salvaguardar carpetas sensibles contra movimientos de duplicados.
- Análisis diferencial exhaustivo de carpetas sospechosas (>= 75% similitud) con ruta, tamaño y fecha de archivos disjuntos (sin fusiones masivas).
- Clasificación de sueltos por `alias-personajes.json`, dejando los no emparejados en "sin clasificar" (`destino: null`).
- Registro informativo de carpetas vacías (`destino: null`).
- Huella de integridad con recálculo de SHA-256 en vivo leyendo el archivo físico real en streaming (sin consultar la base SQLite para validar) y tolerancia de 2s para mtime en sistemas FAT/exFAT.
- Implementar un analizador estático basado en AST que detecte exhaustivamente las 11 primitivas prohibidas de borrado y pisado, con tests que verifiquen la detección de cada una y aseguren que el código del proyecto está limpio.

**Non-Goals:**
- **Cero operaciones de escritura/traslado en este change**: No implementar ninguna función que copie, mueva, renombre, borre o escriba en el pendrive o `~/Descargas`. Todo el código de ejecución se delega a `ejecutor-plan`.
- **No borrar en rollbacks**: "Revertir" jamás implicará borrar; si una copia falla, se aísla en `_a_revisar/copias_fallidas/`.

## Decisions

### 1. Módulo dedicado `plan_limpieza.py` (Solo Simulación)
- **Decisión**: Crear `plan_limpieza.py` como un módulo independiente que importe las utilidades y clases de datos de `inventario_pendrive.py` (`ArchivoInfo`, `esta_dentro_de_raiz`, `CacheInventario`, `AuditorPendrive`, `formatear_bytes`).
- **Garantía absoluta**: No expone funciones destructivas ni de mutación sobre la raíz analizada. Únicamente escribe `plan_limpieza.json` y `plan_limpieza.md` en el repositorio local.
- **Validación de no preexistencia**: Durante la formulación del plan, el generador comprueba si cualquier `destino` calculado ya existe en el árbol del pendrive. Si existiera, la acción no propone movimiento a esa ruta y se marca como conflicto para evitar sugerir sobrescrituras.

### 2. Archivos de configuración desacoplados: `config_limpieza.json` y `alias-personajes.json`
- **Decisión**:
  - `config_limpieza.json`:
    ```json
    {
      "carpetas_ignoradas": ["_a_revisar", "code", "System Volume Information", "$RECYCLE.BIN", ".Trash-*"],
      "carpetas_protegidas": ["laroli", "videos1/laroli"],
      "umbral_similitud_carpetas": 0.75,
      "prefijo_destino_duplicados": "_a_revisar/duplicados",
      "reglas_duplicados": {
        "prioridad_carpetas": ["videos completos"],
        "criterio_desempate": "mas_reciente"
      },
      "tolerancia_mtime_segundos": 2.0,
      "ruta_alias_personajes": "alias-personajes.json"
    }
    ```
  - `alias-personajes.json`:
    ```json
    {
      "reglas": [
        {
          "patrones": ["roli*", "laroli*", "magui*"],
          "personaje": "roli",
          "destino_carpeta": "roli",
          "requiere_confirmacion": false
        },
        {
          "patrones": ["lucie*", "luci*"],
          "personaje": "lucie",
          "destino_carpeta": "lucie",
          "requiere_confirmacion": false
        },
        {
          "patrones": ["mailen*"],
          "personaje": "mailen",
          "destino_carpeta": "mailen",
          "requiere_confirmacion": true,
          "nota": "a confirmar"
        }
      ]
    }
    ```

### 3. Modelo unificado de acción del plan
- **Decisión**:
  ```json
  {
    "id": 1,
    "tipo": "mover_duplicado",
    "origen": "videos1/roli/clip.mp4",
    "destino": "_a_revisar/duplicados/videos1/roli/clip.mp4",
    "motivo": "Duplicado inter-carpeta de 'videos completos/roli/clip.mp4'.",
    "detalles": {
      "sha256": "abc...",
      "tamanio_bytes": 1048576,
      "copia_conservada": "videos completos/roli/clip.mp4"
    }
  }
  ```

### 4. Huella de integridad y validación pre-ejecución en vivo
- **Decisión**: 
  - La base SQLite se usa **únicamente** para generar el plan sin re-hashear el pendrive completo.
  - El validador pre-ejecución lee en streaming los bytes reales del disco en ese momento, calcula el SHA-256 en vivo y compara el tamaño exacto y el hash contra la huella.
  - El campo `mtime` se trata como informativo con tolerancia de 2 segundos para acomodar las peculiaridades de FAT/exFAT. Si el contenido fue alterado aunque se conserve el tamaño y se restaure `mtime` con `os.utime`, el recálculo de SHA-256 aborta la operación inmediatamente con `HuellaInvalidaError`.

### 5. Analizador estático AST anti-borrado exhaustivo
- **Decisión**: Crear un módulo/utilidad de análisis sintáctico que analice el AST de Python e identifique cualquier llamada a las 11 primitivas prohibidas:
  1. `os.remove`
  2. `os.unlink`
  3. `os.rmdir`
  4. `os.removedirs`
  5. `Path.unlink`
  6. `Path.rmdir`
  7. `shutil.rmtree`
  8. `shutil.move` (copia y borra al cruzar filesystems)
  9. `os.replace` (pisa el destino sin avisar)
  10. `send2trash`
  11. `subprocess` / `os.system` con comandos que invoquen `rm` o `rmdir`
- **Estrategia de prueba**:
  - Test unitario parametrizado con fragmentos sintéticos de código conteniendo cada una de las 11 primitivas, verificando que el analizador reporte infracción en el 100% de los casos.
  - Test unitario que recorre todos los archivos `.py` del código operativo del proyecto y valida que no contengan ninguna infracción.

## Risks / Trade-offs

- **[Riesgo] Destino propuesto que colisiona con un archivo preexistente.**
  → *Mitigación*: Verificación estricta en el generador del plan que comprueba que la ruta de destino no exista previamente.
- **[Riesgo] Alteración silenciosa de archivos en el pendrive tras emitir el plan.**
  → *Mitigación*: Recálculo real en streaming del SHA-256 sobre el archivo físico durante la pre-validación.
- **[Riesgo] Invocación inadvertida de primitivas de borrado o reemplazo destructivo.**
  → *Mitigación*: El test AST inspecciona exhaustivamente el código del repositorio, bloqueando cualquier función prohibida.

## Migration Plan

1. Fase 1: Creación de archivos de configuración por defecto (`config_limpieza.json` con `_a_revisar` y `alias-personajes.json`).
2. Fase 2: Implementación de la lógica del generador en `plan_limpieza.py` (simulación pura, chequeo de no preexistencia de destino, duplicados inter vs intra, huella con tamaño+hash en vivo, exclusión de `_a_revisar`).
3. Fase 3: Pruebas unitarias en `test_plan_limpieza.py` (analizador AST con verificación de las 11 primitivas prohibidas, test de mutación de contenido con `os.utime`, y tests de plan).
4. Fase 4: Ejecución en modo simulación sobre el pendrive real usando la caché existente para emitir `plan_limpieza.json` y `plan_limpieza.md`.
5. Delegación a change futuro: La ejecución real de movimientos, bitácora `.jsonl` y rollback se implementarán en el change `ejecutor-plan`.
