# Proposal: Subcarpetas de Fotos y Videos por Capítulo y Renombrado Total

## Why

Actualmente, los archivos clasificados y movidos a una escena dentro de un capítulo se ubican todos juntos en la raíz de la carpeta de la escena (`~/Descargas/_lucie/<personaje>/<escena>/`). A medida que un capítulo acumula decenas de fotos y videos, la carpeta se vuelve difícil de navegar y mezclar tipos de archivo complica la edición y el consumo posterior. Además, existían excepciones parciales donde ciertos archivos con nombres particulares no se estandarizaban al formato canónico `<base><n>.<ext>`.

Este cambio introduce la organización automática en subcarpetas especializadas (`fotos/` y `videos/`) por escena, asegurando que las subcarpetas se creen de manera perezosa (solo al mover el primer archivo de ese tipo), que todos los archivos multimedia se renombren estrictamente sin excepciones conservando la numeración continua acumulada (considerando tanto archivos sueltos históricos en la raíz como en las subcarpetas), que extensiones desconocidas se trasladen a la raíz con advertencia y preservando su nombre original, y que las operaciones de balance, descarte de capítulo, verificación de colisiones y detección de escenas manejen la recursividad sin exponer jamás `fotos` o `videos` como escenas.

## What Changes

- **Configuración configurable (`config_bandeja.json`)**:
  - Inclusión de `"subcarpeta_fotos": "fotos"` y `"subcarpeta_videos": "videos"`.
- **Clasificación y ruteo a subcarpetas por tipo multimedia**:
  - Fotos (`.jpg`, `.jpeg`, `.png`, `.webp`) se destinan a `<carpeta_escena>/fotos/<base><n>.<ext>`.
  - Videos (`.mp4`, `.mov`, `.webm`) se destinan a `<carpeta_escena>/videos/<base><n>.<ext>`.
  - Extensiones desconocidas/no multimedia: no se mueven a ciegas. La simulación muestra advertencia visual explícita y, al confirmar, se mueven a la raíz de la escena (`<carpeta_escena>/<nombre_original>`) preservando su nombre original sin sobreescritura.
- **Creación perezosa y confinada de subcarpetas**:
  - Las subcarpetas `fotos/` y `videos/` se crean únicamente en el momento en que se efectiviza el movimiento del primer archivo de esa familia (`os.makedirs(..., exist_ok=True)` con verificación estricta de confinamiento mediante `os.path.realpath` dentro de `ruta_destino_base`). Nunca se crean vacías por adelantado.
- **Renombrado total sin excepciones**:
  - Se eliminan todas las excepciones que conservaban nombres previos del usuario (ej. `lucierascadapatalon.mp4`, `lucieoliendoselamano.png`).
  - Todo archivo multimedia toma el nombre normalizado `<base><n>.<ext>` respetando la base del personaje, nombre de escena compactado sin espacios, orden por `mtime` y desempate por nombre.
- **Numeración continua e insensible a mayúsculas/minúsculas**:
  - El contador de cada familia continúa a partir del número máximo encontrado en la subcarpeta del tipo, en la raíz de la escena (archivos históricos previos al cambio) y en cualquier otra subcarpeta de tipo.
  - Comparación insensible a mayúsculas (`case-insensitive`) para compatibilidad total con sistemas de archivos FAT/exFAT.
  - Mecanismo de seguridad con sufijo `" (1)"` en caso de colisión física imprevista.
- **Simulación previa y visualización en interfaz web**:
  - El modal de simulación muestra claramente `nombre original -> nombre nuevo` y la ruta relativa de destino completa incluyendo la subcarpeta (ej. `lucie / oloraculo / videos / lucieoloraculo3.mp4`).
  - Advertencia destacada si un lote incluye archivos de extensiones no multimedia que irán a la raíz.
- **Bitácora, base de datos y deshacer estricto**:
  - Registro de `nombre_original`, `nombre_nuevo` y ruta final con subcarpeta.
  - Deshacer restaura el archivo con su nombre original a su ubicación origen (o falla de forma segura si el origen está ocupado).
  - Si una subcarpeta queda vacía tras un deshacer, NO se elimina (cero llamadas a `rmdir` o primitivas destructivas).
- **Descarte de capítulo y balances recursivos**:
  - `descartar_capitulo` cuenta, simula y traslada recursivamente todo el árbol de la carpeta (incluyendo subcarpetas), validando integridad con hashes SHA-256 idénticos antes y después del traslado.
  - Los balances de "Movidos", "Pendientes", "Terminar capítulo" y el aviso de carpeta existente contabilizan recursivamente (raíz + subcarpetas).
- **Aislamiento de nombres reservados**:
  - Las carpetas `fotos` y `videos` se excluyen de la detección de escenas y capítulos: jamás se listan como opciones en los desplegables.
- **Compatibilidad hacia atrás**:
  - Capítulos preexistentes con archivos sueltos en la raíz no se migran forzosamente ni se alteran; los nuevos archivos que se incorporen usarán las subcarpetas y continuarán la numeración sin duplicados.

## Capabilities

### New Capabilities
- `subcarpetas-fotos-videos`: Organización jerárquica de archivos por subcarpetas (`fotos/`, `videos/`, raíz para otros), renombrado universal forzoso `<base><n>.<ext>`, numeración incremental multi-nivel, y preservación de compatibilidad con exclusión de escenas reservadas y balance recursivo.

### Modified Capabilities
<!-- No requirement changes to existing specs -->

## Impact

- **Código**:
  - `bandeja_descargas.py`: Ajustes en `ConfiguracionBandeja`, `GestorMovimientosBandeja` (cálculo de contadores recursivos, simulación de rutas con subcarpetas, creación confinada al mover, advertencia de otros tipos, renombrado total sin excepciones), filtros de escaneo en `VigilanteBandeja` y `FiltroListaBlanca` para excluir `fotos` y `videos` de escenas, conteo recursivo en descarte de capítulos y avisos de carpetas existentes, y modal de simulación en frontend.
  - `config_bandeja.json`: Claves `"subcarpeta_fotos"` y `"subcarpeta_videos"`.
- **Base de Datos y Bitácora**:
  - Registro transparente de rutas finales con subcarpeta en `archivos_recientes.jsonl` y `bandeja.db`.
- **Pruebas**:
  - `test_bandeja_descargas.py`: Casos de prueba específicos que validan ruteo por tipo, renombrado incondicional, creación perezosa, continuidad de numeración (raíz vs subcarpetas), colisión case-insensitive, extensiones desconocidas a raíz con aviso, reversibilidad en deshacer sin borrado de carpetas, descarte recursivo de capítulo y exclusión de carpetas reservadas en selectores.
