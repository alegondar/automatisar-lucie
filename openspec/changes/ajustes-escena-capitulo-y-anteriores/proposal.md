# Propuesta: Ajustes de Escena de Capítulo y Lotes Anteriores

## Contexto y Motivación
En el flujo de trabajo de `bandeja_descargas.py`, se identificaron dos problemas clave que afectaban la experiencia de uso al ordenar material:

1. **Problema 1 - La carpeta del capítulo no existía hasta mover el primer archivo:**
   Al "Empezar capítulo" (ej. `lucie/olor a culo`), el capítulo se registraba en SQLite pero su carpeta física en `~/Descargas/_lucie/<personaje>/<nombre>/` no se creaba hasta mover un archivo. Con 0 archivos movidos, el desplegable "Escena" no ofrecía la carpeta, el campo quedaba vacío y la validación exigía ingresar un nombre ("no puede estar vacío").
   - Solución: crear la carpeta al empezar el capítulo y al reabrirlo con `os.makedirs(..., exist_ok=True)` validando nombre y confinamiento; informar si ya existía con archivos; ofrecer `[Capítulo activo] <nombre>` como primera opción preseleccionada en el desplegable sin duplicados; y al descartar el capítulo, mover la carpeta a `_descartados` incluso si está vacía.

2. **Problema 2 - Lotes de "Anteriores" con archivos tildados y causa raíz:**
   Lotes de material anterior al capítulo (con `lucie*.mp4` y `lucie*.png`) podían aparecer con checkboxes tildados y botón de mover activo si se armaban con mtime mixto o retenían clasificaciones previas.
   - Solución: todo lote y archivo de "Anteriores" debe renderizarse siempre destildado, sin escena preasignada y sin preselección. Si un lote tiene mtime mixto (archivos anteriores y nuevos), debe partirse estrictamente de forma que los anteriores nunca contaminen los lotes recientes ni queden tildados.

## Objetivos
- Crear de forma segura la carpeta de capítulo al empezar o reabrir, alertando si ya contenía archivos sin tocar nada existente.
- Ofrecer `[Capítulo activo] <nombre>` preseleccionada como primera opción en el desplegable de escena para lotes del capítulo activo, omitiendo duplicados en `[Destino]`.
- Mostrar en simulación el personaje y la ruta resultantes cuando el lote cambie de personaje respecto al capítulo.
- Permitir que "Descartar capítulo" traslade la carpeta vacía a `_descartados` mediante `os.rename`, preservando el soporte de deshacer.
- Garantizar que los lotes mixtos se dividan y que ningún archivo anterior se muestre tildado ni con escena preasignada.
- Respetar rigurosamente las 7 Reglas de Oro (sin primitivas de borrado ni pisado, 0 infracciones AST).

## Impacto
- `bandeja_descargas.py`: lógica de backend (creación y validación de carpeta, separación estricta de lotes en `AgrupadorLotes`, soporte de descarte de carpeta vacía) y frontend web (desplegable con `[Capítulo activo]`, lotes anteriores destildados).
- `test_bandeja_descargas.py`: cobertura exhaustiva de creación, reutilización, traversal, desplegable, división de lotes mixtos y descarte de carpetas vacías.
