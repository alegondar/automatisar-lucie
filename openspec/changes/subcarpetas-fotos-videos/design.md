# Design: Subcarpetas de Fotos y Videos por Capítulo y Renombrado Total

## Context

Actualmente `GestorMovimientosBandeja` traslada los archivos directamente a `<carpeta_destino_base>/<personaje>/<escena>/`. Todos los archivos (imágenes y videos) comparten el mismo directorio raíz de la escena. Aunque se contaba con lógica de renombrado `<base><n>.<ext>`, existían excepciones que dejaban nombres previos intactos y la numeración sólo examinaba la carpeta plana.

El sistema debe evolucionar para segregar automáticamente en subcarpetas `fotos/` y `videos/`, aplicar un renombrado estricto sin excepciones a todo material multimedia, mantener la numeración correlativa contemplando el inventario histórico (archivos sueltos en la raíz y en subcarpetas), tratar extensiones no multimedia con advertencias sin pérdida de nombres, y asegurar que todas las operaciones auxiliares (descarte de capítulos, balance, deshecho y detección de escenas) operen respetando las Reglas de Oro del proyecto.

## Goals / Non-Goals

**Goals:**
- Clasificar por extensión y rutear fotos a `<escena>/fotos/` y videos a `<escena>/videos/`.
- Crear las subcarpetas de manera estrictamente perezosa (al mover el primer archivo).
- Renombrado total obligatorio de todo archivo multimedia a `<base><n>.<ext>`.
- Numeración unificada continua calculando el máximo entre la raíz de la escena, la subcarpeta del tipo y otras subcarpetas.
- Rutear extensiones desconocidas a la raíz de la escena con advertencia y conservando su nombre original.
- Mostrar la subcarpeta en la ruta relativa del modal de simulación (`personaje / escena / videos / archivo.mp4`).
- Conteo recursivo en `descartar_capitulo`, balances y avisos de carpetas existentes.
- Exclusión total de los nombres `fotos` y `videos` en el listado de escenas existentes.
- Deshacer no destructivo: nunca borrar subcarpetas con `rmdir`, aun si quedan vacías.
- Cumplimiento de cero infracciones AST contra primitivas destructivas.

**Non-Goals:**
- Migración automática retroactiva de archivos preexistentes ya ubicados en la raíz de escenas históricas.
- Soporte para subcarpetas adicionales personalizadas definidas por el usuario más allá de las configuradas en `config_bandeja.json`.

## Decisions

### Decisión 1: Ruteo por extensión y creación perezosa
- **Elección**: Definir en `ConfiguracionBandeja` las claves `subcarpeta_fotos` ("fotos") y `subcarpeta_videos` ("videos").
- **Implementación**: Durante la simulación, si el archivo es foto se asigna `subcarpeta = self.subcarpeta_fotos`; si es video, `subcarpeta = self.subcarpeta_videos`; si no es ninguno, `subcarpeta = ""` (raíz). En la ejecución del movimiento se invoca `os.makedirs(os.path.dirname(ruta_destino), exist_ok=True)` inmediatamente antes del movimiento con creación exclusiva.
- **Alternativas consideradas**:
  - *Crear de antemano ambas carpetas al crear una escena*: Descartada porque generaría carpetas vacías si una escena solo contiene videos o solo fotos, ensuciando la estructura de carpetas.

### Decisión 2: Renombrado total incondicional
- **Elección**: Eliminar cualquier bifurcación de código o excepción que respete nombres originales como `lucierascadapatalon.mp4`.
- **Implementación**: Para fotos y videos, el nombre resultante es obligatoriamente `f"{base}{num}{ext_lower}"`.
- **Alternativas consideradas**:
  - *Ofrecer un checkbox "conservar nombre original"*: Descartada porque contradice la directiva explícita del usuario de renombrado total universal y orden uniforme.

### Decisión 3: Escaneo recursivo para numeración continua y desempate case-insensitive
- **Elección**: En `obtener_contadores_carpeta_destino`, recorrer con `os.walk` o inspección de subdirectorios la raíz de la escena y todas sus subcarpetas.
- **Implementación**: Se extrae el número del patrón `^{base}(\d+)(?:\s*\(\d+\))?\.([a-zA-Z0-9]+)$` de manera insensible a mayúsculas (`re.IGNORECASE`). Los contadores calculados serán `max(encontrados) + 1` para cada familia. Si al resolver la ruta final física se detecta colisión (por ejemplo por mayúsculas/minúsculas en FAT/exFAT o presencia física simultánea), se aplica sufijo de seguridad `" (1)"`.
- **Alternativas consideradas**:
  - *Reiniciar el contador en 1 dentro de cada subcarpeta*: Descartada porque crearía colisiones con archivos sueltos históricos que ya estuvieran en la raíz antes de la introducción de las subcarpetas.

### Decisión 4: Tratamiento de extensiones no multimedia
- **Elección**: Rutear a la raíz de la carpeta de la escena (`<escena>/<nombre_original>`).
- **Implementación**: En la simulación se marca `es_otro_tipo = True` y se genera una advertencia visible. El archivo conserva su nombre original y nunca se sobrescribe.
- **Alternativas consideradas**:
  - *Rechazar el movimiento de archivos desconocidos*: Descartada porque el usuario puede desear archivar notas o archivos auxiliares en la escena confirmando la acción.

### Decisión 5: Exclusión de `fotos` y `videos` en descubrimiento de escenas
- **Elección**: En `VigilanteBandeja.escanear` y `FiltroListaBlanca.es_carpeta_escena_existente`, filtrar cualquier carpeta con nombre `fotos` o `videos` (case-insensitive).
- **Implementación**: Prevenir que aparezcan como escenas en el selector de la interfaz web o como carpetas de capítulos huérfanos.

### Decisión 6: Deshacer no destructivo y descarte de capítulos recursivo
- **Elección**: `deshacer_operacion` sólo revierte el archivo al origen. No ejecuta `rmdir` ni limpia subcarpetas vacías.
- **Implementación**: `descartar_capitulo` inspecciona el árbol completo con `os.walk` para generar la lista de archivos a trasladar a `_descartados`, calculando hashes antes y después para cada uno.

## Risks / Trade-offs

- **[Riesgo] Carpetas `fotos` o `videos` creadas previamente como escenas por un usuario**:
  - *Mitigación*: La exclusión de nombres reservados protege de ambigüedades; si existía una escena llamada `fotos`, queda aislada de la clasificación de subcarpetas automáticas.
- **[Riesgo] Colisión en sistemas de archivos case-insensitive (FAT/exFAT)**:
  - *Mitigación*: Se utiliza comparación normalizada a minúsculas al evaluar nombres existentes y se mantiene la verificación de destino previo con sufijo `" (1)"`.
- **[Riesgo] Violación de la regla AST anti-borrado al intentar limpiar carpetas vacías**:
  - *Mitigación*: Directiva estricta de no incluir `rmdir`, `removedirs`, `rmtree` ni ningún comando de eliminación en el código.
