# Proposal: refactor-modular-bandeja

## Why

El archivo `bandeja_descargas.py` ha crecido hasta superar las 8.000 líneas de código monolítico, conteniendo la configuración, base de datos SQLite, clasificación de medios, agrupación de lotes, gestión de movimientos de archivos, transferencias seguras a pendrive, demonio vigilante en segundo plano, servidor HTTP y más de 3.100 líneas de HTML, CSS y JavaScript embebidos en una plantilla de texto crudo. Esta concentración dificulta el mantenimiento, la navegación, la depuración y la auditoría modular, por lo que es necesario descomponerlo en un paquete modular limpio `bandeja/` con frontend estático desacoplado en `bandeja/web/`, garantizando una estricta equivalencia de comportamiento y 0 regresiones.

## What Changes

- **Partición en paquete modular `bandeja/`**: Extracción del monolito en 10 módulos especializados:
  - `bandeja/__init__.py`: Interfaz pública del paquete y exportación de símbolos.
  - `bandeja/config.py`: Clase `ConfiguracionBandeja` y constantes operativas.
  - `bandeja/db.py`: `GestorBaseDatosBandeja` y migraciones de esquema SQLite.
  - `bandeja/clasificacion.py`: `FiltroListaBlanca`, resolución de alias de personajes y `ValidadorEscenas`.
  - `bandeja/lotes.py`: `AgrupadorLotes` y utilidades de fecha de llegada (`obtener_fecha_llegada`).
  - `bandeja/movimientos.py`: `GestorMovimientosBandeja` (simulación, renombrado seguro, registro en bitácora, deshacer y renderizado de simulación HTML).
  - `bandeja/capitulos.py`: Lógica de ciclo de vida de capítulos (creación, foco, balance, cierre, descarte y alertas de olvido).
  - `bandeja/pendrive.py`: Detección de marcador `.lucie_pendrive.json`, vinculación inicial, plan de envío atómico con `.part`, manifiesto append-only `manifiesto.jsonl` y reversión segura a `_revertidos`.
  - `bandeja/plataforma.py`: Capa de abstracción del sistema operativo (puntos de montaje, detección de sistema de archivos en Linux y Windows, lectura de espacio libre y notificaciones de escritorio).
  - `bandeja/vigilante.py`: Demonio `VigilanteBandeja` y gestión de sondeo/notificaciones.
  - `bandeja/servidor.py`: `HandlerServidorBandeja` con despacho de rutas API REST y servidor HTTP multihilo `crear_servidor`.
- **Extracción de activos web a `bandeja/web/`**:
  - `bandeja/web/panel.html`: Estructura HTML semántica del panel SPA.
  - `bandeja/web/panel.css`: Hoja de estilos con variables de tema oscuro y layout responsivo.
  - `bandeja/web/panel.js`: Lógica cliente (gestión de estado UI, reactividad, sondeo adaptativo, modales y renderizado dinámico).
  - Servicio estático seguro desde `HandlerServidorBandeja` con lista blanca estricta (`panel.html`, `panel.js`, `panel.css`), impidiendo cualquier recorrido de rutas arbitrario (*path traversal*), inyectando el token CSRF y valores de configuración requeridos.
- **Punto de entrada compatible (`bandeja_descargas.py`)**:
  - Queda como un archivo fino (~50-100 líneas) que expone `main()` e importa los símbolos públicos del paquete `bandeja` para preservar compatibilidad total hacia atrás con invocaciones CLI (`python3 bandeja_descargas.py`) e imports existentes.
- **Auditoría AST anti-borrado dinámica y automática**:
  - Modificación de `seguridad_anti_borrado.py` para descubrir y auditar automáticamente todos los archivos `.py` dentro de `bandeja/` y todos los `.py` de la raíz (excluyendo tests).
  - Nuevo test unitario que falla si existe algún `.py` operativo que no haya sido auditado por el análisis AST.
  - Cumplimiento estricto de las Reglas de Oro con 0 infracciones en las 11 primitivas prohibidas de borrado y pisado.
- **Límite de tamaño por módulo**:
  - Ningún módulo de código Python excederá aproximadamente 1.200 líneas.
- **Preservación total de comportamiento (SIN cambios funcionales)**:
  - Sin cambios en el esquema SQLite, formato de `config_bandeja.json`, endpoints HTTP, respuestas JSON, parámetros CLI ni semántica de las operaciones.
  - Todos los tests existentes (161 tests) deben continuar pasando en verde, actualizando las rutas de `mock.patch` donde corresponda sin debilitar ninguna aserción.

## Capabilities

### New Capabilities
- `specs/refactor-modular-bandeja`: Especifica la modularización del monolito `bandeja_descargas.py` en el paquete `bandeja/`, la separación de activos web en `bandeja/web/`, la auditoría estática AST con descubrimiento automático de módulos, el límite de líneas por módulo y la garantía de preservación idéntica del comportamiento operativo y de la suite de pruebas.

### Modified Capabilities
<!-- No existing capabilities under openspec/specs/ are modified. -->

## Impact

- **Código fuente**: `bandeja_descargas.py` pasa a ser un envoltorio fino; nuevo paquete `bandeja/` con submódulos desacoplados y directorio de recursos estáticos `bandeja/web/`.
- **Auditoría AST**: `seguridad_anti_borrado.py` incorpora descubrimiento automático de módulos operativos; se actualizan `test_plan_limpieza.py` y `test_bandeja_descargas.py` para validar la auditoría completa.
- **Pruebas unitarias**: Los tests en `test_bandeja_descargas.py` que utilizan `unittest.mock.patch` con rutas a `bandeja_descargas.<simbolo>` se actualizan hacia sus nuevos submódulos canónicos o se mantiene la resolución vía facade re-exportador según corresponda. La prueba de frontend en Node.js se actualiza para consumir los nuevos archivos en `bandeja/web/`.
- **Compatibilidad externa**: Idéntica. Los comandos del usuario, scripts externos y el flujo de trabajo permanecen 100% inalterados.
