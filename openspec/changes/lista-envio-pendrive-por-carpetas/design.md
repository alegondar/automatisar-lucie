# Design: lista-envio-pendrive-por-carpetas

## Context

En la arquitectura actual de la bandeja (`bandeja/pendrive.py` y `bandeja/servidor.py`), la lista de carpetas para enviar dependía de `_leer_estado_pendrive_raw`, la cual retornaba una lista vacía `capitulos_pendientes: []` si no había un pendrive conectado y vinculado. Para garantizar resiliencia absoluta, separamos la obtención de carpetas de sala de espera en un endpoint local independiente (`GET /api/pendrive/carpetas`), dejando `GET /api/pendrive/estado` exclusivamente para la salud y parámetros de la unidad pendrive.

## Goals / Non-Goals

**Goals:**
- Separar completamente los endpoints: `GET /api/pendrive/carpetas` para el escaneo local de la sala de espera y `GET /api/pendrive/estado` para la unidad física.
- Escaneo recursivo seguro con `followlinks=False` (nunca seguir symlinks), con tope máximo de profundidad (6 niveles) y exclusión de carpetas del sistema (`_enviados`, `_revertidos`, `_descartados`, `_a_revisar`).
- No descartar carpetas que solo tengan archivos en subcarpetas anidadas: computar el conteo y peso total recursivo acumulado.
- Tipificar cada carpeta cruzando personaje y nombre con `bandeja_capitulos`:
  - `Capítulo en foco`: activo y en foco en la base de datos.
  - `Capítulo abierto`: registrado y abierto en la base de datos.
  - `Capítulo cerrado`: registrado y cerrado en la base de datos.
  - `Escena suelta`: no registrada en la base de datos pero con estructura de escena.
  - `Carpeta heredada`: carpeta sin estructura canónica de capítulo (por ejemplo `imagenes`), con insignia de advertencia y exclusión de envíos automáticos.
- Permitir la inspección desplegable ("Ver archivos") con nombres, pesos y miniaturas enlazadas al visor lightbox interactivo existente.
- Permitir selección granular múltiple (checkbox por carpeta, botones de selección masiva) y generación de un único plan de envío consolidado con simulación obligatoria (dry-run).
- Distinguir nítidamente los cuatro estados físicos de la unidad pendrive en el panel.
- Contrastar archivos pendientes contra el manifiesto del pendrive (`sha256`) para informar archivos ya transferidos sin bloquear la interfaz.
- Preservar las casillas seleccionadas por el usuario durante los ciclos de refresco automático (polling).

**Non-Goals:**
- Modificar el protocolo de transferencia física segura al pendrive (sigue usando escritura atómica `.part`, modo exclusivo `xb`, verificación de hash post-copia, registro `.jsonl` y manifiesto append-only).
- Modificar el esquema de tablas en SQLite.
- Ejecutar transferencias sin aprobación previa y simulación obligatoria.

## Decisions

### 1. Desacoplamiento de Endpoints: `GET /api/pendrive/carpetas` vs `GET /api/pendrive/estado`
- `GET /api/pendrive/carpetas`: escanea la sala de espera local `~/Descargas/_lucie/<personaje>/<carpeta>` y cruza con `GestorBaseDatosBandeja`. Nunca interactúa con el pendrive ni corre riesgos de timeout o cuelgues si una unidad USB no responde.
- `GET /api/pendrive/estado`: se enfoca en consultar la unidad física pendrive (conectado, unidad candidata sin vincular, espacio libre/total, archivos `.part` huérfanos).

### 2. Algoritmo de Escaneo Recursivo Seguro (`escanear_sala_espera_carpetas`)
- Recorre `~/Descargas/_lucie/<personaje>/<carpeta>` usando `os.walk(..., followlinks=False)`.
- Control de profundidad: calcula la profundidad relativa respecto a la carpeta inspeccionada y trunca si supera 6 niveles.
- Ignora carpetas reservadas del sistema: `_enviados`, `_revertidos`, `_descartados`, `_a_revisar`.
- Acumula recursivamente todos los archivos encontrados: fotos, videos y archivos no multimedia. Una carpeta cuyos archivos están dentro de subcarpetas (como `imagenes/prueba bandeja/foto.jpg`) acumula sus totales y se incluye en la lista.
- Para cada archivo, registra nombre, ruta relativa, tamaño, tipo y fecha de modificación.

### 3. Tipificación Cruzando con `bandeja_capitulos`
Para cada carpeta identificada por `(personaje, nombre)`:
1. Se consulta el registro en `bandeja_capitulos`.
2. Si el registro existe:
   - Si `en_foco == 1` y `estado == 'activo'`: **Capítulo en foco**.
   - Si `estado == 'activo'`: **Capítulo abierto**.
   - Si `estado == 'cerrado'`: **Capítulo cerrado**.
3. Si el registro no existe en la base:
   - Si el nombre o estructura coincide con patrones o es una carpeta histórica preexistente (como `imagenes`): **Carpeta heredada**. Se acompaña de un aviso visual preventivo.
   - En caso general de carpetas de material clasificado: **Escena suelta**.

### 4. Enrutamiento de Archivos Sueltos y no Multimedia
- Archivos multimedia sueltos en la raíz de una carpeta: el generador de plan los enruta automáticamente por tipo a sus subcarpetas de destino en el pendrive (`videos/` o `videos sin editar`, `fotos/` o `imagenes`), preservando su nombre normalizado.
- Archivos no multimedia: se contabilizan y listan como advertencia visual en el panel y en la simulación previa.

### 5. Selección en Lote y Plan Unificado
El endpoint `/api/pendrive/envio-simular` y `/api/pendrive/envio` admite una lista de carpetas: `carpetas: ["lucie/lucie-invitaCafe", "lucie/oloraculo", ...]`.
- Se genera un único plan consolidado de simulación (verificación de espacio en pendrive, 1 GiB de margen, límite de 4 GiB en FAT32, deduplicación por manifiesto, colisiones case-insensitive).
- Un solo modal de confirmación con aprobación de un clic.

### 6. Persistencia de Selección en Frontend
En `bandeja/web/panel.js`, el cliente mantiene un `Set` en memoria (`carpetasPendriveSeleccionadas`) con las claves identificadoras (`${c.personaje}/${c.carpeta}`). Al redibujar la tabla en el sondeo cada 4 segundos, las filas reconstruidas restauran el estado de las casillas y los contadores en base a dicho `Set`.

## Risks / Trade-offs

- **[Riesgo]**: Enlaces simbólicos circulares o carpetas muy profundas en la sala de espera.
  - *Mitigación*: `followlinks=False` en `os.walk` y poda a una profundidad máxima de 6 niveles.
- **[Riesgo]**: Desincronización de selecciones al refrescar el panel.
  - *Mitigación*: `carpetasPendriveSeleccionadas` almacena las claves canónicas `<personaje>/<carpeta>` y re-tilda las casillas durante el renderizado.
- **[Riesgo]**: Violación de la Regla de Oro al transferir carpetas heredadas.
  - *Mitigación*: Simulación previa obligatoria idéntica a la de capítulos regulares; ninguna operación destructiva; destino verificado con modo 'xb'.
