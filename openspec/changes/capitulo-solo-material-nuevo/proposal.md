# Proposal: Adopción Exclusiva de Material Nuevo por Capítulo y Base de Nombre Compacta

## Why
Actualmente en la bandeja de descargas (`bandeja_descargas.py`), al iniciar un capítulo activo ("Empezar capítulo"), la lógica de asignación universal adopta de forma indiscriminada TODO el material multimedia preexistente en `~/Descargas` (incluso archivos descargados semanas o meses atrás como fotos `FB_IMG_*.jpg`). El sistema agrupaba estos archivos viejos en lotes con el capítulo recién iniciado preasignado, los dejaba marcados (`checked`) y con el nombre de escena precargado.

Esto contradice el flujo de trabajo: un capítulo nuevo debe adoptar automáticamente **únicamente el material nuevo** generado o descargado a partir de su inicio. Todo archivo anterior debe tratarse como material de respaldo (sin asignación forzada al capítulo, sin preselección y sin escena precargada), presentándose en una sección secundaria colapsada para no entorpecer el lote actual ni ser trasladado accidentalmente con "Mover lotes listos".

Asimismo, el mecanismo de renombrado automático producía nombres con espacios cuando el usuario ingresaba nombres de escena con separación visual (por ejemplo, "lucie trapitos" generaba `lucie trapitos1.jpg`). Se requiere compactar la base eliminando espacios internos ("lucie trapitos" $\rightarrow$ `lucietrapitos1.jpg`) mientras se preserva el nombre original para la carpeta destino y se asegura la consistencia con la deducción de personaje.

## What Changes
1. **Adopción exclusiva por marca de tiempo (`mtime >= fecha_inicio`):**
   - El escáner (`VigilanteBandeja.escanear`) compara el `st_mtime` de cada archivo contra la `fecha_inicio` del capítulo activo registrada en `bandeja_capitulos`.
   - Se introduce un margen de gracia configurable en `config_bandeja.json`: `"minutos_antes_inicio_capitulo": 0` (por defecto 0). El corte temporal se calcula como `ts_corte = fecha_inicio - (minutos_antes_inicio_capitulo * 60)`.
   - Solo los archivos con `mtime >= ts_corte` son adoptados automáticamente por el capítulo activo.
2. **Tratamiento de archivos anteriores al inicio:**
   - Los archivos con `mtime < ts_corte` NO se asignan al capítulo activo ni se preseleccionan.
   - Si coinciden con alias o patrones de IA (`grok-*`, `Gemini_Generated_Image_*`, `nano banana`), se catalogan como candidatos normales en estado `detectado`, con personaje sugerido (si tiene alias) y escena vacía (`escena = None`).
   - Si no coinciden con ningún patrón conocido, se canalizan a "Sin Identificar".
3. **Sección colapsada en la UI ("Anteriores al capítulo"):**
   - Los lotes que contienen material anterior se envían al panel en una lista independiente `lotes_anteriores`.
   - En el frontend, se renderizan dentro de un bloque `<details id="details-anteriores">` rotulado "Anteriores al capítulo", cerrado por defecto, con todos los checkboxes desmarcados y sin nombre de escena precargado.
4. **Protección de "Mover lotes listos":**
   - El botón masivo "Mover lotes listos" evalúa exclusivamente los lotes correspondientes al material nuevo del capítulo activo (`lotes`). Los lotes de la sección "Anteriores" nunca son incluidos en este traslado.
5. **Reapertura de capítulos preservando fecha original:**
   - Al invocar `reabrir_capitulo`, se mantiene intacta la `fecha_inicio` original registrada en la creación del capítulo, garantizando que el umbral cronológico histórico se respete.
6. **Base de nombre de archivo compacta:**
   - En `GestorMovimientosBandeja.calcular_base_escena`, se eliminan todos los espacios internos de la escena para construir la base del archivo (ej. "lucie trapitos" $\rightarrow$ `lucietrapitos1.jpg`).
   - La carpeta de la escena en destino conserva la denominación original elegida por el usuario.
   - Se mantiene la compatibilidad con `obtener_personaje_de_alias_inicial` para asegurar que el nombre generado continúe deduciendo el personaje correcto.

## Capabilities

### New Capabilities
- `capitulo-solo-material-nuevo`: Control temporal de adopción de medios según `fecha_inicio` de capítulo, margen configurable, segregación de lotes anteriores en UI y base compacta sin espacios en archivos renombrados.

## Impact
- **Código operativo:** `bandeja_descargas.py` (`ConfiguracionBandeja`, `VigilanteBandeja.escanear`, `GestorMovimientosBandeja.calcular_base_escena`, `BaseDatosBandeja.guardar_capitulo_activo`, interfaz web HTML/JS).
- **Configuración:** `config_bandeja.json` agrega `"minutos_antes_inicio_capitulo": 0`.
- **Pruebas:** `test_bandeja_descargas.py` añade la suite completa `TestCapituloSoloMaterialNuevo`.
