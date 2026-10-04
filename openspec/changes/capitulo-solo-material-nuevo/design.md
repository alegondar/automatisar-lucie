# Design: Adopción Exclusiva de Material Nuevo por Capítulo y Base de Nombre Compacta

## Architecture & Data Flow

### 1. Comparación Temporal en Escaneo (`VigilanteBandeja.escanear`)
- Al iniciar el ciclo de escaneo, se consulta `self.db.obtener_capitulo_activo()`.
- Si existe un capítulo activo con `fecha_inicio`, se parsea a timestamp POSIX (`ts_ini`).
- Se recupera el parámetro `minutos_antes_inicio_capitulo` desde `self.config` (por defecto 0) y se calcula:
  $$\text{ts\_corte\_capitulo} = \text{ts\_ini} - (\text{minutos\_antes\_inicio\_capitulo} \times 60)$$
- Para cada archivo detectado en `~/Descargas`, se consulta `st.st_mtime`.
- Si $\text{st\_mtime} < \text{ts\_corte\_capitulo}$, se etiqueta con `es_anterior = True`.

### 2. Clasificación de Candidatos y Lotes Anteriores
- **Archivos nuevos (`es_anterior == False`):**
  - Si hay capítulo activo, se asigna automáticamente al capítulo (`estado = "clasificado"`, `personaje = cap["personaje"]`, `escena = cap["nombre"]`).
  - Se incorporan a `candidatos_estables`, que luego se agrupan en `lotes_generados` (con `es_anterior = False`).
- **Archivos anteriores (`es_anterior == True`):**
  - Si es candidato por alias o patrón IA (`grok-*`, `Gemini_*`, etc.), se registra en la base de datos como `detectado`, con `escena = None`.
  - Se incorporan a `candidatos_anteriores`, que se agrupan en `lotes_anteriores`.
  - En cada lote anterior, se fuerza `es_anterior = True`, `escena_sugerida = ""`, `lote_id = f"ant_{lote_id}"` y cada archivo se marca con `es_anterior = True`.
  - Si no coincide con ningún patrón, se deriva a `sin_identificar`.

### 3. Persistencia y Sincronización en Base de Datos (`BaseDatosBandeja`)
- En `guardar_capitulo_activo(personaje, nombre, habilitado, fecha_inicio=None)`:
  - Cuando `habilitado` es `True` y se especifica un nombre, se asegura la existencia del registro en `bandeja_capitulos` con `fecha_inicio` inmediata si no existía uno activo.
  - Cuando `habilitado` es `False`, se marca el capítulo activo como `cerrado` con `fecha_fin`.
- En `reabrir_capitulo(id_capitulo)`:
  - Se actualiza el capítulo a `estado = 'activo'` y `fecha_fin = NULL`, manteniendo intacta la `fecha_inicio` original.

### 4. Nombres de Archivo Compactos (`GestorMovimientosBandeja.calcular_base_escena`)
- Para construir la base del nombre de archivo:
  - Se limpian espacios internos mediante expresión regular: `re.sub(r'[\s]+', '', escena_raw)`.
  - Si la escena compacta comienza con el nombre canónico del personaje o uno de sus alias correspondientes, se utiliza directamente `escena_compacta`.
  - En caso contrario, se antepone el nombre canónico del personaje: `f"{pers_canonico}{escena_compacta}"`.
  - Esto garantiza que `"lucie trapitos"` resulte en base `"lucietrapitos"`, produciendo archivos como `"lucietrapitos1.jpg"`.
  - Se preserva el nombre de carpeta en el destino con los espacios que haya ingresado el usuario.

### 5. Interfaz Web y Control en Frontend
- La API `/api/lotes` y el estado general retornan `lotes` (material nuevo) y `lotes_anteriores` (material anterior).
- En el DOM, se agrega la sección `<details id="details-anteriores">` que aloja `#contenedor-lotes-anteriores`.
- La función `renderLotesAnteriores()` genera tarjetas de lotes con casillas destildadas por defecto y campos de escena en blanco.
- La función `simularMoverLotesListos()` recorre únicamente `#contenedor-lotes .cb-lote-listo:checked` y filtra los lotes donde `lote.es_anterior` sea falso, garantizando que el material anterior quede protegido de traslados desatendidos.
