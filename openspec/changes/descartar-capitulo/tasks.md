# Tasks: Descartar Capítulo Moviéndolo a `_descartados` con Deshacer Reversible

- [x] 1. Migración y Modelo de Datos SQLite
  - [x] 1.1 Implementar migración segura en `_inicializar_db` para agregar `descartado` y `fecha_descartado` a `bandeja_capitulos`.
  - [x] 1.2 Actualizar `listar_capitulos_cerrados()` para excluir capítulos con `descartado = 1`.
  - [x] 1.3 Implementar `listar_capitulos_descartados()` y `marcar_capitulo_descartado()`.
  - [x] 1.4 Actualizar `bandeja_archivos` (rutas y estado) al descartar y al deshacer.

- [x] 2. Lógica de Descarte, Confinamiento y Bitácora en GestorMovimientosBandeja
  - [x] 2.1 Implementar `_validar_confinamiento_destino_base()` para asegurar rutas dentro de `~/Descargas/_lucie` y rechazar symlinks.
  - [x] 2.2 Implementar `simular_descartar_capitulo()` con conteo, peso, detección de carpetas vacías/inexistentes y resolución de colisiones con sufijo ` (1)`.
  - [x] 2.3 Implementar `ejecutar_descartar_capitulo()` con validación de confirmación de nombre, `os.rename` atómico de la carpeta completa y registro en `bitacora_bandeja.jsonl`.
  - [x] 2.4 Extender `deshacer_operacion()` para revertir eventos `descartar_capitulo` restaurando la carpeta si el origen está libre (negándose si está ocupado).
  - [x] 2.5 Actualizar `obtener_historial()` para representar adecuadamente las operaciones de descarte en la bitácora.

- [x] 3. Endpoints REST y Protección en Servidor HTTP
  - [x] 3.1 Implementar `POST /api/capitulos/descartar-simular` con validación de seguridad (Host, Content-Type, CSRF).
  - [x] 3.2 Implementar `POST /api/capitulos/descartar` con verificación de confirmación y cierre del capítulo activo si corresponde.
  - [x] 3.3 Implementar `GET /api/capitulos/descartados`.
  - [x] 3.4 Asegurar que `_descartados` nunca sea leída como escena en `escanear()` ni en `ValidadorEscenas`.

- [x] 4. Interfaz de Usuario Web
  - [x] 4.1 Añadir botón "Descartar capítulo" en el banner del capítulo activo y botón "Descartar" en la lista de Capítulos Cerrados.
  - [x] 4.2 Crear modal de confirmación con origen, destino, conteo, peso, aviso anti-borrado y campo de tipeo de nombre exacto.
  - [x] 4.3 Añadir pestaña y contenedor para "Capítulos Descartados".
  - [x] 4.4 Integrar aviso superior permanente con botón "Deshacer" y botón en la pestaña "Historial".

- [x] 5. Pruebas Unitarias y Auditoría AST
  - [x] 5.1 Crear clase de pruebas `TestDescartarCapitulo` en `test_bandeja_descargas.py`.
  - [x] 5.2 Probar simulación con conteo y peso sin mover nada.
  - [x] 5.3 Probar descarte moviendo carpeta completa y verificando hashes SHA-256 antes y después.
  - [x] 5.4 Probar rechazo con confirmación de nombre incorrecto.
  - [x] 5.5 Probar resolución de colisión en destino con sufijo numérico sin pisar.
  - [x] 5.6 Probar deshacer exitoso y rechazo terminante si el origen está ocupado.
  - [x] 5.7 Probar que capítulo activo descartado deja de asignar archivos nuevos.
  - [x] 5.8 Probar migración de la tabla `bandeja_capitulos` con datos previos.
  - [x] 5.9 Probar rechazo de endpoints sin token CSRF.
  - [x] 5.10 Probar rechazo de path traversal y symlinks salientes.
  - [x] 5.11 Ejecutar suite completa (`test_*.py`) con 100% de éxito.
  - [x] 5.12 Ejecutar auditoría AST anti-borrado verificando 0 infracciones.
