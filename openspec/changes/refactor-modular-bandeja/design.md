# Design: refactor-modular-bandeja

## Context

El script `bandeja_descargas.py` ha acumulado más de 8.000 líneas de código que concentran tanto la lógica del sistema (configuración, persistencia SQLite, clasificación, clustering de lotes, operaciones atómicas de movimiento, integración con pendrive, demonio vigilante y servidor HTTP) como la presentación del frontend SPA (HTML, CSS y JavaScript embebidos en una plantilla multilínea de más de 3.100 líneas).
El proyecto cuenta con una estricta Regla de Oro que prohíbe 11 primitivas destructivas de borrado y pisado, validada mediante un analizador estático AST (`seguridad_anti_borrado.py`). La suite actual contiene exactamente 161 pruebas unitarias passing.

Para detalles de la motivación y requisitos, véanse `proposal.md` y `specs/refactor-modular-bandeja/spec.md`.

## Goals / Non-Goals

**Goals:**
- Descomponer `bandeja_descargas.py` en un paquete Python modular `bandeja/` con responsabilidades claramente delimitadas y acoplamiento controlado.
- Extraer los recursos web a `bandeja/web/{panel.html, panel.js, panel.css}` y servirlos desde una lista blanca fija, bloqueando *path traversal*.
- Mantener `bandeja_descargas.py` como un punto de entrada ligero compatible tanto a nivel CLI como a nivel de importación de símbolos públicos.
- Actualizar `seguridad_anti_borrado.py` con descubrimiento automático de todos los `.py` de la raíz (excepto tests) y del paquete `bandeja/`, incorporando una prueba que falle si existe algún módulo operativo sin auditar.
- Limitar el tamaño de cada módulo Python a no más de ~1.200 líneas.
- Preservar exactamente el 100% de la suite de pruebas (mínimo 161 tests en verde) y la equivalencia de respuestas JSON y HTML con las capturas *golden*.
- Realizar la migración paso a paso con verificación completa y commits individuales por módulo extraído.

**Non-Goals:**
- No se agrega ninguna funcionalidad nueva ni se altera la lógica de negocio existente.
- No se modifica el esquema de base de datos SQLite (`_lucie_bandeja.sqlite`).
- No se modifica la estructura ni claves de `config_bandeja.json`.
- No se alteran las rutas, métodos ni contratos de los endpoints HTTP `/api/*`.
- No se debilitan ni eliminan aserciones en los tests existentes.

## Decisions

### 1. Grafo de dependencias y modularización del paquete `bandeja/`

Para evitar dependencias circulares y mantener los módulos por debajo de ~1.200 líneas, se establece el siguiente grafo acíclico (DAG):

```
                     bandeja/plataforma.py (OS, mounts, fs, notificaciones)
                               ^
                               |
                      bandeja/config.py (ConfiguracionBandeja, constantes)
                               ^
                               |
         +---------------------+---------------------+
         |                                           |
bandeja/clasificacion.py                    bandeja/db.py
(FiltroListaBlanca, alias, escenas)         (GestorBaseDatosBandeja, SQLite)
         ^                                           ^
         |                     +---------------------+
         |                     |
  bandeja/lotes.py             |
(AgrupadorLotes, mtime/ctime)  |
         |                     |
         +----------+----------+
                    |
          bandeja/capitulos.py (ciclo de vida, foco, balance, descarte)
                    ^
                    |
         +----------+----------+---------------------+
         |                                           |
bandeja/movimientos.py                      bandeja/pendrive.py
(GestorMovimientosBandeja,                  (detección, marcador,
 renombrado, simulación, undo)               envío seguro .part, manifiesto)
         |                                           |
         +---------------------+---------------------+
                               |
                      bandeja/vigilante.py (VigilanteBandeja, escaneo, polling)
                               ^
                               |
                      bandeja/servidor.py (HandlerServidorBandeja, crear_servidor)
                               ^
                               |
                      bandeja/__init__.py y bandeja_descargas.py (CLI / Facade)
```

**Justificación:**
- `plataforma.py` aisla todas las llamadas específicas a Linux (`/proc/mounts`, `/media/*`, `notify-send`) y stubs para Windows, sin dependencias internas.
- `capitulos.py` desacopla la coordinación de ciclo de vida (balance de escenas, reglas de descarte, detección de capítulos olvidados) para mantener `movimientos.py` y `db.py` dentro del umbral de líneas.
- `pendrive.py` concentra la lógica del marcador `.lucie_pendrive.json`, copia segura en bloques con hash sobre `.part` y manifiesto append-only, apoyándose en `plataforma.py`.

*Alternativa descartada:* Mantener `capitulos` dentro de `movimientos.py` o `db.py`. Se descartó porque superaría las 1.400 líneas en un solo archivo.

### 2. Extracción y servicio de activos frontend (`bandeja/web/`)

- **Estructura en disco:**
  ```
  bandeja/
  └── web/
      ├── panel.html
      ├── panel.css
      └── panel.js
  ```
- **Servicio seguro con lista blanca fija:**
  `HandlerServidorBandeja` servirá exclusivamente los siguientes recursos mapeados a archivos reales:
  - `GET /` o `GET /index.html` → `bandeja/web/panel.html` (con inyección dinámica de configuración y token CSRF).
  - `GET /panel.js` → `bandeja/web/panel.js`.
  - `GET /panel.css` → `bandeja/web/panel.css`.
  Cualquier otra ruta estática devolverá HTTP 404 (o 403), imposibilitando cualquier ataque de *directory traversal*.
- **Inyección de configuración:**
  En `panel.html`, se mantendrán las variables de arranque (`window.TOKEN_CSRF`, `window.PUERTO_SERVIDOR`, `window.REFRESCO_PANEL_SEGUNDOS`, `window.TITULO_BASE`) mediante marcadores de reemplazo o un bloque `<script>` contextual previo a la carga de `panel.js`.
- **Ruta de recursos:**
  La localización de `bandeja/web/` se resuelve dinámicamente mediante `os.path.join(os.path.dirname(__file__), "web")` para total independencia del directorio de trabajo actual.

*Alternativa descartada:* Servir archivos estáticos con un `SimpleHTTPRequestHandler` abierto. Se descartó por riesgo de seguridad y violación de confinamiento.

### 3. Descubrimiento automático en el analizador AST anti-borrado

- En `seguridad_anti_borrado.py`:
  - Se implementa `descubrir_archivos_operativos(directorio_raiz: str) -> List[str]`.
  - Escanea los archivos `.py` en la raíz (ej. `inventario_pendrive.py`, `plan_limpieza.py`, `seguridad_anti_borrado.py`, `bandeja_descargas.py`) excluyendo archivos que comiencen con `test_` o carpetas de control/entorno (`.git`, `__pycache__`, `.agents`, `venv`, `.venv`, `frontend`).
  - Escanea recursivamente todos los `.py` dentro de `bandeja/`.
  - `auditar_archivos_proyecto` utiliza automáticamente esta lista cuando no se pasa una explícita.
- En la suite de pruebas (`test_plan_limpieza.py` y `test_bandeja_descargas.py`):
  - Se añade un test que invoca `descubrir_archivos_operativos` y valida que audite efectivamente todos los módulos de `bandeja/` y de la raíz.
  - Se añade una aserción que garantiza que si se añade un archivo operativo nuevo, este se incluye automáticamente en la auditoría, y que si alguno es omitido la prueba falla.

### 4. Fachada de compatibilidad en `bandeja_descargas.py`

`bandeja_descargas.py` contendrá:
```python
from bandeja import (
    ConfiguracionBandeja, GestorBaseDatosBandeja, FiltroListaBlanca,
    ValidadorEscenas, AgrupadorLotes, GestorMovimientosBandeja,
    GeneradorMiniaturas, VigilanteBandeja, HandlerServidorBandeja,
    crear_servidor, main, calcular_sha256, formatear_bytes,
    obtener_fecha_llegada, asegurar_carpeta_capitulo,
    detectar_pendrive, simular_envio_capitulos, ejecutar_envio_pendrive,
    deshacer_envio_pendrive, ...
)

if __name__ == "__main__":
    main()
```
Esto asegura que cualquier script externo, prueba unitaria o invocación CLI continúe funcionando exactamente igual.

### 5. Estrategia de actualización de `unittest.mock.patch` en tests

- Los tests que hacen mock de funciones o métodos que se movieron a nuevos módulos continuarán funcionando a través del facade `bandeja_descargas.<simbolo>` o apuntarán limpiamente a `bandeja.<modulo>.<simbolo>` según corresponda.
- La prueba en Node.js `test_frontend_funciones_preservacion_ui_y_pausas_en_node` se adaptará para evaluar `bandeja/web/panel.js` y el HTML servido, manteniendo idénticas todas las validaciones de DOM, tildes, modales, scroll y reintentos.

## Risks / Trade-offs

- **[Riesgo] Dependencias circulares entre submódulos al mover código**:
  - *Mitigación:* Se diseñó un DAG estricto. La interacción entre `db.py`, `movimientos.py` y `capitulos.py` se realiza pasando instancias o funciones desacopladas, nunca importando módulos padre desde módulos hoja.
- **[Riesgo] Rutas de `unittest.mock.patch` rotas en pruebas existentes**:
  - *Mitigación:* Se ejecuta la suite completa de 161 tests tras la creación de cada módulo individual. `bandeja_descargas.py` re-exporta los símbolos públicos para mantener retrocompatibilidad durante y después de la migración.
- **[Riesgo] Desalineación de inyecciones dinámicas en `panel.html`**:
  - *Mitigación:* Se captura la respuesta *golden* de `GET /` previa a la migración y se valida que los scripts y metadatos inyectados produzcan un DOM equivalente comprobado por el test de Node.js.
- **[Riesgo] Violación inadvertida de la Regla de Oro AST**:
  - *Mitigación:* En cada paso se ejecuta `seguridad_anti_borrado.py`. Ningún commit se realiza si las infracciones son mayores a 0.

## Migration Plan

1. **Captura de línea base (Golden baseline):**
   - Ejecutar la suite completa y registrar 161 tests en verde.
   - Capturar y almacenar respuestas de referencia para `GET /`, `/api/estado-version`, `/api/capitulos/estado`, `/api/pendrive/estado` y `/api/lotes`.
2. **Auditoría AST dinámica:**
   - Actualizar `seguridad_anti_borrado.py` con `descubrir_archivos_operativos`.
   - Incorporar test de auditoría dinámica en `test_bandeja_descargas.py` / `test_plan_limpieza.py`.
3. **Extracción modular incremental (1 módulo por paso, test suite + commit individual):**
   - Paso 3.1: `bandeja/plataforma.py` (abstracción SO, mounts, filesystem).
   - Paso 3.2: `bandeja/config.py` (`ConfiguracionBandeja` y constantes).
   - Paso 3.3: `bandeja/db.py` (`GestorBaseDatosBandeja`).
   - Paso 3.4: `bandeja/clasificacion.py` (`FiltroListaBlanca`, alias, `ValidadorEscenas`).
   - Paso 3.5: `bandeja/lotes.py` (`AgrupadorLotes`, `obtener_fecha_llegada`).
   - Paso 3.6: `bandeja/capitulos.py` (ciclo de vida y balance de capítulos).
   - Paso 3.7: `bandeja/movimientos.py` (`GestorMovimientosBandeja`, renombrado, reversión).
   - Paso 3.8: `bandeja/pendrive.py` (operaciones seguras con pendrive).
   - Paso 3.9: `bandeja/vigilante.py` (`VigilanteBandeja`).
   - Paso 3.10: `bandeja/web/` (`panel.html`, `panel.js`, `panel.css`) y `bandeja/servidor.py` (`HandlerServidorBandeja`).
   - Paso 3.11: `bandeja/__init__.py` y adelgazamiento de `bandeja_descargas.py`.
4. **Verificación final:**
   - Comprobar que todos los módulos tengan <= ~1.200 líneas.
   - Comprobar respuesta con baseline *golden*.
   - Ejecutar suite completa (>= 161 tests) y auditoría AST (0 infracciones).
