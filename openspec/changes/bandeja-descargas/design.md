# Design

## Context

El flujo de producción de contenidos para el proyecto Lucie genera continuamente archivos multimedia que se descargan en `~/Descargas`. Estos archivos deben ser detectados, agrupados y clasificados hacia la estructura espejo del proyecto (`~/Descargas/_lucie/<personaje>/videos sin editar/<escena>/`), o hacia carpetas de escenas ya existentes en `~/Descargas`, garantizando que **no se toque el pendrive físico** y se respeten las 7 Reglas de Oro del proyecto (prohibición absoluta de borrado y pisado destructivo, simulación previa obligatoria, verificación de colisiones, registro auditable y reversibilidad).

## Goals / Non-Goals

**Goals:**
- Implementar un servicio local en Python estándar (`bandeja_descargas.py`) con sondeo periódico no invasivo y servidor web en `127.0.0.1` (puerto configurable, default `8766`).
- Aplicar una lista blanca estricta para procesar únicamente extensiones multimedia permitidas (`.mp4`, `.mov`, `.webm`, `.jpg`, `.jpeg`, `.png`, `.webp`) y patrones configurados en `config_bandeja.json` (`grok-video-*`, Nano Banana con marca temporal de 14 dígitos, y Flow editable).
- Identificar escenas existentes en `~/Descargas` (carpetas de 1er nivel con alias) y carpetas de escenas ya creadas en el destino, permitiendo enviar archivos directamente a ellas sin reordenarlas ni moverlas.
- Validar de manera rigurosa los nombres de escena (máximo 100 caracteres, sin `/`, `\`, `..`, caracteres de control, caracteres inválidos de Windows/exFAT `< > : " | ? *`, sin punto o espacio al final, y excluyendo nombres reservados de Windows como `CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`).
- Implementar protección anti-CSRF y verificación de cabeceras (`Host: 127.0.0.1:<puerto>` y `Content-Type: application/json`) respondiendo `403 Forbidden` ante solicitudes no autorizadas.
- Proveer una pestaña para archivos multimedia sin identificar donde el usuario pueda catalogarlos como "del proyecto" o "ignorar", recordando la decisión por hash SHA-256 en SQLite.
- Ignorar archivos temporales (`.crdownload`, `.part`, `.tmp`) y descargas activas (verificación de estabilidad de tamaño durante 5 segundos).
- Agrupar automáticamente candidatos en lotes por proximidad de `mtime` (ventana de 10 min configurable) y emitir notificaciones con `notify-send` si está disponible.
- Ofrecer un panel web interactivo con miniaturas seguras generadas vía `ffmpeg` referenciadas por ID de archivo en base de datos (nunca por ruta directa), selectores de personaje y escena, preselección del último personaje, simulación previa obligatoria y botón "Mover lote".
- Mover archivos exclusivamente con `os.rename` dentro de `~/Descargas` tras validar que el destino no existe (sufijo numérico en colisiones en el destino inicial), confinando todas las rutas con `os.path.realpath`.
- Mantener una bitácora reversible `.jsonl` con función de deshacer que devuelva los archivos a su ruta original mediante `os.rename`; si la ruta original ya está ocupada, la reversión se niega terminantemente (sin pisar ni sufijar jamás).
- Registrar estados en la tabla SQLite `bandeja_archivos` e ignorar bitácoras en `.gitignore`.
- Garantizar 0 violaciones en el analizador estático AST anti-borrado.

**Non-Goals:**
- No acceder, montar, copiar, mover ni alterar nada en el pendrive físico (`/run/media/...`).
- No utilizar primitivas de borrado (`os.remove`, `os.unlink`, `shutil.rmtree`, `send2trash`, etc.) ni de pisado ciego (`shutil.move`, `os.replace`).
- No procesar ni leer archivos o carpetas que no pertenezcan a la lista blanca.
- No depender de frameworks web externos (Flask, FastAPI) ni dependencias externas de Node.js/npm.

## Decisions

### 1. Módulo Unificado `bandeja_descargas.py` y Componentes
- **Decisión**: Estructurar la lógica en componentes desacoplados dentro de `bandeja_descargas.py`:
  - `ConfiguracionBandeja`: Carga y validación de `config_bandeja.json`.
  - `FiltroListaBlanca`: Validación estricta de nombres y extensiones. Lo no coincidente no se abre ni se procesa.
  - `ValidadorEscenas`: Validación exhaustiva de nombres de escena (longitud, caracteres especiales, nombres reservados) y resolución canónica con `os.path.realpath`.
  - `DetectorDescargasActivas`: Seguimiento de tamaño y tiempo para descartar `.crdownload`, `.part`, `.tmp` y archivos con mutaciones en los últimos 5 segundos.
  - `AgrupadorLotes`: Agrupa archivos estables por cercanía de `mtime` dentro de la ventana configurada.
  - `GestorBaseDatosBandeja`: Gestión de la tabla `bandeja_archivos` en SQLite para registrar archivos, recordar decisiones de archivos sin patrón y resolver IDs para miniaturas.
  - `GestorMovimientosBandeja`: Confinamiento de rutas con `os.path.realpath`, creación de directorios, resolución de colisiones numéricas en destino inicial, ejecución atómica con `os.rename`, registro en bitácora `.jsonl` y reversión estricta (rechazando si el origen está ocupado).
  - `BandejaHTTPHandler` y servidor `ThreadingHTTPServer`: Generación de token anti-CSRF al iniciar, validación de cabeceras en endpoints POST, endpoints REST y servicio de la SPA embebida.
- **Razón**: Mantiene el código autocontenido, fácil de probar con `unittest` en `/tmp` y auditable por el analizador AST.

### 2. Formato de `config_bandeja.json`
- **Decisión**: Crear un archivo de configuración JSON con la siguiente estructura:
  ```json
  {
    "ruta_descargas": "~/Descargas",
    "ruta_destino_base": "~/Descargas/_lucie",
    "puerto_servidor": 8766,
    "host_servidor": "127.0.0.1",
    "intervalo_sondeo_segundos": 5,
    "ventana_lote_minutos": 10,
    "extensiones_media": [".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".webp"],
    "patrones_candidatos": {
      "grok": "grok-video-*",
      "nano_banana_regex": "^.+_\\d{14}\\.(jpg|jpeg|png|webp)$",
      "flow": ""
    },
    "extensiones_temporales": [".crdownload", ".part", ".tmp"]
  }
  ```

### 3. Validación Exhaustiva de Nombres de Escena
- **Decisión**: La función `validar_nombre_escena(nombre: str)` valida:
  - Longitud: `1 <= len(nombre) <= 100`.
  - Prohibición de separadores y navegación: rechaza si contiene `/`, `\`, o `..`.
  - Caracteres de control: rechaza si algún carácter tiene código ASCII `< 32`.
  - Caracteres inválidos en sistemas de archivos Windows/exFAT: rechaza si contiene `< > : " | ? *`.
  - Fin de nombre: rechaza si termina con punto `.` o espacio ` `.
  - Nombres reservados de Windows: rechaza si el nombre base (ignorando mayúsculas y extensiones) coincide con `CON`, `PRN`, `AUX`, `NUL`, `COM1` a `COM9`, o `LPT1` a `LPT9`.
  - Confinamiento con `os.path.realpath`: calcula la ruta absoluta final y verifica que empiece estrictamente con el directorio de destino canónico.
- **Razón**: Asegura interoperabilidad total si el contenido luego se copia a discos exFAT/FAT32 y previene vulnerabilidades de path traversal.

### 4. Enrutamiento de Destino: Escenas Existentes vs Nuevas
- **Decisión**:
  - **Escena existente en `~/Descargas` (carpeta con alias)**: Si el usuario selecciona una carpeta existente de Descargas (ej. `~/Descargas/roli parque`), los archivos del lote se mueven directamente al interior de esa carpeta (`~/Descargas/roli parque/<archivo>`). La carpeta existente no se mueve, no se renombra ni se altera en su estructura.
  - **Escena nueva o existente en `<destino>`**: Se crea y utiliza la ruta canónica `<destino>/<personaje>/videos sin editar/<escena>/<archivo>`.
- **Razón**: Permite alimentar carpetas de trabajo activas sin duplicar jerarquías innecesarias.

### 5. Protección Anti-CSRF y Validación de Cabeceras
- **Decisión**:
  - Al iniciar, el servidor genera un token aleatorio con `secrets.token_urlsafe(32)`.
  - El token se inyecta en el HTML de la página cliente.
  - En todos los endpoints `POST` (`/api/mover-lote`, `/api/deshacer`, `/api/clasificar-sin-identificar`):
    - Se verifica la cabecera `X-CSRF-Token` contra el token generado usando `hmac.compare_digest`.
    - Se verifica que la cabecera `Content-Type` comience con `application/json`.
    - Se verifica que la cabecera `Host` sea exactamente `127.0.0.1:<puerto>`.
    - Si cualquiera de estas validaciones falla, se rechaza la petición con `HTTP 403 Forbidden` y payload JSON con el motivo.
- **Razón**: Bloquea cualquier intento de Cross-Site Request Forgery desde navegadores que visiten sitios maliciosos en otras pestañas.

### 6. Generación Segura de Miniaturas vía Identificador y ffmpeg
- **Decisión**:
  - El endpoint `/api/miniatura?id=<archivo_id>` recibe un identificador numérico o hash registrado en SQLite. **Nunca se acepta una ruta de archivo como parámetro**.
  - El servidor busca el ID en la base de datos para obtener la ruta del archivo validada.
  - Al invocar `ffmpeg`, se ejecuta mediante `subprocess.run` con lista de argumentos explícita, `shell=False` y el separador `--` antes de la ruta del archivo para evitar inyección de comandos o flags si el nombre empieza con guión:
    `["ffmpeg", "-y", "-ss", "00:00:01", "-i", "--", ruta_archivo, "-vframes", "1", "-q:v", "2", ruta_miniatura]`
- **Razón**: Evita ataques de inyección de rutas (LFI) o flags maliciosos en la línea de comandos de `ffmpeg`.

### 7. Deshacer Estricto sin Pisado ni Sufijado
- **Decisión**:
  - Al solicitar deshacer una operación, se lee el registro en `bitacora_bandeja.jsonl`.
  - Para cada archivo a restaurar, se comprueba si la ruta original de origen ya existe (`os.path.exists(origen_anterior)`).
  - Si la ruta original ya está ocupada por otro archivo: **el proceso de deshacer se niega por completo**, informando con un mensaje claro al usuario: *"No se puede deshacer: la ruta original '<ruta>' ya está ocupada. No se sobrescribe ni se altera ningún archivo."*
  - **Nunca se sobrescribe y nunca se añade sufijo numérico durante el deshacer**.
- **Razón**: Garantiza la integridad absoluta de los datos sin alterar archivos preexistentes en la carpeta de descargas.

### 8. Esquema de Base de Datos SQLite
- **Decisión**: Añadir a `.cache/inventario_pendrive_cache.sqlite` la tabla:
  ```sql
  CREATE TABLE IF NOT EXISTS bandeja_archivos (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      hash TEXT UNIQUE NOT NULL,
      ruta_actual TEXT NOT NULL,
      estado TEXT NOT NULL, -- 'detectado', 'clasificado', 'ignorado', 'movido'
      personaje TEXT,
      escena TEXT,
      fecha TEXT NOT NULL
  );
  ```

## Endpoints de la API Local

| Ruta | Método | Seguridad / Requisitos | Descripción |
| :--- | :--- | :--- | :--- |
| `/` | `GET` | Ninguna | Interfaz web SPA (`bandeja.html`) con token CSRF embebido |
| `/api/lotes` | `GET` | Ninguna | Lista de lotes agrupados con candidatos, IDs de miniatura y metadatos |
| `/api/sin-identificar` | `GET` | Ninguna | Lista de archivos multimedia sin patrón reconocido |
| `/api/escenas` | `GET` | Ninguna | Escenas existentes (carpetas con alias en Descargas y en destino) |
| `/api/personajes` | `GET` | Ninguna | Lista de personajes disponibles y último personaje usado |
| `/api/miniatura` | `GET` | Requiere `?id=<archivo_id>` registrado | Genera y sirve miniatura segura vía `ffmpeg` con `--` |
| `/api/clasificar-sin-identificar` | `POST` | Requiere CSRF, Host y JSON | Asignar decisión ("proyecto" o "ignorar") a archivo sin patrón |
| `/api/simular-mover` | `POST` | Requiere CSRF, Host y JSON | Simulación obligatoria: valida escena y devuelve origen y destino exactos |
| `/api/mover-lote` | `POST` | Requiere CSRF, Host y JSON | Ejecuta el movimiento seguro del lote tras confirmación |
| `/api/deshacer` | `POST` | Requiere CSRF, Host y JSON | Revierte un lote; rechaza si la ruta original está ocupada |

## Risks / Trade-offs

- **[Riesgo: Mover archivo que se sigue descargando]** → *Mitigación*: Validación de doble lectura con intervalo de 5 segundos y descarte estricto de extensiones `.crdownload`, `.part`, `.tmp`.
- **[Riesgo: Intento de mover archivos fuera de Descargas o hacia el pendrive]** → *Mitigación*: Validación con `os.path.realpath` que asegura que tanto el origen como el destino están confinados en `~/Descargas`. Prohibición absoluta de referencias al pendrive.
- **[Riesgo: Inyección de comandos o path traversal en nombres de escena]** → *Mitigación*: Validación estricta con lista negra de caracteres prohibidos, nombres reservados de Windows y verificación canónica con `os.path.realpath`.
- **[Riesgo: Inyección en ffmpeg o acceso a archivos arbitrarios vía /api/miniatura]** → *Mitigación*: Consulta obligatoria de ID en SQLite, ejecución de `ffmpeg` sin shell y con el flag `--`.
- **[Riesgo: Peticiones foráneas vía CSRF o DNS rebinding]** → *Mitigación*: Token anti-CSRF aleatorio, validación estricta de encabezado `Host: 127.0.0.1:<puerto>` y `Content-Type: application/json`.
- **[Riesgo: Conflicto de archivos al deshacer un movimiento]** → *Mitigación*: Negativa inmediata a deshacer si el destino previo está ocupado, sin pisar ni crear sufijos no deseados.
