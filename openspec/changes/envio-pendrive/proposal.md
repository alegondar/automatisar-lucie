# Proposal

## Why

El flujo de trabajo actual organiza y clasifica material en la sala de espera local (`~/Descargas/_lucie/<personaje>/<capítulo>/fotos|videos`), pero carece de un mecanismo controlado, verificable y seguro para transferir capítulos terminados o en curso hacia el almacenamiento físico externo (pendrive). Esta propuesta incorpora un sistema integral de envío hacia una estructura completamente nueva y aislada dentro del pendrive (`LucieSinReglas`), garantizando la preservación absoluta de los archivos preexistentes del usuario, verificación de integridad criptográfica (SHA-256), registro append-only y reversibilidad completa sin borrado, en estricto cumplimiento de las 7 Reglas de Oro.

## What Changes

- **Marcador de identidad y detección multiplataforma**:
  - Detección de pendrives vinculados mediante el marcador de identidad `<pendrive>/.lucie_pendrive.json` (`{"id": "<uuid4>", "creado": "<fecha>", "version": 1}`).
  - Función aislada `detectar_pendrive()` con estrategia según sistema operativo (`os.name`), con soporte para Linux (`/media/<usuario>/*`, `/run/media/<usuario>/*`), preparación de mapeo para Windows (unidades A-Z) y soporte de rutas candidatas por configuración (`"rutas_candidatas_pendrive"`) para pruebas.
  - Bloqueo total de operaciones de envío si el pendrive no contiene un marcador válido.
- **Acción de vinculación de pendrive**:
  - Endpoint y flujo de vinculación con simulación previa obligatoria que detalla punto de montaje, sistema de archivos y espacio libre disponible.
  - Creación controlada del marcador `.lucie_pendrive.json` y la estructura base `LucieSinReglas/` (`videos sin editar`, `videos ya editados`, `videos completos`, `imagenes`, `.lucie`) exclusivamente tras confirmación explícita, sin sobrescribir marcadores existentes.
- **Estructura confinada en pendrive (`LucieSinReglas`)**:
  - Aislamiento total: todo lo que resida fuera de `LucieSinReglas/` se considera de solo lectura y nunca se toca. Confinamiento estricto mediante `os.path.realpath`.
  - Mapeo de rutas: videos de la sala de espera van a `LucieSinReglas/videos sin editar/<personaje>/<capítulo>/<archivo>` y fotos a `LucieSinReglas/imagenes/<personaje>/<capítulo>/<archivo>`.
  - Archivos sueltos no multimedia en la raíz del capítulo no se envían y generan advertencias en la simulación.
- **Plan de envío con simulación obligatoria (un solo plan por lote)**:
  - Simulación exhaustiva previa por capítulo o para "todos los pendientes de envío", detallando origen, destino relativo, tamaño en bytes y SHA-256.
  - Detección y bloqueo ante espacio insuficiente con margen de seguridad.
  - Inspección del sistema de archivos en `/proc/mounts`: si es FAT32/vfat, detección y bloqueo preventivo de archivos individuales que superen los 4 GiB.
  - Validación de colisiones case-insensitive y caracteres incompatibles.
  - Detección de archivos ya enviados (mismo SHA-256 en manifiesto se omiten) y marcado de conflictos (destino existente con hash distinto: se reporta conflicto y no se copia ni se sufija a ciegas).
  - Confirmación explícita en un solo clic ("Confirmar y enviar") para procesar el lote completo.
- **Copia segura con archivos temporales y verificación en dos fases**:
  - Copia en bloques de 1 MB hacia `<destino>.part` calculando SHA-256 al vuelo, vaciado a disco (`os.fsync`) y renombrado con `os.rename` únicamente tras verificar que el destino final no existe.
  - Verificación posterior releyendo el destino para certificar coincidencia de SHA-256.
  - En caso de falla o desconexión, el `.part` permanece visible e informado en el panel sin borrarse, deteniendo el envío subsiguiente.
- **Preservación de originales en `_enviados`**:
  - Únicamente tras confirmar la copia íntegra, el archivo original en la sala de espera se reubica con `os.rename` hacia `~/Descargas/_lucie/_enviados/<personaje>/<capítulo>/(fotos|videos)/<archivo>`.
  - Resolución no destructiva de colisiones en `_enviados` mediante sufijos numéricos.
  - Aislamiento estricto: `_enviados` nunca se ofrece como escena ni se lee como capítulo.
- **Manifiesto append-only en pendrive y bitácora local**:
  - Registro de transferencias en `<pendrive>/LucieSinReglas/.lucie/manifiesto.jsonl` abierto exclusivamente en modo append (`'a'`).
  - Asentamiento simultáneo en `bitacora_bandeja.jsonl` con el evento `"envio_pendrive"`.
- **Deshacer envíos sin borrado**:
  - Reversión que traslada la copia del pendrive a `<pendrive>/LucieSinReglas/_revertidos/<id_envio>/<ruta_relativa>` con `os.rename` y devuelve el original desde `_enviados/` a su ubicación previa en la sala de espera.
  - Si la ruta previa está ocupada, se rechaza la operación sin pisar ningún archivo.
  - Asentamiento de `"envio_revertido"` en el manifiesto del pendrive y en la bitácora local.
- **Detección automática en vigilante e interfaz de usuario**:
  - Sondeo periódico en `VigilanteBandeja` para detectar la conexión física del pendrive y mostrar un banner interactivo con la cantidad de archivos y capítulos listos para enviar.
  - Pestaña "Pendrive" en el panel web con diagnóstico en tiempo real (estado, ID, filesystem, espacio libre), vinculación de unidades, listado de capítulos con botones de envío individual y masivo, historial de envíos con botón "Deshacer", y monitoreo de `.part` huérfanos.
  - Botón "Enviar al pendrive" en cada fila de capítulo (abiertos y cerrados) y en el banner del capítulo en foco (con advertencia si el capítulo sigue abierto).
- **Nuevos endpoints HTTP protegidos**:
  - `GET /api/pendrive/estado`
  - `POST /api/pendrive/vincular-simular`
  - `POST /api/pendrive/vincular`
  - `POST /api/pendrive/envio-simular`
  - `POST /api/pendrive/envio`
  - Extensión de `POST /api/deshacer` para soportar la reversión de envíos.
  - Protección estricta con token anti-CSRF, cabecera `Host` local y `Content-Type: application/json`.

## Capabilities

### New Capabilities

- `envio-pendrive`: Transferencia segura y verificada de capítulos clasificados a una estructura aislada en el pendrive (`LucieSinReglas`), con detección de identidad por marcador, simulación previa de lote, copia con `.part`, manifiesto append-only, preservación en `_enviados` y reversión sin borrado a `_revertidos`.

### Modified Capabilities

<!-- No requirement changes to existing capabilities; existing filters and scene validations are extended without altering existing requirements. -->

## Impact

- **Código fuente**:
  - `bandeja_descargas.py`: Incorporación de funciones de detección de pendrive, vinculación, simulación de envío, copia segura `.part`, manifiesto `.jsonl`, reversión de envíos, sondeo en `VigilanteBandeja`, endpoints HTTP `/api/pendrive/*`, y componentes de interfaz en la SPA.
  - `config_bandeja.json`: Parámetros `"carpeta_raiz_pendrive": "LucieSinReglas"` y `"rutas_candidatas_pendrive": []`.
  - `inventario_pendrive.py`: Reutilización de funciones de lectura de espacio, hashing y sanitización de rutas sin modificar su implementación interna.
- **Seguridad y Reglas de Oro**:
  - 0 infracciones en el análisis estático AST anti-borrado (`seguridad_anti_borrado.py`). Prohibición absoluta de `os.remove`, `os.unlink`, `os.rmdir`, `os.removedirs`, `Path.unlink`, `Path.rmdir`, `shutil.rmtree`, `shutil.move`, `os.replace`, `send2trash` y llamadas `rm` vía shell/subprocess.
- **Pruebas**:
  - `test_envio_pendrive.py`: Suite exhaustiva utilizando directorios temporales como pendrives simulados para validar vinculación, simulación, detección FAT32, copia segura, preservación de originales, manifiesto, reversión, confinamiento y seguridad en endpoints.
