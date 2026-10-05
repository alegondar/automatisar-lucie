# Design: preseleccion-reciente-y-seleccion-global

## Context

El sistema de bandeja de descargas cuenta con una arquitectura modular desacoplada en el paquete `bandeja/`. `VigilanteBandeja` (`bandeja/vigilante.py`) escanea periódicamente el directorio `~/Descargas` en un hilo en segundo plano, clasifica archivos y los agrupa en lotes mediante `AgrupadorLotes` (`bandeja/lotes.py`), exponiendo el estado a través de la API servida por `HandlerServidorBandeja` (`bandeja/servidor.py`) y presentada por la SPA estática en `bandeja/web/`.

Para la motivación detallada, véase [proposal.md](file:///home/<usuario>/Documentos/code-proyect/automatisar-lucie/openspec/changes/preseleccion-reciente-y-seleccion-global/proposal.md).
Para los requerimientos funcionales, véase [specs/preseleccion-reciente-y-seleccion-global/spec.md](file:///home/<usuario>/Documentos/code-proyect/automatisar-lucie/openspec/changes/preseleccion-reciente-y-seleccion-global/specs/preseleccion-reciente-y-seleccion-global/spec.md).

## Goals / Non-Goals

**Goals:**
- Actualizar el valor predeterminado de `horas_material_reciente` a 168 (7 días) en `ConfiguracionBandeja` y `config_bandeja.json`.
- Segregar archivos con antigüedad mayor al umbral hacia `lotes_anteriores` cuando no haya capítulo en foco, sin tildar y sin escena precargada.
- Preservar al 100% el comportamiento existente cuando haya capítulo en foco (corte exclusivo por `fecha_inicio`).
- Dividir lotes mixtos que contengan archivos recientes y antiguos.
- Implementar controles globales "Seleccionar todo", "Ninguno" y contador en la cabecera de la sección principal sin afectar la sección de anteriores ni perder selección en el sondeo reactivo.
- Diferir el mensaje visual "El nombre de la escena no puede estar vacío" hasta el evento `blur` o intento de mover.
- Detectar duplicados contra archivos listados, movidos previamente y manifiesto del pendrive en segundo plano, mostrando la insignia y deseleccionándolos por defecto.
- Mantener 0 infracciones en el análisis estático AST y 100% de la suite de pruebas en verde.

**Non-Goals:**
- No se permite saltarse la simulación previa obligatoria ni la confirmación modal al mover lotes.
- No se eliminan ni alteran archivos existentes en disco (estricto cumplimiento de las Reglas de Oro).

## Decisions

### 1. Bifurcación del criterio de corte temporal en `VigilanteBandeja`
En `bandeja/vigilante.py`, la determinación de `es_anterior` se bifurca limpiamente:
```python
es_anterior = False
if es_cap_foco:
    if fecha_llegada < ts_corte_capitulo:
        es_anterior = True
else:
    horas_reciente = float(getattr(self.config, "horas_material_reciente", 0) or 0)
    if horas_reciente > 0:
        ts_corte_reciente = time.time() - (horas_reciente * 3600.0)
        if fecha_llegada < ts_corte_reciente:
            es_anterior = True
```
*Justificación:* Garantiza que cuando haya un capítulo activo, la ventana de horas recientes no interfiera con los archivos creados después del inicio del capítulo, cumpliendo el requerimiento de no alterar el flujo de capítulos.

### 2. Detección no bloqueante de duplicados en el ciclo de escaneo
`VigilanteBandeja.escanear` se ejecuta en un hilo de fondo. Durante cada barrido:
- Mantiene un diccionario temporal `hashes_en_descargas: Dict[str, str]` (hash -> nombre primer archivo) para detectar duplicados entre descargas concurrentes.
- Consulta en SQLite `bandeja_archivos` si existe registro con el mismo hash en estado `'movido'`, extrayendo la ruta de destino.
- Si el pendrive está conectado y tiene manifiesto `.lucie/manifiesto.jsonl`, verifica si el hash ya fue transferido.
- Si hay coincidencia, adjunta un diccionario descriptivo a `item_info`:
  ```python
  item_info["duplicado"] = {
      "es_duplicado": True,
      "tipo": "descargas" | "movido" | "pendrive",
      "coincide_con": nombre_o_destino,
      "mensaje": f"Coincide con {nombre_o_destino}"
  }
  ```
- En `AgrupadorLotes`, la información del duplicado se propaga a cada archivo. Al cargarse en la UI, los archivos con `duplicado` se renderizan con checkbox destildado (`checked = false`) y una insignia visible `<span class="badge-duplicado">Duplicado</span>`.

*Alternativa considerada:* Calcular el hash bajo demanda en una ruta HTTP `/api/duplicados`. Se descartó para evitar latencia de red adicional y peticiones redundantes.

### 3. Barra de selección global y persistencia reactiva en la SPA
- En `bandeja/web/panel.html`, se añade un toolbar junto al botón "Mover lotes listos":
  - Botón `#btn-global-seleccionar-todo`
  - Botón `#btn-global-seleccionar-ninguno`
  - Etiqueta `#conteo-global-seleccion` (`X archivos seleccionados de Y`)
- En `bandeja/web/panel.js`:
  - `seleccionarTodoGlobal(marcar)` consulta exclusivamente los `.chk-archivo` dentro de `#contenedor-lotes` (lotes principales). Actualiza cada checkbox, el checkbox maestro `.cb-lote-listo` de cada lote y refresca contadores individuales y el contador global.
  - La sección `#sec-lotes-anteriores` queda expresamente excluida de esta acción.
  - `capturarEstadoUI` y `restaurarEstadoUI` conservan las selecciones del usuario ante cada refresco periódico de 4 segundos.

### 4. Supresión inicial del mensaje de error de escena vacía
- En `bandeja/web/panel.js`:
  - Se modifica `validarInputEscena(loteId, forzarMostrarVacio = false)`.
  - Si el campo está vacío y `forzarMostrarVacio` es `false`, se oculta el mensaje de error `error-escena-${loteId}`.
  - Al recibir el evento `blur` (`onblur="validarInputEscena('${loteId}', true)"`) o al intentar mover (`iniciarMover` / `simularMoverLotesListos`), se invoca con `forzarMostrarVacio = true`, activando el mensaje en caso de estar en blanco.

### 5. Encabezado de la sección Anteriores
- En `bandeja/web/panel.js`, `renderLotesAnteriores` actualiza dinámicamente el texto del summary:
  - Sin capítulo en foco: `Anteriores (M) • Material de más de N horas: revisá antes de mover` (con N = `horas_material_reciente`).
  - Con capítulo en foco: `Anteriores al capítulo (M)`.

## Risks / Trade-offs

- **[Riesgo] Rendimiento al calcular hashes de archivos grandes en Descargas**:
  - *Mitigación:* Se aprovecha el cache de SQLite por ruta y mtime en `VigilanteBandeja`. Si el archivo no ha cambiado, no se relee el disco. El escaneo ocurre íntegramente en el hilo en segundo plano, por lo que la interfaz no se congela.
- **[Riesgo] Desincronización de contadores globales con la selección manual**:
  - *Mitigación:* Cada cambio en cualquier `.chk-archivo` de los lotes principales llama a una función centralizada `actualizarConteoGlobalSeleccion()`.
