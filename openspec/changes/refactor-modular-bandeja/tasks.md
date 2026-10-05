# Tasks: refactor-modular-bandeja

## 1. Línea base y auditoría AST dinámica

- [x] 1.1 Ejecutar la suite completa, verificar 161 tests pasando y almacenar respuestas de referencia (*golden*) para `GET /`, `/api/estado-version`, `/api/capitulos/estado`, `/api/pendrive/estado` y `/api/lotes`
- [x] 1.2 Implementar en `seguridad_anti_borrado.py` la función `descubrir_archivos_operativos` que identifique automáticamente todos los `.py` en la raíz (no tests) y en el paquete `bandeja/`
- [x] 1.3 Agregar un test unitario en `test_bandeja_descargas.py` / `test_plan_limpieza.py` que falle si se detecta cualquier archivo `.py` operativo fuera del conjunto auditado
- [x] 1.4 Ejecutar auditoría estática AST verificando 0 infracciones en todo el proyecto y confirmar que los 161 tests pasen al 100%

## 2. Módulos base de plataforma y configuración

- [x] 2.1 Extraer a `bandeja/plataforma.py` la capa del sistema operativo (puntos de montaje, tipo de sistema de archivos `/proc/mounts`, espacio libre, notificaciones de escritorio y stubs para Windows); verificar suite completa y AST
- [x] 2.2 Extraer a `bandeja/config.py` la clase `ConfiguracionBandeja`, rutas por defecto y constantes operativas; verificar suite completa y AST

## 3. Módulos de persistencia, clasificación y agrupación

- [x] 3.1 Extraer a `bandeja/db.py` la clase `GestorBaseDatosBandeja`, esquemas de tablas SQLite y migraciones; verificar suite completa y AST
- [ ] 3.2 Extraer a `bandeja/clasificacion.py` las clases `FiltroListaBlanca`, `ValidadorEscenas` y resolución de alias; verificar suite completa y AST
- [ ] 3.3 Extraer a `bandeja/lotes.py` la clase `AgrupadorLotes`, `obtener_fecha_llegada` y utilidades de fecha; verificar suite completa y AST

## 4. Módulos de ciclo de vida, movimientos y pendrive

- [ ] 4.1 Extraer a `bandeja/capitulos.py` la lógica de ciclo de vida de capítulos, balance de medios, capítulos olvidados y descarte; verificar suite completa y AST
- [ ] 4.2 Extraer a `bandeja/movimientos.py` la clase `GestorMovimientosBandeja`, simulación HTML, renombrado atómico y reversión; verificar suite completa y AST
- [ ] 4.3 Extraer a `bandeja/pendrive.py` la detección de marcador `.lucie_pendrive.json`, vinculación, plan de envío seguro con `.part`, manifiesto append-only y deshacer envío; verificar suite completa y AST

## 5. Vigilante en segundo plano, frontend desacoplado y servidor HTTP

- [ ] 5.1 Extraer a `bandeja/vigilante.py` la clase `VigilanteBandeja`, escaneo periódico de descargas y banner reactivo; verificar suite completa y AST
- [ ] 5.2 Extraer los activos del frontend SPA a `bandeja/web/panel.html`, `bandeja/web/panel.css` y `bandeja/web/panel.js`, eliminando la plantilla embebida del monolito
- [ ] 5.3 Extraer a `bandeja/servidor.py` la clase `HandlerServidorBandeja` y `crear_servidor`, sirviendo activos estáticos exclusivamente mediante lista blanca estricta con inyección de token CSRF
- [ ] 5.4 Actualizar la prueba de Node.js en `test_bandeja_descargas.py` para validar los archivos estáticos nuevos de `bandeja/web/` manteniendo idénticas todas las aserciones de UI y DOM; verificar suite completa y AST

## 6. Fachada de compatibilidad e integración final

- [ ] 6.1 Crear `bandeja/__init__.py` exportando la interfaz pública completa del paquete
- [ ] 6.2 Convertir `bandeja_descargas.py` en un punto de entrada ligero compatible que re-exporta los símbolos públicos e invoca `main()`; verificar ejecución directa vía CLI
- [ ] 6.3 Ajustar rutas de `mock.patch` en `test_bandeja_descargas.py` y `test_envio_pendrive.py` que requieran actualización hacia los nuevos submódulos, sin debilitar ninguna aserción
- [ ] 6.4 Validar que ningún archivo `.py` en `bandeja/` supere ~1.200 líneas de código, comprobar equivalencia con las respuestas *golden*, verificar 100% de la suite de tests (>= 161 tests) y confirmar 0 infracciones en la auditoría AST
