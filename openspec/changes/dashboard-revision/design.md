# Design

## Context

El proyecto `automatisar-lucie` cuenta con módulos de inventario (`inventario_pendrive.py`) y generación de plan (`plan_limpieza.py`) que producen archivos JSON detallados (`informe_pendrive.json`, `plan_limpieza.json`) y una base de metadatos SQLite (`.cache/inventario_pendrive_cache.sqlite`).

Para auditar y validar estas decisiones antes de cualquier acción física, se requiere un dashboard interactivo local. Conforme a las Reglas de Oro, la herramienta debe ser de solo lectura estricta, no depender de librerías externas de terceros y operar aislada en la interfaz `127.0.0.1` (puerto predeterminado `8765`, evitando el puerto `8000` ocupado por Portainer).

## Goals / Non-Goals

**Goals:**
- Implementar un servidor HTTP en Python estándar (`http.server.ThreadingHTTPServer`) sin dependencias de terceros (`Flask`, `FastAPI`, etc.).
- Exponer una interfaz REST de solo lectura con métodos `GET` exclusivos, respondiendo con `405 Method Not Allowed` a cualquier intento de mutación (`POST`, `PUT`, `DELETE`, `PATCH`).
- Proveer una interfaz gráfica SPA en HTML5/CSS/JavaScript vanilla con tema oscuro, responsive y 100% funcional sin conexión a internet.
- Ofrecer un banner fijo visible `"SOLO LECTURA: este panel no modifica nada"` y botón de recarga de datos en memoria.
- Presentar las 7 vistas especializadas requeridas: Resumen, Por carpeta 1er nivel con barras, Por personaje y estado con duración de videos, Duplicados detallados, Plan de limpieza con checkbox "revisado" en `localStorage`, Sección destacada de diferencias `laroli`, y Archivos sueltos.
- Garantizar total cumplimiento de las Reglas de Oro mediante tests unitarios (`unittest`) con fixtures en `/tmp` y auditoría estática AST anti-borrado.

**Non-Goals:**
- No implementar funciones de ejecución, copia, movimiento ni borrado de archivos.
- No permitir modificaciones al pendrive ni a directorios locales desde el navegador.
- No persistir en disco el estado de las casillas de verificación (revisión se mantiene únicamente en `localStorage` del cliente).
- No exponer el servicio a interfaces de red públicas (exclusivo para `127.0.0.1`).

## Decisions

### 1. Servidor HTTP estándar vs Framework externo
- **Decisión**: Utilizar `http.server.ThreadingHTTPServer` y `http.server.BaseHTTPRequestHandler` de la biblioteca estándar de Python.
- **Razón**: Evita instalar paquetes externos (`pip`), facilitando la ejecución inmediata en cualquier entorno con Python 3 estándar, garantizando estabilidad y ligereza.
- **Alternativas consideradas**:
  - *Flask/FastAPI*: Ofrecen ruteo más expresivo, pero añaden dependencias de terceros y riesgo de desactualización en entornos offline.

### 2. Estructura modular del servidor (`servidor_dashboard.py`)
- **Decisión**: Estructurar el backend en dos capas principales:
  1. `ProveedorDatosDashboard`: Clase encargada de cargar y procesar en memoria `informe_pendrive.json`, `plan_limpieza.json` y consultar la base SQLite en modo solo lectura (`file:...mode=ro`). Provee métodos para calcular métricas agregadas y recargar los datos.
  2. `DashboardHandler`: Manejador HTTP que valida el método (`GET` obligatorio; rechazo de otros métodos con código `405`), procesa las rutas de la API (`/api/*`) y sirve la SPA (`/` o `/index.html`).
- **Razón**: Desacopla la lógica de agregación y parsing de la capa de transporte HTTP, permitiendo testear las respuestas de datos de forma unitaria sin necesidad de levantar sockets de red durante todos los tests.

### 3. Conexión SQLite en modo estricto de solo lectura
- **Decisión**: Utilizar la URI de SQLite `file:{ruta}?mode=ro` al interactuar con `.cache/inventario_pendrive_cache.sqlite`.
- **Razón**: Cumple estrictamente con la Regla de Oro #1, asegurando que SQLite no intente abrir archivos de bloqueo en modo escritura ni modificar la base.

### 4. Arquitectura de la SPA Frontend
- **Decisión**: Desarrollar la interfaz en un único archivo HTML autocontenido (`dashboard.html` o servido por el script) con estilos CSS embebidos (variables de tema oscuro: fondos `#121212`, `#1e1e1e`, texto `#e0e0e0`, acentos `#bb86fc`, `#03dac6`, `#cf6679`) y JavaScript vanilla sin librerías externas.
- **Razón**: Elimina cualquier necesidad de descargar recursos desde CDNs, asegurando que el dashboard funcione sin conexión a internet y sin vulnerabilidades de supply-chain.

### 5. Deducción de Personajes, Estados y Duraciones
- **Decisión**:
  - **Personajes**: Deducidos a partir de las carpetas y reglas de alias (`lucie`, `roli` / `laroli`, `mailen`).
  - **Estados**: Deducidos de las carpetas conocidas (`videos sin editar`, `videos ya editados`, `videos completos`, `videos sin publicar`). Rutas que no contengan estas carpetas se clasifican como `sin clasificar`.
  - **Duración de videos**: Obtenida cruzando las rutas relativas contra el campo `duration` de la tabla `cache_archivos` en SQLite.
  - **Diferencias laroli**: Identificar archivos presentes en `laroli/` vs `videos1/laroli/` calculando la diferencia simétrica relativa para resaltar qué archivos existen exclusivamente en una sola de las dos ubicaciones.

### 6. Persistencia de auditoría en el cliente (`localStorage`)
- **Decisión**: Almacenar el estado de las casillas "revisado" de las acciones del plan en la clave `dashboard_acciones_revisadas` del `localStorage` del navegador, asociando los IDs únicos de acción.
- **Razón**: Permite al operador mantener control visual de su avance en la revisión del plan sin emitir llamadas de escritura al backend ni alterar archivos en el disco o pendrive.

## Endpoints de la API

| Ruta | Método | Descripción |
| :--- | :--- | :--- |
| `/` | `GET` | Interfaz gráfica SPA (`dashboard.html`) |
| `/api/resumen` | `GET` | Métricas generales de disco, conteo de archivos, duplicados y acciones |
| `/api/carpetas` | `GET` | Peso y conteo por carpeta de 1er nivel y categoría (video, foto, etc.) |
| `/api/personajes` | `GET` | Agrupación por personaje y estado con cantidad de videos y duración total |
| `/api/duplicados` | `GET` | Grupos de duplicados con filtros inter/intra/protegidas y tamaños |
| `/api/plan` | `GET` | Acciones del plan de limpieza con detalles, motivos y origen/destino |
| `/api/laroli-dif` | `GET` | Comparación de archivos exclusivos en `laroli` vs `videos1/laroli` |
| `/api/sueltos` | `GET` | Archivos sueltos clasificados por alias vs sin clasificar |
| `/api/recargar` | `GET` | Recarga en memoria los archivos JSON y caché sin reiniciar el servidor |

Cualquier petición con método `POST`, `PUT`, `DELETE` o `PATCH` responderá inmediatamente con `HTTP 405 Method Not Allowed`.

## Risks / Trade-offs

- **[Riesgo: Bloqueo de puerto 8765]** → *Mitigación*: Implementar argumento CLI `--puerto` / `-p` para permitir cambiar el puerto al vuelo, emitiendo un mensaje claro si el puerto está en uso.
- **[Riesgo: Volumen grande de acciones y duplicados en el navegador]** → *Mitigación*: Implementar paginación o renderizado eficiente de tablas con filtros dinámicos en JavaScript vanilla, evitando bloqueos de la interfaz.
- **[Riesgo: Desincronización si cambian los archivos en disco]** → *Mitigación*: Endpoint `/api/recargar` y botón visible para forzar lectura fresca de los archivos JSON en cualquier momento sin alterar el estado local de revisión.
- **[Riesgo: Caché agresiva del navegador en APIs]** → *Mitigación*: Incluir cabeceras HTTP `Cache-Control: no-cache, no-store, must-revalidate` en todas las respuestas JSON.
