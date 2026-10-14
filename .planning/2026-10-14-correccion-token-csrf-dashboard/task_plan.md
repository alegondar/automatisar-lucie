# Corrección de token CSRF del dashboard

## Objetivo
Permitir iniciar capítulos tras reiniciar la bandeja con una pestaña abierta,
conservando CSRF/Host, confirmaciones, selección y ausencia de reenvíos automáticos.

## Fases
- Diagnóstico de token fijo en HTML y ocho POST directos de Edición/CapCut: complete.
- Implementación de renovación por HTML local antes de cada POST: complete.
- Regresión de token cambiado, fallo de renovación y sin reintentos; temporales: complete.
- CSRF: auditorías y evidencia de entrega: complete.
- Apertura de Chrome al iniciar Python y sin duplicarla desde BAT: complete.
- Validación del lote ampliado: complete. Commit/push autorizados: en ejecución.

## Next Step
Crear commit del lote revisado, subir y comprobar la referencia remota.

## Decisiones
La plantilla se lee al servirla; la corrección HTML/JS queda disponible sin
reiniciar el servidor. Obtener HTML sin caché, leer solo meta con DOMParser,
no ejecutar scripts ni insertar HTML; solicitudes solo al mismo origen.
Si falla renovación, no enviar el POST. No reintentar ninguna mutación.
Pruebas en temporales. No crear el capítulo real como fixture ni iniciar bandeja.

El usuario autorizó commit/push y pidió añadir Chrome automático al ejecutar
bandeja_descargas.py. La autorización incluye este lote ampliado. Chrome debe
abrirse también si la bandeja ya estaba activa, sin iniciar otros vigilantes;
si falta Chrome o el servidor no está listo, informar sin bloquear la bandeja.
