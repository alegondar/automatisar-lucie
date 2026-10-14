# Progreso — 2026-10-14

Diagnóstico terminado. Se preservan cambios publicados 76bbfa7 y la protección
CSRF del servidor. Corrección nueva todavía sin autorización de commit/push.

Corrección HTML/JS terminada: metadato de token, fetchConCsrf compartido por
apiFetch y ocho POST de Edición/CapCut. Sin cambios de seguridad del servidor.
Prueba Node/HTTP: token anterior 403, actual crea un capítulo en temporales una
sola vez; GET, cabeceras, renovación fallida y POST incierto sin reintentos.
Suite completa Kali/Python 3.13.12: 382 OK, cinco saltos Windows, 51.684 s.
Bandeja detenida con SIGINT antes de suite; manifiesto contado 285/285 estable.
Logs de suite y control en temporal del sistema; AST 0/25, JS/UI y auditorías OK.
Al finalizar ya había una bandeja activa en 8766: no se inició una segunda.
HTML/JS nuevos servidos comprobados en solo lectura. No se
creó capítulo real ni se enviaron/movieron archivos como fixture. Windows no
ejecutado. Requiere Ctrl+F5 del navegador. Nuevo lote pendiente de commit/push.

El intento de restablecer uso normal detectó puerto ocupado y se detuvo antes
de iniciar nada. La instancia existente sirve la corrección; no se duplicó.

Usuario autoriza commit/push y amplía lote con Chrome automático desde Python.
Fetch sin novedades. BAT actual abre Chrome antes del servidor y fija 8766;
se delegará en Python para evitar dos pestañas y respetar --puerto.

Chrome implementado en navegador.py y llamado desde main: espera HTTP del panel,
puerto efectivo, localización Linux/Windows, sin shell, modo --sin-navegador,
instancia existente sin nuevos vigilantes. BAT delega apertura para no duplicar.
Ocho tests nuevos con servidores temporales y Popen simulado; sin Chrome real
como fixture. Suite ampliada: 390 OK, cinco saltos Windows, 53.519 s; manifiesto
290/290 estable. AST 0/26; JS/UI y auditorías rastreados/nuevos/historial OK.
Bandeja detenida antes de suite y disponible para uso normal después. No se
atribuyen tests Windows nativos a los mocks. Commit/push del lote autorizados.
