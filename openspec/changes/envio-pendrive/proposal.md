# Proposal

## Why

El flujo de trabajo actual permite clasificar y organizar descargas multimedia dentro de `~/Descargas/_lucie`, pero carece de un mecanismo controlado, seguro y auditable para transferir las escenas terminadas al almacenamiento externo físico (pendrive) donde se consolida el material final. 

Esta propuesta introduce un módulo y flujo de envío por escena con validación de integridad previa y posterior (sha256), pre-chequeos estrictos de montaje, permisos y espacio libre con margen de 1 GB, creación atómica exclusiva en archivos temporales `.parcial`, preservación sin borrado en `_enviados` y `_a_revisar`, capacidad de reversión completa y registro auditable en bitácora `.jsonl` y base de datos SQLite, respetando estrictamente las 7 Reglas de Oro del proyecto.

## What Changes

- **Nuevo archivo de configuración `config_envio.json`**: Define la ruta de origen base (`~/Descargas/_lucie`), raíz de pendrive (default `/run/media/<usuario>/<pendrive>`), subcarpeta destino de videos (`videos1`), tamaño de buffer para copia en bloques, margen mínimo de seguridad en disco (1 GB) y rutas para bitácoras y registros.
- **Pre-chequeos de seguridad del pendrive**: Detección y bloqueo preventivo si la raíz no es punto de montaje (`os.path.ismount`), si no existe el directorio base `videos1`, si el medio está montado en solo lectura (`os.statvfs` con `ST_RDONLY`), o si el espacio libre disponible es inferior al tamaño del lote a copiar más 1 GB de margen.
- **Flujo de envío escena por escena (sin envíos masivos a ciegas)**:
  - Simulación previa (`dry-run`) detallada de cada archivo de la escena: origen, destino proyectado, tamaño en bytes y estado (`nuevo`, `ya existe idéntico`, `ya existe distinto`).
  - Copia atómica en bloques binarios hacia un archivo temporal oculto `.<nombre>.parcial` en la carpeta destino creado con modo exclusivo (`'xb'`) y vaciado forzado a disco (`os.fsync`).
  - Verificación de integridad mediante recálculo de hash SHA-256 del temporal comparado con el origen.
  - Si el hash coincide: renombrado atómico con `os.rename` al nombre definitivo tras verificar ausencia de colisión.
  - Si el hash no coincide o la copia falla: reubicación preventiva del temporal a `<raiz_pendrive>/_a_revisar/copias_fallidas/<ruta relativa>` con `os.rename`, sin eliminarlo jamás.
  - Resolución no destructiva de colisiones: si ya existe un archivo idéntico (mismo hash), se omite la copia marcándolo como "ya estaba"; si existe uno distinto, se genera un sufijo numérico correlativo sin pisar.
  - Preservación del original: tras verificar la integridad de la copia en el pendrive, el archivo original en `~/Descargas/_lucie` se reubica con `os.rename` hacia `~/Descargas/_lucie/_enviados/<ruta relativa>` dentro del mismo sistema de archivos. Prohibición total de borrado.
- **Mecanismo de Deshacer Envío**:
  - Reversión por escena u operación individual: mueve la copia del pendrive a `<raiz_pendrive>/_a_revisar/envios_deshechos/<ruta relativa>` y restaura el archivo original desde `_enviados` a su ubicación previa con `os.rename`.
  - Negativa estricta ante colisiones: rechaza la reversión con mensaje explicativo si la ruta original previa ya se encuentra ocupada o si falta alguno de los componentes.
- **Actualización de base de datos SQLite y bitácoras**:
  - Ampliación del esquema para registrar el estado `"en_pendrive"` con hash, ruta destino en pendrive y marca de tiempo.
  - Asentamiento auditable de cada envío y reversión en `bitacora_envio.jsonl`.
- **Integración con panel web existente (`127.0.0.1:8766`)**:
  - Nueva pestaña "Envío al pendrive" en el panel web local, protegida con la misma verificación de encabezado `Host` local y token anti-CSRF `X-CSRF-Token`.
  - Visualización del estado del pendrive (montaje, espacio libre, advertencias de solo lectura).
  - Selector de personaje y escena clasificada con lista de archivos listos para transferir.
  - Modal de simulación previa detallada y confirmación explícita escena por escena.
- **Protección y filtros en bandeja e inventario**:
  - Actualización de los módulos existentes para ignorar de forma estricta el directorio `_enviados` y los archivos con extensión `.parcial`.
  - Actualización de `.gitignore` para omitir bitácoras y cachés de envío.
  - Verificación permanente de 0 violaciones en el analizador estático AST anti-borrado.

## Capabilities

### New Capabilities
- `envio-pendrive`: Transferencia segura y verificada de escenas clasificadas desde `~/Descargas/_lucie` hacia el pendrive, incluyendo pre-chequeos de punto de montaje y modo de solo lectura, copia atómica verificada por hash sin borrado, preservación en `_enviados`, reversibilidad a `envios_deshechos` e integración en el panel web local.

### Modified Capabilities
<!-- No requirement changes to existing capabilities; existing bandeja and inventario filters receive additions without modifying their base contract. -->

## Impact

- **Código fuente**:
  - Nuevo módulo `envio_pendrive.py` o integración modular desacoplada en el servidor de `bandeja_descargas.py`.
  - Actualización de `GestorBaseDatosBandeja` para soportar estados y consultas `"en_pendrive"`.
  - Actualización de filtros en `FiltroListaBlanca` e inventario para ignorar `_enviados` y `*.parcial`.
  - Adición de endpoints seguros en el servidor HTTP: `/api/envio/estado-pendrive`, `/api/envio/escenas-disponibles`, `/api/envio/simular`, `/api/envio/ejecutar`, `/api/envio/deshacer`.
  - Nueva pestaña en la SPA embebida de `bandeja_descargas.py`.
- **Configuración y sistema**:
  - Creación de `config_envio.json`.
  - Actualización de `.gitignore`.
- **Pruebas y Auditoría**:
  - Nueva suite `test_envio_pendrive.py` con pruebas unitarias sobre entornos simulados en `/tmp`.
  - Verificación AST anti-borrado en `seguridad_anti_borrado.py`.
