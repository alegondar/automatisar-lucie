# Design

## Context

El flujo de producción de contenidos para el proyecto Lucie genera continuamente archivos multimedia que se descargan en `~/Descargas`. Estos archivos deben ser detectados, agrupados y clasificados hacia la estructura espejo del proyecto (`~/Descargas/_lucie/<personaje>/videos sin editar/<escena>/`), garantizando que **no se toque el pendrive físico** y se respeten las 7 Reglas de Oro del proyecto (prohibición absoluta de borrado y pisado destructivo, simulación previa obligatoria, verificación de colisiones, registro auditable y reversibilidad).

## Goals / Non-Goals

**Goals:**
- Implementar un servicio local en Python estándar (`bandeja_descargas.py`) con sondeo periódico no invasivo y servidor web en `127.0.0.1` (puerto configurable, default `8766`).
- Aplicar una lista blanca estricta para procesar únicamente extensiones multimedia permitidas (`.mp4`, `.mov`, `.webm`, `.jpg`, `.jpeg`, `.png`, `.webp`) y patrones configurados en `config_bandeja.json` (`grok-video-*`, Nano Banana con marca temporal de 14 dígitos, y Flow editable).
- Identificar escenas existentes en `~/Descargas` (carpetas de 1er nivel con alias) y carpetas de escenas ya creadas en el destino, sin moverlas jamás.
- Proveer una pestaña para archivos multimedia sin identificar donde el usuario pueda catalogarlos como "del proyecto" o "ignorar", recordando la decisión por hash SHA-256 en SQLite.
- Ignorar archivos temporales (`.crdownload`, `.part`, `.tmp`) y descargas activas (verificación de estabilidad de tamaño durante 5 segundos).
- Agrupar automáticamente candidatos en lotes por proximidad de `mtime` (ventana de 10 min configurable) y emitir notificaciones con `notify-send` si está disponible.
- Ofrecer un panel web interactivo con miniaturas (generadas mediante `ffmpeg` si está instalado), selectores de personaje y escena, preselección del último personaje, simulación previa obligatoria y botón "Mover lote".
- Mover archivos exclusivamente con `os.rename` dentro de `~/Descargas` tras validar que el destino no existe (sufijo numérico en colisiones), confinando todas las rutas con `os.path.realpath`.
- Mantener una bitácora reversible `.jsonl` con opción de deshacer movimientos (utilizando `os.rename`, nunca borrando) y registrar estados en la tabla SQLite `bandeja_archivos`.
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
  - `DetectorDescargasActivas`: Seguimiento de tamaño y tiempo para descartar `.crdownload`, `.part`, `.tmp` y archivos con mutaciones en los últimos 5 segundos.
  - `AgrupadorLotes`: Agrupa archivos estables por cercanía de `mtime` dentro de la ventana configurada.
  - `GestorBaseDatosBandeja`: Gestión de la tabla `bandeja_archivos` en SQLite para recordar decisiones de archivos sin patrón y registrar estados.
  - `GestorMovimientosBandeja`: Confinamiento de rutas con `os.path.realpath`, creación de directorios, resolución de colisiones numéricas, ejecución atómica con `os.rename`, registro en bitácora `.jsonl` y reversión segura.
  - `BandejaHTTPHandler` y servidor `ThreadingHTTPServer`: Endpoints REST y servicio de la SPA embebida.
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
- **Razón**: Permite ajustar ventanas temporales y patrones (como el de Flow cuando se defina) sin modificar código.

### 3. Detección de Estabilidad de Descargas (5 segundos)
- **Decisión**: Mantener un diccionario en memoria `{ruta: (tamanio, timestamp)}`. Un archivo solo se considera elegible si su tamaño no ha cambiado durante al menos 5 segundos y no posee sufijos temporales.
- **Razón**: Previene mover videos o imágenes parcialmente descargados por el navegador o clientes de descarga.

### 4. Notificaciones de Escritorio con `notify-send`
- **Decisión**: Verificar `shutil.which("notify-send")`. Si existe, invocarlo de forma segura mediante `subprocess.run(["notify-send", "Proyecto Lucie", "Nuevo lote detectado en ~/Descargas..."], check=False)`.
- **Razón**: Brinda feedback inmediato al usuario en su entorno Linux sin añadir dependencias de librerías de notificación en Python.

### 5. Generación de Miniaturas con `ffmpeg`
- **Decisión**: Si `shutil.which("ffmpeg")` está disponible, extraer un fotograma en el segundo 1 (`ffmpeg -ss 00:00:01 -i <video> -vframes 1 -q:v 2 <miniatura.jpg>`) y almacenarlo en `.cache/miniaturas_bandeja/`. Para imágenes, servir directamente la imagen escalada o un thumbnail. Si no hay `ffmpeg`, la interfaz muestra un icono representativo de media.
- **Razón**: Permite al usuario identificar visualmente el contenido del lote antes de moverlo.

### 6. Resolución de Colisiones y Confinamiento de Rutas
- **Decisión**:
  - Validar confinamiento: `ruta_real = os.path.realpath(ruta)` debe comenzar con `descargas_real + "/"`. Si intenta salirse, se rechaza inmediatamente.
  - Colisión en destino: si `destino` ya existe, se genera `nombre (1).ext`, `nombre (2).ext` hasta encontrar un nombre disponible.
  - Movimiento: `os.rename(origen, destino)`. Al operar dentro de la misma partición (`~/Descargas`), `os.rename` es una llamada al sistema atómica que no copia ni borra.

### 7. Reversibilidad con Bitácora `.jsonl` y Función Deshacer
- **Decisión**: Cada movimiento de lote genera un registro en `bitacora_bandeja.jsonl` con la lista de `(origen_anterior, destino_nuevo, hash, fecha)`.
  - La función `deshacer(id_lote)` lee el registro correspondiente y ejecuta `os.rename(destino_nuevo, origen_anterior)` verificando que no exista colisión en el origen anterior. Si hay colisión, busca un sufijo disponible.
  - **Jamás se elimina ningún archivo durante el proceso de deshacer**.

### 8. Esquema de Base de Datos SQLite
- **Decisión**: Añadir a `.cache/inventario_pendrive_cache.sqlite` la tabla:
  ```sql
  CREATE TABLE IF NOT EXISTS bandeja_archivos (
      hash TEXT PRIMARY KEY,
      ruta_actual TEXT NOT NULL,
      estado TEXT NOT NULL, -- 'detectado', 'clasificado', 'ignorado', 'movido'
      personaje TEXT,
      escena TEXT,
      fecha TEXT NOT NULL
  );
  ```

## Endpoints de la API Local

| Ruta | Método | Descripción |
| :--- | :--- | :--- |
| `/` | `GET` | Interfaz web SPA (`bandeja.html`) |
| `/api/lotes` | `GET` | Lista de lotes agrupados con candidatos, miniaturas y metadatos |
| `/api/sin-identificar` | `GET` | Lista de archivos multimedia sin patrón reconocido |
| `/api/escenas` | `GET` | Escenas existentes (carpetas con alias en Descargas y en destino) |
| `/api/personajes` | `GET` | Lista de personajes disponibles y último personaje usado |
| `/api/clasificar-sin-identificar` | `POST` | Asignar decisión ("proyecto" o "ignorar") a archivo sin patrón |
| `/api/simular-mover` | `POST` | Simulación obligatoria: calcula y devuelve origen y destino exactos |
| `/api/mover-lote` | `POST` | Ejecuta el movimiento seguro del lote tras confirmación |
| `/api/deshacer` | `POST` | Revierte el movimiento de un lote moviendo los archivos a su origen |
| `/api/miniatura` | `GET` | Sirve la miniatura del archivo de video o imagen |

*(Nota de seguridad)*: A diferencia del dashboard de auditoría del pendrive (que era 100% de solo lectura con solo GETs), la bandeja de descargas requiere endpoints POST para autorizar interactivamente la clasificación y el movimiento atómico de archivos dentro de `~/Descargas`. Todos los POST validan confinamiento estricto de rutas y jamás invocan primitivas de borrado.

## Risks / Trade-offs

- **[Riesgo: Mover archivo que se sigue descargando]** → *Mitigación*: Validación de doble lectura con intervalo de 5 segundos y descarte estricto de extensiones `.crdownload`, `.part`, `.tmp`.
- **[Riesgo: Intento de mover archivos fuera de Descargas o hacia el pendrive]** → *Mitigación*: Validación con `os.path.realpath` que asegura que tanto el origen como el destino están confinados en `~/Descargas`. Prohibición absoluta de referencias al pendrive.
- **[Riesgo: Colisión de nombres en destino]** → *Mitigación*: Verificación de existencia previa con generación automática de sufijos numéricos correlativos (`video (1).mp4`), evitando sobrescrituras destructivas.
- **[Riesgo: Violación de la regla anti-borrado]** → *Mitigación*: Implementación exclusiva mediante `os.rename` (prohibido `shutil.move`, `os.replace`, `os.remove`, etc.) y verificación estricta con el analizador AST en `test_bandeja_descargas.py`.
