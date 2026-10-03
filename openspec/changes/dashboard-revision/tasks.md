# Tasks

## 1. Capa de Datos y Métricas (`servidor_dashboard.py`)

- [ ] 1.1 Crear la clase `ProveedorDatosDashboard` para cargar `informe_pendrive.json`, `plan_limpieza.json` y conectar a la caché SQLite con URI de solo lectura `file:...mode=ro`, verificando su correcta inicialización con datos simulados en `/tmp`.
- [ ] 1.2 Implementar métodos para calcular métricas de resumen, agregación por carpeta de primer nivel (peso y categorías video/foto/audio/documento/otro) y comparación disjunta de carpetas `laroli`, verificando que retornen las estructuras esperadas mediante pruebas unitarias.
- [ ] 1.3 Implementar métodos para clasificar videos por personaje (`lucie`, `roli`, `mailen`, `sin clasificar`) y estado de producción ("videos sin editar", "videos ya editados", "videos completos", "videos sin publicar"), sumando la duración desde SQLite, verificando con pruebas unitarias.
- [ ] 1.4 Implementar métodos para filtrar duplicados (inter, intra, protegidas) y clasificar archivos sueltos (alias vs sin clasificar), verificando los resultados mediante pruebas unitarias.
- [ ] 1.5 Implementar el método `recargar()` para actualizar los datos en memoria sin escribir en disco, verificando que refleje cambios en los archivos JSON de prueba sin reiniciar el proceso.

## 2. Servidor HTTP de Solo Lectura (`servidor_dashboard.py`)

- [ ] 2.1 Implementar `DashboardHandler` con ruteo de endpoints GET (`/api/resumen`, `/api/carpetas`, `/api/personajes`, `/api/duplicados`, `/api/plan`, `/api/laroli-dif`, `/api/sueltos`, `/api/recargar`), verificando respuestas JSON con cabeceras `Cache-Control: no-cache`.
- [ ] 2.2 Implementar el rechazo estricto de métodos no-GET (`POST`, `PUT`, `DELETE`, `PATCH`) devolviendo código `405 Method Not Allowed`, verificando el comportamiento con peticiones HTTP simuladas.
- [ ] 2.3 Implementar la configuración CLI con `argparse` (`--puerto` / `-p` con defecto 8765, `--host` fijo en 127.0.0.1, rutas configurables a JSONs y SQLite) y arranque con `ThreadingHTTPServer`, verificando la vinculación correcta al socket local.

## 3. Frontend SPA Autocontenido y Tema Oscuro (`dashboard.html` / embebido)

- [ ] 3.1 Diseñar la estructura HTML de la SPA con tema oscuro (paleta oscura con buen contraste), estilos CSS embebidos, tipografía del sistema (cero CDNs) y el banner fijo superior permanente `"SOLO LECTURA: este panel no modifica nada"`.
- [ ] 3.2 Desarrollar el encabezado con el botón "Recargar datos" y la botonera de navegación entre las 7 vistas, verificando la alternancia visual entre pestañas.
- [ ] 3.3 Desarrollar las vistas 1 (Resumen con tarjetas de métricas) y 2 (Carpetas de 1er nivel con barras proporcionales por categoría de archivo), verificando la carga y pintado desde `/api/resumen` y `/api/carpetas`.
- [ ] 3.4 Desarrollar la vista 3 (Personajes y estado de producción con conteo y duración acumulada H:M:S) y la vista 6 (Diferencias exclusivas en `laroli` vs `videos1/laroli`), verificando el renderizado desde `/api/personajes` y `/api/laroli-dif`.
- [ ] 3.5 Desarrollar la vista 4 (Duplicados con filtros interactivos por tipo y tamaño) y la vista 7 (Archivos sueltos clasificados vs sin clasificar), verificando el filtrado dinámico en el navegador.
- [ ] 3.6 Desarrollar la vista 5 (Plan de limpieza con filtros por tipo, personaje y tamaño, origen -> destino y motivo) e integrar el checkbox "revisado" con persistencia en `localStorage`, verificando que conserve el estado tras recargar la página sin enviar peticiones de escritura al servidor.

## 4. Pruebas Unitarias, Seguridad AST y Validación

- [ ] 4.1 Crear `test_servidor_dashboard.py` con fixtures en `/tmp` verificando que todos los endpoints GET devuelvan datos válidos y respuestas HTTP 200 correctas.
- [ ] 4.2 Agregar en `test_servidor_dashboard.py` pruebas que envíen peticiones POST, PUT, DELETE y PATCH a las rutas y validen el retorno de código `405 Method Not Allowed`.
- [ ] 4.3 Integrar `servidor_dashboard.py` en la auditoría estática AST anti-borrado de `seguridad_anti_borrado.py`, verificando que mantenga 0 violaciones de las 11 primitivas prohibidas.
- [ ] 4.4 Ejecutar la suite completa de tests (`test_plan_limpieza.py`, `test_inventario.py`, `test_servidor_dashboard.py`) y verificar que todas las pruebas pasen al 100%.
