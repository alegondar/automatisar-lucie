# Tasks

## 1. Persistencia y Modelo de Datos SQLite

- [x] 1.1 Migrar esquema en `GestorBaseDatosBandeja._crear_tablas()`: agregar columna `en_foco INTEGER DEFAULT 0`, eliminar índice `idx_capitulo_unico_activo`, crear índice parcial único `idx_capitulo_en_foco ON bandeja_capitulos(en_foco) WHERE en_foco = 1`, y migrar capítulos activos existentes a `en_foco = 1`. Verificar creando BD de prueba y consultando índices con `PRAGMA index_list`.
- [x] 1.2 Implementar `GestorBaseDatosBandeja.poner_capitulo_en_foco(id_capitulo)` con transacción atómica que apague el foco previo y active el nuevo. Verificar intentando violar la unicidad de foco y comprobando que solo uno queda en foco.
- [x] 1.3 Actualizar `GestorBaseDatosBandeja.empezar_capitulo(...)` para que no falle si existen otros capítulos abiertos, asigne `en_foco = 1` al nuevo y apague el foco anterior en una sola transacción. Verificar abriendo dos capítulos sucesivos.
- [x] 1.4 Actualizar `GestorBaseDatosBandeja.terminar_capitulo(id_capitulo)` y `descartar` para aceptar ID explícito; si era el capítulo en foco, dejar el foco vacío (`en_foco = 0`). Verificar que terminar el que está en foco deja el foco vacío sin tocar los demás.
- [x] 1.5 Implementar `GestorBaseDatosBandeja.obtener_capitulo_en_foco()` y `GestorBaseDatosBandeja.listar_capitulos_abiertos()`. Verificar que retornan los registros correctos con su información de carpeta.

## 2. Ingesta Automática y Asignación de Lotes

- [x] 2.1 Actualizar `VigilanteBandeja.escanear()` para consultar `obtener_capitulo_en_foco()`, limitando la auto-asignación y corte de fecha exclusivamente al capítulo en foco. Si no hay capítulo en foco, aplicar modo respaldo por alias inicial. Verificar mediante escaneo con y sin foco.
- [x] 2.2 Actualizar `simular_movimiento_lote` para comparar el personaje del lote contra el capítulo en foco si existe, emitiendo advertencia clara en caso de discrepancia.
- [x] 2.3 Permitir en `simular_movimiento_lote` y `ejecutar_movimiento_lote` el envío manual a cualquier capítulo abierto secundario, actualizando el conteo de `archivos_movidos` del capítulo seleccionado. Verificar moviendo archivos a un capítulo sin foco.

## 3. Endpoints HTTP y Seguridad

- [x] 3.1 Implementar `GET /api/capitulos/abiertos` que retorne la lista completa de capítulos abiertos con sus balances e indicador de foco. Verificar con petición GET en test de servidor.
- [x] 3.2 Implementar `POST /api/capitulos/en-foco` con validación estricta de token anti-CSRF, cabecera `Host` autorizada y `Content-Type: application/json`. Verificar con peticiones con y sin CSRF.
- [x] 3.3 Actualizar `GET /api/capitulos/estado` para devolver `capitulo_foco`, `capitulos_abiertos` y `cantidad_abiertos`. Verificar la respuesta JSON devuelta.
- [x] 3.4 Actualizar endpoints `/api/capitulos/terminar`, `/api/capitulos/reabrir` y `/api/capitulos/descartar` para aceptar `id` explícito en el body JSON. Verificar operando capítulos por ID.

## 4. Interfaz Web y Frontend

- [x] 4.1 Actualizar el desplegable de escenas en `renderLotes` para listar `[Capítulo en foco] <nombre>` (preseleccionado), seguido de `[Capítulo abierto] <personaje>/<nombre>` por cada otro capítulo abierto, omitiendo duplicados en `[Destino]`. Verificar inspeccionando el HTML generado.
- [x] 4.2 Actualizar el banner superior en `renderCapituloActivo` para reflejar el capítulo en foco, o mostrar el aviso `"Ningún capítulo en foco"` con enlace a la pestaña de abiertos, además del indicador `+N capítulos abiertos`.
- [x] 4.3 Agregar la pestaña "Capítulos Abiertos (N)" en la barra superior junto a "Capítulos Cerrados", con su tabla de listado, badge `⭐ En foco` y botones de acción por fila (`Poner en foco`, `Terminar`, `Descartar`).

## 5. Pruebas Unitarias y Auditoría AST

- [x] 5.1 Implementar la clase de pruebas `TestCapitulosAbiertosMultiples` en `test_bandeja_descargas.py` cubriendo migración, concurrencia de abiertos, unicidad de foco, ingesta restringida a foco, cambio de foco, envío manual a abierto secundario, cierre/descarte por ID y endpoints con CSRF.
- [x] 5.2 Ejecutar `python3 -m unittest test_bandeja_descargas.TestAuditoriaASTAntiBorrado` y verificar 0 infracciones de primitivas prohibidas.
- [x] 5.3 Ejecutar la suite completa `python3 -m unittest discover -s . -p "test_*.py"` y verificar 100% de tests aprobados.
