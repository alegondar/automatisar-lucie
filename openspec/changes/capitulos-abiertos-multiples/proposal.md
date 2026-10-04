# Proposal: Capítulos Abiertos Múltiples y Gestión de Foco

## Why

Actualmente el sistema restringe el flujo de trabajo a un único capítulo activo mediante un índice único en SQLite (`idx_capitulo_unico_activo` en `bandeja_capitulos` WHERE `estado='activo'`). En la práctica de producción de contenidos, el usuario trabaja simultáneamente en múltiples historias y personajes (Lucie, Roli, Mailen) y requiere tener varios capítulos abiertos a la vez sin que se cierren unos a otros. Además, para mantener la automatización predecible, exactamente uno (o ninguno) de los capítulos abiertos debe estar "en foco" para recibir la asignación automática de nuevas descargas, mientras los restantes capítulos abiertos permanecen disponibles para asignación manual y gestión granular.

## What Changes

- **Modelo de datos de capítulos**:
  - El estado `'activo'` pasa a significar "abierto" (pueden coexistir múltiples capítulos en estado `'activo'`).
  - Se agrega la columna `en_foco INTEGER DEFAULT 0` a `bandeja_capitulos`.
  - Migración segura en SQLite: se elimina el índice único `idx_capitulo_unico_activo` y se crea un índice parcial único `idx_capitulo_en_foco ON bandeja_capitulos(en_foco) WHERE en_foco = 1`. Si ya existe un capítulo activo, se migra con `en_foco = 1`. No se recrea la tabla ni se modifica el `CHECK(estado IN ('activo', 'cerrado'))`.
- **Empezar capítulo**:
  - Ya no falla si existen otros capítulos abiertos.
  - El nuevo capítulo se abre y pasa a estar `en_foco = 1`, quitando el foco del anterior (que permanece abierto con `en_foco = 0`).
  - Crea inmediatamente su carpeta física `~/Descargas/_lucie/<personaje>/<nombre>/` (respetando las reglas existentes) y registra su `fecha_inicio`.
- **Asignación automática por foco (`VigilanteBandeja.escanear`)**:
  - El material entrante se asigna automáticamente **únicamente** al capítulo que esté `en_foco = 1`, usando como corte temporal su `fecha_inicio`.
  - La asignación es estable (se fija al momento de la detección y no cambia automáticamente si cambia el foco posterior).
  - Si ningún capítulo está en foco, rige el modo respaldo por alias al inicio o sin identificar.
- **Acción "Poner en foco"**:
  - Nueva transacción atómica en `GestorBaseDatosBandeja` que desmarca el foco actual y asigna `en_foco = 1` al capítulo indicado. No altera archivos ya asignados.
- **Asignación manual a capítulos abiertos sin foco**:
  - Los capítulos abiertos sin foco pueden recibir archivos cuando el usuario los seleccione manualmente en el lote.
  - Pasan por la simulación previa obligatoria y se contabilizan en su balance y `archivos_movidos`.
- **Desplegable de Escena en Lotes**:
  - Lista como primera opción preseleccionada `[Capítulo en foco] <nombre>`.
  - Luego lista `[Capítulo abierto] <personaje>/<nombre>` por cada otro capítulo abierto.
  - Luego mantiene `+ Crear nueva escena...`, carpetas en Descargas y carpetas existentes en destino sin duplicar ninguna que ya corresponda a un capítulo abierto.
- **Banner superior**:
  - Muestra el capítulo en foco con su balance y botones "Terminar capítulo" y "Descartar capítulo".
  - Si hay otros capítulos abiertos, muestra un enlace/botón `+N capítulos abiertos` que abre la nueva pestaña.
  - Si no hay capítulo en foco pero hay abiertos, muestra el aviso `"Ningún capítulo en foco"` con acceso directo a la pestaña.
- **Nueva pestaña "Capítulos Abiertos"**:
  - Pestaña en la barra de navegación (junto a "Capítulos Cerrados") con conteo en el rótulo `Capítulos Abiertos (N)`.
  - Tabla con: Personaje, Nombre, Fecha de inicio, Archivos movidos, Archivos pendientes, Indicador de foco (`⭐ En foco`), y botones de acción por fila: `Poner en foco`, `Terminar` y `Descartar`.
- **Terminar capítulo por ID**:
  - Se puede terminar cualquier capítulo abierto pasando su ID.
  - Si se termina el capítulo en foco, el foco queda vacío (no se traslada automáticamente a otro).
- **Reabrir capítulo**:
  - Reabre sin cerrar los que ya estén abiertos. Si no hay capítulo en foco, toma el foco automáticamente; si ya hay uno en foco, queda abierto sin foco.
- **Descarte de capítulos por ID**:
  - El modal y la acción de descarte funcionan por ID para cualquier capítulo abierto o cerrado. Si estaba en foco, el foco queda vacío.
- **Alerta de capítulo olvidado (>12h)**:
  - Se evalúa por capítulo; la alerta del banner principal se muestra solo para el capítulo en foco. Para los demás, se muestra su última actividad en la pestaña "Capítulos Abiertos".
- **API HTTP**:
  - Endpoints existentes aceptan parámetro `id` explícito cuando corresponda.
  - Nuevos endpoints: `GET /api/capitulos/abiertos` y `POST /api/capitulos/en-foco` (con payload JSON `{"id": <id>}`).
  - `/api/capitulos/estado` retorna el capítulo en foco (`capitulo_foco`), la lista de capítulos abiertos (`capitulos_abiertos`) y `cantidad_abiertos`.
  - Todo POST valida token anti-CSRF, cabeceras Host y Content-Type JSON.

## Capabilities

### New Capabilities
- `capitulos-abiertos-multiples`: Permite coexistencia de múltiples capítulos abiertos, gestión atómica del capítulo en foco para la ingesta automática, asignación manual sin duplicación de escenas y visualización dedicada en pestaña de Capítulos Abiertos.

### Modified Capabilities
<!-- No requirement changes to existing specs as this is a new capability in the project -->

## Impact

- **Código**:
  - `bandeja_descargas.py`: Métodos de `GestorBaseDatosBandeja` (`migrar_bd`, `empezar_capitulo`, `terminar_capitulo`, `reabrir_capitulo`, `poner_capitulo_en_foco`, `obtener_capitulo_en_foco`, `listar_capitulos_abiertos`), lógica de escaneo en `VigilanteBandeja`, simulación y descarte en `GestorMovimientosBandeja`, handlers HTTP (`/api/capitulos/abiertos`, `/api/capitulos/en-foco`, etc.) y UI frontend (HTML, estilos, pestañas, modales, JS de renderizado de lotes y capítulos).
- **Seguridad y Reglas de Oro**:
  - Sin primitivas prohibidas de borrado o sobreescritura (test AST intacto con 0 infracciones).
  - Bitácora `.jsonl` y reversibilidad garantizadas.
- **Pruebas**:
  - `test_bandeja_descargas.py`: Nuevos casos de prueba unitarios e integración en clase `TestCapitulosAbiertosMultiples`.
