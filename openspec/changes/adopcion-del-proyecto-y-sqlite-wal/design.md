# Design: adopcion-del-proyecto-y-sqlite-wal

## Architectural Decisions

### 1. Precedencia de Adopción sobre Corte Temporal
Cuando un archivo no posee un prefijo o alias conocido (clasificado inicialmente como `sin_identificar`), carece de metadatos automáticos sobre personaje o escena. Al hacer clic en "Del Proyecto", el usuario toma una decisión explícita de gestión.
- **Regla**: Si `reg_bd.get("estado") == "clasificado"` o el archivo fue adoptado a mano, tiene prioridad sobre la regla de material antiguo/anterior (`es_anterior`).
- **Comportamiento en Vigilante**:
  - Se clasifica para el loteo principal (`candidatos_estables`).
  - No se le infiere alias ni escena de forma inventada (`personaje = None`, `escena = None`).
  - Se le agrega la propiedad `adoptado_a_mano = True`.
  - Aparece en la sección principal de "Lotes Detectados" (no en "Anteriores").
  - Su checkbox arranca seleccionado (`seleccionado: True`).
  - En el selector de escena, no se preselecciona ninguna, pero se incluyen todas las opciones disponibles (incluyendo la del capítulo en foco si existe).

### 2. Ciclo de Vida y Reversibilidad ("Deshacer")
- Al ejecutar `POST /api/clasificar-sin-identificar` con `es_proyecto: true`:
  - Se registra en `bandeja.db` el estado `clasificado` con metadatos de adopción.
  - El vigilante actualiza sus estructuras y aumenta `_version_token` para que los clientes en sondeo sincronicen de inmediato.
  - La respuesta HTTP devuelve éxito y los datos necesarios para revertir.
- Nuevo endpoint `POST /api/deshacer-clasificar-sin-identificar`:
  - Parámetros: `{ "hash": str, "ruta": str }`.
  - Reversión en base de datos: elimina o resetea el registro de decisión en `bandeja_sin_identificar` (o equivalente en `bandeja.db`).
  - El vigilante re-escanea o limpia el estado del archivo, restableciéndolo a `sin_identificar`.
  - Se incrementa `_version_token`.
- En el cliente web (`panel.js`):
  - Inmediatamente al hacer clic en "Del Proyecto" o "Ignorar", se remueve la fila del DOM con animación y feedback visual.
  - Se crea un toast/banner persistente:
    - Para "Del Proyecto": "Archivo adoptado a Lotes Detectados. [Ver en lotes] [Deshacer]"
    - Para "Ignorar": "Archivo marcado como ignorado. [Deshacer]"
  - Al pulsar "Deshacer", se ejecuta la llamada a `/api/deshacer-clasificar-sin-identificar` y se restaura el archivo en la tabla de "Sin Identificar".
  - Manejo de errores visibles: cualquier falla HTTP o de red se muestra en pantalla vía `mostrarError(mensaje)`, sin ser ignorada ni silenciada.

### 3. Concurrencia SQLite y Modo WAL
- Problema: Lecturas externas concurrentes (`sqlite3.OperationalError: database is locked`) debido a que SQLite por defecto opera con diario en modo DELETE y sin espera configurable ante bloqueos.
- Solución:
  - En `bandeja/db.py`, en el método de apertura de conexión (`_conectar`):
    ```python
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    ```
  - En la caché del inventario del pendrive (`.cache/inventario_pendrive_cache.sqlite` o `inventario_pendrive.py`):
    ```python
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    ```
  - Garantizar que las transacciones sean puntuales (`with conn: ...` o commit inmediato) evitando mantener conexiones abiertas con transacciones pendientes en hilos en reposo.

### 4. Robustez ante Refresco Automático en UI
- Los botones de la tabla "Sin Identificar" y de "Lotes Detectados" deben mantener sus event listeners o usar delegación de eventos en sus contenedores respectivos.
- De esta manera, las actualizaciones incrementales provocadas por el refresco automático de 4 segundos no invalidan los manejadores de eventos.
