# Proposal: adopcion-del-proyecto-y-sqlite-wal

## Why

En la bandeja de descargas, cuando el usuario presiona el botón "Del Proyecto" sobre un archivo en la sección "Sin Identificar" (por ejemplo `Man_smells_pole_on_bus_20261006062714.mp4` o imágenes `FB_IMG_*.jpg`), la interfaz no muestra ningún cambio visible ni confirmación, y el archivo desaparece por completo de todos los listados: no figura en "Lotes Detectados", no figura en "Anteriores al capítulo", y ya no está en "Sin Identificar". Además, procesos externos que leen concurrentemente la base de datos SQLite (`.cache/inventario_pendrive_cache.sqlite` o `bandeja.db`) fallan con `sqlite3.OperationalError: database is locked`.

La causa raíz se debe a una falla combinada en el backend y el frontend:
1. En el backend, al clasificar el hash como `clasificado`, `servidor.py` lo filtra de `sin_identificar`. Pero si la fecha de llegada es anterior al corte o al capítulo en foco (`es_anterior == True`), la rama `es_anterior` en `bandeja/vigilante.py` solo acepta archivos cuyo tipo sea `candidato`, descartando completamente los archivos marcados como `clasificado` (o no asignándoles lote válido). Como resultado, el archivo entra en un limbo ("black hole") donde ninguna lista lo incluye.
2. La adopción manual "Del Proyecto" es una decisión humana explícita que debe tener precedencia absoluta sobre el corte temporal: el archivo adoptado debe ubicarse en la sección principal de "Lotes Detectados" (no en "Anteriores"), marcado con insignia "Adoptado a mano", con checkbox tildado, sin personaje ni escena prefijados por alias, y permitiendo seleccionar cualquier escena (incluyendo el capítulo en foco).
3. En la interfaz web, no se daba retroalimentación inmediata (el archivo no desaparecía de inmediato de la tabla, ni se mostraba toast/banner con botón "Deshacer"), ni se incrementaba el token de versión del vigilante tras clasificar, impidiendo el refresco en tiempo real.
4. En SQLite, las conexiones operan en modo de diario tradicional (DELETE) sin `PRAGMA journal_mode=WAL` ni `PRAGMA busy_timeout=5000`, bloqueando la base por completo durante transacciones de escritura.

## What Changes

1. **Test de Regresión Inicial**:
   - Crear un test de regresión con servidor HTTP real que reproduzca la desaparición del archivo sin patrón tras invocar "Del Proyecto". Debe fallar antes de la corrección.

2. **Adopción Explícita y Prioridad en Vigilante**:
   - Registrar la adopción manual por hash y ruta con flag de adopción a mano.
   - En `bandeja/vigilante.py`, cuando un archivo tiene estado `clasificado` (o adoptado por el usuario), clasificarlo como candidato adoptado, ignorando el corte de `es_anterior` (forzando inclusión en la sección principal de Lotes Detectados).
   - Asignar atributo `adoptado_a_mano: True`, sin personaje ni escena inferidos de alias.
   - Incrementar de inmediato el token de versión del vigilante (`_version_token`) para forzar refresco instantáneo en el sondeo del panel.

3. **Mecanismo de Deshacer ("Deshacer Adopción" e "Ignorar")**:
   - Endpoint de reversión / deshacer para decisiones sobre archivos sin identificar (`POST /api/deshacer-clasificar-sin-identificar`).
   - Al deshacer, se revierte el estado en la base de datos SQLite y el archivo reaparece inmediatamente en "Sin Identificar" sin alterar archivos en disco.
   - Misma visibilidad y capacidad de deshacer para la acción "Ignorar".

4. **Interfaz Web y Experiencia de Usuario**:
   - En `panel.js`, al hacer clic en "Del Proyecto" o "Ignorar":
     - Remover inmediatamente la fila de la vista para respuesta instantánea.
     - Mostrar notificación toast/banner visible: "Agregado a Lotes Detectados" con enlace directo a la pestaña y botón "Deshacer".
     - Ante errores del servidor, mostrar el error exacto en pantalla (nunca silenciar).
     - Garantizar que los botones continúen funcionando tras los redibujados incrementales del refresco automático (delegación de eventos o re-vinculación robusta).
   - En la tarjeta/fila del lote en Lotes Detectados:
     - Mostrar insignia visual destacada "Adoptado a mano".
     - Checkbox tildado por defecto.
     - Selector de escena con todas las opciones disponibles (incluyendo la del capítulo en foco si existe), sin preseleccionar ninguna.

5. **Robustez y Concurrencia SQLite (WAL Mode)**:
   - Configurar `PRAGMA journal_mode=WAL;` y `PRAGMA busy_timeout=5000;` en todas las aperturas de base de datos (`bandeja/db.py` y `inventario_pendrive.py` / cachés SQLite).
   - Garantizar transacciones cortas y evitar escrituras redundantes durante ciclos de escaneo.
   - Agregar test que verifique lectura concurrente mientras se escribe en la base de datos sin errores de `database is locked`.

## Impact

- `bandeja/db.py`: Activación de WAL y busy_timeout, métodos para registrar adopción a mano y revertir decisiones de archivos sin identificar.
- `bandeja/vigilante.py`: Lógica para procesar archivos adoptados a mano con precedencia sobre corte reciente, incremento de `_version_token`.
- `bandeja/servidor.py`: Endpoints para adopción y reversión inmediata, exposición de atributos `adoptado_a_mano`.
- `bandeja/web/panel.js`, `bandeja/web/panel.html`, `bandeja/web/panel.css`: Feedback interactivo inmediato, banners/toasts con "Deshacer", renderizado de insignia "Adoptado a mano" y selectores de escenas.
- `inventario_pendrive.py`: Configuración de WAL y timeout en la caché SQLite del inventario.
