# Tasks: lista-envio-pendrive-por-carpetas

## 1. Backend: Escaneo recursivo seguro, tipificación y endpoint desacoplado

- [x] 1.1 Implementar `escanear_sala_espera_carpetas` en `bandeja/pendrive.py` usando `os.walk(..., followlinks=False)` con tope de 6 niveles, excluyendo `_enviados`, `_revertidos`, `_descartados` y `_a_revisar`, computando fotos, videos, archivos no multimedia, peso total y fecha más reciente sin descartar carpetas que solo tengan archivos en subcarpetas; verificar con pruebas unitarias
- [x] 1.2 Implementar la clasificación de cada carpeta cruzando personaje y nombre con `bandeja_capitulos` (`Capítulo en foco`, `Capítulo abierto`, `Capítulo cerrado`, `Escena suelta`, `Carpeta heredada`); verificar con pruebas unitarias
- [x] 1.3 Crear el endpoint `GET /api/pendrive/carpetas` en `bandeja/servidor.py` para devolver exclusivamente la lista de carpetas locales de la sala de espera sin interactuar con el pendrive físico; verificar con pruebas unitarias
- [x] 1.4 Reflejar claramente los cuatro estados de la unidad física en la respuesta de `obtener_estado_pendrive` y `GET /api/pendrive/estado`: sin unidad, unidad conectada sin vincular (con datos técnicos completos), conectado y vinculado, y sin respuesta; verificar con pruebas unitarias

## 2. Backend: Selección múltiple heterogénea y plan de envío unificado

- [x] 2.1 Actualizar `simular_envio_capitulos` y `ejecutar_envio_capitulos` en `bandeja/pendrive.py` para aceptar una lista de carpetas seleccionadas (`carpetas: ["lucie/carpeta1", ...]`), enrutando archivos sueltos en raíz a `videos/` o `fotos/` según corresponda y excluyendo archivos no multimedia con aviso; verificar con pruebas unitarias
- [x] 2.2 Integrar el cotejo con el manifiesto del pendrive para indicar archivos ya enviados (`sha256`) frente a pendientes sin bloquear el servidor durante el sondeo; verificar con pruebas unitarias
- [x] 2.3 Actualizar los manejadores `/api/pendrive/envio-simular` y `/api/pendrive/envio` en `bandeja/servidor.py` para validar y procesar la lista consolidada de carpetas; verificar con pruebas unitarias

## 3. Frontend: Tabla enriquecida, estados de unidad, selección masiva y vista previa

- [x] 3.1 Actualizar `bandeja/web/panel.html` y `bandeja/web/panel.css` con la nueva sección de carpetas de sala de espera: tabla responsive con columnas (selección, personaje, carpeta, tipo, archivos/peso, enviados/pendientes, acciones), badges de tipo, desplegables de archivos y estilos para unidad candidata sin vincular
- [x] 3.2 Implementar en `bandeja/web/panel.js` el consumo independiente de `GET /api/pendrive/carpetas` y `GET /api/pendrive/estado`, con botones globales "Seleccionar todas", "Ninguna", contador "Enviar seleccionadas (N)" y botón individual "Enviar esta carpeta"
- [x] 3.3 Implementar el desplegable "Ver archivos" por fila en `bandeja/web/panel.js` con lista de archivos (nombre, tamaño, tipo) y llamada al visor lightbox interactivo existente (`abrirVisorMedia`)
- [x] 3.4 Implementar en `bandeja/web/panel.js` la persistencia de las selecciones del usuario (`carpetasPendriveSeleccionadas`) a través de los ciclos de refresco automático
- [x] 3.5 Gestionar en `bandeja/web/panel.js` la inhabilitación explicativa de los botones de envío cuando no hay pendrive vinculado y la visualización destacada de la tarjeta de unidad conectada sin vincular

## 4. Pruebas unitarias, suite completa y auditoría AST anti-borrado

- [x] 4.1 Añadir en `test_bandeja_descargas.py` la suite completa de pruebas unitarias cubriendo carpetas en raíz y subcarpetas, carpetas heredadas y vacías, listado sin pendrive ni base, exclusión de carpetas del sistema, inhabilitación sin pendrive, simulación unificada de lote y distinción de unidad
- [x] 4.2 Ejecutar `python3 seguridad_anti_borrado.py` verificando 0 infracciones en todos los módulos operativos y correr la suite completa con 100% de tests en verde
