# Design: Corte por Fecha de Llegada (ctime) y Notificaciones Selectivas

## Context

En Linux y sistemas POSIX, `st_mtime` representa la fecha de última modificación del contenido de un archivo, mientras que `st_ctime` representa el último cambio del inodo (creación, copia, renombrado o atributos). Cuando un navegador como Chrome descarga un archivo o se copia con `cp -p`, el navegador puede restaurar `st_mtime` con la cabecera HTTP `Last-Modified` proporcionada por el servidor web (por ejemplo, Grok o servicios de IA). Como consecuencia, un archivo recién ingresado a la bandeja puede tener un `st_mtime` de hace horas o días, cayendo falsamente en la sección "Anteriores al capítulo".

Dado que la llamada del sistema `utime()` / `utimensat()` permite alterar `mtime` y `atime` pero **no puede alterar `ctime` retroactivamente** (toda llamada que modifique el inodo actualiza `ctime` al reloj actual del sistema), la fecha de llegada real a nivel local está dada por `max(st_mtime, st_ctime)`.

Ver `proposal.md` y `specs/corte-por-fecha-de-llegada/spec.md`.

## Goals / Non-Goals

**Goals:**
- Implementar una única función `obtener_fecha_llegada(archivo_o_stat)` que calcule `max(st_mtime, st_ctime)` de manera robusta.
- Utilizar `obtener_fecha_llegada` en todos los cortes de material reciente: asignación al capítulo en foco, sección "Anteriores" y evaluación de `horas_material_reciente`.
- Exponer `fecha_llegada` en el diccionario del archivo (ISO o legible) y mostrarla en la interfaz (tooltip / tarjeta).
- Garantizar que el aviso de escritorio de lotes nuevos cuente únicamente lotes que ingresan a la lista principal, ignorando por completo los de "Anteriores".
- Ajustar el banner del capítulo en foco para adoptar el estilo amarillo con estrella (`⭐ EN FOCO`) congruente con la tabla de Capítulos Abiertos, preservando el aviso `(+N abierto(s))`.
- Mantener las Reglas de Oro intactas (AST con 0 infracciones, simulación obligatoria, bitácora y reversibilidad).

**Non-Goals:**
- No alterar el orden de los archivos dentro de los lotes ni la numeración correlativa en los nombres de destino al renombrar (se preserva el orden por `mtime`).
- No modificar el esquema de base de datos SQLite ni la estructura de almacenamiento de los capítulos.
- No alterar archivos reales en el sistema de descargas.

## Decisions

### 1. Definición de `obtener_fecha_llegada`
- **Decisión**: Se implementa a nivel de módulo en `bandeja_descargas.py`:
  ```python
  def obtener_fecha_llegada(archivo_o_stat: Union[str, os.stat_result, Any]) -> float:
      if hasattr(archivo_o_stat, "st_mtime") and hasattr(archivo_o_stat, "st_ctime"):
          return max(float(archivo_o_stat.st_mtime), float(archivo_o_stat.st_ctime))
      if isinstance(archivo_o_stat, dict):
          mt = archivo_o_stat.get("st_mtime", archivo_o_stat.get("mtime", 0.0))
          ct = archivo_o_stat.get("st_ctime", archivo_o_stat.get("ctime", 0.0))
          return max(float(mt), float(ct))
      if isinstance(archivo_o_stat, (int, float)):
          return float(archivo_o_stat)
      st = os.stat(str(archivo_o_stat))
      return max(float(st.st_mtime), float(st.st_ctime))
  ```
- **Alternativas consideradas**: Usar `st_btime` (birth time). Descartado porque no todos los filesystems en Linux soportan `btime` vía `statx`, mientras que `st_ctime` está universalmente disponible en POSIX y refleja cuándo el archivo llegó o se creó en el sistema de archivos local.

### 2. Uso en cortes de clasificación en `VigilanteBandeja.escanear`
- **Decisión**:
  Al examinar cada archivo:
  ```python
  st = os.stat(ruta_completa)
  tamanio = st.st_size
  mtime = st.st_mtime
  fecha_llegada = obtener_fecha_llegada(st)
  ```
  La condición `es_anterior` se calcula como:
  ```python
  es_anterior = False
  if es_cap_foco and fecha_llegada < ts_corte_capitulo:
      es_anterior = True
  horas_reciente = float(getattr(self.config, "horas_material_reciente", 0) or 0)
  if horas_reciente > 0:
      ts_corte_horas = time.time() - (horas_reciente * 3600.0)
      if fecha_llegada < ts_corte_horas:
          es_anterior = True
  ```
- **Razón**: Permite que tanto el capítulo en foco como el umbral opcional de horas utilicen de forma homogénea la fecha de llegada real.

### 3. Preservación estricta de orden y numeración por `mtime`
- **Decisión**: En `AgrupadorLotes.agrupar` y en `GestorMovimientosBandeja.simular_movimiento_lote`, la ordenación para agrupar y para enumerar los archivos (`lucietrapitos1.jpg`, `lucietrapitos2.jpg`) sigue utilizando `mtime`.
- **Razón**: Requisito explícito de la Regla 2 del cambio para asegurar que la secuencia cronológica de tomas producidas no sufra distorsiones.

### 4. Filtrado estricto en notificación de lotes nuevos
- **Decisión**: En `VigilanteBandeja.escanear`, el cómputo de lotes nuevos listos para ordenar se calcula sobre `lotes_principales = [l for l in lotes_generados if not l.get("es_anterior")]`:
  ```python
  lotes_principales = [l for l in lotes_generados if not l.get("es_anterior")]
  if len(lotes_principales) > self._ultimo_conteo_lotes:
      nuevos = len(lotes_principales) - self._ultimo_conteo_lotes
      self._notificar_escritorio(f"Se detectaron {nuevos} lote(s) nuevo(s) listos para ordenar.")
  self._ultimo_conteo_lotes = len(lotes_principales)
  ```
- **Razón**: Evita notificar al usuario sobre lotes que no aparecen en la lista principal activa y que fueron segregados a "Anteriores".

### 5. Estilo visual del banner en foco
- **Decisión**:
  En el banner superior `#banner-capitulo-activo`:
  - Se actualiza la clase `.badge-capitulo-activo` a `background: #f59e0b; color: #000; font-weight: 700; border-radius: 4px; padding: 2px 8px; font-size: 0.75rem;`.
  - El texto del badge se establece en `⭐ EN FOCO`.
  - Se preserva el elemento `#banner-otros-abiertos` con su lógica de `(+N abierto(s))` y click para navegar a la pestaña de Capítulos Abiertos.

## Risks / Trade-offs

- **[Riesgo]** En tests unitarios con `os.utime`, si se manipula únicamente `mtime`, `ctime` permanece en el reloj actual del sistema.
  → **Mitigación**: Los tests que verifiquen archivos con "mtime y ctime anteriores" deben mockear `os.stat` o utilizar `obtener_fecha_llegada` / mocks de stat para simular que tanto `st_mtime` como `st_ctime` son anteriores, ya que el kernel Linux no permite a nivel de usuario setear `ctime` al pasado.
- **[Riesgo]** Reglas de Oro y AST: La incorporación de `ctime` no debe agregar ninguna función prohibida ni alterar el comportamiento no destructivo.
  → **Mitigación**: Solo se lee `st_ctime` de `os.stat`, sin llamadas a funciones de modificación ni borrado.
