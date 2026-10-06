# Tasks: adopcion-del-proyecto-y-sqlite-wal

## Fases de Implementación

### Fase 1: Test de Regresión Inicial (Falla antes de corregir)
- [x] 1.1 Escribir test de regresión en `test_bandeja_descargas.py` (o suite dedicada) que monte un servidor HTTP real, cree un archivo sin alias con fecha anterior en la carpeta de descargas, verifique que aparece en "Sin Identificar", envíe `POST /api/clasificar-sin-identificar` (`es_proyecto: true`), y compruebe que el archivo debe aparecer en la sección principal de lotes detectados. <!-- id: 1.1 -->
- [x] 1.2 Ejecutar el test y confirmar que falla exactamente con la conducta reportada (el archivo desaparece de todas partes). <!-- id: 1.2 -->
- [x] 1.3 Reportar causa raíz detallada al usuario con evidencia previa a la modificación del código de producción. <!-- id: 1.3 -->

### Fase 2: SQLite WAL y Concurrencia
- [x] 2.1 Configurar `PRAGMA journal_mode=WAL;` y `PRAGMA busy_timeout=5000;` en `bandeja/db.py` al establecer cada conexión. <!-- id: 2.1 -->
- [x] 2.2 Configurar `PRAGMA journal_mode=WAL;` y `PRAGMA busy_timeout=5000;` en `inventario_pendrive.py` (o cualquier caché SQLite asociada). <!-- id: 2.2 -->
- [x] 2.3 Implementar test de concurrencia que lea la base de datos desde un hilo/proceso externo mientras otro escribe repetidamente, asegurando cero errores de `database is locked`. <!-- id: 2.3 -->

### Fase 3: Adopción a Mano en Backend (DB, Vigilante, Servidor)
- [x] 3.1 Añadir métodos en `bandeja/db.py` para registrar adopción explícita (`adoptado_a_mano`) y para revertir decisión (`revertir_decision_sin_identificar`). <!-- id: 3.1 -->
- [x] 3.2 Modificar `bandeja/vigilante.py` para que los archivos clasificados como adoptados a mano tengan precedencia sobre `es_anterior`, ingresen en `candidatos_estables`, con `adoptado_a_mano=True`, sin personaje ni escena prefijados. <!-- id: 3.2 -->
- [x] 3.3 Implementar en `bandeja/servidor.py` el endpoint `POST /api/deshacer-clasificar-sin-identificar` y asegurar que `_version_token` del vigilante se actualice de inmediato tras clasificar o deshacer. <!-- id: 3.3 -->
- [x] 3.4 Verificar que el test de regresión de la Fase 1 pase satisfactoriamente. <!-- id: 3.4 -->

### Fase 4: Frontend (Feedback Inmediato, Toast con Deshacer, Insignia e Interfaz)
- [x] 4.1 En `bandeja/web/panel.js`, remover la fila de inmediato de "Sin Identificar" al presionar "Del Proyecto" o "Ignorar". <!-- id: 4.1 -->
- [x] 4.2 Crear componente o banner/toast con mensaje claro, enlace a "Lotes Detectados" y botón "Deshacer" funcional (que llama a `/api/deshacer-clasificar-sin-identificar` y restaura la fila). <!-- id: 4.2 -->
- [x] 4.3 Mostrar errores del servidor explícitamente en la UI con `mostrarError(msg)` cuando falle una petición. <!-- id: 4.3 -->
- [x] 4.4 Renderizar la insignia "Adoptado a mano" en la tarjeta/fila del lote en la sección principal de Lotes Detectados, con checkbox seleccionado, sin alias ni escena prefijada, y con el desplegable completo de escenas (incluyendo capítulo en foco). <!-- id: 4.4 -->
- [x] 4.5 Asegurar que los botones sigan respondiendo tras los refrescos incrementales periódicos. <!-- id: 4.5 -->

### Fase 5: Validación Integral y Finalización
- [x] 5.1 Ejecutar suite de pruebas completa (`pytest test_bandeja_descargas.py test_envio_pendrive.py`) logrando 100% de tests pasando. <!-- id: 5.1 -->
- [x] 5.2 Ejecutar `python3 seguridad_anti_borrado.py` verificando 0 infracciones detectadas. <!-- id: 5.2 -->
- [x] 5.3 Crear commit git con el mensaje obligatorio: `fix(bandeja): Del Proyecto adopta el archivo en lotes con aviso y deshacer; SQLite en WAL`. <!-- id: 5.3 -->
- [x] 5.4 Presentar resumen detallado de cambios y diff al usuario. <!-- id: 5.4 -->
