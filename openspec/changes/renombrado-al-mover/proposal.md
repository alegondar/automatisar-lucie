# Proposal: Renombrado Automático de Archivos al Mover en Bandeja de Descargas

## Why
Actualmente, al confirmar el movimiento de un lote o archivo en la bandeja de descargas, el archivo se transfiere a la sala de espera (`~/Descargas/_lucie/<personaje>/<escena>/`) conservando su nombre crudo generado por las herramientas de IA (por ejemplo, `grok-image-3545ac09-....jpg`). Esto obliga al usuario a renombrar manualmente o lidiar con nombres alfanuméricos caóticos antes de la transferencia al pendrive y su edición en CapCut en Windows. Es necesario que el renombrado ocurra de manera automática, atómica y segura en el mismo momento del traslado (`os.rename`), asignando nombres limpios y homogéneos de la forma `<base><número>.<ext>` con contadores separados para fotos y videos, garantizando continuidad de numeración y prevención estricta de colisiones sin pisado ni pérdida de datos.

## What Changes
- **Cálculo de base del nombre de escena:**
  - Si la escena ya comienza con el personaje o alguno de sus alias conocidos (`alias-personajes.json` o set base de `FiltroListaBlanca`), la base del nombre es la escena tal cual (ej. personaje `lucie`, escena `lucietrapitos` $\rightarrow$ base `lucietrapitos`).
  - Si no comienza con el alias, la base se compone como `<personaje><escena>` (ej. personaje `lucie`, escena `trapitos` $\rightarrow$ base `lucietrapitos`).
  - La base se normaliza siempre en minúsculas y sin espacios adicionales.
- **Contadores de numeración independientes por tipo:**
  - Contadores separados para imágenes (`.jpg`, `.jpeg`, `.png`, `.webp`) y videos (`.mp4`, `.mov`, `.webm`):
    - Fotos: `<base>1.jpg`, `<base>2.png`, etc.
    - Videos: `<base>1.mp4`, `<base>2.mov`, etc.
  - Formato compacto `<base><número>` pegado, sin guiones ni ceros a la izquierda. Extensión normalizada a minúscula.
- **Orden de asignación y continuidad numérica:**
  - Dentro de un lote, los archivos se ordenan cronológicamente por `mtime` ascendente (desempate por nombre original).
  - Si la carpeta de destino ya contiene archivos de esa misma base y tipo (por lotes previos o reapertura de capítulo), la numeración continúa a partir del número máximo existente $+ 1$, sin sobrescribir ni repetir índices.
- **Prevención de colisiones case-insensitive y atómica:**
  - Detección de colisiones insensible a mayúsculas y minúsculas (pensado para compatibilidad con sistemas FAT32/exFAT del pendrive destino).
  - Garantía de que dos archivos en una misma simulación no compartan destino.
  - Re-verificación de inexistencia en destino justo antes de invocar `os.rename`, manteniendo el sufijo correlativo ` (1)` exclusivamente como red de seguridad final.
- **Soporte universal en movimientos:**
  - Aplica a lotes individuales, movimientos multi-lote ("Mover lotes listos") y traslados hacia escenas preexistentes en `~/Descargas`.
- **Transparencia en simulación y UI:**
  - `simular_movimiento_lote` proyecta los nombres calculados.
  - `generar_html_simulacion` y el modal de simulación muestran con claridad `nombre_original -> nombre_nuevo` y la ruta destino completa en el tooltip.
  - Eliminación definitiva de etiquetas visuales obsoletas (`imagenes`, `videos sin editar`) en el modal.
  - Limpieza de la clave legada `carpeta_imagenes` en `config_bandeja.json` y en el código de bandeja.
- **Auditoría, bitácora y reversibilidad estricta:**
  - Cada registro de movimiento en `bitacora_bandeja.jsonl` incorpora `nombre_original` y `nombre_nuevo`, manteniendo retrocompatibilidad con registros preexistentes.
  - La función `deshacer_operacion` restaura el archivo a su ubicación y nombre original de descarga con `os.rename`. Si el origen original está ocupado, el deshacer se niega rotundamente sin pisar ni sufijar.
  - La base de datos SQLite (`bandeja_archivos.ruta_actual`) refleja la ruta con el nombre nuevo tras mover y la ruta con el nombre original tras deshacer.

## Capabilities

### New Capabilities
- `renombrado-al-mover`: Capacidad que rige las reglas de normalización de base, contadores independientes por tipo de medio, continuidad secuencial, prevención de colisiones case-insensitive, visualización en simulación y reversibilidad con nombre original en la bandeja de descargas.

### Modified Capabilities
*(Ninguna spec previa fue consolidada en `openspec/specs/`; todos los requerimientos anteriores pertenecen a cambios en curso o completados no archivados).*

## Impact
- **Código operativo:**
  - `bandeja_descargas.py`: Métodos de `GestorMovimientosBandeja` (`simular_movimiento_lote`, `ejecutar_movimiento_lote`, `deshacer_operacion`, `obtener_historial`), función `generar_html_simulacion`, clases de configuración y remoción de `carpeta_imagenes`.
- **Configuración:**
  - `config_bandeja.json`: Eliminación de la clave obsoleta `carpeta_imagenes`.
- **Persistencia y datos:**
  - `bitacora_bandeja.jsonl`: Nuevos campos `nombre_original` y `nombre_nuevo` en transacciones futuras, manteniendo compatibilidad de lectura con líneas previas.
  - `bandeja_archivos` (SQLite): El campo `ruta_actual` almacena la ruta con el nuevo nombre al mover y se restaura al nombre original al deshacer.
- **Pruebas:**
  - `test_bandeja_descargas.py`: Nuevos casos de prueba unitaria para validar contadores separados, escenas con/sin alias, continuidad secuencial, colisiones case-insensitive, multi-lote, reversión y compatibilidad de bitácora.
