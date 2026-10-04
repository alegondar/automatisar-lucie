# Design

## Context

El proyecto `automatisar-lucie` organiza descargas en `~/Descargas/_lucie/<personaje>/{videos sin editar,imagenes}/<escena>/`. Hasta ahora, el flujo terminaba en el disco local. Para completar el ciclo de producción, el material clasificado debe transferirse físicamente al pendrive consolidado (`/run/media/<usuario>/<pendrive>/videos1`), garantizando que jamás se borren archivos, que las transferencias sean verificadas por integridad (SHA-256) y que cualquier envío pueda revertirse sin riesgo de pérdida de datos.

Este diseño define la arquitectura del módulo de envío, los pre-chequeos del sistema de archivos, el protocolo de copia atómica y verificación, la integración con la SPA existente en `127.0.0.1:8766`, y el aislamiento estricto respecto de las 7 Reglas de Oro.

## Goals / Non-Goals

**Goals:**
- Módulo `envio_pendrive.py` desacoplado y reutilizable, con configuración en `config_envio.json`.
- Integración en el servidor HTTP de `bandeja_descargas.py` bajo rutas `/api/envio/*` compartiendo puerto `8766`, token anti-CSRF y validación de `Host`.
- Nueva pestaña en la SPA ("Envío al pendrive") con diagnóstico en tiempo real del medio físico.
- Pre-chequeos automáticos: `os.path.ismount`, existencia de `videos1`, verificación de modo de solo lectura (`ST_RDONLY`), y margen de espacio libre de al menos 1 GB sobre el tamaño de la escena.
- Protocolo de copia en bloques binarios con creación exclusiva (`'xb'`) en archivo temporal oculto `.<nombre>.parcial`, vaciado a disco (`os.fsync`) y comparación de hash SHA-256 contra el origen.
- Preservación de originales en `~/Descargas/_lucie/_enviados/<ruta relativa>` con `os.rename` tras copia exitosa.
- Desvío de archivos fallidos a `<raiz_pendrive>/_a_revisar/copias_fallidas/<ruta relativa>` sin borrado.
- Manejo de colisiones en destino: omisión si el hash es idéntico ("ya estaba") o sufijo numérico correlativo si el hash es diferente.
- Función de deshacer: reubicación de la copia a `<raiz_pendrive>/_a_revisar/envios_deshechos/<ruta relativa>` y restauración del original desde `_enviados/`.
- Registro auditable en `bitacora_envio.jsonl` y SQLite con estado `"en_pendrive"`.
- 0 violaciones en el análisis estático AST anti-borrado.

**Non-Goals:**
- No implementar envíos recursivos masivos globales ("enviar todo"): la unidad de transferencia y aprobación es estrictamente la escena.
- No modificar ni sobrescribir archivos preexistentes en el pendrive bajo ninguna circunstancia.
- No utilizar `shutil.move` ni `os.replace` (prohibidos por Regla de Oro #1).
- No depender de herramientas de sincronización externas como `rsync` o utilidades del sistema con llamadas a `shell`.

## Decisions

### 1. Módulo Especializado `envio_pendrive.py` y Componentes
- **Decisión**: Crear un módulo dedicado `envio_pendrive.py` que encapsule:
  - `ConfiguracionEnvio`: Carga de `config_envio.json` con valores por defecto seguros.
  - `VerificadorPendrive`: Comprobaciones de punto de montaje (`os.path.ismount`), existencia del directorio base `videos1`, flag `ST_RDONLY` mediante `os.statvfs`, y cálculo de espacio libre restante con margen de 1 GB.
  - `GestorEnvioPendrive`: Lógica de simulación previa por escena, copia atómica en bloques binarios, verificación SHA-256, resolución de colisiones y reubicación a `_enviados` y `_a_revisar`.
- **Razón**: Mantiene la lógica de bajo nivel desacoplada del servidor web y facilita la ejecución de pruebas unitarias con sistemas de archivos simulados en `/tmp`.
- **Alternativa descartada**: Incrustar toda la lógica en `bandeja_descargas.py`. Se descartó para no sobrecargar dicho archivo y mantener modularidad limpia.

### 2. Protocolo de Copia Atómica y Verificación en Dos Pasos
- **Decisión**:
  1. El archivo se abre en el pendrive con modo `'xb'` en la ruta temporal `.<nombre>.parcial`. Si ya existe el temporal, se añade un contador para evitar colisión de temporales.
  2. La lectura y escritura se realiza en bloques de 1 MB actualizando el hash SHA-256 en memoria para el archivo de origen y para el destino.
  3. Al completar los bloques, se invoca `os.fsync(f.fileno())` antes de cerrar el descriptor de archivo para forzar la escritura en el dispositivo físico.
  4. Se valida si ambos hashes coinciden:
     - **Coincidencia**: Se verifica que el nombre final no exista y se ejecuta `os.rename(temp, final)`. Luego se mueve el original a `_enviados/` con `os.rename`.
     - **Discrepancia o error de E/S**: Se ejecuta `os.rename(temp, os.path.join(raiz, "_a_revisar", "copias_fallidas", ruta_relativa))`. En ningún caso se invoca `os.remove` ni ninguna función destructiva.
- **Razón**: El pendrive puede desconectarse abruptamente o tener sectores defectuosos; el archivo temporal oculto evita que archivos truncados se interpreten como válidos, y `os.fsync` garantiza que los datos residan en la memoria flash antes del chequeo de hash.
- **Alternativa descartada**: Copiar directamente al nombre final. Se descartó porque ante una interrupción o corte quedaría un archivo corrupto visible e incompleto.

### 3. Preservación del Original en `_enviados` (Mismo Sistema de Archivos)
- **Decisión**: Tras la verificación exitosa, el archivo local original se mueve de `~/Descargas/_lucie/<personaje>/<subcarpeta>/<escena>/<archivo>` a `~/Descargas/_lucie/_enviados/<personaje>/<subcarpeta>/<escena>/<archivo>` mediante `os.rename`.
- **Razón**: Al permanecer dentro del mismo volumen de disco (`~/Descargas`), `os.rename` es una operación atómica de puntero de inodo instantánea que no consume espacio adicional ni realiza copia física, y cumple la prohibición de borrado preservando el archivo original.

### 4. Resolución de Colisiones en Pendrive
- **Decisión**:
  - Si en la ruta destino `<raiz>/videos1/<personaje>/<tipo>/<escena>/<archivo>` ya existe un archivo:
    - Se calcula su hash SHA-256.
    - Si `hash(destino) == hash(origen)`: Se omite la copia, se clasifica en la simulación como `"ya_estaba"` y se reubica el original a `_enviados`.
    - Si `hash(destino) != hash(origen)`: Se genera un sufijo numérico correlativo (ej. `archivo_1.mp4`, `archivo_2.mp4`) buscando el primer nombre no existente para transferir la nueva versión sin tocar la existente.
- **Razón**: Evita transferencias redundantes si la escena ya fue enviada previamente, y protege contra sobreescritura accidental si existen dos tomas con el mismo nombre y diferente contenido.

### 5. Reversibilidad (Deshacer Envío)
- **Decisión**:
  - Al solicitar deshacer una operación de envío:
    1. La copia que se encuentra en el pendrive se mueve con `os.rename` hacia `<raiz_pendrive>/_a_revisar/envios_deshechos/<ruta relativa>`.
    2. El archivo original en `~/Descargas/_lucie/_enviados/<ruta relativa>` se mueve de regreso con `os.rename` a su ubicación previa en `~/Descargas/_lucie/`.
    3. Si la ruta original previa está ocupada por otro archivo, o si falta el original en `_enviados`, la operación aborta con error 409 y mensaje explícito, sin realizar modificaciones parciales.
- **Razón**: Permite corregir envíos erróneos sin destruir los datos transferidos ni sobrescribir archivos nuevos generados en el área de trabajo.

### 6. Integración en el Servidor Web Existente y Panel SPA
- **Decisión**:
  - Extender `HandlerServidorBandeja` en `bandeja_descargas.py` para mapear las rutas:
    - `GET /api/envio/estado-pendrive`: Devuelve estado de montaje, solo lectura, espacio libre y margen.
    - `GET /api/envio/escenas-disponibles`: Lista personajes y escenas presentes en `~/Descargas/_lucie` (excluyendo `_enviados`).
    - `POST /api/envio/simular`: Devuelve la simulación previa detallada de la escena seleccionada.
    - `POST /api/envio/ejecutar`: Ejecuta la transferencia de la escena simulada.
    - `GET /api/envio/historial`: Lista los envíos recientes desde `bitacora_envio.jsonl`.
    - `POST /api/envio/deshacer`: Revierte un envío específico.
  - La SPA agrega la pestaña "Envío al pendrive", consumiendo la misma sesión y token `CSRF_TOKEN`.
- **Razón**: Ofrece una experiencia unificada en un solo puerto local, evitando la proliferación de procesos y configuraciones de red.

### 7. Confinamiento de Rutas y Filtros en Bandeja e Inventario
- **Decisión**:
  - `FiltroListaBlanca` e `inventario_pendrive.py` deben ignorar expresamente cualquier directorio con nombre `_enviados` o `_a_revisar`, así como archivos que comiencen con `.` o terminen en `.parcial`.
  - Confinamiento con `os.path.realpath` para asegurar que el origen no escape de `~/Descargas/_lucie` y el destino no escape de `<raiz_pendrive>/videos1`.

## Risks / Trade-offs

- **[Riesgo: Desconexión accidental del pendrive durante la copia]** → **Mitigación**: La escritura en modo exclusivo en un archivo temporal oculto `.<nombre>.parcial` previene que archivos incompletos sean considerados válidos. Al reconectar el pendrive, el archivo parcial no altera el destino y, ante errores, se aísla en `_a_revisar/copias_fallidas`.
- **[Riesgo: El usuario intenta enviar sin verificar previamente el espacio]** → **Mitigación**: El endpoint de simulación y el de ejecución calculan preventivamente `espacio_libre >= total_bytes + 1 GB`. Si no se cumple, la transferencia se bloquea antes de crear ningún archivo.
- **[Riesgo: Violación accidental de las primitivas anti-borrado]** → **Mitigación**: El código de `envio_pendrive.py` y `bandeja_descargas.py` solo utiliza `open('xb')` y `os.rename`. El test estático AST en `seguridad_anti_borrado.py` audita ambos archivos garantizando 0 violaciones.
- **[Riesgo: Pendrive montado en solo lectura por fallos en sistema de archivos]** → **Mitigación**: `VerificadorPendrive` consulta `os.statvfs(raiz).f_flag & os.ST_RDONLY`. Si está activo, el sistema bloquea inmediatamente la interfaz con una advertencia explicativa.
