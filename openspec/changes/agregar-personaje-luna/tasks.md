# Tasks

## 1. Catálogo, clasificación y capítulos

- [x] 1.1 Incorporar Luna en aliases y respaldos de clasificación/movimientos; probar prefijos de archivos/carpetas, nombres con varios personajes, nombre base y rechazo de personaje desconocido en temporales.
- [x] 1.2 Admitir Luna en la lista API, inicio de capítulos y descubrimiento de escenas de sala de espera; verificar creación, foco, cierre y reapertura por API con DB temporal y conservar las pruebas existentes.
- [x] 1.3 Añadir Luna a todos los selectores de panel.html y a la identificación visual del catálogo; verificar con parser HTML que Empezar capítulo y clasificación manual incluyan `value="luna"`, y documentar la protagonista en README.md.

## 2. Guardado, edición y publicación

- [x] 2.1 Añadir Luna al organizador mensual y verificar un capítulo con video, imagen y MP3: plan, envío, rutas categoría/luna/mes/capítulo, hashes y Deshacer exclusivamente en temporales.
- [x] 2.2 Admitir Luna en reconocimiento de publicación por carpeta/sesión/prefijo, resguardo explícito de exports y selectores dinámicos de panel.js/wifi.js; verificar filtros, asignación de numéricos y revisión invalidada al cambiar personaje, conservando Lucie/Roli/Mailen.
- [x] 2.3 Probar una edición de Luna hasta Ya editados y su export titulado hasta Sin publicar; verificar recepción HTTP temporal, archivo en Publicados y Deshacer con integridad y colisiones preservadas. Documentar rutas y flujo en docs/publicacion-wifi.md.

## 3. Integración y entrega

- [x] 3.1 Ejecutar suite Python hermética y regresiones JS, comprobar sintaxis y auditorías anti-borrado/repositorio; cerrar bandeja real antes de suite y registrar conteo de manifiesto antes/después si está montado, sin otras lecturas reales durante pruebas.
- [x] 3.2 Comprobar en navegador temporal/API sintética los selectores de Luna, creación y filtros, sin operaciones sobre material real; registrar validación y límites de SO en ESTADO_ACTUAL.md y revisar el diff sin incluir notas locales preexistentes.
- [x] 3.3 Con la autorización explícita de publicación para este lote, hacer commit y push de archivos seleccionados en feat/lucie-recibir y verificar SHA remoto; si no se autoriza, conservar cambios locales y documentarlo.
