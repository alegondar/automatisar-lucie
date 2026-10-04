# Tasks

## 1. Base de Datos y Configuración

- [x] 1.1 Agregar `horas_alerta_capitulo_olvidado: 12` en `config_bandeja.json` y verificar su lectura y valor de respaldo en `bandeja_descargas.py`.
- [x] 1.2 Implementar la tabla `bandeja_capitulos` y métodos de ciclo de vida (`empezar_capitulo`, `obtener_capitulo_activo`, `terminar_capitulo`, `reabrir_capitulo`, `listar_capitulos_cerrados`, `posponer_alerta_capitulo`) en `GestorBaseDatosBandeja`, verificando mediante tests unitarios la unicidad de capítulo activo y la persistencia SQLite.

## 2. Detección y Canalización de Archivos

- [x] 2.1 Conectar la detección de candidatos entrantes con el capítulo activo en `GestorBaseDatosBandeja.registrar_archivo`, asignando siempre el personaje y nombre del capítulo activo sin importar el alias en el nombre del archivo, verificando con pruebas unitarias.
- [x] 2.2 Implementar el cómputo de balance (archivos pendientes en Descargas vs. archivos ya movidos) para el capítulo activo y verificar con pruebas unitarias.

## 3. Endpoints API REST y Validaciones de Seguridad

- [x] 3.1 Implementar endpoints `/api/capitulos/empezar`, `/api/capitulos/estado`, `/api/capitulos/terminar`, `/api/capitulos/reabrir`, `/api/capitulos/cerrados` y `/api/capitulos/posponer_alerta` con validación de token anti-CSRF, verificación de sanitización de nombres y manejo de errores HTTP (400, 403, 409). Verificar con tests de integración HTTP en `/tmp`.
- [x] 3.2 Integrar la opción "Mover pendientes y terminar" con la simulación previa obligatoria y registrar el cierre del capítulo tras el traslado, y verificar que "Terminar sin mover" cierra el capítulo dejando los archivos intactos en Descargas.

## 4. Interfaz Web (SPA)

- [x] 4.1 Implementar controles superiores para "Empezar capítulo" (selector de personaje, input de nombre de capítulo y botón de inicio) visibles cuando no hay capítulo activo.
- [x] 4.2 Implementar el banner superior permanente "Capítulo activo: <personaje>/<capítulo>" con botón "Terminar capítulo" y el modal de terminación con el balance ("N archivos pendientes, M ya movidos") ofreciendo "Mover pendientes y terminar" y "Terminar sin mover".
- [x] 4.3 Implementar el aviso de capítulo olvidado cuando la antigüedad supere el límite configurado (>12h) con botones "Seguir" y "Terminar".
- [x] 4.4 Implementar el visor/pestaña de capítulos cerrados con lista detallada y botón "Reabrir" para reactivar un capítulo histórico.

## 5. Pruebas y Validación de Reglas de Oro

- [x] 5.1 Test unitario: terminar capítulo cierra la asignación y los archivos posteriores no se le asignan.
- [x] 5.2 Test unitario: reabrir un capítulo cerrado permite asignar de nuevo los archivos posteriores al capítulo.
- [x] 5.3 Test unitario: el aviso de capítulo olvidado aparece a las 12 horas evaluado con reloj simulado.
- [x] 5.4 Test unitario: el resumen y cómputo de pendientes y movidos es exacto.
- [x] 5.5 Test unitario: un capítulo de personaje "roli" recibe también un archivo candidato con prefijo "lucie...".
- [x] 5.6 Ejecutar suite completa de tests unitarios e integración en `/tmp` y verificar el test estático AST anti-borrado asegurando 0 violaciones a las Reglas de Oro.
